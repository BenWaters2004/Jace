"""C4A offline tests. No provider, device, database or network calls."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jace.collaboration.contracts import CollaborationRequest, ReviewerAssessment
from jace.collaboration.review import (
    CollaborationNotReady, CollaborationOutputError, run_review,
)


class Route:
    def __init__(self, identifier):
        self.provider, self.model = identifier.split(":", 1)
        self.local = False
        self.route_id = identifier


class FakeProvider:
    enabled = True
    supports_protected_cloud = True
    operations = ("generate", "generate_structured", "stream_chat")
    structured_chat = object()


class Gateway:
    def __init__(self, *, no_output=False, invalid_review=False, oversize=False):
        self.calls = []
        self.no_output = no_output
        self.invalid_review = invalid_review
        self.oversize = oversize

    def resolve(self, capability, *, requested_model):
        assert capability == "reasoning.high"
        return Route(requested_model)

    def _provider(self, route):
        return FakeProvider()

    async def generate(self, **kw):
        self.calls.append(("generate", kw))
        assert kw["model"] in ("openai:test-A", "anthropic:test-B")
        if self.no_output:
            return ""
        if self.oversize:
            return "X" * 25000
        return "Draft answer" if len(self.calls) == 1 else "Revised answer, with clear uncertainties."

    async def generate_structured(self, **kw):
        self.calls.append(("review", kw))
        assert kw["response_model"] is ReviewerAssessment
        if self.invalid_review:
            return {"assessment": "fabricated", "summary": "untrue"}
        return ReviewerAssessment(
            assessment="insufficient_evidence",
            summary="No primary evidence.",
            unsupported_claims=["No source was retrieved"],
        )


class Privacy:
    def __init__(self, *, enabled=True, egress=True, force_local=False):
        self.enabled, self.cloud_egress_enabled = enabled, egress
        self.force_local = force_local
        self.checks = []

    def prepare_for_provider(self, payload, **kwargs):
        self.checks.append((payload, kwargs))
        if self.force_local:
            return SimpleNamespace(require_local=True, action="reroute_local")
        return SimpleNamespace(require_local=False, action="protected_cloud")


def config(**overrides):
    d = dict(collaboration_enabled=True,
             collaboration_drafter_route="openai:test-A",
             collaboration_reviewer_route="anthropic:test-B",
             collaboration_max_output_chars=12000,
             collaboration_timeout_seconds=10)
    d.update(overrides)
    return SimpleNamespace(**d)


def req(with_notes=True):
    x = {"objective": "Examine worker queue tradeoffs and proposed architecture."}
    if with_notes:
        x["notes"] = [{"id": "provided", "content": "PostgreSQL is expected for durable state."}]
    return CollaborationRequest.model_validate(x)


class C4ATests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_provider_three_calls(self):
        g, p = Gateway(), Privacy()
        result = await run_review(req(), gateway=g, privacy=p, config=config())
        self.assertEqual([c[0] for c in g.calls], ["generate", "review", "generate"])
        self.assertEqual([c[1]["model"] for c in g.calls],
                         ["openai:test-A", "anthropic:test-B", "openai:test-A"])
        self.assertEqual(result.verification_status, "not_verified")
        self.assertEqual(result.tools_executed, 0)
        self.assertEqual(result.model_calls, 3)
        self.assertEqual(result.verified_citations, [])
        self.assertEqual(result.evidence_source, "user_supplied_unverified")
        self.assertEqual(len(p.checks), 4)

    async def test_no_notes_cannot_become_verified(self):
        output = await run_review(req(False), gateway=Gateway(), privacy=Privacy(), config=config())
        self.assertEqual(output.evidence_source, "none")
        self.assertEqual(output.verification_status, "not_verified")

    async def test_disabled_fails_before_any_provider_call(self):
        g = Gateway()
        with self.assertRaises(CollaborationNotReady):
            await run_review(req(), gateway=g, privacy=Privacy(),
                             config=config(collaboration_enabled=False))
        self.assertEqual(g.calls, [])

    async def test_no_egress_fails_closed(self):
        g = Gateway()
        with self.assertRaises(CollaborationNotReady):
            await run_review(req(), gateway=g, privacy=Privacy(egress=False), config=config())
        self.assertEqual(g.calls, [])

    async def test_privacy_off_fails_closed(self):
        with self.assertRaises(CollaborationNotReady):
            await run_review(req(), gateway=Gateway(), privacy=Privacy(enabled=False), config=config())

    async def test_local_only_fails_before_request(self):
        g = Gateway()
        with self.assertRaises(CollaborationNotReady):
            await run_review(req(), gateway=g, privacy=Privacy(force_local=True), config=config())
        self.assertEqual(g.calls, [])

    async def test_same_provider_forbidden(self):
        g = Gateway()
        with self.assertRaises(CollaborationNotReady):
            await run_review(req(), gateway=g, privacy=Privacy(),
                             config=config(collaboration_reviewer_route="openai:test-other"))
        self.assertEqual(g.calls, [])

    async def test_unknown_or_local_route_forbidden(self):
        for bad in ("model-name", "ollama:local", "openai:", "foobar:model"):
            g = Gateway()
            with self.subTest(bad=bad), self.assertRaises(CollaborationNotReady):
                await run_review(req(), gateway=g, privacy=Privacy(),
                                 config=config(collaboration_drafter_route=bad))
            self.assertEqual(g.calls, [])

    async def test_no_empty_or_oversized_draft(self):
        for opts in ({"no_output": True}, {"oversize": True}):
            g = Gateway(**opts)
            with self.subTest(opts=opts), self.assertRaises(CollaborationOutputError):
                await run_review(req(), gateway=g, privacy=Privacy(), config=config())
            self.assertEqual(len(g.calls), 1)

    async def test_unexpected_review_schema_fails(self):
        g = Gateway(invalid_review=True)
        with self.assertRaises(Exception):
            await run_review(req(), gateway=g, privacy=Privacy(), config=config())
        self.assertEqual(len(g.calls), 2)

    async def test_duplicate_note_ids_rejected(self):
        with self.assertRaises(ValueError):
            CollaborationRequest.model_validate({"objective": "Evaluate robust task scheduling.",
                "notes": [{"id":"x","content":"a"},{"id":"x","content":"b"}]})

    async def test_overlong_note_rejected(self):
        with self.assertRaises(ValueError):
            CollaborationRequest.model_validate({"objective": "Evaluate robust task scheduling.",
                "notes": [{"id":"x","content":"a"*2501}]})

    async def test_external_timeout_stops_flow(self):
        class HangingGateway(Gateway):
            async def generate(self, **kw):
                await asyncio.sleep(999)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(
                run_review(req(), gateway=HangingGateway(), privacy=Privacy(), config=config()), timeout=0.025)

    async def test_review_inputs_marked_untrusted(self):
        g = Gateway()
        await run_review(req(), gateway=g, privacy=Privacy(), config=config())
        prompts = [x[1]["messages"][0]["content"] for x in g.calls]
        self.assertTrue(all("UNVERIFIED CONTEXT" in p for p in prompts))
        self.assertIn("INDEPENDENT MODEL REVIEW", prompts[2])
        self.assertIn("INITIAL DRAFT", prompts[1])


if __name__ == "__main__":
    unittest.main()
