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
import threading
from typing import Any, List, Optional
from uuid import UUID

from app.events.models import new_trace_id
from app.events.types import INGEST_OBJECT_CREATED
from app.services.outbox import insert_object_and_outbox, payload_fingerprint
from app.objects.relation_types import RelationEdge, GraphSlice
from app.stores.base import RelationIndex
from app.store.vector_index import ScoredNeighbor, VectorIndex
from app.stores import resolve_object_store_port


@dataclass
class DomainObject:
    uuid: str
    kind: str
    payload: dict[str, Any]
    source_ref: Optional[str]
    created_at: datetime


# In-process storage for the explicit memory backend. Durable backends always
# read their own committed state: this dictionary has no transaction-aware
# invalidation protocol and therefore must not act as a Postgres cache (I-S4).
_MEMORY_STORE: dict[str, DomainObject] = {}
_MEMORY_STORE_LOCK = threading.RLock()


def _normalize_ts(ts: datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _list_from_memory(
    kind: Optional[str] = None, limit: int | None = 100
) -> List[DomainObject]:
    values = list(_MEMORY_STORE.values())
    if kind is not None:
        values = [o for o in values if o.kind == kind]
    values.sort(key=lambda o: o.created_at, reverse=True)
    return values if limit is None else values[:limit]


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
    only stores the explicit memory backend; durable reads always consult their
    canonical store and never fall back to process memory.
    """

    def get_object(self, object_id: str, *, strict_backend: bool = False) -> DomainObject | None:
        # ``strict_backend`` is retained for signature compatibility; store
        # errors always propagate now.
        binding = resolve_object_store_port()
        if binding.backend == "memory":
            with _MEMORY_STORE_LOCK:
                return _MEMORY_STORE.get(object_id)
        record = binding.store.get(UUID(str(object_id)))
        if not record:
            return None
        return _to_domain(record)

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
            with _MEMORY_STORE_LOCK:
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
                required_db=True,
            )
        # Do not mirror durable state in-process: transactional producers can
        # commit through another connection, so a process-local cache cannot be
        # invalidated atomically with every canonical write.

    def create_object_once(self, obj: DomainObject) -> bool:
        """Atomically create an immutable object identity without an upsert fallback.

        Returns ``True`` for the winner and ``False`` when the identity already exists. This
        StorePort seam is for raw evidence and immutable derived-run artifacts; rebuildable
        projections that intentionally replace equivalent bytes continue to use ``save_object``.
        """
        obj.created_at = _normalize_ts(obj.created_at)
        binding = resolve_object_store_port()
        if binding.backend == "memory":
            with _MEMORY_STORE_LOCK:
                if obj.uuid in _MEMORY_STORE:
                    return False
                _MEMORY_STORE[obj.uuid] = obj
                return True
        return bool(
            binding.store.put_if_absent(
                UUID(str(obj.uuid)),
                kind=str(obj.kind or "note"),
                source_ref=str(obj.source_ref or ""),
                payload=dict(obj.payload or {}),
            )
        )

    def list_objects(
        self,
        kind: Optional[str] = None,
        limit: int | None = 100,
    ) -> List[DomainObject]:
        binding = resolve_object_store_port()
        if binding.backend == "memory":
            with _MEMORY_STORE_LOCK:
                return _list_from_memory(kind, limit)
        rows = list(binding.store.list_objects(kind=kind, limit=limit))
        return [_to_domain(row if isinstance(row, dict) else dict(row)) for row in rows]

    def count_objects(self, kind: Optional[str] = None) -> int:
        binding = resolve_object_store_port()
        if binding.backend == "memory":
            with _MEMORY_STORE_LOCK:
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
    from app.stores.pg import assert_store_schema_with_connection, put_object_with_connection

    assert_store_schema_with_connection(conn)

    put_object_with_connection(
        conn,
        object_id=UUID(str(obj.uuid)),
        kind=str(obj.kind or "note"),
        source_ref=obj.source_ref,
        payload=dict(obj.payload or {}),
    )
    # Defensive cleanup for processes that populated this key while using the
    # explicit memory backend. Postgres reads never consult this dictionary.
    _MEMORY_STORE.pop(str(obj.uuid), None)


def resolve_canonical_object_id_in_transaction(conn: Any, vault_uuid: str) -> str:
    """Resolve a retained vault UUID to the canonical object id on ``conn``."""
    from app.stores.pg import resolve_vault_uuid_with_connection

    return resolve_vault_uuid_with_connection(conn, vault_uuid)


def resolve_canonical_object_id(vault_uuid: str) -> str:
    """Resolve runtime vault identity without weakening durable fail-loud behavior.

    The explicit memory backend has no retained compatibility table, so its
    vault UUID is already the object id.  The Postgres backend must consult the
    retained ``objects.uuid -> objects.id`` mapping before any canonical write
    or lifecycle event; database failures propagate just like the write that
    follows.
    """
    binding = resolve_object_store_port()
    if binding.backend != "pg":
        return str(vault_uuid)

    from app.stores.pg import resolve_vault_uuid

    return resolve_vault_uuid(str(vault_uuid))


def canonical_event_identity(canonical_object_id: str, vault_uuid: str) -> dict[str, str]:
    """Return the single reviewed lifecycle-event identity shape for #3510."""
    return {
        "uuid": str(canonical_object_id),
        "object_id": str(canonical_object_id),
        "vault_uuid": str(vault_uuid),
    }


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
    _MEMORY_STORE.pop(str(object_id), None)


__all__ = [
    "DomainObject",
    "ObjectStore",
    "RelationEdge",
    "GraphSlice",
    "RelationIndex",
    "ScoredNeighbor",
    "VectorIndex",
    "save_object_in_transaction",
    "resolve_canonical_object_id",
    "resolve_canonical_object_id_in_transaction",
    "canonical_event_identity",
    "update_object_source_ref_in_transaction",
]
