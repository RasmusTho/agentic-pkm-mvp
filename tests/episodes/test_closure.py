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
        lambda event, *, idempotency_key: emitted.append((event, idempotency_key)),
    )

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


def test_close_episode_already_closed_is_idempotent_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    def _boom(*a: Any, **k: Any) -> None:
        raise AssertionError("write_outbox_event must not be called for an already-closed episode")

    monkeypatch.setattr(closure_module, "write_outbox_event", _boom)

    candidate = EpisodeCloseCandidate(
        episode_id=episode_id, scope="work", note_path=episode_note_rel_path(episode_id), time_end=end
    )
    result = close_episode(candidate, vault_root=tmp_path, write_guard=_allow_guard())

    assert result is None


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
    # actual on-disk state -- proving idempotency is close_episode's own job (AC1: "closes once"),
    # not merely a query-side filter never re-offering it.
    monkeypatch.setattr(closure_module, "find_closable_episodes", lambda **k: [candidate])
    monkeypatch.setattr(closure_module, "_count_active_bound_artifacts", lambda eid: 0)
    emitted: list[Any] = []
    monkeypatch.setattr(
        closure_module,
        "write_outbox_event",
        lambda event, *, idempotency_key: emitted.append(idempotency_key),
    )

    first = run_closure_tick(vault_root=tmp_path, now=now, write_guard=_allow_guard())
    assert first == {"closed": [episode_id], "events_emitted": 1}
    assert len(emitted) == 1

    second = run_closure_tick(vault_root=tmp_path, now=now, write_guard=_allow_guard())
    assert second == {"closed": [], "events_emitted": 0}
    # No second event attempt at all -- close_episode's own already-closed guard short-circuits
    # before ever deriving a (would-be-identical) idempotency key.
    assert len(emitted) == 1

    from app.episodes.notes import parse_episode_note

    text = (tmp_path / episode_note_rel_path(episode_id)).read_text(encoding="utf-8")
    assert parse_episode_note(text)["time"]["closed"] is True
