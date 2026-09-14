from __future__ import annotations

# JACE_STEP4A4_RUNTIME_CAPABILITY_RESOLVER

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from jace.capabilities.registry import snapshot
from jace.config import settings


ResolutionStatus = Literal[
    "ready",
    "needs_access",
    "implementation_pending",
    "permission_denied",
    "connection_error",
    "disconnected",
    "connection_required",
    "ambiguous",
    "tools_disabled",
    "unsupported",
]


@dataclass(frozen=True)
class CapabilityNeed:
    capability_id: str
    reason: str
    preferred_provider: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityCandidate:
    capability_id: str
    provider_id: str
    connection_id: str | None
    account_hint: str | None
    state: str
    permission: str | None
    tool_name: str | None
    availability_reason: str | None
    missing_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityResolution:
    capability_id: str
    status: ResolutionStatus
    preferred_provider: str | None
    provider_id: str | None
    connection_id: str | None
    account_hint: str | None
    permission: str | None
    tool_name: str | None
    missing_scopes: tuple[str, ...] = ()
    candidates: tuple[CapabilityCandidate, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = [item.as_dict() for item in self.candidates]
        return payload


@dataclass(frozen=True)
class RuntimeCapabilityPlan:
    message: str
    needs: tuple[CapabilityNeed, ...]
    resolutions: tuple[CapabilityResolution, ...]
    tool_names: tuple[str, ...]
    tool_bindings: dict[str, dict[str, Any]]

    @classmethod
    def empty(cls, message: str = "") -> "RuntimeCapabilityPlan":
        return cls(
            message=message,
            needs=(),
            resolutions=(),
            tool_names=(),
            tool_bindings={},
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "needs": [item.as_dict() for item in self.needs],
            "resolutions": [item.as_dict() for item in self.resolutions],
            "tool_names": list(self.tool_names),
            "tool_bindings": self.tool_bindings,
        }

    def prompt_context(self) -> str:
        if not self.resolutions:
            return ""

        lines = [
            "EXTERNAL CAPABILITY RESOLUTION",
            (
                "The application has already resolved which connected external "
                "capabilities are available for this request. Treat these results "
                "as authoritative. Never claim that you read, searched, changed, "
                "sent, or created external data unless an executable tool was "
                "actually supplied and called."
            ),
        ]

        for resolution in self.resolutions:
            label = resolution.capability_id
            account = (
                f"{resolution.provider_id} / {resolution.account_hint}"
                if resolution.provider_id and resolution.account_hint
                else resolution.provider_id
                or "no selected account"
            )

            if resolution.status == "ready":
                lines.append(
                    f"- {label}: READY via {account}. "
                    "Use the supplied tool when the user's request requires it."
                )
                continue

            if resolution.status == "needs_access":
                scopes = ", ".join(resolution.missing_scopes) or "additional provider access"
                lines.append(
                    f"- {label}: NOT AVAILABLE via {account}. "
                    f"The connected account is missing provider authorization ({scopes}). "
                    "Do not pretend the external data was accessed."
                )
                continue

            if resolution.status == "implementation_pending":
                lines.append(
                    f"- {label}: NOT EXECUTABLE via {account}. "
                    "The account/provider access is configured, but Jace does not yet "
                    "have a runnable tool implementation for this capability."
                )
                continue

            if resolution.status == "permission_denied":
                lines.append(
                    f"- {label}: DENIED via {account}. "
                    "Jace's permission policy forbids this capability."
                )
                continue

            if resolution.status == "connection_error":
                lines.append(
                    f"- {label}: CONNECTION ERROR via {account}. "
                    "The account must be verified or reconnected before use."
                )
                continue

            if resolution.status == "disconnected":
                lines.append(
                    f"- {label}: DISCONNECTED via {account}. "
                    "The account must be connected again before use."
                )
                continue

            if resolution.status == "connection_required":
                lines.append(
                    f"- {label}: NO CONNECTED ACCOUNT. "
                    "A compatible service account must be connected first."
                )
                continue

            if resolution.status == "ambiguous":
                choices = ", ".join(
                    (
                        f"{candidate.provider_id}"
                        + (f" ({candidate.account_hint})" if candidate.account_hint else "")
                    )
                    for candidate in resolution.candidates
                    if candidate.connection_id
                )
                lines.append(
                    f"- {label}: MULTIPLE POSSIBLE ACCOUNTS"
                    + (f" ({choices})" if choices else "")
                    + ". Ask which account/provider to use rather than guessing."
                )
                continue

            if resolution.status == "tools_disabled":
                lines.append(
                    f"- {label}: TOOLS DISABLED. "
                    "Jace's global tool execution setting prevents this capability."
                )
                continue

            lines.append(
                f"- {label}: UNSUPPORTED for the currently configured providers."
            )

        lines.extend(
            [
                (
                    "If a capability is unavailable, explain the blocker briefly and "
                    "accurately. Do not imply that connecting an account alone grants "
                    "permissions which have not actually been authorized. NEVER INVENT AUTHORIZATION UI, "
                    "browser menus, session-only access buttons, token-vault state, or setup steps that "
                    "are not present in Jace. If provider access is missing, name the missing scope and "
                    "refer only to Jace Settings > Connections / the provider consent flow."
                ),
                "END EXTERNAL CAPABILITY RESOLUTION",
            ]
        )
        return "\n".join(lines)


_EMAIL_SEND = re.compile(
    r"\b(?:send|forward|send out)\b.{0,45}\b(?:email|e-mail|mail|message|gmail|outlook)\b"
    r"|\b(?:email|e-mail|mail|gmail|outlook)\b.{0,35}\b(?:send|forward)\b",
    re.IGNORECASE,
)
_EMAIL_DRAFT = re.compile(
    r"\b(?:draft|compose|write|prepare|reply to)\b.{0,45}\b(?:email|e-mail|mail|message|gmail|outlook)\b"
    r"|\b(?:email|e-mail|mail|gmail|outlook)\b.{0,35}\b(?:draft|compose|reply)\b",
    re.IGNORECASE,
)
_EMAIL_SEARCH = re.compile(
    r"\b(?:search|find|look for|locate|check|scan)\b.{0,50}\b(?:email|e-mail|mail|gmail|outlook|inbox|messages?)\b"
    r"|\b(?:email|e-mail|mail|gmail|outlook|inbox)\b.{0,50}\b(?:from|about|containing|search|find|check)\b",
    re.IGNORECASE,
)
_EMAIL_READ = re.compile(
    r"\b(?:read|open|show|summari[sz]e|review|check|latest|recent)\b.{0,45}\b(?:email|e-mail|mail|gmail|outlook|inbox|messages?)\b"
    r"|\b(?:what(?:'s| is)|anything|new)\b.{0,35}\b(?:in )?(?:my )?(?:email|mail|inbox)\b",
    re.IGNORECASE,
)
_CALENDAR_CREATE = re.compile(
    r"\b(?:create|add|schedule|book|make)\b.{0,45}\b(?:calendar )?(?:event|meeting|appointment)\b",
    re.IGNORECASE,
)
_CALENDAR_MODIFY = re.compile(
    r"\b(?:reschedule|move|update|change|edit|cancel)\b.{0,45}\b(?:calendar )?(?:event|meeting|appointment)\b",
    re.IGNORECASE,
)
_CALENDAR_READ = re.compile(
    r"\b(?:read|show|check|view|what(?:'s| is)|availability|free|busy|upcoming)\b.{0,50}\b(?:calendar|schedule|meetings?|appointments?)\b"
    r"|\b(?:calendar|schedule)\b.{0,40}\b(?:today|tomorrow|week|month|show|check|availability)\b",
    re.IGNORECASE,
)
_DRIVE_READ = re.compile(
    r"\b(?:google drive|one ?drive)\b"
    r"|\b(?:read|open|show|find|search)\b.{0,40}\b(?:drive file|cloud file)\b",
    re.IGNORECASE,
)
_GITHUB_REPO_SEARCH = re.compile(
    r"\b(?:search|find|locate|look for)\b.{0,45}\b(?:github|repositor(?:y|ies)|repos?)\b",
    re.IGNORECASE,
)
_GITHUB_REPO_READ = re.compile(
    r"\b(?:read|open|inspect|show|review|check)\b.{0,45}\b(?:github|repositor(?:y|ies)|repos?)\b"
    r"|\b(?:my )?github\b.{0,35}\b(?:repo|repository|code)\b",
    re.IGNORECASE,
)
_GITHUB_ISSUE_WRITE = re.compile(
    r"\b(?:create|open|close|update|edit|comment on)\b.{0,40}\b(?:github )?issues?\b",
    re.IGNORECASE,
)
_GITHUB_ISSUE_READ = re.compile(
    r"\b(?:read|show|check|find|search|review)\b.{0,40}\b(?:github )?issues?\b"
    r"|\b(?:github )?issues?\b.{0,35}\b(?:open|latest|assigned|mine)\b",
    re.IGNORECASE,
)
_GITHUB_PR_READ = re.compile(
    r"\b(?:read|show|check|review|inspect|find)\b.{0,45}\b(?:pull requests?|prs?)\b"
    r"|\b(?:pull requests?|prs?)\b.{0,35}\b(?:github|open|latest|mine)\b",
    re.IGNORECASE,
)
_CUSTOM_API = re.compile(
    r"\b(?:custom api|configured api|api connection)\b",
    re.IGNORECASE,
)


def _provider_preference(message: str, capability_id: str) -> str | None:
    lowered = message.casefold()

    if capability_id.startswith(("email.", "calendar.", "files.")):
        google = bool(
            re.search(r"\b(?:gmail|google calendar|google drive|google account)\b", lowered)
        )
        microsoft = bool(
            re.search(
                r"\b(?:outlook|microsoft 365|office 365|onedrive|one drive|microsoft calendar|microsoft account)\b",
                lowered,
            )
        )
        if google and not microsoft:
            return "google"
        if microsoft and not google:
            return "microsoft"
        return None

    if capability_id.startswith(
        ("repositories.", "issues.", "pull_requests.")
    ):
        return "github"

    if capability_id == "custom.request":
        return "custom_api"

    return None


def detect_capability_needs(message: str) -> tuple[CapabilityNeed, ...]:
    text = " ".join((message or "").strip().split())
    if not text:
        return ()

    found: dict[str, str] = {}

    def add(capability_id: str, reason: str) -> None:
        found.setdefault(capability_id, reason)

    if _EMAIL_SEND.search(text):
        add("email.send", "The request asks Jace to send or forward email.")
    if _EMAIL_DRAFT.search(text):
        add("email.draft", "The request asks Jace to draft or compose email.")
    if _EMAIL_SEARCH.search(text):
        add("email.search", "The request asks Jace to search or check email.")
    if _EMAIL_READ.search(text):
        add("email.read", "The request asks Jace to read or summarise email.")

    if _CALENDAR_CREATE.search(text):
        add("calendar.create", "The request asks Jace to create a calendar event.")
    if _CALENDAR_MODIFY.search(text):
        add("calendar.modify", "The request asks Jace to change a calendar event.")
    if _CALENDAR_READ.search(text):
        add("calendar.read", "The request asks Jace to inspect a calendar.")

    if _DRIVE_READ.search(text):
        add("files.read", "The request asks Jace to read cloud-drive files.")

    if _GITHUB_REPO_SEARCH.search(text):
        add("repositories.search", "The request asks Jace to search GitHub repositories.")
    if _GITHUB_REPO_READ.search(text):
        add("repositories.read", "The request asks Jace to inspect a GitHub repository.")
    if _GITHUB_ISSUE_WRITE.search(text):
        add("issues.write", "The request asks Jace to change GitHub issues.")
    if _GITHUB_ISSUE_READ.search(text):
        add("issues.read", "The request asks Jace to inspect GitHub issues.")
    if _GITHUB_PR_READ.search(text):
        add("pull_requests.read", "The request asks Jace to inspect pull requests.")

    if _CUSTOM_API.search(text):
        add("custom.request", "The request explicitly refers to a configured custom API.")

    return tuple(
        CapabilityNeed(
            capability_id=capability_id,
            reason=reason,
            preferred_provider=_provider_preference(text, capability_id),
        )
        for capability_id, reason in found.items()
    )


_STATE_RANK = {
    "ready": 600,
    "configured": 500,
    "blocked:missing_scopes": 400,
    "blocked:permission_denied": 350,
    "blocked:connection_error": 300,
    "blocked": 250,
    "disconnected": 150,
    "planned": 100,
}


def _candidate_from_row(row: dict[str, Any]) -> CapabilityCandidate:
    return CapabilityCandidate(
        capability_id=str(row.get("provider_capability_id") or ""),
        provider_id=str(row.get("provider_id") or ""),
        connection_id=str(row["connection_id"]) if row.get("connection_id") else None,
        account_hint=str(row["account_hint"]) if row.get("account_hint") else None,
        state=str(row.get("state") or "planned"),
        permission=str(row["permission"]) if row.get("permission") else None,
        tool_name=str(row["tool_name"]) if row.get("tool_name") else None,
        availability_reason=(
            str(row["availability_reason"])
            if row.get("availability_reason")
            else None
        ),
        missing_scopes=tuple(
            str(item)
            for item in (row.get("missing_scopes") or [])
        ),
        granted_scopes=tuple(
            str(item)
            for item in (row.get("granted_scopes") or [])
        ),
    )


def _candidate_rank(candidate: CapabilityCandidate) -> int:
    key = candidate.state
    if candidate.state == "blocked":
        key = f"blocked:{candidate.availability_reason or ''}"
    rank = _STATE_RANK.get(key, 0)

    if candidate.permission == "allow":
        rank += 3
    elif candidate.permission == "ask":
        rank += 2
    elif candidate.permission == "deny":
        rank += 1

    return rank


def _account_mentions(
    message: str,
    candidates: list[CapabilityCandidate],
) -> list[CapabilityCandidate]:
    lowered = message.casefold()
    return [
        candidate
        for candidate in candidates
        if candidate.account_hint
        and candidate.account_hint.casefold() in lowered
    ]


def _resolution_from_candidate(
    need: CapabilityNeed,
    candidate: CapabilityCandidate,
    *,
    all_candidates: tuple[CapabilityCandidate, ...],
) -> CapabilityResolution:
    if candidate.state == "ready":
        if not settings.tools_enabled:
            status: ResolutionStatus = "tools_disabled"
            reason = "Global tool execution is disabled."
        else:
            status = "ready"
            reason = "A connected, permitted, executable tool binding is available."
    elif candidate.state == "configured":
        status = "implementation_pending"
        reason = "Provider access exists, but no executable tool implementation is registered."
    elif candidate.state == "blocked":
        if candidate.availability_reason == "missing_scopes":
            status = "needs_access"
            reason = "The connected account is missing required provider authorization."
        elif candidate.availability_reason == "permission_denied":
            status = "permission_denied"
            reason = "Jace's capability permission is Deny."
        elif candidate.availability_reason == "connection_error":
            status = "connection_error"
            reason = "The account connection is currently in an error state."
        else:
            status = "permission_denied"
            reason = "The capability is blocked."
    elif candidate.state == "disconnected":
        status = "disconnected"
        reason = "The matching account is disconnected."
    elif candidate.state == "planned":
        status = "connection_required"
        reason = "No connected account currently provides this capability."
    else:
        status = "unsupported"
        reason = "No usable capability binding was found."

    return CapabilityResolution(
        capability_id=need.capability_id,
        status=status,
        preferred_provider=need.preferred_provider,
        provider_id=candidate.provider_id or None,
        connection_id=candidate.connection_id,
        account_hint=candidate.account_hint,
        permission=candidate.permission,
        tool_name=candidate.tool_name if status == "ready" else None,
        missing_scopes=candidate.missing_scopes,
        candidates=all_candidates,
        reason=reason,
    )


def _resolve_need(
    message: str,
    need: CapabilityNeed,
    provider_rows: list[dict[str, Any]],
) -> CapabilityResolution:
    candidates = [
        _candidate_from_row(row)
        for row in provider_rows
        if row.get("source") == "connection"
        and row.get("provider_capability_id") == need.capability_id
    ]

    if need.preferred_provider:
        preferred = [
            candidate
            for candidate in candidates
            if candidate.provider_id == need.preferred_provider
        ]
        if preferred:
            candidates = preferred

    if not candidates:
        return CapabilityResolution(
            capability_id=need.capability_id,
            status="unsupported",
            preferred_provider=need.preferred_provider,
            provider_id=need.preferred_provider,
            connection_id=None,
            account_hint=None,
            permission=None,
            tool_name=None,
            candidates=(),
            reason="No provider in the capability registry declares this capability.",
        )

    explicitly_named_accounts = _account_mentions(message, candidates)
    if explicitly_named_accounts:
        candidates = explicitly_named_accounts

    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -_candidate_rank(candidate),
            candidate.provider_id,
            candidate.account_hint or "",
            candidate.connection_id or "",
        ),
    )

    all_candidates = tuple(ordered)
    best_rank = _candidate_rank(ordered[0])
    best = [
        candidate
        for candidate in ordered
        if _candidate_rank(candidate) == best_rank
    ]
    real_best = [
        candidate
        for candidate in best
        if candidate.connection_id
    ]

    if len(real_best) > 1:
        return CapabilityResolution(
            capability_id=need.capability_id,
            status="ambiguous",
            preferred_provider=need.preferred_provider,
            provider_id=None,
            connection_id=None,
            account_hint=None,
            permission=None,
            tool_name=None,
            candidates=all_candidates,
            reason=(
                "More than one equally suitable connected account can provide "
                "this capability and the request does not identify which one to use."
            ),
        )

    selected = real_best[0] if real_best else best[0]
    return _resolution_from_candidate(
        need,
        selected,
        all_candidates=all_candidates,
    )


