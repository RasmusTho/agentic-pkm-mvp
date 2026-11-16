"""Read the exact #6561 Codex session relations from the local Codex host.

This is a Builder-host observation, not a Vault or dispatcher data source, and
not a writer fence or lifecycle authority. The only permitted database and
identities are the local Codex state file and the two named sessions below.
"""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
from typing import TypedDict
from uuid import UUID

CHILD = "01a19b1d-7671-7f43-a053-77db65ac7dfb"
PARENT = "01a18113-fbc7-79e1-813f-bb54a5f7d59c"
STATE_DB = Path.home() / ".codex/state_5.sqlite"
CHILD_JOURNAL = Path.home() / ".codex/sessions/2026/11/02/rollout-2026-11-02T08-16-01-01a19b1d-7671-7f43-a053-77db65ac7dfb.jsonl"
PARENT_JOURNAL = Path.home() / ".codex/sessions/2026/10/28/rollout-2026-10-28T06-55-32-01a18113-fbc7-79e1-813f-bb54a5f7d59c.jsonl"
_MAX_CHILDREN = 4096


class RelationsUnavailable(ValueError):
    """The qualified Codex source or its exact relations are unknown."""


class RelationSnapshot(TypedDict):
    source: str
    parent: str
    child: str
    child_rollout: str
    parent_rollout: str
    child_thread_source: str
    registered_children: list[str]


def _regular(path: Path, *, required: bool) -> tuple[int, int] | None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        if not required:
            return None
        raise RelationsUnavailable("UNKNOWN: Codex state source is missing") from None
    except OSError as exc:
        raise RelationsUnavailable("UNKNOWN: Codex state source is unavailable") from exc
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022):
        raise RelationsUnavailable("UNKNOWN: Codex state source is unqualified")
    return metadata.st_dev, metadata.st_ino


