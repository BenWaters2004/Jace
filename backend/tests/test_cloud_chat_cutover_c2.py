"""No live provider calls: Phase C2 chat cutover contract regression checks."""
from __future__ import annotations

import unittest
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from jace.model_gateway.cutover import (
    ChatCutoverConfigurationError, choose_chat_model, configured_cloud_models,
)


class ChatModelMigrationTest(unittest.TestCase):
    def test_disabled_is_identity(self):
        self.assertEqual(choose_chat_model("qwen3.5:4b", cutover_enabled=False, fast_route=""), "qwen3.5:4b")

    def test_old_qualified_ollama_tags_are_not_mistaken_for_provider_routes(self):
        self.assertEqual(choose_chat_model("qwen3.5:4b", cutover_enabled=True, fast_route="openai:gpt-example"), "openai:gpt-example")

    def test_existing_unqualified_name_migrates_lazily(self):
        self.assertEqual(choose_chat_model("qwen3:1.7b", cutover_enabled=True, fast_route="anthropic:claude-example"), "anthropic:claude-example")

    def test_explicit_ollama_override_survives(self):
        self.assertEqual(choose_chat_model("ollama:qwen3.5:4b", cutover_enabled=True, fast_route="openai:gpt-example"), "ollama:qwen3.5:4b")

    def test_explicit_cloud_override_survives(self):
        self.assertEqual(choose_chat_model("anthropic:another", cutover_enabled=True, fast_route="openai:gpt-example"), "anthropic:another")

    def test_no_cutover_without_configured_cloud_route(self):
        for invalid in ("", "qwen3:4b", "ollama:qwen3:4b", "openai:"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ChatCutoverConfigurationError):
                    choose_chat_model("qwen3.5:4b", cutover_enabled=True, fast_route=invalid)

    def test_visibility_requires_key_and_egress(self):
        routes = ["openai:gpt-example", "anthropic:claude-example"]
        self.assertEqual(configured_cloud_models(routes, cloud_egress=False, openai_enabled=True, anthropic_enabled=True), [])
        self.assertEqual(configured_cloud_models(routes, cloud_egress=True, openai_enabled=True, anthropic_enabled=False), ["openai:gpt-example"])

    def test_deduplication_and_default_order(self):
        self.assertEqual(configured_cloud_models(
            ["openai:gpt-example", "openai:gpt-example", "anthropic:claude-example", "ollama:qwen"],
            cloud_egress=True, openai_enabled=True, anthropic_enabled=True),
            ["openai:gpt-example", "anthropic:claude-example"])


if __name__ == "__main__":
    unittest.main()
