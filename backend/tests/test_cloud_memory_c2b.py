"""C2B offline memory routing/regression tests (no cloud requests)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from jace.memory.retrieval_policy import (  # noqa E402
    embedding_models_match, lexical_relevance, score_memory,
)


class MemoryRouteSafetyTests(unittest.TestCase):
    def test_legacy_ollama_model_matches_same_qualified_model(self):
        self.assertTrue(embedding_models_match('qwen3-embedding:0.6b','ollama:qwen3-embedding:0.6b'))

    def test_same_dimension_different_provider_cannot_match(self):
        self.assertFalse(embedding_models_match('ollama:embed', 'openai:embed'))
        self.assertFalse(embedding_models_match('text-embedding-3-small','openai:text-embedding-3-small'))

    def test_new_cloud_route_can_match_itself(self):
        self.assertTrue(embedding_models_match('openai:text-embedding-3-small','openai:text-embedding-3-small'))

    def test_subject_match_retrieves_legacy_vector_in_hybrid_mode(self):
        hit = score_memory(query='What is the Jace architecture?',subject='Jace architecture',
            content='It uses a backend.',stored_model='ollama:old',embedding_json='[0.9,0.2]',
            active_route='openai:embedding',query_vector=[0.1,0.9],mode='hybrid',
            min_semantic=0.5,min_lexical=0.6)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], 'lexical')

    def test_semantic_mode_does_not_mix_vectors(self):
        self.assertIsNone(score_memory(query='Jace',subject='Jace',content='Jace uses PostgreSQL',
            stored_model='ollama:one',embedding_json='[1,0]', active_route='openai:two',
            query_vector=[1,0],mode='semantic',min_semantic=.5,min_lexical=.6))

    def test_lexical_mode_ignores_even_identical_vectors(self):
        hit = score_memory(query='Jace',subject='Jace',content='Jace context',
            stored_model='openai:x',embedding_json='[1,0]',active_route='openai:x',
            query_vector=[1,0],mode='lexical',min_semantic=.5,min_lexical=.6)
        self.assertEqual(hit[1], 'lexical')

    def test_same_provider_vector_cosine(self):
        hit = score_memory(query='anything',subject='not matched',content='not matched',
            stored_model='openai:embed',embedding_json='[1,0]',active_route='openai:embed',
            query_vector=[1,0],mode='hybrid',min_semantic=.5,min_lexical=.6)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], 'semantic')
        self.assertAlmostEqual(hit[0],1.0)

    def test_unrelated_memory_is_not_lexically_injected(self):
        self.assertEqual(lexical_relevance('Explain DNS','travel bookings','Flights to Greece in May'),0.0)

    def test_content_requires_two_nontrivial_terms(self):
        self.assertEqual(lexical_relevance('What is DNS?','random note','DNS issue yesterday'),0.0)

    def test_bad_or_corrupt_vector_does_not_crash(self):
        for value in ('broken', '{}', 'null', '[]', '[1]', '["oops",3]'):
            with self.subTest(value=value):
                self.assertIsNone(score_memory(query='unrelated query',subject='file notes',content='nil',
                    stored_model='openai:embed',embedding_json=value,active_route='openai:embed',
                    query_vector=[1,0],mode='semantic',min_semantic=.5,min_lexical=.6))

    def test_bare_model_no_longer_impersonates_cloud_model(self):
        self.assertFalse(embedding_models_match('embedding','anthropic:embedding'))


if __name__ == '__main__':
    unittest.main()
