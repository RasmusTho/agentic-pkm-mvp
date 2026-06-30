from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def _embedding_identity_dict(identity: Any) -> dict[str, Any]:
    if identity is None:
        return {}
    if is_dataclass(identity):
        return dict(asdict(identity))
    if isinstance(identity, dict):
        return dict(identity)
    return {
        "provider": getattr(identity, "provider", None),
        "model": getattr(identity, "model", None),
        "dim": getattr(identity, "dim", None),
        "normalize": getattr(identity, "normalize", None),
    }


def build_indexed_unit_payload(
    *,
    object_id: Any,
    kind: str,
    source_ref: str,
    payload: dict | None,
    text: str | None = None,
    embedding_identity: Any = None,
) -> dict:
    payload_out = dict(payload or {})
    safe_object_id = str(object_id)
    safe_source_ref = str(source_ref)
    safe_kind = str(kind or "note")

    if text is not None:
        payload_out.setdefault("text", text)
        payload_out.setdefault("content", text)
    payload_out.setdefault("object_type", safe_kind)
    payload_out.setdefault("system_intent", "learn")
    payload_out.setdefault("emergent_tags", [])

    payload_out["artifact_id"] = safe_object_id
    payload_out["stable_id"] = safe_object_id
    payload_out["path"] = safe_source_ref
    payload_out["source_ref"] = safe_source_ref
    payload_out["language"] = str(payload_out.get("language") or payload_out.get("lang") or "und")
    payload_out["source_role"] = str(payload_out.get("source_role") or payload_out.get("origin") or safe_kind)
    payload_out["origin"] = str(payload_out.get("origin") or "unknown")
    payload_out["trust"] = str(payload_out.get("trust") or "unreviewed")
    payload_out["review_state"] = str(payload_out.get("review_state") or "provisional")
    if embedding_identity is not None:
        payload_out["embedding_identity"] = _embedding_identity_dict(embedding_identity)
    return payload_out


__all__ = ["build_indexed_unit_payload"]
