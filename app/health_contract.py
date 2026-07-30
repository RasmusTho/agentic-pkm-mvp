from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import timezone, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from app.config.environment import active_environment
from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.db.dsn import ping_postgres
from app.events.outbox import default_outbox_path, event_name, latest_trace_story, normalize_timestamp
from app.index.doctor import diagnose_index
from app.settings.health_settings import HealthThresholds, load_health_settings
from app.stores import get_object_store, resolve_store_backend

logger = logging.getLogger(__name__)

# Health checks must never load the full outbox into memory; it can grow to hundreds of MB.
# Bound tail reads to this many bytes — enough to capture recent activity for all checks.
_HEALTH_TAIL_BYTES = 8 * 1024 * 1024  # 8 MB


@dataclass(frozen=True)
class StoreBackendResolution:
    """Outcome of consulting the canonical store-resolution seam (#2843).

    Every health-surface site that used to re-derive "is this pg or memory?"
    from `os.getenv("STORE_BACKEND")` directly (three sites, ~lines 26/72/540
    at audit time) diverged from `app.stores`'s unset -> DSN-resolution
    semantics: an unset `STORE_BACKEND` with a configured-but-unreachable DSN
    was silently read as "memory" and pg-only checks were skipped instead of
    surfacing the fail-loud resolution error (KERNEL-03 / #2765). This type is
    the single place that consults `resolve_store_backend()` so the health
    surface can never re-diverge from the store seam's own semantics.
    """

    backend: str | None
    error: str | None


def _resolve_store_backend_for_health() -> StoreBackendResolution:
    """Consult the production store-resolution seam; never raise.

    Wraps `app.stores.resolve_store_backend()` — the exact seam
    `get_object_store()` / `get_vector_index()` use — so a resolution failure
    (unknown backend value, configured-but-unreachable Postgres, no backend
    configured at all) is captured as data instead of allowed to propagate out
    of the health contract (loud ≠ fatal at boot, #2005).
    """
    try:
        backend = resolve_store_backend()
    except Exception as exc:
        # Intentional swallow: the failure is carried as data into the health
        # snapshot (store_resolution_error) — logged too so it is greppable.
        logger.warning("Store backend resolution failed", exc_info=True)
        return StoreBackendResolution(backend=None, error=f"{type(exc).__name__}: {exc}")
    return StoreBackendResolution(backend=backend, error=None)


def _count_outbox_lines_db(resolution: StoreBackendResolution | None = None) -> int | None:
    """Count total outbox rows via DB when the resolved backend is pg. None on any error.

    ``resolution`` lets one `evaluate()` call resolve the backend once and
    reuse it across sibling helpers rather than re-probing Postgres per call;
    defaults to a fresh resolution for direct/standalone callers.
    """
    resolution = resolution or _resolve_store_backend_for_health()
    if resolution.backend != "pg":
        return None
    try:
        from app.services.outbox import count_outbox_events

        return count_outbox_events()
    except Exception:
        # Intentional swallow: fall back to the file-based count, but log the
        # DB failure instead of silently degrading (#3894).
        logger.warning("DB outbox count failed; falling back to file count", exc_info=True)
        return None


def _count_outbox_lines_from_file(path: Path) -> int:
    """Streaming file line count of the outbox; never touches the DB. 0 on error."""
    if not path.exists():
        return 0
    try:
        count = 0
        saw_bytes = False
        last_byte = b""
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                saw_bytes = True
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if saw_bytes and last_byte != b"\n":
            count += 1
        return count
    except Exception:
        # Intentional swallow: health must not crash on an unreadable outbox
        # file, but the read failure is logged rather than folded into 0.
        logger.warning("Outbox file line count failed for %s", path, exc_info=True)
        return 0


def _count_outbox_lines(path: Path, resolution: StoreBackendResolution | None = None) -> int:
    """Count outbox records: DB when available, else streaming file line count."""
    db_count = _count_outbox_lines_db(resolution)
    if db_count is not None:
        return db_count
    return _count_outbox_lines_from_file(path)


