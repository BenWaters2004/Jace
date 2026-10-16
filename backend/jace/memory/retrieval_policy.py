"""Pure memory retrieval policy for the C2B hybrid-cloud migration.

Never compare vectors from different model identities; fallback lexical relevance
is explicitly labelled an approximation and is not semantic similarity.
"""
from __future__ import annotations

import json
import math
import re

_STOP = frozenset({
    'a','about','after','again','all','am','an','and','are','as','at','be','been',
    'by','can','could','did','do','does','for','from','had','has','have','how','i',
    'in','into','is','it','me','my','of','on','or','our','please','remember','say',
    'tell','that','the','their','them','there','these','this','those','to','was',
    'we','were','what','when','where','which','who','why','will','with','would',
    'you','your','know','previous','previously','last','time','did','discuss',
})


def embedding_models_match(stored: str | None, active_route: str | None) -> bool:
    """A stored legacy bare Ollama model may match its qualified Ollama route."""
    stored = (stored or '').strip()
    active_route = (active_route or '').strip()
    if not stored or not active_route:
        return False
    if stored == active_route:
        return True
    if active_route.startswith('ollama:') and stored == active_route.split(':', 1)[1]:
        return True
    return False


def _tokens(text: str) -> set[str]:
    words = re.findall(r'[a-z0-9]{3,}', text.lower())
    return {
        word[:-1] if len(word) > 4 and word.endswith('s') and not word.endswith('ss') else word
        for word in words if word not in _STOP
    }


def lexical_relevance(query: str, subject: str, content: str) -> float:
    """Conservative [0,1] lexical relevance; no model/network is involved."""
    q = _tokens(query)
    if not q:
        return 0.0
    s = _tokens(subject)
    c = _tokens(content)
    subject_hits = len(q & s)
    if subject_hits:
        coverage = subject_hits / max(1, len(s))
        return min(0.96, 0.64 + 0.24 * coverage + 0.05 * (subject_hits > 1))
    content_hits = len(q & c)
    # Require at least two non-stopword matches in the content before a
    # memory with an unrelated subject is allowed into cloud-model context.
    if content_hits >= 2 and content_hits / max(1, len(q)) >= 0.4:
        return min(0.79, 0.56 + 0.19 * content_hits / max(1, len(q)))
    return 0.0


def cosine_similarity(first: list[float], second: list[float]) -> float:
    if not first or len(first) != len(second):
        return 0.0
    dot = sum(a * b for a, b in zip(first, second))
    na = math.sqrt(sum(v * v for v in first))
    nb = math.sqrt(sum(v * v for v in second))
    return dot / (na * nb) if na and nb else 0.0


def score_memory(
    *, query: str, subject: str, content: str, stored_model: str,
    embedding_json: str, active_route: str | None, query_vector: list[float] | None,
    mode: str, min_semantic: float, min_lexical: float,
) -> tuple[float, str] | None:
    """Return (relevance, source) where source is 'semantic' or 'lexical'."""
    if (mode != 'lexical' and query_vector is not None
            and embedding_models_match(stored_model, active_route)):
        try:
            stored = json.loads(embedding_json)
            if not isinstance(stored, list) or not all(isinstance(x, (int, float)) for x in stored):
                return None
            relevance = cosine_similarity(query_vector, [float(x) for x in stored])
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(relevance):
            return None
        return (relevance, 'semantic') if relevance >= min_semantic else None
    if mode not in {'lexical', 'hybrid'}:
        return None
    relevance = lexical_relevance(query, subject, content)
    return (relevance, 'lexical') if relevance >= min_lexical else None
