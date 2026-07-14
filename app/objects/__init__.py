"""
Canonical import boundary for object-store contract types.

All callers that need ``DomainObject``, ``ObjectStore``, ``RelationEdge``,
``GraphSlice``, ``RelationIndex``, ``ScoredNeighbor``, or ``VectorIndex``
should import from this package::

    from app.objects import DomainObject, ObjectStore
    from app.objects import RelationIndex, RelationEdge, GraphSlice
    from app.objects import VectorIndex, ScoredNeighbor

``DomainObject`` and ``ObjectStore`` are owned here (KERNEL-03 removed the
legacy ``app.store.object_store`` module). Durable writes route exclusively
through the ``app.stores`` provider seam (``resolve_object_store_port``);
store failures propagate — there is no silent in-memory fallback.

``app.store.relation_index`` and ``app.store.vector_index`` remain as
backward-compatibility shims for existing callers and will be migrated
per-area in follow-up issues. See docs/CODE_INVENTORY.md :: Cleanup follow-ups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from app.events.models import new_trace_id
from app.events.types import INGEST_OBJECT_CREATED
from app.services.outbox import insert_object_and_outbox, payload_fingerprint
from app.store.relation_index import RelationEdge, GraphSlice, RelationIndex
from app.store.vector_index import ScoredNeighbor, VectorIndex
from app.stores import resolve_object_store_port


@dataclass
class DomainObject:
    uuid: str
    kind: str
    payload: dict[str, Any]
    source_ref: Optional[str]
    created_at: datetime


# In-process mirror used by the explicit memory backend and as a read-through
# cache. It is never a fallback for a failed durable write (I-S4).
_MEMORY_STORE: dict[str, DomainObject] = {}


def _normalize_ts(ts: datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _list_from_memory(kind: Optional[str] = None, limit: int = 100) -> List[DomainObject]:
    values = list(_MEMORY_STORE.values())
    if kind is not None:
        values = [o for o in values if o.kind == kind]
    values.sort(key=lambda o: o.created_at, reverse=True)
    return values[:limit]


def _to_domain(row: dict[str, Any]) -> DomainObject:
    object_id = row.get("object_id")
    if object_id is None:
        raise ValueError("missing object_id in object row")
    created_at = row.get("created_at")
    return DomainObject(
        uuid=str(object_id),
        kind=str(row.get("kind") or "note"),
        payload=dict(row.get("payload") or {}),
        source_ref=(str(row.get("source_ref")) if row.get("source_ref") else None),
        created_at=_normalize_ts(created_at if isinstance(created_at, datetime) else None),
    )


class ObjectStore:
    """DomainObject facade over the canonical ``app.stores`` provider seam.

    Fail-loud contract (KERNEL-03 / audit invariant I-S4): backend resolution
    and durable store errors propagate to the caller. The in-process mirror is
    only the storage for the explicit memory backend and a read-through cache
    for durable rows — never an error fallback.
    """

    def get_object(self, object_id: str, *, strict_backend: bool = False) -> DomainObject | None:
        # ``strict_backend`` is retained for signature compatibility; store
        # errors always propagate now.
        if object_id in _MEMORY_STORE:
            return _MEMORY_STORE[object_id]

        binding = resolve_object_store_port()
        if binding.backend == "memory":
            return _MEMORY_STORE.get(object_id)
        record = binding.store.get(UUID(str(object_id)))
        if not record:
            return _MEMORY_STORE.get(object_id)
        domain = _to_domain(record)
        _MEMORY_STORE[domain.uuid] = domain
        return domain

    def save_object(
        self,
        obj: DomainObject,
        emit_outbox: bool = True,
        trace_id: Optional[str] = None,
    ) -> None:
        if trace_id is None:
            trace_id = new_trace_id()
        obj.created_at = _normalize_ts(obj.created_at)

        binding = resolve_object_store_port()
        if binding.backend == "memory":
            _MEMORY_STORE[obj.uuid] = obj
            return
        binding.store.put(
            UUID(str(obj.uuid)),
            kind=str(obj.kind or "note"),
            source_ref=str(obj.source_ref or ""),
            payload=dict(obj.payload or {}),
        )
        if emit_outbox:
            # Observation-scoped idempotency key (#2863, KERNEL-02): the emitted
            # payload is only {uuid, kind}, so without a content component a
            # later save of the SAME uuid with CHANGED content derives the same
            # key and is swallowed by ON CONFLICT DO NOTHING — silent event loss
            # while the durable store write still lands. Mixing the durable
            # payload's content fingerprint into the key (fingerprint-only, not
            # into the emitted payload) makes content changes emit a distinct
            # event while a crash-retry of the same save (identical content)
            # still dedups. Mirrors the observation= mechanism from PR #2859.
            insert_object_and_outbox(
                {
                    "uuid": obj.uuid,
                    "kind": obj.kind,
                },
                INGEST_OBJECT_CREATED,
                trace_id=trace_id,
                object_id=obj.uuid,
                source="object_store",
                observation=payload_fingerprint(obj.payload),
            )
        # Mirror only after the durable write succeeded — the mirror must never
        # hold state the durable store does not (I-S4).
        _MEMORY_STORE[obj.uuid] = obj

    def list_objects(
        self,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> List[DomainObject]:
        binding = resolve_object_store_port()
        if binding.backend == "memory":
            return _list_from_memory(kind, limit)
        rows = list(binding.store.list_objects(kind=kind, limit=limit))
        out = [_to_domain(row if isinstance(row, dict) else dict(row)) for row in rows]
        for domain in out:
            _MEMORY_STORE[domain.uuid] = domain
        return out

    def count_objects(self, kind: Optional[str] = None) -> int:
        binding = resolve_object_store_port()
        if binding.backend == "memory":
            values = list(_MEMORY_STORE.values())
            if kind is not None:
                values = [obj for obj in values if obj.kind == kind]
            return len(values)
        return int(binding.store.count_objects(kind=kind))


def save_object_in_transaction(conn: Any, obj: DomainObject) -> None:
    """Persist a canonical object inside an existing Postgres transaction.

    Vault filesystem ingestion also maintains the retained ``objects`` mirror.
    This seam lets that compatibility producer update the canonical parent and
    its outbox/file-state writes atomically without becoming a second SQL
    writer for ``store_objects``.
    """
    from app.stores.pg import put_object_with_connection

    put_object_with_connection(
        conn,
        object_id=UUID(str(obj.uuid)),
        kind=str(obj.kind or "note"),
        source_ref=obj.source_ref,
        payload=dict(obj.payload or {}),
    )


def update_object_source_ref_in_transaction(
    conn: Any,
    *,
    object_id: str,
    source_ref: str | None,
) -> None:
    """Update canonical source identity inside an existing transaction."""
    from app.stores.pg import update_object_source_ref_with_connection

    update_object_source_ref_with_connection(
        conn,
        object_id=UUID(str(object_id)),
        source_ref=source_ref,
    )


__all__ = [
    "DomainObject",
    "ObjectStore",
    "RelationEdge",
    "GraphSlice",
    "RelationIndex",
    "ScoredNeighbor",
    "VectorIndex",
    "save_object_in_transaction",
    "update_object_source_ref_in_transaction",
]
