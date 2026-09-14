from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CapabilityRisk = Literal["read", "write", "execute"]
CapabilityPermissionMode = Literal["allow", "ask", "deny"]
ProviderSetupState = Literal["available"]
OAuthFlowKind = Literal["authorization_code_pkce", "device_code"]


@dataclass(frozen=True)
class ProviderCapability:
    id: str
    label: str
    description: str
    category: str
    risk: CapabilityRisk
    required_scopes: tuple[str, ...] = ()
    default_permission: CapabilityPermissionMode = "ask"
    tool_name: str | None = None


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    description: str
    auth_kind: str
    setup_state: ProviderSetupState
    connection_label: str
    capabilities: tuple[ProviderCapability, ...]
    oauth_flow: OAuthFlowKind | None = None
    oauth_scopes: tuple[str, ...] = ()
    oauth_client_secret_supported: bool = False
    oauth_tenant_supported: bool = False


GOOGLE = ProviderDefinition(
    id="google",
    name="Google",
    description=(
        "Google account identity is connected now. Gmail, Calendar and Drive "
        "capabilities are enabled only when the account has the required OAuth access."
    ),
    auth_kind="oauth2",
    setup_state="available",
    connection_label="Google account",
    oauth_flow="authorization_code_pkce",
    # 4C.1 adds the narrowest Gmail scope that supports real message reads.
    # Draft/send/modify scopes remain intentionally excluded.
    oauth_scopes=(
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.readonly",
    ),
    oauth_client_secret_supported=True,
    capabilities=(
        ProviderCapability(
            "email.read",
            "Read email",
            "Read Gmail messages and threads.",
            "Email",
            "read",
            required_scopes=("https://www.googleapis.com/auth/gmail.readonly",),
            default_permission="allow",
            tool_name="gmail_read_email",
        ),
        ProviderCapability(
            "email.search",
            "Search email",
            "Search Gmail mailbox content and metadata.",
            "Email",
            "read",
            required_scopes=("https://www.googleapis.com/auth/gmail.readonly",),
            default_permission="allow",
            tool_name="gmail_search_email",
        ),
        ProviderCapability(
            "email.draft",
            "Draft email",
            "Create or edit a Gmail draft without sending it.",
            "Email",
            "write",
            required_scopes=("https://www.googleapis.com/auth/gmail.compose",),
            default_permission="ask",
        ),
        ProviderCapability(
            "email.send",
            "Send email",
            "Send an approved Gmail message.",
            "Email",
            "write",
            required_scopes=("https://www.googleapis.com/auth/gmail.send",),
            default_permission="ask",
        ),
        ProviderCapability(
            "calendar.read",
            "Read calendar",
            "Inspect Google Calendar events and availability.",
            "Calendar",
            "read",
            required_scopes=("https://www.googleapis.com/auth/calendar.readonly",),
            default_permission="allow",
        ),
        ProviderCapability(
            "calendar.create",
            "Create event",
            "Create an approved Google Calendar event.",
            "Calendar",
            "write",
            required_scopes=("https://www.googleapis.com/auth/calendar.events",),
            default_permission="ask",
        ),
        ProviderCapability(
            "calendar.modify",
            "Modify event",
            "Change an existing Google Calendar event.",
            "Calendar",
            "write",
            required_scopes=("https://www.googleapis.com/auth/calendar.events",),
            default_permission="ask",
        ),
        ProviderCapability(
            "files.read",
            "Read Drive files",
            "Read explicitly accessible Google Drive files.",
            "Files",
            "read",
            required_scopes=("https://www.googleapis.com/auth/drive.readonly",),
            default_permission="allow",
        ),
    ),
)


