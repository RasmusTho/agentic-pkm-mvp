"""YSS-04 (#3919): durable, source-agnostic acquisition request queue.

Implements `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: AcquisitionRequest`
exactly: discovery must never fetch, and fetch must never depend on discovery
being alive — the durable request row is the seam. Discovery enqueues cheaply;
a bounded drain acquires later; restarts, retries, and dedup converge on the
row (INV-YSS-1..3).

Deliberately a migration-owned table, NOT outbox rows: the queue needs status
queries, trigger-append provenance, priority, and per-item backoff that
append-only events cannot carry, and its slow drain must not ride the shared
outbox worker's fast dispatch loop.

Shape and discipline:

- **Identity (INV-YSS-2):** ``request_id = uuid5(namespace,
  "{source_kind}:{item_ref}:{policy_version}")`` — one request per
  ``(source_kind, item_ref, policy_version)``. The same video saved in N
  playlists is ONE request whose ``discovery_triggers`` records all N bindings;
  a duplicate discovery appends its trigger (identity-novel triggers only — an
  identical ``(binding_id, trigger, playlist_item_id)`` re-discovery converges
  without unbounded growth) and touches nothing else.
- **Dual backend** (the ``app/heimdal/cursor_store.py`` /
  ``source_registry.py`` shape): memory for ``not_pg`` tests, Postgres for a
  configured runtime with fail-loud resolution (never a silent volatile
  fallback), migration-owned schema with a fail-loud
  :class:`AcquisitionRequestsSchemaMissingError` preflight and the
  ``STORE_SCHEMA_AUTOCREATE`` test-only autocreate opt-in.
- **Events** on the canonical DB outbox only
  (``app/services/outbox.py::write_outbox_event`` + the single shared
  ``derive_idempotency_key`` scheme; KERNEL-08 registered schemas). Lineage
  posture: these topics record queue transitions; no ``_dispatch_topic``
  branch is added. Keys: ``acquisition.requested`` is
  ``(topic, request_id, policy_version)``-scoped (first insert only);
  ``acquisition.started/completed/failed`` are attempt-scoped so a crash-retry
  duplicate delivery of the SAME attempt dedups while a genuinely new attempt
  is a distinct event; ``youtube.source.discovered`` is
  ``(topic, binding_id, item_ref)``-scoped so re-discovery of the same item in
  the same source dedups.
- **Terminality (INV-YSS-3):** ``completed`` requires the KA pipeline's
  terminal candidate outcome (note written or traced dedup no-op). A
  WriteGuard block or transient failure resets to ``pending`` with a reason
  code + backoff; ``dead_lettered`` is explicit and item-scoped (KA stage
  dead-letter surfaced, or attempts exhausted — default max 8).
- **Retry and backoff** per contract: exponential base 60 s, factor 4, cap
  6 h, with non-negative jitter (the gate never fires EARLIER than the
  deterministic floor). Rows stuck ``in_progress`` past a stale threshold are
  reset to ``pending`` by :meth:`AcquisitionRequests.reset_stale_in_progress`
  (restart recovery; the re-run converges through KA idempotency).

The drain adapter :func:`drain_one` owns *what happens* when a request runs
(the mapping from `AcquisitionReceipt` to queue state); the scheduler slice
(YSS-06) owns *when* it runs.
"""

from __future__ import annotations

import json
import os
import random
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.db.dsn import resolve_dsn
from app.events.models import new_event
from app.events.types import (
    ACQUISITION_COMPLETED,
    ACQUISITION_FAILED,
    ACQUISITION_REQUESTED,
    ACQUISITION_STARTED,
    YOUTUBE_SOURCE_DISCOVERED,
)
from app.knowledge_acquisition.source_registry import VALID_PRIORITIES as _registry_priorities
from app.services.outbox import derive_idempotency_key, write_outbox_event

# --- Contract vocab ----------------------------------------------------------

ACQUISITION_REQUESTED_TOPIC = ACQUISITION_REQUESTED
ACQUISITION_STARTED_TOPIC = ACQUISITION_STARTED
ACQUISITION_COMPLETED_TOPIC = ACQUISITION_COMPLETED
ACQUISITION_FAILED_TOPIC = ACQUISITION_FAILED
YOUTUBE_SOURCE_DISCOVERED_TOPIC = YOUTUBE_SOURCE_DISCOVERED

# Envelope attribution per SOURCE_SYNC_CONTRACT.md :: Event topics.
EVENT_SOURCE = "knowledge_acquisition.source_sync"

VALID_STATUSES: frozenset[str] = frozenset({"pending", "in_progress", "completed", "dead_lettered"})
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "dead_lettered"})
VALID_TRIGGER_KINDS: frozenset[str] = frozenset({"poll", "backfill", "manual"})

# The registry's per-source priority is what flows into request priority — one
# shared vocabulary, not a second copy (reuse over redeclaration).
VALID_PRIORITIES = _registry_priorities

# The one source kind the youtube-specific lineage topic applies to. Kept as a
# module constant (not an import of youtube_plugin, which would couple the
# source-agnostic queue to the plugin at import time); a test ties it to
# youtube_plugin.SOURCE_KIND so the two can never drift silently.
YOUTUBE_SOURCE_KIND = "youtube_url"

DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_STALE_IN_PROGRESS_SECONDS = 900

BACKOFF_BASE_SECONDS = 60
BACKOFF_FACTOR = 4
BACKOFF_CAP_SECONDS = 21600  # 6 h

# Fixed UUIDv5 namespace for deterministic request identity (INV-YSS-2).
# Changing this value changes every request id and breaks enqueue idempotency
# against existing rows — never rotate it.
ACQUISITION_REQUEST_NAMESPACE = uuid.UUID("3f8e6b1a-9d24-5c7e-8a02-6e5b1d4c9f30")

_TABLE = "acquisition_requests"
_MIGRATION_HINT = (
    "acquisition_requests schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See "
    "app/alembic/versions/b5c6d7e8f9a0_yss04_acquisition_requests.py."
)
_ALLOWED_BACKENDS = {"memory", "pg"}


class AcquisitionRequestsSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the queue table is absent."""


class AcquisitionRequestValidationError(ValueError):
    """Raised for malformed enqueue/transition inputs (fail-loud, never coerced)."""


def request_identity(source_kind: str, item_ref: str, policy_version: int) -> str:
    """Deterministic request id: ``uuid5(ns, "{source_kind}:{item_ref}:{policy_version}")``."""
    return str(
        uuid.uuid5(ACQUISITION_REQUEST_NAMESPACE, f"{source_kind}:{item_ref}:{policy_version}")
    )


def compute_backoff_seconds(attempt: int, *, rng: Callable[[], float] | None = None) -> int:
    """Backoff gate for a failed ``attempt`` (1-based) per contract §Retry and backoff.

    Deterministic floor ``min(cap, base * factor**(attempt-1))`` with base 60 s,
    factor 4, cap 6 h, plus non-negative jitter (multiplier in ``[1.0, 1.25)``)
    so concurrent retries de-synchronize but the gate never fires EARLIER than
    the floor. ``rng`` is injectable for deterministic tests (``lambda: 0.0``
    yields the exact floor).
    """
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise AcquisitionRequestValidationError(f"attempt must be a positive int, got {attempt!r}")
    floor = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * BACKOFF_FACTOR ** (attempt - 1))
    jitter = 1.0 + 0.25 * (rng() if rng is not None else random.random())
    return int(min(BACKOFF_CAP_SECONDS, floor * jitter))


# --- Event key helpers (KERNEL-02: one shared derivation scheme) -------------


def requested_event_key(request_id: str, policy_version: int) -> str:
    """``acquisition.requested`` key — ``(topic, request_id, policy_version)``."""
    return derive_idempotency_key(ACQUISITION_REQUESTED_TOPIC, request_id, f"policy:{policy_version}")


def attempt_event_key(topic: str, request_id: str, attempt: int) -> str:
    """Attempt-scoped key for started/completed — each attempt is distinct."""
    return derive_idempotency_key(topic, request_id, f"attempt:{attempt}")


def failed_event_key(request_id: str, attempt: int, *, terminal: bool) -> str:
    """Attempt-scoped key for ``acquisition.failed``, terminal-marked.

    A retryable failure and a terminal dead-letter of the SAME attempt are two
    distinct lineage facts (an explicit ``dead_letter()`` can follow a
    retryable ``fail()`` before any new claim), so the terminal marker joins
    the fingerprint — mirroring the ``retry:<n>`` / ``poison:<attempts>``
    precedent in :func:`derive_idempotency_key`'s scheme. Duplicate delivery of
    the same (attempt, terminality) still dedups.
    """
    marker = f"attempt:{attempt}:terminal" if terminal else f"attempt:{attempt}"
    return derive_idempotency_key(ACQUISITION_FAILED_TOPIC, request_id, marker)


def discovered_event_key(binding_id: str, item_ref: str) -> str:
    """``youtube.source.discovered`` key — ``(topic, binding_id, item_ref)``."""
    return derive_idempotency_key(YOUTUBE_SOURCE_DISCOVERED_TOPIC, binding_id, item_ref)


# --- Value types -------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryTrigger:
    """One discovery provenance entry (contract ``discovery_triggers`` row)."""

    binding_id: str
    collection_kind: str
    collection_ref: str
    trigger: str
    playlist_item_id: str | None = None
    discovered_at: str | None = None

    def validate(self) -> None:
        for name in ("binding_id", "collection_kind", "collection_ref", "trigger"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise AcquisitionRequestValidationError(
                    f"trigger.{name} must be a non-empty NUL-free string, got {value!r}"
                )
        if self.trigger not in VALID_TRIGGER_KINDS:
            raise AcquisitionRequestValidationError(
                f"trigger.trigger must be one of {sorted(VALID_TRIGGER_KINDS)}, got {self.trigger!r}"
            )
        if self.playlist_item_id is not None and (
            not isinstance(self.playlist_item_id, str) or not self.playlist_item_id.strip()
        ):
            raise AcquisitionRequestValidationError("trigger.playlist_item_id must be a non-empty string or None")

    def stored_dict(self, *, discovered_at: str) -> dict[str, Any]:
        """The contract trigger row persisted into ``discovery_triggers``.

        ``playlist_item_id`` is stored explicitly (``null`` when absent) so the
        novelty probe below is symmetric: identity comparison must not depend on
        which of two otherwise-identical triggers arrived first.
        """
        return {
            "binding_id": self.binding_id,
            "collection_kind": self.collection_kind,
            "playlist_item_id": self.playlist_item_id,
            "discovered_at": self.discovered_at or discovered_at,
            "trigger": self.trigger,
        }

    def identity_dict(self) -> dict[str, Any]:
        """The novelty probe — the full identity triple, order-independent.

        Always includes ``playlist_item_id`` (as ``null`` when absent): a probe
        that omitted it would be subset-matched by a stored trigger that HAS
        one, making provenance depend on discovery arrival order.
        """
        return {
            "binding_id": self.binding_id,
            "trigger": self.trigger,
            "playlist_item_id": self.playlist_item_id,
        }


@dataclass(frozen=True)
class AcquisitionRequest:
    """One durable queue row. See `SOURCE_SYNC_CONTRACT.md :: AcquisitionRequest`."""

    request_id: str
    source_kind: str
    item_ref: str
    source_ref: str
    status: str
    priority: str
    requested_at: str
    completed_at: str | None
    attempts: int
    next_attempt_at: str | None
    last_failure: dict[str, Any] | None
    discovery_triggers: tuple[dict[str, Any], ...]
    policy_snapshot: dict[str, Any]
    policy_version: int
    trace_id: str | None
    content_identity: str | None
    artifact_path: str | None
    updated_at: str = field(default="")


def _now(now: datetime | None = None) -> datetime:
    """Resolve the effective clock; a naive injected ``now`` is treated as UTC.

    Normalizing here keeps both backends parity-identical: the pg backend would
    coerce a naive timestamp to UTC at the ``::timestamptz`` cast, so the memory
    backend must not instead raise on aware-vs-naive comparison (AC7).
    """
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _validate_expected_attempt(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AcquisitionRequestValidationError(
            f"expected_attempt must be a positive int, got {value!r}"
        )


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def sanitize_error(error: BaseException | str | None) -> str | None:
    """Exception-class + bounded safe message (contract: never token material)."""
    if error is None:
        return None
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}"
    else:
        text = str(error)
    return text.replace("\x00", "")[:500]


def _copy_request(row: AcquisitionRequest) -> AcquisitionRequest:
    """Detach nested JSON so callers cannot mutate stored state in place.

    ``copy.deepcopy`` mirrors ``source_registry._copy_binding`` — no repeated
    text serialization per read.
    """
    return replace(
        row,
        last_failure=deepcopy(row.last_failure),
        discovery_triggers=tuple(deepcopy(t) for t in row.discovery_triggers),
        policy_snapshot=deepcopy(row.policy_snapshot),
    )


def _trigger_is_novel(existing: tuple[dict[str, Any], ...], probe: dict[str, Any]) -> bool:
    return not any(all(t.get(k) == v for k, v in probe.items()) for t in existing)


# --- Backend resolution (mirrors source_registry._resolve_backend) ----------


def _resolve_backend() -> str:
    override = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if override:
        if override not in _ALLOWED_BACKENDS:
            raise RuntimeError(
                f"Store backend '{override}' is not supported for the acquisition request queue: "
                "set STORE_BACKEND to 'pg' or 'memory', or unset it to resolve from "
                "DATABASE_URL/DB_DSN."
            )
        return override
    dsn = resolve_dsn()
    if not dsn:
        raise RuntimeError(
            "No store backend configured for the acquisition request queue: set "
            "STORE_BACKEND=memory explicitly for the volatile in-memory backend, or configure "
            "DATABASE_URL/DB_DSN."
        )
    try:
        import psycopg  # noqa: PLC0415

        conn = psycopg.connect(dsn, connect_timeout=1)
        conn.close()
    except Exception as exc:
        raise RuntimeError(
            "Acquisition request queue backend resolution failed: Postgres is configured but "
            f"unreachable. Refusing to fall back to a volatile in-memory store. Underlying error: {exc}"
        ) from exc
    return "pg"


# --- Memory backend ----------------------------------------------------------


class _MemoryAcquisitionRequestsBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, AcquisitionRequest] = {}

    def insert_or_append(
        self, row: AcquisitionRequest, trigger: DiscoveryTrigger
    ) -> tuple[AcquisitionRequest, bool]:
        with self._lock:
            existing = self._rows.get(row.request_id)
            if existing is None:
                self._rows[row.request_id] = _copy_request(row)
                return _copy_request(row), True
            probe = trigger.identity_dict()
            if _trigger_is_novel(existing.discovery_triggers, probe):
                # Contract: "appends the new discovery trigger ... and touches
                # nothing else" — updated_at is deliberately NOT bumped; it is
                # the stale-in_progress recovery clock, and a re-discovery must
                # never defer a crashed attempt's recovery.
                appended = replace(
                    existing,
                    discovery_triggers=existing.discovery_triggers
                    + (trigger.stored_dict(discovered_at=row.requested_at),),
                )
                self._rows[row.request_id] = appended
                return _copy_request(appended), False
            return _copy_request(existing), False

    def get(self, request_id: str) -> AcquisitionRequest | None:
        with self._lock:
            row = self._rows.get(request_id)
            return _copy_request(row) if row is not None else None

    def list_all(self) -> tuple[AcquisitionRequest, ...]:
        with self._lock:
            return tuple(_copy_request(r) for r in self._rows.values())

    def claim(self, limit: int, now: datetime) -> tuple[AcquisitionRequest, ...]:
        with self._lock:
            eligible = [
                r
                for r in self._rows.values()
                if r.status == "pending"
                and (r.next_attempt_at is None or _parse_iso(r.next_attempt_at) <= now)
            ]
            # 'high' < 'normal' lexicographically, so plain column order gives
            # high-priority-first — identical to the pg ORDER BY (index-servable).
            eligible.sort(key=lambda r: (r.priority, r.requested_at))
            claimed: list[AcquisitionRequest] = []
            for row in eligible[: max(0, limit)]:
                updated = replace(
                    row, status="in_progress", attempts=row.attempts + 1, updated_at=_iso(now)
                )
                self._rows[row.request_id] = updated
                claimed.append(_copy_request(updated))
            return tuple(claimed)

    def _mutate(
        self,
        request_id: str,
        *,
        allowed_from: frozenset[str],
        expected_attempt: int | None = None,
        **changes: Any,
    ) -> AcquisitionRequest | None:
        """Guarded transition: applies only when the current status is in
        ``allowed_from``. Returns ``None`` on a guard miss (row exists but is in
        a disallowed state — the service layer classifies), raises ``KeyError``
        when the row is missing. This is what makes terminal states terminal
        (INV-YSS-3): a stale drainer's late ``fail()`` can never reopen a
        completed/dead-lettered request.
        """
        row = self._rows.get(request_id)
        if row is None:
            raise KeyError(f"no such acquisition request: {request_id}")
        if row.status not in allowed_from or (
            expected_attempt is not None and row.attempts != expected_attempt
        ):
            return None
        updated = replace(row, **changes)
        self._rows[request_id] = updated
        return _copy_request(updated)

    def set_completed(
        self,
        request_id: str,
        *,
        content_identity: str,
        artifact_path: str | None,
        expected_attempt: int,
        now: datetime,
    ) -> AcquisitionRequest | None:
        with self._lock:
            return self._mutate(
                request_id,
                allowed_from=frozenset({"in_progress"}),
                expected_attempt=expected_attempt,
                status="completed",
                completed_at=_iso(now),
                next_attempt_at=None,
                content_identity=content_identity,
                artifact_path=artifact_path,
                updated_at=_iso(now),
            )

    def set_failed_retryable(
        self,
        request_id: str,
        *,
        last_failure: dict[str, Any],
        next_attempt_at: datetime,
        expected_attempt: int,
        now: datetime,
    ) -> AcquisitionRequest | None:
        with self._lock:
            return self._mutate(
                request_id,
                allowed_from=frozenset({"in_progress"}),
                expected_attempt=expected_attempt,
                status="pending",
                last_failure=last_failure,
                next_attempt_at=_iso(next_attempt_at),
                updated_at=_iso(now),
            )

    def set_dead_lettered(
        self,
        request_id: str,
        *,
        last_failure: dict[str, Any],
        expected_attempt: int | None,
        now: datetime,
    ) -> AcquisitionRequest | None:
        allowed_from = (
            frozenset({"pending"})
            if expected_attempt is None
            else frozenset({"in_progress"})
        )
        with self._lock:
            return self._mutate(
                request_id,
                allowed_from=allowed_from,
                expected_attempt=expected_attempt,
                status="dead_lettered",
                last_failure=last_failure,
                next_attempt_at=None,
                updated_at=_iso(now),
            )

    def reset_stale(self, older_than_seconds: int, now: datetime) -> int:
        with self._lock:
            threshold = now - timedelta(seconds=older_than_seconds)
            count = 0
            for request_id, row in list(self._rows.items()):
                if row.status == "in_progress" and _parse_iso(row.updated_at) <= threshold:
                    self._rows[request_id] = replace(row, status="pending", updated_at=_iso(now))
                    count += 1
            return count

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_MEMORY_REQUESTS = _MemoryAcquisitionRequestsBackend()


def reset_memory_acquisition_requests() -> None:
    """Test-only reset hook (mirrors the other memory-backend reset helpers)."""
    _MEMORY_REQUESTS.clear()


# --- Postgres backend ---------------------------------------------------------

_COLUMNS = (
    "request_id",
    "source_kind",
    "item_ref",
    "source_ref",
    "status",
    "priority",
    "requested_at",
    "completed_at",
    "attempts",
    "next_attempt_at",
    "last_failure",
    "discovery_triggers",
    "policy_snapshot",
    "policy_version",
    "trace_id",
    "content_identity",
    "artifact_path",
    "updated_at",
)
_COLUMNS_SQL = ", ".join(_COLUMNS)


def _pg_connect() -> Any:
    import psycopg  # noqa: PLC0415

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (_TABLE,))
    row = cur.fetchone()
    if not (row and row[0]):
        raise AcquisitionRequestsSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            request_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            item_ref TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT NOT NULL DEFAULT 'normal',
            requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ,
            last_failure JSONB,
            discovery_triggers JSONB NOT NULL DEFAULT '[]'::jsonb,
            policy_snapshot JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            policy_version INTEGER NOT NULL DEFAULT 1,
            trace_id TEXT,
            content_identity TEXT,
            artifact_path TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT acquisition_requests_status_chk CHECK (
                status IN ('pending', 'in_progress', 'completed', 'dead_lettered')
            ),
            CONSTRAINT acquisition_requests_priority_chk CHECK (priority IN ('high', 'normal'))
        )
        """
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS acquisition_requests_drain_idx "
        f"ON {_TABLE} (status, priority, requested_at)"
    )
    cur.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS acquisition_requests_identity_uq "
        f"ON {_TABLE} (source_kind, item_ref, policy_version)"
    )


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _row_to_request(row: tuple[Any, ...]) -> AcquisitionRequest:
    values = dict(zip(_COLUMNS, row))

    def _json_field(name: str, default: Any) -> Any:
        value = values[name]
        if value is None:
            return default
        if isinstance(value, str):
            return json.loads(value)
        return value

    triggers = _json_field("discovery_triggers", [])
    return AcquisitionRequest(
        request_id=values["request_id"],
        source_kind=values["source_kind"],
        item_ref=values["item_ref"],
        source_ref=values["source_ref"],
        status=values["status"],
        priority=values["priority"],
        requested_at=_iso_or_none(values["requested_at"]) or "",
        completed_at=_iso_or_none(values["completed_at"]),
        attempts=int(values["attempts"]),
        next_attempt_at=_iso_or_none(values["next_attempt_at"]),
        last_failure=_json_field("last_failure", None),
        discovery_triggers=tuple(triggers if isinstance(triggers, list) else []),
        policy_snapshot=_json_field("policy_snapshot", {}),
        policy_version=int(values["policy_version"]),
        trace_id=values["trace_id"],
        content_identity=values["content_identity"],
        artifact_path=values["artifact_path"],
        updated_at=_iso_or_none(values["updated_at"]) or "",
    )


