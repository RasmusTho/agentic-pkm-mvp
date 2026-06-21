"""Regression tests for issue #2377.

``app.services.audit.audit_event()`` is a best-effort logger: it must never
stall the caller when no reachable DB is configured. The original code opened a
psycopg connection through ``conn_rw()`` with no bound, so in memory/non-pg mode
the default DSN (``db:5432``) could stall in ``socket.getaddrinfo()`` for far
longer than the per-test ``not pg`` timeout before the best-effort ``except``
could no-op (observed on PR #2376 and, after a connect_timeout-only attempt, on
the #2377 fix's own CI run via the classifier audit path in test_uat_run_cli).

``connect_timeout`` bounds only the TCP connect, **not** DNS resolution, so it
cannot stop a ``getaddrinfo`` stall. The fix gates the audit write on
``STORE_BACKEND``: in memory/non-pg mode it does not attempt a connection at all
(removing the stall at its source), while a configured Postgres backend keeps
writing audit rows (with the connect additionally bounded by ``connect_timeout``
for an unreachable-but-resolvable host).
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
