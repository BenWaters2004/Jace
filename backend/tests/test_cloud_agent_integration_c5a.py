"""Offline integration contracts for C5A patch layout (no network or tool calls)."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


class CloudAgentIntegrationTests(unittest.TestCase):
    def test_director_uses_explicit_route(self):
        text = source("jace/agents/director.py")
        self.assertIn('resolve_agent_model("director", legacy_model=profile.default_model)', text)
        self.assertIn('model=model, temperature=temperature, objective=objective', text)

    def test_task_model_is_persisted_before_queue(self):
        text=source("jace/agents/service.py")
        self.assertIn('resolved_agent_model = resolve_agent_model(definition.id, requested_model=model)', text)
        self.assertIn('model=resolved_agent_model,',text)
        self.assertIn('session.add(task)',text)

    def test_executor_rejects_unpinned_legacy_queue(self):
        text=source("jace/agents/runner.py")
        self.assertIn('if settings.agent_cloud_routing_enabled and not task.model:', text)
        self.assertIn('model = resolve_agent_model(',text)

    def test_ollama_probe_skipped_in_cloud_mode(self):
        text=source("jace/agents/readiness.py")
        self.assertIn('if not settings.agent_cloud_routing_enabled:\n        try:',text)
        self.assertIn('model_routing_error=model_routing_error',text)
        self.assertIn('cloud_route_unproven',text)

    def test_default_off_and_environment_opt_in(self):
        text=source("jace/config.py")
        self.assertIn('agent_cloud_routing_enabled: bool = False',text)
        for role in ('director','research','code','files','analyst','general'):
            self.assertIn(f'agent_route_{role}: str = ""',text)

    def test_imports_and_syntax(self):
        for path in ("jace/agents/runner.py", "jace/agents/director.py",
                     "jace/agents/readiness.py", "jace/agents/service.py",
                     "jace/agents/cloud_routing.py", "jace/config.py"):
            with self.subTest(path=path):
                ast.parse(source(path), filename=path)

    def test_disabled_mode_preserves_legacy_ollama_readiness(self):
        text=source('jace/agents/readiness.py')
        self.assertIn('if not ollama_connected:',text)
        self.assertIn('if not settings.agent_cloud_routing_enabled:',text)

    def test_no_changes_to_tool_executor_policy(self):
        text=source('jace/agents/runner.py')
        self.assertIn('tool_message, tool_execution = await _execute_tool(',text)
        self.assertIn('event_type="tool_started"',text)


if __name__ == '__main__':unittest.main()
