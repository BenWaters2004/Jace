"""Offline policy tests: no API calls, filesystem writes or tool execution."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jace.agents.cloud_routing import AgentCloudRoutingError, ROLE_CONFIG, resolve_agent_model


def config(**overrides):
    value = dict(agent_cloud_routing_enabled=True, privacy_enabled=True,
                 privacy_cloud_egress_enabled=True,
                 agent_route_director="openai:director-test",
                 agent_route_research="anthropic:research-test",
                 agent_route_code="openai:code-test",
                 agent_route_files="anthropic:files-test",
                 agent_route_analyst="openai:analyst-test",
                 agent_route_general="anthropic:general-test")
    value.update(overrides)
    return SimpleNamespace(**value)


def gateway():
    fake = Mock()
    def resolve(_capability, *, requested_model):
        provider, model = requested_model.split(":", 1)
        return SimpleNamespace(provider=provider.lower(), model=model, local=False)
    fake.resolve.side_effect = resolve
    return fake


class CloudAgentRoutingTests(unittest.TestCase):
    def test_roles_have_routes(self):
        self.assertEqual(set(ROLE_CONFIG), {"director", "research", "code", "files", "analyst", "general"})

    def test_legacy_without_cloud_returns_profile(self):
        self.assertEqual(resolve_agent_model("research", legacy_model="qwen3:4b",
            config=config(agent_cloud_routing_enabled=False), gateway=gateway()), "qwen3:4b")

    def test_disabled_new_task_can_have_no_model(self):
        self.assertIsNone(resolve_agent_model("code", config=config(agent_cloud_routing_enabled=False), gateway=gateway()))

    def test_explicit_legacy_model_when_disabled(self):
        self.assertEqual(resolve_agent_model("analyst", requested_model="custom:1",
            legacy_model="qwen3:4b", config=config(agent_cloud_routing_enabled=False), gateway=gateway()), "custom:1")

    def test_all_six_cloud_routes(self):
        g = gateway()
        for role in ROLE_CONFIG:
            with self.subTest(role=role):
                self.assertTrue(resolve_agent_model(role, legacy_model="qwen3:4b",
                    config=config(), gateway=g).startswith(("openai:", "anthropic:")))
        self.assertEqual(g.resolve.call_count, 6)

    def test_caller_can_override_with_explicit_cloud_route(self):
        self.assertEqual(resolve_agent_model("code", requested_model="anthropic:override-test",
            config=config(), gateway=gateway()), "anthropic:override-test")

    def test_unqualified_override_denied(self):
        with self.assertRaises(AgentCloudRoutingError):
            resolve_agent_model("code", requested_model="qwen3:4b", config=config(), gateway=gateway())

    def test_explicit_local_denied(self):
        with self.assertRaises(AgentCloudRoutingError):
            resolve_agent_model("research", requested_model="ollama:qwen3:4b", config=config(), gateway=gateway())

    def test_no_automatic_local_fallback_from_legacy_profile(self):
        self.assertEqual(resolve_agent_model("general", legacy_model="ollama:qwen3:4b",
            config=config(), gateway=gateway()), "anthropic:general-test")

    def test_missing_route_denied(self):
        with self.assertRaisesRegex(AgentCloudRoutingError, "JACE_AGENT_ROUTE_CODE"):
            resolve_agent_model("code", config=config(agent_route_code=""), gateway=gateway())

    def test_cloud_privacy_must_be_enabled(self):
        for values in ({"privacy_enabled":False}, {"privacy_cloud_egress_enabled":False}):
            with self.subTest(values=values), self.assertRaises(AgentCloudRoutingError):
                resolve_agent_model("code", config=config(**values), gateway=gateway())

    def test_provider_disabled_fails_closed(self):
        fake=gateway()
        fake.resolve.side_effect=RuntimeError("api-key-private-text")
        with self.assertRaises(AgentCloudRoutingError) as cm:
            resolve_agent_model("code", config=config(), gateway=fake)
        self.assertNotIn("private", str(cm.exception))

    def test_gateway_local_fallback_route_rejected(self):
        fake=gateway()
        fake.resolve.side_effect=lambda *_a, **_k: SimpleNamespace(provider="ollama",model="qwen3",local=True)
        with self.assertRaises(AgentCloudRoutingError):
            resolve_agent_model("code", config=config(), gateway=fake)

    def test_unknown_role_rejected_even_legacy(self):
        with self.assertRaises(AgentCloudRoutingError):
            resolve_agent_model("superuser", config=config(agent_cloud_routing_enabled=False), gateway=gateway())

    def test_nul_or_multiline_denied(self):
        for route in ["openai:x\nJACE_API_KEY=fake", "", "x:y", "openai:", "anthropic:     "]:
            with self.subTest(route=route), self.assertRaises(AgentCloudRoutingError):
                resolve_agent_model("general", requested_model=route or None,
                    config=config(agent_route_general=route), gateway=gateway())

    def test_space_in_model_id_rejected(self):
        with self.assertRaises(AgentCloudRoutingError):
            resolve_agent_model("code", requested_model="openai:model with spaces",
                config=config(), gateway=gateway())

    def test_no_gateway_calls_when_disabled(self):
        fake=gateway()
        resolve_agent_model("code", config=config(agent_cloud_routing_enabled=False), gateway=fake)
        fake.resolve.assert_not_called()

    def test_no_gateway_calls_when_privacy_disabled(self):
        fake=gateway()
        with self.assertRaises(AgentCloudRoutingError):
            resolve_agent_model("code", config=config(privacy_cloud_egress_enabled=False), gateway=fake)
        fake.resolve.assert_not_called()

    def test_route_pins_exact_model(self):
        self.assertEqual(resolve_agent_model("research", requested_model="openai:my-model-2026",
            config=config(), gateway=gateway()), "openai:my-model-2026")


if __name__ == "__main__": unittest.main()
