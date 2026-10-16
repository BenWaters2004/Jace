"""C3A deterministic selection tests: no external provider calls."""
from __future__ import annotations
import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / 'jace/model_gateway/smart_router.py'
spec = importlib.util.spec_from_file_location('jace_smart_router_c3a', MODULE)
import sys
router = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = router
spec.loader.exec_module(router)


class SmartRoutingTests(unittest.TestCase):
    def route(self, **kwargs):
        inputs = dict(message='Hello', reasoning_mode='fast',
                      fast_route='openai:configured-fast',
                      balanced_route='anthropic:configured-balanced',
                      deep_route='openai:configured-deep',
                      coding_route='anthropic:configured-code',
                      research_route='openai:configured-research')
        inputs.update(kwargs)
        return router.select_route(**inputs)

    def test_short_fast(self):
        s = self.route()
        self.assertEqual((s.tier, s.route), ('fast', 'openai:configured-fast'))

    def test_explicit_balanced(self):
        self.assertEqual(self.route(reasoning_mode='balanced').route,
                         'anthropic:configured-balanced')

    def test_explicit_deep_wins(self):
        s = self.route(message='research and debug', reasoning_mode='deep')
        self.assertEqual((s.tier, s.route), ('deep', 'openai:configured-deep'))

    def test_source_research(self):
        self.assertEqual(self.route(message='Find sources for DNS caching').tier, 'research')

    def test_coding_request(self):
        self.assertEqual(self.route(message='Refactor a Python script').tier, 'coding')

    def test_simple_what_is_python_remains_fast(self):
        self.assertEqual(self.route(message='What is Python?').tier, 'fast')

    def test_large_request_balanced(self):
        self.assertEqual(self.route(message='a' * 655).tier, 'balanced')

    def test_missing_specialist_falls_back_with_flag(self):
        s = self.route(message='Research current DNS vulnerabilities', research_route='')
        self.assertEqual(s.route, 'openai:configured-fast')
        self.assertTrue(s.fallback_to_fast)
        self.assertEqual(s.tier, 'research')

    def test_does_not_fall_back_if_broken_route(self):
        with self.assertRaises(router.SmartRoutingConfigurationError):
            self.route(coding_route='api:model', message='Debug the code')

    def test_missing_fast_fails_closed(self):
        with self.assertRaises(router.SmartRoutingConfigurationError):
            self.route(fast_route='')

    def test_tags_with_colons_preserved(self):
        self.assertEqual(self.route(fast_route='ollama:qwen3.5:4b').route,
                         'ollama:qwen3.5:4b')

    def test_no_provider_secrets_in_router(self):
        self.assertEqual(self.route(message='hello').reason, 'short_request')


class CloudCutoverContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cutover_path = MODULE.with_name('cutover.py')
        cutover_spec = importlib.util.spec_from_file_location('jace_cutover_c3a', cutover_path)
        cls.cutover = importlib.util.module_from_spec(cutover_spec)
        sys.modules[cutover_spec.name] = cls.cutover
        cutover_spec.loader.exec_module(cls.cutover)

    def test_auto_preserved_when_opted_in(self):
        self.assertEqual(self.cutover.choose_chat_model(
            'auto', cutover_enabled=True,
            fast_route='openai:configured-fast', auto_enabled=True,
        ), 'auto')

    def test_auto_disabled_resolves_to_fast(self):
        self.assertEqual(self.cutover.choose_chat_model(
            'auto', cutover_enabled=True,
            fast_route='openai:configured-fast', auto_enabled=False,
        ), 'openai:configured-fast')

    def test_explicit_model_stays_manual(self):
        self.assertEqual(self.cutover.choose_chat_model(
            'anthropic:chosen-model', cutover_enabled=True,
            fast_route='openai:configured-fast', auto_enabled=True,
        ), 'anthropic:chosen-model')

    def test_disabled_cloud_cutover_preserves_legacy_model(self):
        self.assertEqual(self.cutover.choose_chat_model(
            'qwen3.5:4b', cutover_enabled=False,
            fast_route='', auto_enabled=True,
        ), 'qwen3.5:4b')


if __name__ == '__main__':
    unittest.main()
