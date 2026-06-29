"""Authentication and rate limiting utilities."""

from __future__ import annotations

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


def _can_trust_forwarded_for(immediate_host: str | None) -> bool:
    return _is_loopback_host(immediate_host) or _is_configured_trusted_proxy(immediate_host)


def _effective_client_host(request: Request) -> str | None:
    immediate_host = request.client.host if request.client else None
    if not _can_trust_forwarded_for(immediate_host):
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
