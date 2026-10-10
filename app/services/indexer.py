from __future__ import annotations

import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from app.components.embeddings import EmbeddingClientProtocol
from app.components.llm.fabric import get_product_embedding_client
from app.index.artifact_metadata import (
    build_indexed_unit_payload,
    canonicalize_indexable_text,
    canonicalize_indexed_text,
)
from app.index.embedding_identity import ensure_index_primary_identity
from app.domain.state_axes import normalize_artifact_state_axes
from app.ingest.episode_ref import episode_ref_from_frontmatter
from app.llm.embed_queue import EmbedDeadLetterError
from app.llm.fallback_orchestrator import embed_with_fallback
from app.observability.tracer import start_span
from app.outbox.events import DEFAULT_EMBEDDING_VIEW, emit_index_embedding_failed, emit_index_object_embedded
from app.objects import DomainObject, ObjectStore, resolve_canonical_object_id
from app.services.companion_note import is_companion_path
from app.stores import get_vector_index

logger = logging.getLogger(__name__)


def llm_embed_text(*, text: str, client: EmbeddingClientProtocol) -> list[float]:
    vector = client.embed_text(text)
    if len(vector) != client.identity.dim:
        raise ValueError(f"expected {client.identity.dim} got {len(vector)}")
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


def resolve_event_object_id(obj: Dict[str, object]) -> object:
    """Return canonical identity for current and queued pre-cutover events.

    Current producers carry ``object_id`` explicitly, but the raw ``POST
    /ingest`` producer sets it from the caller-supplied UUID and may therefore
    still carry a retained frontmatter identity. Every valid candidate crosses
    the retained ``objects.uuid -> objects.id`` mapping; already-canonical IDs
    resolve to themselves. Older vault-sync rows carry only ``uuid`` and use
    the same path during replay after #3510.
    """
    object_id = obj.get("object_id")
    candidate = object_id or obj.get("uuid")
    if _is_valid_uuid(candidate):
        return resolve_canonical_object_id(str(candidate))
    return candidate


def _source_backed_projection_metadata(
    obj: Dict[str, object],
    *,
    vault_root: Path | None,
    source_snapshot: str | None,
) -> dict[str, object]:
    """Derive retained-source metadata from the worker's admitted file snapshot.

    The generic ``ingest.object.created`` producer has no source-backed
    authority. Only the watched-note worker supplies ``source_snapshot`` after
    it has read and admitted the whole file, so arbitrary client payloads cannot
    mint replay provenance or replace a retained title.
    """
    if vault_root is None or source_snapshot is None:
        return {}

    raw_source_ref = obj.get("source_ref")
    if not isinstance(raw_source_ref, str) or not raw_source_ref.strip():
        return {}

    root = vault_root.expanduser().resolve()
    source_path = Path(raw_source_ref).expanduser()
    if not source_path.is_absolute():
        source_path = root / source_path
    source_path = source_path.resolve()
    if (
        not source_path.is_relative_to(root)
        or not source_path.is_file()
        or is_companion_path(source_path, root)
    ):
        return {}

    from app.ingest.vault_alpha import (
        _derive_title,
        _frontmatter_title,
        product_replay_for_vault_note,
    )
    from app.rebuildability import canonical_product_body_text, parse_bounded_frontmatter

    frontmatter, body, parse_error = parse_bounded_frontmatter(source_snapshot)
    if parse_error is not None:
        return {}

    normalized = normalize_artifact_state_axes(
        frontmatter,
        default_review_state="provisional",
    )
    return {
        "title": _frontmatter_title(frontmatter) or _derive_title(body, source_path),
        "review_state": normalized["review_state"],
        "maturity": normalized.get("maturity"),
        "episode_ref": episode_ref_from_frontmatter(frontmatter),
        "replay": product_replay_for_vault_note(
            source_path,
            vault_root=root,
            source_text=source_snapshot,
        ),
        "content": canonical_product_body_text(body),
    }


