from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from app.events.models import new_trace_id
from app.events.types import INGEST_OBJECT_CREATED
from app.services.outbox import insert_object_and_outbox
from app.stores import resolve_object_store_port


@dataclass
class DomainObject:
    uuid: str
    kind: str
    payload: dict[str, Any]
    source_ref: Optional[str]
    created_at: datetime


# Legacy in-process mirror kept for test compatibility and local fallback behavior.
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
    def get_object(self, object_id: str, *, strict_backend: bool = False) -> DomainObject | None:
        if object_id in _MEMORY_STORE:
            return _MEMORY_STORE[object_id]

        try:
            binding = resolve_object_store_port()
            if binding.backend == "memory":
                return _MEMORY_STORE.get(object_id)
            record = binding.store.get(UUID(str(object_id)))
            if not record:
                return _MEMORY_STORE.get(object_id)
            domain = _to_domain(record)
            _MEMORY_STORE[domain.uuid] = domain
            return domain
        except Exception:
            if strict_backend:
                raise
            return _MEMORY_STORE.get(object_id)

    def save_object(
        self,
        obj: DomainObject,
        emit_outbox: bool = True,
        trace_id: Optional[str] = None,
    ) -> None:
        if trace_id is None:
            trace_id = new_trace_id()
        obj.created_at = _normalize_ts(obj.created_at)
        _MEMORY_STORE[obj.uuid] = obj

        try:
            binding = resolve_object_store_port()
            if binding.backend == "memory":
                return
            binding.store.put(
                UUID(str(obj.uuid)),
                kind=str(obj.kind or "note"),
                source_ref=str(obj.source_ref or ""),
                payload=dict(obj.payload or {}),
            )
            if emit_outbox:
                insert_object_and_outbox(
                    {
                        "uuid": obj.uuid,
                        "kind": obj.kind,
                    },
                    INGEST_OBJECT_CREATED,
                    trace_id=trace_id,
                    object_id=obj.uuid,
                    source="object_store",
                )
        except Exception:
            return

    def list_objects(
        self,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> List[DomainObject]:
        try:
            binding = resolve_object_store_port()
            if binding.backend == "memory":
                return _list_from_memory(kind, limit)
            rows = list(binding.store.list_objects(kind=kind, limit=limit))
            out = [_to_domain(row if isinstance(row, dict) else dict(row)) for row in rows]
            for domain in out:
                _MEMORY_STORE[domain.uuid] = domain
            return out
        except Exception:
            return _list_from_memory(kind, limit)

    def count_objects(self, kind: Optional[str] = None) -> int:
        try:
            binding = resolve_object_store_port()
            if binding.backend == "memory":
                values = list(_MEMORY_STORE.values())
                if kind is not None:
                    values = [obj for obj in values if obj.kind == kind]
                return len(values)
            return int(binding.store.count_objects(kind=kind))
        except Exception:
            values = list(_MEMORY_STORE.values())
            if kind is not None:
                values = [obj for obj in values if obj.kind == kind]
            return len(values)