def _source_identity() -> tuple[tuple[int, int], tuple[int, int] | None, tuple[int, int] | None]:
    try:
        directory = os.lstat(STATE_DB.parent)
        if (not STATE_DB.is_absolute() or not stat.S_ISDIR(directory.st_mode)
                or directory.st_uid != os.getuid() or directory.st_mode & 0o022):
            raise RelationsUnavailable("UNKNOWN: Codex state directory is unqualified")
        main = _regular(STATE_DB, required=True)
        wal = _regular(Path(str(STATE_DB) + "-wal"), required=False)
        shm = _regular(Path(str(STATE_DB) + "-shm"), required=False)
        if main is None or (wal is not None and shm is None):
            raise RelationsUnavailable("UNKNOWN: Codex WAL snapshot cannot be read safely")
        fd = os.open(STATE_DB, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            header = os.read(fd, 100)
            if ((opened.st_dev, opened.st_ino) != main or len(header) != 100
                    or header[:16] != b"SQLite format 3\x00" or header[18:20] not in (b"\x01\x01", b"\x02\x02")):
                raise RelationsUnavailable("UNKNOWN: Codex state header or identity is unqualified")
            # A WAL database without its existing sidecars could cause SQLite
            # to create shared state merely to read it; refuse that case.
            if header[18:20] == b"\x02\x02" and (wal is None or shm is None):
                raise RelationsUnavailable("UNKNOWN: Codex WAL sidecars are unavailable")
            if header[18:20] == b"\x01\x01" and (wal is not None or shm is not None):
                raise RelationsUnavailable("UNKNOWN: unexpected Codex WAL sidecar")
        finally:
            os.close(fd)
        return main, wal, shm
    except OSError as exc:
        raise RelationsUnavailable("UNKNOWN: Codex state directory is unavailable") from exc


def _schema(db: sqlite3.Connection) -> None:
    # Reject views, virtual tables, or absent/misidentified primary keys. Extra
    # Codex-owned columns may coexist; only these exact relations are queried.
    for name, (columns, pragma) in {
        "threads": ({"id": ("TEXT", 0, 1), "rollout_path": ("TEXT", 1, 0), "thread_source": ("TEXT", 0, 0)},
                    "PRAGMA table_info(threads)"),
        "thread_spawn_edges": ({"parent_thread_id": ("TEXT", 1, 0), "child_thread_id": ("TEXT", 1, 1),
                                "status": ("TEXT", 1, 0)}, "PRAGMA table_info(thread_spawn_edges)"),
    }.items():
        row = db.execute("SELECT type, sql FROM sqlite_master WHERE name=?", (name,)).fetchall()
        if (len(row) != 1 or row[0][0] != "table" or not isinstance(row[0][1], str)
                or not row[0][1].lstrip().upper().startswith("CREATE TABLE")):
            raise RelationsUnavailable("UNKNOWN: Codex relation schema is unqualified")
        actual = {column[1]: (str(column[2]).upper(), column[3], column[5])
                  for column in db.execute(pragma).fetchall()}
        if any(actual.get(column) != expected for column, expected in columns.items()):
            raise RelationsUnavailable("UNKNOWN: Codex relation schema changed")


def _authorize(action: int, first: str | None, second: str | None,
               database: str | None, trigger: str | None) -> int:
    """Forbid writes and access outside the two named Codex metadata tables."""
    if trigger is not None:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and first == "table_info" and second in {"threads", "thread_spawn_edges"}:
        return sqlite3.SQLITE_OK
    allowed = {"sqlite_master": {"name", "type", "sql"},
               "threads": {"id", "rollout_path", "thread_source"},
               "thread_spawn_edges": {"parent_thread_id", "child_thread_id"}}
    if action == sqlite3.SQLITE_READ and database == "main" and first in allowed and second in allowed[first]:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def read_6561() -> RelationSnapshot:
    """Read one transactional, target-only projection; never create or mutate DB state."""
    before = _source_identity()
    try:
        with closing(sqlite3.connect(STATE_DB.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("BEGIN")
            db.set_authorizer(_authorize)
            _schema(db)
            child = db.execute("SELECT id, rollout_path, thread_source FROM threads WHERE id=?", (CHILD,)).fetchall()
            parent = db.execute("SELECT id, rollout_path FROM threads WHERE id=?", (PARENT,)).fetchall()
            upstream = db.execute("SELECT parent_thread_id FROM thread_spawn_edges WHERE child_thread_id=?", (CHILD,)).fetchall()
            children = db.execute("SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=? "
                                  "ORDER BY child_thread_id LIMIT ?", (CHILD, _MAX_CHILDREN + 1)).fetchall()
            if (child != [(CHILD, str(CHILD_JOURNAL), "subagent")]
                    or parent != [(PARENT, str(PARENT_JOURNAL))] or upstream != [(PARENT,)]):
                raise RelationsUnavailable("UNKNOWN: Codex parent or child identity changed")
            if len(children) > _MAX_CHILDREN:
                raise RelationsUnavailable("UNKNOWN: Codex child relation list is too large")
            ids = []
            for row in children:
                value = row[0]
                if not isinstance(value, str) or str(UUID(value)) != value:
                    raise RelationsUnavailable("UNKNOWN: malformed registered child identity")
                ids.append(value)
            if len(set(ids)) != len(ids):
                raise RelationsUnavailable("UNKNOWN: duplicate registered child identity")
            if _source_identity() != before:
                raise RelationsUnavailable("UNKNOWN: Codex state source identity changed")
            return {"source": str(STATE_DB), "parent": PARENT, "child": CHILD,
                    "child_rollout": str(CHILD_JOURNAL), "parent_rollout": str(PARENT_JOURNAL),
                    "child_thread_source": "subagent", "registered_children": ids}
    except (sqlite3.Error, ValueError, OSError) as exc:
        if isinstance(exc, RelationsUnavailable):
            raise
        raise RelationsUnavailable("UNKNOWN: Codex relations are unavailable or malformed") from exc
