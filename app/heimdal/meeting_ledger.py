"""Meeting session/segment ledger (CDLM-02, issue #4385).

Specified by
`docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS.md`
and bound by INV-CDLM-3 (idempotent rows) and INV-CDLM-9 (gaps are legible) in
that directory's `README.md`. No person attribution appears anywhere in this
schema (INV-CDLM-8).

This module makes "which parts of this meeting does the hub durably hold?" a
database answer. It consumes CDLM-01's admission seam — every admission that
carries `(session_id, session_seq)` upserts exactly one ledger row referencing
the admission receipt — and it is what CDLM-06 projections and CDLM-03/09
reconnect resend read.

Load-bearing rules:

- **Idempotent by client-minted identity.** Re-posting open/close replays the
  recorded outcome; a replayed admission never duplicates a segment row.
- **Sequence conflicts fail closed.** A *different* content hash arriving for
  an already-ledgered `(session_id, session_seq)` never replaces the original
  row: the conflict is recorded in its own append-only table and surfaced as
  `needs_attention` in the gap report. A ledger that silently replaced a
  sequence row would rewrite what "the hub holds" means.
- **Sessions never re-open.** A late admission into a closed session updates
  the ledger, emits `heimdal.meeting.segment.late_admitted`, and completeness
  is recomputed from the ledger — the close record itself is immutable.
- **The ledger IS the state.** Rows live in durable storage (SQLite file for
  the dev/test lane, migration-owned Postgres for PDM); a hub restart rebuilds
  nothing from memory. Nothing in this module caches ledger state in-process.

Storage backends, resolved per the Heimdal family convention
(`app.heimdal._backend.resolve_heimdal_backend`):

- `pg`: migration-owned tables (`heimdal_meeting_session`,
  `heimdal_meeting_segment`, `heimdal_meeting_segment_conflict`, migration
  `a7c2e9f4b1d3`) whose absence fails loud rather than silently degrading.
- `memory`: a SQLite file at ``HEIMDAL_MEETING_LEDGER_PATH``. Unlike the
  sibling memory stores this one is file-backed even in the dev/test lane,
  because the restart AC ("a simulated hub restart loses no ledger state") is
  only honest if the test lane has real durable storage to read back from —
  the same posture `tests/panel/test_proposal_store_persistence.py` uses. When
  the env var is unset a per-process temp file is used, making the state
  volatile per test session the way the sibling memory backends are.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.events.schema import make_outbox_event
from app.events.types import HEIMDAL_MEETING_SEGMENT_LATE_ADMITTED
from app.heimdal._backend import resolve_heimdal_backend
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services import outbox as outbox_service

logger = logging.getLogger(__name__)

_EVENT_SOURCE = "heimdal.meeting.ledger"
LATE_ADMITTED_EVENT = HEIMDAL_MEETING_SEGMENT_LATE_ADMITTED

_SESSION_TABLE = "heimdal_meeting_session"
_SEGMENT_TABLE = "heimdal_meeting_segment"
_CONFLICT_TABLE = "heimdal_meeting_segment_conflict"

_MIGRATION_HINT = (
    "heimdal meeting-ledger schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/a7c2e9f4b1d3_heim_meeting_ledger_v0.py."
)

_LEDGER_PATH_ENV = "HEIMDAL_MEETING_LEDGER_PATH"

# Upper bound on sequence numbers and declared final counts. A meeting emits
# segments at human-time scale (seconds each), so six figures is far past any
# real session; without a bound, one huge declared count makes every later gap
# report materialize `range(count)` and turns the immutable close into a
# permanent crash trigger (second-round review P1). Enforced at every input
# boundary: the sidecar schema, the close route, and this module's validators.
MAX_SESSION_SEQ = 100_000

# Segment outcomes, returned by `record_segment_admission`.
OUTCOME_RECORDED = "recorded"
OUTCOME_REPLAY = "replay"
OUTCOME_CONFLICT = "conflict"


class MeetingSessionNotFoundError(LookupError):
    """The named session has no open record in the ledger."""


class MeetingLedgerSchemaMissingError(RuntimeError):
    """Postgres backend selected but the ledger tables are absent (fail loud)."""


class MeetingLedgerPersistenceError(RuntimeError):
    """A ledger write or read-back could not be completed durably."""


@dataclass(frozen=True)
class MeetingSession:
    """One meeting session's recorded lifecycle state."""

    session_id: str
    device_id: str
    template_selection: Dict[str, Any]
    opened_at: datetime
    closed: bool
    final_seq_count: Optional[int]
    closed_at: Optional[datetime]
    trace_id: str


