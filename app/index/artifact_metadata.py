from __future__ import annotations

import hashlib
from typing import Any

from app.agents.panel.filters import strip_ai_panels
from app.ingest.chunk_policy import CHUNK_POLICY_VERSION
from app.ingest.episode_ref import episode_ref_from_frontmatter

# Embed-pipeline version stamped into every store_vector_index row's
# provenance (KERNEL-06, #2768). Bump this when the embedding pipeline
# (pre-processing, chunking-to-embed wiring, or model-invocation shape)
# changes in a way that would make existing vectors stale relative to a
# re-run, independent of a chunk-policy or model change.
EMBED_PIPELINE_VERSION = "v1"
INDEXABLE_TEXT_KEYS = ("content", "text", "raw_text")


def _embedding_identity_dict(identity: Any) -> dict[str, Any]:
    """Project an EmbeddingIdentity to the documented W3-SPINE-01 provenance
    shape: provider/model/dim/normalize only (docs/DB_SCHEMA.md ::
    store_vector_index). Explicitly enumerated (not a raw asdict/vars dump) so
    additive identity-note fields such as ``no_prefix`` (#2984, call-site
    metadata, not a persisted provenance field) never silently widen this
    stored contract."""
    if identity is None:
        return {}
    if isinstance(identity, dict):
        return {
            "provider": identity.get("provider"),
            "model": identity.get("model"),
            "dim": identity.get("dim"),
            "normalize": identity.get("normalize"),
        }
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


def extract_indexable_text(payload: dict | None) -> str:
    """Select source text with the same precedence used by index rebuild.

    ``store_objects`` can carry compatibility aliases simultaneously.  The
    producer contract is content-first, then text, then raw_text; diagnosis
    and reconcile must not independently choose a different alias.
    """
    data = payload or {}
    for key in INDEXABLE_TEXT_KEYS:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def canonicalize_indexable_text(payload: dict | None) -> str:
    """Return the exact producer text used for embedding and provenance."""
    return canonicalize_indexed_text(extract_indexable_text(payload))


def canonicalize_indexed_text(text: str) -> str:
    """Strip panels while preserving meaningful source whitespace.

    Panel removal can leave only separator newlines around an otherwise
    panel-only note.  Such a remainder has no semantic bytes to embed and must
    converge with contentless source handling, while text-bearing notes retain
    their exact post-panel bytes.
    """
    canonical = strip_ai_panels(text or "")
    return canonical if canonical.strip() else ""


def compute_indexed_content_hash(text: str) -> str:
    """Hash text with the producer's AI-panel canonicalization."""
    return compute_content_hash(canonicalize_indexed_text(text))


def compute_payload_content_hash(payload: dict | None) -> str:
    """Hash the producer-selected text from a durable object payload."""
    return compute_content_hash(canonicalize_indexable_text(payload))


def build_indexed_unit_payload(
    *,
    object_id: Any,
    kind: str,
    source_ref: str,
    payload: dict | None,
    text: str | None = None,
    embedding_identity: Any = None,
    bind_text_aliases: bool = True,
) -> dict:
    payload_out = dict(payload or {})
    safe_object_id = str(object_id)
    safe_source_ref = str(source_ref)
    safe_kind = str(kind or "note")

    canonical_text = canonicalize_indexed_text(
        text if text is not None else extract_indexable_text(payload_out)
    )
    if text is not None and bind_text_aliases:
        # A derived vector payload must expose exactly the bytes that produced
        # both its embedding and provenance hash.  Assignment is intentional:
        # compatibility aliases copied from a source row may be stale/raw.
        payload_out["text"] = canonical_text
        payload_out["content"] = canonical_text
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
    # episode_ref choke (ERE-03/ERE-05, invariant->producers): every store_vector_index row
    # RETRIEVAL reads is written through this builder, so defaulting episode_ref here guarantees the
    # field is ALWAYS present on the retrieval path -- a present, schema-valid binding is preserved,
    # anything absent/malformed becomes the honest 'unbound' sentinel. Producers that carry the REAL
    # vault-canonical binding (vault ingest, ERE-05 assignment) still win because this only fills a
    # gap; it never overwrites a present binding. This is the structural backstop the store-payload
    # census (tests/properties/test_store_payload_episode_ref.py) verifies for builder-covered sinks.
    payload_out["episode_ref"] = episode_ref_from_frontmatter(payload_out)
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
    "canonicalize_indexable_text",
    "canonicalize_indexed_text",
    "compute_content_hash",
    "compute_indexed_content_hash",
    "compute_payload_content_hash",
    "extract_indexable_text",
    "EMBED_PIPELINE_VERSION",
    "INDEXABLE_TEXT_KEYS",
]
