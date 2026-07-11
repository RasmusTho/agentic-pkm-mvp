from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from app.standing_questions.projection import rebuild_standing_questions_projection
from app.standing_questions.question_store import QuestionStore
from app.write_guard import WriteGuard

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()
    name = f"scratch_questions_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        conn.execute(f"ALTER DATABASE \"{name}\" SET lc_messages = 'C'")
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")
    yield dsn
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


@pytest.mark.pg
def test_projection_rebuilds_from_vault(scratch_db: str, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))
    note, _ = store.create_question(text="Will it rebuild?", scope="work", registered_via="explicit")

    first = rebuild_standing_questions_projection(vault)
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        baseline = conn.execute(
            "SELECT question_id, scope, text, status, evidence FROM standing_questions ORDER BY question_id"
        ).fetchall()
        conn.execute("TRUNCATE TABLE standing_questions")
    second = rebuild_standing_questions_projection(vault)
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rebuilt = conn.execute(
            "SELECT question_id, scope, text, status, evidence FROM standing_questions ORDER BY question_id"
        ).fetchall()
    assert first.inserted == second.inserted == 1
    assert baseline == rebuilt
    assert rebuilt[0][0] == note["question_id"]


@pytest.mark.pg
def test_standing_questions_projection_migration_applies(scratch_db: str) -> None:
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        row = conn.execute("SELECT to_regclass('public.standing_questions')").fetchone()
    assert row[0] == "standing_questions"
