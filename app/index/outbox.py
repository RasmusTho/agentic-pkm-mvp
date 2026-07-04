from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

try:
    import orjson as _json
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without orjson
    import json as _json  # type: ignore

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTBOX_PATH = Path(
    os.environ.get("INDEX_OUTBOX_PATH", str(REPO_ROOT / "tmp" / "index-outbox.jsonl"))
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

    Pure audit log (KERNEL-05, audit invariant I-D3): this function no longer
    fans in to the in-memory retrieval store. Retrieval is populated only by
    ``app.retrieval.hybrid.rebuild_from_durable_index()`` loading from
    ``store_vector_index`` — never from this JSONL append path. See
    docs/RUNTIME_CORRECTNESS_KERNEL/RETRIEVAL_READS_DURABLE_INDEX.md.
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


__all__ = ["append_jsonl", "DEFAULT_OUTBOX_PATH"]
