from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any

_MIN_VALID_TS = 1_000_000_000


def _sanitize_ts(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        ts = float(value)
    except Exception:
        return None
    if ts < _MIN_VALID_TS:
        return None
    return ts


def _sanitize_files(raw: dict[str, dict[str, Any]] | Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for rel, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        new_entry: dict[str, Any] = {}
        if "mtime" in entry:
            try:
                new_entry["mtime"] = float(entry["mtime"])
            except Exception:
                pass
        if "hash" in entry:
            try:
                new_entry["hash"] = str(entry["hash"])
            except Exception:
                pass
        settings_values = entry.get("settings_runtime_values")
        if isinstance(settings_values, dict):
            new_entry["settings_runtime_values"] = dict(settings_values)
        seen = _sanitize_ts(entry.get("last_seen"))
        emitted = _sanitize_ts(entry.get("last_emitted"))
        if seen is not None:
            new_entry["last_seen"] = seen
        if emitted is not None:
            new_entry["last_emitted"] = emitted
        if new_entry:
            cleaned[rel] = new_entry
    return cleaned


def _sanitize_rate_window(raw: list[float] | Any) -> list[float]:
    if not isinstance(raw, list):
        return []
    cleaned: list[float] = []
    for ts in raw:
        valid = _sanitize_ts(ts)
        if valid is not None:
            cleaned.append(valid)
    return cleaned


class RegistryObservationStore:
    """Durable, incrementally updated registry observations.

    The legacy watcher deliberately keeps using ``WatcherState.files``.  Only
    registry states attach this sidecar, which avoids serialising the entire
    vault into the per-tick checkpoint while preserving the old state API.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5.0) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS file_observations (
                    path TEXT PRIMARY KEY,
                    entry_json TEXT NOT NULL,
                    scan_generation INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    def get(self, rel_path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT entry_json FROM file_observations WHERE path = ?",
                (rel_path,),
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(str(row[0]))
        except Exception:
            return None
        return dict(value) if isinstance(value, dict) else None

    def paths(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT path FROM file_observations").fetchall()
        return {str(row[0]) for row in rows}

    def put(self, rel_path: str, entry: Mapping[str, Any], generation: int) -> None:
        encoded = json.dumps(dict(entry), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO file_observations(path, entry_json, scan_generation)
                VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    entry_json = excluded.entry_json,
                    scan_generation = excluded.scan_generation
                """,
                (rel_path, encoded, generation),
            )

    def apply(
        self,
        upserts: Mapping[str, tuple[Mapping[str, Any], int]],
        deletes: Iterable[str],
    ) -> None:
        """Commit one tick's observation changes as a single transaction."""

        with self._connect() as connection:
            for rel_path in sorted(set(deletes)):
                connection.execute(
                    "DELETE FROM file_observations WHERE path = ?", (rel_path,)
                )
            for rel_path, (entry, generation) in sorted(upserts.items()):
                encoded = json.dumps(dict(entry), sort_keys=True, separators=(",", ":"))
                connection.execute(
                    """
                    INSERT INTO file_observations(path, entry_json, scan_generation)
                    VALUES (?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        entry_json = excluded.entry_json,
                        scan_generation = excluded.scan_generation
                    """,
                    (rel_path, encoded, generation),
                )

    def delete(self, rel_path: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM file_observations WHERE path = ?", (rel_path,))

    def delete_not_seen_in(self, generation: int, *, retain: Iterable[str] = ()) -> None:
        retained = {path for path in retain if path}
        with self._connect() as connection:
            if retained:
                placeholders = ",".join("?" for _ in retained)
                connection.execute(
                    f"DELETE FROM file_observations WHERE scan_generation != ? "
                    f"AND path NOT IN ({placeholders})",
                    (generation, *sorted(retained)),
                )
            else:
                connection.execute(
                    "DELETE FROM file_observations WHERE scan_generation != ?",
                    (generation,),
                )

    def paths_not_seen_in(self, generation: int) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT path FROM file_observations WHERE scan_generation != ?",
                (generation,),
            ).fetchall()
        return {str(row[0]) for row in rows}


@dataclass
class WatcherState:
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    changed_detected: int = 0
    intents_emitted: int = 0
    ticks_run: int = 0
    errors: int = 0
    rate_limited: int = 0
    enqueue_failures_total: int = 0
    backoff_until: float | None = None
    last_summary_at: float | None = None
    last_stop_warning: float | None = None
    rate_window: list[float] = field(default_factory=list)
    last_trace_id: str | None = None
    bad_ticks: int = 0
    outbox_offset: int = 0
    dynamic_sleep_seconds: float | None = None
    last_emitted_event_at: float | None = None
    scope_status: str = "ok"
    last_scope_warning: float | None = None
    scan_in_progress: bool = False
    scan_generation: int = 0
    scan_identity: str | None = None
    scan_root_index: int = 0
    scan_stack: list[dict[str, str]] = field(default_factory=list)
    scan_scope_matched_files: int = 0
    scan_generation_had_error: bool = False
    observation_status: str = "healthy-idle"
    continuation_reason: str | None = None
    _observation_store: RegistryObservationStore | None = field(
        default=None, repr=False, compare=False
    )
    _pending_observations: dict[str, tuple[dict[str, Any], int]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _pending_deletes: set[str] = field(default_factory=set, repr=False, compare=False)

    @classmethod
    def load(cls, path: Path) -> WatcherState:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        state = cls(
            files=_sanitize_files(data.get("files")),
            changed_detected=int(data.get("changed_detected") or 0),
            intents_emitted=int(data.get("intents_emitted") or 0),
            ticks_run=int(data.get("ticks_run") or 0),
            errors=int(data.get("errors") or 0),
            rate_limited=int(data.get("rate_limited") or 0),
            enqueue_failures_total=int(data.get("enqueue_failures_total") or 0),
            backoff_until=_sanitize_ts(data.get("backoff_until")),
            last_summary_at=_sanitize_ts(data.get("last_summary_at")),
            last_stop_warning=_sanitize_ts(data.get("last_stop_warning")),
            rate_window=_sanitize_rate_window(data.get("rate_window")),
            last_trace_id=data.get("last_trace_id"),
            bad_ticks=int(data.get("bad_ticks") or 0),
            outbox_offset=int(data.get("outbox_offset") or 0),
            dynamic_sleep_seconds=_sanitize_ts(data.get("dynamic_sleep_seconds")),
            last_emitted_event_at=_sanitize_ts(data.get("last_emitted_event_at")),
            scope_status=str(data.get("scope_status") or "ok"),
            last_scope_warning=_sanitize_ts(data.get("last_scope_warning")),
            scan_in_progress=bool(data.get("scan_in_progress", False)),
            scan_generation=int(data.get("scan_generation") or 0),
            scan_identity=(str(data["scan_identity"]) if data.get("scan_identity") else None),
            scan_root_index=int(data.get("scan_root_index") or 0),
            scan_stack=[
                {"dir": str(frame.get("dir") or ""), "after": str(frame.get("after") or "")}
                for frame in (data.get("scan_stack") or [])
                if isinstance(frame, dict)
            ],
            scan_scope_matched_files=int(data.get("scan_scope_matched_files") or 0),
            scan_generation_had_error=bool(data.get("scan_generation_had_error", False)),
            observation_status=str(data.get("observation_status") or "healthy-idle"),
            continuation_reason=(
                str(data["continuation_reason"])
                if data.get("continuation_reason")
                else None
            ),
        )
        observation_name = data.get("observation_store")
        if isinstance(observation_name, str) and observation_name:
            observation_path = path.parent / Path(observation_name).name
            state.files.clear()
            state._observation_store = RegistryObservationStore(observation_path)
        return state

    @classmethod
    def load_registry(cls, checkpoint_path: Path, observation_path: Path) -> WatcherState:
        state = cls.load(checkpoint_path)
        store = state._observation_store or RegistryObservationStore(observation_path)
        legacy_files = dict(state.files)
        state.files.clear()
        state._observation_store = store
        if legacy_files:
            generation = max(state.scan_generation, 0)
            for rel_path, entry in legacy_files.items():
                if store.get(rel_path) is None:
                    store.put(rel_path, entry, generation)
        return state

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._observation_store is not None and (
            self._pending_observations or self._pending_deletes
        ):
            self._observation_store.apply(
                self._pending_observations,
                self._pending_deletes,
            )
            self._pending_observations.clear()
            self._pending_deletes.clear()
        payload: dict[str, Any] = {
            "files": self.files if self._observation_store is None else {},
            "changed_detected": self.changed_detected,
            "intents_emitted": self.intents_emitted,
            "ticks_run": self.ticks_run,
            "errors": self.errors,
            "rate_limited": self.rate_limited,
            "enqueue_failures_total": self.enqueue_failures_total,
            "backoff_until": self.backoff_until,
            "last_summary_at": self.last_summary_at,
            "last_stop_warning": self.last_stop_warning,
            "rate_window": self.rate_window,
            "last_trace_id": self.last_trace_id,
            "bad_ticks": self.bad_ticks,
            "outbox_offset": self.outbox_offset,
            "dynamic_sleep_seconds": self.dynamic_sleep_seconds,
            "last_emitted_event_at": self.last_emitted_event_at,
            "scope_status": self.scope_status,
            "last_scope_warning": self.last_scope_warning,
            "scan_in_progress": self.scan_in_progress,
            "scan_generation": self.scan_generation,
            "scan_identity": self.scan_identity,
            "scan_root_index": self.scan_root_index,
            "scan_stack": self.scan_stack,
            "scan_scope_matched_files": self.scan_scope_matched_files,
            "scan_generation_had_error": self.scan_generation_had_error,
            "observation_status": self.observation_status,
            "continuation_reason": self.continuation_reason,
            "observation_store": (
                self._observation_store.path.name
                if self._observation_store is not None
                else None
            ),
        }
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def checkpoint_observations(
        self,
    ) -> tuple[dict[str, tuple[dict[str, Any], int]], set[str]]:
        """Capture uncommitted observation changes for tick rollback."""

        return deepcopy(self._pending_observations), set(self._pending_deletes)

    def restore_observations(
        self,
        checkpoint: tuple[dict[str, tuple[dict[str, Any], int]], set[str]],
    ) -> None:
        """Restore pending observations after a failed delivery transaction."""

        pending_observations, pending_deletes = checkpoint
        self._pending_observations = deepcopy(pending_observations)
        self._pending_deletes = set(pending_deletes)

    def file_entry(self, rel_path: str) -> dict[str, Any] | None:
        if self._observation_store is not None:
            if rel_path in self._pending_deletes:
                return None
            pending = self._pending_observations.get(rel_path)
            if pending is not None:
                return dict(pending[0])
            return self._observation_store.get(rel_path)
        entry = self.files.get(rel_path)
        return dict(entry) if entry is not None else None

    def file_paths(self) -> set[str]:
        if self._observation_store is not None:
            return (
                self._observation_store.paths()
                | set(self._pending_observations)
            ) - self._pending_deletes
        return set(self.files)

    def restore_file_state(self, rel_path: str, entry: Mapping[str, Any] | None) -> None:
        if self._observation_store is not None:
            if entry is None:
                self._pending_observations.pop(rel_path, None)
                self._pending_deletes.add(rel_path)
            else:
                self._pending_deletes.discard(rel_path)
                self._pending_observations[rel_path] = (
                    dict(entry),
                    self.scan_generation,
                )
            return
        if entry is None:
            self.files.pop(rel_path, None)
        else:
            self.files[rel_path] = dict(entry)

    def remove_file(self, rel_path: str) -> None:
        self.restore_file_state(rel_path, None)

    def update_file_state(
        self,
        rel_path: str,
        *,
        mtime: float | None = None,
        content_hash: str | None = None,
        settings_runtime_values: Mapping[str, Any] | None = None,
        seen_at: float | None = None,
        emitted_at: float | None = None,
    ) -> None:
        entry = self.file_entry(rel_path) or {}
        if mtime is not None:
            entry["mtime"] = mtime
        if content_hash is not None:
            entry["hash"] = content_hash
        if settings_runtime_values is not None:
            entry["settings_runtime_values"] = dict(settings_runtime_values)
        if seen_at is not None:
            entry["last_seen"] = seen_at
        if emitted_at is not None:
            entry["last_emitted"] = emitted_at
        if self._observation_store is not None:
            self._pending_deletes.discard(rel_path)
            self._pending_observations[rel_path] = (entry, self.scan_generation)
        else:
            self.files[rel_path] = entry

    def invalidate_file_observation(
        self,
        rel_path: str,
        *,
        settings_runtime_values: Mapping[str, Any] | None = None,
    ) -> None:
        """Retain accepted settings state while forcing the file to be rehashed."""

        entry = self.file_entry(rel_path) or {}
        entry.pop("mtime", None)
        entry.pop("hash", None)
        if settings_runtime_values is not None:
            entry["settings_runtime_values"] = dict(settings_runtime_values)
        if self._observation_store is not None:
            self._pending_deletes.discard(rel_path)
            self._pending_observations[rel_path] = (entry, self.scan_generation)
        else:
            self.files[rel_path] = entry

    def prune_files(self, keep_paths: Iterable[str]) -> None:
        keep = {path for path in keep_paths if path}
        if self._observation_store is not None:
            for rel_path in self.file_paths() - keep:
                self.remove_file(rel_path)
            return
        if not keep:
            self.files.clear()
            return
        self.files = {path: entry for path, entry in self.files.items() if path in keep}

    def prune_unseen_generation(self, *, retain: Iterable[str] = ()) -> None:
        if self._observation_store is None:
            return
        retained = {path for path in retain if path}
        for rel_path in self.paths_unseen_in_generation(()) - retained:
            self.remove_file(rel_path)

    def paths_unseen_in_generation(self, scanned_paths: Iterable[str]) -> set[str]:
        if self._observation_store is not None:
            unseen = self._observation_store.paths_not_seen_in(self.scan_generation)
            for rel_path, (_entry, generation) in self._pending_observations.items():
                if generation == self.scan_generation:
                    unseen.discard(rel_path)
                else:
                    unseen.add(rel_path)
            return unseen - self._pending_deletes
        return self.file_paths() - {path for path in scanned_paths if path}

    def last_seen(self, rel_path: str) -> float | None:
        entry = self.file_entry(rel_path) or {}
        seen = entry.get("last_seen")
        return float(seen) if seen is not None else None

    def last_mtime(self, rel_path: str) -> float | None:
        entry = self.file_entry(rel_path) or {}
        value = entry.get("mtime")
        return float(value) if value is not None else None

    def last_hash(self, rel_path: str) -> str | None:
        entry = self.file_entry(rel_path) or {}
        value = entry.get("hash")
        return str(value) if value is not None else None

    def last_settings_runtime_values(self, rel_path: str) -> dict[str, Any] | None:
        entry = self.file_entry(rel_path) or {}
        value = entry.get("settings_runtime_values")
        return dict(value) if isinstance(value, dict) else None

    def record_rate_event(self, now: float) -> None:
        self.rate_window.append(now)
        self.rate_window = [ts for ts in self.rate_window if now - ts <= 60]

    def rate_window_count(self, now: float) -> int:
        self.rate_window = [ts for ts in self.rate_window if now - ts <= 60]
        return len(self.rate_window)

    def in_backoff(self, now: float) -> bool:
        return self.backoff_until is not None and now < float(self.backoff_until)


__all__ = ["RegistryObservationStore", "WatcherState"]
