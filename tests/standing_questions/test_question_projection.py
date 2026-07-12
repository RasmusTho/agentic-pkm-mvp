from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from app.standing_questions.projection import (
    QuestionsDirectoryMissingError,
    iter_question_notes,
    rebuild_standing_questions_projection,
)
from app.standing_questions.question_store import QuestionStore
from app.write_guard import WriteGuard

REPO_ROOT = Path(__file__).resolve().parents[2]


def _store(vault: Path) -> QuestionStore:
    return QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))


def test_missing_questions_directory_raises_instead_of_wiping(tmp_path: Path) -> None:
    """Review finding #2: a missing questions/ dir must fail loud, never TRUNCATE the
    existing projection down to zero rows as if it were legitimately empty."""
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(QuestionsDirectoryMissingError):
        rebuild_standing_questions_projection(vault)
    with pytest.raises(QuestionsDirectoryMissingError):
        iter_question_notes(vault)


def test_present_but_empty_questions_directory_is_not_missing(tmp_path: Path) -> None:
    """The dir-missing guard must not fire for a genuinely empty (but present) dir."""
    vault = tmp_path / "vault"
    (vault / "questions").mkdir(parents=True)
    assert iter_question_notes(vault) == []


def test_iter_question_notes_isolates_malformed_note(tmp_path: Path) -> None:
    """Review finding #1: one malformed Question note must not abort parsing of the
    rest -- it is skipped, and every valid note still comes back."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text="Valid question", scope="work", registered_via="explicit")

    bad_path = vault / "questions" / "sq-0badbad0-0000-0000-0000-000000000000.md"
    bad_path.write_text(
        "---\nquestion_id: sq-0badbad0-0000-0000-0000-000000000000\n---\n\nincomplete\n",
        encoding="utf-8",
    )

    notes = iter_question_notes(vault)
    assert [source for source, _ in notes] == [f"questions/{note['question_id']}.md"]


def test_iter_question_notes_ignores_non_question_markdown(tmp_path: Path) -> None:
    """Review finding #4: reusing iter_vault_markdown_files must not pick up unrelated
    markdown dropped directly into questions/."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text="Valid question", scope="work", registered_via="explicit")
    (vault / "questions" / "README.md").write_text("not a question note", encoding="utf-8")

    notes = iter_question_notes(vault)
    assert [source for source, _ in notes] == [f"questions/{note['question_id']}.md"]


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
def test_rebuild_reports_and_survives_a_malformed_note(scratch_db: str, tmp_path: Path) -> None:
    """Review finding #1, end-to-end: a malformed note next to valid ones must not
    abort the transaction -- the valid note is still projected, the malformed one is
    reported in ``skipped_invalid``."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))
    note, _ = store.create_question(text="Survives a bad sibling?", scope="work", registered_via="explicit")
    bad_path = vault / "questions" / "sq-0badbad0-0000-0000-0000-000000000000.md"
    bad_path.write_text(
        "---\nquestion_id: sq-0badbad0-0000-0000-0000-000000000000\n---\n\nincomplete\n",
        encoding="utf-8",
    )

    summary = rebuild_standing_questions_projection(vault)

    assert summary.inserted == 1
    assert len(summary.skipped_invalid) == 1
    assert summary.skipped_invalid[0]["note_path"] == "questions/sq-0badbad0-0000-0000-0000-000000000000.md"
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rows = conn.execute("SELECT question_id FROM standing_questions").fetchall()
    assert [r[0] for r in rows] == [note["question_id"]]


@pytest.mark.pg
def test_standing_questions_projection_migration_applies(scratch_db: str) -> None:
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        row = conn.execute("SELECT to_regclass('public.standing_questions')").fetchone()
    assert row[0] == "standing_questions"
