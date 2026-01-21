from __future__ import annotations

import os

import psycopg
import pytest

from app.db.dsn import resolve_dsn
from app.stores import reset_store_backends, resolve_store_backend


def _pg_available() -> bool:
    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _reset_between_tests():
    reset_store_backends()
    yield
    reset_store_backends()


def test_store_backend_override_wins(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    assert resolve_store_backend() == "memory"


def test_store_backend_auto_detects_pg(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or "postgresql://app:app@127.0.0.1:15432/app")
    assert resolve_store_backend() == "pg"


def test_store_backend_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "")
    assert resolve_store_backend() == "memory"
