from __future__ import annotations
import time, uuid
from typing import Optional
from .base import DecisionsStore, ObjectsStore, Decision


class MemoryObjects(ObjectsStore):
    def __init__(self) -> None:
        self._o: dict[str, dict] = {}

    def upsert(self, *, kind: str, payload: dict, source_ref: str | None = None, path: str | None = None) -> dict:
        oid = str(uuid.uuid4())
        self._o[oid] = {
            "id": oid,
            "kind": kind,
            "payload": payload,
            "source_ref": source_ref,
            "path": path,
            "created_at": time.time(),
        }
        return {"id": oid}


class MemoryDecisions(DecisionsStore):
    def __init__(self) -> None:
        self._d: list[Decision] = []

    def put(self, *, object_id: str, agent: str, kind: str, key: str, value: dict) -> dict:
        did = str(uuid.uuid4())
        self._d.append(
            {
                "id": did,
                "object_id": object_id,
                "agent": agent,
                "kind": kind,
                "key": key,
                "value": value,
                "created_at": time.time(),
            }  # type: ignore[typeddict-item]
        )
        return {"id": did}

    def latest(self, *, object_id: str, key: str) -> Optional[Decision]:
        xs = [d for d in self._d if d["object_id"] == object_id and d["key"] == key]
        xs.sort(key=lambda d: d.get("created_at", 0), reverse=True)
        return xs[0] if xs else None
