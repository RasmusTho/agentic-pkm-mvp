from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import UUID

from app.components.embeddings import EmbeddingIdentity, get_embedding_identity
from app.embedding_config import coerce_floats, get_embed_dim, l2_normalize

from .base import (
    Decision,
    DecisionsStore,
    ObjectStore,
    ObjectsStore,
    RelationMembership,
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

    def list_objects(self, kind: str | None = None, *, limit: int = 100) -> Iterable[dict]:
        out: list[dict] = []
        for oid in self._order:
            rec = self._objects.get(oid)
            if not rec:
                continue
            if kind is not None and rec.get("kind") != kind:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def count_objects(self, kind: str | None = None) -> int:
        if kind is None:
            return len(self._objects)
        return sum(1 for rec in self._objects.values() if rec.get("kind") == kind)


@dataclass
class _VectorEntry:
    object_id: UUID
    kind: str
    source_ref: str
    payload: dict
    embedding: list[float]
    model: str
    seq: int
    identity: EmbeddingIdentity | None = None


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
        self._identity: EmbeddingIdentity | None = None
        self._dim: int | None = None
        self._seq = 0
        raw_path = (persist_path or os.getenv("INDEX_PERSIST_PATH", "").strip())
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
        identity: EmbeddingIdentity | None = None,
        reconcilable_fallback: bool = False,
    ) -> None:
        # reconcilable_fallback is accepted for interface parity with PgVectorIndex.
        # The in-memory index has no per-row identity column and is dev/test-only,
        # so fallback recording / mixed-identity handling is out of scope here
        # (see docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md "Out of Scope").
        del reconcilable_fallback
        embedding_floats = coerce_floats(embedding)
        resolved_identity = self._ensure_identity(identity, allow_initialize=True)
        dim = len(embedding_floats)
        if resolved_identity.dim != dim:
            raise ValueError(
                f"embedding dim mismatch for identity {resolved_identity.model}: expected {resolved_identity.dim}, got {dim}"
            )
        if model and model != resolved_identity.model:
            raise ValueError(
                f"embedding model mismatch: stored={resolved_identity.model} provided={model}"
            )
        model_value = model or resolved_identity.model
        if resolved_identity.normalize:
            embedding_norm = l2_normalize(embedding_floats)
        else:
            embedding_norm = embedding_floats

        self._seq += 1
        entry = _VectorEntry(
            object_id=object_id,
            kind=kind,
            source_ref=source_ref,
            payload=dict(payload),
            embedding=embedding_norm,
            model=model_value,
            seq=self._seq,
            identity=self._identity,
        )
        self._entries[object_id] = entry
        self._persist_entry(entry)

    def purge_vectors(self, object_id: UUID, *, view: str) -> int:
        del view
        if object_id in self._entries:
            del self._entries[object_id]
            return 1
        return 0

    def count_vectors(self) -> int:
        return len(self._entries)

    def search(self, vector: list[float], *, k: int = 5, identity: EmbeddingIdentity | None = None) -> list:
        if not self._entries:
            return []

        resolved_identity = self._ensure_identity(identity, allow_initialize=False)
        query = coerce_floats(vector)
        dim = len(query)
        if dim != resolved_identity.dim:
            raise ValueError(
                f"query embedding dim mismatch: expected {resolved_identity.dim}, got {dim}"
            )
        if resolved_identity.normalize:
            query_norm = l2_normalize(query)
        else:
            query_norm = query

        results: list[tuple[float, int, _VectorHit]] = []
        for entry in self._entries.values():
            score = self._dot(query_norm, entry.embedding)
            results.append((score, entry.seq, _VectorHit(entry, score)))
        results.sort(key=lambda item: (-item[0], item[1]))
        return [hit for _, _, hit in results[:k]]

    def get_identity(self) -> EmbeddingIdentity | None:
        return self._identity

    def _ensure_identity(self, supplied: EmbeddingIdentity | None, *, allow_initialize: bool) -> EmbeddingIdentity:
        effective = supplied or get_embedding_identity()
        stored = self._identity
        if stored is None:
            if not allow_initialize:
                raise ValueError("vector index identity has not been established; insert embeddings first")
            if effective.dim <= 0:
                raise ValueError("embedding identity must include a positive dimension")
            self._identity = EmbeddingIdentity(
                provider=effective.provider,
                model=effective.model,
                dim=effective.dim,
                normalize=effective.normalize,
            )
            self._dim = effective.dim
            return self._identity
        if (
            stored.provider != effective.provider
            or stored.model != effective.model
            or stored.dim != effective.dim
            or stored.normalize != effective.normalize
        ):
            raise ValueError(
                "embedding identity mismatch: expected provider={} model={} dim={} normalize={}; got provider={} model={} dim={} normalize={}. "
                "Run 'python -m app.cli index rebuild' to realign the index.".format(
                    stored.provider,
                    stored.model,
                    stored.dim,
                    stored.normalize,
                    effective.provider,
                    effective.model,
                    effective.dim,
                    effective.normalize,
                )
            )
        return stored

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
            "identity": asdict(self._identity) if self._identity else None,
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
                    if not embedding:
                        continue
                    dim = len(embedding)
                    identity_data = data.get("identity") if isinstance(data.get("identity"), dict) else None
                    loaded_identity = None
                    if identity_data:
                        try:
                            loaded_identity = EmbeddingIdentity(
                                provider=str(identity_data.get("provider", "")),
                                model=str(identity_data.get("model", "")),
                                dim=int(identity_data.get("dim", 0) or 0),
                                normalize=bool(identity_data.get("normalize", True)),
                            )
                        except Exception:
                            loaded_identity = None
                    if loaded_identity and loaded_identity.dim and loaded_identity.dim != dim:
                        continue
                    if self._identity is None:
                        if loaded_identity:
                            self._identity = loaded_identity
                        else:
                            self._identity = EmbeddingIdentity(
                                provider="legacy",
                                model=str(data.get("model", "")),
                                dim=dim,
                                normalize=True,
                            )
                    elif loaded_identity and (
                        loaded_identity.provider != self._identity.provider
                        or loaded_identity.model != self._identity.model
                        or (loaded_identity.dim and loaded_identity.dim != self._identity.dim)
                        or loaded_identity.normalize != self._identity.normalize
                    ):
                        continue
                    if self._identity.dim != dim:
                        continue

                    embedding_values = coerce_floats(embedding)
                    if self._identity.normalize:
                        stored_embedding = l2_normalize(embedding_values)
                    else:
                        stored_embedding = embedding_values

                    entry = _VectorEntry(
                        object_id=obj_id,
                        kind=str(data.get("kind", "")),
                        source_ref=str(data.get("source_ref", "")),
                        payload=data.get("payload") or {},
                        embedding=stored_embedding,
                        model=str(data.get("model", "")),
                        seq=int(data.get("seq", 0)),
                        identity=self._identity,
                    )
                    self._dim = self._identity.dim
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
        self._memberships: dict[str, dict[UUID, list[dict[str, Any]]]] = {}

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

    def add_membership(self, src: UUID, *, rel: str, value: str, payload: dict | None = None) -> None:
        rel_map = self._memberships.setdefault(rel, {})
        memberships = rel_map.setdefault(src, [])
        for entry in memberships:
            if entry["value"] == value:
                entry["payload"] = dict(payload or {})
                return
        memberships.append({"value": value, "payload": dict(payload or {})})

    def memberships(self, src: UUID, *, rel: str | None = None) -> list[RelationMembership]:
        if rel is not None:
            rel_items = ((rel, self._memberships.get(rel, {})),)
        else:
            rel_items = self._memberships.items()
        out: list[RelationMembership] = []
        for relation_type, rel_map in rel_items:
            for entry in rel_map.get(src, []):
                out.append(
                    RelationMembership(
                        object_id=src,
                        relation_type=relation_type,
                        value=str(entry["value"]),
                        payload=dict(entry.get("payload") or {}),
                    )
                )
        return out
