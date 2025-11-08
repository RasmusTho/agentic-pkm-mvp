from __future__ import annotations
import time, uuid
from dataclasses import dataclass
from typing import Optional, Iterable
from uuid import UUID
from .base import (
    DecisionsStore,
    ObjectsStore,
    Decision,
    ObjectStore,
    VectorIndex,
    RelationIndex,
)


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


class MemoryObjectStore(ObjectStore):
    def __init__(self) -> None:
        self._objects: dict[UUID, dict] = {}
        self._order: list[UUID] = []

    def get(self, object_id: UUID) -> dict | None:
        return self._objects.get(object_id)

    def put(self, object_id: UUID, *, kind: str, source_ref: str, payload: dict) -> None:
        record = {
            "object_id": object_id,
            "kind": kind,
            "source_ref": source_ref,
            "payload": dict(payload),
            "updated_at": time.time(),
        }
        if object_id not in self._objects:
            self._order.append(object_id)
        self._objects[object_id] = record

    def list_by_kind(self, kind: str, *, limit: int = 100) -> Iterable[dict]:
        out: list[dict] = []
        for oid in self._order:
            rec = self._objects.get(oid)
            if not rec:
                continue
            if rec["kind"] != kind:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out


@dataclass
class _VectorEntry:
    object_id: UUID
    kind: str
    source_ref: str
    payload: dict
    embedding: list[float]
    model: str
    seq: int


class _VectorHit:
    __slots__ = ("object_id", "payload", "score", "kind", "source_ref", "model")

    def __init__(self, entry: _VectorEntry, score: float) -> None:
        self.object_id = entry.object_id
        self.payload = entry.payload
        self.kind = entry.kind
        self.source_ref = entry.source_ref
        self.model = entry.model
        self.score = score


class MemoryVectorIndex(VectorIndex):
    def __init__(self) -> None:
        self._entries: dict[UUID, _VectorEntry] = {}
        self._seq = 0

    def upsert(
        self,
        object_id: UUID,
        *,
        kind: str,
        source_ref: str,
        payload: dict,
        embedding: list[float],
        model: str,
    ) -> None:
        self._seq += 1
        self._entries[object_id] = _VectorEntry(
            object_id=object_id,
            kind=kind,
            source_ref=source_ref,
            payload=dict(payload),
            embedding=list(embedding),
            model=model,
            seq=self._seq,
        )

    def search(self, vector: list[float], *, k: int = 5) -> list:
        if not self._entries:
            return []
        results: list[tuple[float, int, _VectorHit]] = []
        for entry in self._entries.values():
            score = self._dot(vector, entry.embedding)
            results.append((score, entry.seq, _VectorHit(entry, score)))
        results.sort(key=lambda item: (-item[0], item[1]))
        return [hit for _, _, hit in results[:k]]

    @staticmethod
    def _dot(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        total = 0.0
        length = min(len(a), len(b))
        for i in range(length):
            total += (a[i] or 0.0) * (b[i] or 0.0)
        return total


class MemoryRelationIndex(RelationIndex):
    def __init__(self) -> None:
        self._links: dict[str, dict[UUID, list[UUID]]] = {}

    def link(self, src: UUID, dst: UUID, *, rel: str, payload: dict | None = None) -> None:
        rel_map = self._links.setdefault(rel, {})
        neighbors = rel_map.setdefault(src, [])
        if dst not in neighbors:
            neighbors.append(dst)

    def neighbors(self, src: UUID, *, rel: str, k: int = 20) -> list[UUID]:
        rel_map = self._links.get(rel, {})
        neighbors = rel_map.get(src, [])
        return neighbors[:k]
