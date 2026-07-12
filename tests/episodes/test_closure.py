"""Episode closure detection + ``episode.closed`` emission tests (ERE-06, #3181).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md``.

- AC1: a quiesced open episode flips ``closed: true`` and emits exactly one idempotent
  ``episode.closed`` event; a still-active episode does not close. Verify:
  ``test_quiesced_episode_closes_once`` (+ ``test_find_closable_episodes_filters_by_quiescence``
  for the "still-active does not close" half).

No live Postgres needed: DB reads/writes are stubbed at the module-function boundary (the same
monkeypatch discipline ``tests/episodes/test_segmentation_core.py`` / ``test_assignment.py``
already establish for this engine) -- only the real vault-note write path (tmp_path) runs for real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.episodes import closure as closure_module
from app.episodes.closure import (
    EPISODE_CLOSURE_QUIESCENCE_MINUTES,
    EpisodeCloseCandidate,
    close_episode,
    find_closable_episodes,
    run_closure_tick,
)
from app.episodes.notes import episode_note_rel_path
from app.episodes.store import write_episode_note
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _dt(hour: int, minute: int = 0, day: int = 11) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


def _write_open_episode_note(
    tmp_path: Path, *, episode_id: str, scope: str = "work", end: datetime
) -> None:
    write_episode_note(
        title="Debugging session",
        scope=scope,
        start=(end - timedelta(hours=1)).isoformat(),
        end=end.isoformat(),
        closed=False,
        segmentation="proposed",
        episode_id=episode_id,
        vault_root=tmp_path,
        write_guard=_allow_guard(),
    )


class _RegclassCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self._result: Any = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if "to_regclass" in sql:
            self._result = ("episodes",)
        elif "FROM episodes" in sql:
            self._result = list(self._rows)
        else:  # pragma: no cover -- defensive
            raise AssertionError(f"unexpected SQL in fake cursor: {sql}")

    def fetchone(self):
        return self._result if not isinstance(self._result, list) else None

    def fetchall(self):
        return self._result if isinstance(self._result, list) else []


class _RegclassConn:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _RegclassCursor(self._rows)


class _SyncCursor:
    """Fake cursor for ``_sync_projection_closed``: answers the ``to_regclass`` schema
    preflight, then records + simulates the incremental ``UPDATE ... SET closed = true`` --
    ``rowcount`` is 1 when ``episode_id`` is a member of ``existing_ids`` (projection has a row
    for it), 0 otherwise (simulates a truncated/missing projection row)."""

    def __init__(self, existing_ids: set[str], calls: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._existing_ids = existing_ids
        self._calls = calls
        self.rowcount = 0
        self._result: Any = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._calls.append((sql, params))
        if "to_regclass" in sql:
            self._result = ("episodes",)
        elif sql.strip().upper().startswith("UPDATE"):
            episode_id = params[0]
            self.rowcount = 1 if episode_id in self._existing_ids else 0
        else:  # pragma: no cover -- defensive
            raise AssertionError(f"unexpected SQL in fake sync cursor: {sql}")

    def fetchone(self):
        return self._result


class _SyncConn:
    """Fake ``conn_rw()`` context manager backing :class:`_SyncCursor`. Records every executed
    statement on ``.calls`` so tests can assert the incremental-UPDATE shape directly."""

    def __init__(self, existing_ids: set[str]) -> None:
        self._existing_ids = existing_ids
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _SyncCursor(self._existing_ids, self.calls)


# ---------------------------------------------------------------------------
# AC1 (still-active half): quiescence filtering is pure Python-side comparison
# ---------------------------------------------------------------------------


def test_find_closable_episodes_filters_by_quiescence(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _dt(12, 0)
    quiesced_end = now - timedelta(minutes=EPISODE_CLOSURE_QUIESCENCE_MINUTES + 1)
    still_active_end = now - timedelta(minutes=1)

    rows = [
        ("ep-11111111-2222-4333-8444-555555555555", "work", quiesced_end, "episodes/ep-1.md"),
        ("ep-22222222-2222-4333-8444-555555555555", "work", still_active_end, "episodes/ep-2.md"),
    ]
    monkeypatch.setattr(closure_module, "conn_rw", lambda *a, **k: _RegclassConn(rows))

    candidates = find_closable_episodes(now=now)

    assert [c.episode_id for c in candidates] == ["ep-11111111-2222-4333-8444-555555555555"]


# ---------------------------------------------------------------------------
# AC1: close_episode flips closed + emits exactly one event; idempotent no-op if already closed
# ---------------------------------------------------------------------------


def test_close_episode_flips_closed_and_emits_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode_id = "ep-33333333-2222-4333-8444-555555555555"
    end = _dt(10, 0)
    _write_open_episode_note(tmp_path, episode_id=episode_id, end=end)

    monkeypatch.setattr(closure_module, "_count_active_bound_artifacts", lambda eid: 3)
    emitted: list[tuple[Any, str]] = []
    monkeypatch.setattr(
        closure_module,
        "write_outbox_event",
        lambda event, *, idempotency_key: (emitted.append((event, idempotency_key)) or idempotency_key),
    )
    sync_conn = _SyncConn({episode_id})
    monkeypatch.setattr(closure_module, "conn_rw", lambda *a, **k: sync_conn)

    candidate = EpisodeCloseCandidate(
        episode_id=episode_id, scope="work", note_path=episode_note_rel_path(episode_id), time_end=end
    )
    result = close_episode(candidate, vault_root=tmp_path, write_guard=_allow_guard())

    assert result is not None
    assert result.episode_id == episode_id
    assert result.event_emitted is True

    from app.episodes.notes import parse_episode_note

    text = (tmp_path / episode_note_rel_path(episode_id)).read_text(encoding="utf-8")
    fields = parse_episode_note(text)
    assert fields["time"]["closed"] is True
    # Everything else survives the rewrite untouched.
    assert fields["scope"] == "work"
    assert fields["segmentation"] == "proposed"

    assert len(emitted) == 1
    event, idempotency_key = emitted[0]
    assert event.event_type == "episode.closed"
    assert event.payload["episode_id"] == episode_id
    assert event.payload["scope"] == "work"
    assert event.payload["bound_artifact_count"] == 3
    assert isinstance(idempotency_key, str) and idempotency_key

    # #3181 review fix P1-1: close_episode must ALSO keep the `episodes` projection's `closed`
    # column current itself -- production retrieval (closure_decay.read_closed_episode_ids) reads
    # THAT column, never the vault note directly, and nothing else refreshes it incrementally.
    update_calls = [c for c in sync_conn.calls if c[0].strip().upper().startswith("UPDATE")]
    assert len(update_calls) == 1
    assert update_calls[0][1] == (episode_id,)


def test_close_episode_already_closed_note_reconciles_outbox_and_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3181 review fix P1-2: an already-closed note is exactly the shape a crash-recovery retry
    sees (a prior call flipped the note but died before the outbox write and/or the projection
    sync landed). The note must never be rewritten twice, but the outbox emission and the
    projection sync must STILL be attempted -- both are idempotent, so a genuine retry converges
    instead of a lost event/projection update, and a genuine no-op race (another tick already
    finished everything) costs one deduped insert + one idempotent UPDATE."""
    episode_id = "ep-44444444-2222-4333-8444-555555555555"
    end = _dt(10, 0)
    write_episode_note(
        title="Already closed",
        scope="work",
        start=(end - timedelta(hours=1)).isoformat(),
        end=end.isoformat(),
        closed=True,
        segmentation="proposed",
        episode_id=episode_id,
        vault_root=tmp_path,
        write_guard=_allow_guard(),
    )

    def _boom_on_rewrite(*a: Any, **k: Any) -> None:
        raise AssertionError("write_episode_note must not be called for an already-closed note")

    monkeypatch.setattr(closure_module, "write_episode_note", _boom_on_rewrite)
    monkeypatch.setattr(closure_module, "_count_active_bound_artifacts", lambda eid: 0)

    emitted: list[str] = []
    monkeypatch.setattr(
        closure_module,
        "write_outbox_event",
        lambda event, *, idempotency_key: (emitted.append(idempotency_key) or idempotency_key),
    )
    sync_conn = _SyncConn({episode_id})
    monkeypatch.setattr(closure_module, "conn_rw", lambda *a, **k: sync_conn)

    candidate = EpisodeCloseCandidate(
        episode_id=episode_id, scope="work", note_path=episode_note_rel_path(episode_id), time_end=end
    )
    result = close_episode(candidate, vault_root=tmp_path, write_guard=_allow_guard())

    # NOT None: the crash-recovery/reconciliation path is a real completion, not a no-op.
    assert result is not None
    assert result.episode_id == episode_id
    assert result.event_emitted is True

    assert len(emitted) == 1
    update_calls = [c for c in sync_conn.calls if c[0].strip().upper().startswith("UPDATE")]
    assert len(update_calls) == 1
    assert update_calls[0][1] == (episode_id,)


