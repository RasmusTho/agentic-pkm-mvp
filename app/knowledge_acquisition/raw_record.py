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

from app.objects import DomainObject, ObjectStore
from app.observability.log import json_log

RAW_RECORD_KIND = "knowledge_acquisition.raw"


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
            record=dict(existing.payload),
        )

    record_payload = dict(payload)
    record_payload.setdefault("content_identity", content_identity)
    record_payload.setdefault("source_kind", source_kind)
    record_payload.setdefault("item_ref", item_ref)
    record_payload.setdefault("acquired_at", time.time())

    domain_object = DomainObject(
        uuid=str(object_id),
        kind=RAW_RECORD_KIND,
        payload=record_payload,
        source_ref=source_ref,
        created_at=datetime.now(timezone.utc),
    )
    # emit_outbox=False: see module docstring — raw fetch is pre-pipeline and
    # must not trigger the indexer/embedding consumer.
    store.save_object(domain_object, emit_outbox=False)
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


def get_raw_record(object_id: UUID) -> dict[str, Any] | None:
    existing = ObjectStore().get_object(str(object_id))
    if existing is None:
        return None
    return dict(existing.payload)


__all__ = [
    "RAW_RECORD_KIND",
    "RawRecordResult",
    "raw_record_object_id",
    "persist_raw_record",
    "get_raw_record",
]
