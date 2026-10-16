"""C4B.1 isolated tests, no live providers, database, network or device access."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jace.collaboration.evidence import (
    EvidenceReviewRequest, EvidenceDraft, EvidenceAssessment, ProposedClaim,
    ReviewVerdict, QuoteReference, SuppliedExcerpt, audit_claims,
    quote_present, run_evidence_review,
)
from jace.collaboration.review import CollaborationNotReady, CollaborationOutputError

TEXT = "The device connects outbound using an authenticated WebSocket and reconnects automatically."


def request():
    return EvidenceReviewRequest(objective="Assess the documented transport behavior.", evidence=[
        SuppliedExcerpt(id="s1", label="supplied document", content=TEXT)
    ])


def config(**kwargs):
    d = dict(collaboration_enabled=True, collaboration_evidence_enabled=True,
             collaboration_drafter_route="openai:unit-one",
             collaboration_reviewer_route="anthropic:unit-two",
             collaboration_max_output_chars=12000, collaboration_timeout_seconds=10)
    d.update(kwargs)
    return SimpleNamespace(**d)


class Route:
    def __init__(self, value):
        self.provider, self.model = value.split(":", 1)
        self.local = False
        self.route_id = value


class Provider:
    enabled = True
    supports_protected_cloud = True
    operations = ("generate", "generate_structured", "stream_chat")
    structured_chat = object()


class Gateway:
    def __init__(self, *, quote=None, judgement="supported", unknown_source=False,
                 missing_claim=False, empty_final=False, halt=False):
        self.calls = []
        self.quote = quote if quote is not None else "connects outbound using an authenticated WebSocket"
        self.judgement = judgement
        self.unknown_source = unknown_source
        self.missing_claim = missing_claim
        self.empty_final = empty_final
        self.halt = halt

    def resolve(self, capability, *, requested_model):
        assert capability == "reasoning.high"
        return Route(requested_model)

    def _provider(self, route):
        return Provider()

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.halt:
            await asyncio.sleep(999)
        if kwargs["response_model"] is EvidenceDraft:
            return EvidenceDraft(answer="The device connects outbound.", claims=[
                ProposedClaim(id="c1", statement="The device uses an outbound authenticated WebSocket.",
                              citations=[QuoteReference(
                                  source_id="missing" if self.unknown_source else "s1", quote=self.quote,
                              )])
            ])
        assert kwargs["response_model"] is EvidenceAssessment
        return EvidenceAssessment(overall="An assessment of the supplied text only.", verdicts=[
            ReviewVerdict(claim_id="different" if self.missing_claim else "c1", judgement=self.judgement,
                          explanation="The quoted excerpt mentions this transport.", inspected_source_ids=["s1"])
        ])

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return "" if self.empty_final else "According to the supplied excerpt, the connection is outbound."


class Privacy:
    enabled = True
    cloud_egress_enabled = True

    def __init__(self, *, block=False, enabled=True, egress=True, transform=False, block_after=None):
        self.block, self.enabled, self.cloud_egress_enabled, self.transform = block, enabled, egress, transform
        self.block_after = block_after
        self.calls = []

    def prepare_for_provider(self, payload, **kwargs):
        self.calls.append((payload, kwargs))
        if self.block or (self.block_after is not None and len(self.calls) >= self.block_after):
            return SimpleNamespace(require_local=True, action="reroute_local", transformed_payload={})
        if self.transform and "evidence" in payload:
            import copy
            data = copy.deepcopy(payload)
            data["evidence"][0]["content"] = data["evidence"][0]["content"].replace("WebSocket", "socket")
            return SimpleNamespace(require_local=False, action="protected_cloud", transformed_payload=data)
        return SimpleNamespace(require_local=False, action="protected_cloud", transformed_payload=payload)


class EvidenceContracts(unittest.TestCase):
    def test_quotes_are_whitespace_and_case_insensitive(self):
        self.assertTrue(quote_present("outbound using AN AUTHENTICATED   WebSocket", TEXT))
        self.assertFalse(quote_present("an authenticated WebSocket which uses a QUIC transport", TEXT))

    def test_short_anchor_is_rejected(self):
        self.assertFalse(quote_present("WebSocket", TEXT))

    def test_duplicate_evidence_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceReviewRequest(objective="Assess transport docs", evidence=[
                {"id": "s1", "label": "one", "content": TEXT},
                {"id": "s1", "label": "two", "content": TEXT},
            ])

    def test_oversized_evidence_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceReviewRequest(objective="Assess transport docs", evidence=[
                {"id": f"s{i}", "label": f"doc {i}", "content": "A"*4000}
                for i in range(8)
            ])

    def test_duplicate_claim_ids_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceDraft(answer="Some answer here", claims=[
                {"id":"x", "statement":"First long statement"},
                {"id":"x", "statement":"Second long statement"},
            ])

    def test_review_must_cover_each_claim(self):
        draft = EvidenceDraft(answer="A draft answer", claims=[
            ProposedClaim(id="one", statement="Some source-backed claim."),
        ])
        review = EvidenceAssessment(overall="Many claims are unsupported.", verdicts=[
            ReviewVerdict(claim_id="other", judgement="insufficient", explanation="No matching evidence.")
        ])
        with self.assertRaises(CollaborationOutputError):
            audit_claims(draft, review, request().evidence)

    def test_unknown_checked_source_rejected(self):
        draft = EvidenceDraft(answer="A draft answer", claims=[ProposedClaim(
            id="c1", statement="A claim about transport without proof.")])
        review = EvidenceAssessment(overall="Reviewer checked source", verdicts=[ReviewVerdict(
            claim_id="c1", judgement="supported", explanation="Contains the relevant phrase", inspected_source_ids=["made-up"])])
        with self.assertRaises(CollaborationOutputError):
            audit_claims(draft, review, request().evidence)


class EvidenceRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_three_calls_two_providers(self):
        gateway = Gateway()
        output = await run_evidence_review(request(), gateway=gateway, privacy=Privacy(), config=config())
        self.assertEqual(len(gateway.calls), 3)
        self.assertEqual([c["model"] for c in gateway.calls], ["openai:unit-one", "anthropic:unit-two", "openai:unit-one"])
        self.assertEqual(output.claim_audit[0].status, "reviewer_supported_on_supplied_text")
        self.assertEqual(output.verification_status, "supplied_excerpts_only")
        self.assertEqual(output.independently_verified_claims, 0)
        self.assertEqual(output.independently_retrieved_sources, 0)
        self.assertEqual(output.tools_executed, 0)
        self.assertEqual(output.sources[0].provenance, "user_supplied_not_retrieved")
        self.assertEqual(len(output.sources[0].sha256), 64)

    async def test_invalid_quote_not_anchored(self):
        out = await run_evidence_review(request(), gateway=Gateway(quote="no such transport is available here"), privacy=Privacy(), config=config())
        self.assertEqual(out.claim_audit[0].status, "not_anchored")
        self.assertFalse(out.claim_audit[0].citation_checks[0].exact_quote_present)

    async def test_unknown_citation_not_anchored(self):
        out = await run_evidence_review(request(), gateway=Gateway(unknown_source=True), privacy=Privacy(), config=config())
        self.assertEqual(out.claim_audit[0].status, "not_anchored")

    async def test_contradicted_does_not_pass(self):
        out = await run_evidence_review(request(), gateway=Gateway(judgement="contradicted"), privacy=Privacy(), config=config())
        self.assertEqual(out.claim_audit[0].status, "disputed")

    async def test_reviewer_insufficient_is_not_verified(self):
        out = await run_evidence_review(request(), gateway=Gateway(judgement="insufficient"), privacy=Privacy(), config=config())
        self.assertEqual(out.claim_audit[0].status, "insufficient_evidence")

    async def test_missing_reviewer_claim_fails(self):
        with self.assertRaises(CollaborationOutputError):
            await run_evidence_review(request(), gateway=Gateway(missing_claim=True), privacy=Privacy(), config=config())

    async def test_disabled_switches_no_calls(self):
        for setting in (dict(collaboration_enabled=False), dict(collaboration_evidence_enabled=False)):
            gateway = Gateway()
            with self.subTest(setting=setting), self.assertRaises(CollaborationNotReady):
                await run_evidence_review(request(), gateway=gateway, privacy=Privacy(), config=config(**setting))
            self.assertFalse(gateway.calls)

    async def test_privacy_gates_no_calls(self):
        for privacy in [Privacy(block=True), Privacy(enabled=False), Privacy(egress=False)]:
            gateway = Gateway()
            with self.subTest(privacy=vars(privacy)), self.assertRaises(CollaborationNotReady):
                await run_evidence_review(request(), gateway=gateway, privacy=privacy, config=config())
            self.assertFalse(gateway.calls)

    async def test_privacy_rechecks_reviewer_call(self):
        gateway = Gateway()
        with self.assertRaises(CollaborationNotReady):
            await run_evidence_review(request(), gateway=gateway,
                                      privacy=Privacy(block_after=3), config=config())
        self.assertEqual(len(gateway.calls), 1)

    async def test_privacy_rechecks_final_call(self):
        gateway = Gateway()
        with self.assertRaises(CollaborationNotReady):
            await run_evidence_review(request(), gateway=gateway,
                                      privacy=Privacy(block_after=4), config=config())
        self.assertEqual(len(gateway.calls), 2)

    async def test_same_provider_no_calls(self):
        gateway = Gateway()
        with self.assertRaises(CollaborationNotReady):
            await run_evidence_review(request(), gateway=gateway, privacy=Privacy(),
                                      config=config(collaboration_reviewer_route="openai:other"))
        self.assertFalse(gateway.calls)

    async def test_model_only_sees_transformed_evidence(self):
        gateway = Gateway()
        privacy = Privacy(transform=True)
        await run_evidence_review(request(), gateway=gateway, privacy=privacy, config=config())
        self.assertNotIn("WebSocket", gateway.calls[0]["messages"][0]["content"])
        self.assertIn("socket", gateway.calls[0]["messages"][0]["content"])

    async def test_final_output_must_not_be_empty(self):
        with self.assertRaises(CollaborationOutputError):
            await run_evidence_review(request(), gateway=Gateway(empty_final=True), privacy=Privacy(), config=config())

    async def test_timeout_does_not_complete(self):
        gateway = Gateway(halt=True)
        with self.assertRaises(CollaborationOutputError):
            await run_evidence_review(request(), gateway=gateway, privacy=Privacy(),
                                      config=config(collaboration_timeout_seconds=1))
