"""Regression test for issue #2377.

`app.services.audit.audit_event()` is a best-effort logger: it must never stall
the caller when the configured DB host is unreachable. Before the fix, it opened
a psycopg connection through ``conn_rw()`` with no connect timeout, so an
unreachable host (e.g. the default ``db:5432`` resolved in memory/non-pg mode)
could stall in socket connect / ``getaddrinfo`` for up to ~75s — past the
per-test ``not pg`` timeout — before the best-effort ``except`` could no-op.

The fix bounds that connect with ``connect_timeout=1`` on the best-effort audit
path only. This test points the DSN at an unroutable (packet-dropping) host and
asserts ``audit_event()`` returns far below the unbounded stall, proving the
connect is now bounded. A truly unroutable host still costs ~1-2s of bounded
connect (vs ~75s unbounded), so the assertion threshold separates the bounded
fix from the unbounded regression rather than asserting strict sub-second.
"""

from __future__ import annotations

import time

import pytest

import app.db.db as db_module
from app.services.audit import audit_event

pytestmark = pytest.mark.not_pg

# TEST-NET-3 (RFC 5737) — guaranteed non-routable; connects silently drop,
# so an unbounded connect would hang far past any reasonable test budget.
_UNROUTABLE_DSN = "postgresql://app:app@192.0.2.1:5432/app"

# The bounded path costs ~1-2s for the silently-dropped connect; the unbounded
# regression costs ~75s. 5s cleanly distinguishes the two and stays well under
# the 120s per-test CI timeout the issue is about.
_MAX_SECONDS = 5.0


def test_audit_event_returns_promptly_when_db_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The non-pg autouse fixture strips DATABASE_URL/DB_DSN; set it back to a
    # non-empty unreachable DSN so conn_rw() actually attempts (and must bound)
    # a connect, reproducing the stall the fix guards against.
    monkeypatch.setenv("DATABASE_URL", _UNROUTABLE_DSN)
    # Force a real connect attempt rather than reusing a process-cached schema flag.
    monkeypatch.setattr(db_module, "_SCHEMA_INITIALIZED", False)

    start = time.monotonic()
    # Best-effort: must return None without raising even though the DB is down.
    result = audit_event(event="test.event", object_id=None, agent="tester", trace_id="t-2377")
    elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < _MAX_SECONDS, (
        f"audit_event() took {elapsed:.2f}s against an unreachable DB; expected a "
        f"bounded connect (<{_MAX_SECONDS}s). The connect_timeout guard is likely missing."
    )
