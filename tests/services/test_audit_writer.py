"""Tests for #2600: audit writer INSERT schema fix.

AC1 — end-to-end privileged action writes ≥1 audit row on a real pg:
    test_audit_row_written_on_action  (pytest.mark.pg)
    test_audit_row_written_for_object_scoped_action  (pytest.mark.pg) — the real
        promotion-gate path: object_id present in store_objects but NOT in the
        FK-referenced `objects` table; row must still be written with a NULL
        object_id and the original id preserved in details.object_ref.

AC2 — forced INSERT failure logs ERROR and does NOT abort the calling action:
    test_audit_insert_failure_logs_error_non_fatal  (not pg — monkeypatched)

AC3 — writer column list matches migration schema:
    test_audit_columns_match_migration  (not pg — structural check)

FK-fallback unit coverage (not pg — monkeypatched):
    test_audit_object_fk_violation_falls_back_to_null_object_id
"""

from __future__ import annotations

import inspect
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from psycopg import IntegrityError

import app.services.audit as audit_module
from app.services.audit import audit_event


# ---------------------------------------------------------------------------
# AC1 — real Postgres (pytest.mark.pg)
# ---------------------------------------------------------------------------

@pytest.mark.pg
def test_audit_row_written_on_action() -> None:
    """An audit_event call against a live pg writes at least one audit row.

    Requires a running Postgres on the default local DSN
    (postgresql://app:app@127.0.0.1:15432/app) — skip or xfail if the DB is
    unreachable.  The default_pg_dsn_for_pg_tests fixture in conftest.py sets
    DATABASE_URL automatically for pg-marked tests.
    """
    import os  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    from app.db.db import conn_rw  # noqa: PLC0415

    test_trace_id = f"test-ac1-{uuid.uuid4()}"

    # Ensure audit_event sees the pg backend
    os.environ["STORE_BACKEND"] = "pg"

    try:
        audit_event(
            event="test.ac1.write",
            object_id=None,
            agent="test-audit-writer",
            trace_id=test_trace_id,
            extra={"purpose": "AC1 audit-row-written test"},
        )
    except Exception as exc:
        pytest.fail(f"audit_event raised unexpectedly: {exc}")

    # Query the row back
    try:
        with conn_rw(connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, agent, action, trace_id, details "
                    "FROM audit WHERE trace_id = %s",
                    (test_trace_id,),
                )
                rows = cur.fetchall()
    except Exception as exc:
        pytest.fail(f"Could not query audit table: {exc}")

    assert len(rows) >= 1, (
        f"Expected at least 1 audit row for trace_id={test_trace_id!r}; got 0. "
        "The INSERT schema may still be wrong or the commit was not flushed."
    )
    row = rows[0]
    assert row["agent"] == "test-audit-writer"
    assert row["action"] == "test.ac1.write"
    assert row["trace_id"] == test_trace_id


@pytest.mark.pg
def test_audit_row_written_for_object_scoped_action() -> None:
    """The real promotion-gate path: an object-scoped audit row is still written.

    The `audit.object_id` FK references the legacy `objects` table, but the
    active object store (`PgObjectStore`) writes to `store_objects`. A real
    object-scoped audit call (e.g. `promotion-gate` with `object_id=str(oid)`)
    therefore carries an id that exists in `store_objects` but not in `objects`,
    which would raise an FK violation. The writer must fall back to a NULL
    object_id and preserve the original id in `details.object_ref` so a row IS
    written.

    Requires a live pg with pgvector (the migration creates a `vector`-typed
    column).
    """
    import os  # noqa: PLC0415
    import uuid  # noqa: PLC0415

    from app.db.db import conn_rw  # noqa: PLC0415

    # A UUID that is (overwhelmingly) NOT present in the `objects` table.
    orphan_object_id = str(uuid.uuid4())
    test_trace_id = f"test-ac1-objscoped-{uuid.uuid4()}"

    os.environ["STORE_BACKEND"] = "pg"

    try:
        audit_event(
            event="test.ac1.object_scoped",
            object_id=orphan_object_id,
            agent="promotion-gate",
            trace_id=test_trace_id,
            extra={"reason": "AC1 object-scoped FK-fallback test"},
        )
    except Exception as exc:
        pytest.fail(f"audit_event raised unexpectedly for object-scoped call: {exc}")

    try:
        with conn_rw(connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, object_id, agent, action, trace_id, details "
                    "FROM audit WHERE trace_id = %s",
                    (test_trace_id,),
                )
                rows = cur.fetchall()
    except Exception as exc:
        pytest.fail(f"Could not query audit table: {exc}")

    assert len(rows) >= 1, (
        f"Expected at least 1 audit row for object-scoped trace_id={test_trace_id!r}; "
        "got 0. The FK-fallback retry may be missing — the FK violation dropped the row."
    )
    row = rows[0]
    assert row["agent"] == "promotion-gate"
    assert row["action"] == "test.ac1.object_scoped"
    # FK could not be satisfied → object_id written as NULL.
    assert row["object_id"] is None, (
        "Expected object_id NULL after FK fallback (the id is not in `objects`), "
        f"got {row['object_id']!r}"
    )
    # Original id preserved in details so the audit trail is not lossy.
    details = row["details"]
    if isinstance(details, str):
        import json as _json  # noqa: PLC0415

        details = _json.loads(details)
    assert details.get("object_ref") == orphan_object_id, (
        "Expected the original object_id preserved in details.object_ref, "
        f"got {details.get('object_ref')!r}"
    )