# ---------------------------------------------------------------------------
# AC1 headline: a quiesced episode closes once (idempotent across ticks)
# ---------------------------------------------------------------------------


def test_quiesced_episode_closes_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    episode_id = "ep-55555555-2222-4333-8444-555555555555"
    now = _dt(12, 0)
    quiesced_end = now - timedelta(minutes=EPISODE_CLOSURE_QUIESCENCE_MINUTES + 30)
    _write_open_episode_note(tmp_path, episode_id=episode_id, end=quiesced_end)

    candidate = EpisodeCloseCandidate(
        episode_id=episode_id,
        scope="work",
        note_path=episode_note_rel_path(episode_id),
        time_end=quiesced_end,
    )
    # find_closable_episodes offers the SAME candidate on every tick regardless of the note's
    # actual on-disk state -- this is deliberately the crash-recovery replay shape (#3181 review
    # fix P1-2): in production this only happens while the `episodes` projection still reads
    # `closed = false` for this episode_id, i.e. exactly while there is still unfinished
    # outbox/projection work to retry.
    monkeypatch.setattr(closure_module, "find_closable_episodes", lambda **k: [candidate])
    monkeypatch.setattr(closure_module, "_count_active_bound_artifacts", lambda eid: 0)

    seen_keys: set[str] = set()
    inserted: list[str] = []

    def _fake_write_outbox_event(event: Any, *, idempotency_key: str) -> str:
        # Mirrors app.services.outbox.write_outbox_event's real `ON CONFLICT (id) DO NOTHING`
        # semantics: the FIRST insert of a given (fixed) idempotency key lands and returns the
        # key; every later attempt with the SAME key is a deduped no-op returning "".
        if idempotency_key in seen_keys:
            return ""
        seen_keys.add(idempotency_key)
        inserted.append(idempotency_key)
        return idempotency_key

    monkeypatch.setattr(closure_module, "write_outbox_event", _fake_write_outbox_event)

    synced: list[str] = []
    monkeypatch.setattr(closure_module, "_sync_projection_closed", lambda eid: synced.append(eid))

    first = run_closure_tick(vault_root=tmp_path, now=now, write_guard=_allow_guard())
    assert first == {"closed": [episode_id], "events_emitted": 1}
    assert inserted == [inserted[0]]  # exactly one genuine insert
    assert len(inserted) == 1

    second = run_closure_tick(vault_root=tmp_path, now=now, write_guard=_allow_guard())
    # The note is not rewritten twice and no SECOND outbox row is ever inserted (dedup keeps
    # events_emitted at 0), but close_episode is still called and still ensures the projection
    # sync is (re)attempted -- proving the crash-recovery replay path actually retries instead of
    # short-circuiting to a hard no-op.
    assert second == {"closed": [episode_id], "events_emitted": 0}
    assert len(inserted) == 1
    assert synced == [episode_id, episode_id]

    from app.episodes.notes import parse_episode_note

    text = (tmp_path / episode_note_rel_path(episode_id)).read_text(encoding="utf-8")
    assert parse_episode_note(text)["time"]["closed"] is True


