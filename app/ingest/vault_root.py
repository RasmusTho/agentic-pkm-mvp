from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.agents.classifier.agent import run as classify_run
from app.agents.normalizer.agent import run as normalize_run
from app.index.outbox import append_jsonl
from app.observability.ingest_meta import record_ingest_failure, record_ingest_success
from app.obs.log import with_trace_id
from app.search.service import ingest_object as index_ingest_object
from app.stores import get_object_store

logger = logging.getLogger(__name__)


def iter_vault_root_markdown(root: Path, limit: int | None = None) -> Iterable[Path]:
    """
    Yield up to `limit` markdown files in the vault root (non-recursive).
    Only regular `.md` files; ignore hidden files and directories.
    """
    if not root.exists() or not root.is_dir():
        return []
    files = [
        p
        for p in root.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".md"
    ]
    files.sort(key=lambda p: p.name.lower())
    if limit is not None:
        files = files[:max(limit, 0)]
    return files


def _ingest_file(path: Path, *, trace_id: str) -> str:
    text = path.read_text(encoding="utf-8")
    normalize_res = normalize_run(str(path), trace_id=trace_id)
    object_id = str(normalize_res.get("object_id") or normalize_res.get("uuid") or "").strip()
    if not object_id:
        raise RuntimeError("normalize did not return object_id")

    classify_res = classify_run(object_id, trace_id=trace_id)
    append_jsonl(
        {
            "object_id": object_id,
            "kind": "pipeline",
            "source_ref": str(path),
            "payload": {"normalize": normalize_res, "classify": classify_res},
        }
    )

    try:
        object_uuid = uuid.UUID(object_id)
    except Exception:
        object_uuid = uuid.uuid4()

    title = (normalize_res.get("core6") or {}).get("title")
    payload = {"title": title, "origin": "vault", "source": str(path)}
    try:
        index_ingest_object(
            object_id=object_uuid,
            kind="note",
            source_ref=str(path),
            payload=payload,
            text=text,
        )
    except Exception:
        logger.exception("Vector index ingest failed for %s", path)

    try:
        store = get_object_store()
        store.put(object_uuid, kind="note", source_ref=str(path), payload={**payload, "text": text})
    except Exception:
        logger.exception("Object store upsert failed for %s", path)

    return object_id


def ingest_vault_root(root: Path, limit: int | None = None) -> int:
    """
    Run the existing ingestion pipeline on up to `limit` markdown files
    in the vault root. Returns the number of files successfully ingested.
    """
    run_started = datetime.now(timezone.utc)
    processed = 0
    failures = 0
    files = iter_vault_root_markdown(root, limit)
    try:
        for path in files:
            trace_id = with_trace_id(None)
            try:
                _ingest_file(path, trace_id=trace_id)
                processed += 1
            except Exception as exc:  # pragma: no cover - defensive logging
                failures += 1
                logger.exception("Failed to ingest %s: %s", path, exc)
        record_ingest_success(run_started)
    except Exception as exc:
        record_ingest_failure(run_started, str(exc))
        raise

    if failures:
        logger.warning("Vault root ingest completed with %s failures", failures)
    return processed


__all__ = ["iter_vault_root_markdown", "ingest_vault_root"]