@dataclass(frozen=True)
class SegmentRow:
    """One ledgered segment: the durable link from a sequence number to its receipt."""

    session_id: str
    session_seq: int
    receipt_id: str
    content_sha256: str
    raw_ref: str
    admitted_at: datetime
    late: bool


@dataclass(frozen=True)
class SegmentConflict:
    """A recorded fail-closed conflict: a different hash for an existing pair."""

    session_id: str
    session_seq: int
    attempted_content_sha256: str
    attempted_receipt_id: str
    recorded_at: datetime


@dataclass(frozen=True)
class SegmentOutcome:
    """What one admission did to the ledger.

    ``outcome`` is ``recorded`` (new row), ``replay`` (same identity already
    ledgered; nothing changed), or ``conflict`` (different content hash for an
    existing pair; original preserved, conflict recorded). ``late`` is True
    exactly when a new row landed in an already-closed session.
    """

    outcome: str
    late: bool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _validate_session_id(session_id: Any) -> str:
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(f"session_id must be a non-empty string, got {session_id!r}")
    return session_id.strip()


def _validate_seq(session_seq: Any) -> int:
    if (
        isinstance(session_seq, bool)
        or not isinstance(session_seq, int)
        or session_seq < 0
        or session_seq > MAX_SESSION_SEQ
    ):
        raise ValueError(
            f"session_seq must be an integer in [0, {MAX_SESSION_SEQ}], got {session_seq!r}"
        )
    return session_seq


