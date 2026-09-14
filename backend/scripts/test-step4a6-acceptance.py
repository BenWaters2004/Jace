from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:8000"


def request(
    method: str,
    path: str,
    payload: dict | None = None,
):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=15,
        ) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )
        raise RuntimeError(
            f"{method} {path} returned {exc.code}: {body}"
        ) from exc

    if not raw:
        return None

    return json.loads(raw)


def active_provider_connections(
    connection_payload: dict,
    provider_id: str,
) -> list[dict]:
    return [
        row
        for row in connection_payload.get(
            "connections",
            [],
        )
        if row.get("provider_id") == provider_id
        and row.get("status") not in {
            "disconnected",
            "error",
        }
    ]


def assert_provider_blocked(
    provider_id: str,
    reason: str,
) -> None:
    snapshot = request(
        "GET",
        "/capabilities",
    )

    rows = [
        row
        for row in snapshot.get(
            "capabilities",
            [],
        )
        if row.get("source") == "connection"
        and row.get("provider_id") == provider_id
        and row.get("connection_id")
        and row.get("connection_status")
        not in {
            "disconnected",
            "error",
        }
    ]

    if not rows:
        raise RuntimeError(
            f"No active {provider_id} capability bindings were found."
        )

    incorrect = [
        row
        for row in rows
        if row.get("state") != "blocked"
        or row.get("availability_reason") != reason
    ]

    if incorrect:
        raise RuntimeError(
            f"{provider_id} was not consistently blocked by {reason}: "
            + json.dumps(
                incorrect[:3],
                indent=2,
            )
        )


def main() -> int:
    print()
    print("Jace Step 4A.6 final acceptance test")
    print("====================================")
    print()

    request(
        "GET",
        "/health",
    )
    print("Backend reachable: PASS")

    connections = request(
        "GET",
        "/connections",
    )

    for provider_id in (
        "google",
        "microsoft",
        "github",
    ):
        if not active_provider_connections(
            connections,
            provider_id,
        ):
            raise RuntimeError(
                f"Expected an active {provider_id} connection."
            )

    print(
        "Google + Microsoft + GitHub connected: PASS"
    )

    original = request(
        "GET",
        "/security/external-access",
    )

    original_enabled = bool(
        original.get(
            "external_services_enabled",
            True,
        )
    )
    original_providers = dict(
        original.get(
            "providers",
            {},
        )
    )

    try:
        request(
            "PATCH",
            "/security/external-access",
            {
                "external_services_enabled": True,
                "providers": {
                    "google": False,
                },
            },
        )

        assert_provider_blocked(
            "google",
            "provider_disabled",
        )

        print(
            "Per-provider kill switch: PASS"
        )

        request(
            "PATCH",
            "/security/external-access",
            {
                "providers": {
                    "google": True,
                },
            },
        )

        request(
            "PATCH",
            "/security/external-access",
            {
                "external_services_enabled": False,
            },
        )

        for provider_id in (
            "google",
            "microsoft",
            "github",
        ):
            assert_provider_blocked(
                provider_id,
                "external_services_disabled",
            )

        print(
            "External-services master switch: PASS"
        )

    finally:
        request(
            "PATCH",
            "/security/external-access",
            {
                "external_services_enabled": original_enabled,
                "providers": original_providers,
            },
        )

    restored = request(
        "GET",
        "/security/external-access",
    )

    if (
        bool(
            restored.get(
                "external_services_enabled",
            )
        )
        != original_enabled
        or dict(
            restored.get(
                "providers",
                {},
            )
        )
        != original_providers
    ):
        raise RuntimeError(
            "The original external access policy was not restored exactly."
        )

    print(
        "Policy restoration: PASS"
    )

    resolver = request(
        "POST",
        "/capabilities/resolve",
        {
            "message": (
                "Search my email for recent messages."
            ),
        },
    )

    email_resolution = next(
        (
            row
            for row in resolver.get(
                "resolutions",
                [],
            )
            if row.get(
                "capability_id"
            ) == "email.search"
        ),
        None,
    )

    if email_resolution is None:
        raise RuntimeError(
            "The runtime resolver did not detect email.search."
        )

    candidate_connections = {
        row.get("connection_id")
        for row in email_resolution.get(
            "candidates",
            [],
        )
        if row.get("connection_id")
    }

    if (
        len(candidate_connections) >= 2
        and email_resolution.get("status")
        not in {
            "ambiguous",
            "ready",
        }
    ):
        raise RuntimeError(
            "Multiple email-capable accounts were present but the "
            "resolver did not return a safe ambiguity/readiness outcome."
        )

    print(
        "Multi-account resolver behaviour: PASS "
        f"({email_resolution.get('status')})"
    )

    audit = request(
        "GET",
        "/tools/audit?limit=10",
    )

    if not isinstance(
        audit.get(
            "entries",
            [],
        ),
        list,
    ):
        raise RuntimeError(
            "Tool audit endpoint returned an invalid payload."
        )

    print(
        "Audit endpoint: PASS"
    )

    print()
    print(
        "PASS - Step 4A.6 Connections & Capabilities acceptance passed."
    )
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except Exception as exc:
        print()
        print(
            f"FAIL - {exc}",
            file=sys.stderr,
        )
        print()
        raise
