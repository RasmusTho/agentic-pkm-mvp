"""Append-only JSONL event writer for the dispatcher MVP."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.dispatcher.models import EventRecord


def claim_event_digest(event: Mapping[str, Any]) -> str:
    """Digest the immutable claim projection used by a predecessor comparison."""
    fields = ("event_id", "timestamp", "task_id", "event_type", "actor", "lease_id", "payload")
    if set(event) != set(fields) or event.get("event_type") != "task.claimed" or not isinstance(event.get("payload"), dict):
        raise ValueError("claim event projection is invalid")
    try:
        encoded = json.dumps(dict(event), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("claim event projection is invalid") from exc
    return hashlib.sha256(encoded).hexdigest()


def event_history_digest(events: Sequence[Mapping[str, Any]]) -> str:
    """Digest the exact ordered dispatcher event projection, without emitting it."""
    fields = {"event_id", "timestamp", "task_id", "event_type", "actor", "lease_id", "payload"}
    if any(not isinstance(event, Mapping) or set(event) != fields for event in events):
        raise ValueError("dispatcher event history projection is invalid")
    try:
        encoded = json.dumps([dict(event) for event in events], sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("dispatcher event history projection is invalid") from exc
    return hashlib.sha256(encoded).hexdigest()


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
