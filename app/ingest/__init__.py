from __future__ import annotations
from typing import Any, Optional

from .api import ingest_object as ingest_object
from .lifecycle import handle_post_ingest as _handle_post_ingest
from .lifecycle import normalize_payload as _normalize_payload


def normalize_payload(payload: dict[str, Any], text: Optional[str] = None) -> dict[str, Any]:
    return _normalize_payload(payload, text or payload.get("text") or "")


def handle_post_ingest(object_id: str, payload: dict[str, Any], text: Optional[str] = None) -> None:
    return _handle_post_ingest(object_id, payload, text or payload.get("text") or "")


__all__ = ["ingest_object", "normalize_payload", "handle_post_ingest"]