# ---------------------------------------------------------------------------
# AC2 — forced INSERT failure logs ERROR, does NOT abort caller (not pg)
# ---------------------------------------------------------------------------

@pytest.mark.not_pg
def test_audit_insert_failure_logs_error_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A forced INSERT failure must log at ERROR and must not raise.

    The writer is best-effort: a failed pg write must never abort the calling
    action.  This test verifies both constraints: (a) the caller is not
    interrupted, (b) the failure surfaces in the log at ERROR level.
    """
    # Force the pg backend check to return True so the try-block is entered.
    monkeypatch.setattr(audit_module, "_audit_pg_backend_selected", lambda: True)

    # Build a fake conn_rw that raises when cursor().execute() is called.
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.execute.side_effect = Exception("simulated UndefinedColumn from pg")

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor

    def _failing_conn_rw(*, connect_timeout: int) -> Any:
        return mock_conn

    monkeypatch.setattr(audit_module, "conn_rw", _failing_conn_rw)

    # The call must NOT raise — writer stays non-fatal.
    with caplog.at_level(logging.ERROR, logger="app.services.audit"):
        result = audit_event(
            event="test.ac2.forced_failure",
            object_id=None,
            agent="test-audit-writer",
            trace_id="test-trace-ac2",
        )

    assert result is None, "audit_event must return None (non-fatal), not raise"

    # Failure must be logged at ERROR.
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, (
        "Expected at least one ERROR-level log record after a forced INSERT failure; "
        "got none. The bare `except: return` may still be silencing failures."
    )
    combined_message = " ".join(r.getMessage() for r in error_records)
    assert "audit" in combined_message.lower() or "INSERT" in combined_message or "dropped" in combined_message.lower(), (
        f"ERROR log message does not mention audit/INSERT/dropped: {combined_message!r}"
    )


# ---------------------------------------------------------------------------
# FK-fallback unit coverage (#2625 P1) — not pg, monkeypatched
# ---------------------------------------------------------------------------


class _FkFallbackCursor:
    """Records executes; raises FK IntegrityError when object_id is non-NULL."""

    def __init__(self, recorder: list[tuple[str, tuple[object, ...]]]) -> None:
        self._recorder = recorder

    def __enter__(self) -> _FkFallbackCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[object, ...]) -> None:
        # params order: (id, object_id, agent, action, ts, trace_id, details)
        object_id = params[1]
        self._recorder.append((statement, params))
        if object_id is not None:
            # Simulate the audit.object_id FK violation against `objects`.
            raise IntegrityError("insert or update on table \"audit\" violates foreign key constraint")


class _FkFallbackConnection:
    """Fake connection: first (SAVEPOINT) insert with object_id fails the FK,
    NULL-object_id retry succeeds. Records every execute for assertion."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FkFallbackConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _FkFallbackCursor:
        return _FkFallbackCursor(self.statements)

    @contextmanager
    def transaction(self):
        # SAVEPOINT scope: a raised IntegrityError propagates out (rolled back to
        # the savepoint by real psycopg) so the writer can run the NULL retry.
        yield self