# ---------------------------------------------------------------------------
# SQLite backend (dev/test lane — file-backed so restart is honestly testable)
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_SESSION_TABLE} (
    session_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    template_selection TEXT NOT NULL DEFAULT '{{}}',
    opened_at TEXT NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0,
    final_seq_count INTEGER,
    closed_at TEXT,
    trace_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS {_SEGMENT_TABLE} (
    session_id TEXT NOT NULL,
    session_seq INTEGER NOT NULL,
    receipt_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_ref TEXT NOT NULL DEFAULT '',
    admitted_at TEXT NOT NULL,
    late INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, session_seq)
);
CREATE TABLE IF NOT EXISTS {_CONFLICT_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    session_seq INTEGER NOT NULL,
    attempted_content_sha256 TEXT NOT NULL,
    attempted_receipt_id TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL
);
"""

_process_tmp_lock = threading.Lock()
_process_tmp_path: Optional[str] = None


def _sqlite_path() -> str:
    """Resolve the SQLite ledger path.

    ``HEIMDAL_MEETING_LEDGER_PATH`` when set (the dev/test durable location);
    otherwise one per-process temp file, created lazily — volatile across
    processes like the sibling memory backends, but still consistent within
    one process.
    """
    env_path = (os.environ.get(_LEDGER_PATH_ENV) or "").strip()
    if env_path:
        return env_path
    global _process_tmp_path
    with _process_tmp_lock:
        if _process_tmp_path is None:
            fd, path = tempfile.mkstemp(prefix="heimdal-meeting-ledger-", suffix=".sqlite3")
            os.close(fd)
            _process_tmp_path = path
        return _process_tmp_path


def reset_process_meeting_ledger() -> None:
    """Test-only reset for the *default* (env-unset) per-process ledger file."""
    global _process_tmp_path
    with _process_tmp_lock:
        if _process_tmp_path is not None:
            try:
                Path(_process_tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            _process_tmp_path = None


class _SqliteLedgerStore:
    """File-backed ledger store. One connection per operation, no in-process cache:
    the file is the state, which is exactly what the restart AC asserts."""

    def __init__(self, path: str) -> None:
        self._path = path
        with self._connect() as conn:
            conn.executescript(_SQLITE_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # Commit-on-success AND close: `sqlite3.Connection`'s own context
        # manager only commits, and a connection left to the GC holds the file
        # handle open for the rest of the process.
        conn = sqlite3.connect(self._path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def open_session(self, session: MeetingSession) -> tuple[MeetingSession, bool]:
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_SESSION_TABLE} "
                "(session_id, device_id, template_selection, opened_at, closed, "
                " final_seq_count, closed_at, trace_id) "
                "VALUES (?, ?, ?, ?, 0, NULL, NULL, ?)",
                (
                    session.session_id,
                    session.device_id,
                    json.dumps(session.template_selection),
                    _iso(session.opened_at),
                    session.trace_id,
                ),
            )
            created = cur.rowcount == 1
        existing = self.get_session(session.session_id)
        if existing is None:
            raise MeetingLedgerPersistenceError(
                f"session {session.session_id!r} was neither inserted nor readable"
            )
        return existing, created

    def close_session(
        self, session_id: str, final_seq_count: int, closed_at: datetime
    ) -> tuple[MeetingSession, bool]:
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE {_SESSION_TABLE} SET closed = 1, final_seq_count = ?, closed_at = ? "
                "WHERE session_id = ? AND closed = 0",
                (final_seq_count, _iso(closed_at), session_id),
            )
            newly_closed = cur.rowcount == 1
        session = self.get_session(session_id)
        if session is None:
            raise MeetingSessionNotFoundError(f"session {session_id!r} is not in the ledger")
        return session, newly_closed

    def get_session(self, session_id: str) -> Optional[MeetingSession]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT session_id, device_id, template_selection, opened_at, closed, "
                f"final_seq_count, closed_at, trace_id FROM {_SESSION_TABLE} "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return MeetingSession(
            session_id=row[0],
            device_id=row[1],
            template_selection=json.loads(row[2] or "{}"),
            opened_at=_parse_ts(row[3]),
            closed=bool(row[4]),
            final_seq_count=row[5],
            closed_at=_parse_ts(row[6]) if row[6] else None,
            trace_id=row[7] or "",
        )

    def insert_segment(self, segment: SegmentRow) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_SEGMENT_TABLE} "
                "(session_id, session_seq, receipt_id, content_sha256, raw_ref, admitted_at, late) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    segment.session_id,
                    segment.session_seq,
                    segment.receipt_id,
                    segment.content_sha256,
                    segment.raw_ref,
                    _iso(segment.admitted_at),
                    1 if segment.late else 0,
                ),
            )
            return cur.rowcount == 1

    def get_segment(self, session_id: str, session_seq: int) -> Optional[SegmentRow]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT session_id, session_seq, receipt_id, content_sha256, raw_ref, "
                f"admitted_at, late FROM {_SEGMENT_TABLE} "
                "WHERE session_id = ? AND session_seq = ?",
                (session_id, session_seq),
            ).fetchone()
        return self._segment_from_row(row) if row else None

    def segments_for_session(self, session_id: str) -> List[SegmentRow]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT session_id, session_seq, receipt_id, content_sha256, raw_ref, "
                f"admitted_at, late FROM {_SEGMENT_TABLE} "
                "WHERE session_id = ? ORDER BY session_seq ASC",
                (session_id,),
            ).fetchall()
        return [self._segment_from_row(row) for row in rows]

    @staticmethod
    def _segment_from_row(row: tuple) -> SegmentRow:
        return SegmentRow(
            session_id=row[0],
            session_seq=int(row[1]),
            receipt_id=row[2],
            content_sha256=row[3],
            raw_ref=row[4] or "",
            admitted_at=_parse_ts(row[5]),
            late=bool(row[6]),
        )

    def insert_conflict(self, conflict: SegmentConflict) -> None:
        # Idempotent per logical conflict: a client retry loop re-presents the
        # same (pair, attempted hash) on every resend, and each retry re-enters
        # the conflict branch because its row never lands — without this guard
        # one logical conflict would grow the needs-attention list unboundedly.
        with self._connect() as conn:
            existing = conn.execute(
                f"SELECT 1 FROM {_CONFLICT_TABLE} WHERE session_id = ? AND "
                "session_seq = ? AND attempted_content_sha256 = ? LIMIT 1",
                (
                    conflict.session_id,
                    conflict.session_seq,
                    conflict.attempted_content_sha256,
                ),
            ).fetchone()
            if existing is not None:
                return
            conn.execute(
                f"INSERT INTO {_CONFLICT_TABLE} "
                "(session_id, session_seq, attempted_content_sha256, attempted_receipt_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    conflict.session_id,
                    conflict.session_seq,
                    conflict.attempted_content_sha256,
                    conflict.attempted_receipt_id,
                    _iso(conflict.recorded_at),
                ),
            )

    def conflicts_for_session(self, session_id: str) -> List[SegmentConflict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT session_id, session_seq, attempted_content_sha256, "
                f"attempted_receipt_id, recorded_at FROM {_CONFLICT_TABLE} "
                "WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [
            SegmentConflict(
                session_id=row[0],
                session_seq=int(row[1]),
                attempted_content_sha256=row[2],
                attempted_receipt_id=row[3] or "",
                recorded_at=_parse_ts(row[4]),
            )
            for row in rows
        ]


# ---------------------------------------------------------------------------
# Postgres backend (PDM; migration-owned, fail-loud preflight)
# ---------------------------------------------------------------------------


def _pg_connect() -> Any:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    for table in (_SESSION_TABLE, _SEGMENT_TABLE, _CONFLICT_TABLE):
        cur.execute("SELECT to_regclass(%s)", (table,))
        row = cur.fetchone()
        if not (row and row[0]):
            raise MeetingLedgerSchemaMissingError(f"Missing table '{table}'. {_MIGRATION_HINT}")


_PG_AUTOCREATE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_SESSION_TABLE} (
    session_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    template_selection JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed BOOLEAN NOT NULL DEFAULT false,
    final_seq_count INTEGER,
    closed_at TIMESTAMPTZ,
    trace_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS {_SEGMENT_TABLE} (
    session_id TEXT NOT NULL,
    session_seq INTEGER NOT NULL,
    receipt_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_ref TEXT NOT NULL DEFAULT '',
    admitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    late BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (session_id, session_seq)
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_segment_session_idx
    ON {_SEGMENT_TABLE} (session_id);
CREATE TABLE IF NOT EXISTS {_CONFLICT_TABLE} (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    session_seq INTEGER NOT NULL,
    attempted_content_sha256 TEXT NOT NULL,
    attempted_receipt_id TEXT NOT NULL DEFAULT '',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_segment_conflict_session_idx
    ON {_CONFLICT_TABLE} (session_id);
"""


