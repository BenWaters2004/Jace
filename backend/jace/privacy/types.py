from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


PrivacyClassification = Literal[
    "public",
    "internal",
    "confidential",
    "personal",
    "secret",
]

PrivacyMode = Literal[
    "cloud_allowed",
    "protected_cloud",
    "local_only",
]

PrivacyAction = Literal[
    "local",
    "raw_cloud",
    "protected_cloud",
    "reroute_local",
]


@dataclass(frozen=True, slots=True)
class PrivacyDetection:
    kind: str
    classification: PrivacyClassification
    count: int


@dataclass(slots=True)
class PrivacyDecision:
    classification: PrivacyClassification
    mode: PrivacyMode
    action: PrivacyAction
    require_local: bool
    detections: list[PrivacyDetection] = field(default_factory=list)
    transformed_payload: Any = None
    replacement_count: int = 0
    content_sha256: str = ""
    reason: str = ""
