from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import UUID

from app.embedding_config import assert_embed_dim, coerce_floats, get_embed_dim, l2_normalize

from .base import (
    Decision,
    DecisionsStore,
    ObjectStore,
    ObjectsStore,
    RelationIndex,
    VectorIndex,
)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
    def __init__(self, *, persist_path: str | None = None, load_existing: bool | None = None) -> None:
        self._entries: dict[UUID, _VectorEntry] = {}
        self._seq = 0
        raw_path = (persist_path or os.getenv("INDEX_PERSIST_PATH", "")).strip()
        self._persist_path = Path(raw_path).expanduser() if raw_path else None
        should_load = bool(self._persist_path) and (
            load_existing if load_existing is not None else _truthy_env("INDEX_PERSIST_LOAD")
        )
        if should_load:
            self._load_from_disk()

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
        embedding_floats = coerce_floats(embedding)
        assert_embed_dim(embedding_floats, name="embedding")
        embedding_norm = l2_normalize(embedding_floats)

        self._seq += 1
        entry = _VectorEntry(
            object_id=object_id,
            kind=kind,
            source_ref=source_ref,
            payload=dict(payload),
            embedding=embedding_norm,
            model=model,
            seq=self._seq,
        )
        self._entries[object_id] = entry
        self._persist_entry(entry)

    def search(self, vector: list[float], *, k: int = 5) -> list:
        if not self._entries:
            return []

        query = coerce_floats(vector)
        assert_embed_dim(query, name="query embedding")
        query_norm = l2_normalize(query)

        results: list[tuple[float, int, _VectorHit]] = []
        for entry in self._entries.values():
            score = self._dot(query_norm, entry.embedding)
            results.append((score, entry.seq, _VectorHit(entry, score)))
        results.sort(key=lambda item: (-item[0], item[1]))
        return [hit for _, _, hit in results[:k]]

    def _persist_entry(self, entry: _VectorEntry) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "object_id": str(entry.object_id),
            "kind": entry.kind,
            "source_ref": entry.source_ref,
            "payload": entry.payload,
            "embedding": entry.embedding,
            "model": entry.model,
            "seq": entry.seq,
        }
        with self._persist_path.open("a", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, default=str)
            fh.write("\n")

    def _load_from_disk(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        expected_dim = get_embed_dim()
        try:
            with self._persist_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        obj_id = UUID(str(data["object_id"]))
                    except Exception:
                        continue

                    embedding = list(data.get("embedding") or [])
                    if len(embedding) != expected_dim:
                        continue

                    entry = _VectorEntry(
                        object_id=obj_id,
                        kind=str(data.get("kind", "")),
                        source_ref=str(data.get("source_ref", "")),
                        payload=data.get("payload") or {},
                        embedding=l2_normalize(coerce_floats(embedding)),
                        model=str(data.get("model", "")),
                        seq=int(data.get("seq", 0)),
                    )
                    self._entries[obj_id] = entry
                    self._seq = max(self._seq, entry.seq)
        except FileNotFoundError:
            return

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
        self._links: dict[str, dict[UUID, list[dict[str, Any]]]] = {}

    def link(self, src: UUID, dst: UUID, *, rel: str, payload: dict | None = None) -> None:
        rel_map = self._links.setdefault(rel, {})
        neighbors = rel_map.setdefault(src, [])
        for entry in neighbors:
            if entry["dst"] == dst:
                entry["payload"] = dict(payload or {})
                return
        neighbors.append({"dst": dst, "payload": dict(payload or {})})

    def neighbors(self, src: UUID, *, rel: str, k: int = 20) -> list[UUID]:
        rel_map = self._links.get(rel, {})
        neighbors = rel_map.get(src, [])
        return [entry["dst"] for entry in neighbors[:k]]

    def has_any(self, src: UUID) -> bool:
        for rel_map in self._links.values():
            if src in rel_map and rel_map[src]:
                return True
            for neighbors in rel_map.values():
                for entry in neighbors:
                    if entry["dst"] == src:
                        return True
        return False