def _source_metadata_matches_existing(
    existing: DomainObject | None,
    *,
    incoming_ref: str,
    vault_root: Path | None,
) -> bool:
    """Keep a source-backed update bound to the object's retained locator."""
    if existing is None:
        return True
    if vault_root is None or not existing.source_ref:
        return False

    root = vault_root.expanduser().resolve()

    def _resolved_ref(value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = root / path
        return path.resolve()

    try:
        existing_path = _resolved_ref(existing.source_ref)
        incoming_path = _resolved_ref(incoming_ref)
    except OSError:
        return False
    if existing_path == incoming_path:
        return True
    # Preserve the established stale-locator repair seam. A different live
    # source path sharing a UUID is a binding conflict; missing old locators
    # are still repairable from the admitted source event.
    if is_companion_path(existing_path, root):
        return True
    return not existing_path.is_file()


def _source_replay_matches_existing(
    existing: DomainObject | None,
    source_metadata: dict[str, object],
) -> bool:
    """Reject a refresh that would mix a new source replay with an old one."""
    if existing is None:
        return True
    existing_replay = existing.payload.get("replay")
    incoming_replay = source_metadata.get("replay")
    if not isinstance(existing_replay, dict) or not isinstance(incoming_replay, dict):
        return True
    existing_identity = existing_replay.get("source_identity")
    incoming_identity = incoming_replay.get("source_identity")
    if not isinstance(existing_identity, str) or not isinstance(incoming_identity, str):
        return True
    return existing_identity == incoming_identity


def _source_metadata_for_existing(
    existing: DomainObject | None,
    source_metadata: dict[str, object],
    *,
    incoming_ref: str,
    vault_root: Path | None,
) -> dict[str, object]:
    """Avoid minting replay provenance for a legacy row with a stale locator."""
    if existing is None or vault_root is None or not existing.source_ref:
        return source_metadata
    if isinstance(existing.payload.get("replay"), dict):
        return source_metadata
    if not isinstance(source_metadata.get("replay"), dict):
        return source_metadata

    root = vault_root.expanduser().resolve()

    def _resolved_ref(value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = root / path
        return path.resolve()

    try:
        existing_path = _resolved_ref(existing.source_ref)
        incoming_path = _resolved_ref(incoming_ref)
    except OSError:
        return source_metadata
    if existing_path == incoming_path or is_companion_path(existing_path, root):
        return source_metadata
    # The row has no replay authority and its old source file is gone. Keep
    # the legacy fields updateable, but do not pair a new replay identity with
    # that retained locator; readiness must remain refused until reconciled.
    return {key: value for key, value in source_metadata.items() if key != "replay"}


def _infer_dim_from_error(exc: Exception) -> int | None:
    text = str(exc)
    match = re.search(r"got\s+(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def handle_ingest_object_created(
    obj: Dict[str, object],
    *,
    vault_root: Path | None = None,
    source_snapshot: str | None = None,
) -> None:
    incoming_uuid = resolve_event_object_id(obj)
    object_uuid = incoming_uuid if _is_valid_uuid(incoming_uuid) else str(_uuid.uuid4())

    content = str(obj.get("content") or "")
    obj_payload = obj.get("payload") or {}
    source_metadata = _source_backed_projection_metadata(
        obj,
        vault_root=vault_root,
        source_snapshot=source_snapshot,
    )
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
    incoming_ref = str(obj.get("source_ref") or obj.get("path") or "")
    source_metadata_bound = _source_metadata_matches_existing(
        existing,
        incoming_ref=incoming_ref,
        vault_root=vault_root,
    )
    source_replay_bound = _source_replay_matches_existing(existing, source_metadata)
    if source_snapshot is not None and (not source_metadata_bound or not source_replay_bound):
        logger.warning(
            "watched source binding conflict; preserving existing projection object_id=%s source_ref=%s incoming_ref=%s replay_bound=%s",
            object_uuid,
            existing.source_ref if existing is not None else None,
            incoming_ref,
            source_replay_bound,
        )
        return
    if source_metadata_bound:
        source_metadata = _source_metadata_for_existing(
            existing,
            source_metadata,
            incoming_ref=incoming_ref,
            vault_root=vault_root,
        )
        payload.update({key: value for key, value in source_metadata.items() if value is not None})

    if existing is None:
        domain = DomainObject(
            uuid=object_uuid,
            kind=obj.get("kind") or "note",
            payload=payload,
            source_ref=incoming_ref or None,
            created_at=datetime.now(timezone.utc),
        )
    else:
        updated_payload = dict(existing.payload or {})
        updated_payload.update({k: v for k, v in payload.items() if v is not None})
        source_ref = existing.source_ref
        # Validated vault-source reingest can repair the locator left by a
        # pre-fix companion publication. Retain every other existing locator;
        # this does not establish a general rename/duplicate-identity policy.
        if vault_root is not None and source_ref and incoming_ref:
            root = vault_root.expanduser().resolve()
            source_path = Path(incoming_ref).expanduser()
            if not source_path.is_absolute():
                source_path = root / source_path
            source_path = source_path.resolve()
            if (
                source_path.is_relative_to(root)
                and source_path.is_file()
                and not is_companion_path(source_path, root)
                and is_companion_path(Path(source_ref), root)
            ):
                source_ref = str(source_path)
        domain = DomainObject(
            uuid=existing.uuid,
            kind=existing.kind,
            payload=updated_payload,
            source_ref=source_ref,
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

    embedding_client = get_product_embedding_client()
    identity = embedding_client.identity
    vector_index = get_vector_index()
    actual_identity = identity
    embedding: list[float] | None = None
    actual_dim: int | None = None
    is_fallback = False

    try:
        ensure_index_primary_identity(vector_index, identity)
        embedding, actual_identity, is_fallback = embed_with_fallback(
            canonical_content,
            primary_identity=identity,
            object_id=object_uuid,
            primary_embed_callable=lambda: llm_embed_text(
                text=canonical_content,
                client=embedding_client,
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
    finally:
        close = getattr(embedding_client, "close", None)
        if callable(close):
            close()

    model_name = actual_identity.model

    object_uuid_val = _uuid.UUID(object_uuid)
    with start_span("indexer.upsert", trace_id, {"kind": obj.get("kind") or "note"}):
        try:
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
