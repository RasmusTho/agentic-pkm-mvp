from __future__ import annotations


import psycopg
import pytest

from app.db.dsn import resolve_dsn
from app.stores import reset_store_backends, resolve_store_backend, resolved_store_backend_hint


def _pg_available() -> bool:
    url = resolve_dsn()
    if not url:
        # An empty conninfo is not "no target": libpq then supplies its own
        # from PGHOST/PGPORT/PGDATABASE or the local socket. This module is not
        # pg-marked, so force_memory_store_for_non_pg has already cleared
        # DATABASE_URL/DB_DSN and `url` is always empty here — dialling would
        # mean silently picking whatever the ambient environment names (#4573).
        return False
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def _fake_connect(captured: dict[str, object]):
    class _Conn:
        def close(self) -> None:
            return None

    def _connect(dsn: str, connect_timeout: int = 1):
        captured["dsn"] = dsn
        captured["connect_timeout"] = connect_timeout
        return _Conn()

    return _connect


@pytest.fixture(autouse=True)
def _reset_between_tests():
    reset_store_backends()
    yield
    reset_store_backends()


def test_store_backend_override_wins(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    # Must not be a reachable production address (#4573): this module's autouse
    # teardown calls reset_store_backends() -> truncate_pg_tables(), and that
    # finalizer runs BEFORE monkeypatch restores the environment. With the prod
    # DSN still installed, the teardown issued DELETE against production on any
    # host publishing it on 15432. The assertion only needs *some* DSN present.
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15434/app_test")
    assert resolve_store_backend() == "memory"


def test_store_backend_auto_detects_pg_psycopg_dsn(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(psycopg, "connect", _fake_connect(captured))
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/db")

    assert resolve_store_backend() == "pg"
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/db"
    assert captured["connect_timeout"] == 1
    assert resolved_store_backend_hint() == "pg"


def test_store_backend_auto_detects_pg_postgresql_dsn(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(psycopg, "connect", _fake_connect(captured))
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

    assert resolve_store_backend() == "pg"
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/db"
    assert captured["connect_timeout"] == 1


def test_store_backend_auto_detects_pg(monkeypatch):
    """A reachable DSN and no override auto-detects the pg backend.

    Driven through the fake connector rather than a live server (#4573). This
    module is not pg-marked, so `force_memory_store_for_non_pg` clears
    DATABASE_URL/DB_DSN before the body runs and `resolve_dsn()` is always
    empty here — the previous form asked a real Postgres whether it was up,
    which meant dialling whatever the environment named, and on this repo's
    hosts that was production. Skipping instead would trade a prod dial for a
    permanently silent `s`, so the assertion is kept and the server removed.
    """

    captured: dict[str, object] = {}
    monkeypatch.setattr(psycopg, "connect", _fake_connect(captured))
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15434/app_test")

    assert resolve_store_backend() == "pg"
    assert captured["dsn"] == "postgresql://app:app@127.0.0.1:15434/app_test"


def test_store_backend_without_config_raises(monkeypatch):
    """Memory is explicit-only (KERNEL-03): no DSN + no override => raise."""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.delenv("DB_DSN", raising=False)
    with pytest.raises(RuntimeError, match="STORE_BACKEND=memory"):
        resolve_store_backend()


def test_store_backend_hint_is_none_when_environment_changes(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(psycopg, "connect", _fake_connect(captured))
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

    assert resolve_store_backend() == "pg"
    assert resolved_store_backend_hint() == "pg"

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5433/db")

    assert resolved_store_backend_hint() is None
