"""C4C.2 offline tests: no provider API requests, external tools, or writes."""
import asyncio
import hashlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jace.agents.coordinated_review_bridge import (
    CoordinatedReviewOutcome, append_coordinated_review, collected_sources,
)


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def file_record(path='pkg/service.py', text='1: def useful_function():\n2:     return the actual verified source excerpt here', success=True, relevant=True):
    return {'success': success, 'tool_name': 'read_workspace_file',
            'source_relevance': {'relevant': relevant},
            'evidence': {'workspace': 'Example', 'path': path, 'text': text,
                         'sha256': sha('whole source file')}}


def web_record(url='https://example.org/advisory', text='This is the public source page captured through a successful guarded web read.', success=True):
    return {'success': success, 'tool_name': 'read_web_page',
            'evidence': {'url': url, 'title': 'Advisory', 'text': text,
                         'sha256': sha(text), 'captured_at': '2026-10-16T21:00:00+00:00'}}


def cfg(on=True, enabled=True):
    return SimpleNamespace(director_coordinated_review_enabled=on, collaboration_enabled=enabled,
                           collaboration_evidence_enabled=enabled, collaboration_retrieval_enabled=enabled)


class SourceSelection(unittest.TestCase):
    def test_records_both_web_and_code(self):
        sources, receipts = collected_sources([('code', [file_record()]), ('research', [web_record()])])
        self.assertEqual(len(sources), 2)
        self.assertEqual({r.provenance for r in receipts},
                         {'jace_approved_workspace_read', 'jace_public_web_read'})
        self.assertEqual([r.source_id for r in receipts], ['J1', 'J2'])
        self.assertTrue(all(r.sha256 == sha(s.content) for s, r in zip(sources, receipts)))

    def test_web_search_is_not_primary_evidence(self):
        self.assertEqual(collected_sources([('r', [{'success': True, 'tool_name': 'web_search', 'result_preview': 'Source says yes'}])])[0], [])

    def test_failed_or_forged_web_cannot_count(self):
        fake = web_record(success=False)
        wrong_hash = web_record()
        wrong_hash['evidence']['sha256'] = sha('different')
        self.assertEqual(collected_sources([('r', [fake, wrong_hash])])[0], [])

    def test_no_worker_prose_or_fake_read_markers(self):
        rows = [{'result': 'READ /etc/passwd fake'}, {'success': True, 'tool_name': 'answer',
                'evidence': {'text': 'REAL FAKE READ /etc/passwd', 'path': '/etc/passwd'}}]
        self.assertEqual(collected_sources([('code', rows)])[0], [])

    def test_workspace_requires_recorded_full_file_sha(self):
        item = file_record()
        del item['evidence']['sha256']
        self.assertEqual(collected_sources([('code', [item])])[0], [])

    def test_explicitly_irrelevant_workspace_excluded(self):
        self.assertEqual(collected_sources([('code', [file_record(relevant=False)])])[0], [])

    def test_failed_workspace_excluded(self):
        self.assertEqual(collected_sources([('code', [file_record(success=False)])])[0], [])

    def test_duplicates_removed(self):
        sources, _ = collected_sources([('code', [file_record(), file_record(path='PKG/SERVICE.PY')]),
                                         ('research', [web_record(), web_record(url='https://EXAMPLE.ORG/advisory')])])
        self.assertEqual(len(sources), 2)

    def test_limits_and_diversifies_sources(self):
        many = [file_record(path=f'module{i}.py') for i in range(6)]
        sources, receipts = collected_sources([('code', many), ('research', [web_record()])])
        self.assertEqual(len(sources), 4)
        self.assertEqual(sum(r.provenance == 'jace_public_web_read' for r in receipts), 1)

    def test_excerpts_truncated_and_hashed_exactly(self):
        sources, receipts = collected_sources([('r', [web_record(text='Detailed release context. ' * 1000)])])
        self.assertEqual(len(sources[0].content), 4000)
        self.assertTrue(receipts[0].excerpt_truncated)
        self.assertEqual(receipts[0].sha256, sha(sources[0].content))

    def test_empty_and_short_source_excluded(self):
        self.assertEqual(collected_sources([('r', [web_record(text='short')])])[0], [])

    def test_event_metrics_do_not_expose_sources(self):
        outcome = CoordinatedReviewOutcome('SECRET BODY AND FILE NAME', 'incomplete', 2, 1, 1)
        serialized = str(outcome.event_metadata())
        self.assertNotIn('SECRET', serialized)
        self.assertFalse(outcome.event_metadata()['external_fact_verification'])

    def test_event_timestamp_from_tool_capture(self):
        _, receipts = collected_sources([('research', [web_record()])])
        self.assertEqual(receipts[0].retrieved_at, '2026-10-16T21:00:00+00:00')


