import asyncio
import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UnsafeWebAddressError(ValueError):
    """Raised when a URL could access a local/private/non-web resource."""


_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443}
_BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home",
)


def _normalise_url_parts(url: str) -> SplitResult:
    candidate = url.strip()
    if not candidate:
        raise UnsafeWebAddressError("URL cannot be empty.")

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeWebAddressError("Only http:// and https:// URLs are allowed.")
    if not parsed.hostname:
        raise UnsafeWebAddressError("URL must contain a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeWebAddressError("URLs containing usernames or passwords are not allowed.")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UnsafeWebAddressError("Local network hostnames are not allowed.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeWebAddressError("URL contains an invalid port.") from exc

    if port is not None and port not in _ALLOWED_PORTS:
        raise UnsafeWebAddressError("Only standard web ports 80 and 443 are allowed.")

    return parsed


def normalise_public_url(url: str) -> str:
    parsed = _normalise_url_parts(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname.rstrip(".").lower() if parsed.hostname else ""

    port = parsed.port
    host_netloc = f"[{host}]" if ":" in host else host
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = host_netloc
    else:
        netloc = f"{host_netloc}:{port}"

    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return bool(ip.is_global)


async def resolve_public_addresses(hostname: str, port: int) -> set[str]:
    loop = asyncio.get_running_loop()

    try:
        records = await loop.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise UnsafeWebAddressError(f"Could not resolve hostname: {hostname}") from exc

    addresses: set[str] = set()
    for record in records:
        sockaddr = record[4]
        if not sockaddr:
            continue
        address = str(sockaddr[0])
        try:
            if not _is_public_ip(address):
                raise UnsafeWebAddressError(
                    f"The address for {hostname} resolves to a private or non-public network."
                )
        except ValueError as exc:
            raise UnsafeWebAddressError("Hostname resolved to an invalid network address.") from exc
        addresses.add(address)

    if not addresses:
        raise UnsafeWebAddressError(f"No usable public address was found for {hostname}.")

    return addresses


async def validate_public_url(url: str) -> str:
    normalised = normalise_public_url(url)
    parsed = urlsplit(normalised)
    host = parsed.hostname
    assert host is not None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Literal IPs are checked directly; hostnames are resolved before a request
    # is allowed. This prevents the common local/private SSRF cases.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        await resolve_public_addresses(host, port)
    else:
        if not literal.is_global:
            raise UnsafeWebAddressError("Private or non-public IP addresses are not allowed.")

    return normalised


def is_obviously_public_search_result(url: str) -> bool:
    """Cheap filter for search result URLs. Full DNS validation occurs before fetching."""
    try:
        _normalise_url_parts(url)
        return True
    except UnsafeWebAddressError:
        return False
