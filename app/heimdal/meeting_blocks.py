"""Meeting block ownership model + fail-closed write guard (CDLM-07, issue #4387).

Specified by
`docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ENFORCE_MEETING_BLOCK_OWNERSHIP.md`
and bound by INV-CDLM-6: AI, reconciliation, template change, and finalization
never overwrite, merge, move, reorder, or normalize user notes — and any
ambiguity fails closed preserving user content. This module is the mechanical
form of "the AI can never touch your notes": an authority boundary, not a UI
promise.

The model: every meeting-page block carries `{block_id (stable, minted at
creation, never reused), owner ∈ {user, system}, type ∈ {user_note,
derived_projection, transcript_segment}, provenance, created_at, revised_at}`
in a durable per-session registry.

The guard: **one seam** — :func:`apply_block_write` — through which every block
mutation passes: user edits (the user-note endpoint), analysis revisions,
late-segment reconciliation, template re-render, and finalization (CDLM-08
consumes the same seam). Rules, all fail-closed:

- a `user_note` block is writable only by the user's editor identity
  (`WRITER_USER_EDITOR`); every derived writer is refused regardless of what
  `editor_identity` string it carries — the writer *kind* is structural, so a
  forged identity from a derived context cannot pass;
- a derived writer may create/revise/retire only `derived_projection` (or, for
  the ASR role, `transcript_segment`) blocks whose recorded provenance engine
  and role match its own; it may never move, renumber, merge, or reorder any
  block outside its provenance, even within derived types;
- a write naming an unknown `block_id`, an unknown owner/type, or a target
  whose recorded ownership conflicts with the writer is refused: content
  untouched, and a legible refusal `{who attempted, what target, why}` is
  durably recorded and surfaced as needs-attention on the projection read.

Editor identity is structural, not cryptographic, in this slice (client
contract gap F2 owns keys); it rides the existing provenance conventions and
is stated honestly as such.

Storage follows the CDLM-02/06 pattern: migration-owned Postgres tables
(`c9e4a1b6d3f5`) with fail-loud preflight, and a file-backed SQLite lane for
dev/test. `user_note` blocks are Human Knowledge Artifacts — their revisions
supersede content but preserve identity, position, and full edit history.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.heimdal._backend import resolve_heimdal_backend

logger = logging.getLogger(__name__)

_BLOCK_TABLE = "heimdal_meeting_block"
_NOTE_REVISION_TABLE = "heimdal_meeting_user_note_revision"
_REFUSAL_TABLE = "heimdal_meeting_block_refusal"

_MIGRATION_HINT = (
    "heimdal meeting-block schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/c9e4a1b6d3f5_heim_meeting_blocks_v0.py."
)

_BLOCKS_PATH_ENV = "HEIMDAL_MEETING_BLOCKS_PATH"

OWNER_USER = "user"
OWNER_SYSTEM = "system"
OWNERS = (OWNER_USER, OWNER_SYSTEM)

TYPE_USER_NOTE = "user_note"
TYPE_DERIVED_PROJECTION = "derived_projection"
TYPE_TRANSCRIPT_SEGMENT = "transcript_segment"
BLOCK_TYPES = (TYPE_USER_NOTE, TYPE_DERIVED_PROJECTION, TYPE_TRANSCRIPT_SEGMENT)

WRITER_USER_EDITOR = "user_editor"
WRITER_DERIVED = "derived"

# Structural provenance keys the guard derives from the writer identity; a
# caller-supplied `provenance_extra` can never override them (P1: allowing it
# would let a writer re-home a block under another writer's provenance or
# forge the user-editor kind).
_RESERVED_PROVENANCE_KEYS = frozenset({"kind", "engine", "role", "editor_identity"})

ACTION_CREATE = "create"
ACTION_REVISE = "revise"
ACTION_RETIRE = "retire"
ACTION_MOVE = "move"
_ACTIONS = (ACTION_CREATE, ACTION_REVISE, ACTION_RETIRE, ACTION_MOVE)


class MeetingBlockSchemaMissingError(RuntimeError):
    """Postgres backend selected but the block tables are absent (fail loud)."""


class MeetingBlockPersistenceError(RuntimeError):
    """A block write or read-back could not be completed durably."""


@dataclass(frozen=True)
class WriterIdentity:
    """Who is attempting a block write — the structural authority input.

    ``kind`` is the load-bearing field: ``user_editor`` is the one identity
    that may touch `user_note` blocks, and it is asserted by the user-note
    endpoint alone; every derived production path (analysis, reconciliation,
    template re-render, finalization, ASR) constructs a ``derived`` writer, so
    no string it carries can impersonate the user.
    """

    kind: str
    editor_identity: str = ""
    engine: str = ""
    role: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_provenance(self) -> Dict[str, Any]:
        if self.kind == WRITER_USER_EDITOR:
            return {"kind": self.kind, "editor_identity": self.editor_identity}
        return {
            "kind": self.kind,
            "engine": self.engine,
            "role": self.role,
            **{k: v for k, v in self.detail.items()},
        }


@dataclass(frozen=True)
class MeetingBlock:
    """One registered meeting-page block."""

    block_id: str
    session_id: str
    owner: str
    block_type: str
    provenance: Dict[str, Any]
    content: str
    position: int
    revision: int
    retired: bool
    created_at: datetime
    revised_at: datetime


@dataclass(frozen=True)
class BlockRefusal:
    """A recorded fail-closed refusal: who attempted, what target, why."""

    session_id: str
    block_id: str
    attempted_by: Dict[str, Any]
    action: str
    reason: str
    recorded_at: datetime


@dataclass(frozen=True)
class BlockWriteOutcome:
    """The guard's answer for one attempted mutation."""

    allowed: bool
    reason: str = ""
    block: Optional[MeetingBlock] = None
    replayed: bool = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# SQLite backend (dev/test lane — file-backed)
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_BLOCK_TABLE} (
    block_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    block_type TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT '{{}}',
    content TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    retired INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    revised_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_block_session_idx
    ON {_BLOCK_TABLE} (session_id);
CREATE TABLE IF NOT EXISTS {_NOTE_REVISION_TABLE} (
    note_block_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    text TEXT NOT NULL,
    editor_identity TEXT NOT NULL,
    written_at TEXT NOT NULL,
    PRIMARY KEY (note_block_id, revision)
);
CREATE TABLE IF NOT EXISTS {_REFUSAL_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    attempted_by TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_block_refusal_session_idx
    ON {_REFUSAL_TABLE} (session_id);
"""

_process_tmp_lock = threading.Lock()
_process_tmp_path: Optional[str] = None


def _sqlite_path() -> str:
    env_path = (os.environ.get(_BLOCKS_PATH_ENV) or "").strip()
    if env_path:
        return env_path
    global _process_tmp_path
    with _process_tmp_lock:
        if _process_tmp_path is None:
            fd, path = tempfile.mkstemp(prefix="heimdal-meeting-blocks-", suffix=".sqlite3")
            os.close(fd)
            _process_tmp_path = path
        return _process_tmp_path


def reset_process_meeting_blocks() -> None:
    """Test-only reset for the default (env-unset) per-process blocks file."""
    global _process_tmp_path
    with _process_tmp_lock:
        if _process_tmp_path is not None:
            try:
                Path(_process_tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            _process_tmp_path = None


class _SqliteBlockStore:
    def __init__(self, path: str) -> None:
        self._path = path
        with self._connect() as conn:
            conn.executescript(_SQLITE_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    _BLOCK_COLS = (
        "block_id, session_id, owner, block_type, provenance, content, position, "
        "revision, retired, created_at, revised_at"
    )

    def get_block(self, block_id: str) -> Optional[MeetingBlock]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._BLOCK_COLS} FROM {_BLOCK_TABLE} WHERE block_id = ?",
                (block_id,),
            ).fetchone()
        return self._block_from_row(row) if row else None

    def blocks_for_session(self, session_id: str) -> List[MeetingBlock]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._BLOCK_COLS} FROM {_BLOCK_TABLE} "
                "WHERE session_id = ? ORDER BY position ASC, block_id ASC",
                (session_id,),
            ).fetchall()
        return [self._block_from_row(row) for row in rows]

    def insert_block(self, block: MeetingBlock) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_BLOCK_TABLE} "
                "(block_id, session_id, owner, block_type, provenance, content, position, "
                "revision, retired, created_at, revised_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    block.block_id,
                    block.session_id,
                    block.owner,
                    block.block_type,
                    json.dumps(block.provenance),
                    block.content,
                    block.position,
                    block.revision,
                    1 if block.retired else 0,
                    _iso(block.created_at),
                    _iso(block.revised_at),
                ),
            )
            return cur.rowcount == 1

    def update_block(self, block: MeetingBlock) -> None:
        """Revise a block in place. Only the guard calls this, after authorization;
        identity fields (block_id, session_id, owner, block_type, created_at)
        never change — a revision supersedes content, not identity."""
        with self._connect() as conn:
            conn.execute(
                f"UPDATE {_BLOCK_TABLE} SET content = ?, position = ?, revision = ?, "
                "retired = ?, provenance = ?, revised_at = ? WHERE block_id = ?",
                (
                    block.content,
                    block.position,
                    block.revision,
                    1 if block.retired else 0,
                    json.dumps(block.provenance),
                    _iso(block.revised_at),
                    block.block_id,
                ),
            )

    @staticmethod
    def _block_from_row(row: tuple) -> MeetingBlock:
        return MeetingBlock(
            block_id=row[0],
            session_id=row[1],
            owner=row[2],
            block_type=row[3],
            provenance=json.loads(row[4] or "{}"),
            content=row[5] or "",
            position=int(row[6]),
            revision=int(row[7]),
            retired=bool(row[8]),
            created_at=_parse_ts(row[9]),
            revised_at=_parse_ts(row[10]),
        )

    def get_note_revision(self, note_block_id: str, revision: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT note_block_id, revision, text, editor_identity, written_at "
                f"FROM {_NOTE_REVISION_TABLE} WHERE note_block_id = ? AND revision = ?",
                (note_block_id, revision),
            ).fetchone()
        if row is None:
            return None
        return {
            "note_block_id": row[0],
            "revision": int(row[1]),
            "text": row[2],
            "editor_identity": row[3],
            "written_at": row[4],
        }

    def insert_note_revision(
        self, note_block_id: str, revision: int, text: str, editor_identity: str
    ) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {_NOTE_REVISION_TABLE} "
                "(note_block_id, revision, text, editor_identity, written_at) "
                "VALUES (?,?,?,?,?)",
                (note_block_id, revision, text, editor_identity, _iso(_utcnow())),
            )
            return cur.rowcount == 1

    def note_revisions(self, note_block_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT revision, text, editor_identity, written_at "
                f"FROM {_NOTE_REVISION_TABLE} WHERE note_block_id = ? ORDER BY revision ASC",
                (note_block_id,),
            ).fetchall()
        return [
            {
                "revision": int(r[0]),
                "text": r[1],
                "editor_identity": r[2],
                "written_at": r[3],
            }
            for r in rows
        ]

    def insert_refusal(self, refusal: BlockRefusal) -> None:
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO {_REFUSAL_TABLE} "
                "(session_id, block_id, attempted_by, action, reason, recorded_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    refusal.session_id,
                    refusal.block_id,
                    json.dumps(refusal.attempted_by),
                    refusal.action,
                    refusal.reason,
                    _iso(refusal.recorded_at),
                ),
            )

    def refusals_for_session(self, session_id: str) -> List[BlockRefusal]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT session_id, block_id, attempted_by, action, reason, recorded_at "
                f"FROM {_REFUSAL_TABLE} WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [
            BlockRefusal(
                session_id=r[0],
                block_id=r[1],
                attempted_by=json.loads(r[2] or "{}"),
                action=r[3],
                reason=r[4],
                recorded_at=_parse_ts(r[5]),
            )
            for r in rows
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
    for table in (_BLOCK_TABLE, _NOTE_REVISION_TABLE, _REFUSAL_TABLE):
        cur.execute("SELECT to_regclass(%s)", (table,))
        row = cur.fetchone()
        if not (row and row[0]):
            raise MeetingBlockSchemaMissingError(f"Missing table '{table}'. {_MIGRATION_HINT}")


_PG_AUTOCREATE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_BLOCK_TABLE} (
    block_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    block_type TEXT NOT NULL,
    provenance JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    content TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    retired BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revised_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_block_session_idx
    ON {_BLOCK_TABLE} (session_id);
CREATE TABLE IF NOT EXISTS {_NOTE_REVISION_TABLE} (
    note_block_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    text TEXT NOT NULL,
    editor_identity TEXT NOT NULL,
    written_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_block_id, revision)
);
CREATE TABLE IF NOT EXISTS {_REFUSAL_TABLE} (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    attempted_by JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS heimdal_meeting_block_refusal_session_idx
    ON {_REFUSAL_TABLE} (session_id);
"""


class _PgBlockStore:
    _BLOCK_COLS = _SqliteBlockStore._BLOCK_COLS

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            if _schema_autocreate_enabled():
                cur = conn.cursor()
                tables = (_BLOCK_TABLE, _NOTE_REVISION_TABLE, _REFUSAL_TABLE)
                cur.execute(
                    "SELECT " + ", ".join("to_regclass(%s)" for _ in tables),
                    tables,
                )
                existing = cur.fetchone()
                if existing and any(existing):
                    _assert_pg_schema(conn)
                else:
                    table_groups = ((_BLOCK_TABLE, (_PG_AUTOCREATE_DDL,)),)
                    for table_name, statements in table_groups:
                        cur.execute("SELECT to_regclass(%s)", (table_name,))
                        row = cur.fetchone()
                        table_present = bool(row and row[0])
                        if table_present:
                            continue
                        for statement in statements:
                            cur.execute(statement)
            else:
                _assert_pg_schema(conn)
        finally:
            conn.close()

    def get_block(self, block_id: str) -> Optional[MeetingBlock]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT {self._BLOCK_COLS} FROM {_BLOCK_TABLE} WHERE block_id = %s",
                (block_id,),
            )
            row = cur.fetchone()
            return self._block_from_row(row) if row else None
        finally:
            conn.close()

    def blocks_for_session(self, session_id: str) -> List[MeetingBlock]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT {self._BLOCK_COLS} FROM {_BLOCK_TABLE} "
                "WHERE session_id = %s ORDER BY position ASC, block_id ASC",
                (session_id,),
            )
            return [self._block_from_row(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def insert_block(self, block: MeetingBlock) -> bool:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO {_BLOCK_TABLE} "
                "(block_id, session_id, owner, block_type, provenance, content, position, "
                "revision, retired, created_at, revised_at) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (block_id) DO NOTHING",
                (
                    block.block_id,
                    block.session_id,
                    block.owner,
                    block.block_type,
                    json.dumps(block.provenance),
                    block.content,
                    block.position,
                    block.revision,
                    block.retired,
                    block.created_at,
                    block.revised_at,
                ),
            )
            return cur.rowcount == 1
        finally:
            conn.close()

    def update_block(self, block: MeetingBlock) -> None:
        conn = _pg_connect()
        try:
            conn.cursor().execute(
                f"UPDATE {_BLOCK_TABLE} SET content = %s, position = %s, revision = %s, "
                "retired = %s, provenance = %s::jsonb, revised_at = %s WHERE block_id = %s",
                (
                    block.content,
                    block.position,
                    block.revision,
                    block.retired,
                    json.dumps(block.provenance),
                    block.revised_at,
                    block.block_id,
                ),
            )
        finally:
            conn.close()

    @staticmethod
    def _block_from_row(row: tuple) -> MeetingBlock:
        def _as_obj(value: Any) -> Dict[str, Any]:
            if isinstance(value, dict):
                return value
            return json.loads(value) if value else {}

        return MeetingBlock(
            block_id=row[0],
            session_id=row[1],
            owner=row[2],
            block_type=row[3],
            provenance=_as_obj(row[4]),
            content=row[5] or "",
            position=int(row[6]),
            revision=int(row[7]),
            retired=bool(row[8]),
            created_at=_parse_ts(row[9]),
            revised_at=_parse_ts(row[10]),
        )

    def get_note_revision(self, note_block_id: str, revision: int) -> Optional[Dict[str, Any]]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT note_block_id, revision, text, editor_identity, written_at "
                f"FROM {_NOTE_REVISION_TABLE} WHERE note_block_id = %s AND revision = %s",
                (note_block_id, revision),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "note_block_id": row[0],
                "revision": int(row[1]),
                "text": row[2],
                "editor_identity": row[3],
                "written_at": _iso(_parse_ts(row[4])),
            }
        finally:
            conn.close()

    def insert_note_revision(
        self, note_block_id: str, revision: int, text: str, editor_identity: str
    ) -> bool:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO {_NOTE_REVISION_TABLE} "
                "(note_block_id, revision, text, editor_identity) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (note_block_id, revision) DO NOTHING",
                (note_block_id, revision, text, editor_identity),
            )
            return cur.rowcount == 1
        finally:
            conn.close()

    def note_revisions(self, note_block_id: str) -> List[Dict[str, Any]]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT revision, text, editor_identity, written_at "
                f"FROM {_NOTE_REVISION_TABLE} WHERE note_block_id = %s ORDER BY revision ASC",
                (note_block_id,),
            )
            return [
                {
                    "revision": int(r[0]),
                    "text": r[1],
                    "editor_identity": r[2],
                    "written_at": _iso(_parse_ts(r[3])),
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def insert_refusal(self, refusal: BlockRefusal) -> None:
        conn = _pg_connect()
        try:
            conn.cursor().execute(
                f"INSERT INTO {_REFUSAL_TABLE} "
                "(session_id, block_id, attempted_by, action, reason, recorded_at) "
                "VALUES (%s,%s,%s::jsonb,%s,%s,%s)",
                (
                    refusal.session_id,
                    refusal.block_id,
                    json.dumps(refusal.attempted_by),
                    refusal.action,
                    refusal.reason,
                    refusal.recorded_at,
                ),
            )
        finally:
            conn.close()

    def refusals_for_session(self, session_id: str) -> List[BlockRefusal]:
        conn = _pg_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT session_id, block_id, attempted_by, action, reason, recorded_at "
                f"FROM {_REFUSAL_TABLE} WHERE session_id = %s ORDER BY id ASC",
                (session_id,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        def _as_obj(value: Any) -> Dict[str, Any]:
            if isinstance(value, dict):
                return value
            return json.loads(value) if value else {}

        return [
            BlockRefusal(
                session_id=r[0],
                block_id=r[1],
                attempted_by=_as_obj(r[2]),
                action=r[3],
                reason=r[4],
                recorded_at=_parse_ts(r[5]),
            )
            for r in rows
        ]


def _backend() -> "_SqliteBlockStore | _PgBlockStore":
    if resolve_heimdal_backend() == "pg":
        return _PgBlockStore()
    return _SqliteBlockStore(_sqlite_path())


# ---------------------------------------------------------------------------
# The ownership guard — the one seam every block mutation passes through
# ---------------------------------------------------------------------------


def _refuse(
    store: "_SqliteBlockStore | _PgBlockStore",
    *,
    session_id: str,
    block_id: str,
    writer: WriterIdentity,
    action: str,
    reason: str,
) -> BlockWriteOutcome:
    refusal = BlockRefusal(
        session_id=session_id,
        block_id=block_id,
        attempted_by=writer.as_provenance(),
        action=action,
        reason=reason,
        recorded_at=_utcnow(),
    )
    try:
        store.insert_refusal(refusal)
    except Exception as exc:
        # The refusal itself must still be the outcome even if it cannot be
        # recorded; content preservation never depends on the audit write.
        logger.error(
            "meeting block refusal could not be recorded session=%s block=%s: %s",
            session_id,
            block_id,
            exc,
        )
    logger.warning(
        "meeting block write refused session=%s block=%s action=%s writer=%s: %s",
        session_id,
        block_id,
        action,
        writer.as_provenance(),
        reason,
    )
    return BlockWriteOutcome(allowed=False, reason=reason)


def _authorize_target(
    writer: WriterIdentity, block: MeetingBlock, session_id: str
) -> Optional[str]:
    """Authorize ``writer`` against an existing block; None means authorized,
    otherwise the refusal reason. One function so no path (revise, retire,
    move, create-replay, race-loser replay) can skip a check the others run."""
    if block.session_id != session_id:
        return "block belongs to a different session (ownership conflict)"
    if block.owner not in OWNERS or block.block_type not in BLOCK_TYPES:
        return (
            f"recorded ownership is unknown (owner={block.owner!r}, "
            f"type={block.block_type!r}); failing closed"
        )
    if block.block_type == TYPE_USER_NOTE:
        if writer.kind != WRITER_USER_EDITOR:
            return "derived writers never touch user_note blocks (INV-CDLM-6)"
        recorded_identity = (block.provenance or {}).get("editor_identity", "")
        if not writer.editor_identity.strip() or (
            recorded_identity and writer.editor_identity != recorded_identity
        ):
            return "editor identity does not match the note's recorded editor"
        return None
    if writer.kind != WRITER_DERIVED or not _derived_owns(writer, block):
        return (
            "writer provenance does not own this block "
            "(derived writers are confined to their own provenance)"
        )
    return None


def _derived_owns(writer: WriterIdentity, block: MeetingBlock) -> bool:
    """A derived writer owns exactly the blocks whose recorded provenance
    carries its engine and role — never anything broader."""
    prov = block.provenance or {}
    return (
        prov.get("kind") == WRITER_DERIVED
        and prov.get("engine") == writer.engine
        and prov.get("role") == writer.role
        and bool(writer.engine)
    )


def apply_block_write(
    *,
    session_id: str,
    writer: WriterIdentity,
    action: str,
    block_id: str,
    block_type: Optional[str] = None,
    content: str = "",
    position: Optional[int] = None,
    provenance_extra: Optional[Dict[str, Any]] = None,
    verify_only: bool = False,
) -> BlockWriteOutcome:
    """The shared block-write guard. Every mutation goes through here.

    Fail-closed by construction: only explicitly authorized combinations fall
    through to a write; everything else — unknown action, unknown type, unknown
    target, ownership conflict, identity mismatch — refuses, preserves the
    existing content byte-for-byte, and records a legible refusal.
    """
    if not isinstance(block_id, str) or not block_id.strip():
        raise ValueError("block_id must be a non-empty string")
    store = _backend()

    if action not in _ACTIONS:
        return _refuse(
            store,
            session_id=session_id,
            block_id=block_id,
            writer=writer,
            action=str(action),
            reason=f"unknown action {action!r}",
        )
    if writer.kind not in (WRITER_USER_EDITOR, WRITER_DERIVED):
        return _refuse(
            store,
            session_id=session_id,
            block_id=block_id,
            writer=writer,
            action=action,
            reason=f"unknown writer kind {writer.kind!r}",
        )

    existing = store.get_block(block_id)

    if action == ACTION_CREATE:
        if verify_only and existing is None:
            # A probe never writes — on any branch. Creating on a free id is
            # authorized purely by writer kind/type rules, checked below via a
            # dry evaluation with no insert.
            if block_type not in BLOCK_TYPES:
                return _refuse(
                    store,
                    session_id=session_id,
                    block_id=block_id,
                    writer=writer,
                    action=action,
                    reason=f"unknown block type {block_type!r}",
                )
            if block_type == TYPE_USER_NOTE:
                if writer.kind != WRITER_USER_EDITOR or not writer.editor_identity.strip():
                    return _refuse(
                        store,
                        session_id=session_id,
                        block_id=block_id,
                        writer=writer,
                        action=action,
                        reason="user_note blocks are writable only by the user's editor "
                        "identity (INV-CDLM-6)",
                    )
            elif writer.kind != WRITER_DERIVED or not writer.engine:
                return _refuse(
                    store,
                    session_id=session_id,
                    block_id=block_id,
                    writer=writer,
                    action=action,
                    reason=f"{block_type} blocks are created only by derived writers "
                    "with engine provenance",
                )
            elif block_type == TYPE_TRANSCRIPT_SEGMENT and writer.role != "asr":
                # The dry evaluation must refuse everything the real create
                # refuses — a probe that authorizes what the write path would
                # refuse breaks the fail-closed contract.
                return _refuse(
                    store,
                    session_id=session_id,
                    block_id=block_id,
                    writer=writer,
                    action=action,
                    reason="transcript_segment blocks are created only by the ASR "
                    "derivation (CDLM-06)",
                )
            return BlockWriteOutcome(allowed=True)
        if existing is not None:
            # A create landing on an existing block is a replay only when the
            # writer would also be AUTHORIZED for that block and the identity
            # and content match — authorization is never skipped on replay
            # (otherwise a derived writer could collect success acks against
            # user notes, or a foreign editor against another's note).
            auth_refusal = _authorize_target(writer, existing, session_id)
            if auth_refusal is not None:
                return _refuse(
                    store,
                    session_id=session_id,
                    block_id=block_id,
                    writer=writer,
                    action=action,
                    reason=auth_refusal,
                )
            if existing.block_type == (block_type or "") and existing.content == content:
                return BlockWriteOutcome(allowed=True, block=existing, replayed=True)
            return _refuse(
                store,
                session_id=session_id,
                block_id=block_id,
                writer=writer,
                action=action,
                reason="block_id already exists with different identity or content "
                "(block ids are never reused)",
            )
        if block_type not in BLOCK_TYPES:
            return _refuse(
                store,
                session_id=session_id,
                block_id=block_id,
                writer=writer,
                action=action,
                reason=f"unknown block type {block_type!r}",
            )
        if block_type == TYPE_USER_NOTE:
            if writer.kind != WRITER_USER_EDITOR or not writer.editor_identity.strip():
                return _refuse(
                    store,
                    session_id=session_id,
                    block_id=block_id,
                    writer=writer,
                    action=action,
                    reason="user_note blocks are writable only by the user's editor "
                    "identity (INV-CDLM-6)",
                )
            owner = OWNER_USER
        else:
            if writer.kind != WRITER_DERIVED or not writer.engine:
                return _refuse(
                    store,
                    session_id=session_id,
                    block_id=block_id,
                    writer=writer,
                    action=action,
                    reason=f"{block_type} blocks are created only by derived writers "
                    "with engine provenance",
                )
            if block_type == TYPE_TRANSCRIPT_SEGMENT and writer.role != "asr":
                return _refuse(
                    store,
                    session_id=session_id,
                    block_id=block_id,
                    writer=writer,
                    action=action,
                    reason="transcript_segment blocks are created only by the ASR "
                    "derivation (CDLM-06)",
                )
            owner = OWNER_SYSTEM
        provenance = writer.as_provenance()
        if provenance_extra:
            provenance = {
                **provenance,
                **{
                    k: v
                    for k, v in provenance_extra.items()
                    if k not in _RESERVED_PROVENANCE_KEYS
                },
            }
        now = _utcnow()
        block = MeetingBlock(
            block_id=block_id,
            session_id=session_id,
            owner=owner,
            block_type=block_type,
            provenance=provenance,
            content=content,
            position=position if position is not None else 0,
            revision=1,
            retired=False,
            created_at=now,
            revised_at=now,
        )
        created = store.insert_block(block)
        if not created:
            racer = store.get_block(block_id)
            if (
                racer is not None
                and _authorize_target(writer, racer, session_id) is None
                and racer.block_type == block_type
                and racer.content == content
            ):
                return BlockWriteOutcome(allowed=True, block=racer, replayed=True)
            return _refuse(
                store,
                session_id=session_id,
                block_id=block_id,
                writer=writer,
                action=action,
                reason="block_id was concurrently minted with different content",
            )
        return BlockWriteOutcome(allowed=True, block=block)

    # revise / retire / move — the target must exist and belong to this writer.
    if existing is None:
        return _refuse(
            store,
            session_id=session_id,
            block_id=block_id,
            writer=writer,
            action=action,
            reason="unknown block_id (fail closed: nothing was written)",
        )
    auth_refusal = _authorize_target(writer, existing, session_id)
    if auth_refusal is not None:
        return _refuse(
            store,
            session_id=session_id,
            block_id=block_id,
            writer=writer,
            action=action,
            reason=auth_refusal,
        )

    # An authorization probe never writes: `verify_only` stops here after the
    # full check chain, so a replay-acknowledgement path can prove the writer
    # is entitled to the block without any race being able to turn the probe
    # into a mutation.
    if verify_only:
        return BlockWriteOutcome(allowed=True, block=existing, replayed=True)

    # Same-content revise is a replay: fully authorized above, nothing to
    # write, no revision bump — this is how idempotent resends stay
    # authorization-checked without double-counting.
    if (
        action == ACTION_REVISE
        and content == existing.content
        and (position is None or position == existing.position)
    ):
        return BlockWriteOutcome(allowed=True, block=existing, replayed=True)

    now = _utcnow()
    if action == ACTION_MOVE:
        revised = MeetingBlock(
            block_id=existing.block_id,
            session_id=existing.session_id,
            owner=existing.owner,
            block_type=existing.block_type,
            provenance=existing.provenance,
            content=existing.content,
            position=position if position is not None else existing.position,
            revision=existing.revision,
            retired=existing.retired,
            created_at=existing.created_at,
            revised_at=now,
        )
    elif action == ACTION_RETIRE:
        revised = MeetingBlock(
            block_id=existing.block_id,
            session_id=existing.session_id,
            owner=existing.owner,
            block_type=existing.block_type,
            provenance=existing.provenance,
            content=existing.content,
            position=existing.position,
            revision=existing.revision,
            retired=True,
            created_at=existing.created_at,
            revised_at=now,
        )
    else:  # revise
        provenance = existing.provenance
        if provenance_extra:
            provenance = {
                **provenance,
                **{
                    k: v
                    for k, v in provenance_extra.items()
                    if k not in _RESERVED_PROVENANCE_KEYS
                },
            }
        revised = MeetingBlock(
            block_id=existing.block_id,
            session_id=existing.session_id,
            owner=existing.owner,
            block_type=existing.block_type,
            provenance=provenance,
            content=content,
            position=existing.position if position is None else position,
            revision=existing.revision + 1,
            retired=existing.retired,
            created_at=existing.created_at,
            revised_at=now,
        )
    store.update_block(revised)
    return BlockWriteOutcome(allowed=True, block=revised)


# ---------------------------------------------------------------------------
# Read + audit surfaces
# ---------------------------------------------------------------------------


def get_block(block_id: str) -> Optional[MeetingBlock]:
    return _backend().get_block(block_id)


def blocks_for_session(session_id: str) -> List[MeetingBlock]:
    return _backend().blocks_for_session(session_id)


def refusals_for_session(session_id: str) -> List[Dict[str, Any]]:
    """Refusals as needs-attention entries for the projection read."""
    return [
        {
            "block_id": refusal.block_id,
            "reason": "block_write_refused",
            "refusal": refusal.reason,
            "action": refusal.action,
            "attempted_by": refusal.attempted_by,
            "recorded_at": _iso(refusal.recorded_at),
        }
        for refusal in _backend().refusals_for_session(session_id)
    ]


def get_note_revision(note_block_id: str, revision: int) -> Optional[Dict[str, Any]]:
    return _backend().get_note_revision(note_block_id, revision)


def insert_note_revision(
    note_block_id: str, revision: int, text: str, editor_identity: str
) -> bool:
    return _backend().insert_note_revision(note_block_id, revision, text, editor_identity)


def note_revisions(note_block_id: str) -> List[Dict[str, Any]]:
    return _backend().note_revisions(note_block_id)


__all__ = [
    "ACTION_CREATE",
    "ACTION_MOVE",
    "ACTION_RETIRE",
    "ACTION_REVISE",
    "BLOCK_TYPES",
    "OWNER_SYSTEM",
    "OWNER_USER",
    "TYPE_DERIVED_PROJECTION",
    "TYPE_TRANSCRIPT_SEGMENT",
    "TYPE_USER_NOTE",
    "WRITER_DERIVED",
    "WRITER_USER_EDITOR",
    "BlockRefusal",
    "BlockWriteOutcome",
    "MeetingBlock",
    "MeetingBlockPersistenceError",
    "MeetingBlockSchemaMissingError",
    "WriterIdentity",
    "apply_block_write",
    "blocks_for_session",
    "get_block",
    "get_note_revision",
    "note_revisions",
    "refusals_for_session",
    "reset_process_meeting_blocks",
]
