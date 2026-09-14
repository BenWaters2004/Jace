from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets as secure_random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from jace.connections import secrets
from jace.connections.models import ConnectionRecord
from jace.connections.providers import ProviderDefinition, get_provider
from jace.connections.schemas import OAuthSessionResponse, OAuthStartResponse
from jace.connections.service import (
    OAUTH_TOKEN_KEY,
    _loads_object,
    get_oauth_client_config,
    list_provider_connections,
    oauth_client_secret,
)
from jace.db.models import utc_now

GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REDIRECT = "http://127.0.0.1:8000"

MICROSOFT_GRAPH_ME = "https://graph.microsoft.com/v1.0/me"
MICROSOFT_REDIRECT = "http://localhost:8000"

GITHUB_DEVICE_CODE = "https://github.com/login/device/code"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"
GITHUB_EMAILS = "https://api.github.com/user/emails"

SESSION_TTL_SECONDS = 10 * 60
HTTP_TIMEOUT_SECONDS = 20.0


@dataclass
class OAuthFlowSession:
    session_id: str
    provider_id: str
    flow_kind: str
    status: str
    created_at: datetime
    expires_at: datetime
    poll_interval_seconds: int = 2
    authorization_url: str | None = None
    state: str | None = None
    code_verifier: str | None = None
    device_code: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    next_poll_at_epoch: float = 0.0
    connection_id: str | None = None
    account_hint: str | None = None
    error: str | None = None


_sessions: dict[str, OAuthFlowSession] = {}
_state_to_session: dict[str, str] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:600]
    return fallback


def _purge_expired() -> None:
    now = _now()
    stale: list[str] = []
    for session_id, flow in _sessions.items():
        if flow.status == "pending" and flow.expires_at <= now:
            flow.status = "expired"
            flow.error = "The OAuth authorization window expired. Start the connection again."
        if flow.expires_at + timedelta(minutes=20) <= now:
            stale.append(session_id)
    for session_id in stale:
        flow = _sessions.pop(session_id, None)
        if flow and flow.state:
            _state_to_session.pop(flow.state, None)


def _provider_or_error(provider_id: str) -> ProviderDefinition:
    provider = get_provider(provider_id)
    if provider is None or provider.oauth_flow is None:
        raise ValueError("This provider does not support OAuth account connections.")
    return provider


def _pkce_pair() -> tuple[str, str]:
    verifier = secure_random.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def _new_session(provider: ProviderDefinition, *, ttl_seconds: int = SESSION_TTL_SECONDS) -> OAuthFlowSession:
    created = _now()
    flow = OAuthFlowSession(
        session_id=secure_random.token_urlsafe(24),
        provider_id=provider.id,
        flow_kind=provider.oauth_flow or "authorization_code_pkce",
        status="pending",
        created_at=created,
        expires_at=created + timedelta(seconds=ttl_seconds),
    )
    _sessions[flow.session_id] = flow
    return flow


def _redirect_uri(provider_id: str) -> str:
    if provider_id == "google":
        return GOOGLE_REDIRECT
    if provider_id == "microsoft":
        return MICROSOFT_REDIRECT
    raise ValueError("This provider does not use a loopback redirect.")


def _oauth_config_dict(row) -> dict:
    return _loads_object(row.config_json) if row is not None else {}


async def _client_config(session: AsyncSession, provider: ProviderDefinition):
    row = await get_oauth_client_config(session, provider.id)
    if row is None or not row.client_id.strip():
        raise ValueError(f"Configure the {provider.name} OAuth application before connecting an account.")
    return row


def _microsoft_tenant(config: dict) -> str:
    tenant = config.get("tenant")
    if not isinstance(tenant, str) or not tenant:
        return "common"
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in tenant):
        raise ValueError("Stored Microsoft tenant is invalid.")
    return tenant


def _session_start_response(flow: OAuthFlowSession) -> OAuthStartResponse:
    return OAuthStartResponse(
        session_id=flow.session_id,
        provider_id=flow.provider_id,
        flow_kind=flow.flow_kind,
        status=flow.status,
        authorization_url=flow.authorization_url,
        verification_uri=flow.verification_uri,
        user_code=flow.user_code,
        expires_at=flow.expires_at,
        poll_interval_seconds=flow.poll_interval_seconds,
    )


def _session_response(flow: OAuthFlowSession) -> OAuthSessionResponse:
    return OAuthSessionResponse(
        session_id=flow.session_id,
        provider_id=flow.provider_id,
        flow_kind=flow.flow_kind,
        status=flow.status,
        verification_uri=flow.verification_uri,
        user_code=flow.user_code,
        expires_at=flow.expires_at,
        poll_interval_seconds=flow.poll_interval_seconds,
        connection_id=flow.connection_id,
        account_hint=flow.account_hint,
        error=flow.error,
    )


