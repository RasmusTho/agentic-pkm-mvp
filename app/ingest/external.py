from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List
from uuid import uuid4

from app.observability.ingest_meta import record_ingest_run
from app.search.service import ingest_object as index_ingest_object
from app.stores import get_object_store

logger = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS = {".txt", ".md"}


@dataclass
class ExternalIngestSummary:
    scanned: int
    ingested: int
    errors: int = 0
    error_files: List[str] = field(default_factory=list)


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file() and root.suffix.lower() in SUPPORTED_EXTENSIONS:
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def ingest_external_folder(root: Path, *, limit: int | None = None) -> ExternalIngestSummary:
    root = root.expanduser().resolve()
    files = list(_iter_files(root))
    if limit is not None:
        files = files[: max(limit, 0)]
    scanned = len(files)
    ingested = 0
    errors: list[str] = []
    store = get_object_store()

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            title = path.stem
            object_id = uuid4()
            payload = {
                "title": title,
                "origin": "external_raw",
                "plane": "external",
                "source_ref": str(path),
                "text": text,
                "content": text,
            }
            store.put(object_id, kind="external", source_ref=str(path), payload=payload)
            index_ingest_object(object_id=object_id, kind="external", source_ref=str(path), payload=payload, text=text)
            ingested += 1
        except Exception as exc:
            errors.append(str(path))
            logger.warning("Failed to ingest external file %s: %s", path, exc)
            continue

    summary = ExternalIngestSummary(scanned=scanned, ingested=ingested, errors=len(errors), error_files=errors)
    try:
        record_ingest_run(
            "external",
            scanned=summary.scanned,
            ingested=summary.ingested,
            errors=summary.errors,
            malformed=0,
            ok=summary.errors == 0,
            message=None if summary.errors == 0 else "external ingest errors",
        )
    except Exception:
        pass
    return summary


__all__ = ["ingest_external_folder", "ExternalIngestSummary", "SUPPORTED_EXTENSIONS"]
