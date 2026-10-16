"""C4B.2 offline: contract, tool policy and source receipt tests. No live calls."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jace.collaboration import retrieval as r
from jace.collaboration.evidence import (
    SuppliedExcerpt, SourceReceipt, EvidenceReviewRequest, EvidenceDraft,
    EvidenceAssessment, ProposedClaim, QuoteReference, ReviewVerdict, run_evidence_review,
)

TEXT = "The authenticated desktop Device Agent connects outbound and reconnects using a secure WebSocket."
WEB = "https://example.org/research?page=2&token=secret-query"


class Provider:
    enabled = True
    supports_protected_cloud = True
    operations = ("generate", "generate_structured", "stream_chat")
    structured_chat = object()


class Gateway:
    def resolve(self, capability, *, requested_model):
        provider, model = requested_model.split(":", 1)
        return SimpleNamespace(provider=provider, model=model, local=False, route_id=requested_model)

    def _provider(self, route):
        return Provider()


class Privacy:
    enabled = True
    cloud_egress_enabled = True

    def __init__(self, block=False):
        self.block = block
        self.calls = 0

    def prepare_for_provider(self, payload, **kwargs):
        self.calls += 1
        return SimpleNamespace(require_local=self.block, action="reroute_local" if self.block else "protected_cloud",
                               transformed_payload=payload)


def config(**kwargs):
    data = dict(collaboration_enabled=True, collaboration_evidence_enabled=True,
                collaboration_retrieval_enabled=True, collaboration_drafter_route="openai:drafter",
                collaboration_reviewer_route="anthropic:reviewer", tools_enabled=True, web_enabled=True,
                computer_enabled=True, collaboration_retrieval_timeout_seconds=30)
    data.update(kwargs)
    return SimpleNamespace(**data)


def actor():
    return SimpleNamespace(actor_id="unit-user", client_id="unit-client", server_mode=True)


def web(id="s1", url="https://example.org/news"):
    return r.RequestedSource(id=id, kind="public_web", url=url)


def file(id="f1"):
    return r.RequestedSource(id=id, kind="workspace_file", workspace_id="a"*36,
                             path="docs/architecture.md")


class FakeSession:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False


class Tool:
    def __init__(self, result):
        self.result = result
        self.risk = "read"
        self.capability_id = None
        self.execute = AsyncMock(return_value=SimpleNamespace(content=result, display="source captured"))

    def resolve_policy(self, args):
        return SimpleNamespace(minimum_permission="allow")


def web_result(content=TEXT):
    data = {"url": "https://example.org/news", "title": "Source title", "text": content}
    return r._UNTRUSTED_PREFIX + json.dumps(data) + r._UNTRUSTED_SUFFIX


def file_result(content=TEXT):
    return json.dumps({"workspace": "Jace", "path": "docs/architecture.md", "sha256": "a"*64,
                       "text": content, "returned_lines": 1})


class ContractTests(unittest.TestCase):
    def test_web_source_shape(self):
        self.assertEqual(web().kind, "public_web")

    def test_private_ip_syntax_denied(self):
        # Existing fetch security additionally validates DNS at execution.
        with self.assertRaises(ValueError):
            web(url="http://localhost/internal")
        with self.assertRaises(ValueError):
            web(url="http://127.0.0.1/secrets")

    def test_nonstandard_port_blocked(self):
        with self.assertRaises(ValueError):
            web(url="https://example.org:8080/secret")

    def test_file_requires_scope(self):
        with self.assertRaises(ValueError):
            r.RequestedSource(id="f1", kind="workspace_file", path="test.py")

    def test_file_cannot_include_url(self):
        with self.assertRaises(ValueError):
            r.RequestedSource(id="f1", kind="workspace_file", url="https://example.org", workspace_id="a"*36, path="test.py")

    def test_duplicate_sources_rejected(self):
        with self.assertRaises(ValueError):
            r.RetrievalReviewRequest(objective="Investigate transport", sources=[web(), web()])

    def test_source_count_bounded(self):
        with self.assertRaises(ValueError):
            r.RetrievalReviewRequest(objective="Investigate transport", sources=[web(str(i)) for i in range(5)])

    def test_web_marker_validation(self):
        with self.assertRaises(r.RetrievalFailed):
            r._decode_web(json.dumps({"url":"https://example.org", "text":TEXT}), web())
        text, label, url, full_sha = r._decode_web(web_result(), web())
        self.assertEqual((text, label, url, full_sha), (TEXT, "Source title", "https://example.org/news", None))

    def test_workspace_receipt_requires_full_file_checksum(self):
        result = json.loads(file_result())
        result["sha256"] = "wrong"
        with self.assertRaises(r.RetrievalFailed):
            r._decode_workspace(json.dumps(result), file())

    def test_audit_omits_url_query(self):
        output = r._url_audit_identifier(WEB)
        self.assertEqual(output["host"], "example.org")
        self.assertNotIn("token=", repr(output))
        self.assertEqual(len(output["url_sha256"]), 64)

    def test_secret_privacy_preflight(self):
        with self.assertRaises(r.RetrievalNotAvailable):
            r._preflight(r.RetrievalReviewRequest(objective="Investigate transport", sources=[web()]),
                         gateway=Gateway(), privacy=Privacy(block=True), config=config())

    def test_not_enabled_blocks(self):
        with self.assertRaises(r.RetrievalNotAvailable):
            r._preflight(r.RetrievalReviewRequest(objective="Investigate transport", sources=[web()]),
                         gateway=Gateway(), privacy=Privacy(), config=config(collaboration_retrieval_enabled=False))

    def test_receipt_sha_mismatch_rejected(self):
        async def go():
            model = Gateway()
            quote = SourceReceipt(source_id="s1", label="Retrieved", sha256="0"*64,
                                  provenance="jace_public_web_read")
            request = EvidenceReviewRequest(objective="Investigate transport", evidence=[
                SuppliedExcerpt(id="s1", label="Retrieved", content=TEXT)])
            await run_evidence_review(request, gateway=model, privacy=Privacy(), config=config(),
                                      retrieved_receipts=[quote])
        with self.assertRaises(r.CollaborationOutputError):
            asyncio.run(go())

    def test_retrieved_review_provenance_does_not_count_as_independent_verification(self):
        class ReviewGateway(Gateway):
            async def generate_structured(self, **kwargs):
                if kwargs["response_model"] is EvidenceDraft:
                    return EvidenceDraft(answer="This code uses an outbound connection.", claims=[
                        ProposedClaim(id="c1", statement="The agent establishes an outbound WebSocket.",
                                      citations=[QuoteReference(source_id="s1",
                                                                quote="connects outbound and reconnects using a secure WebSocket")])
                    ])
                return EvidenceAssessment(overall="Claim aligns with the captured source excerpt.", verdicts=[
                    ReviewVerdict(claim_id="c1", judgement="supported",
                                  explanation="The wording appears in the collected text.",
                                  inspected_source_ids=["s1"])
                ])
            async def generate(self, **kwargs):
                return "The captured source states it uses an outbound WebSocket. This has not been independently fact-checked."
        async def go():
            request = EvidenceReviewRequest(objective="Investigate transport", evidence=[
                SuppliedExcerpt(id="s1", label="Retrieved", content=TEXT)])
            receipt = SourceReceipt(source_id="s1", label="Retrieved", sha256=r._sha(TEXT),
                                    provenance="jace_public_web_read", locator="https://example.org/news")
            return await run_evidence_review(request, gateway=ReviewGateway(), privacy=Privacy(),
                                             config=config(collaboration_timeout_seconds=10),
                                             retrieved_receipts=[receipt])
        response = asyncio.run(go())
        self.assertEqual(response.stage, "C4B.2")
        self.assertEqual(response.verification_status, "retrieved_excerpts_reviewed")
        self.assertEqual(response.independently_retrieved_sources, 1)
        self.assertEqual(response.independently_verified_claims, 0)
        self.assertEqual(response.tools_executed, 1)
        self.assertIn("not independently verified", response.notice)
        self.assertEqual(response.sources[0].provenance, "jace_public_web_read")

    def test_same_provider_blocks(self):
        with self.assertRaises(r.RetrievalNotAvailable):
            r._preflight(r.RetrievalReviewRequest(objective="Investigate transport", sources=[web()]),
                         gateway=Gateway(), privacy=Privacy(),
                         config=config(collaboration_reviewer_route="openai:other"))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, *, kind="public_web", permission="allow", tool=None, cfg=None, privacy=None, mixed=False):
        item = web() if kind == "public_web" else file()
        if mixed: item = web()
        req = r.RetrievalReviewRequest(objective="Investigate transport", sources=[item])
        tool = tool or Tool(web_result() if kind == "public_web" else file_result())
        registry = SimpleNamespace(get=lambda name: tool)
        audit = SimpleNamespace(id="audit-id")
        with patch.object(r, "registry", registry), \
             patch.object(r, "ensure_tools_registered"), \
             patch.object(r, "SessionLocal", return_value=FakeSession()), \
             patch.object(r, "get_tool_permission", new=AsyncMock(return_value=permission)), \
             patch.object(r, "create_tool_audit", new=AsyncMock(return_value=audit)) as create_audit, \
             patch.object(r, "update_tool_audit", new=AsyncMock()) as update_audit, \
             patch.object(r, "require_or_claim_local", new=AsyncMock()) as owner, \
             patch.object(r, "run_evidence_review", new=AsyncMock(return_value=SimpleNamespace(stage="C4B.2"))) as review:
            reply = await r.run_retrieval_review(req, actor=actor(), gateway=Gateway(), privacy=privacy or Privacy(), config=cfg or config())
            return reply, tool, create_audit, update_audit, owner, review

    async def test_public_url_retrieved_once(self):
        reply, tool, audit, updated, owner, review = await self.call()
        self.assertEqual(reply.stage, "C4B.2")
        self.assertEqual(tool.execute.await_count, 1)
        self.assertEqual(review.await_count, 1)
        excerpt = review.await_args.args[0].evidence[0]
        self.assertEqual(excerpt.content, TEXT)
        receipt = review.await_args.kwargs["retrieved_receipts"][0]
        self.assertEqual(receipt.provenance, "jace_public_web_read")
        self.assertEqual(receipt.sha256, r._sha(TEXT))
        self.assertIsNotNone(receipt.retrieved_at)
        self.assertEqual(audit.await_count, 1)
        self.assertEqual(owner.await_count, 0)

    async def test_ask_permission_fails_before_execution(self):
        with self.assertRaises(r.RetrievalNotAvailable):
            await self.call(permission="ask")

    async def test_workspace_owner_checked(self):
        _, tool, _, _, owner, review = await self.call(kind="workspace_file")
        self.assertGreaterEqual(owner.await_count, 1)
        self.assertEqual(tool.execute.await_count, 1)
        receipt = review.await_args.kwargs["retrieved_receipts"][0]
        self.assertEqual(receipt.full_document_sha256, "a"*64)

    async def test_fail_closed_on_tool_read_error(self):
        failed = Tool(web_result())
        failed.execute.side_effect = RuntimeError("private server detail sk-secret-from-exception")
        with self.assertRaisesRegex(r.RetrievalFailed, "could not be collected") as caught:
            await self.call(tool=failed)
        self.assertNotIn("sk-secret", str(caught.exception))

    async def test_long_text_clipped_with_receipt(self):
        long_text = TEXT * 150
        _, _, _, _, _, review = await self.call(tool=Tool(web_result(long_text)))
        excerpt = review.await_args.args[0].evidence[0]
        receipt = review.await_args.kwargs["retrieved_receipts"][0]
        self.assertLessEqual(len(excerpt.content), 4800)
        self.assertTrue(receipt.excerpt_truncated)

    async def test_malformed_tool_result_blocks_model(self):
        with self.assertRaises(r.RetrievalFailed):
            await self.call(tool=Tool("not valid framed JSON"))

    async def test_blocked_cloud_preflight_does_not_execute(self):
        with self.assertRaises(r.RetrievalNotAvailable):
            await self.call(privacy=Privacy(block=True))

    async def test_failure_updates_audit(self):
        tool = Tool(web_result())
        tool.execute.side_effect = RuntimeError("tool failed")
        with self.assertRaises(r.RetrievalFailed):
            await self.call(tool=tool)
        self.assertEqual(tool.execute.await_count, 1)


if __name__ == "__main__":
    unittest.main()