# Dead-letter audit topic (KERNEL-12 / #2774). Mirrors OUTBOX_EVENT_DEAD_LETTERED
# in app/workers/outbox_worker.py without importing the worker module.
_DEAD_LETTER_EVENT = "outbox.event.dead_lettered"


def _dead_letter_stats_db(resolution: StoreBackendResolution | None = None) -> dict[str, Any] | None:
    """Dead-letter/backlog stats via the DB outbox when the resolved backend is pg.

    None on any error. ``resolution`` lets callers reuse a single resolved
    backend across one `evaluate()` pass (see `_count_outbox_lines_db`).
    """
    resolution = resolution or _resolve_store_backend_for_health()
    if resolution.backend != "pg":
        return None
    try:
        from app.services.outbox import dead_letter_stats

        return dead_letter_stats()
    except Exception:
        # Intentional swallow: fall back to the JSONL-tail stats, but log the
        # DB failure instead of silently degrading (#3894).
        logger.warning(
            "DB dead-letter stats failed; falling back to JSONL tail", exc_info=True
        )
        return None


def _dead_letter_stats_from_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """File-based fallback: count dead-letter audit records in the JSONL tail.

    The JSONL log is an append-only audit sink with no delivery tracking, so
    ``oldest_undelivered_age_seconds`` is 0.0 on this path — the DB outbox is
    the only delivery queue (the memory backend has none).
    """
    count = 0
    for rec in records:
        if event_name(rec) == _DEAD_LETTER_EVENT:
            count += 1
    return {"dead_lettered_count": count, "oldest_undelivered_age_seconds": 0.0}


def _dead_letter_status(stats: dict[str, Any], thresholds: HealthThresholds) -> str:
    """Return ``"warn"`` when a dead-letter/backlog threshold is breached, else ``"pass"``.

    Alerting signal ONLY (KERNEL-12 design decision): this status never feeds
    ``WRITE_BLOCKED_STATES`` — dead-letters are downstream-processing failures
    and must not block the human's ability to capture notes.
    """
    warn_count = max(int(thresholds.dead_lettered_warn), 1)
    if int(stats.get("dead_lettered_count") or 0) >= warn_count:
        return "warn"
    age = float(stats.get("oldest_undelivered_age_seconds") or 0.0)
    if age > float(thresholds.oldest_undelivered_age_warn_s):
        return "warn"
    return "pass"


def dead_letter_snapshot(*, thresholds: HealthThresholds | None = None) -> dict[str, Any]:
    """Read-only dead-letter signal for non-contract health surfaces (CLI check).

    Reflects the exact fields and thresholds `HealthContract.evaluate()` puts in
    the contract snapshot, computed from the same outbox source (DB when
    ``STORE_BACKEND=pg``, else the JSONL audit tail). Detection only — never
    mutates the outbox.
    """
    if thresholds is None:
        try:
            vault_root = resolve_optional_vault_root()
        except VaultRootMisconfiguredError:
            vault_root = None
        thresholds = load_health_settings(vault_root=vault_root).settings.thresholds
    stats = _dead_letter_stats_db()
    source = "db_outbox"
    if stats is None:
        stats = _dead_letter_stats_from_records(_read_tail_records())
        source = "jsonl_tail"
    return {
        "dead_lettered_count": stats["dead_lettered_count"],
        "oldest_undelivered_age_seconds": stats["oldest_undelivered_age_seconds"],
        "dead_letter_status": _dead_letter_status(stats, thresholds),
        "source": source,
        "thresholds": {
            "dead_lettered_warn": thresholds.dead_lettered_warn,
            "oldest_undelivered_age_warn_s": thresholds.oldest_undelivered_age_warn_s,
        },
    }


