from __future__ import annotations

import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Dict

from app.components.embeddings import get_embedding_client, get_embedding_identity
from app.index.artifact_metadata import (
    build_indexed_unit_payload,
    canonicalize_indexable_text,
    canonicalize_indexed_text,
)
from app.ingest.episode_ref import episode_ref_from_frontmatter
from app.llm.embed_queue import EmbedDeadLetterError
from app.llm.fallback_orchestrator import embed_with_fallback
from app.observability.tracer import start_span
from app.outbox.events import DEFAULT_EMBEDDING_VIEW, emit_index_embedding_failed, emit_index_object_embedded
from app.objects import DomainObject, ObjectStore
from app.stores import get_vector_index

logger = logging.getLogger(__name__)


def llm_embed_text(*, text: str, provider: str, model: str, dim: int, normalize: bool) -> list[float]:
    client = get_embedding_client(override_provider=provider, override_model=model)
    vector = client.embed_text(text)
    if len(vector) != dim:
        raise ValueError(f"expected {dim} got {len(vector)}")
    if normalize:
        return list(vector)
    return list(vector)


def purge_object_vectors(object_id: _uuid.UUID) -> int:
    """Purge every vector row for ``object_id`` from the durable index (T-delete, #2944).

    Delete-path twin of the purge half of :func:`handle_ingest_object_created`:
    lives here (not in the outbox worker) because this module is the
    established indexer seam onto ``app.stores.get_vector_index()`` — the
    worker's ``handle_ingest_object_deleted`` delegates its purge to this
    function so the worker never grows a direct dependency on the
    transitional store layer (``tests/architecture/
    test_deprecated_store_callers.py`` forbids new callers).

    Mirrors ``app/indexer/consumer.py::_purge_vectors``: a missing purge
    primitive or a raising purge degrades to zero rows purged rather than
    propagating, so a delete event never crash-loops the worker. Purging an
    object with no vector rows is a documented no-op on both store backends
    (``purge_vectors`` returns 0 instead of raising), which is what makes
    redelivery of the same delete event converge (KERNEL-11).
    """
    idx = get_vector_index()
    purge = getattr(idx, "purge_vectors", None)
    if purge is None:
        return 0
    try:
        return purge(object_id, view=DEFAULT_EMBEDDING_VIEW)
    except Exception:
        logger.exception(
            "purge_vectors raised while purging deleted object's vectors object_id=%s",
            object_id,
        )
        return 0


def _is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        _uuid.UUID(str(value))
    except Exception:
        return False
    return True


