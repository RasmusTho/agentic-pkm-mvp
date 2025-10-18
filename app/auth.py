"""Authentication and rate limiting utilities."""
from __future__ import annotations

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


limiter = Limiter(key_func=get_remote_address, enabled=settings.rate_limit_enabled)


def rate_limit_default() -> str:
    return settings.rate_limit_default


def configure_rate_limit_storage() -> None:
    limiter.enabled = settings.rate_limit_enabled


def verify_request(request: Request) -> Request:
    """Compatibility dependency to allow SlowAPI to access request.state."""
    return request
