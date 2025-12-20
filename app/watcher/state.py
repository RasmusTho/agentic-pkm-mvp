from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WatcherState:
    files: dict[str, dict[str, float | str | None]] = field(default_factory=dict)
    changed_detected: int = 0
    intents_emitted: int = 0
    ticks_run: int = 0
    errors: int = 0
    rate_limited: int = 0
    backoff_until: float | None = None
    last_summary_at: float | None = None
    last_stop_warning: float | None = None
    rate_window: list[float] = field(default_factory=list)
    last_trace_id: str | None = None

    @classmethod
    def load(cls, path: Path) -> WatcherState:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        return cls(
            files=dict(data.get("files") or {}),
            changed_detected=int(data.get("changed_detected") or 0),
            intents_emitted=int(data.get("intents_emitted") or 0),
            ticks_run=int(data.get("ticks_run") or 0),
            errors=int(data.get("errors") or 0),
            rate_limited=int(data.get("rate_limited") or 0),
            backoff_until=data.get("backoff_until"),
            last_summary_at=data.get("last_summary_at"),
            last_stop_warning=data.get("last_stop_warning"),
            rate_window=list(data.get("rate_window") or []),
            last_trace_id=data.get("last_trace_id"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "files": self.files,
            "changed_detected": self.changed_detected,
            "intents_emitted": self.intents_emitted,
            "ticks_run": self.ticks_run,
            "errors": self.errors,
            "rate_limited": self.rate_limited,
            "backoff_until": self.backoff_until,
            "last_summary_at": self.last_summary_at,
            "last_stop_warning": self.last_stop_warning,
            "rate_window": self.rate_window,
            "last_trace_id": self.last_trace_id,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def update_file_state(
        self,
        rel_path: str,
        *,
        mtime: float,
        content_hash: str | None = None,
        seen_at: float | None = None,
        emitted_at: float | None = None,
    ) -> None:
        entry = dict(self.files.get(rel_path) or {})
        entry["mtime"] = mtime
        if content_hash is not None:
            entry["hash"] = content_hash
        if seen_at is not None:
            entry["last_seen"] = seen_at
        if emitted_at is not None:
            entry["last_emitted"] = emitted_at
        self.files[rel_path] = entry

    def last_seen(self, rel_path: str) -> float | None:
        entry = self.files.get(rel_path) or {}
        seen = entry.get("last_seen")
        return float(seen) if seen is not None else None

    def last_mtime(self, rel_path: str) -> float | None:
        entry = self.files.get(rel_path) or {}
        value = entry.get("mtime")
        return float(value) if value is not None else None

    def last_hash(self, rel_path: str) -> str | None:
        entry = self.files.get(rel_path) or {}
        value = entry.get("hash")
        return str(value) if value is not None else None

    def record_rate_event(self, now: float) -> None:
        self.rate_window.append(now)
        self.rate_window = [ts for ts in self.rate_window if now - ts <= 60]

    def rate_window_count(self, now: float) -> int:
        self.rate_window = [ts for ts in self.rate_window if now - ts <= 60]
        return len(self.rate_window)

    def in_backoff(self, now: float) -> bool:
        return self.backoff_until is not None and now < float(self.backoff_until)


__all__ = ["WatcherState"]