def _infer_dim_from_error(exc: Exception) -> int | None:
    text = str(exc)
    match = re.search(r"got\s+(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def handle_ingest_object_created(obj: Dict[str, object]) -> None:
    incoming_uuid = obj.get("uuid")
    object_uuid = incoming_uuid if _is_valid_uuid(incoming_uuid) else str(_uuid.uuid4())

    content = str(obj.get("content") or "")
    obj_payload = obj.get("payload") or {}
    payload = {
        "title": obj.get("title"),
        "review_state": obj.get("review_state"),
        "maturity": obj.get("maturity"),
        "content": content,
        "source_uuid": incoming_uuid,
        "raw_text": obj_payload.get("raw_text"),
        "text": content,
    }
    frontmatter = obj_payload.get("frontmatter")
    if isinstance(frontmatter, dict) and "content" in obj:
        # Vault-change events carry the already selected note body explicitly.
        # Preserve that selection even when it canonicalizes to empty: falling
        # through to raw_text would re-index YAML/frontmatter for a panel-only
        # note whose authoritative body is empty.
        canonical_content = canonicalize_indexed_text(content)
        payload["indexable_text_source"] = "content"
    else:
        canonical_content = canonicalize_indexable_text(payload)
        payload["indexable_text_source"] = next(
            (
                key
                for key in ("content", "text", "raw_text")
                if payload.get(key)
            ),
            "content",
        )
    # Carry the note's vault-canonical episode_ref (ERE-03/ERE-05, invariant->producers): the
    # POST /ingest → outbox → this-handler path builds a FRESH store_objects/store_vector_index
    # payload. When the event carries frontmatter (the ingest.vault.changed path), that frontmatter
    # is the canonical episode_ref source, so project it in -- it wins the update-merge below,
    # keeping a stamped binding across a body-edit reingest. When the event carries NO frontmatter
    # (the raw POST /ingest path), episode_ref is deliberately left off `payload` so the merge
    # PRESERVES any existing DB binding and the build_indexed_unit_payload choke defaults a fresh
    # object to the honest 'unbound' -- never clobbering a real binding with 'unbound'.
    if isinstance(frontmatter, dict):
        payload["episode_ref"] = episode_ref_from_frontmatter(frontmatter)
    trace_id = obj.get("trace_id")
    store = ObjectStore()
    existing = store.get_object(object_uuid)

    if existing is None:
        domain = DomainObject(
            uuid=object_uuid,
            kind=obj.get("kind") or "note",
            payload=payload,
            source_ref=obj.get("source_ref"),
            created_at=datetime.now(timezone.utc),
        )
    else:
        updated_payload = dict(existing.payload or {})
        updated_payload.update({k: v for k, v in payload.items() if v is not None})
        domain = DomainObject(
            uuid=existing.uuid,
            kind=existing.kind,
            payload=updated_payload,
            source_ref=existing.source_ref,
            created_at=existing.created_at,
        )
    domain.payload = build_indexed_unit_payload(
        object_id=domain.uuid,
        kind=domain.kind,
        source_ref=domain.source_ref or "",
        payload=domain.payload,
        text=canonical_content,
        bind_text_aliases=False,
    )
    store.save_object(domain, emit_outbox=False, trace_id=trace_id)

    if not canonical_content:
        vector_index = get_vector_index()
        vector_index.purge_vectors(
            _uuid.UUID(str(object_uuid)), view=DEFAULT_EMBEDDING_VIEW
        )
        return

    identity = get_embedding_identity()
    actual_identity = identity
    embedding: list[float] | None = None
    actual_dim: int | None = None
    is_fallback = False

    try:
        embedding, actual_identity, is_fallback = embed_with_fallback(
            canonical_content,
            primary_identity=identity,
            object_id=object_uuid,
            primary_embed_callable=lambda: llm_embed_text(
                text=canonical_content,
                provider=identity.provider,
                model=identity.model,
                dim=identity.dim,
                normalize=identity.normalize,
            ),
        )
        actual_dim = len(embedding)
    except EmbedDeadLetterError as exc:
        actual_dim = _infer_dim_from_error(exc)
        emit_index_embedding_failed(
            object_id=object_uuid,
            trace_id=trace_id,
            source_ref=domain.source_ref,
            provider=identity.provider,
            model=identity.model,
            expected_dim=identity.dim,
            actual_dim=actual_dim,
            error=str(exc),
        )
        return
    except Exception as exc:
        actual_dim = _infer_dim_from_error(exc)
        emit_index_embedding_failed(
            object_id=object_uuid,
            trace_id=trace_id,
            source_ref=domain.source_ref,
            provider=identity.provider,
            model=identity.model,
            expected_dim=identity.dim,
            actual_dim=actual_dim,
            error=str(exc),
        )
        return

    vector_index = get_vector_index()
    model_name = actual_identity.model

    object_uuid_val = _uuid.UUID(object_uuid)
    with start_span("indexer.upsert", trace_id, {"kind": obj.get("kind") or "note"}):
        try:
            vector_index.purge_vectors(object_uuid_val, view=DEFAULT_EMBEDDING_VIEW)
            upsert_kwargs = {
                "kind": domain.kind,
                "source_ref": domain.source_ref or "",
                "payload": build_indexed_unit_payload(
                    object_id=object_uuid_val,
                    kind=domain.kind,
                    source_ref=domain.source_ref or "",
                    payload=domain.payload,
                    text=canonical_content,
                    embedding_identity=actual_identity,
                ),
                "embedding": embedding,
                "model": model_name,
                "identity": actual_identity,
            }
            if is_fallback:
                upsert_kwargs["reconcilable_fallback"] = True
            vector_index.upsert(object_uuid_val, **upsert_kwargs)
            emit_index_object_embedded(
                object_id=object_uuid,
                trace_id=trace_id,
                source_ref=domain.source_ref,
                provider=actual_identity.provider,
                model=model_name,
                dim=actual_dim,
                meta=(
                    {
                        "fallback_used": True,
                        "primary_provider": identity.provider,
                    }
                    if is_fallback
                    else None
                ),
            )
        except Exception as exc:  # pragma: no cover - best-effort logging path
            logger.exception("Vector index ingest failed for %s", object_uuid)
            emit_index_embedding_failed(
                object_id=object_uuid,
                trace_id=trace_id,
                source_ref=domain.source_ref,
                provider=actual_identity.provider,
                model=model_name,
                expected_dim=actual_identity.dim,
                actual_dim=actual_dim,
                error=str(exc),
            )