class _PgAcquisitionRequestsBackend:
    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def insert_or_append(
        self, row: AcquisitionRequest, trigger: DiscoveryTrigger
    ) -> tuple[AcquisitionRequest, bool]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (
                    request_id, source_kind, item_ref, source_ref, status, priority,
                    requested_at, completed_at, attempts, next_attempt_at, last_failure,
                    discovery_triggers, policy_snapshot, policy_version, trace_id,
                    content_identity, artifact_path, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s::timestamptz, %s::timestamptz, %s, %s::timestamptz, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s, %s,
                    %s, %s, %s::timestamptz
                )
                ON CONFLICT (request_id) DO NOTHING
                RETURNING {_COLUMNS_SQL}
                """,
                (
                    row.request_id,
                    row.source_kind,
                    row.item_ref,
                    row.source_ref,
                    row.status,
                    row.priority,
                    row.requested_at,
                    row.completed_at,
                    row.attempts,
                    row.next_attempt_at,
                    json.dumps(row.last_failure) if row.last_failure is not None else None,
                    json.dumps(list(row.discovery_triggers)),
                    json.dumps(row.policy_snapshot),
                    row.policy_version,
                    row.trace_id,
                    row.content_identity,
                    row.artifact_path,
                    row.updated_at,
                ),
            )
            inserted = cur.fetchone()
            if inserted is not None:
                return _row_to_request(tuple(inserted)), True
            # Conflict: append the trigger IF identity-novel, and touch nothing
            # else — updated_at deliberately excluded (it is the stale-recovery
            # clock; a re-discovery must never defer a crashed attempt's reset).
            probe = trigger.identity_dict()
            cur.execute(
                f"""
                UPDATE {_TABLE}
                SET discovery_triggers = discovery_triggers || %s::jsonb
                WHERE request_id = %s
                  AND NOT (discovery_triggers @> %s::jsonb)
                RETURNING {_COLUMNS_SQL}
                """,
                (
                    json.dumps([trigger.stored_dict(discovered_at=row.requested_at)]),
                    row.request_id,
                    json.dumps([probe]),
                ),
            )
            updated = cur.fetchone()
            if updated is not None:
                return _row_to_request(tuple(updated)), False
            # Exact-duplicate trigger: nothing changed; read the existing row.
            fetched = self.get(row.request_id, conn=conn)
            assert fetched is not None  # conflicted on an existing row
            return fetched, False
        finally:
            conn.close()

    def get(self, request_id: str, conn: Any = None) -> AcquisitionRequest | None:
        own = conn is None
        conn = conn or _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_COLUMNS_SQL} FROM {_TABLE} WHERE request_id = %s", (request_id,))
            row = cur.fetchone()
            return _row_to_request(tuple(row)) if row else None
        finally:
            if own:
                conn.close()

    def list_all(self) -> tuple[AcquisitionRequest, ...]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_COLUMNS_SQL} FROM {_TABLE} ORDER BY requested_at")
            return tuple(_row_to_request(tuple(row)) for row in cur.fetchall())
        finally:
            conn.close()

    def claim(self, limit: int, now: datetime) -> tuple[AcquisitionRequest, ...]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            # Single-statement claim: atomic under autocommit; SKIP LOCKED keeps
            # concurrent drainers from double-claiming (INV-YSS-6 belongs to the
            # scheduler lease, but the row claim is still race-safe here).
            cur.execute(
                f"""
                WITH picked AS (
                    SELECT request_id FROM {_TABLE}
                    WHERE status = 'pending'
                      AND (next_attempt_at IS NULL OR next_attempt_at <= %s::timestamptz)
                    ORDER BY priority ASC, requested_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE {_TABLE} t
                SET status = 'in_progress', attempts = t.attempts + 1, updated_at = %s::timestamptz
                FROM picked
                WHERE t.request_id = picked.request_id
                RETURNING {", ".join("t." + c for c in _COLUMNS)}
                """,
                (_iso(now), max(0, limit), _iso(now)),
            )
            rows = [_row_to_request(tuple(r)) for r in cur.fetchall()]
            # RETURNING order is not guaranteed; re-sort with the same key as
            # the pick ('high' < 'normal' lexicographically, then FIFO).
            rows.sort(key=lambda r: (r.priority, r.requested_at))
            return tuple(rows)
        finally:
            conn.close()

    def _mutate(
        self,
        request_id: str,
        sets: str,
        params: tuple[Any, ...],
        *,
        allowed_from: tuple[str, ...],
        expected_attempt: int | None = None,
    ) -> AcquisitionRequest | None:
        """Guarded single-statement transition (``UPDATE ... RETURNING``).

        The status predicate makes terminal states terminal (INV-YSS-3): a
        stale drainer's late ``fail()``/``complete()`` cannot reopen or rewrite
        a completed/dead-lettered row. Returns ``None`` on a guard miss (row
        exists in a disallowed state — the service layer classifies), raises
        ``KeyError`` when the row is missing.
        """
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            attempt_predicate = "" if expected_attempt is None else " AND attempts = %s"
            attempt_params: tuple[Any, ...] = (
                () if expected_attempt is None else (expected_attempt,)
            )
            cur.execute(
                f"UPDATE {_TABLE} SET {sets} WHERE request_id = %s AND status = ANY(%s)"
                f"{attempt_predicate} RETURNING {_COLUMNS_SQL}",
                (*params, request_id, list(allowed_from), *attempt_params),
            )
            row = cur.fetchone()
            if row is not None:
                return _row_to_request(tuple(row))
            if self.get(request_id, conn=conn) is None:
                raise KeyError(f"no such acquisition request: {request_id}")
            return None
        finally:
            conn.close()

    def set_completed(
        self,
        request_id: str,
        *,
        content_identity: str,
        artifact_path: str | None,
        expected_attempt: int,
        now: datetime,
    ) -> AcquisitionRequest | None:
        return self._mutate(
            request_id,
            "status = 'completed', completed_at = %s::timestamptz, next_attempt_at = NULL, "
            "content_identity = %s, artifact_path = %s, updated_at = %s::timestamptz",
            (_iso(now), content_identity, artifact_path, _iso(now)),
            allowed_from=("in_progress",),
            expected_attempt=expected_attempt,
        )

    def set_failed_retryable(
        self,
        request_id: str,
        *,
        last_failure: dict[str, Any],
        next_attempt_at: datetime,
        expected_attempt: int,
        now: datetime,
    ) -> AcquisitionRequest | None:
        return self._mutate(
            request_id,
            "status = 'pending', last_failure = %s::jsonb, next_attempt_at = %s::timestamptz, "
            "updated_at = %s::timestamptz",
            (json.dumps(last_failure), _iso(next_attempt_at), _iso(now)),
            allowed_from=("in_progress",),
            expected_attempt=expected_attempt,
        )

    def set_dead_lettered(
        self,
        request_id: str,
        *,
        last_failure: dict[str, Any],
        expected_attempt: int | None,
        now: datetime,
    ) -> AcquisitionRequest | None:
        allowed_from = ("pending",) if expected_attempt is None else ("in_progress",)
        return self._mutate(
            request_id,
            "status = 'dead_lettered', last_failure = %s::jsonb, next_attempt_at = NULL, "
            "updated_at = %s::timestamptz",
            (json.dumps(last_failure), _iso(now)),
            allowed_from=allowed_from,
            expected_attempt=expected_attempt,
        )

    def reset_stale(self, older_than_seconds: int, now: datetime) -> int:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                UPDATE {_TABLE}
                SET status = 'pending', updated_at = %s::timestamptz
                WHERE status = 'in_progress' AND updated_at <= %s::timestamptz
                """,
                (_iso(now), _iso(now - timedelta(seconds=older_than_seconds))),
            )
            return cur.rowcount
        finally:
            conn.close()