MICROSOFT = ProviderDefinition(
    id="microsoft",
    name="Microsoft",
    description=(
        "Microsoft account identity is connected now. Outlook, Calendar and "
        "OneDrive capabilities are enabled only when the account has the required Graph access."
    ),
    auth_kind="oauth2",
    setup_state="available",
    connection_label="Microsoft account",
    oauth_flow="authorization_code_pkce",
    # 4A.2 identity/profile access only.
    oauth_scopes=("openid", "profile", "email", "offline_access", "User.Read"),
    oauth_tenant_supported=True,
    capabilities=(
        ProviderCapability(
            "email.read",
            "Read email",
            "Read Outlook messages and threads.",
            "Email",
            "read",
            required_scopes=("Mail.Read",),
            default_permission="allow",
        ),
        ProviderCapability(
            "email.search",
            "Search email",
            "Search Outlook mailbox content and metadata.",
            "Email",
            "read",
            required_scopes=("Mail.Read",),
            default_permission="allow",
        ),
        ProviderCapability(
            "email.draft",
            "Draft email",
            "Create or edit an Outlook draft without sending it.",
            "Email",
            "write",
            required_scopes=("Mail.ReadWrite",),
            default_permission="ask",
        ),
        ProviderCapability(
            "email.send",
            "Send email",
            "Send an approved Outlook message.",
            "Email",
            "write",
            required_scopes=("Mail.Send",),
            default_permission="ask",
        ),
        ProviderCapability(
            "calendar.read",
            "Read calendar",
            "Inspect Microsoft calendar events and availability.",
            "Calendar",
            "read",
            required_scopes=("Calendars.Read",),
            default_permission="allow",
        ),
        ProviderCapability(
            "calendar.create",
            "Create event",
            "Create an approved Microsoft calendar event.",
            "Calendar",
            "write",
            required_scopes=("Calendars.ReadWrite",),
            default_permission="ask",
        ),
        ProviderCapability(
            "calendar.modify",
            "Modify event",
            "Change an existing Microsoft calendar event.",
            "Calendar",
            "write",
            required_scopes=("Calendars.ReadWrite",),
            default_permission="ask",
        ),
        ProviderCapability(
            "files.read",
            "Read OneDrive files",
            "Read explicitly accessible OneDrive files.",
            "Files",
            "read",
            required_scopes=("Files.Read",),
            default_permission="allow",
        ),
    ),
)


GITHUB = ProviderDefinition(
    id="github",
    name="GitHub",
    description=(
        "GitHub identity is connected with device flow. Repository capabilities "
        "remain unavailable until Jace has the repository scope required for private content."
    ),
    auth_kind="oauth2",
    setup_state="available",
    connection_label="GitHub account",
    oauth_flow="device_code",
    oauth_scopes=("read:user", "user:email"),
    capabilities=(
        ProviderCapability(
            "repositories.read",
            "Read repositories",
            "Read accessible public and private repository metadata and content.",
            "Code",
            "read",
            required_scopes=("repo",),
            default_permission="allow",
        ),
        ProviderCapability(
            "repositories.search",
            "Search repositories",
            "Search accessible public and private repositories and code context.",
            "Code",
            "read",
            required_scopes=("repo",),
            default_permission="allow",
        ),
        ProviderCapability(
            "issues.read",
            "Read issues",
            "Read issues and discussion metadata in accessible repositories.",
            "Code",
            "read",
            required_scopes=("repo",),
            default_permission="allow",
        ),
        ProviderCapability(
            "issues.write",
            "Manage issues",
            "Create or update issues after approval.",
            "Code",
            "write",
            required_scopes=("repo",),
            default_permission="ask",
        ),
        ProviderCapability(
            "pull_requests.read",
            "Read pull requests",
            "Inspect pull requests, reviews and checks in accessible repositories.",
            "Code",
            "read",
            required_scopes=("repo",),
            default_permission="allow",
        ),
    ),
)


CUSTOM_API = ProviderDefinition(
    id="custom_api",
    name="Custom API",
    description=(
        "Store a reusable API endpoint and credential without placing the secret "
        "in Jace's database."
    ),
    auth_kind="api_key",
    setup_state="available",
    connection_label="API connection",
    capabilities=(
        ProviderCapability(
            "custom.request",
            "Custom API request",
            "A future guarded request capability bound to this configured endpoint.",
            "API",
            "write",
            default_permission="ask",
        ),
    ),
)


PROVIDERS: tuple[ProviderDefinition, ...] = (
    GOOGLE,
    MICROSOFT,
    GITHUB,
    CUSTOM_API,
)

PROVIDER_MAP = {
    provider.id: provider
    for provider in PROVIDERS
}

OAUTH_PROVIDERS = tuple(
    provider
    for provider in PROVIDERS
    if provider.oauth_flow is not None
)


def get_provider(provider_id: str) -> ProviderDefinition | None:
    return PROVIDER_MAP.get(provider_id)