async def start_oauth(session: AsyncSession, provider_id: str) -> OAuthStartResponse:
    _purge_expired()
    provider = _provider_or_error(provider_id)
    if not secrets.status().available:
        raise RuntimeError(secrets.status().reason or "Secure credential storage is unavailable.")
    config_row = await _client_config(session, provider)

    if provider.oauth_flow == "device_code":
        return await _start_github_device(provider, config_row.client_id)

    verifier, challenge = _pkce_pair()
    flow = _new_session(provider)
    flow.code_verifier = verifier
    flow.state = secure_random.token_urlsafe(32)
    _state_to_session[flow.state] = flow.session_id
    redirect_uri = _redirect_uri(provider.id)
    scope = " ".join(provider.oauth_scopes)

    if provider.id == "google":
        params = {
            "client_id": config_row.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": flow.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        flow.authorization_url = f"{GOOGLE_AUTHORIZE}?{urlencode(params)}"
    elif provider.id == "microsoft":
        config = _oauth_config_dict(config_row)
        tenant = _microsoft_tenant(config)
        params = {
            "client_id": config_row.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": scope,
            "state": flow.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        flow.authorization_url = (
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"
        )
    else:
        raise ValueError("Unsupported authorization-code provider.")

    return _session_start_response(flow)


async def _start_github_device(provider: ProviderDefinition, client_id: str) -> OAuthStartResponse:
    headers = {"Accept": "application/json", "User-Agent": "Jace-Desktop"}
    data = {"client_id": client_id, "scope": " ".join(provider.oauth_scopes)}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(GITHUB_DEVICE_CODE, data=data, headers=headers)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("GitHub returned an unreadable device-flow response.") from exc
    if response.status_code >= 400:
        raise RuntimeError(_safe_error(payload.get("error_description") or payload.get("error"), "GitHub device flow could not start."))

    device_code = payload.get("device_code")
    user_code = payload.get("user_code")
    verification_uri = payload.get("verification_uri") or payload.get("verification_uri_complete")
    if not all(isinstance(value, str) and value for value in (device_code, user_code, verification_uri)):
        raise RuntimeError("GitHub did not return the required device authorization fields.")

    expires_in = max(60, int(payload.get("expires_in") or 900))
    interval = max(5, int(payload.get("interval") or 5))
    flow = _new_session(provider, ttl_seconds=expires_in)
    flow.device_code = device_code
    flow.user_code = user_code
    flow.verification_uri = verification_uri
    flow.authorization_url = verification_uri
    flow.poll_interval_seconds = interval
    flow.next_poll_at_epoch = time.time() + interval
    return _session_start_response(flow)


async def oauth_session_status(session: AsyncSession, session_id: str) -> OAuthSessionResponse:
    _purge_expired()
    flow = _sessions.get(session_id)
    if flow is None:
        raise ValueError("OAuth session not found. Start the connection again.")
    if flow.status == "pending" and flow.provider_id == "github":
        await _poll_github_device(session, flow)
    return _session_response(flow)


async def _poll_github_device(session: AsyncSession, flow: OAuthFlowSession) -> None:
    if flow.status != "pending" or not flow.device_code:
        return
    if flow.expires_at <= _now():
        flow.status = "expired"
        flow.error = "The GitHub device code expired. Start the connection again."
        return
    if time.time() < flow.next_poll_at_epoch:
        return

    provider = _provider_or_error("github")
    config_row = await _client_config(session, provider)
    data = {
        "client_id": config_row.client_id,
        "device_code": flow.device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    headers = {"Accept": "application/json", "User-Agent": "Jace-Desktop"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(GITHUB_TOKEN, data=data, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        flow.status = "failed"
        flow.error = "GitHub returned an unreadable token response."
        return

    if isinstance(payload.get("access_token"), str):
        try:
            row = await _finalize_oauth_connection(session, provider, payload)
        except Exception as exc:
            flow.status = "failed"
            flow.error = _safe_error(str(exc), "Could not save the GitHub account.")
            return
        flow.status = "completed"
        flow.connection_id = row.id
        flow.account_hint = row.account_hint
        return

    error = payload.get("error")
    if error == "authorization_pending":
        flow.next_poll_at_epoch = time.time() + flow.poll_interval_seconds
        return
    if error == "slow_down":
        flow.poll_interval_seconds += 5
        flow.next_poll_at_epoch = time.time() + flow.poll_interval_seconds
        return
    if error in {"expired_token", "token_expired"}:
        flow.status = "expired"
        flow.error = "The GitHub device code expired. Start the connection again."
        return
    flow.status = "failed"
    flow.error = _safe_error(payload.get("error_description") or error, "GitHub authorization failed.")


async def complete_callback(
    session: AsyncSession,
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    error_description: str | None,
) -> OAuthFlowSession:
    _purge_expired()
    if not state:
        raise ValueError("OAuth callback is missing its state value.")
    session_id = _state_to_session.get(state)
    flow = _sessions.get(session_id or "")
    if flow is None or flow.state != state:
        raise ValueError("OAuth state is invalid or has expired.")
    if flow.status != "pending":
        return flow
    if flow.expires_at <= _now():
        flow.status = "expired"
        flow.error = "The OAuth authorization window expired. Start the connection again."
        return flow
    if error:
        flow.status = "failed"
        flow.error = _safe_error(error_description or error, "Authorization was declined or failed.")
        return flow
    if not code:
        flow.status = "failed"
        flow.error = "The provider did not return an authorization code."
        return flow

    provider = _provider_or_error(flow.provider_id)
    try:
        token_payload = await _exchange_code(session, provider, flow, code)
        row = await _finalize_oauth_connection(session, provider, token_payload)
    except Exception as exc:
        flow.status = "failed"
        flow.error = _safe_error(str(exc), "Could not complete the OAuth connection.")
        return flow

    flow.status = "completed"
    flow.connection_id = row.id
    flow.account_hint = row.account_hint
    return flow


async def _exchange_code(
    session: AsyncSession,
    provider: ProviderDefinition,
    flow: OAuthFlowSession,
    code: str,
) -> dict[str, Any]:
    config_row = await _client_config(session, provider)
    if not flow.code_verifier:
        raise RuntimeError("PKCE verifier is missing. Start the connection again.")
    redirect_uri = _redirect_uri(provider.id)
    data: dict[str, str] = {
        "client_id": config_row.client_id,
        "code": code,
        "code_verifier": flow.code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    headers = {"Accept": "application/json", "User-Agent": "Jace-Desktop"}

    if provider.id == "google":
        secret = oauth_client_secret("google")
        if secret:
            data["client_secret"] = secret
        endpoint = GOOGLE_TOKEN
    elif provider.id == "microsoft":
        config = _oauth_config_dict(config_row)
        tenant = _microsoft_tenant(config)
        data["scope"] = " ".join(provider.oauth_scopes)
        endpoint = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    else:
        raise RuntimeError("Unsupported authorization-code provider.")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(endpoint, data=data, headers=headers)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{provider.name} returned an unreadable token response.") from exc
    if response.status_code >= 400 or not isinstance(payload.get("access_token"), str):
        raise RuntimeError(
            _safe_error(payload.get("error_description") or payload.get("error"), f"{provider.name} token exchange failed.")
        )
    return payload


def _token_bundle(provider: ProviderDefinition, payload: dict[str, Any], previous: dict | None = None) -> dict[str, Any]:
    previous = dict(previous or {})
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(f"{provider.name} did not return an access token.")
    bundle: dict[str, Any] = {
        "provider_id": provider.id,
        "access_token": access_token,
        "token_type": str(payload.get("token_type") or previous.get("token_type") or "Bearer"),
        "obtained_at": time.time(),
    }
    refresh_token = payload.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        bundle["refresh_token"] = refresh_token
    elif isinstance(previous.get("refresh_token"), str):
        bundle["refresh_token"] = previous["refresh_token"]

    expires_in = payload.get("expires_in")
    try:
        if expires_in is not None:
            bundle["expires_at"] = time.time() + max(0, int(expires_in))
    except (TypeError, ValueError):
        pass
    if "expires_at" not in bundle and isinstance(previous.get("expires_at"), (int, float)):
        bundle["expires_at"] = previous["expires_at"]

    refresh_expires_in = payload.get("refresh_token_expires_in")
    try:
        if refresh_expires_in is not None:
            bundle["refresh_expires_at"] = time.time() + max(0, int(refresh_expires_in))
    except (TypeError, ValueError):
        pass

    scope = payload.get("scope")
    if isinstance(scope, str):
        bundle["scope"] = scope
    elif isinstance(previous.get("scope"), str):
        bundle["scope"] = previous["scope"]
    else:
        bundle["scope"] = " ".join(provider.oauth_scopes)
    return bundle


def _read_token_bundle(connection_id: str) -> dict[str, Any]:
    raw = secrets.read(connection_id, OAUTH_TOKEN_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_token_bundle(connection_id: str, bundle: dict[str, Any]) -> None:
    secrets.write(connection_id, OAUTH_TOKEN_KEY, json.dumps(bundle, separators=(",", ":")))


async def _identity(provider: ProviderDefinition, access_token: str) -> dict[str, str | None]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "Jace-Desktop",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        if provider.id == "google":
            response = await client.get(GOOGLE_USERINFO, headers=headers)
            payload = _json_or_error(response, "Google identity lookup failed.")
            return {
                "subject": _required_identity(payload.get("sub"), "Google account ID"),
                "email": _optional_string(payload.get("email")),
                "display_name": _optional_string(payload.get("name")),
                "avatar_url": _optional_string(payload.get("picture")),
            }
        if provider.id == "microsoft":
            response = await client.get(MICROSOFT_GRAPH_ME, headers=headers, params={"$select": "id,displayName,mail,userPrincipalName"})
            payload = _json_or_error(response, "Microsoft identity lookup failed.")
            return {
                "subject": _required_identity(payload.get("id"), "Microsoft account ID"),
                "email": _optional_string(payload.get("mail")) or _optional_string(payload.get("userPrincipalName")),
                "display_name": _optional_string(payload.get("displayName")),
                "avatar_url": None,
            }
        if provider.id == "github":
            response = await client.get(GITHUB_USER, headers=headers)
            payload = _json_or_error(response, "GitHub identity lookup failed.")
            email = _optional_string(payload.get("email"))
            if not email:
                email_response = await client.get(GITHUB_EMAILS, headers=headers)
                if email_response.status_code < 400:
                    try:
                        email_rows = email_response.json()
                    except ValueError:
                        email_rows = []
                    if isinstance(email_rows, list):
                        preferred = next(
                            (
                                row.get("email")
                                for row in email_rows
                                if isinstance(row, dict) and row.get("primary") is True and row.get("verified") is True
                            ),
                            None,
                        )
                        email = _optional_string(preferred)
            return {
                "subject": _required_identity(payload.get("id"), "GitHub account ID"),
                "email": email,
                "display_name": _optional_string(payload.get("name")) or _optional_string(payload.get("login")),
                "avatar_url": _optional_string(payload.get("avatar_url")),
                "login": _optional_string(payload.get("login")),
            }
    raise RuntimeError("Unsupported OAuth identity provider.")


def _json_or_error(response: httpx.Response, fallback: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(fallback) from exc
    if response.status_code >= 400 or not isinstance(payload, dict):
        detail = payload.get("error_description") if isinstance(payload, dict) else None
        if not detail and isinstance(payload, dict):
            raw_error = payload.get("error")
            if isinstance(raw_error, dict):
                detail = raw_error.get("message")
            elif isinstance(raw_error, str):
                detail = raw_error
        raise RuntimeError(_safe_error(detail, fallback))
    return payload


def _required_identity(value: Any, label: str) -> str:
    if isinstance(value, (str, int)) and str(value):
        return str(value)
    raise RuntimeError(f"Provider response did not include {label}.")


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _finalize_oauth_connection(
    session: AsyncSession,
    provider: ProviderDefinition,
    token_payload: dict[str, Any],
) -> ConnectionRecord:
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str):
        raise RuntimeError("Access token is missing.")
    identity = await _identity(provider, access_token)
    subject = str(identity["subject"])
    rows = await list_provider_connections(session, provider.id)
    row = next((candidate for candidate in rows if _loads_object(candidate.config_json).get("oauth_subject") == subject), None)
    now = utc_now()
    email = _optional_string(identity.get("email"))
    login = _optional_string(identity.get("login"))
    display_name = _optional_string(identity.get("display_name"))
    account_hint = email or login or display_name or subject
    config = {
        "oauth_subject": subject,
        "display_name": display_name,
        "email": email,
        "login": login,
        "avatar_url": _optional_string(identity.get("avatar_url")),
        "scopes": list(provider.oauth_scopes),
    }
    config = {key: value for key, value in config.items() if value is not None}

    if row is None:
        row = ConnectionRecord(
            provider_id=provider.id,
            label=f"{provider.name} — {account_hint}",
            status="configured",
            auth_type="oauth2",
            config_json=json.dumps(config, separators=(",", ":")),
            capabilities_json=json.dumps([capability.id for capability in provider.capabilities]),
            account_hint=account_hint,
            updated_at=now,
            last_verified_at=now,
        )
        session.add(row)
        await session.flush()
    else:
        row.label = f"{provider.name} — {account_hint}"
        row.status = "configured"
        row.auth_type = "oauth2"
        row.config_json = json.dumps(config, separators=(",", ":"))
        row.capabilities_json = json.dumps([capability.id for capability in provider.capabilities])
        row.account_hint = account_hint
        row.updated_at = now
        row.last_verified_at = now
        row.last_error = None

    previous = _read_token_bundle(row.id)
    bundle = _token_bundle(provider, token_payload, previous)
    try:
        _write_token_bundle(row.id, bundle)
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    await session.refresh(row)
    return row


async def valid_access_token(session: AsyncSession, row: ConnectionRecord) -> str:
    provider = _provider_or_error(row.provider_id)
    bundle = _read_token_bundle(row.id)
    access_token = bundle.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("OAuth token is missing. Reconnect this account.")
    expires_at = bundle.get("expires_at")
    if not isinstance(expires_at, (int, float)) or expires_at > time.time() + 60:
        return access_token
    refresh_token = bundle.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("The provider token expired and cannot be refreshed. Reconnect this account.")

    config_row = await _client_config(session, provider)
    data: dict[str, str] = {
        "client_id": config_row.client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Accept": "application/json", "User-Agent": "Jace-Desktop"}
    if provider.id == "google":
        secret = oauth_client_secret("google")
        if secret:
            data["client_secret"] = secret
        endpoint = GOOGLE_TOKEN
    elif provider.id == "microsoft":
        config = _oauth_config_dict(config_row)
        tenant = _microsoft_tenant(config)
        data["scope"] = str(bundle.get("scope") or " ".join(provider.oauth_scopes))
        endpoint = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    elif provider.id == "github":
        endpoint = GITHUB_TOKEN
    else:
        raise RuntimeError("Unsupported token refresh provider.")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(endpoint, data=data, headers=headers)
    payload = _json_or_error(response, f"{provider.name} token refresh failed.")
    refreshed = _token_bundle(provider, payload, bundle)
    _write_token_bundle(row.id, refreshed)
    return str(refreshed["access_token"])


async def verify_oauth_connection(session: AsyncSession, row: ConnectionRecord) -> ConnectionRecord:
    provider = _provider_or_error(row.provider_id)
    if row.auth_type != "oauth2":
        raise ValueError("This connection is not an OAuth account.")
    try:
        access_token = await valid_access_token(session, row)
        identity = await _identity(provider, access_token)
    except Exception as exc:
        row.status = "error"
        row.last_error = _safe_error(str(exc), "Account verification failed.")
        row.updated_at = utc_now()
        await session.commit()
        await session.refresh(row)
        raise RuntimeError(row.last_error) from exc

    config = _loads_object(row.config_json)
    config.update(
        {
            "oauth_subject": str(identity["subject"]),
            "display_name": _optional_string(identity.get("display_name")),
            "email": _optional_string(identity.get("email")),
            "login": _optional_string(identity.get("login")),
            "avatar_url": _optional_string(identity.get("avatar_url")),
        }
    )
    config = {key: value for key, value in config.items() if value is not None}
    account_hint = config.get("email") or config.get("login") or config.get("display_name") or config.get("oauth_subject")
    row.account_hint = str(account_hint) if account_hint else row.account_hint
    row.label = f"{provider.name} — {row.account_hint}" if row.account_hint else row.label
    row.config_json = json.dumps(config, separators=(",", ":"))
    row.status = "configured"
    row.last_error = None
    row.last_verified_at = utc_now()
    row.updated_at = utc_now()
    await session.commit()
    await session.refresh(row)
    return row


def callback_html(flow: OAuthFlowSession | None, error: str | None = None) -> str:
    if error:
        title = "Jace connection failed"
        body = html.escape(error)
        accent = "#d86b6b"
    elif flow and flow.status == "completed":
        title = "Jace account connected"
        body = f"{html.escape(flow.account_hint or flow.provider_id)} is now connected. You can close this tab and return to Jace."
        accent = "#6fcf97"
    elif flow and flow.status in {"failed", "expired"}:
        title = "Jace connection failed"
        body = html.escape(flow.error or "Authorization did not complete.")
        accent = "#d86b6b"
    else:
        title = "Jace OAuth callback"
        body = "Return to Jace to continue."
        accent = "#8fa7ff"
    return f"""<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title}</title><style>body{{margin:0;background:#0c1016;color:#e8edf4;font:16px system-ui;display:grid;min-height:100vh;place-items:center}}main{{max-width:560px;margin:24px;padding:28px;border:1px solid #293240;border-radius:16px;background:#121821}}h1{{margin:0 0 12px;color:{accent}}}p{{line-height:1.6;color:#aeb8c5}}</style></head><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"""
