from __future__ import annotations

import asyncio
from jace.connections.oauth import _pkce_pair
from jace.connections.providers import GITHUB, GOOGLE, MICROSOFT

async def main() -> None:
    verifier, challenge = _pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43
    assert GOOGLE.oauth_flow == "authorization_code_pkce"
    assert MICROSOFT.oauth_flow == "authorization_code_pkce"
    assert GITHUB.oauth_flow == "device_code"
    assert "openid" in GOOGLE.oauth_scopes
    assert "offline_access" in MICROSOFT.oauth_scopes
    assert "read:user" in GITHUB.oauth_scopes
    print("Step 4A.2 OAuth provider smoke: OK")

if __name__ == "__main__": asyncio.run(main())
