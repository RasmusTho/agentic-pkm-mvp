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
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# not-pg: the doctor's comparison-row builder is pure -- regression-pin the two
# review findings without needing a database.
# ---------------------------------------------------------------------------


def _fields(**overrides):
    base = {
        "episode_id": "ep-11111111-2222-4333-8444-555555555555",
        "scope": "work",
        "title": "Debugging session",
        "time": {"start": "2026-07-11T10:00:00+00:00", "closed": False},
        "space": [],
        "protagonists": [],
        "goal": [],
        "causation": [],
        "parent_episode": None,
        "segmentation": "proposed",
        "derived_from": [],
    }
    base.update(overrides)
    return base


def test_comparison_row_title_starting_with_bracket_is_not_parsed_as_json() -> None:
    """Review regression (PR #3492 finding 1): a scalar field whose text happens to
    start with '[' or '{' (title is user-supplied) must be carried verbatim, never
    sniffed as pre-serialized JSON -- the old heuristic raised JSONDecodeError here."""
    from app.jobs.episodes_projection import _comparison_row

    for title in ("[Retro] Sprint 12", "{urgent} prod incident"):
        row = _comparison_row(_fields(title=title), "episodes/x.md")
        assert row[2] == title


def test_comparison_row_normalizes_z_suffixed_timestamps_instant_wise() -> None:
    """Review regression (PR #3492 finding 4): the schema's ``format: date-time``
    permits 'Z'-suffixed RFC 3339, and the DB side renders '+00:00' -- the doctor
    must compare instants, not raw strings, or the same row reports as drift on
    both sides."""
    from app.jobs.episodes_projection import _comparison_row

    z_row = _comparison_row(
        _fields(time={"start": "2026-07-11T10:00:00Z", "closed": False}),
        "episodes/x.md",
    )
    offset_row = _comparison_row(
        _fields(time={"start": "2026-07-11T10:00:00+00:00", "closed": False}),
        "episodes/x.md",
    )
    assert z_row == offset_row
    # And both equal the DB side's rendering of the same instant (a datetime).
    from app.jobs.episodes_projection import _norm_ts

    assert _norm_ts(datetime(2026, 7, 11, 10, 0, 0, tzinfo=timezone.utc)) == z_row[3]


def test_raw_frontmatter_validation_allows_renderer_metadata_only() -> None:
    """Retry, rebuild, and doctor share the same unknown-field boundary."""
    from app.episodes.notes import parse_validated_episode_note, render_episode_note
    from app.episodes.notes import EpisodeFrontmatterParseError
    from app.episodes.schema import EpisodeSchemaValidationError

    text = render_episode_note(_fields())
    assert parse_validated_episode_note(text)["episode_id"] == _fields()["episode_id"]

    malformed = text.replace(
        "artifact_class: episode_note\n", "artifact_class: episode_note\nunexpected: value\n"
    )
    with pytest.raises(EpisodeSchemaValidationError):
        parse_validated_episode_note(malformed)

    with pytest.raises(EpisodeFrontmatterParseError):
        parse_validated_episode_note("---\nepisode_id: [unterminated\n---\n")


def test_rebuild_does_not_truncate_when_a_vault_note_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I/O/decode errors must preserve the prior projection, not become skipped notes."""
    from app.jobs import episodes_projection

    broken = tmp_path / "episodes" / "ep-unreadable.md"
    broken.parent.mkdir()
    broken.write_bytes(b"\xff")
    monkeypatch.setattr(
        episodes_projection,
        "conn_rw",
        lambda: pytest.fail("rebuild must read the vault before truncating the projection"),
    )

    with pytest.raises(UnicodeDecodeError):
        episodes_projection.rebuild_episodes_projection(tmp_path)


def test_doctor_reports_unreadable_vault_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Doctor cannot report convergence when it was unable to inspect a note."""
    from app.jobs import episodes_projection

    broken = tmp_path / "episodes" / "ep-unreadable.md"
    broken.parent.mkdir()
    broken.write_bytes(b"\xff")
    monkeypatch.setattr(episodes_projection, "_db_projection_rows", lambda: [])

    report = episodes_projection.doctor_episodes_projection(tmp_path)

    assert report.ok is False
    assert report.unreadable_vault_notes[0]["note_path"] == "episodes/ep-unreadable.md"


def test_rebuild_and_doctor_surface_malformed_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed YAML is an operational failure, not a schema-invalid orphan."""
    from app.episodes.notes import EpisodeFrontmatterParseError
    from app.jobs import episodes_projection

    broken = tmp_path / "episodes" / "ep-malformed.md"
    broken.parent.mkdir()
    broken.write_text("---\nepisode_id: [unterminated\n---\n", encoding="utf-8")
    monkeypatch.setattr(
        episodes_projection,
        "conn_rw",
        lambda: pytest.fail("rebuild must parse the vault before truncating the projection"),
    )

    with pytest.raises(EpisodeFrontmatterParseError):
        episodes_projection.rebuild_episodes_projection(tmp_path)

    monkeypatch.setattr(episodes_projection, "_db_projection_rows", lambda: [])
    report = episodes_projection.doctor_episodes_projection(tmp_path)
    assert report.ok is False
    assert report.unreadable_vault_notes[0]["note_path"] == "episodes/ep-malformed.md"


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

    # Review regression (PR #3492 finding 3): the DB CHECK enforces the same strict
    # 8-4-4-4-12 UUID grouping as the app-level fused-id validator -- an ungrouped
    # 36-hex-char id (which the app rejects) must fail at the DB too.
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO episodes (episode_id, scope, title, time_start, closed, "
                "segmentation, note_path) VALUES "
                f"('ep-{'a' * 36}', 'work', 'bad-id', now(), false, 'proposed', "
                "'episodes/bad.md')"
            )

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
    # Review regressions (PR #3492 findings 1 + 4) through the REAL doctor path:
    # a user-supplied title starting with '[' (must not be sniffed as JSON) and a
    # 'Z'-suffixed RFC 3339 start (must compare instant-wise against the DB's
    # '+00:00' rendering, not as a raw string).
    r3 = write_episode_note(
        title="[Retro] Sprint 12",
        scope="work",
        start="2026-07-11T14:00:00Z",
        closed=False,
        segmentation="proposed",
        vault_root=vault,
        write_guard=_allow_guard(),
    )

    summary = rebuild_episodes_projection(vault)
    assert summary.total_notes == 3
    assert summary.inserted == 3
    assert summary.skipped_invalid == []

    report = doctor_episodes_projection(vault)
    assert report.ok, (report.missing_in_db, report.extra_in_db)
    assert report.db_rows == 3
    assert report.vault_rows == 3

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rows = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT episode_id, segmentation FROM episodes"
            ).fetchall()
        }
    assert rows[r1.episode_id] == "accepted"
    assert rows[r2.episode_id] == "proposed"
    assert rows[r3.episode_id] == "proposed"

    # Drop -> rebuild reproduces the projection identically (AC5).
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("TRUNCATE TABLE episodes")
        assert conn.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0

    summary2 = rebuild_episodes_projection(vault)
    assert summary2.inserted == 3
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
