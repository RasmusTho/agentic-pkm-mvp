"""ERE-02 (#3177): the ``episodes`` PG projection.

- AC5: projection rebuild from a fixture vault reproduces the projection exactly (drop ->
  rebuild -> identical rows). Verify:
  ``tests/episodes/test_episode_projection.py::test_projection_rebuilds_from_vault`` (pg-marked)
- AC6: Alembic migration applies + is recorded forward-only. Verify:
  ``tests/episodes/test_episode_projection.py::test_episodes_projection_migration_applies``
  (pg-marked)

Laptop has no pg by design; both tests skip cleanly without Postgres (mac-mini test channel
runs them for real, per house practice).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    """A throwaway database at ``alembic upgrade head``, mirroring
    ``tests/jobs/test_decisions_projection_rebuild.py::scratch_db``."""
    import psycopg

    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_episodes_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        conn.execute(f'ALTER DATABASE "{name}" SET lc_messages = \'C\'')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"

    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "pg")
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


def _allow_guard():
    from app.write_guard import WriteGuard

    return WriteGuard(lambda: {"state": "healthy", "reason": None})


@pytest.mark.pg
def test_episodes_projection_migration_applies(scratch_db: str) -> None:
    """The migration created the episodes table forward-only, with the shape the
    projection job writes into."""
    import psycopg

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        cols = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'episodes'"
            ).fetchall()
        }
    expected = {
        "episode_id", "scope", "title", "time_start", "time_end", "closed",
        "segmentation", "parent_episode", "space", "protagonists", "goal",
        "causation", "derived_from", "note_path", "updated_at",
    }
    assert expected <= cols

    # Forward-only: the migration module declares no usable downgrade.
    import importlib

    module = importlib.import_module(
        "app.alembic.versions.e0f2a9c4b7d1_ere02_episodes_projection"
    )
    assert module.reversibility == "forward-only"
    with pytest.raises(RuntimeError):
        module.downgrade()


@pytest.mark.pg
def test_projection_rebuilds_from_vault(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drop -> rebuild -> identical rows; the projection is never written except by the
    projector (drift from the vault SoR is a rebuild bug, not tolerated)."""
    import psycopg

    from app.episodes.store import write_episode_note
    from app.jobs.episodes_projection import (
        doctor_episodes_projection,
        rebuild_episodes_projection,
    )

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    r1 = write_episode_note(
        title="Morning standup",
        scope="work",
        start="2026-07-11T09:00:00+00:00",
        end="2026-07-11T09:15:00+00:00",
        closed=True,
        segmentation="accepted",
        vault_root=vault,
        write_guard=_allow_guard(),
    )
    r2 = write_episode_note(
        title="Debugging session",
        scope="work",
        start="2026-07-11T10:00:00+00:00",
        closed=False,
        segmentation="proposed",
        derived_from=["heimdal-session-xyz"],
        vault_root=vault,
        write_guard=_allow_guard(),
    )

    summary = rebuild_episodes_projection(vault)
    assert summary.total_notes == 2
    assert summary.inserted == 2
    assert summary.skipped_invalid == []

    report = doctor_episodes_projection(vault)
    assert report.ok, (report.missing_in_db, report.extra_in_db)
    assert report.db_rows == 2
    assert report.vault_rows == 2

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rows = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT episode_id, segmentation FROM episodes"
            ).fetchall()
        }
    assert rows[r1.episode_id] == "accepted"
    assert rows[r2.episode_id] == "proposed"

    # Drop -> rebuild reproduces the projection identically (AC5).
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("TRUNCATE TABLE episodes")
        assert conn.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0

    summary2 = rebuild_episodes_projection(vault)
    assert summary2.inserted == 2
    report2 = doctor_episodes_projection(vault)
    assert report2.ok, (report2.missing_in_db, report2.extra_in_db)

    # A hand-written INSERT bypassing the projector is caught as drift by the doctor --
    # the projection must never be written except by rebuild_episodes_projection().
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO episodes (episode_id, scope, title, time_start, closed, "
            "segmentation, note_path) VALUES "
            "('ep-99999999-9999-4999-8999-999999999999', 'work', 'rogue', now(), "
            "false, 'proposed', 'episodes/rogue.md')"
        )
    drifted = doctor_episodes_projection(vault)
    assert not drifted.ok
    assert drifted.extra_in_db
