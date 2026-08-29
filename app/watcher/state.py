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
        trace_id = entry.get("trace_id")
        if isinstance(trace_id, str) and trace_id:
            new_entry["trace_id"] = trace_id
        rebind_revision = entry.get("rebind_revision")
        if (
            isinstance(rebind_revision, int)
            and not isinstance(rebind_revision, bool)
            and rebind_revision > 0
        ):
            new_entry["rebind_revision"] = rebind_revision
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


def _checkpoint_counter(data: Mapping[str, Any], field_name: str) -> int:
    """Load a persisted non-negative integer without coercing bad shapes."""

    if field_name not in data:
        return 0
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid checkpoint counter: {field_name}")
    return value


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observation_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
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

    def active_identity(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM observation_metadata WHERE key = 'identity'"
            ).fetchone()
        if row is None or not row[0]:
            return None
        return str(row[0])

    def initialize_identity(self, identity: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO observation_metadata(key, value) VALUES ('identity', ?)",
                (identity,),
            )

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
        *,
        active_identity: str | None = None,
    ) -> None:
        """Commit one tick's observation changes as a single transaction."""

        with self._connect() as connection:
            if active_identity is not None:
                connection.execute(
                    """
                    INSERT INTO observation_metadata(key, value) VALUES ('identity', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (active_identity,),
                )
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

    def replace_identity(
        self,
        active_identity: str,
        upserts: Mapping[str, tuple[Mapping[str, Any], int]],
        deletes: Iterable[str],
    ) -> None:
        """Switch the sidecar namespace and apply new observations atomically."""

        with self._connect() as connection:
            connection.execute("DELETE FROM file_observations")
            connection.execute(
                """
                INSERT INTO observation_metadata(key, value) VALUES ('identity', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (active_identity,),
            )
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

    def clear(self) -> None:
        """Remove observations when their vault identity is no longer valid."""

        with self._connect() as connection:
            connection.execute("DELETE FROM file_observations")

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
    observations_invalidated: bool = False
    observation_identity: str | None = None
    checkpoint_load_error: bool = False
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
            return cls(
                errors=1,
                scan_generation_had_error=True,
                observation_status="degraded",
                checkpoint_load_error=True,
            )
        if not isinstance(data, dict):
            return cls(
                errors=1,
                scan_generation_had_error=True,
                observation_status="degraded",
                checkpoint_load_error=True,
            )
        try:
            counters = {
                field_name: _checkpoint_counter(data, field_name)
                for field_name in (
                    "changed_detected",
                    "intents_emitted",
                    "ticks_run",
                    "errors",
                    "rate_limited",
                    "enqueue_failures_total",
                    "bad_ticks",
                    "outbox_offset",
                    "scan_generation",
                    "scan_root_index",
                    "scan_scope_matched_files",
                )
            }
        except (TypeError, ValueError, OverflowError):
            return cls(
                errors=1,
                scan_generation_had_error=True,
                observation_status="degraded",
                checkpoint_load_error=True,
            )
        state = cls(
            files=_sanitize_files(data.get("files")),
            changed_detected=counters["changed_detected"],
            intents_emitted=counters["intents_emitted"],
            ticks_run=counters["ticks_run"],
            errors=counters["errors"],
            rate_limited=counters["rate_limited"],
            enqueue_failures_total=counters["enqueue_failures_total"],
            backoff_until=_sanitize_ts(data.get("backoff_until")),
            last_summary_at=_sanitize_ts(data.get("last_summary_at")),
            last_stop_warning=_sanitize_ts(data.get("last_stop_warning")),
            rate_window=_sanitize_rate_window(data.get("rate_window")),
            last_trace_id=data.get("last_trace_id"),
            bad_ticks=counters["bad_ticks"],
            outbox_offset=counters["outbox_offset"],
            dynamic_sleep_seconds=_sanitize_ts(data.get("dynamic_sleep_seconds")),
            last_emitted_event_at=_sanitize_ts(data.get("last_emitted_event_at")),
            scope_status=str(data.get("scope_status") or "ok"),
            last_scope_warning=_sanitize_ts(data.get("last_scope_warning")),
            scan_in_progress=bool(data.get("scan_in_progress", False)),
            scan_generation=counters["scan_generation"],
            scan_identity=(str(data["scan_identity"]) if data.get("scan_identity") else None),
            scan_root_index=counters["scan_root_index"],
            scan_stack=[
                {"dir": str(frame.get("dir") or ""), "after": str(frame.get("after") or "")}
                for frame in (data.get("scan_stack") or [])
                if isinstance(frame, dict)
            ],
            scan_scope_matched_files=counters["scan_scope_matched_files"],
            scan_generation_had_error=bool(data.get("scan_generation_had_error", False)),
            observation_status=str(data.get("observation_status") or "healthy-idle"),
            continuation_reason=(
                str(data["continuation_reason"])
                if data.get("continuation_reason")
                else None
            ),
            observations_invalidated=bool(data.get("observations_invalidated", False)),
            observation_identity=(
                str(data["observation_identity"])
                if data.get("observation_identity")
                else (str(data["scan_identity"]) if data.get("scan_identity") else None)
            ),
            checkpoint_load_error=bool(data.get("checkpoint_load_error", False)),
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
        if state.observation_identity is None and store.active_identity() is not None:
            # A missing or malformed checkpoint cannot authorize the sidecar's
            # relative-path observations. Hide them until the next scan binds
            # a verified vault identity and replaces the namespace.
            state.observations_invalidated = True
        if state.observation_identity is not None and store.active_identity() is None:
            store.initialize_identity(state.observation_identity)
        if legacy_files:
            generation = max(state.scan_generation, 0)
            for rel_path, entry in legacy_files.items():
                if store.get(rel_path) is None:
                    store.put(rel_path, entry, generation)
        return state

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._observation_store is not None:
            if self.observations_invalidated:
                # Switch the sidecar namespace before publishing the new
                # checkpoint. An older checkpoint sees the identity mismatch
                # and hides the new rows if the process dies in between.
                identity = self.observation_identity or self.scan_identity
                if identity is None:
                    raise RuntimeError("cannot invalidate observations without an identity")
                self._observation_store.replace_identity(
                    identity,
                    self._pending_observations,
                    self._pending_deletes,
                )
                self.observations_invalidated = False
                self._pending_observations.clear()
                self._pending_deletes.clear()
            identity = self.observation_identity or self.scan_identity
            identity_mismatch = (
                identity is not None
                and self._observation_store.active_identity() != identity
            )
            if identity_mismatch:
                # A checkpoint can survive a sidecar commit failure (or vice
                # versa). Never relabel incompatible rows into the current
                # namespace; replace the namespace before publishing state.
                self._observation_store.replace_identity(
                    identity,
                    self._pending_observations,
                    self._pending_deletes,
                )
                self._pending_observations.clear()
                self._pending_deletes.clear()
            elif self._pending_observations or self._pending_deletes:
                self._observation_store.apply(
                    self._pending_observations,
                    self._pending_deletes,
                    active_identity=identity,
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
            "observations_invalidated": self.observations_invalidated,
            "observation_identity": self.observation_identity,
            "checkpoint_load_error": self.checkpoint_load_error,
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
    ) -> tuple[dict[str, tuple[dict[str, Any], int]], set[str], bool]:
        """Capture uncommitted observation changes for tick rollback."""

        return (
            deepcopy(self._pending_observations),
            set(self._pending_deletes),
            self.observations_invalidated,
        )

    def restore_observations(
        self,
        checkpoint: tuple[dict[str, tuple[dict[str, Any], int]], set[str], bool],
    ) -> None:
        """Restore pending observations after a failed delivery transaction."""

        pending_observations, pending_deletes, observations_invalidated = checkpoint
        self._pending_observations = deepcopy(pending_observations)
        self._pending_deletes = set(pending_deletes)
        self.observations_invalidated = observations_invalidated

    def reset_observations_for_new_identity(self) -> None:
        """Invalidate observations belonging to a replaced vault/root identity."""

        self._pending_observations.clear()
        self._pending_deletes.clear()
        if self._observation_store is not None:
            self.observations_invalidated = True
        else:
            self.files.clear()

    def file_entry(self, rel_path: str) -> dict[str, Any] | None:
        if self._observation_store is not None:
            if rel_path in self._pending_deletes:
                return None
            pending = self._pending_observations.get(rel_path)
            if pending is not None:
                return dict(pending[0])
            if self.observations_invalidated or (
                self.observation_identity is not None
                and self._observation_store.active_identity() != self.observation_identity
            ):
                return None
            return self._observation_store.get(rel_path)
        entry = self.files.get(rel_path)
        return dict(entry) if entry is not None else None

    def file_paths(self) -> set[str]:
        if self._observation_store is not None:
            if self.observations_invalidated or (
                self.observation_identity is not None
                and self._observation_store.active_identity() != self.observation_identity
            ):
                return set(self._pending_observations) - self._pending_deletes
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
        trace_id: str | None = None,
        rebind_revision: int | None = None,
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
        if trace_id is not None:
            entry["trace_id"] = trace_id
        if rebind_revision is not None:
            if isinstance(rebind_revision, bool) or rebind_revision <= 0:
                raise ValueError("rebind revision must be a positive integer")
            entry["rebind_revision"] = rebind_revision
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
            if self.observations_invalidated or (
                self.observation_identity is not None
                and self._observation_store.active_identity() != self.observation_identity
            ):
                return set()
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
