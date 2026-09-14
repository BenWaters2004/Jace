from __future__ import annotations

# JACE_STEP4A6_EXTERNAL_ACCESS_POLICY

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from jace.connections.models import ExternalAccessPolicyRecord
from jace.connections.providers import PROVIDERS
from jace.db.models import utc_now


POLICY_ID = "default"


@dataclass(frozen=True)
class ExternalAccessPolicy:
    external_services_enabled: bool
    providers: dict[str, bool]

    def provider_enabled(self, provider_id: str) -> bool:
        return (
            self.external_services_enabled
            and self.providers.get(provider_id, True)
        )

    def as_dict(self) -> dict:
        return {
            "external_services_enabled": self.external_services_enabled,
            "providers": dict(self.providers),
        }


def _loads_provider_states(value: str) -> dict[str, bool]:
    try:
        raw = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    return {
        str(key): bool(item)
        for key, item in raw.items()
    }


def _normalised_provider_states(
    raw: dict[str, bool] | None,
) -> dict[str, bool]:
    incoming = raw or {}
    known = {provider.id for provider in PROVIDERS}

    return {
        provider_id: bool(incoming.get(provider_id, True))
        for provider_id in sorted(known)
    }


async def get_or_create_external_access_policy(
    session: AsyncSession,
) -> ExternalAccessPolicyRecord:
    row = await session.get(
        ExternalAccessPolicyRecord,
        POLICY_ID,
    )

    if row is None:
        row = ExternalAccessPolicyRecord(
            id=POLICY_ID,
            external_services_enabled=True,
            provider_states_json=json.dumps(
                _normalised_provider_states(None),
                separators=(",", ":"),
            ),
            updated_at=utc_now(),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return row


async def external_access_policy(
    session: AsyncSession,
) -> ExternalAccessPolicy:
    row = await get_or_create_external_access_policy(
        session
    )

    return ExternalAccessPolicy(
        external_services_enabled=bool(
            row.external_services_enabled
        ),
        providers=_normalised_provider_states(
            _loads_provider_states(
                row.provider_states_json
            )
        ),
    )


async def update_external_access_policy(
    session: AsyncSession,
    *,
    external_services_enabled: bool | None = None,
    providers: dict[str, bool] | None = None,
) -> ExternalAccessPolicy:
    row = await get_or_create_external_access_policy(
        session
    )

    current = _normalised_provider_states(
        _loads_provider_states(
            row.provider_states_json
        )
    )

    if external_services_enabled is not None:
        row.external_services_enabled = bool(
            external_services_enabled
        )

    if providers is not None:
        known = {provider.id for provider in PROVIDERS}

        unknown = set(providers) - known
        if unknown:
            raise ValueError(
                "Unknown external provider(s): "
                + ", ".join(sorted(unknown))
            )

        for provider_id, enabled in providers.items():
            current[provider_id] = bool(enabled)

    row.provider_states_json = json.dumps(
        _normalised_provider_states(current),
        separators=(",", ":"),
    )
    row.updated_at = utc_now()

    await session.commit()
    await session.refresh(row)

    return ExternalAccessPolicy(
        external_services_enabled=bool(
            row.external_services_enabled
        ),
        providers=_normalised_provider_states(
            _loads_provider_states(
                row.provider_states_json
            )
        ),
    )