class _PgLedgerStore:
    """Postgres-backed ledger store, mirroring `_SqliteLedgerStore` semantics."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            if _schema_autocreate_enabled():
                conn.cursor().execute(_PG_AUTOCREATE_DDL)
            else:
                _assert_pg_schema(conn)
        finally:
            conn.close()

    def open_session(self, session: MeetingSession) -> tuple[MeetingSession, bool]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO {_SESSION_TABLE} "
                "(session_id, device_id, template_selection, opened_at, trace_id) "
                "VALUES (%s, %s, %s::jsonb, %s, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (
                    session.session_id,
                    session.device_id,
                    json.dumps(session.template_selection),
                    session.opened_at,
                    session.trace_id,
                ),
            )
            created = cur.rowcount == 1
            existing = self._get_session(conn, session.session_id)
            if existing is None:
                raise MeetingLedgerPersistenceError(
                    f"session {session.session_id!r} was neither inserted nor readable"
                )
            return existing, created
        finally:
            conn.close()

    def close_session(
        self, session_id: str, final_seq_count: int, closed_at: datetime
    ) -> tuple[MeetingSession, bool]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"UPDATE {_SESSION_TABLE} SET closed = true, final_seq_count = %s, "
                "closed_at = %s WHERE session_id = %s AND closed = false",
                (final_seq_count, closed_at, session_id),
            )
            newly_closed = cur.rowcount == 1
            session = self._get_session(conn, session_id)
            if session is None:
                raise MeetingSessionNotFoundError(
                    f"session {session_id!r} is not in the ledger"
                )
            return session, newly_closed
        finally:
            conn.close()

    def get_session(self, session_id: str) -> Optional[MeetingSession]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            return self._get_session(conn, session_id)
        finally:
            conn.close()

    @staticmethod
    def _get_session(conn: Any, session_id: str) -> Optional[MeetingSession]:
        cur = conn.cursor()
        cur.execute(
            f"SELECT session_id, device_id, template_selection, opened_at, closed, "
            f"final_seq_count, closed_at, trace_id FROM {_SESSION_TABLE} "
            "WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        template = row[2]
        if not isinstance(template, dict):
            template = json.loads(template or "{}")
        return MeetingSession(
            session_id=row[0],
            device_id=row[1],
            template_selection=template,
            opened_at=_parse_ts(row[3]),
            closed=bool(row[4]),
            final_seq_count=row[5],
            closed_at=_parse_ts(row[6]) if row[6] else None,
            trace_id=row[7] or "",
        )

    def insert_segment(self, segment: SegmentRow) -> bool:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO {_SEGMENT_TABLE} "
                "(session_id, session_seq, receipt_id, content_sha256, raw_ref, admitted_at, late) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (session_id, session_seq) DO NOTHING",
                (
                    segment.session_id,
                    segment.session_seq,
                    segment.receipt_id,
                    segment.content_sha256,
                    segment.raw_ref,
                    segment.admitted_at,
                    segment.late,
                ),
            )
            return cur.rowcount == 1
        finally:
            conn.close()

    def get_segment(self, session_id: str, session_seq: int) -> Optional[SegmentRow]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT session_id, session_seq, receipt_id, content_sha256, raw_ref, "
                f"admitted_at, late FROM {_SEGMENT_TABLE} "
                "WHERE session_id = %s AND session_seq = %s",
                (session_id, session_seq),
            )
            row = cur.fetchone()
            return _SqliteLedgerStore._segment_from_row(row) if row else None
        finally:
            conn.close()

    def segments_for_session(self, session_id: str) -> List[SegmentRow]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT session_id, session_seq, receipt_id, content_sha256, raw_ref, "
                f"admitted_at, late FROM {_SEGMENT_TABLE} "
                "WHERE session_id = %s ORDER BY session_seq ASC",
                (session_id,),
            )
            return [_SqliteLedgerStore._segment_from_row(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def insert_conflict(self, conflict: SegmentConflict) -> None:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            # Same idempotency-per-logical-conflict guard as the SQLite lane.
            cur.execute(
                f"SELECT 1 FROM {_CONFLICT_TABLE} WHERE session_id = %s AND "
                "session_seq = %s AND attempted_content_sha256 = %s LIMIT 1",
                (
                    conflict.session_id,
                    conflict.session_seq,
                    conflict.attempted_content_sha256,
                ),
            )
            if cur.fetchone() is not None:
                return
            cur.execute(
                f"INSERT INTO {_CONFLICT_TABLE} "
                "(session_id, session_seq, attempted_content_sha256, attempted_receipt_id, recorded_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    conflict.session_id,
                    conflict.session_seq,
                    conflict.attempted_content_sha256,
                    conflict.attempted_receipt_id,
                    conflict.recorded_at,
                ),
            )
        finally:
            conn.close()

    def conflicts_for_session(self, session_id: str) -> List[SegmentConflict]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT session_id, session_seq, attempted_content_sha256, "
                f"attempted_receipt_id, recorded_at FROM {_CONFLICT_TABLE} "
                "WHERE session_id = %s ORDER BY id ASC",
                (session_id,),
            )
            return [
                SegmentConflict(
                    session_id=row[0],
                    session_seq=int(row[1]),
                    attempted_content_sha256=row[2],
                    attempted_receipt_id=row[3] or "",
                    recorded_at=_parse_ts(row[4]),
                )
                for row in cur.fetchall()
            ]
        finally:
            conn.close()


def _backend() -> "_SqliteLedgerStore | _PgLedgerStore":
    if resolve_heimdal_backend() == "pg":
        return _PgLedgerStore()
    return _SqliteLedgerStore(_sqlite_path())


# ---------------------------------------------------------------------------
# Event emission (same sink discipline as the admission seam)
# ---------------------------------------------------------------------------


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _emit_late_admitted_event(payload: Dict[str, Any], *, trace_id: str) -> None:
    """Emit `heimdal.meeting.segment.late_admitted` — the CDLM-06/08 re-derive trigger.

    Sink discipline mirrors `media_ingress._emit_admission_event`. Unlike the
    admission event, this one is *not* a precondition of any acknowledgement:
    the ledger row is the truth and downstream projections recompute from it,
    so a failed emission is logged loudly rather than unwinding a durable
    ledger update that already happened.
    """
    evt = make_outbox_event(
        event=LATE_ADMITTED_EVENT,
        source=_EVENT_SOURCE,
        payload=payload,
        trace_id=trace_id,
    )
    try:
        outbox_service.append_jsonl_outbox_event(
            _resolve_outbox_path(), evt, default_source=_EVENT_SOURCE
        )
    except Exception as exc:
        logger.error(
            "meeting ledger late-admitted event jsonl write failed trace_id=%s err=%s",
            trace_id,
            exc,
        )

    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend == "pg" or db_url:
        outbox_evt = outbox_service.coerce_outbox_event(evt, default_source=_EVENT_SOURCE)
        if outbox_evt is not None:
            try:
                outbox_service.write_outbox_event(
                    outbox_evt,
                    idempotency_key=outbox_service.derive_idempotency_key(
                        outbox_evt.event,
                        f"{payload.get('session_id', '')}\x1f{payload.get('session_seq', '')}",
                        str(payload.get("content_sha256", "")),
                    ),
                )
            except Exception as exc:
                logger.error(
                    "meeting ledger late-admitted event db outbox write failed "
                    "trace_id=%s err=%s",
                    trace_id,
                    exc,
                )


# ---------------------------------------------------------------------------
# Public ledger API
# ---------------------------------------------------------------------------


def open_meeting_session(
    *,
    session_id: str,
    device_id: str,
    template_selection: Optional[Dict[str, Any]] = None,
    trace_id: str = "",
) -> tuple[MeetingSession, bool]:
    """Open a session, idempotent by the client-minted ``session_id``.

    Returns ``(session, created)``. A re-post replays the *recorded* outcome —
    the stored session, whatever fields the replay carried — and never forks
    session state.
    """
    session_id = _validate_session_id(session_id)
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError(f"device_id must be a non-empty string, got {device_id!r}")
    session = MeetingSession(
        session_id=session_id,
        device_id=device_id.strip(),
        template_selection=dict(template_selection or {}),
        opened_at=_utcnow(),
        closed=False,
        final_seq_count=None,
        closed_at=None,
        trace_id=trace_id or "",
    )
    return _backend().open_session(session)


def close_meeting_session(
    *, session_id: str, final_seq_count: int
) -> tuple[MeetingSession, bool]:
    """Record the client's declared final segment count and close the session.

    Idempotent: a re-post replays the recorded close outcome unchanged —
    including the originally recorded ``final_seq_count``, even if the replay
    declared a different one; the first recorded close is the truth and
    sessions never fork or re-open. Returns ``(session, newly_closed)``.

    Raises :class:`MeetingSessionNotFoundError` for a session that was never
    opened: closing what was never opened would mint session state from a
    close, which is a fork.
    """
    session_id = _validate_session_id(session_id)
    if (
        isinstance(final_seq_count, bool)
        or not isinstance(final_seq_count, int)
        or final_seq_count < 0
        or final_seq_count > MAX_SESSION_SEQ
    ):
        raise ValueError(
            f"final_seq_count must be an integer in [0, {MAX_SESSION_SEQ}], "
            f"got {final_seq_count!r}"
        )
    store = _backend()
    if store.get_session(session_id) is None:
        raise MeetingSessionNotFoundError(f"session {session_id!r} is not in the ledger")
    return store.close_session(session_id, final_seq_count, _utcnow())


def get_meeting_session(session_id: str) -> Optional[MeetingSession]:
    """Read one session's recorded state, or None."""
    return _backend().get_session(_validate_session_id(session_id))


