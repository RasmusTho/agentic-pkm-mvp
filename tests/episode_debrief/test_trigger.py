"""All DEBRIEF-01 ACs and protected crash/concurrency floors on real PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
import subprocess
import sys
from threading import Event, current_thread

import pytest

from app.episode_debrief import trigger
from app.episode_debrief.trigger import DebriefReconciliationError, debrief_id_for_episode
from app.stores import episode_debrief as store

pytestmark = pytest.mark.pg


def test_eligible_closure_produces_exactly_one_trigger(debrief_db) -> None:
    eligible = debrief_db.episode(count=trigger.EPISODE_DEBRIEF_MIN_ARTIFACT_COUNT)
    trivial = debrief_db.episode(count=trigger.EPISODE_DEBRIEF_MIN_ARTIFACT_COUNT - 1)
    debrief_db.closure(eligible)
    debrief_db.closure(trivial, ordinal=2)
    summary = debrief_db.tick()
    assert summary["triggered"] == [debrief_id_for_episode(eligible)]
    assert summary["skipped_ineligible"] == 1
    assert [payload["episode_id"] for payload in debrief_db.triggers()] == [eligible]
    assert debrief_db.execute("SELECT payload->'meta'->>'payload_schema' FROM outbox "
                              "WHERE topic='debrief.trigger.created'") == [("debrief.trigger.created.v1",)]


def test_real_closure_producer_drives_debrief_consumer(debrief_db) -> None:
    from datetime import datetime, timezone
    from app.episodes.closure import EpisodeCloseCandidate, close_episode
    from app.write_guard import WriteGuard
    episode = debrief_db.episode(closed=False)
    candidate = EpisodeCloseCandidate(episode, "work", f"episodes/{episode}.md",
                                      datetime(2026, 10, 13, 9, tzinfo=timezone.utc))
    result = close_episode(candidate, vault_root=debrief_db.root,
                           write_guard=WriteGuard(lambda: {"state": "healthy"}))
    assert result is not None and result.event_emitted
    assert debrief_db.tick()["triggered"] == [debrief_id_for_episode(episode)]
    assert debrief_db.execute("SELECT payload->'meta'->>'payload_schema' FROM outbox "
                              "WHERE topic='episode.closed'") == [("episode.closed.v1",)]


def test_redelivered_closure_is_idempotent_at_consumer_entrypoint(debrief_db) -> None:
    episode = debrief_db.episode()
    debrief_db.closure(episode)
    debrief_db.tick()
    debrief_db.closure(episode, ordinal=2)
    assert debrief_db.tick()["triggered"] == []
    assert len(debrief_db.triggers()) == 1


@pytest.mark.parametrize("scope", ["work", "private", "fused-flow-123", " Scope-é "])
def test_trigger_scope_matches_episode_scope_no_widening(debrief_db, scope: str) -> None:
    episode = debrief_db.episode(scope=scope)
    # A stale event cannot override the current note's resolved scope.
    debrief_db.closure(episode, scope="stale-event-scope")
    debrief_db.tick()
    assert debrief_db.triggers()[0]["scope"] == scope


def test_open_episode_never_triggers(debrief_db) -> None:
    episode = debrief_db.episode(closed=False)
    debrief_db.closure(episode)
    # Also cover an obsolete closed projection after a human re-opened the note.
    debrief_db.execute("UPDATE episodes SET closed=true")
    assert debrief_db.tick()["skipped_open"] == 1
    assert debrief_db.triggers() == []


def test_partial_failure_after_trigger_is_retried_not_lost(debrief_db) -> None:
    episode = debrief_db.episode()
    debrief_db.closure(episode)
    debrief_db.tick()  # Downstream synthesis then fails before creating its artifact.
    cursor = store.get_cursor()
    recovered = debrief_db.tick()
    assert recovered["consumed"] == 0
    assert recovered["pending_debrief"] == [debrief_id_for_episode(episode)]
    assert len(debrief_db.triggers()) == 1
    assert store.get_cursor() == cursor


def test_emit_before_cursor_crash_and_retry(debrief_db, monkeypatch) -> None:
    episode = debrief_db.episode()
    frontier = debrief_db.closure(episode)
    original = trigger.write_outbox_event

    def crash_after_emit(*args, **kwargs):
        assert original(*args, **kwargs)
        raise RuntimeError("simulated process death after durable emission")

    with monkeypatch.context() as patch:
        patch.setattr(trigger, "write_outbox_event", crash_after_emit)
        with pytest.raises(RuntimeError, match="process death"):
            debrief_db.tick()
    assert store.get_cursor() is None
    assert len(debrief_db.triggers()) == 1
    assert debrief_db.tick()["pending_debrief"] == [debrief_id_for_episode(episode)]
    assert store.get_cursor().row_id == frontier
    assert len(debrief_db.triggers()) == 1


def test_cursor_write_failure_and_fresh_process_restart(debrief_db) -> None:
    import psycopg
    episode = debrief_db.episode()
    frontier = debrief_db.closure(episode)
    debrief_db.execute("""
        CREATE FUNCTION refuse_cursor() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'injected cursor storage failure'; END $$;
        CREATE TRIGGER refuse_cursor BEFORE INSERT OR UPDATE ON episode_engine_state
        FOR EACH ROW EXECUTE FUNCTION refuse_cursor();
    """)
    with pytest.raises(psycopg.errors.RaiseException, match="cursor storage failure"):
        debrief_db.tick()
    assert store.get_cursor() is None
    assert len(debrief_db.triggers()) == 1
    debrief_db.execute("DROP TRIGGER refuse_cursor ON episode_engine_state; DROP FUNCTION refuse_cursor()")
    code = (
        "import json; from pathlib import Path; from app.episode_debrief.trigger import run_debrief_tick; "
        "from app.write_guard import WriteGuard; "
        "print(json.dumps(run_debrief_tick(vault_root=Path(__import__('sys').argv[1]), "
        "write_guard=WriteGuard(lambda: {'state':'healthy'}))))"
    )
    restarted = subprocess.run([sys.executable, "-c", code, str(debrief_db.root)],
                               env=os.environ.copy(), text=True, capture_output=True, timeout=30, check=True)
    assert json.loads(restarted.stdout)["pending_debrief"] == [debrief_id_for_episode(episode)]
    assert store.get_cursor().row_id == frontier
    assert len(debrief_db.triggers()) == 1


def test_concurrent_stale_tick_cannot_regress_cursor(debrief_db, monkeypatch) -> None:
    episode = debrief_db.episode()
    first = debrief_db.closure(episode)
    final = debrief_db.closure(episode, ordinal=2)
    old_waiting, newer_finished = Event(), Event()
    advance = store.advance_cursor

    def delayed_advance(position, **kwargs):
        if current_thread().name.startswith("older"):
            assert position.row_id == first
            old_waiting.set()
            assert newer_finished.wait(10)
        advance(position, **kwargs)

    monkeypatch.setattr(store, "advance_cursor", delayed_advance)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="older") as pool:
        old = pool.submit(debrief_db.tick, limit=1)
        try:
            assert old_waiting.wait(10)
            debrief_db.tick()
            assert store.get_cursor().row_id == final
        finally:
            newer_finished.set()
        old.result(timeout=10)
    assert store.get_cursor().row_id == final
    assert len(debrief_db.triggers()) == 1


def test_equal_timestamp_uuid_frontier_is_atomic_and_monotone(debrief_db) -> None:
    from datetime import datetime, timezone
    instant = datetime(2026, 10, 13, tzinfo=timezone.utc)
    high = store.CursorPosition(instant, "ffffffff-ffff-ffff-ffff-ffffffffffff")
    low = store.CursorPosition(instant + timedelta(hours=2), "00000000-0000-0000-0000-000000000001")
    # Same instant with a different timezone spelling must compare as an instant.
    from datetime import timezone as tz
    equivalent_low = store.CursorPosition(instant.astimezone(tz(timedelta(hours=2))), low.row_id)
    store.advance_cursor(high)
    store.advance_cursor(equivalent_low)
    assert store.get_cursor() == high


def test_malformed_final_row_advances_only_after_successful_reconciliation(debrief_db) -> None:
    episode = debrief_db.episode()
    debrief_db.closure(episode)
    malformed = debrief_db.closure(episode, malformed=True, ordinal=2)
    first = debrief_db.tick()
    assert first["malformed_events"] == 1
    assert len(debrief_db.triggers()) == 1
    assert store.get_cursor().row_id == malformed
    assert debrief_db.tick()["consumed"] == 0


def test_failed_projection_reconciliation_does_not_ack_malformed_frontier(debrief_db) -> None:
    episode = debrief_db.episode()
    malformed = debrief_db.closure(episode, malformed=True)
    debrief_db.execute("UPDATE episodes SET note_path='../outside.md'")
    with pytest.raises(DebriefReconciliationError, match="outside"):
        debrief_db.tick()
    assert store.get_cursor() is None
    debrief_db.execute("UPDATE episodes SET note_path=%s", (f"episodes/{episode}.md",))
    debrief_db.tick()
    assert store.get_cursor().row_id == malformed


def test_bad_episode_does_not_suppress_unrelated_healthy_trigger(debrief_db) -> None:
    bad = debrief_db.episode(episode_id="ep-00000000-0000-4000-8000-000000000001")
    good = debrief_db.episode(episode_id="ep-00000000-0000-4000-8000-000000000002", scope="private")
    debrief_db.closure(bad, malformed=True)
    frontier = debrief_db.closure(good, ordinal=2, scope="private")
    debrief_db.execute("UPDATE episodes SET note_path='../outside.md' WHERE episode_id=%s", (bad,))
    with pytest.raises(DebriefReconciliationError, match="outside"):
        debrief_db.tick()
    assert store.get_cursor() is None
    assert [payload["episode_id"] for payload in debrief_db.triggers()] == [good]
    debrief_db.execute("UPDATE episodes SET note_path=%s WHERE episode_id=%s",
                       (f"episodes/{bad}.md", bad))
    debrief_db.tick()
    assert store.get_cursor().row_id == frontier
    assert {payload["episode_id"] for payload in debrief_db.triggers()} == {good, bad}


@pytest.mark.parametrize("linked", [False, True])
def test_existing_debrief_artifact_survives_closure_replay(debrief_db, linked: bool) -> None:
    from uuid import uuid4
    episode = "ep-" + str(uuid4())
    debrief = debrief_id_for_episode(episode)
    debrief_db.episode(episode_id=episode, debrief_ref=[debrief] if linked else None)
    artifact = debrief_db.root / "_system" / "episode-debriefs" / f"{debrief}.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("---\nreview_state: archived\n---\nExisting debrief.\n", encoding="utf-8")
    debrief_db.closure(episode)
    assert debrief_db.tick()["skipped_already_debriefed"] == 1
    debrief_db.closure(episode, ordinal=2)
    assert debrief_db.tick()["pending_debrief"] == []
    assert debrief_db.triggers() == []


def test_binding_isolation_and_reconciliation_without_event(debrief_db) -> None:
    from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
    episode = debrief_db.episode(count=2)
    debrief_db.episode(episode_id=episode, count=5, scope="private", binding="other-binding")
    debrief_db.closure(episode, binding="other-binding")
    assert debrief_db.tick()["consumed"] == 0
    assert debrief_db.triggers() == []
    debrief_db.execute("INSERT INTO episode_artifact_binding VALUES (%s, 'artifact-extra', %s, 'active')",
                       (COMPATIBILITY_BINDING_ID, episode))
    assert debrief_db.tick()["triggered"] == [debrief_id_for_episode(episode)]
    assert debrief_db.triggers()[0]["scope"] == "work"


def test_production_cli_tick_is_registered_and_uses_real_consumer(debrief_db, monkeypatch) -> None:
    from click.testing import CliRunner
    from app.cli import cli
    monkeypatch.setattr(trigger.DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    episode = debrief_db.episode()
    debrief_db.closure(episode)
    result = CliRunner().invoke(cli, ["episode-debrief", "tick", "--vault-root", str(debrief_db.root), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["triggered"] == [debrief_id_for_episode(episode)]
    assert len(debrief_db.triggers()) == 1
