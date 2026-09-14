from __future__ import annotations

from jace.connections.providers import PROVIDERS, get_provider
from jace.connections.secrets import status


def main() -> None:
    ids = [provider.id for provider in PROVIDERS]
    assert ids == ["google", "microsoft", "github", "custom_api"], ids
    assert get_provider("custom_api") is not None
    assert get_provider("custom_api").setup_state == "available"
    assert get_provider("google").setup_state == "oauth_pending"
    vault = status()
    print(f"Providers: {', '.join(ids)}")
    print(f"Credential vault: {vault.backend} available={vault.available}")
    if vault.reason:
        print(f"Credential vault note: {vault.reason}")
    print("Step 4A.1 connection foundation smoke: OK")


if __name__ == "__main__":
    main()
