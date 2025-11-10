from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

try:
    import orjson as _json
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without orjson
    import json as _json  # type: ignore

# Default path complies with spec (tmp/index-outbox.jsonl)
DEFAULT_OUTBOX_PATH = Path(
    os.environ.get("INDEX_OUTBOX_PATH", "./tmp/index-outbox.jsonl")
).expanduser()
os.environ.setdefault("INDEX_OUTBOX_PATH", str(DEFAULT_OUTBOX_PATH))


def _current_outbox_path() -> Path:
    return Path(os.environ.get("INDEX_OUTBOX_PATH", str(DEFAULT_OUTBOX_PATH))).expanduser()


def _ensure_dir(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def append_jsonl(obj: Dict[str, Any]) -> None:
    """
    Append a validated JSON document to the index outbox.
    Ensures directory exists and writes one line per entry.
    """
    for field in ("object_id", "kind", "payload"):
        if field not in obj:
            raise ValueError(f"index-outbox entry missing '{field}'")
    path = _current_outbox_path()
    _ensure_dir(path)
    dumped = _json.dumps(obj)
    line = dumped.decode("utf-8") if isinstance(dumped, (bytes, bytearray)) else dumped
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        if not line.endswith("\n"):
            fh.write("\n")

    # Opportunistically fan-in to in-memory retrieval store (best effort)
    try:
        payload = obj.get("payload") or {}
        text = payload.get("content") or payload.get("text")
        if text:
            from app.retrieval.hybrid import get_store

            get_store().add_document(
                doc_id=obj["object_id"],
                text=str(text),
                language=payload.get("language"),
                source_ref=obj.get("source_ref"),
            )
    except Exception:
        # retrieval store is best-effort; never block outbox writes
        pass


__all__ = ["append_jsonl", "DEFAULT_OUTBOX_PATH"]