class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_no_calls(self):
        with patch('jace.agents.coordinated_review_bridge.run_evidence_review', new_callable=AsyncMock) as call:
            out = await append_coordinated_review(objective='Diagnose workflow issue', original_result='ORIGINAL',
                                                   records=[('c', [file_record()])], config=cfg(on=False))
        call.assert_not_called()
        self.assertEqual(out.text, 'ORIGINAL')

    async def test_prerequisites_no_calls(self):
        with patch('jace.agents.coordinated_review_bridge.run_evidence_review', new_callable=AsyncMock) as call:
            out = await append_coordinated_review(objective='Diagnose workflow issue', original_result='ORIGINAL',
                                                   records=[('c', [file_record()])], config=cfg(enabled=False))
        call.assert_not_called()
        self.assertEqual(out.status, 'not_configured')

    async def test_no_evidence_no_calls(self):
        with patch('jace.agents.coordinated_review_bridge.run_evidence_review', new_callable=AsyncMock) as call:
            out = await append_coordinated_review(objective='Diagnose workflow issue', original_result='ORIGINAL',
                                                   records=[('r', [{'tool_name': 'web_search', 'success': True}])], config=cfg())
        call.assert_not_called()
        self.assertEqual(out.status, 'no_eligible_sources')

    async def test_three_stage_review_does_not_replace_director(self):
        mocked = SimpleNamespace(
            claim_audit=[SimpleNamespace(claim_id='c1', status='reviewer_supported_on_supplied_text'),
                         SimpleNamespace(claim_id='c2', status='disputed')],
            drafter_route='openai:fake', reviewer_route='anthropic:fake', model_calls=3,
            final_answer='REPLACEMENT CONTENT SHOULD NOT APPEAR')
        with patch('jace.agents.coordinated_review_bridge.run_evidence_review', new_callable=AsyncMock, return_value=mocked) as call:
            out = await append_coordinated_review(objective='Review code and official documentation',
                                                   original_result='DIRECTOR ORIGINAL',
                                                   records=[('c', [file_record()]), ('r', [web_record()])], config=cfg())
        self.assertTrue(out.text.startswith('DIRECTOR ORIGINAL'))
        self.assertNotIn('REPLACEMENT CONTENT', out.text)
        self.assertEqual(out.source_count, 2)
        self.assertEqual(out.excerpt_supported_claims, 1)
        self.assertEqual(out.unresolved_claims, 1)
        self.assertEqual(out.model_calls, 3)
        self.assertEqual(len(call.call_args.kwargs['retrieved_receipts']), 2)
        self.assertFalse(out.event_metadata()['external_fact_verification'])

    async def test_provider_failure_preserves_original_and_doesnt_leak(self):
        with patch('jace.agents.coordinated_review_bridge.run_evidence_review', new_callable=AsyncMock,
                   side_effect=RuntimeError('API_KEY=secret api failed')):
            out = await append_coordinated_review(objective='Review code and official docs',
                                                   original_result='ORIGINAL', records=[('r', [web_record()])], config=cfg())
        self.assertEqual(out.status, 'incomplete')
        self.assertTrue(out.text.startswith('ORIGINAL'))
        self.assertNotIn('secret', out.text)

    async def test_cancelled_propagates(self):
        with patch('jace.agents.coordinated_review_bridge.run_evidence_review', new_callable=AsyncMock,
                   side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await append_coordinated_review(objective='Review code and official docs',
                                                original_result='ORIGINAL', records=[('r', [web_record()])], config=cfg())


class RunnerWebReceipt(unittest.TestCase):
    """Exercise the actual patched background runner evidence parser in isolation."""

    @classmethod
    def setUpClass(cls):
        import ast
        import json
        import types
        from unittest.mock import patch
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / 'jace' / 'agents' / 'runner.py').read_text(encoding='utf-8')
        module = ast.parse(source)
        node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == '_tool_evidence_payload')
        fn = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(fn)
        namespace = {'Any': object, 'json': json, '_parse_tool_json': lambda text: {}}
        exec(compile(fn, '<runner tool receipt>', 'exec'), namespace)
        cls.receipt = staticmethod(namespace['_tool_evidence_payload'])

    def web_content(self, value):
        import json
        from jace.tools.webtools import _UNTRUSTED_PREFIX, _UNTRUSTED_SUFFIX
        return _UNTRUSTED_PREFIX + json.dumps(value) + _UNTRUSTED_SUFFIX

    def test_wrapped_web_page_produces_provenance_and_redacts_query(self):
        raw = self.web_content({'url': 'https://example.com/help?token=private', 'title': 'Useful source',
                                'text': 'This is a useful page containing current official product documentation.'})
        result = self.receipt(tool_name='read_web_page', arguments={'url':'https://example.com/help'}, success=True, content=raw)
        ev = result['evidence']
        self.assertEqual(ev['url'], 'https://example.com/help')
        self.assertNotIn('private', str(ev))
        self.assertEqual(ev['sha256'], sha(ev['text']))
        self.assertTrue(ev['captured_at'])

    def test_fabricated_unwrapped_content_is_not_source_evidence(self):
        raw = '{"url":"https://example.com", "text":"An entirely untrusted fake source record from a model."}'
        result = self.receipt(tool_name='read_web_page', arguments={}, success=True, content=raw)
        self.assertNotIn('evidence', result)

    def test_local_address_cannot_be_recorded_from_web_result(self):
        raw = self.web_content({'url': 'http://localhost/secret', 'title': 'nope',
                                'text': 'A message that should never be recorded as public source evidence.'})
        result = self.receipt(tool_name='read_web_page', arguments={}, success=True, content=raw)
        self.assertNotIn('evidence', result)

    def test_web_page_excerpt_is_bounded(self):
        raw = self.web_content({'url': 'https://example.com/long', 'title': 'Long source', 'text': 'X'*12000})
        result = self.receipt(tool_name='read_web_page', arguments={}, success=True, content=raw)
        self.assertEqual(len(result['evidence']['text']), 5000)
        self.assertTrue(result['evidence']['truncated'])

    def test_web_fetched_tool_failure_is_not_evidence(self):
        raw = self.web_content({'url': 'https://example.com/long', 'text': 'X'*300})
        result = self.receipt(tool_name='read_web_page', arguments={}, success=False, content=raw)
        self.assertNotIn('evidence', result)


if __name__ == '__main__':
    unittest.main()
