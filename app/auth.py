"""Authentication and rate limiting utilities."""

from __future__ import annotations

import socket
import time
from ipaddress import ip_address, ip_network

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.settings import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Depends(api_key_header)) -> str:
    expected = settings.api_key
    if expected is None:
        return ""  # auth disabled
    if api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return expected


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    if host in {"", "localhost", "testclient"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _configured_trusted_proxy_hosts() -> list[str]:
    raw = settings.companion_trusted_proxy_hosts or ""
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def _is_configured_trusted_proxy(host: str | None) -> bool:
    if host is None:
        return False
    try:
        host_ip = ip_address(host)
    except ValueError:
        host_ip = None

    for entry in _configured_trusted_proxy_hosts():
        if host_ip is not None:
            try:
                if host_ip in ip_network(entry, strict=False):
                    return True
            except ValueError:
                pass
        if host == entry:
            return True
    return False


def _is_trusted_forwarding_peer(host: str | None) -> bool:
    # X-Forwarded-For is security-sensitive: trust loopback by default and
    # explicit operator-declared proxy peers only. A direct LAN/Tailscale caller
    # that sends XFF is still judged by its immediate peer address.
    return _is_loopback_host(host) or _is_configured_trusted_proxy(host)


# --- Companion UI container proxy trust (#3102) ---------------------------
#
# In the documented docker-compose deployment the browser never reaches the api
# directly: it talks to the companion-ui container, which relays over the Docker
# bridge network. Neither hop is loopback, so the loopback/API-key-gated
# vault-selection routes 401'd on every onboarding action. Trust the Companion
# UI container's OWN server-side proxy call by construction: resolve the
# configured proxy host(s) (default: the compose service name `companion-ui`) to
# their bridge address(es) and authorise a request whose immediate peer is that
# container. This is deliberately NOT `_is_trusted_forwarding_peer`: it does not
# look through `X-Forwarded-For` to the (non-loopback) browser — the container
# itself is the authorised same-deployment caller, scoped to the resolved
# companion-ui address only, so an unrelated bridge/LAN peer stays untrusted
# (preserving the #2706 anti-spoofing posture).

_PROXY_DNS_TTL_SECONDS = 30.0
# name -> (resolved_at_monotonic, (address, ...)). Negative results (empty
# tuple) are cached too so a non-resolving name (e.g. outside docker) does not
# incur a slow lookup on every gated request.
_proxy_dns_cache: dict[str, tuple[float, tuple[str, ...]]] = {}


def _configured_companion_ui_proxy_hosts() -> list[str]:
    raw = settings.companion_ui_proxy_hosts or ""
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def _resolve_proxy_host_addresses(name: str) -> tuple[str, ...]:
    """Resolve a hostname to its current address(es), cached with a short TTL.

    Docker service names (e.g. `companion-ui`) resolve to the container's bridge
    address; a short TTL lets a container restart re-map without a process
    bounce. Resolution failures (non-docker, NXDOMAIN) cache an empty tuple.
    """

    now = time.monotonic()
    cached = _proxy_dns_cache.get(name)
    if cached is not None and (now - cached[0]) < _PROXY_DNS_TTL_SECONDS:
        return cached[1]
    try:
        infos = socket.getaddrinfo(name, None)
    except (socket.gaierror, OSError):
        addresses: tuple[str, ...] = ()
    else:
        addresses = tuple({info[4][0] for info in infos})
    _proxy_dns_cache[name] = (now, addresses)
    return addresses


def _is_trusted_companion_ui_proxy(host: str | None) -> bool:
    if host is None:
        return False
    entries = _configured_companion_ui_proxy_hosts()
    if not entries:
        return False
    try:
        host_ip = ip_address(host)
    except ValueError:
        host_ip = None

    for entry in entries:
        if host == entry:
            return True
        # A numeric entry (single IP or CIDR) is matched by network membership;
        # it is never DNS-resolved.
        try:
            network = ip_network(entry, strict=False)
        except ValueError:
            network = None
        if network is not None:
            if host_ip is not None and host_ip in network:
                return True
            continue
        # A hostname entry (e.g. the `companion-ui` service name) is resolved to
        # its address(es) and compared against the numeric immediate peer.
        if host_ip is not None:
            for resolved in _resolve_proxy_host_addresses(entry):
                try:
                    if host_ip == ip_address(resolved):
                        return True
                except ValueError:
                    continue
    return False


def _effective_client_host(request: Request) -> str | None:
    immediate_host = request.client.host if request.client else None
    if not _is_trusted_forwarding_peer(immediate_host):
        return immediate_host
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for is None:
        return immediate_host
    forwarded_host = forwarded_for.split(",", 1)[0].strip()
    return forwarded_host or immediate_host


def require_loopback_or_api_key(
    request: Request,
    api_key: str | None = Depends(api_key_header),
) -> str:
    if _is_loopback_host(_effective_client_host(request)):
        return ""
    # The Companion UI container is the sole caller of these routes in the
    # documented docker-compose deployment; trust its own server-side proxy call
    # by construction (#3102). Judged on the immediate peer only — never the
    # forwarded browser address — and scoped to the resolved companion-ui
    # address, so unrelated non-loopback callers still require the API key.
    immediate_host = request.client.host if request.client else None
    if _is_trusted_companion_ui_proxy(immediate_host):
        return ""
    expected = settings.api_key
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required for non-loopback request",
        )
    if api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return expected


limiter = Limiter(key_func=get_remote_address, enabled=settings.rate_limit_enabled)


def rate_limit_default() -> str:
    return settings.rate_limit_default


def configure_rate_limit_storage() -> None:
    limiter.enabled = settings.rate_limit_enabled


def verify_request(request: Request) -> Request:
    """Compatibility dependency to allow SlowAPI to access request.state."""
    return request
