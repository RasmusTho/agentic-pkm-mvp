"""Canonical Uvicorn entrypoint for the Reality-MVP HTTP API."""

from __future__ import annotations

# Reality-MVP FastAPI app used by API tests (/api/status, /api/ask)
from app.api.app import app

# Legacy agent/demo endpoints are preserved separately in app.legacy_http:app

__all__ = ["app"]
