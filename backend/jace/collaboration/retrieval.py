"""C4B.2: explicit, bounded, permissioned source collection for evidence review.

No autonomous search or writes. The only execution paths are Jace's already
registered, guarded read_web_page and read_workspace_file tools. Permission=ask
is not treated as permission=allow; interactive approval belongs to the agent
runtime and will be integrated in a later stage.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jace.auth.resource_ownership import require_or_claim_local
from jace.collaboration.evidence import (
    EvidenceReviewRequest, EvidenceReviewResponse, SourceReceipt,
    SuppliedExcerpt, run_evidence_review,
)
from jace.collaboration.review import CollaborationNotReady, CollaborationOutputError, _route_id
from jace.database import SessionLocal
from jace.tools import ensure_tools_registered
from jace.tools.base import ToolContext
from jace.tools.permissions import create_tool_audit, get_tool_permission, update_tool_audit
from jace.tools.registry import registry
from jace.tools.webtools import _UNTRUSTED_PREFIX, _UNTRUSTED_SUFFIX
from jace.web.security import normalise_public_url


class RetrievalNotAvailable(CollaborationNotReady):
    """Precondition/permission/configuration failure: not executed."""


class RetrievalFailed(CollaborationOutputError):
    """A retrieval or evidence parsing operation did not succeed."""


class RequestedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,48}$")
    kind: Literal["public_web", "workspace_file"]
    url: str | None = Field(default=None, max_length=2000)
    workspace_id: str | None = Field(default=None, min_length=36, max_length=36)
    path: str | None = Field(default=None, min_length=1, max_length=800)
    start_line: int = Field(default=1, ge=1, le=100000)
    max_lines: int = Field(default=120, ge=1, le=200)

    @model_validator(mode="after")
    def source_shape(self):
        if self.kind == "public_web":
            if not self.url or self.workspace_id or self.path or self.start_line != 1:
                raise ValueError("A public_web source requires only a URL, not workspace fields.")
            # This is only syntactic screening. The existing Jace read_web_page
            # tool performs the actual hostname/DNS/redirect checks.
            safe_url = normalise_public_url(self.url)
            host = urlsplit(safe_url).hostname or ""
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                pass  # DNS/IP checks still happen at tool execution.
            else:
                if not address.is_global:
                    raise ValueError("Local/private IP addresses cannot be retrieved.")
        else:
            if self.url or not self.workspace_id or not self.path:
                raise ValueError("A workspace_file source requires workspace_id and path, not URL.")
        return self


class RetrievalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=5, max_length=8000)
    sources: list[RequestedSource] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_sources(self):
        ids = [item.id for item in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("Requested source IDs must be unique.")
        return self


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _url_audit_identifier(url: str) -> dict[str, str]:
    # Do not persist URL query strings, fragments, credentials or full paths in
    # the audit; they may contain privacy-sensitive or signed tokens.
    parsed = urlsplit(url)
    return {"host": parsed.hostname or "", "url_sha256": _sha(url)}


def _tool_request(item: RequestedSource) -> tuple[str, dict]:
    if item.kind == "public_web":
        return "read_web_page", {"url": item.url, "max_chars": 6000}
    return "read_workspace_file", {
        "workspace_id": item.workspace_id, "path": item.path,
        "start_line": item.start_line, "max_lines": item.max_lines,
    }


def _decode_web(raw: str, item: RequestedSource) -> tuple[str, str, str | None, str | None]:
    # Existing web tool explicitly wraps untrusted JSON. No loose regex that
    # might parse attacker-supplied pseudo-JSON from an invalid tool response.
    if not raw.startswith(_UNTRUSTED_PREFIX) or not raw.endswith(_UNTRUSTED_SUFFIX):
        raise RetrievalFailed("Web tool response has unexpected provenance format.")
    data = json.loads(raw[len(_UNTRUSTED_PREFIX):-len(_UNTRUSTED_SUFFIX)])
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise RetrievalFailed("Web tool response is missing readable text.")
    locator = str(data.get("url") or "")
    if not locator:
        raise RetrievalFailed("Web tool response did not include a final source URL.")
    # Treat tool-returned URL as untrusted metadata, independently check its
    # permitted syntax; final DNS/network checks belong to the fetch tool.
    locator = normalise_public_url(locator)
    # External URLs sometimes contain signed or tracking query parameters.
    # Source receipts expose the public page path, not URL query secrets.
    parts = urlsplit(locator)
    locator = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    title = str(data.get("title") or "").strip()[:115]
    label = title or (urlsplit(locator).hostname or "Public webpage")
    return data["text"], label, locator, None


def _decode_workspace(raw: str, item: RequestedSource) -> tuple[str, str, str | None, str | None]:
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise RetrievalFailed("Workspace tool response is missing readable text.")
    # This locator is a reference to an already approved workspace; never a
    # model-controlled raw absolute path.
    reported = str(data.get("path") or "")
    if not reported or not str(data.get("workspace") or ""):
        raise RetrievalFailed("Workspace tool response is missing provenance fields.")
    locator = f"workspace:{item.workspace_id}/{reported}"
    file_sha = str(data.get("sha256") or "")
    if len(file_sha) != 64 or any(ch not in "0123456789abcdef" for ch in file_sha.lower()):
        raise RetrievalFailed("Workspace tool did not provide the full-file checksum.")
    return data["text"], f"{data['workspace']}:{reported}"[:120], locator, file_sha


def _preflight(request: RetrievalReviewRequest, *, gateway, privacy, config) -> None:
    if not (getattr(config, "collaboration_enabled", False)
            and getattr(config, "collaboration_evidence_enabled", False)
            and getattr(config, "collaboration_retrieval_enabled", False)):
        raise RetrievalNotAvailable("C4B.2 is disabled; all three collaboration switches must be enabled.")
    if not getattr(config, "tools_enabled", False):
        raise RetrievalNotAvailable("Jace tools are disabled.")
    if not getattr(privacy, "enabled", False) or not getattr(privacy, "cloud_egress_enabled", False):
        raise RetrievalNotAvailable("Protected cloud processing is disabled by privacy policy.")
    drafter, drafter_provider = _route_id(gateway, str(getattr(config, "collaboration_drafter_route", "")).strip())
    reviewer, reviewer_provider = _route_id(gateway, str(getattr(config, "collaboration_reviewer_route", "")).strip())
    if drafter_provider == reviewer_provider:
        raise RetrievalNotAvailable("Drafter and reviewer must use different cloud providers.")
    del drafter, reviewer
    privacy_decision = privacy.prepare_for_provider(
        request.model_dump(), provider_local=False,
        provider_supports_protected_cloud=True, requested_mode="protected_cloud",
    )
    if privacy_decision.require_local or privacy_decision.action not in {"raw_cloud", "protected_cloud"}:
        raise RetrievalNotAvailable("Cloud privacy policy blocked source review before retrieval.")
    if any(source.kind == "public_web" for source in request.sources) and not getattr(config, "web_enabled", False):
        raise RetrievalNotAvailable("The public web capability is disabled in Jace settings.")
    if any(source.kind == "workspace_file" for source in request.sources) and not getattr(config, "computer_enabled", False):
        raise RetrievalNotAvailable("Approved workspace reading is disabled in Jace settings.")


async def _source(item: RequestedSource, *, objective: str, actor, session) -> tuple[SuppliedExcerpt, SourceReceipt]:
    tool_name, arguments = _tool_request(item)
    definition = registry.get(tool_name)
    if definition is None or definition.risk != "read" or definition.capability_id is not None:
        raise RetrievalNotAvailable("A required approved read-only tool is unavailable.")
    configured = await get_tool_permission(session, tool_name)
    policy = definition.resolve_policy(arguments)
    if configured != "allow" or policy.minimum_permission != "allow":
        raise RetrievalNotAvailable(
            f"The {tool_name} tool must be explicitly set to Allow in Jace before this endpoint can use it. "
            "Ask and Deny remain blocked; there is no implicit approval."
        )
    if item.kind == "workspace_file":
        # Core's workspace_id is a protected actor-owned resource in server mode.
        await require_or_claim_local(
            session, resource_kind="workspace", resource_id=item.workspace_id,
            actor_id=actor.actor_id, client_id=actor.client_id,
            server_mode=actor.server_mode,
        )
    # The tool audit intentionally records a stable hash instead of raw URL
    # parameters or path contents. Actual request stays in an ephemeral dict.
    safe_args: dict = {"source_id": item.id, "source_kind": item.kind}
    if item.kind == "public_web":
        safe_args.update(_url_audit_identifier(item.url or ""))
    else:
        safe_args.update({"workspace_id": item.workspace_id,
                          "relative_path_sha256": _sha(item.path or "")})
    audit = await create_tool_audit(
        session, conversation_id=None, tool_name=tool_name,
        permission_mode="allow", configured_permission=configured,
        arguments=safe_args, actor_id=actor.actor_id, client_id=actor.client_id,
    )
    try:
        result = await definition.execute(arguments, ToolContext(
            session=session, conversation_id=None, user_message=objective,
            actor_id=actor.actor_id, client_id=actor.client_id,
        ))
        if item.kind == "public_web":
            raw_text, label, locator, full_sha = _decode_web(result.content, item)
        else:
            raw_text, label, locator, full_sha = _decode_workspace(result.content, item)
        snippet = raw_text[:4800].strip()
        if len(snippet) < 20:
            raise RetrievalFailed("Retrieved source has insufficient readable content.")
        excerpt = SuppliedExcerpt(id=item.id, label=label, content=snippet)
        receipt = SourceReceipt(
            source_id=item.id, label=label, sha256=_sha(snippet),
            provenance=("jace_public_web_read" if item.kind == "public_web"
                        else "jace_approved_workspace_read"),
            locator=locator,
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            retrieval_tool=tool_name, full_document_sha256=full_sha,
            excerpt_truncated=(len(raw_text) > len(snippet)),
        )
        await update_tool_audit(session, audit.id, status="completed",
                                result_preview=f"Source {item.id}: captured {len(snippet)} characters, sha256={receipt.sha256}",
                                completed=True)
        return excerpt, receipt
    except asyncio.CancelledError:
        await update_tool_audit(session, audit.id, status="cancelled", completed=True)
        raise
    except Exception as exc:
        # Never place raw exception text (including URLs or tool output) into
        # responses or persistent audit records.
        await update_tool_audit(session, audit.id, status="failed", error="Read-only source collection failed.", completed=True)
        raise RetrievalFailed(f"Source {item.id} could not be collected. No review was started.") from None


async def run_retrieval_review(request: RetrievalReviewRequest, *, actor, gateway,
                               privacy, config) -> EvidenceReviewResponse:
    """Retrieve all user-selected sources first; then run three guarded model calls.

    There are no model-directed source/tool requests, no auto-search, no writes,
    and no partial success result if any source read fails.
    """
    _preflight(request, gateway=gateway, privacy=privacy, config=config)
    ensure_tools_registered()
    timeout = max(20, min(300, int(getattr(config, "collaboration_retrieval_timeout_seconds", 150))))

    async def execute() -> EvidenceReviewResponse:
        collected: list[SuppliedExcerpt] = []
        receipts: list[SourceReceipt] = []
        async with SessionLocal() as session:
            # Permission for ALL sources checked before any tool is invoked,
            # ensuring no partial retrieval when the second tool is disabled.
            for item in request.sources:
                name, arguments = _tool_request(item)
                definition = registry.get(name)
                if definition is None or definition.risk != "read" or definition.capability_id is not None:
                    raise RetrievalNotAvailable("A required approved read-only tool is unavailable.")
                permission = await get_tool_permission(session, name)
                if permission != "allow" or definition.resolve_policy(arguments).minimum_permission != "allow":
                    raise RetrievalNotAvailable(f"{name} is not explicitly allowed; zero source tools were executed.")
                if item.kind == "workspace_file":
                    await require_or_claim_local(
                        session, resource_kind="workspace", resource_id=item.workspace_id,
                        actor_id=actor.actor_id, client_id=actor.client_id,
                        server_mode=actor.server_mode,
                    )
            for item in request.sources:
                excerpt, receipt = await _source(item, objective=request.objective, actor=actor, session=session)
                collected.append(excerpt)
                receipts.append(receipt)
        # C4B.1's policy evaluates original returned text; neither a model nor
        # this collector can override its local-only classification.
        review_request = EvidenceReviewRequest(objective=request.objective, evidence=collected)
        return await run_evidence_review(
            review_request, gateway=gateway, privacy=privacy, config=config,
            retrieved_receipts=receipts,
        )

    try:
        async with asyncio.timeout(timeout):
            return await execute()
    except TimeoutError:
        raise RetrievalFailed("C4B.2 timed out; no verified conclusion was produced.") from None
