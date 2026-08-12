"""Immutable `raw` record persistence for the Knowledge Acquisition Platform (KA-01).

Per `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § `raw`:
content exactly as acquired plus source metadata and provenance, immutable and
versioned by `content_identity`. A changed source yields a new `raw` record,
never an overwrite.

Persistence routes through the canonical `app.objects` import boundary
(`DomainObject` / `ObjectStore`), which itself resolves the durable write
through the PDM-owned StorePort seam (`app.stores.resolve_object_store_port`)
per `docs/contracts/STORE_PORT.md` and D3 (`docs/architecture/SBS_TRANSITION_DEBT.md`)
— no private store construction. `app.store` / `app.stores` are deprecated for
new callers (`docs/CODE_INVENTORY.md` § Deprecated Packages: "New code must
import from `app.objects`"; guard: `tests/architecture/test_deprecated_store_callers.py`).

Outbox: `ObjectStore.save_object` is called with ``emit_outbox=False``. The raw
fetch is deliberately pre-pipeline (`ACQUIRE_YOUTUBE_CAPTIONS.md` § Out of
Scope: "no vault write", no pipeline stages); emitting the default
`INGEST_OBJECT_CREATED` event would route the unprocessed raw payload straight
into the indexer/embedding consumer (`app/workers/outbox_worker.py ::
handle_ingest_object_created`), which is exactly the pipeline behavior this
slice must not trigger (`REFINEMENT_PIPELINE_CONTRACT.md`: chunking/embedding
belongs to later stages, never the source plugin). A future refinement-stage
slice emits its own stage event per that contract's lineage/replay model.

Dedup identity: `(source_kind, item_ref, content_identity)`
(`docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md` § Identity and dedup). The
object's `object_id` is a deterministic UUID5 derived from that triple, so:

- re-fetching unchanged content always resolves to the same `object_id` — the
  record already exists and the fetch is a traced no-op, never a duplicate or
  an overwrite;
- changed upstream content yields a different `content_identity`, hence a
  different `object_id` — a genuinely new record, with the prior record left
  untouched.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.ingest.episode_ref import episode_ref_from_frontmatter
from app.objects import DomainObject, ObjectStore
from app.observability.log import json_log

RAW_RECORD_KIND = "knowledge_acquisition.raw"


class RawRecordIntegrityError(RuntimeError):
    """A deterministic raw identity is occupied by non-raw or inconsistent state."""


def raw_record_object_id(*, source_kind: str, item_ref: str, content_identity: str) -> UUID:
    """Deterministic identity for a raw record: (source_kind, item_ref, content_identity)."""
    key = f"{source_kind}:{item_ref}:{content_identity}"
    return uuid5(NAMESPACE_URL, f"urn:knowledge-acquisition:raw:{key}")


@dataclass(frozen=True)
class RawRecordResult:
    object_id: UUID
    content_identity: str
    is_new: bool
    record: dict[str, Any]


def persist_raw_record(
    *,
    source_kind: str,
    item_ref: str,
    content_identity: str,
    payload: dict[str, Any],
    source_ref: str,
) -> RawRecordResult:
    """Persist an immutable raw record, deduping on identity.

    If a record already exists at the derived ``object_id`` (same
    source_kind/item_ref/content_identity), this is a traced no-op: the
    existing record is returned unchanged and nothing is written. Otherwise a
    new record is written once and never later overwritten by this function
    (a subsequent call with the same identity always short-circuits above).
    """
    object_id = raw_record_object_id(
        source_kind=source_kind, item_ref=item_ref, content_identity=content_identity
    )
    store = ObjectStore()

    existing = store.get_object(str(object_id))
    if existing is not None:
        record = _validated_raw_payload(
            existing,
            object_id=object_id,
            source_kind=source_kind,
            item_ref=item_ref,
            content_identity=content_identity,
        )
        json_log(
            event="knowledge_acquisition.raw.dedup_noop",
            source_kind=source_kind,
            item_ref=item_ref,
            content_identity=content_identity,
            object_id=str(object_id),
        )
        return RawRecordResult(
            object_id=object_id,
            content_identity=content_identity,
            is_new=False,
            record=record,
        )

    record_payload = dict(payload)
    record_payload.setdefault("content_identity", content_identity)
    record_payload.setdefault("source_kind", source_kind)
    record_payload.setdefault("item_ref", item_ref)
    record_payload.setdefault("acquired_at", time.time())
    # Carry episode_ref (ERE-03/ERE-05, invariant->producers): a raw acquisition record is a
    # frontmatter-less external source and never an ERE-05 assignment target, so the honest
    # vault-canonical value is the 'unbound' sentinel -- normalized from whatever the caller's
    # payload carries (kept if a valid binding, else 'unbound'), never left absent. The {**...}
    # rebuild keeps this an explicit dict literal so the store-payload census can see the key.
    record_payload = {
        **record_payload,
        "episode_ref": episode_ref_from_frontmatter(record_payload),
    }

    domain_object = DomainObject(
        uuid=str(object_id),
        kind=RAW_RECORD_KIND,
        payload=record_payload,
        source_ref=source_ref,
        created_at=datetime.now(timezone.utc),
    )
    # emit_outbox=False: see module docstring — raw fetch is pre-pipeline and
    # must not trigger the indexer/embedding consumer.
    created = store.create_object_once(domain_object)
    if not created:
        winner = store.get_object(str(object_id))
        if winner is None:
            raise RawRecordIntegrityError(
                f"raw identity {object_id} lost its atomic create winner"
            )
        winner_payload = _validated_raw_payload(
            winner,
            object_id=object_id,
            source_kind=source_kind,
            item_ref=item_ref,
            content_identity=content_identity,
        )
        json_log(
            event="knowledge_acquisition.raw.dedup_noop",
            source_kind=source_kind,
            item_ref=item_ref,
            content_identity=content_identity,
            object_id=str(object_id),
        )
        return RawRecordResult(
            object_id=object_id,
            content_identity=content_identity,
            is_new=False,
            record=winner_payload,
        )
    json_log(
        event="knowledge_acquisition.raw.persisted",
        source_kind=source_kind,
        item_ref=item_ref,
        content_identity=content_identity,
        object_id=str(object_id),
    )
    return RawRecordResult(
        object_id=object_id,
        content_identity=content_identity,
        is_new=True,
        record=record_payload,
    )


def find_raw_record(
    *, source_kind: str, item_ref: str, content_identity: str
) -> RawRecordResult | None:
    """Dedup pre-check without persisting: return the existing record at the
    derived identity as a traced no-op result, or ``None`` when absent.

    Lets expensive acquisition paths (KA-02 ASR fallback: audio download +
    local transcription) resolve identity first and skip the acquisition
    entirely on a dedup hit, per `SOURCE_PLUGIN_CONTRACT.md` § Identity and
    dedup ("Dedup is decided **before** fetch wherever the source allows it").
    Emits the same ``knowledge_acquisition.raw.dedup_noop`` trace as
    :func:`persist_raw_record`'s internal dedup branch.
    """
    object_id = raw_record_object_id(
        source_kind=source_kind, item_ref=item_ref, content_identity=content_identity
    )
    existing = ObjectStore().get_object(str(object_id))
    if existing is None:
        return None
    record = _validated_raw_payload(
        existing,
        object_id=object_id,
        source_kind=source_kind,
        item_ref=item_ref,
        content_identity=content_identity,
    )
    json_log(
        event="knowledge_acquisition.raw.dedup_noop",
        source_kind=source_kind,
        item_ref=item_ref,
        content_identity=content_identity,
        object_id=str(object_id),
    )
    return RawRecordResult(
        object_id=object_id,
        content_identity=content_identity,
        is_new=False,
        record=record,
    )


def get_raw_record(object_id: UUID | str) -> dict[str, Any] | None:
    try:
        resolved_id = object_id if isinstance(object_id, UUID) else UUID(object_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise RawRecordIntegrityError(f"invalid raw object_id {object_id!r}") from exc
    existing = ObjectStore().get_object(str(resolved_id))
    if existing is None:
        return None
    if existing.kind != RAW_RECORD_KIND:
        raise RawRecordIntegrityError(
            f"object_id {resolved_id} is {existing.kind!r}, not immutable raw evidence"
        )
    record = dict(existing.payload)
    source_kind = record.get("source_kind")
    item_ref = record.get("item_ref")
    content_identity = record.get("content_identity")
    if not all(
        isinstance(value, str) and value
        for value in (source_kind, item_ref, content_identity)
    ):
        raise RawRecordIntegrityError(
            f"raw object {resolved_id} is missing its deterministic identity fields"
        )
    assert isinstance(source_kind, str)
    assert isinstance(item_ref, str)
    assert isinstance(content_identity, str)
    expected_id = raw_record_object_id(
        source_kind=source_kind,
        item_ref=item_ref,
        content_identity=content_identity,
    )
    if expected_id != resolved_id:
        raise RawRecordIntegrityError(
            f"raw object {resolved_id} does not match payload-derived identity {expected_id}"
        )
    return record


def _validated_raw_payload(
    existing: DomainObject,
    *,
    object_id: UUID,
    source_kind: str,
    item_ref: str,
    content_identity: str,
) -> dict[str, Any]:
    if existing.kind != RAW_RECORD_KIND:
        raise RawRecordIntegrityError(
            f"raw identity {object_id} is occupied by kind {existing.kind!r}"
        )
    record = dict(existing.payload)
    expected = {
        "source_kind": source_kind,
        "item_ref": item_ref,
        "content_identity": content_identity,
    }
    mismatched = {
        key: record.get(key)
        for key, value in expected.items()
        if record.get(key) != value
    }
    if mismatched:
        raise RawRecordIntegrityError(
            f"raw identity {object_id} has inconsistent identity fields {sorted(mismatched)}"
        )
    return record


__all__ = [
    "RAW_RECORD_KIND",
    "RawRecordIntegrityError",
    "RawRecordResult",
    "raw_record_object_id",
    "persist_raw_record",
    "find_raw_record",
    "get_raw_record",
]