async def resolve_runtime_capabilities(
    session: AsyncSession,
    message: str,
) -> RuntimeCapabilityPlan:
    needs = detect_capability_needs(message)
    if not needs:
        return RuntimeCapabilityPlan.empty(message)

    capability_snapshot = await snapshot(session)
    rows = list(capability_snapshot.get("capabilities") or [])

    resolutions = tuple(
        _resolve_need(message, need, rows)
        for need in needs
    )

    tool_names: list[str] = []
    tool_bindings: dict[str, dict[str, Any]] = {}

    for resolution in resolutions:
        if (
            resolution.status != "ready"
            or not resolution.tool_name
            or not resolution.connection_id
            or not resolution.provider_id
        ):
            continue

        tool_name = resolution.tool_name
        binding = {
            "provider_id": resolution.provider_id,
            "connection_id": resolution.connection_id,
            "capability_id": resolution.capability_id,
            "account_hint": resolution.account_hint,
            "permission": resolution.permission or "ask",
        }

        existing = tool_bindings.get(tool_name)
        if existing and existing != binding:
            continue

        tool_bindings[tool_name] = binding
        if tool_name not in tool_names:
            tool_names.append(tool_name)

    return RuntimeCapabilityPlan(
        message=message,
        needs=needs,
        resolutions=resolutions,
        tool_names=tuple(tool_names),
        tool_bindings=tool_bindings,
    )
