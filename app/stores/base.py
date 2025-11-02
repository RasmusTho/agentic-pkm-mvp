from __future__ import annotations
from typing import Protocol, TypedDict, Optional


class Decision(TypedDict):
    id: str
    object_id: str
    agent: str
    kind: str
    key: str
    value: dict


class DecisionsStore(Protocol):
    def put(self, *, object_id: str, agent: str, kind: str, key: str, value: dict) -> dict: ...
    def latest(self, *, object_id: str, key: str) -> Optional[Decision]: ...


class ObjectsStore(Protocol):
    def upsert(self, *, kind: str, payload: dict, source_ref: str | None = None, path: str | None = None) -> dict: ...
