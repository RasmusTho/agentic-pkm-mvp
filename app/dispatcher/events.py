"""Append-only JSONL event writer for the dispatcher MVP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.dispatcher.models import EventRecord


class JsonlEventWriter:
    """Append events as one JSON object per line.

    JSONL is the audit trail; SQLite remains the live current-state authority.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: EventRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for ln in self._path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            rows.append(json.loads(ln))
        return rows
