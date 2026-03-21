"""Canonical Uvicorn entrypoint for the Reality-MVP HTTP API."""

from __future__ import annotations

# Reality-MVP FastAPI app used by API tests (/api/status, /api/ask)
from app.api.app import app

__all__ = ["app"]
