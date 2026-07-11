"""Two-Stream Segmentation Core tests (ERE-04, #3179).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/TWO_STREAM_SEGMENTATION_CORE.md``.
Covers the governing Issue's behavioral Acceptance Criteria against the pure
segmentation core (:func:`app.episodes.segmenter.fold_signals_into_segments`)
and the emission seam (:func:`app.episodes.segmenter._emit_proposal`), which
together are what the production tick (``run_segmentation_tick``) composes
with live stream I/O. The pure core needs no vault/DB, so these tests run in
the ``not pg`` lane; emission tests use a `tmp_path` vault the same way
``tests/episodes/test_episode_store.py`` does.

- ``test_two_stream_fixture_segments_into_expected_episodes`` (AC1): two
  Heimdal sessions + interleaved vault edits, separated by a >45 min gap,
  segment into exactly two episodes with correct bitemporal bounds and
  complete ``derived_from``.
- ``test_segmentation_idempotent_under_redelivery`` (AC2): redelivered
  signals (cursor replay / crash-before-cursor-advance) never double-fold or
  double-propose.
- ``test_heimdal_session_hint_respected`` (AC3): a Heimdal per-session id
  keeps its observations in one segment even across a shift that would
  otherwise split them; a differing session id does not get this protection.
- ``test_segments_keyed_per_scope_by_default`` (AC7): signals partition
  strictly per-scope, including the unscoped ("default") bucket, never
  cross-scope fused.
- ``test_proposals_are_schema_valid_proposal_class`` (AC5): every emitted
  note passes the episode-note schema and carries ``segmentation: proposed``.

No network, no Postgres, no real vault beyond ``tmp_path``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.episodes.notes import episode_note_rel_path, parse_episode_note
from app.episodes.schema import validate_episode_note_fields
from app.episodes.segmenter import (
    SegmentationSignal,
    _emit_proposal,
    fold_signals_into_segments,
)
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _dt(hour: int, minute: int, day: int = 11) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


def _signal(
    *,
    stream_id: str = "heimdal.observations",
    signal_id: str,
    observed_at: datetime,
    scope: str = "work",
    protagonists: tuple[str, ...] = (),
    goal: tuple[str, ...] = (),
    heimdal_session_id: str | None = None,
    causal_break: bool = False,
) -> SegmentationSignal:
    return SegmentationSignal(
        stream_id=stream_id,
        signal_id=signal_id,
        observed_at=observed_at,
        scope=scope,
        provenance_ref=f"{stream_id}:{signal_id}",
        protagonists=protagonists,
        goal=goal,
        heimdal_session_id=heimdal_session_id,
        causal_break=causal_break,
    )


# ---------------------------------------------------------------------------
# AC1: two-stream fixture segments into exactly two episodes
# ---------------------------------------------------------------------------


def test_two_stream_fixture_segments_into_expected_episodes() -> None:
    session_a = [
        _signal(signal_id="obs-a1", observed_at=_dt(9, 0), protagonists=("alice",), heimdal_session_id="sess-a"),
        _signal(signal_id="obs-a2", observed_at=_dt(9, 5), protagonists=("alice",), heimdal_session_id="sess-a"),
    ]
    vault_a = [
        _signal(stream_id="vault.activity", signal_id="vault-a1", observed_at=_dt(9, 7), goal=("proj-x",)),
    ]
    # >45 min gap between 09:07 (last signal of segment A) and 10:00 (first of segment B).
    session_b = [
        _signal(signal_id="obs-b1", observed_at=_dt(10, 0), protagonists=("alice",), heimdal_session_id="sess-b"),
        _signal(signal_id="obs-b2", observed_at=_dt(10, 3), protagonists=("alice",), heimdal_session_id="sess-b"),
    ]
    vault_b = [
        _signal(stream_id="vault.activity", signal_id="vault-b1", observed_at=_dt(10, 5), goal=("proj-x",)),
    ]
    signals = session_a + vault_a + session_b + vault_b

    # `now` well past the last signal so both segments are stale and close in one fold.
    updated_open, closed = fold_signals_into_segments(signals, open_segments=None, now=_dt(11, 0))

    assert updated_open == {}
    assert len(closed) == 2
    first, second = sorted(closed, key=lambda c: c.start)

    assert first.start == _dt(9, 0)
    assert first.end == _dt(9, 7)
    assert set(first.derived_from) == {
        "heimdal.observations:obs-a1",
        "heimdal.observations:obs-a2",
        "vault.activity:vault-a1",
    }

    assert second.start == _dt(10, 0)
    assert second.end == _dt(10, 5)
    assert set(second.derived_from) == {
        "heimdal.observations:obs-b1",
        "heimdal.observations:obs-b2",
        "vault.activity:vault-b1",
    }


# ---------------------------------------------------------------------------
# AC2: idempotent under at-least-once redelivery
# ---------------------------------------------------------------------------


def test_segmentation_idempotent_under_redelivery() -> None:
    signals = [
        _signal(signal_id="obs-1", observed_at=_dt(9, 0), protagonists=("alice",), heimdal_session_id="sess-a"),
        _signal(signal_id="obs-2", observed_at=_dt(9, 5), protagonists=("alice",), heimdal_session_id="sess-a"),
    ]

    # First fold: the segment stays open (now is close to the last signal).
    open_after_first, closed_after_first = fold_signals_into_segments(signals, open_segments=None, now=_dt(9, 10))
    assert closed_after_first == []
    assert set(open_after_first) == {"work"}
    first_state = open_after_first["work"]

    # Redelivery: the exact same batch (cursor never advanced) folded again
    # against the carried-over open-segment state must be a pure no-op.
    open_after_replay, closed_after_replay = fold_signals_into_segments(
        signals, open_segments=open_after_first, now=_dt(9, 10)
    )
    assert closed_after_replay == []
    replay_state = open_after_replay["work"]
    assert replay_state.derived_from == first_state.derived_from
    assert replay_state.signal_ids == first_state.signal_ids
    assert replay_state.start == first_state.start
    assert replay_state.last_signal_at == first_state.last_signal_at

    # Emission-level idempotency: closing the segment and writing its note
    # twice (simulating a crash between note-write and cursor-advance) must
    # never double-propose.
    _, closed = fold_signals_into_segments(signals, open_segments=None, now=_dt(10, 0))
    assert len(closed) == 1


def test_emission_idempotent_under_redelivery(tmp_path: Path) -> None:
    signals = [
        _signal(signal_id="obs-1", observed_at=_dt(9, 0), protagonists=("alice",), heimdal_session_id="sess-a"),
        _signal(signal_id="obs-2", observed_at=_dt(9, 5), protagonists=("alice",), heimdal_session_id="sess-a"),
    ]
    vault_root = tmp_path / "vault"
    guard = _allow_guard()

    _, closed_first = fold_signals_into_segments(signals, open_segments=None, now=_dt(10, 0))
    assert len(closed_first) == 1
    first_id = _emit_proposal(closed_first[0], vault_root=vault_root, write_guard=guard)
    assert first_id is not None

    # A full replay from cursor zero re-derives the SAME closed segment
    # (deterministic) -- re-emitting it must detect the existing note and
    # skip, never write a second one.
    _, closed_second = fold_signals_into_segments(signals, open_segments=None, now=_dt(10, 0))
    second_id = _emit_proposal(closed_second[0], vault_root=vault_root, write_guard=guard)
    assert second_id is None

    notes = list((vault_root / "episodes").glob("*.md"))
    assert len(notes) == 1


# ---------------------------------------------------------------------------
# AC3: Heimdal per-session episode_id is respected as a boundary hint
# ---------------------------------------------------------------------------


def test_heimdal_session_hint_respected() -> None:
    # Same session id across a protagonist shift that would otherwise split
    # the segment -- the session hint must keep them together.
    same_session = [
        _signal(signal_id="s1", observed_at=_dt(9, 0), protagonists=("alice",), heimdal_session_id="sess-a"),
        _signal(signal_id="s2", observed_at=_dt(9, 2), protagonists=("bob",), heimdal_session_id="sess-a"),
    ]
    open_segments, closed = fold_signals_into_segments(same_session, open_segments=None, now=_dt(9, 3))
    assert closed == []
    assert set(open_segments) == {"work"}
    segment = open_segments["work"]
    assert segment.protagonists == frozenset({"alice", "bob"})
    assert segment.signal_ids == frozenset({"s1", "s2"})

    # Contrast: the same protagonist-disjoint pair WITHOUT a shared session
    # id is not protected -- the protagonist shift fires and splits them.
    different_session = [
        _signal(signal_id="d1", observed_at=_dt(9, 0), protagonists=("alice",), heimdal_session_id="sess-a"),
        _signal(signal_id="d2", observed_at=_dt(9, 2), protagonists=("bob",), heimdal_session_id="sess-b"),
    ]
    open_segments_2, closed_2 = fold_signals_into_segments(different_session, open_segments=None, now=_dt(9, 3))
    assert len(closed_2) == 1
    assert closed_2[0].derived_from == ("heimdal.observations:d1",)
    assert set(open_segments_2) == {"work"}
    assert open_segments_2["work"].derived_from == ("heimdal.observations:d2",)

    # One session's observations never end up split across two proposed
    # episodes, even when interleaved with a later, unrelated session.
    interleaved = [
        _signal(signal_id="i1", observed_at=_dt(9, 0), heimdal_session_id="sess-x"),
        _signal(signal_id="i2", observed_at=_dt(9, 1), heimdal_session_id="sess-x"),
        _signal(signal_id="i3", observed_at=_dt(9, 2), heimdal_session_id="sess-x"),
    ]
    _, closed_3 = fold_signals_into_segments(interleaved, open_segments=None, now=_dt(9, 3))
    assert closed_3 == []  # still open, but never split mid-session


# ---------------------------------------------------------------------------
# AC7: signals lacking scope context never cross-scope fuse
# ---------------------------------------------------------------------------


def test_segments_keyed_per_scope_by_default() -> None:
    signals = [
        _signal(signal_id="w1", observed_at=_dt(9, 0), scope="work", protagonists=("alice",)),
        _signal(signal_id="p1", observed_at=_dt(9, 1), scope="personal", protagonists=("alice",)),
        _signal(signal_id="u1", observed_at=_dt(9, 2), scope="default", protagonists=("alice",)),
    ]
    open_segments, closed = fold_signals_into_segments(signals, open_segments=None, now=_dt(9, 3))

    assert closed == []
    assert set(open_segments) == {"work", "personal", "default"}
    assert open_segments["work"].derived_from == ("heimdal.observations:w1",)
    assert open_segments["personal"].derived_from == ("heimdal.observations:p1",)
    assert open_segments["default"].derived_from == ("heimdal.observations:u1",)

    # A later signal sharing the same near-identical time/protagonist context
    # but a distinct scope still starts its own segment -- proves partitioning
    # is by scope, not merely by arrival order.
    open_segments_2, _ = fold_signals_into_segments(
        [_signal(signal_id="w2", observed_at=_dt(9, 4), scope="work", protagonists=("alice",))],
        open_segments=open_segments,
        now=_dt(9, 5),
    )
    assert open_segments_2["work"].derived_from == ("heimdal.observations:w1", "heimdal.observations:w2")
    assert open_segments_2["personal"].derived_from == ("heimdal.observations:p1",)
    assert open_segments_2["default"].derived_from == ("heimdal.observations:u1",)


# ---------------------------------------------------------------------------
# AC5: proposals are schema-valid, proposal-class notes
# ---------------------------------------------------------------------------


def test_proposals_are_schema_valid_proposal_class(tmp_path: Path) -> None:
    signals = [
        _signal(signal_id="obs-1", observed_at=_dt(9, 0), protagonists=("alice",), goal=("proj-x",)),
        _signal(signal_id="obs-2", observed_at=_dt(9, 5), protagonists=("alice",), goal=("proj-x",)),
    ]
    vault_root = tmp_path / "vault"
    _, closed = fold_signals_into_segments(signals, open_segments=None, now=_dt(10, 0))
    assert len(closed) == 1

    episode_id = _emit_proposal(closed[0], vault_root=vault_root, write_guard=_allow_guard())
    assert episode_id is not None

    note_path = vault_root / episode_note_rel_path(episode_id)
    fields = parse_episode_note(note_path.read_text(encoding="utf-8"))
    validate_episode_note_fields(fields)  # raises on any schema violation

    assert fields["segmentation"] == "proposed"
    assert fields["episode_id"] == episode_id
    assert fields["time"]["closed"] is False
    assert "derived_from" in fields and set(fields["derived_from"]) == {
        "heimdal.observations:obs-1",
        "heimdal.observations:obs-2",
    }
    # Proposal class: no DecisionToken/AuthorityReceipt-shaped fields leak
    # onto the note (INV-ERE-B).
    assert "decision_token" not in fields
    assert "authority_receipt" not in fields