def record_segment_admission(
    *,
    session_id: str,
    session_seq: int,
    receipt_id: str,
    content_sha256: str,
    raw_ref: str = "",
    trace_id: str = "",
) -> SegmentOutcome:
    """Ledger one admitted segment; the production admission path's hook.

    Exactly one row exists per ``(session_id, session_seq)`` across idempotent
    replays (INV-CDLM-3). A *different* content hash for an existing pair fails
    closed: the original row is preserved, the conflict is recorded, and the
    gap report surfaces it as needs-attention.

    A new row landing in an already-**closed** session is a late admission: the
    row is flagged ``late``, `heimdal.meeting.segment.late_admitted` is
    emitted, and completeness is recomputed from the ledger — the session
    itself never re-opens.

    Admissions for sessions with no open record are still ledgered (a segment
    can outrace its session-open after a disconnect); the gap report requires
    the session record, so those rows become visible once the open arrives.
    """
    session_id = _validate_session_id(session_id)
    session_seq = _validate_seq(session_seq)
    store = _backend()

    existing = store.get_segment(session_id, session_seq)
    if existing is not None:
        if existing.content_sha256 == content_sha256:
            return SegmentOutcome(outcome=OUTCOME_REPLAY, late=False)
        store.insert_conflict(
            SegmentConflict(
                session_id=session_id,
                session_seq=session_seq,
                attempted_content_sha256=content_sha256,
                attempted_receipt_id=receipt_id,
                recorded_at=_utcnow(),
            )
        )
        logger.warning(
            "meeting ledger sequence conflict session_id=%s session_seq=%s: existing "
            "content %s, attempted %s; original preserved (fail closed).",
            session_id,
            session_seq,
            existing.content_sha256,
            content_sha256,
        )
        return SegmentOutcome(outcome=OUTCOME_CONFLICT, late=False)

    session = store.get_session(session_id)
    late = bool(session is not None and session.closed)
    created = store.insert_segment(
        SegmentRow(
            session_id=session_id,
            session_seq=session_seq,
            receipt_id=receipt_id,
            content_sha256=content_sha256,
            raw_ref=raw_ref or "",
            admitted_at=_utcnow(),
            late=late,
        )
    )
    if not created:
        # A concurrent admission won the insert between our read and write.
        racer = store.get_segment(session_id, session_seq)
        if racer is not None and racer.content_sha256 == content_sha256:
            return SegmentOutcome(outcome=OUTCOME_REPLAY, late=False)
        store.insert_conflict(
            SegmentConflict(
                session_id=session_id,
                session_seq=session_seq,
                attempted_content_sha256=content_sha256,
                attempted_receipt_id=receipt_id,
                recorded_at=_utcnow(),
            )
        )
        return SegmentOutcome(outcome=OUTCOME_CONFLICT, late=False)

    if late and session is not None:
        report = build_gap_report(session_id)
        _emit_late_admitted_event(
            {
                "session_id": session_id,
                "session_seq": session_seq,
                "receipt_id": receipt_id,
                "content_sha256": content_sha256,
                "complete": report["complete"],
                "missing": report["missing"],
            },
            trace_id=trace_id,
        )
    return SegmentOutcome(outcome=OUTCOME_RECORDED, late=late)


