from __future__ import annotations

from typing import Optional, List
from app.store.object_store import DomainObject


class FakeObjectStore:
    def __init__(self) -> None:
        self._data: dict[str, DomainObject] = {}

    def save_object(
        self,
        obj: DomainObject,
        emit_outbox: bool = True,
        trace_id: Optional[str] = None,
    ) -> None:
        self._data[obj.uuid] = obj

    def get_object(self, uuid: str) -> Optional[DomainObject]:
        return self._data.get(uuid)

    def list_objects(
        self,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> List[DomainObject]:
        values = list(self._data.values())
        if kind is not None:
            values = [o for o in values if o.kind == kind]
        values.sort(key=lambda o: o.created_at, reverse=True)
        return values[:limit]
