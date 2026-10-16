"""Offline C4C.1 tests; no model accounts or external services required."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jace.agents.cross_review_bridge import (
    DirectorReviewOutcome, append_director_cross_review, source_excerpts,
)


def record(*, path='src/real.py', text='1: def greet():\n2:     return "hello world from a real file"',
           success=True, tool='read_workspace_file', relevant=True, workspace='Project'):
    return {
        'success': success, 'tool_name': tool,
        'source_relevance': {'relevant': relevant},
        'evidence': {'path': path, 'workspace': workspace, 'text': text},
    }


def config(on=True, collab=True):
    return SimpleNamespace(director_cross_review_enabled=on,
                           collaboration_enabled=collab,
                           collaboration_evidence_enabled=collab)


class C4C1SelectionTests(unittest.TestCase):
    def test_successful_tool_provenance_required(self):
        rows = [('s1', [record(success=False), record(tool='web_search'),
                        {'result': 'READ src/fake.py contents'}])]
        self.assertEqual(source_excerpts(rows), [])

    def test_explicit_irrelevance_excluded(self):
        self.assertEqual(source_excerpts([('s1', [record(relevant=False)])]), [])

    def test_recorded_workspace_tool_read_retained(self):
        result = source_excerpts([('s1', [record()])])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, 'D1')
        self.assertIn('src/real.py', result[0].label)

    def test_no_model_prose_injection(self):
        rows = [('s1', [{'success': True, 'tool_name': 'model_answer',
                         'evidence': {'text': 'READ src/evil.py', 'path': 'src/evil.py'}}])]
        self.assertEqual(source_excerpts(rows), [])

    def test_duplicate_paths_removed(self):
        rows = [('s1', [record(path='x.py')]), ('s2', [record(path='X.PY')])]
        self.assertEqual(len(source_excerpts(rows)), 1)

    def test_source_cap(self):
        rows = [('s1', [record(path=f'{i}.py') for i in range(12)])]
        self.assertEqual(len(source_excerpts(rows)), 4)

    def test_excerpt_bounded(self):
        rows = [('s1', [record(text='some real source text ' * 1000)])]
        self.assertLessEqual(len(source_excerpts(rows)[0].content), 4000)

    def test_missing_workspace_path_fails(self):
        self.assertEqual(source_excerpts([('x', [record(path='')])]), [])

    def test_short_content_fails(self):
        self.assertEqual(source_excerpts([('x', [record(text='short')])]), [])

    def test_event_metadata_never_includes_source_or_result(self):
        item = DirectorReviewOutcome('secret text', 'incomplete', sources=2)
        data = item.event_metadata()
        self.assertNotIn('secret text', str(data))
        self.assertIs(data['external_fact_verification'], False)


class C4C1RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_disabled_no_provider_calls(self):
        mock = AsyncMock()
        with patch('jace.agents.cross_review_bridge.run_evidence_review', mock):
            result = await append_director_cross_review(
                objective='Investigate source bug', original_result='DIRECTOR',
                records=[('s', [record()])], config=config(on=False))
        self.assertEqual(result.text, 'DIRECTOR')
        mock.assert_not_called()

    async def test_disabled_collaboration_no_calls(self):
        mock = AsyncMock()
        with patch('jace.agents.cross_review_bridge.run_evidence_review', mock):
            result = await append_director_cross_review(
                objective='Investigate source bug', original_result='DIRECTOR',
                records=[('s', [record()])], config=config(collab=False))
        self.assertEqual(result.status, 'not_configured')
        mock.assert_not_called()

    async def test_no_valid_reads_no_calls(self):
        mock = AsyncMock()
        with patch('jace.agents.cross_review_bridge.run_evidence_review', mock):
            result = await append_director_cross_review(
                objective='Investigate source bug', original_result='DIRECTOR',
                records=[('s', [record(success=False)])], config=config())
        self.assertEqual(result.status, 'no_eligible_sources')
        mock.assert_not_called()

    async def test_completed_does_not_override_director_or_claim_verified(self):
        audit = [SimpleNamespace(claim_id='c1', status='reviewer_supported_on_supplied_text'),
                 SimpleNamespace(claim_id='c2', status='not_anchored')]
        mock = AsyncMock(return_value=SimpleNamespace(
            claim_audit=audit, sources=[1], drafter_route='openai:fixture',
            reviewer_route='anthropic:fixture', model_calls=3, final_answer='WRONG REPLACEMENT'))
        with patch('jace.agents.cross_review_bridge.run_evidence_review', mock):
            result = await append_director_cross_review(
                objective='Investigate source bug', original_result='DIRECTOR ORIGINAL',
                records=[('s', [record()])], config=config())
        self.assertTrue(result.text.startswith('DIRECTOR ORIGINAL'))
        self.assertNotIn('WRONG REPLACEMENT', result.text)
        self.assertIn('not a verification', result.text)
        self.assertEqual(result.supported_excerpt_claims, 1)
        self.assertEqual(result.unresolved_claims, 1)

    async def test_provider_error_keeps_original_and_no_raw_exception(self):
        mock = AsyncMock(side_effect=RuntimeError('sk-secret-value source path'))
        with patch('jace.agents.cross_review_bridge.run_evidence_review', mock):
            result = await append_director_cross_review(
                objective='Investigate source bug', original_result='DIRECTOR ORIGINAL',
                records=[('s', [record()])], config=config())
        self.assertEqual(result.status, 'incomplete')
        self.assertTrue(result.text.startswith('DIRECTOR ORIGINAL'))
        self.assertNotIn('sk-secret-value', result.text)

    async def test_cancelled_review_propagates(self):
        mock = AsyncMock(side_effect=asyncio.CancelledError())
        with patch('jace.agents.cross_review_bridge.run_evidence_review', mock):
            with self.assertRaises(asyncio.CancelledError):
                await append_director_cross_review(
                    objective='Investigate source bug', original_result='DIRECTOR',
                    records=[('s', [record()])], config=config())


if __name__ == '__main__':
    unittest.main()
