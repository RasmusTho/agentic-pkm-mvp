"""Regression coverage for #3930: the outbox service binds the real DB helpers.

``from app.db import conn_rw`` resolves through ``app/db/__init__.py::__getattr__``
to the permanent psycopg-free smoke stub in ``app/db/sqlalchemy.py`` (#30), whose
``conn_rw`` always raises ``RuntimeError`` and whose ``ensure_schema`` is a no-op.
``_open_conn``'s ``except Exception: pass`` swallowed that raise, so every
self-opened outbox connection silently fell through to the plain
``psycopg.connect(url, autocommit=True)`` env fallback: the canonical
``app.db.db.conn_rw`` path (canonical DSN resolution, dict_row cursors) was dead
code from this call site — the same defect class ``app/services/vault_sync.py``
fixed in #2937 (see its import NOTE).
"""

from __future__ import annotations

from typing import Any

import pytest

import app.db.db as db_module
from app.services import outbox as outbox_service

pytestmark = pytest.mark.not_pg


class _FakeConn:
    def __init__(self) -> None:
        self.autocommit = False
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_outbox_service_binds_real_db_helpers() -> None:
    """The service must bind app.db.db, not the smoke stub (#3930).

    On the defective import the stub's ``conn_rw`` raised on every call and the
    stub's ``ensure_schema`` no-op silently defeated the KERNEL-05 (#2850)
    "a failure here must surface" intent inside ``bootstrap()``.
    """
    assert outbox_service.conn_rw is db_module.conn_rw
    assert outbox_service.ensure_schema is db_module.ensure_schema


def test_open_conn_prefers_real_conn_rw_autocommit(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_open_conn`` returns the canonical connection switched to autocommit.

    Self-opened callers in the service are single-statement and never call
    ``commit()``; psycopg3 rolls back uncommitted work on ``close()``, so the
    manual-commit connection ``conn_rw`` returns must be flipped to autocommit
    here or every self-opened write would be silently lost.
    """
    fake = _FakeConn()
    monkeypatch.setattr(outbox_service, "conn_rw", lambda *a, **k: fake)

    conn = outbox_service._open_conn()

    assert conn is fake
    assert conn.autocommit is True


def test_open_conn_falls_back_when_conn_rw_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing canonical helper degrades to the env-DSN fallback, not an error.

    With no DATABASE_URL/DB_DSN configured the fallback's own fail-loud error
    is the observable proof that the fallback path was reached instead of the
    conn_rw exception propagating.
    """

    def _raise() -> Any:
        raise RuntimeError("simulated conn_rw outage")

    monkeypatch.setattr(outbox_service, "conn_rw", _raise)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL or DB_DSN not set"):
        outbox_service._open_conn()


def test_open_outbox_txn_conn_requires_explicit_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without explicit DB env the txn helper degrades to None and never dials out.

    ``conn_rw`` falls back to ``settings.db_dsn`` when the environment names no
    database, which could reach a real local Postgres a test run never asked
    for — the explicit-env gate keeps non-pg runs hermetic.
    """

    def _boom() -> Any:  # pragma: no cover - the assertion is that this never runs
        raise AssertionError("conn_rw must not be called without explicit DB env")

    monkeypatch.setattr(outbox_service, "conn_rw", _boom)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")

    assert outbox_service.open_outbox_txn_conn() is None


def test_open_outbox_txn_conn_returns_manual_commit_conn(monkeypatch: pytest.MonkeyPatch) -> None:
    """With explicit DB env the txn helper hands back conn_rw's manual-commit conn."""
    fake = _FakeConn()
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused-in-test")
    monkeypatch.setattr(outbox_service, "conn_rw", lambda *a, **k: fake)

    conn = outbox_service.open_outbox_txn_conn()

    assert conn is fake
    assert conn.autocommit is False


def test_open_outbox_txn_conn_degrades_to_none_on_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connect failure yields None (degraded per-call path), never an exception."""

    def _raise() -> Any:
        raise RuntimeError("simulated connect failure")

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused-in-test")
    monkeypatch.setattr(outbox_service, "conn_rw", _raise)

    assert outbox_service.open_outbox_txn_conn() is None


def test_open_outbox_txn_conn_logs_when_db_configured_but_conn_rw_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A conn_rw() failure with DB explicitly configured is logged (#3930 round-2 review).

    Distinguishes this case from the silent, expected short-circuit below: a
    live worker whose canonical helper breaks while its DSN stays reachable
    (poll/ack still succeed via `_open_conn`'s fallback) would otherwise
    silently and permanently revert to the non-atomic per-call bookkeeping
    this module exists to eliminate, indistinguishable from "DB unconfigured".
    """

    def _raise() -> Any:
        raise RuntimeError("simulated connect failure")

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused-in-test")
    monkeypatch.setattr(outbox_service, "conn_rw", _raise)

    with caplog.at_level("WARNING", logger="app.services.outbox"):
        assert outbox_service.open_outbox_txn_conn() is None

    assert any("conn_rw" in record.message for record in caplog.records)


def test_open_outbox_txn_conn_env_unconfigured_short_circuit_is_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The expected 'DB not configured' short-circuit stays silent (no log spam).

    Guards against the logging fix above firing on every non-pg test run,
    where DATABASE_URL/DB_DSN are deliberately unset.
    """

    def _boom() -> Any:  # pragma: no cover - the assertion is that this never runs
        raise AssertionError("conn_rw must not be called when the env gate short-circuits")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(outbox_service, "conn_rw", _boom)

    with caplog.at_level("WARNING", logger="app.services.outbox"):
        assert outbox_service.open_outbox_txn_conn() is None

    assert caplog.records == []
