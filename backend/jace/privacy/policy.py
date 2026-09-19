from __future__ import annotations

from jace.privacy.types import PrivacyClassification, PrivacyMode


_MODE_RANK = {
    "cloud_allowed": 0,
    "protected_cloud": 1,
    "local_only": 2,
}

_DEFAULT_MODE: dict[PrivacyClassification, PrivacyMode] = {
    "public": "cloud_allowed",
    "internal": "protected_cloud",
    "confidential": "protected_cloud",
    "personal": "protected_cloud",
    "secret": "local_only",
}


def default_mode_for_classification(
    classification: PrivacyClassification,
) -> PrivacyMode:
    return _DEFAULT_MODE[classification]


def effective_mode(
    classification: PrivacyClassification,
    requested_mode: PrivacyMode | None,
) -> PrivacyMode:
    mode = _DEFAULT_MODE[classification]

    if (
        requested_mode is not None
        and _MODE_RANK[requested_mode] > _MODE_RANK[mode]
    ):
        mode = requested_mode

    return mode
