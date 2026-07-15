"""Postgres harness helpers for decisions-schema migration tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import uuid

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def migrated_decisions_db(monkeypatch: pytest.MonkeyPatch):
    """Yield a fresh database upgraded through the live Alembic head."""
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_decisions_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        from alembic import command
        from alembic.config import Config

        monkeypatch.setenv("DATABASE_URL", dsn)
        monkeypatch.delenv("DB_DSN", raising=False)
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
        command.upgrade(cfg, "head")
        yield dsn
    finally:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except Exception:
            pass
