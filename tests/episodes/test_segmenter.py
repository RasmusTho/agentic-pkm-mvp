"""Episode creation -> ``episodes`` PG projection sync (#3532, ERE-02 follow-up).

Context: #3181 (ERE-06) landed ``app.episodes.closure._sync_projection_closed`` -- a targeted
incremental ``UPDATE`` that keeps the projection's ``closed`` column current -- but that fix
assumes a projection row already exists for the episode. No production path ever ``INSERT``ed a
new row into ``episodes`` when a new episode was proposed: ``app.episodes.segmenter._emit_proposal``
(the split-proposal creation seam) and ``_emit_fused_note`` (the cross-scope fusion creation seam,
ERE-08) both only called ``app.episodes.store.write_episode_note``, a vault-note write with no PG
side effect. ``app.episodes.assignment.read_candidate_episodes_for_scopes`` (ERE-05) and
``app.episodes.closure.find_closable_episodes`` (ERE-06) were therefore silently no-op for any
episode proposed after the last manually-triggered ``rebuild_episodes_projection()`` run.

- AC1: proposing a new episode via ``run_segmentation_tick`` results in a corresponding row in the
  ``episodes`` PG table without requiring a ``rebuild_episodes_projection()`` call. Verify:
  ``test_emit_proposal_syncs_new_row_into_projection`` (pg-marked).
- AC2: the sync is idempotent under redelivery (the same ``episode_id`` synced twice never errors
  or duplicates). Verify: ``test_emit_proposal_projection_sync_is_idempotent`` (pg-marked).

Laptop has no pg by design; both tests skip cleanly without Postgres (mac-mini test channel runs
them for real, per house practice).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.episodes import segmenter as segmenter_module
from app.episodes.segmenter import HEIMDAL_STREAM_ID, run_segmentation_tick
from app.episodes.ids import mint_episode_id
from app.episodes.notes import episode_note_rel_path
from app.heimdal.observation_log import ObservationRow
from app.write_guard import WriteGuard

REPO_ROOT = Path(__file__).resolve().parents[2]


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    """A throwaway database at ``alembic upgrade head``, mirroring
    ``tests/episodes/test_episode_projection.py::scratch_db`` /
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

    name = f"scratch_segmenter_{uuid.uuid4().hex[:12]}"
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


def _heimdal_row(
    *,
    observation_id: str,
    observed_at_start: datetime,
    observed_at_end: datetime | None = None,
    protagonist: str | None = None,
    scope_hint: str = "work",
    sequence: int = 1,
) -> ObservationRow:
    payload: dict = {
        "observation_id": observation_id,
        "observed_at_start": observed_at_start.isoformat(),
        "scope_hint": scope_hint,
    }
    if observed_at_end is not None:
        payload["observed_at_end"] = observed_at_end.isoformat()
    if protagonist is not None:
        payload["attributions"] = [{"mention_id": protagonist, "resolution": "resolved"}]
    return ObservationRow(
        id=f"log-{observation_id}",
        topic="heimdal.observation.published",
        idempotency_key=f"k-{observation_id}",
        envelope={"payload": payload},
        created_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        sequence=sequence,
    )


def _stub_stream_io(monkeypatch: pytest.MonkeyPatch, rows: list[ObservationRow]) -> None:
    """Stub the stream/cursor/engine-state I/O boundaries so the REAL tick body (frontier
    building, fold, emission -- including the new projection-sync call) runs without live
    Heimdal/registry state, mirroring
    ``tests/episodes/test_segmentation_core.py::test_tick_long_observed_window_never_closes_nested_session_segment``.
    Deliberately does NOT stub ``conn_rw``/the assignment DB calls -- those hit the real
    ``scratch_db`` so this stays an enforcement test of the real production call site, not a
    helper exercised in isolation."""
    monkeypatch.setattr(
        segmenter_module,
        "enumerate_consumable_streams",
        lambda *a, **k: (SimpleNamespace(stream_id=HEIMDAL_STREAM_ID),),
    )
    monkeypatch.setattr(segmenter_module, "read_observations_for_consumer", lambda *a, **k: rows)
    monkeypatch.setattr(segmenter_module, "advance_cursor_for_consumer", lambda *a, **k: None)
    monkeypatch.setattr(segmenter_module.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter_module.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter_module.engine_state, "delete_state", lambda key: None)


# ---------------------------------------------------------------------------
# AC1: run_segmentation_tick syncs a brand-new proposal into the episodes projection
# ---------------------------------------------------------------------------