# ---------------------------------------------------------------------------
# #3181 review fix P1-1: _sync_projection_closed issues a targeted incremental UPDATE
# ---------------------------------------------------------------------------


def test_sync_projection_closed_issues_incremental_update(monkeypatch: pytest.MonkeyPatch) -> None:
    episode_id = "ep-66666666-2222-4333-8444-555555555555"
    conn = _SyncConn({episode_id})
    monkeypatch.setattr(closure_module, "conn_rw", lambda *a, **k: conn)

    closure_module._sync_projection_closed(episode_id)

    update_calls = [c for c in conn.calls if c[0].strip().upper().startswith("UPDATE")]
    assert len(update_calls) == 1
    sql, params = update_calls[0]
    assert "SET closed = true" in sql
    assert params == (episode_id,)
    # Never a TRUNCATE+replay -- this must stay a targeted single-row update, not a rebuild.
    assert not any("TRUNCATE" in c[0].upper() for c in conn.calls)


def test_sync_projection_closed_logs_but_does_not_raise_on_missing_row(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    conn = _SyncConn(set())  # no matching row -- e.g. a concurrent rebuild truncated it
    monkeypatch.setattr(closure_module, "conn_rw", lambda *a, **k: conn)

    with caplog.at_level("WARNING"):
        closure_module._sync_projection_closed("ep-missing-from-projection")

    assert any("no row for" in record.message for record in caplog.records)