# --- Service layer ------------------------------------------------------------


class AcquisitionRequests:
    """Service facade enforcing identical semantics on both backends."""

    def __init__(
        self,
        backend: _MemoryAcquisitionRequestsBackend | _PgAcquisitionRequestsBackend,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._backend = backend
        self._max_attempts = max_attempts

    @classmethod
    def for_runtime(cls, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> "AcquisitionRequests":
        if _resolve_backend() == "pg":
            return cls(_PgAcquisitionRequestsBackend(), max_attempts=max_attempts)
        return cls(_MEMORY_REQUESTS, max_attempts=max_attempts)

    # -- enqueue ---------------------------------------------------------------

    def enqueue(
        self,
        *,
        source_kind: str,
        item_ref: str,
        source_ref: str,
        trigger: DiscoveryTrigger,
        priority: str = "normal",
        policy_snapshot: dict[str, Any] | None = None,
        trace_id: str | None = None,
        now: datetime | None = None,
        conn: Any = None,
    ) -> AcquisitionRequest:
        """Idempotent enqueue (INV-YSS-2). Emits ``youtube.source.discovered``
        (key-deduped per ``(binding_id, item_ref)``) and, on first insert only,
        ``acquisition.requested``. On conflict the identity-novel trigger is
        appended and nothing else is touched — a completed/dead-lettered request
        is never reopened by a late duplicate discovery.
        """
        for name, value in (("source_kind", source_kind), ("item_ref", item_ref), ("source_ref", source_ref)):
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise AcquisitionRequestValidationError(
                    f"{name} must be a non-empty NUL-free string, got {value!r}"
                )
        if priority not in VALID_PRIORITIES:
            raise AcquisitionRequestValidationError(
                f"priority must be one of {sorted(VALID_PRIORITIES)}, got {priority!r}"
            )
        if not isinstance(trigger, DiscoveryTrigger):
            raise AcquisitionRequestValidationError("trigger must be a DiscoveryTrigger")
        trigger.validate()

        snapshot = dict(policy_snapshot) if policy_snapshot is not None else {"policy_version": 1}
        policy_version = snapshot.get("policy_version", 1)
        if not isinstance(policy_version, int) or isinstance(policy_version, bool) or policy_version < 1:
            raise AcquisitionRequestValidationError(
                f"policy_snapshot.policy_version must be a positive int, got {policy_version!r}"
            )
        # Normalize: the stored snapshot always mirrors the authoritative
        # policy_version column, so no later reader can see the two disagree.
        snapshot["policy_version"] = policy_version
        extractor_ids = snapshot.get("extractor_ids")
        if extractor_ids is not None:
            if not isinstance(extractor_ids, list) or not all(
                isinstance(x, str) and x.strip() for x in extractor_ids
            ):
                raise AcquisitionRequestValidationError(
                    "policy_snapshot.extractor_ids must be a list of non-empty strings"
                )
        if snapshot.get("extractor_requirements") is not None:
            extractor_requirements = snapshot["extractor_requirements"]
            if not isinstance(extractor_requirements, dict) or not all(
                isinstance(key, str)
                and key.strip()
                and value
                in {
                    "required",
                    "optional",
                    "required_for_materialization",
                    "optional_for_materialization",
                }
                for key, value in extractor_requirements.items()
            ):
                raise AcquisitionRequestValidationError(
                    "policy_snapshot.extractor_requirements must map non-empty extractor ids "
                    "to a required/optional materialization classification"
                )
            selected = tuple(extractor_ids or ("summary",))
            if set(extractor_requirements) != set(selected):
                raise AcquisitionRequestValidationError(
                    "policy_snapshot.extractor_requirements must classify every selected "
                    "extractor exactly once"
                )

        moment = _now(now)
        stamp = _iso(moment)
        request_id = request_identity(source_kind, item_ref, policy_version)
        row = AcquisitionRequest(
            request_id=request_id,
            source_kind=source_kind,
            item_ref=item_ref,
            source_ref=source_ref,
            status="pending",
            priority=priority,
            requested_at=stamp,
            completed_at=None,
            attempts=0,
            next_attempt_at=None,
            last_failure=None,
            discovery_triggers=(trigger.stored_dict(discovered_at=stamp),),
            policy_snapshot=snapshot,
            policy_version=policy_version,
            trace_id=trace_id,
            content_identity=None,
            artifact_path=None,
            updated_at=stamp,
        )
        stored, created = self._backend.insert_or_append(row, trigger)

        # Discovery lineage: youtube-shaped sources only (the queue itself is
        # source-agnostic; the topic is not).
        if source_kind == YOUTUBE_SOURCE_KIND:
            payload: dict[str, Any] = {
                "binding_id": trigger.binding_id,
                "collection_kind": trigger.collection_kind,
                "collection_ref": trigger.collection_ref,
                "item_ref": item_ref,
                "trigger": trigger.trigger,
            }
            if trigger.playlist_item_id is not None:
                payload["playlist_item_id"] = trigger.playlist_item_id
            self._emit(
                YOUTUBE_SOURCE_DISCOVERED_TOPIC,
                payload,
                key=discovered_event_key(trigger.binding_id, item_ref),
                trace_id=trace_id,
                conn=conn,
            )
        # Emitted unconditionally with the deterministic (request_id,
        # policy_version) key: the FIRST emission wins and duplicates dedup, so
        # a crash between the row insert and the emit self-heals on the next
        # duplicate discovery instead of losing the event forever.
        self._emit(
            ACQUISITION_REQUESTED_TOPIC,
            {
                "request_id": request_id,
                "source_kind": source_kind,
                "item_ref": item_ref,
                "policy_version": policy_version,
                "priority": priority,
                "trigger_count": len(stored.discovery_triggers),
            },
            key=requested_event_key(request_id, policy_version),
            trace_id=trace_id,
            conn=conn,
        )
        del created  # identity/dedup outcome is visible via discovery_triggers
        return stored

    # -- drain lifecycle -------------------------------------------------------

    def claim_batch(
        self, limit: int, *, now: datetime | None = None, conn: Any = None
    ) -> list[AcquisitionRequest]:
        """Claim up to ``limit`` due pending requests in ``(priority, requested_at)``
        order, marking them ``in_progress`` (attempt += 1) and emitting one
        attempt-scoped ``acquisition.started`` per claim.
        """
        moment = _now(now)
        claimed = self._backend.claim(limit, moment)
        for row in claimed:
            self._emit(
                ACQUISITION_STARTED_TOPIC,
                {"request_id": row.request_id, "attempt": row.attempts},
                key=attempt_event_key(ACQUISITION_STARTED_TOPIC, row.request_id, row.attempts),
                trace_id=row.trace_id,
                conn=conn,
            )
        return list(claimed)

    def complete(
        self,
        request_id: str,
        *,
        expected_attempt: int,
        content_identity: str,
        artifact_path: str | None = None,
        dedup_noop: bool = False,
        now: datetime | None = None,
        conn: Any = None,
    ) -> AcquisitionRequest:
        """Terminal success (INV-YSS-3): candidate written or traced dedup no-op.

        Applies only to the claimed (``in_progress``, matching ``expected_attempt``) request. A late complete on
        an already-terminal row is an idempotent no-op returning the terminal
        row unchanged (no event); completing a never-claimed row is a loud
        caller error.
        """
        if not isinstance(content_identity, str) or not content_identity.strip():
            raise AcquisitionRequestValidationError("content_identity must be a non-empty string")
        _validate_expected_attempt(expected_attempt)
        moment = _now(now)
        row = self._backend.set_completed(
            request_id,
            content_identity=content_identity,
            artifact_path=artifact_path,
            expected_attempt=expected_attempt,
            now=moment,
        )
        if row is None:
            return self._classify_guard_miss(
                request_id, action="complete", expected_attempt=expected_attempt
            )
        payload: dict[str, Any] = {
            "request_id": request_id,
            "attempt": row.attempts,
            "content_identity": content_identity,
            "dedup_noop": dedup_noop,
        }
        if artifact_path is not None:
            payload["artifact_path"] = artifact_path
        self._emit(
            ACQUISITION_COMPLETED_TOPIC,
            payload,
            key=attempt_event_key(ACQUISITION_COMPLETED_TOPIC, request_id, row.attempts),
            trace_id=row.trace_id,
            conn=conn,
        )
        return row

    def fail(
        self,
        request_id: str,
        *,
        expected_attempt: int,
        reason_code: str,
        error: BaseException | str | None = None,
        now: datetime | None = None,
        conn: Any = None,
        rng: Callable[[], float] | None = None,
    ) -> AcquisitionRequest:
        """Reason-coded failure of the current attempt.

        Retryable: back to ``pending`` with a contract backoff gate. Attempts
        exhausted (``>= max_attempts``): explicit item-scoped ``dead_lettered``
        with ``terminal: true``. Applies only to a claimed (``in_progress``)
        request generation: a late fail from a stale drainer on an already-terminal row is
        an idempotent no-op (INV-YSS-3 — terminal is terminal), and failing a
        never-claimed row is a loud caller error.
        """
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise AcquisitionRequestValidationError("reason_code must be a non-empty string")
        _validate_expected_attempt(expected_attempt)
        current = self._backend.get(request_id)
        if current is None:
            raise KeyError(f"no such acquisition request: {request_id}")
        if current.status in TERMINAL_STATUSES:
            return current
        if current.status != "in_progress":
            raise AcquisitionRequestValidationError(
                f"fail requires a claimed (in_progress) request; {request_id} is {current.status!r}"
            )
        if current.attempts != expected_attempt:
            return self._classify_guard_miss(
                request_id, action="fail", expected_attempt=expected_attempt
            )
        moment = _now(now)
        attempt = expected_attempt
        last_failure = {
            "reason_code": reason_code,
            "error": sanitize_error(error),
            "at": _iso(moment),
        }
        if attempt >= self._max_attempts:
            row = self._backend.set_dead_lettered(
                request_id,
                last_failure=last_failure,
                expected_attempt=expected_attempt,
                now=moment,
            )
            if row is None:
                return self._classify_guard_miss(
                    request_id, action="fail", expected_attempt=expected_attempt
                )
            self._emit_failed(row, attempt, reason_code, terminal=True, next_attempt_at=None, conn=conn)
            return row
        gate = moment + timedelta(seconds=compute_backoff_seconds(attempt, rng=rng))
        row = self._backend.set_failed_retryable(
            request_id,
            last_failure=last_failure,
            next_attempt_at=gate,
            expected_attempt=expected_attempt,
            now=moment,
        )
        if row is None:
            return self._classify_guard_miss(
                request_id, action="fail", expected_attempt=expected_attempt
            )
        self._emit_failed(row, attempt, reason_code, terminal=False, next_attempt_at=_iso(gate), conn=conn)
        return row

    def dead_letter(
        self,
        request_id: str,
        *,
        expected_attempt: int | None = None,
        reason_code: str,
        error: BaseException | str | None = None,
        now: datetime | None = None,
        conn: Any = None,
    ) -> AcquisitionRequest:
        """Explicit item-scoped terminal outcome (KA stage dead-letter surfaced).

        Applies from ``in_progress`` with its expected attempt generation, or from unowned
        ``pending``; a repeat on an
        already-terminal row is an idempotent no-op (INV-YSS-3).
        """
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise AcquisitionRequestValidationError("reason_code must be a non-empty string")
        if expected_attempt is not None:
            _validate_expected_attempt(expected_attempt)
        moment = _now(now)
        last_failure = {
            "reason_code": reason_code,
            "error": sanitize_error(error),
            "at": _iso(moment),
        }
        current = self._backend.get(request_id)
        if current is None:
            raise KeyError(f"no such acquisition request: {request_id}")
        if current.status == "in_progress" and expected_attempt is None:
            raise AcquisitionRequestValidationError(
                "dead_letter requires expected_attempt for an in_progress request"
            )
        row = self._backend.set_dead_lettered(
            request_id,
            last_failure=last_failure,
            expected_attempt=expected_attempt,
            now=moment,
        )
        if row is None:
            return self._classify_guard_miss(
                request_id, action="dead_letter", expected_attempt=expected_attempt
            )
        self._emit_failed(
            row, max(1, row.attempts), reason_code, terminal=True, next_attempt_at=None, conn=conn
        )
        return row

    def _classify_guard_miss(
        self,
        request_id: str,
        *,
        action: str,
        expected_attempt: int | None = None,
    ) -> AcquisitionRequest:
        """A guarded transition matched no row: terminal ⇒ idempotent no-op
        (return the terminal row unchanged, emit nothing — INV-YSS-3), any other
        disallowed state ⇒ loud caller error, missing ⇒ KeyError."""
        current = self._backend.get(request_id)
        if current is None:
            raise KeyError(f"no such acquisition request: {request_id}")
        if current.status in TERMINAL_STATUSES:
            return current
        if expected_attempt is not None and current.attempts != expected_attempt:
            raise AcquisitionRequestValidationError(
                f"{action} belongs to stale attempt {expected_attempt}; "
                f"request {request_id} is owned by attempt {current.attempts}"
            )
        raise AcquisitionRequestValidationError(
            f"{action} is not applicable to request {request_id} in status {current.status!r}"
        )

    def reset_stale_in_progress(
        self,
        *,
        older_than_seconds: int = DEFAULT_STALE_IN_PROGRESS_SECONDS,
        now: datetime | None = None,
    ) -> int:
        """Restart recovery: rows stuck ``in_progress`` past the threshold go back
        to ``pending`` (attempts untouched, no event — the next claim emits its
        own attempt-scoped ``acquisition.started``). Returns the reset count.
        """
        return self._backend.reset_stale(older_than_seconds, _now(now))

    # -- reads ----------------------------------------------------------------

    def get(self, request_id: str) -> AcquisitionRequest | None:
        return self._backend.get(request_id)

    def list_all(self) -> tuple[AcquisitionRequest, ...]:
        return self._backend.list_all()

    # -- emission helpers ------------------------------------------------------

    def _emit_failed(
        self,
        row: AcquisitionRequest,
        attempt: int,
        reason_code: str,
        *,
        terminal: bool,
        next_attempt_at: str | None,
        conn: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "request_id": row.request_id,
            "attempt": attempt,
            "reason_code": reason_code,
            "terminal": terminal,
        }
        if next_attempt_at is not None:
            payload["next_attempt_at"] = next_attempt_at
        self._emit(
            ACQUISITION_FAILED_TOPIC,
            payload,
            key=failed_event_key(row.request_id, attempt, terminal=terminal),
            trace_id=row.trace_id,
            conn=conn,
        )

    def _emit(
        self, topic: str, payload: dict[str, Any], *, key: str, trace_id: str | None, conn: Any
    ) -> None:
        event = new_event(event_type=topic, payload=payload, trace_id=trace_id, source=EVENT_SOURCE)
        write_outbox_event(event, conn=conn, idempotency_key=key)


# --- Drain adapter ------------------------------------------------------------


def drain_one(
    request: AcquisitionRequest,
    *,
    vault_context: Any,
    queue: AcquisitionRequests,
    write_guard: Any = None,
    conn: Any = None,
    env: Any = None,
    now: datetime | None = None,
    acquire_fn: Callable[..., Any] | None = None,
) -> AcquisitionRequest:
    """Run one claimed request through the existing KA pipeline and map its
    outcome to queue state per INV-YSS-3.

    - ``AcquisitionReceipt.ok`` → :meth:`AcquisitionRequests.complete`
      (+``content_identity``/``artifact_path``; ``dedup_noop`` when the
      candidate write was the traced ``already_exists`` no-op).
    - ``blocked`` (governed WriteGuard denial) → retryable
      ``writeguard_blocked``.
    - required stage dead-letter → ``pipeline_dead_letter`` — terminal, item-scoped.
    - optional stage dead-letter with a degraded candidate → ``completed``; the candidate and
      receipt retain the visible evidence gap and rerun handle.
    - raised :class:`AcquisitionError` → retryable ``network_error`` (the
      transient fetch/ASR chain dominates this path; deterministic pipeline
      failures still surface their durable stage dead-letter in lineage and
      converge to ``dead_lettered`` through attempts exhaustion).

    A queue row carries the effective acquisition policy at enqueue time, so
    the drain is its enforcement boundary.  The current ``acquire_youtube``
    entrypoint is a full transcript/caption pipeline: it cannot truthfully
    service ``candidate_metadata_only``, ``captions: false``, or enabled media
    archival. Those modes therefore produce an explicit terminal policy
    disposition before any external acquisition occurs; a future metadata-only
    or media pipeline must replace the corresponding guarded branch rather
    than bypass it.

    The scheduler slice (YSS-06) owns *when* this runs; unexpected exceptions
    (config errors such as ``DatabaseNotConfiguredError`` included) propagate
    loud rather than being folded into queue state.
    """
    from app.knowledge_acquisition.acquire import (
        AcquisitionError,
        RetryableSourceAcquisitionError,
        TerminalAcquisitionError,
        acquire_youtube,
    )
    from app.write_guard import DEFAULT_WRITE_GUARD

    if request.source_kind != YOUTUBE_SOURCE_KIND:
        # No drain adapter exists for this kind yet: an explicit item-scoped
        # terminal outcome with the contract reason code, never a crash that
        # would wedge the whole drain loop on one row.
        return queue.dead_letter(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="source_unsupported",
            error=f"no drain adapter for source_kind {request.source_kind!r}",
            now=now,
            conn=conn,
        )

    policy = request.policy_snapshot or {}
    mode = policy.get("mode")
    captions = policy.get("captions")
    media = policy.get("media")
    unsupported_policy: str | None = None
    if media is not None and not isinstance(media, dict):
        unsupported_policy = "policy media must be an object when present"
    elif media is not None and media.get("enabled") is True:
        return queue.dead_letter(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="media_policy_disabled",
            error="media acquisition is disabled because the archival engine is not delivered",
            now=now,
            conn=conn,
        )
    elif mode == "candidate_metadata_only":
        unsupported_policy = (
            "policy mode 'candidate_metadata_only' requires a metadata-only candidate "
            "pipeline, which is not available at this drain boundary"
        )
    elif captions is False:
        unsupported_policy = (
            "policy captions=false cannot be honored by the current full transcript "
            "acquisition pipeline"
        )
    elif mode not in (None, "acquire_transcript"):
        unsupported_policy = f"policy mode {mode!r} has no acquisition drain implementation"

    if unsupported_policy is not None:
        return queue.dead_letter(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="policy_unsupported",
            error=unsupported_policy,
            now=now,
            conn=conn,
        )

    raw_extractor_ids = policy.get("extractor_ids") or ()
    if isinstance(raw_extractor_ids, str):
        return queue.dead_letter(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="policy_invalid",
            error="policy_snapshot.extractor_ids must be a list of strings",
            now=now,
            conn=conn,
        )
    extractor_ids = tuple(raw_extractor_ids) or ("summary",)
    raw_extractor_requirements = policy.get("extractor_requirements")
    if raw_extractor_requirements is not None and not isinstance(
        raw_extractor_requirements, dict
    ):
        return queue.dead_letter(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="policy_invalid",
            error="policy_snapshot.extractor_requirements must be an object",
            now=now,
            conn=conn,
        )
    extractor_requirements = (
        dict(raw_extractor_requirements)
        if raw_extractor_requirements is not None
        else None
    )
    guard = write_guard if write_guard is not None else DEFAULT_WRITE_GUARD
    fn = acquire_fn or acquire_youtube

    try:
        receipt = fn(
            request.source_ref,
            vault_context=vault_context,
            extractor_ids=extractor_ids,
            extractor_requirements=extractor_requirements,
            write_guard=guard,
            trace_id=request.trace_id,
            conn=conn,
            env=env,
        )
    except TerminalAcquisitionError as exc:
        return queue.dead_letter(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="pipeline_configuration_or_persistence",
            error=exc,
            now=now,
            conn=conn,
        )
    except AcquisitionError as exc:
        return queue.fail(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code=(exc.reason_code if isinstance(exc, RetryableSourceAcquisitionError) else "network_error"),
            error=exc,
            now=now,
            conn=conn,
        )

    if receipt.blocked:
        blocked_detail = next(
            (s.detail for s in receipt.stages if s.stage == "candidate" and s.status == "blocked"),
            None,
        )
        return queue.fail(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="writeguard_blocked",
            error=blocked_detail or "candidate write blocked by WriteGuard",
            now=now,
            conn=conn,
        )

    required_dead_lettered = tuple(getattr(receipt, "required_dead_lettered", ()))
    optional_dead_lettered = tuple(getattr(receipt, "optional_dead_lettered", ()))
    # Compatibility with pre-policy receipts: an unclassified dead-letter remains required.
    blocking_dead_lettered = tuple(
        dict.fromkeys(
            (
                *required_dead_lettered,
                *(
                    item
                    for item in receipt.dead_lettered
                    if item not in optional_dead_lettered
                ),
            )
        )
    )
    if blocking_dead_lettered:
        return queue.dead_letter(
            request.request_id,
            expected_attempt=request.attempts,
            reason_code="pipeline_dead_letter",
            error=f"required stage dead-letter: {', '.join(blocking_dead_lettered)}",
            now=now,
            conn=conn,
        )

    candidate = next((s for s in receipt.stages if s.stage == "candidate"), None)
    return queue.complete(
        request.request_id,
        expected_attempt=request.attempts,
        content_identity=receipt.content_identity,
        artifact_path=candidate.artifact_path if candidate is not None else None,
        dedup_noop=bool(candidate is not None and candidate.status == "already_exists"),
        now=now,
        conn=conn,
    )


__all__ = [
    "ACQUISITION_COMPLETED_TOPIC",
    "ACQUISITION_FAILED_TOPIC",
    "ACQUISITION_REQUESTED_TOPIC",
    "ACQUISITION_REQUEST_NAMESPACE",
    "ACQUISITION_STARTED_TOPIC",
    "AcquisitionRequest",
    "AcquisitionRequestValidationError",
    "AcquisitionRequests",
    "AcquisitionRequestsSchemaMissingError",
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_CAP_SECONDS",
    "BACKOFF_FACTOR",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_STALE_IN_PROGRESS_SECONDS",
    "DiscoveryTrigger",
    "EVENT_SOURCE",
    "TERMINAL_STATUSES",
    "VALID_PRIORITIES",
    "VALID_STATUSES",
    "VALID_TRIGGER_KINDS",
    "YOUTUBE_SOURCE_DISCOVERED_TOPIC",
    "YOUTUBE_SOURCE_KIND",
    "attempt_event_key",
    "compute_backoff_seconds",
    "discovered_event_key",
    "drain_one",
    "failed_event_key",
    "request_identity",
    "requested_event_key",
    "reset_memory_acquisition_requests",
    "sanitize_error",
]