def build_gap_report(session_id: str) -> Dict[str, Any]:
    """The reconnect answer: received set, missing holes, close state, receipt refs.

    Missing sequence numbers are the holes below the declared final count once
    closed, or below the observed maximum while open (INV-CDLM-9). ``complete``
    flips only when the session is closed and the ledger actually covers every
    sequence in the declared count. Conflicted sequences appear under
    ``needs_attention`` — recorded, never resolved silently.

    Raises :class:`MeetingSessionNotFoundError` for an unknown session.
    """
    session_id = _validate_session_id(session_id)
    store = _backend()
    session = store.get_session(session_id)
    if session is None:
        raise MeetingSessionNotFoundError(f"session {session_id!r} is not in the ledger")

    segments = store.segments_for_session(session_id)
    received = sorted(row.session_seq for row in segments)
    received_set = set(received)

    if session.closed and session.final_seq_count is not None:
        expected = set(range(session.final_seq_count))
    elif received:
        expected = set(range(max(received) + 1))
    else:
        expected = set()
    missing = sorted(expected - received_set)

    complete = bool(
        session.closed
        and session.final_seq_count is not None
        and set(range(session.final_seq_count)) <= received_set
    )

    conflicts = store.conflicts_for_session(session_id)
    return {
        "session_id": session_id,
        "received": received,
        "missing": missing,
        "closed": session.closed,
        "complete": complete,
        "final_seq_count": session.final_seq_count,
        "segments": [
            {
                "seq": row.session_seq,
                "receipt_id": row.receipt_id,
                "content_sha256": row.content_sha256,
                "raw_ref": row.raw_ref,
                "late": row.late,
                "admitted_at": _iso(row.admitted_at),
            }
            for row in segments
        ],
        "needs_attention": [
            {
                "seq": conflict.session_seq,
                "reason": "sequence_content_conflict",
                "attempted_content_sha256": conflict.attempted_content_sha256,
                "attempted_receipt_id": conflict.attempted_receipt_id,
                "recorded_at": _iso(conflict.recorded_at),
            }
            for conflict in conflicts
        ],
    }


__all__ = [
    "LATE_ADMITTED_EVENT",
    "MAX_SESSION_SEQ",
    "OUTCOME_CONFLICT",
    "OUTCOME_RECORDED",
    "OUTCOME_REPLAY",
    "MeetingLedgerPersistenceError",
    "MeetingLedgerSchemaMissingError",
    "MeetingSession",
    "MeetingSessionNotFoundError",
    "SegmentConflict",
    "SegmentOutcome",
    "SegmentRow",
    "build_gap_report",
    "close_meeting_session",
    "get_meeting_session",
    "open_meeting_session",
    "record_segment_admission",
    "reset_process_meeting_ledger",
]