@pytest.mark.pg
def test_emit_proposal_syncs_new_row_into_projection(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: proposing a new episode via ``run_segmentation_tick`` results in a corresponding row
    in the ``episodes`` PG table -- WITHOUT any ``rebuild_episodes_projection()`` call anywhere in
    this test."""
    import psycopg

    # Two signals whose protagonist shift closes the first (mirrors
    # test_segmentation_core.py's own closing mechanism): A (alice) is closed the moment B
    # (bob) arrives, producing exactly one ClosedSegment -> one proposed episode. Anchored to
    # real "now" (not a fixed historical date): run_segmentation_tick unconditionally also runs
    # ERE-06 closure detection against real wall-clock time at the end of the SAME tick, and a
    # fixed past date would make the freshly-proposed episode look quiesced (>45min stale) and
    # get closed again within this same test, which would defeat the "closed is False" assertion
    # below for reasons unrelated to what this test actually verifies.
    now = datetime.now(timezone.utc)
    row_a = _heimdal_row(
        observation_id="obs-a", observed_at_start=now - timedelta(minutes=20),
        protagonist="alice", sequence=1,
    )
    row_b = _heimdal_row(
        observation_id="obs-b", observed_at_start=now - timedelta(minutes=10),
        protagonist="bob", sequence=2,
    )
    _stub_stream_io(monkeypatch, [row_a, row_b])

    vault_root = tmp_path / "vault"
    result = run_segmentation_tick(vault_root=vault_root, write_guard=_allow_guard())

    assert len(result["proposed"]) == 1, result
    episode_id = result["proposed"][0]

    # The note landed on disk (SoR) ...
    note_path = vault_root / episode_note_rel_path(episode_id)
    assert note_path.exists()

    # ... AND the projection row exists WITHOUT a rebuild -- this is the #3532 fix.
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        row = conn.execute(
            "SELECT episode_id, scope, closed, note_path FROM episodes WHERE episode_id = %s",
            (episode_id,),
        ).fetchone()
    assert row is not None, "episodes projection has no row for the newly-proposed episode"
    assert row[0] == episode_id
    assert row[1] == "work"
    assert row[2] is False
    assert row[3] == episode_note_rel_path(episode_id)


# ---------------------------------------------------------------------------
# AC2: the incremental sync is idempotent under redelivery
# ---------------------------------------------------------------------------


def _episode_fields(episode_id: str) -> dict:
    return {
        "episode_id": episode_id,
        "scope": "work",
        "title": "Debugging session",
        "time": {"start": "2026-07-11T09:00:00+00:00", "end": "2026-07-11T09:10:00+00:00", "closed": False},
        "space": [],
        "protagonists": ["alice"],
        "goal": [],
        "causation": [],
        "parent_episode": None,
        "segmentation": "proposed",
        "derived_from": ["heimdal.observations:obs-a"],
    }


@pytest.mark.pg
def test_emit_proposal_projection_sync_is_idempotent(scratch_db: str) -> None:
    """AC2: syncing the SAME ``episode_id`` twice (redelivery / crash-retry / a race with a
    concurrent rebuild) never errors and never duplicates -- exactly one row survives, and the
    columns still reflect the synced fields. Calls the sync helper directly (mirrors
    ``tests/episodes/test_closure.py``'s direct testing of ``_sync_projection_closed`` for the
    same reason: this pins the sync mechanism's own idempotency, distinct from
    ``_emit_proposal``'s separate file-exists idempotency guard)."""
    import psycopg

    episode_id = mint_episode_id()
    note_path = episode_note_rel_path(episode_id)
    fields = _episode_fields(episode_id)

    segmenter_module._sync_new_episode_row(fields, note_path)
    segmenter_module._sync_new_episode_row(fields, note_path)  # redelivered -- must not raise

    with psycopg.connect(scratch_db, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT episode_id, scope, note_path FROM episodes WHERE episode_id = %s",
            (episode_id,),
        ).fetchall()
    assert len(rows) == 1, rows
    assert rows[0][0] == episode_id
    assert rows[0][1] == "work"
    assert rows[0][2] == note_path


def test_sync_new_episode_row_logs_but_does_not_raise_on_db_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Constraint: this must never become a new hard dependency that can block episode note
    writes. A DB condition that would raise in the rebuild/closure path (missing table,
    connection failure) is logged and swallowed here instead -- the vault note (SoR) already
    landed regardless of what happens next. No Postgres needed: ``conn_rw`` is stubbed to raise
    directly, so this never touches a real database."""
    import logging

    def _boom(*a, **k):
        raise RuntimeError("scratch: simulated DB failure")

    monkeypatch.setattr(segmenter_module, "conn_rw", _boom)

    episode_id = mint_episode_id()
    note_path = episode_note_rel_path(episode_id)
    fields = _episode_fields(episode_id)

    with caplog.at_level(logging.WARNING):
        segmenter_module._sync_new_episode_row(fields, note_path)  # must not raise

    assert episode_id in caplog.text