def _read_tail_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Read at most _HEALTH_TAIL_BYTES from the end of the outbox; return parsed records."""
    target = (path or default_outbox_path()).expanduser()
    if not target.exists():
        return []
    try:
        with target.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size > _HEALTH_TAIL_BYTES:
                fh.seek(size - _HEALTH_TAIL_BYTES)
                partial = True
            else:
                fh.seek(0)
                partial = False
            data = fh.read()
    except Exception:
        # Intentional swallow: an unreadable outbox tail degrades to "no recent
        # records" for health purposes, but the I/O failure is logged (#3894).
        logger.warning("Outbox tail read failed for %s", target, exc_info=True)
        return []
    try:
        lines = data.decode("utf-8", errors="replace").splitlines()
    except Exception:
        # Defensive only: decode(errors="replace") cannot realistically raise;
        # logged loudly if it ever does.
        logger.warning("Outbox tail decode failed for %s", target, exc_info=True)
        return []
    if partial and lines:
        lines = lines[1:]  # drop potentially truncated first line
    records: list[dict[str, Any]] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict):
                records.append(obj)
        except Exception:
            # Intentionally silent: a truncated/garbled JSONL line in an
            # append-only log tail is expected (partial writes at the cut
            # boundary); logging per line would spam every health poll.
            continue
    return records

WRITE_BLOCKED_STATES = {"safe_mode", "unhealthy"}
INCIDENT_STATES = {"degraded", "unhealthy", "safe_mode"}


def _transition_entry(state: str, reason: str, since: datetime) -> dict[str, str]:
    return {
        "state": state,
        "reason": reason,
        "since_ts": since.isoformat(),
    }


@dataclass
class HealthStateMachine:
    state: str = "boot"
    reason: str = "initializing"
    since: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # noqa: UP017
    bad_counter: int = 0
    good_counter: int = 0
    transition_history: list[dict[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self.state = "boot"
        self.reason = "initializing"
        self.since = datetime.now(timezone.utc)  # noqa: UP017
        self.bad_counter = 0
        self.good_counter = 0
        self.transition_history = []

    def update(
        self,
        age: float,
        thresholds: HealthThresholds,
        *,
        now: datetime | None = None,
    ) -> tuple[str, str, str]:
        now = now or datetime.now(timezone.utc)  # noqa: UP017
        prev_state = self.state
        next_state = self.state
        reason = self.reason
        degrade_limit = thresholds.outbox_degrade_oldest_age_s
        recover_limit = thresholds.outbox_recover_oldest_age_s
        degrade_samples = thresholds.degrade_samples
        recover_samples = thresholds.recover_samples

        if age > degrade_limit:
            self.bad_counter += 1
            self.good_counter = 0
            if self.bad_counter >= degrade_samples:
                next_state = "degraded"
                reason = f"outbox idle, last event {age:.1f}s ago"
            else:
                next_state = "catch_up"
                reason = f"catching up (last event {age:.1f}s ago)"
        elif age < recover_limit:
            self.good_counter += 1
            self.bad_counter = 0
            if self.state in {"degraded", "recovery"}:
                if self.good_counter >= recover_samples:
                    next_state = "running"
                    reason = "outbox activity recovered"
                else:
                    next_state = "recovery"
                    reason = "recovering (activity improving)"
            else:
                next_state = "running"
                reason = "recent activity"
        else:
            self.bad_counter = 0
            self.good_counter = 0
            next_state = "running"
            reason = "recent activity"

        if next_state != prev_state:
            self.state = next_state
            self.reason = reason
            self.since = now
            self._record_transition()
        return self.state, self.reason, self.since.isoformat()

    def _record_transition(self) -> None:
        entry = _transition_entry(self.state, self.reason, self.since)
        self.transition_history.insert(0, entry)
        if len(self.transition_history) > 20:
            self.transition_history = self.transition_history[:20]


class HealthContract:
    def __init__(
        self,
        *,
        state_machine: HealthStateMachine | None = None,
        now_fn: Callable[[], datetime] | None = None,
        vault_root_fn: Callable[[], Path | None] | None = None,
        db_ping_fn: Callable[..., tuple[bool, str]] | None = None,
    ):
        self.state_machine = state_machine or HealthStateMachine()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))  # noqa: UP017
        # Optional resolver: returns None when no vault is selected (#2384) and
        # still raises VaultRootMisconfiguredError for a set-but-missing root.
        self.vault_root_fn = vault_root_fn or resolve_optional_vault_root
        # Live DB reachability probe (#2598). Injectable so tests can exercise the
        # readiness short-circuit without a real Postgres. Bounded by the caller's
        # connect_timeout so the health probe never hangs.
        self.db_ping_fn = db_ping_fn or ping_postgres
        self._evaluation_lock = Lock()

    def evaluate(self) -> dict[str, Any]:
        with self._evaluation_lock:
            return self._evaluate()

    def _evaluate(self) -> dict[str, Any]:
        now = self.now_fn()
        try:
            vault_root = self.vault_root_fn()
        except VaultRootMisconfiguredError:
            # Set-but-missing VAULT_ROOT stays loud as a not_selected vault
            # identity; health still evaluates the rest of the runtime.
            vault_root = None
        settings_result = load_health_settings(vault_root=vault_root)
        outbox_path = default_outbox_path()

        # Store-resolution layer (#2843): resolve the backend ONCE through the
        # production seam (`app.stores.resolve_store_backend()`) and reuse the
        # outcome for every sibling helper below, instead of each site
        # independently re-deriving "is this pg or memory?" from
        # `os.getenv("STORE_BACKEND")` (three sites diverged from the store
        # seam's unset -> DSN-resolution semantics — see StoreBackendResolution).
        resolution = _resolve_store_backend_for_health()

        # Dependency layer (#2598 + #2843): probe the live DB FIRST, before any
        # DB-backed diagnostic (object store count, index doctor) runs. When
        # Postgres is down, or store resolution itself failed (unknown backend
        # value, no backend configured at all), we must short-circuit and
        # RETURN a complete `unhealthy` snapshot here — those diagnostics would
        # otherwise open a second psycopg connection that raises or hangs,
        # turning /readyz's clean 503 into a 500 or a slow timeout, or would
        # swallow the resolution failure into a false "empty" bootstrap state.
        # `unhealthy` (not `degraded`) is required: `degraded` is in
        # READY_STATES so /readyz would stay 200 on DB-down — the false-green
        # this slice exists to kill.
        db_down_reason = self._db_dependency_down_reason(resolution)
        if db_down_reason is not None:
            return self._db_down_snapshot(
                now=now,
                settings_result=settings_result,
                outbox_path=outbox_path,
                reason=db_down_reason,
                resolution=resolution,
            )

        outbox_count = _count_outbox_lines(outbox_path, resolution)
        records = _read_tail_records(outbox_path)
        # #2843: never swallow a store-access error into a bare 0. Resolution
        # already succeeded (the db_down short-circuit above returned early
        # otherwise), so a failure here is a narrower post-resolution fault
        # (e.g. schema missing) — still surfaced loudly, never folded into
        # "genuinely empty".
        object_count, store_count_error = self._count_objects()
        latest_ts = self._latest_timestamp(records)
        age = self._compute_age(latest_ts, now)
        prev_state = self.state_machine.state
        state, reason, since_ts = self.state_machine.update(
            age,
            settings_result.settings.thresholds,
            now=now,
        )
        catch_up_progress = self._catch_up_progress(
            outbox_count,
            age,
            settings_result.settings.thresholds,
        )
        # Belt-and-braces: a DB-backed index diagnostic must never escape and turn
        # a readiness 503 into a 500. The ping above already guards the known
        # DB-down case; this catches a flaky/partial DB that fails mid-diagnostic.
        try:
            index_result = diagnose_index()
        except Exception as exc:
            # Intentional swallow: the failure is surfaced as an index issue in
            # the snapshot below — logged too, with the full traceback (#3894).
            logger.warning("Index diagnostic failed during health evaluation", exc_info=True)
            index_result = {
                "backend": None,
                "expected_identity": None,
                "stored_identity": None,
                "issues": [f"index diagnostic failed ({type(exc).__name__})"],
                "warnings": [],
            }
        index_status = self._summary_status(
            index_result.get("issues"),
            index_result.get("warnings"),
        )
        events_status = self._events_status(records)
        errors = self._count_errors(records, now)
        # Dead-letter signal (KERNEL-12 / #2774): read-only detection from the
        # outbox source (DB when STORE_BACKEND=pg, else the JSONL audit tail).
        dead_letter = _dead_letter_stats_db(resolution) or _dead_letter_stats_from_records(records)
        dead_letter_status = _dead_letter_status(
            dead_letter,
            settings_result.settings.thresholds,
        )
        writes_allowed = state not in WRITE_BLOCKED_STATES
        write_guard_reason = None if writes_allowed else reason
        suggested_actions = self._suggested_actions(
            age,
            index_status,
            writes_allowed,
            dead_letter_status=dead_letter_status,
            store_count_error=store_count_error,
        )

        bootstrap_state, bootstrap_reason = self._bootstrap_state(
            object_count, outbox_count, store_error=store_count_error
        )

        if settings_result.settings.incident_capture.enabled:
            transitioned = state != prev_state
            if transitioned and state in INCIDENT_STATES:
                    self._append_incident_log(
                        path=settings_result.settings.incident_log_path,
                        entry=self._incident_entry(
                            now=now,
                            state=state,
                            reason=reason,
                            since_ts=since_ts,
                            settings_result=settings_result,
                            outbox_count=outbox_count,
                            outbox_recent_age_s=age,
                            index_status=index_status,
                            events_status=events_status,
                            writes_allowed=writes_allowed,
                            write_guard_reason=write_guard_reason,
                            catch_up_progress=catch_up_progress,
                            suggested_actions=suggested_actions,
                        ),
                    )

        result = {
            "environment": active_environment(),
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "vault": {
                "status": settings_result.vault_status,
                "configured_vault_root": settings_result.configured_vault_root,
            },
            "outbox_count": outbox_count,
            "outbox_recent_age_s": age,
            "store_object_count": object_count,
            # #2843: distinct loud signal for store-resolution health, computed
            # once above and reused by every sibling helper in this evaluate().
            "store_resolution_status": "ok" if resolution.error is None else "failed",
            "store_resolution_error": resolution.error,
            "bootstrap_state": bootstrap_state,
            "bootstrap_reason": bootstrap_reason,
            "embedding_identity": {
                "backend": index_result.get("backend"),
                "expected_identity": index_result.get("expected_identity"),
                "stored_identity": index_result.get("stored_identity"),
            },
            "index_doctor_status": index_status,
            "events_doctor_status": events_status,
            "errors_last_10m": errors,
            "dead_lettered_count": dead_letter["dead_lettered_count"],
            "oldest_undelivered_age_seconds": dead_letter["oldest_undelivered_age_seconds"],
            "dead_letter_status": dead_letter_status,
            "settings_status": settings_result.status,
            "settings_source": settings_result.source.to_payload(),
            "settings_errors": settings_result.errors,
            "thresholds": settings_result.settings.thresholds.to_payload(),
            "writes_allowed": writes_allowed,
            "write_guard_reason": write_guard_reason,
            "catch_up_progress": catch_up_progress,
            "suggested_actions": suggested_actions,
        }
        if settings_result.settings.incident_capture.transition_history:
            result["recent_transition_history"] = list(self.state_machine.transition_history)
        return result

    def _db_down_snapshot(
        self,
        *,
        now: datetime,
        settings_result: Any,
        outbox_path: Path,
        reason: str,
        resolution: StoreBackendResolution | None = None,
    ) -> dict[str, Any]:
        """Build a complete `unhealthy` snapshot for a known DB-down stack.

        Uses only DB-free inputs (env, settings, the outbox file tail) so no
        second psycopg connection is attempted on the known-down path. The shape
        mirrors the normal snapshot key-for-key so `/readyz`, `/status`, and CLI
        consumers never KeyError. The outbox state machine is intentionally NOT
        mutated — this is a contract-level dependency override, so outbox recovery
        hysteresis is unaffected once Postgres returns.

        ``resolution`` (#2843) is the store-resolution outcome that produced
        ``reason`` — carried through so the snapshot's ``store_resolution_*``
        fields and ``bootstrap_state`` reflect *why* we are down (a genuine
        resolution failure, not just a live ping failure) instead of silently
        reporting the ambiguous "empty" bootstrap state.
        """
        state = "unhealthy"
        since_ts = now.isoformat()
        # File-only outbox count: never route through the DB count helper while
        # the DB is known down. _read_tail_records is file-based and fail-soft.
        outbox_count = _count_outbox_lines_from_file(outbox_path)
        records = _read_tail_records(outbox_path)
        age = self._compute_age(self._latest_timestamp(records), now)
        # Do NOT count objects here: the pg object store's connect() has no bounded
        # timeout, so on a known-down DB it could block for seconds. Report 0.
        object_count = 0
        events_status = self._events_status(records)
        # DB is known down: compute the dead-letter signal from the JSONL audit
        # tail only (never a second DB connection on this path).
        dead_letter = _dead_letter_stats_from_records(records)
        dead_letter_status = _dead_letter_status(
            dead_letter,
            settings_result.settings.thresholds,
        )
        catch_up_progress = self._catch_up_progress(
            outbox_count,
            age,
            settings_result.settings.thresholds,
        )
        index_status = "fail"
        writes_allowed = False  # unhealthy is in WRITE_BLOCKED_STATES
        write_guard_reason = reason
        suggested_actions = ["python -m app.cli health status --json"]
        store_error = resolution.error if resolution is not None else reason
        bootstrap_state, bootstrap_reason = self._bootstrap_state(
            object_count, outbox_count, store_error=store_error
        )

        if settings_result.settings.incident_capture.enabled and state != self.state_machine.state:
            self._append_incident_log(
                path=settings_result.settings.incident_log_path,
                entry=self._incident_entry(
                    now=now,
                    state=state,
                    reason=reason,
                    since_ts=since_ts,
                    settings_result=settings_result,
                    outbox_count=outbox_count,
                    outbox_recent_age_s=age,
                    index_status=index_status,
                    events_status=events_status,
                    writes_allowed=writes_allowed,
                    write_guard_reason=write_guard_reason,
                    catch_up_progress=catch_up_progress,
                    suggested_actions=suggested_actions,
                ),
            )

        result: dict[str, Any] = {
            "environment": active_environment(),
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "vault": {
                "status": settings_result.vault_status,
                "configured_vault_root": settings_result.configured_vault_root,
            },
            "outbox_count": outbox_count,
            "outbox_recent_age_s": age,
            "store_object_count": object_count,
            "store_resolution_status": "failed" if store_error is not None else "ok",
            "store_resolution_error": store_error,
            "bootstrap_state": bootstrap_state,
            "bootstrap_reason": bootstrap_reason,
            "embedding_identity": {
                "backend": None,
                "expected_identity": None,
                "stored_identity": None,
            },
            "index_doctor_status": index_status,
            "events_doctor_status": events_status,
            "errors_last_10m": self._count_errors(records, now),
            "dead_lettered_count": dead_letter["dead_lettered_count"],
            "oldest_undelivered_age_seconds": dead_letter["oldest_undelivered_age_seconds"],
            "dead_letter_status": dead_letter_status,
            "settings_status": settings_result.status,
            "settings_source": settings_result.source.to_payload(),
            "settings_errors": settings_result.errors,
            "thresholds": settings_result.settings.thresholds.to_payload(),
            "writes_allowed": writes_allowed,
            "write_guard_reason": write_guard_reason,
            "catch_up_progress": catch_up_progress,
            "suggested_actions": suggested_actions,
        }
        if settings_result.settings.incident_capture.transition_history:
            result["recent_transition_history"] = list(self.state_machine.transition_history)
        return result

    def _db_dependency_down_reason(
        self, resolution: StoreBackendResolution | None = None
    ) -> str | None:
        """Return a human-legible reason when the DB dependency is down, else None.

        ``resolution`` is the outcome of consulting `resolve_store_backend()`
        (the production store seam) — a resolution failure (unknown backend
        value, configured-but-unreachable Postgres, or no backend configured
        at all) is itself a down-dependency reason (#2843): the store seam
        already refuses to fall back to a volatile in-memory store on these
        conditions (KERNEL-03 / #2765), so the health surface must not
        independently decide "unset means memory, skip the check" and go
        quiet where the store layer itself would raise.

        When resolution succeeds and the backend is ``"pg"``, a live ping
        still runs (bounded ``connect_timeout=1.0`` s) as defense in depth
        against Postgres dropping in the moment between resolution and this
        call. The memory backend has no Postgres dependency to ping.
        """
        resolution = resolution or _resolve_store_backend_for_health()
        if resolution.error is not None:
            return f"store resolution failed: {resolution.error}"
        if resolution.backend != "pg":
            return None
        try:
            ok, detail = self.db_ping_fn(timeout=1.0)
        except Exception as exc:  # fail closed: a probe error is not a healthy DB
            return f"postgres unreachable (ping error: {type(exc).__name__})"
        if ok:
            return None
        return f"postgres unreachable: {detail}"

    def _latest_timestamp(self, records: Iterable[dict[str, Any]]) -> datetime | None:
        latest: datetime | None = None
        for rec in records:
            value = normalize_timestamp(rec)
            ts = self._parse_timestamp(value)
            if ts is None:
                continue
            if latest is None or ts > latest:
                latest = ts
        return latest

    def _compute_age(self, ts: datetime | None, now: datetime) -> float:
        if ts is None:
            return 0.0
        delta = now - ts
        return max(delta.total_seconds(), 0.0)

    def _parse_timestamp(self, value: str) -> datetime | None:
        if not value:
            return None
        text = value.strip()
        if text.endswith("Z") and not text.endswith("+00:00"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except Exception:
            # Intentionally silent: called per record on every health poll and
            # malformed timestamps in old outbox records are expected; a None
            # simply excludes the record from age computation.
            return None

    def _summary_status(self, issues: Any, warnings: Any) -> str:
        if issues:
            return "fail"
        if warnings:
            return "warn"
        return "pass"

    def _events_status(self, records: Iterable[dict[str, Any]]) -> str:
        rows = list(records)
        if not rows:
            return "warn"
        story = latest_trace_story(rows)
        if story.get("count", 0) > 0:
            return "pass"
        return "warn"

    def _count_errors(self, records: Iterable[dict[str, Any]], now: datetime) -> int | None:
        cutoff = now - timedelta(minutes=10)
        errors = 0
        seen = False
        for rec in records:
            seen = True
            ts = self._parse_timestamp(normalize_timestamp(rec))
            if ts is None:
                continue
            if ts < cutoff:
                continue
            name = event_name(rec).lower()
            if "error" in name:
                errors += 1
        return errors if seen else None

    def _catch_up_progress(
        self,
        outbox_count: int,
        outbox_recent_age_s: float,
        thresholds: HealthThresholds,
    ) -> dict[str, Any] | None:
        if outbox_count <= 0:
            mode = "idle"
        elif outbox_recent_age_s > thresholds.outbox_degrade_oldest_age_s:
            mode = "replay"
        elif outbox_recent_age_s > thresholds.outbox_recover_oldest_age_s:
            mode = "stalled"
        else:
            mode = "idle"
        return {
            "outbox_count": outbox_count,
            "outbox_recent_age_s": outbox_recent_age_s,
            "processing_mode": mode,
        }

    def _suggested_actions(
        self,
        age: float,
        index_status: str,
        writes_allowed: bool,
        *,
        dead_letter_status: str = "pass",
        store_count_error: str | None = None,
    ) -> list[str]:
        actions: list[str] = []
        if age > 0:
            actions.append("python -m app.cli events-doctor --path $INDEX_OUTBOX_PATH")
        if index_status in {"warn", "fail"}:
            actions.append("python -m app.cli index doctor --json")
        if dead_letter_status == "warn":
            # Detection only: inspection is suggested; re-drive/repair stays an
            # explicit operator/agent action (KERNEL-12 read-only invariant).
            actions.append(
                "inspect dead-lettered outbox events: "
                "grep outbox.event.dead_lettered $INDEX_OUTBOX_PATH"
            )
        if store_count_error is not None:
            # #2843: a post-resolution store-access failure (e.g. schema
            # missing) is loud, not folded into "empty" — point at the doctor.
            actions.append("python -m app.cli health --json")
        if not writes_allowed:
            actions.append("python -m app.cli health status --json")
        return actions

    def _incident_entry(
        self,
        *,
        now: datetime,
        state: str,
        reason: str,
        since_ts: str,
        settings_result: Any,
        outbox_count: int,
        outbox_recent_age_s: float,
        index_status: str,
        events_status: str,
        writes_allowed: bool,
        write_guard_reason: str | None,
        catch_up_progress: dict[str, Any] | None,
        suggested_actions: list[str],
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": now.isoformat(),
            "environment": active_environment(),
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "settings_source": settings_result.source.to_payload(),
            "outbox_count": outbox_count,
            "outbox_recent_age_s": outbox_recent_age_s,
            "index_doctor_status": index_status,
            "events_doctor_status": events_status,
            "writes_allowed": writes_allowed,
            "write_guard_reason": write_guard_reason,
            "catch_up_progress": catch_up_progress,
            "suggested_actions": suggested_actions,
        }
        if settings_result.settings.incident_capture.transition_history:
            entry["recent_transition_history"] = list(self.state_machine.transition_history)
        return entry

    def _append_incident_log(self, *, path: Path, entry: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False))
                handle.write("\n")
        except Exception:
            # Intentional swallow: incident capture is best-effort and must not
            # break health evaluation — but losing an incident record silently
            # is exactly the failure this log line exists to prevent (#3894).
            logger.warning("Failed to append incident log entry to %s", path, exc_info=True)
            return

    def _count_objects(self) -> tuple[int, str | None]:
        """Count objects via the production store seam; never swallow the error (#2843).

        `get_object_store()` routes through the same fail-loud resolution as
        the rest of the runtime, so a store-resolution failure or a runtime
        error surfacing after resolution (e.g. schema missing) is captured and
        returned as data instead of being reported as an innocuous ``0``. The
        caller (`evaluate()`) treats a non-``None`` error as a distinct loud
        signal — it never gets folded into "genuinely empty".
        """
        try:
            return get_object_store().count_objects(), None
        except Exception as exc:
            # Intentional swallow: the failure is returned as data and surfaced
            # by evaluate() — logged too so the traceback is not lost (#3894).
            logger.warning("Object store count failed", exc_info=True)
            return 0, f"{type(exc).__name__}: {exc}"

    def _bootstrap_state(
        self, object_count: int, outbox_count: int, *, store_error: str | None = None
    ) -> tuple[str, str]:
        if store_error is not None:
            return "unknown", f"store object count unavailable: {store_error}"
        if object_count == 0 and outbox_count == 0:
            return "empty", "no objects ingested yet"
        return "active", "objects or outbox events detected"


GLOBAL_STATE_MACHINE = HealthStateMachine()
DEFAULT_CONTRACT = HealthContract(state_machine=GLOBAL_STATE_MACHINE)


def reset_state_machine() -> None:
    GLOBAL_STATE_MACHINE.reset()


__all__ = [
    "HealthStateMachine",
    "GLOBAL_STATE_MACHINE",
    "DEFAULT_CONTRACT",
    "HealthContract",
    "dead_letter_snapshot",
    "reset_state_machine",
]
