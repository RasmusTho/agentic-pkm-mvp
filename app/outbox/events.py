from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

from app.embedding_config import get_embed_dim
from app.events.schema import make_outbox_event
from app.llm.embeddings import EMBED_MODEL
from app.services.outbox import write_outbox_event
from app.settings.watcher_settings import load_watcher_settings

def _try_writable_path(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    try:
        with path.open("a", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


def _build_candidate_list(env_value: str | None) -> list[Path]:
    values: list[Path] = []
    if env_value and env_value.strip():
        values.append(Path(env_value).expanduser())
    values.append(load_watcher_settings().paths.index_outbox)
    return values


class _DynamicIndexOutboxPath:
    def __init__(self) -> None:
        self._cache_env: str | None = None
        self._cache_path: Path | None = None

    def _resolve(self, env_value: str | None) -> Path:
        for candidate in _build_candidate_list(env_value):
            if _try_writable_path(candidate):
                return candidate
        raise RuntimeError("Could not resolve a writable INDEX_OUTBOX_PATH")

    def current(self) -> Path:
        env_value = os.environ.get("INDEX_OUTBOX_PATH")
        env_key = env_value.strip() if env_value else ""
        if env_key == self._cache_env and self._cache_path is not None:
            return self._cache_path
        path = self._resolve(env_value)
        self._cache_env = env_key
        self._cache_path = path
        return path

    def __getattr__(self, name: str):
        return getattr(self.current(), name)

    def __fspath__(self) -> str:
        return str(self.current())

    def __str__(self) -> str:
        return str(self.current())


INDEX_OUTBOX_PATH = _DynamicIndexOutboxPath()
INDEX_EMBEDDING_REQUESTED = "index.embedding.requested"
INDEX_EMBEDDING_CREATED = "index.embedding.created"
INDEX_EMBEDDING_FAILED = "index.embedding.failed"
INDEX_OBJECT_EMBEDDED = "index.object.embedded"
DEFAULT_EMBEDDING_VIEW = "markdown.semantic"


def get_index_outbox_path() -> Path:
    return Path(INDEX_OUTBOX_PATH)


def _coerce_uuid(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _append_record(record: Dict[str, Any]) -> None:
    INDEX_OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_OUTBOX_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def emit_index_embedding_requested(event: Dict[str, Any]) -> None:
    if "object_id" not in event:
        raise ValueError("index.embedding.requested missing field: object_id")

    payload = dict(event)
    payload["object_id"] = _coerce_uuid(payload["object_id"])
    payload.pop("embedding", None)

    trace_val = payload.get("trace_id")
    envelope = make_outbox_event(
        INDEX_EMBEDDING_REQUESTED,
        source=str(payload.get("source") or "ingest"),
        trace_id=str(trace_val) if trace_val else None,
        payload={"object_id": payload["object_id"]},
        meta={k: v for k, v in payload.items() if k not in {"object_id", "trace_id", "source"}},
    )

    record: Dict[str, Any] = dict(envelope.model_dump())
    try:
        write_outbox_event(envelope, idempotency_key=str(record.get("event_id") or ""))
    except Exception:
        # Compatibility fallback: keep audit emission even when DB outbox is unavailable
        # (e.g. unit tests or local flows without Postgres).
        pass
    _append_record(record)


def _build_index_record(
    envelope: Any,
    *,
    object_id: str,
    metrics: Dict[str, Any] | None = None,
    provenance: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    record: Dict[str, Any] = dict(envelope.model_dump())
    record["uuid"] = object_id
    if metrics is not None:
        record["metrics"] = metrics
    if provenance is not None:
        record["provenance"] = provenance
    return record


def emit_index_embedding_created(*, object_id: UUID, trace_id: str | None = None, source: str = "indexer") -> None:
    envelope = make_outbox_event(
        INDEX_EMBEDDING_CREATED,
        source=source,
        trace_id=trace_id,
        payload={"object_id": str(object_id)},
        meta={},
    )

    metrics = {"vectors": 1, "dim": get_embed_dim(), "view": DEFAULT_EMBEDDING_VIEW}
    provenance = {"model": EMBED_MODEL, "version": "1.0"}
    record = _build_index_record(envelope, object_id=str(object_id), metrics=metrics, provenance=provenance)
    _append_record(record)


def emit_index_object_embedded(
    *,
    object_id: UUID | str,
    trace_id: str | None = None,
    source: str = "indexer",
    source_ref: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    dim: int | None = None,
    view: str = DEFAULT_EMBEDDING_VIEW,
    meta: Dict[str, Any] | None = None,
) -> None:
    envelope = make_outbox_event(
        INDEX_OBJECT_EMBEDDED,
        source=source,
        trace_id=trace_id,
        payload={"object_id": _coerce_uuid(object_id)},
        meta=meta or {},
    )

    metrics = {"vectors": 1, "dim": dim or get_embed_dim(), "view": view}
    provenance = {"model": model or EMBED_MODEL, "provider": provider or "indexer"}
    record = _build_index_record(
        envelope,
        object_id=_coerce_uuid(object_id),
        metrics=metrics,
        provenance=provenance,
    )
    if source_ref is not None:
        record.setdefault("meta", {})["source_ref"] = source_ref
    _append_record(record)


def emit_index_embedding_failed(
    *,
    object_id: UUID | str,
    trace_id: str | None = None,
    source: str = "indexer",
    source_ref: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    expected_dim: int | None = None,
    actual_dim: int | None = None,
    error: str | None = None,
) -> None:
    meta: Dict[str, Any] = {k: v for k, v in {
        "provider": provider,
        "model": model,
        "expected_dim": expected_dim,
        "actual_dim": actual_dim,
        "error": error,
        "source_ref": source_ref,
    }.items() if v is not None}

    envelope = make_outbox_event(
        INDEX_EMBEDDING_FAILED,
        source=source,
        trace_id=trace_id,
        payload={"object_id": _coerce_uuid(object_id)},
        meta=meta,
    )

    record = _build_index_record(
        envelope,
        object_id=_coerce_uuid(object_id),
        metrics={"vectors": 0, "dim": expected_dim if expected_dim is not None else actual_dim or get_embed_dim(), "view": DEFAULT_EMBEDDING_VIEW},
        provenance={"model": model or EMBED_MODEL, "provider": provider or "indexer"},
    )
    _append_record(record)


__all__ = [
    "emit_index_embedding_requested",
    "emit_index_embedding_created",
    "emit_index_object_embedded",
    "emit_index_embedding_failed",
    "INDEX_OUTBOX_PATH",
    "INDEX_EMBEDDING_REQUESTED",
    "INDEX_EMBEDDING_CREATED",
    "INDEX_EMBEDDING_FAILED",
    "INDEX_OBJECT_EMBEDDED",
    "get_index_outbox_path",
]
