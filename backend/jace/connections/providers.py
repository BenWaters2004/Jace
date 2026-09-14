from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CapabilityRisk = Literal["read", "write", "execute"]
ProviderSetupState = Literal["available", "oauth_pending"]


@dataclass(frozen=True)
class ProviderCapability:
    id: str
    label: str
    description: str
    category: str
    risk: CapabilityRisk


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    description: str
    auth_kind: str
    setup_state: ProviderSetupState
    connection_label: str
    capabilities: tuple[ProviderCapability, ...]


GOOGLE = ProviderDefinition(
    id="google",
    name="Google",
    description="Personal Gmail, Google Calendar and future Drive access.",
    auth_kind="oauth2",
    setup_state="oauth_pending",
    connection_label="Google account",
    capabilities=(
        ProviderCapability("email.read", "Read email", "Read messages and threads.", "Email", "read"),
        ProviderCapability("email.search", "Search email", "Search mailbox content and metadata.", "Email", "read"),
        ProviderCapability("email.draft", "Draft email", "Create a draft without sending it.", "Email", "write"),
        ProviderCapability("email.send", "Send email", "Send an approved email message.", "Email", "write"),
        ProviderCapability("calendar.read", "Read calendar", "Inspect events and availability.", "Calendar", "read"),
        ProviderCapability("calendar.create", "Create event", "Create an approved calendar event.", "Calendar", "write"),
        ProviderCapability("calendar.modify", "Modify event", "Change an existing calendar event.", "Calendar", "write"),
        ProviderCapability("files.read", "Read Drive files", "Read explicitly accessible Drive files.", "Files", "read"),
    ),
)

MICROSOFT = ProviderDefinition(
    id="microsoft",
    name="Microsoft",
    description="Outlook / Microsoft 365, Calendar and future OneDrive access.",
    auth_kind="oauth2",
    setup_state="oauth_pending",
    connection_label="Microsoft account",
    capabilities=(
        ProviderCapability("email.read", "Read email", "Read Outlook messages and threads.", "Email", "read"),
        ProviderCapability("email.search", "Search email", "Search Outlook mailbox content and metadata.", "Email", "read"),
        ProviderCapability("email.draft", "Draft email", "Create a draft without sending it.", "Email", "write"),
        ProviderCapability("email.send", "Send email", "Send an approved Outlook message.", "Email", "write"),
        ProviderCapability("calendar.read", "Read calendar", "Inspect Microsoft calendar events and availability.", "Calendar", "read"),
        ProviderCapability("calendar.create", "Create event", "Create an approved Microsoft calendar event.", "Calendar", "write"),
        ProviderCapability("calendar.modify", "Modify event", "Change an existing Microsoft calendar event.", "Calendar", "write"),
        ProviderCapability("files.read", "Read OneDrive files", "Read explicitly accessible OneDrive files.", "Files", "read"),
    ),
)

GITHUB = ProviderDefinition(
    id="github",
    name="GitHub",
    description="Repository context, issues, pull requests and development workflows.",
    auth_kind="oauth2",
    setup_state="oauth_pending",
    connection_label="GitHub account",
    capabilities=(
        ProviderCapability("repositories.read", "Read repositories", "Read repository metadata and content.", "Code", "read"),
        ProviderCapability("repositories.search", "Search repositories", "Search accessible repositories and code context.", "Code", "read"),
        ProviderCapability("issues.read", "Read issues", "Read issues and discussion metadata.", "Code", "read"),
        ProviderCapability("issues.write", "Manage issues", "Create or update issues after approval.", "Code", "write"),
        ProviderCapability("pull_requests.read", "Read pull requests", "Inspect pull requests, reviews and checks.", "Code", "read"),
    ),
)

CUSTOM_API = ProviderDefinition(
    id="custom_api",
    name="Custom API",
    description="Store a reusable API endpoint and credential without placing the secret in Jace's database.",
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
        ),
    ),
)

PROVIDERS: tuple[ProviderDefinition, ...] = (GOOGLE, MICROSOFT, GITHUB, CUSTOM_API)
PROVIDER_MAP = {provider.id: provider for provider in PROVIDERS}


def get_provider(provider_id: str) -> ProviderDefinition | None:
    return PROVIDER_MAP.get(provider_id)
