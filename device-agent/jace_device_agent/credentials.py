from __future__ import annotations

import os

SERVICE_NAME = "Jace Device Agent"


class CredentialStore:
    """Store Device Agent secrets in the operating-system credential backend.

    The normal Windows path uses `keyring`, which uses the platform credential
    backend. Tests may opt into an in-memory test token through an environment
    variable without writing credentials.
    """

    def set_device_token(self, device_id: str, token: str) -> None:
        if os.getenv("JACE_DEVICE_AGENT_TEST_TOKEN_STORE") == "memory":
            os.environ["JACE_DEVICE_AGENT_TEST_TOKEN"] = token
            return

        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError(
                "The Device Agent requires the `keyring` package. "
                "Run device-agent\\install.ps1."
            ) from exc

        keyring.set_password(SERVICE_NAME, device_id, token)

    def get_device_token(self, device_id: str) -> str | None:
        if os.getenv("JACE_DEVICE_AGENT_TEST_TOKEN_STORE") == "memory":
            return os.getenv("JACE_DEVICE_AGENT_TEST_TOKEN")

        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError(
                "The Device Agent requires the `keyring` package. "
                "Run device-agent\\install.ps1."
            ) from exc

        return keyring.get_password(SERVICE_NAME, device_id)

    def delete_device_token(self, device_id: str) -> None:
        if os.getenv("JACE_DEVICE_AGENT_TEST_TOKEN_STORE") == "memory":
            os.environ.pop("JACE_DEVICE_AGENT_TEST_TOKEN", None)
            return

        try:
            import keyring
        except ImportError:
            return

        try:
            keyring.delete_password(SERVICE_NAME, device_id)
        except keyring.errors.PasswordDeleteError:
            pass


credential_store = CredentialStore()