@pytest.mark.not_pg
def test_audit_object_fk_violation_falls_back_to_null_object_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An object-scoped audit whose object_id is absent from `objects` (it lives
    in store_objects) must still write a row: object_id NULL, original id in
    details.object_ref. This exercises the real promotion-gate path without
    requiring a live pg.
    """
    monkeypatch.setattr(audit_module, "_audit_pg_backend_selected", lambda: True)

    connection = _FkFallbackConnection()

    def _conn_rw(*, connect_timeout: int) -> _FkFallbackConnection:
        assert connect_timeout == 1
        return connection

    monkeypatch.setattr(audit_module, "conn_rw", _conn_rw)

    orphan_object_id = "11111111-2222-3333-4444-555555555555"

    # Must not raise — writer stays non-fatal even through the fallback.
    result = audit_event(
        event="promotion.orphan_override",
        object_id=orphan_object_id,
        agent="promotion-gate",
        trace_id="t-fk-fallback",
    )
    assert result is None

    # Two inserts: first attempt (object_id present, FK fails), retry (NULL).
    assert len(connection.statements) == 2, (
        f"Expected exactly 2 INSERT attempts (FK attempt + NULL retry); "
        f"got {len(connection.statements)}"
    )

    first_stmt, first_params = connection.statements[0]
    second_stmt, second_params = connection.statements[1]
    assert "INSERT INTO audit" in first_stmt
    assert "INSERT INTO audit" in second_stmt

    # First attempt carried the real object_id.
    assert first_params[1] == orphan_object_id
    # Retry wrote NULL object_id.
    assert second_params[1] is None, (
        f"Retry must write NULL object_id, got {second_params[1]!r}"
    )

    # The original id is preserved in the retry's details payload.
    import json as _json  # noqa: PLC0415

    retry_details = _json.loads(second_params[6])
    assert retry_details.get("object_ref") == orphan_object_id, (
        f"Retry details must preserve original id in object_ref; got {retry_details!r}"
    )


# ---------------------------------------------------------------------------
# AC3 — column list in writer matches migration schema (structural, not pg)
# ---------------------------------------------------------------------------

@pytest.mark.not_pg
def test_audit_columns_match_migration() -> None:
    """The INSERT column list in audit_event must match the migration schema.

    This is a structural check: it parses both the writer source and the
    migration DDL and verifies every migration column is present in the INSERT,
    without requiring a live database.
    """
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "alembic"
        / "versions"
        / "202510241200_sot41_amg_core.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    migration_src = migration_path.read_text(encoding="utf-8")

    # Find the start of the CREATE TABLE audit block.
    start_marker = "CREATE TABLE IF NOT EXISTS audit"
    start_idx = migration_src.lower().find(start_marker.lower())
    assert start_idx != -1, "Could not find CREATE TABLE audit block in migration"

    # Walk forward to find the opening '(' then extract content respecting
    # nested parens (e.g. REFERENCES objects(id) has an inner paren pair).
    paren_start = migration_src.index("(", start_idx)
    depth = 0
    paren_end = paren_start
    for i, ch in enumerate(migration_src[paren_start:], start=paren_start):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                paren_end = i
                break
    audit_ddl = migration_src[paren_start + 1 : paren_end]

    # Extract column names (first word of each line that isn't a constraint).
    migration_columns: set[str] = set()
    for line in audit_ddl.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        # Skip inline constraint keywords.
        if line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "CONSTRAINT")):
            continue
        col_name = line.split()[0].lower()
        if col_name:
            migration_columns.add(col_name)

    # Expected from the migration: id, object_id, agent, action, ts, trace_id, details
    expected = {"id", "object_id", "agent", "action", "ts", "trace_id", "details"}
    assert migration_columns == expected, (
        f"Migration columns parsed as {migration_columns!r}; expected {expected!r}. "
        "Update this test if the migration schema changes."
    )

    # Now check the writer INSERT statement contains exactly these columns. The
    # writer keeps a single canonical INSERT in `_AUDIT_INSERT_SQL`; fall back to
    # scanning the module source if the constant is ever inlined again.
    insert_source = getattr(audit_module, "_AUDIT_INSERT_SQL", None) or inspect.getsource(
        audit_module
    )

    insert_match = re.search(
        r"INSERT INTO audit\s*\(([^)]+)\)",
        insert_source,
        re.DOTALL | re.IGNORECASE,
    )
    assert insert_match, (
        "Could not find INSERT INTO audit(...) in the writer source. "
        "Is the INSERT missing or using a dynamic column list?"
    )
    insert_cols_raw = insert_match.group(1)
    insert_columns = {c.strip().lower() for c in insert_cols_raw.split(",")}

    missing_in_writer = expected - insert_columns
    extra_in_writer = insert_columns - expected
    assert not missing_in_writer, (
        f"Writer INSERT is missing migration columns: {missing_in_writer!r}. "
        f"Writer uses: {insert_columns!r}"
    )
    assert not extra_in_writer, (
        f"Writer INSERT references columns not in migration schema: {extra_in_writer!r}. "
        f"Migration has: {expected!r}"
    )
