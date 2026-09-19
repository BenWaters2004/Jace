from __future__ import annotations

import re
from collections import Counter
from typing import Any

from jace.privacy.types import (
    PrivacyClassification,
    PrivacyDetection,
)


_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "personal": 3,
    "secret": 4,
}

_SECRET_PATTERNS = (
    ("private_key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        re.IGNORECASE,
    )),
    ("bearer_token", re.compile(
        r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}",
        re.IGNORECASE,
    )),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    )),
    ("github_token", re.compile(
        r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b",
        re.IGNORECASE,
    )),
    ("aws_access_key", re.compile(
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    )),
    ("openai_style_key", re.compile(
        r"\bsk-[A-Za-z0-9_-]{20,}\b"
    )),
    ("assigned_secret", re.compile(
        r"""(?ix)
        \b(
            password|passwd|api[_-]?key|client[_-]?secret|
            access[_-]?token|refresh[_-]?token
        )\b
        \s*[:=]\s*
        (?:
            ["'][^"'\r\n]{8,}["']
            |
            [A-Za-z0-9._~+/=-]{12,}
        )
        """
    )),
)

_PERSONAL_PATTERNS = (
    ("email", re.compile(
        r"(?<![A-Za-z0-9._%+-])"
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )),
    ("phone", re.compile(
        r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)"
    )),
)


def _stricter(
    left: PrivacyClassification,
    right: PrivacyClassification,
) -> PrivacyClassification:
    return right if _RANK[right] > _RANK[left] else left


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def inspect_payload(
    payload: Any,
    *,
    default_classification: PrivacyClassification = "internal",
    classification_hint: PrivacyClassification | None = None,
) -> tuple[PrivacyClassification, list[PrivacyDetection]]:
    classification = default_classification

    if classification_hint is not None:
        classification = _stricter(classification, classification_hint)

    counts: Counter[tuple[str, PrivacyClassification]] = Counter()

    for text in _strings(payload):
        for kind, pattern in _SECRET_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                counts[(kind, "secret")] += len(matches)

        for kind, pattern in _PERSONAL_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                counts[(kind, "personal")] += len(matches)

    detections: list[PrivacyDetection] = []

    for (kind, detected_classification), count in sorted(counts.items()):
        classification = _stricter(
            classification,
            detected_classification,
        )
        detections.append(
            PrivacyDetection(
                kind=kind,
                classification=detected_classification,
                count=count,
            )
        )

    return classification, detections
