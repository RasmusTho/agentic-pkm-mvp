"""Tests for #2600: audit writer INSERT schema fix.

AC1 — end-to-end privileged action writes ≥1 audit row on a real pg:
    test_audit_row_written_on_action  (pytest.mark.pg)

AC2 — forced INSERT failure logs ERROR and does NOT abort the calling action:
    test_audit_insert_failure_logs_error_non_fatal  (not pg — monkeypatched)

AC3 — writer column list matches migration schema:
    test_audit_columns_match_migration  (not pg — structural check)
"""

from __future__ import annotations

import inspect
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

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

    # Now check the writer INSERT statement contains exactly these columns.
    writer_src = inspect.getsource(audit_event)

    insert_match = re.search(
        r"INSERT INTO audit\s*\(([^)]+)\)",
        writer_src,
        re.DOTALL | re.IGNORECASE,
    )
    assert insert_match, (
        "Could not find INSERT INTO audit(...) in audit_event source. "
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
