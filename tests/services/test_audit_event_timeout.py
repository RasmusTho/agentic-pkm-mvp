"""Regression tests for issue #2377.

``app.services.audit.audit_event()`` is a best-effort logger: it must never
stall the caller when no reachable DB is configured. The original code opened a
psycopg connection through ``conn_rw()`` with no bound, so in memory/non-pg mode
the default DSN (``db:5432``) could stall in ``socket.getaddrinfo()`` for far
longer than the per-test ``not pg`` timeout before the best-effort ``except``
could no-op (observed on PR #2376 and, after a connect_timeout-only attempt, on
the #2377 fix's own CI run via the classifier audit path in test_uat_run_cli).

``connect_timeout`` bounds only the TCP connect, **not** DNS resolution, so it
cannot stop a ``getaddrinfo`` stall. The fix gates the audit write on an
explicit pg backend or an already-known store-backend hint: in memory/non-pg
mode it does not attempt a connection at all (removing the stall at its source),
while resolved Postgres backends keep writing audit rows (with the connect
additionally bounded by ``connect_timeout`` for an unreachable-but-resolvable
host).
"""

from __future__ import annotations

import time

import pytest

import app.db.db as db_module
import app.services.audit as audit_module
from app.services.audit import audit_event

pytestmark = pytest.mark.not_pg

# TEST-NET-3 (RFC 5737) — guaranteed non-routable; connects silently drop,
# so an unbounded connect would hang far past any reasonable test budget.
_UNROUTABLE_DSN = "postgresql://app:app@192.0.2.1:5432/app"

# The bounded pg path costs ~1-2s for the silently-dropped connect; the unbounded
# regression costs ~75s. 5s cleanly distinguishes the two and stays well under
# the 120s per-test CI timeout the issue is about.
_MAX_SECONDS = 5.0


class _RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[object, ...]) -> None:
        self.statements.append((statement, params))


class _RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = _RecordingCursor()

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _RecordingCursor:
        return self.cursor_instance


def test_audit_event_skips_db_in_memory_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1 (the actual #2377 flake fix): in memory/non-pg mode audit_event must
    not even attempt a connection, so no ``getaddrinfo``/connect stall is possible.
    """
    monkeypatch.setenv("STORE_BACKEND", "memory")
    # Even with a (non-empty, unreachable) DSN present, the write must be skipped.
    monkeypatch.setenv("DATABASE_URL", _UNROUTABLE_DSN)

    def _fail_if_called(*args: object, **kwargs: object):
        raise AssertionError(
            "audit_event must not open a DB connection in memory/non-pg mode"
        )

    monkeypatch.setattr(audit_module, "conn_rw", _fail_if_called)

    start = time.monotonic()
    result = audit_event(event="test.event", object_id=None, agent="tester", trace_id="t-2377")
    elapsed = time.monotonic() - start

    assert result is None
    # No connect attempted at all → effectively instantaneous.
    assert elapsed < 1.0, f"memory-mode audit_event took {elapsed:.2f}s; expected an immediate skip"


def test_audit_event_bounded_connect_on_pg_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2/AC5: with the Postgres backend configured but the host unreachable,
    audit_event still returns promptly (connect is bounded) and no-ops rather
    than raising — the reachable-DB write path is otherwise unchanged.
    """
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("DATABASE_URL", _UNROUTABLE_DSN)
    # Force a real connect attempt rather than reusing a process-cached schema flag.
    monkeypatch.setattr(db_module, "_SCHEMA_INITIALIZED", False)

    start = time.monotonic()
    result = audit_event(event="test.event", object_id=None, agent="tester", trace_id="t-2377")
    elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < _MAX_SECONDS, (
        f"audit_event() took {elapsed:.2f}s against an unreachable DB; expected a "
        f"bounded connect (<{_MAX_SECONDS}s)."
    )


def test_audit_event_does_not_probe_backend_when_store_backend_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no explicit backend, audit_event must not invoke auto-detect.

    Auto-detect may perform a DNS/pg reachability probe, which is too expensive
    and potentially unbounded for best-effort audit emission.
    """
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", _UNROUTABLE_DSN)
    monkeypatch.setattr(audit_module, "resolved_store_backend_hint", lambda: None)

    def _fail_if_called(*args: object, **kwargs: object):
        raise AssertionError("audit_event must not open a DB connection without a pg hint")

    monkeypatch.setattr(audit_module, "conn_rw", _fail_if_called)

    start = time.monotonic()
    result = audit_event(event="test.event", object_id=None, agent="tester", trace_id="t-2406")
    elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < 1.0, f"unhinted audit_event took {elapsed:.2f}s; expected an immediate skip"


def test_audit_event_writes_when_cached_backend_hint_is_pg_without_store_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A previously resolved pg backend keeps audit writes without another probe."""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setattr(audit_module, "resolved_store_backend_hint", lambda: "pg")
    connection = _RecordingConnection()

    def _recording_conn_rw(*, connect_timeout: int) -> _RecordingConnection:
        assert connect_timeout == 1
        return connection

    monkeypatch.setattr(audit_module, "conn_rw", _recording_conn_rw)

    result = audit_event(
        event="test.event",
        object_id="object-1",
        agent="tester",
        trace_id="t-2406",
        extra={"source": "auto-detect"},
    )

    assert result is None
    assert len(connection.cursor_instance.statements) == 1
    statement, params = connection.cursor_instance.statements[0]
    assert "INSERT INTO audit" in statement
    assert params[0] == "t-2406"
    assert params[1] == "test.event"
