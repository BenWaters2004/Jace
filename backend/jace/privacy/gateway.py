from __future__ import annotations

import hashlib
import json
from typing import Any

from jace.config import settings
from jace.privacy.classifier import inspect_payload
from jace.privacy.policy import effective_mode
from jace.privacy.transform import PrivacyTransform
from jace.privacy.types import (
    PrivacyClassification,
    PrivacyDecision,
    PrivacyMode,
)


_VALID_CLASSIFICATIONS = {
    "public",
    "internal",
    "confidential",
    "personal",
    "secret",
}

_VALID_MODES = {
    "cloud_allowed",
    "protected_cloud",
    "local_only",
}


class PrivacyGateway:
    """Deterministic privacy policy for model/data egress."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        cloud_egress_enabled: bool | None = None,
        default_classification: str | None = None,
    ) -> None:
        self.enabled = (
            settings.privacy_enabled
            if enabled is None
            else enabled
        )
        self.cloud_egress_enabled = (
            settings.privacy_cloud_egress_enabled
            if cloud_egress_enabled is None
            else cloud_egress_enabled
        )
        self.default_classification = (
            default_classification
            or settings.privacy_default_classification
        )

        if self.default_classification not in _VALID_CLASSIFICATIONS:
            raise ValueError("Invalid default privacy classification.")

    def inspect(
        self,
        payload: Any,
        *,
        classification_hint: str | None = None,
        requested_mode: str | None = None,
    ) -> PrivacyDecision:
        hint: PrivacyClassification | None = None

        if classification_hint is not None:
            candidate = classification_hint.strip().lower()
            if candidate not in _VALID_CLASSIFICATIONS:
                raise ValueError(
                    f"Invalid privacy classification: {classification_hint}"
                )
            hint = candidate  # type: ignore[assignment]

        mode_hint: PrivacyMode | None = None

        if requested_mode is not None:
            candidate = requested_mode.strip().lower()
            if candidate not in _VALID_MODES:
                raise ValueError(
                    f"Invalid privacy mode: {requested_mode}"
                )
            mode_hint = candidate  # type: ignore[assignment]

        classification, detections = inspect_payload(
            payload,
            default_classification=self.default_classification,  # type: ignore[arg-type]
            classification_hint=hint,
        )

        mode = effective_mode(
            classification,
            mode_hint,
        )

        serialised = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        return PrivacyDecision(
            classification=classification,
            mode=mode,
            action="local",
            require_local=mode == "local_only",
            detections=detections,
            transformed_payload=payload,
            content_sha256=hashlib.sha256(
                serialised.encode("utf-8")
            ).hexdigest(),
            reason="Inspection only.",
        )

    def prepare_for_provider(
        self,
        payload: Any,
        *,
        provider_local: bool,
        provider_supports_protected_cloud: bool,
        classification_hint: str | None = None,
        requested_mode: str | None = None,
    ) -> PrivacyDecision:
        decision = self.inspect(
            payload,
            classification_hint=classification_hint,
            requested_mode=requested_mode,
        )

        if not self.enabled:
            decision.action = (
                "local" if provider_local else "raw_cloud"
            )
            decision.require_local = False
            decision.reason = "Privacy Gateway disabled."
            return decision

        if provider_local:
            # Local inference keeps the original payload unchanged.
            decision.action = "local"
            decision.require_local = False
            decision.transformed_payload = payload
            decision.reason = (
                "Provider is local; original payload retained."
            )
            return decision

        if not self.cloud_egress_enabled:
            decision.action = "reroute_local"
            decision.require_local = True
            decision.reason = (
                "Cloud model egress is disabled by Jace privacy settings."
            )
            return decision

        if decision.mode == "local_only":
            decision.action = "reroute_local"
            decision.require_local = True
            decision.reason = (
                "Privacy policy requires local-only processing."
            )
            return decision

        if decision.mode == "protected_cloud":
            if not provider_supports_protected_cloud:
                decision.action = "reroute_local"
                decision.require_local = True
                decision.reason = (
                    "Selected provider is not approved for protected-cloud "
                    "processing."
                )
                return decision

            transformer = PrivacyTransform()
            decision.transformed_payload = transformer.protect_payload(
                payload
            )
            decision.replacement_count = transformer.replacement_count
            decision.action = "protected_cloud"
            decision.require_local = False
            decision.reason = (
                "Protected-cloud transformation applied before egress."
            )
            return decision

        decision.action = "raw_cloud"
        decision.require_local = False
        decision.transformed_payload = payload
        decision.reason = (
            "Content is permitted for normal cloud processing."
        )
        return decision


privacy_gateway = PrivacyGateway()
