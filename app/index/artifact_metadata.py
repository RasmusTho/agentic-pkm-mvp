from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from typing import Any

from app.agents.panel.filters import strip_ai_panels
from app.ingest.chunk_policy import CHUNK_POLICY_VERSION

# Embed-pipeline version stamped into every store_vector_index row's
# provenance (KERNEL-06, #2768). Bump this when the embedding pipeline
# (pre-processing, chunking-to-embed wiring, or model-invocation shape)
# changes in a way that would make existing vectors stale relative to a
# re-run, independent of a chunk-policy or model change.
EMBED_PIPELINE_VERSION = "v1"


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


def compute_content_hash(text: str) -> str:
    """Stable hash of the exact embedded text (KERNEL-06, #2768).

    Used both to stamp `provenance.content_hash` at write time and to detect
    staleness at doctor/reconcile time (a mismatch means the source text
    changed since the vector was produced).
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


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

    # Transform provenance stamp (KERNEL-06, #2768, audit invariant I-D1).
    # Rides inside this same payload dict so it commits in the same upsert
    # statement as the vector — cross-task invariant #4 forbids a separate
    # "stamp later" write. `content_hash` is computed from the CANONICAL source
    # body — strip_ai_panels applied here so the hash is deterministic across
    # reingest even after an AI panel / companion block is written back into the
    # note (idempotent no-op on panel-free text). Hashing the enriched body
    # instead makes content_hash non-deterministic and breaks reingest
    # idempotence + cold-rebuild (registry_chain).
    embedded_text = text if text is not None else str(payload_out.get("text") or payload_out.get("content") or "")
    canonical_text = strip_ai_panels(embedded_text)
    payload_out["provenance"] = {
        "source_ref": safe_source_ref,
        "content_hash": compute_content_hash(canonical_text),
        "chunk_policy_version": CHUNK_POLICY_VERSION,
        "pipeline_version": EMBED_PIPELINE_VERSION,
        "embedding_identity": _embedding_identity_dict(embedding_identity) if embedding_identity is not None else None,
    }
    return payload_out


__all__ = [
    "build_indexed_unit_payload",
    "compute_content_hash",
    "EMBED_PIPELINE_VERSION",
]
