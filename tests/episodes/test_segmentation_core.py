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
  otherwise split them -- including under cross-stream delivery lag (PR
  #3508 review: quiescence closure is measured against a PER-SCOPE
  observed-time frontier, never wall-clock and never a cross-scope frontier,
  so a sibling scope's progress can never close another scope's segment and
  one session -- always within a single scope -- is never split).
- ``test_sibling_scope_progress_never_closes_segment`` (PR #3508 review
  round 2): a single batch carrying two DIFFERENT scopes must not let one
  scope's later observed instant close the other scope's just-created
  segment; only a scope's OWN frontier advancing past the gap closes it.
- ``test_segments_keyed_per_scope_by_default`` (AC7): signals partition
  strictly per-scope, including the unscoped ("default") bucket, never
  cross-scope fused.
- ``test_proposals_are_schema_valid_proposal_class`` (AC5): every emitted
  note passes the episode-note schema and carries ``segmentation: proposed``.

Plus PR #3508 review round 1 regressions: out-of-order start widening,
observation-time (never emission-time) adapter posture, vault-root
containment for ingest-time absolute paths, and the engine-state schema
preflight.

No network, no Postgres, no real vault beyond ``tmp_path``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.episodes import segmenter
from app.episodes.engine_state import EngineStateSchemaMissingError, _assert_schema
from app.episodes.notes import episode_note_rel_path, parse_episode_note
from app.episodes.schema import validate_episode_note_fields
from app.episodes.segmenter import (
    HEIMDAL_STREAM_ID,
    ClosedSegment,
    SegmentationSignal,
    _deterministic_episode_id,
    _emit_proposal,
    _parse_observation_time,
    _signal_from_heimdal_row,
    _signal_from_vault_activity_row,
    fold_signals_into_segments,
    run_segmentation_tick,
)
from app.episodes.vault_activity_stream import VaultActivityRow, resolve_activity_dimensions
from app.heimdal.observation_log import ObservationRow
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _no_closure_candidates(monkeypatch: pytest.MonkeyPatch):
    """ERE-06 (#3181) extended ``run_segmentation_tick`` with an unconditional closure step
    (``app.episodes.closure.run_closure_tick``) that reads the ``episodes`` DB projection. These
    ERE-04 tests predate closure and don't exercise it -- default to zero candidates so every
    existing ``run_segmentation_tick`` call here stays a ``not pg`` test; closure's own tests
    (``tests/episodes/test_closure.py``) override this explicitly."""
    import app.episodes.closure as closure_module

    monkeypatch.setattr(closure_module, "find_closable_episodes", lambda **k: [])


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


def _scope_frontier(dt: datetime, scope: str = "work") -> dict[str, datetime]:
    """The per-scope observed frontier the pure fold now closes against: a
    segment in ``scope`` goes quiescent only when ``scope``'s OWN observed
    head has moved more than the gap past its last signal."""
    return {scope: dt}


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

    # All signals are scope 'work'; the scope's observed frontier is well past
    # the last signal, so both segments are quiescent and close in one fold.
    updated_open, closed = fold_signals_into_segments(
        signals, open_segments=None, frontiers=_scope_frontier(_dt(11, 0))
    )

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

    # First fold: the segment stays open (no frontier evidence of quiescence).
    open_after_first, closed_after_first = fold_signals_into_segments(signals, open_segments=None, frontiers={})
    assert closed_after_first == []
    assert set(open_after_first) == {"work"}
    first_state = open_after_first["work"]

    # Redelivery: the exact same batch (cursor never advanced) folded again
    # against the carried-over open-segment state must be a pure no-op.
    open_after_replay, closed_after_replay = fold_signals_into_segments(
        signals, open_segments=open_after_first, frontiers={}
    )
    assert closed_after_replay == []
    replay_state = open_after_replay["work"]
    assert replay_state.derived_from == first_state.derived_from
    assert replay_state.signal_ids == first_state.signal_ids
    assert replay_state.start == first_state.start
    assert replay_state.last_signal_at == first_state.last_signal_at

    # Quiescence: with scope 'work's frontier observedly >45min past the last
    # signal, the segment closes -- exactly once.
    _, closed = fold_signals_into_segments(signals, open_segments=None, frontiers=_scope_frontier(_dt(10, 0)))
    assert len(closed) == 1


def test_emission_idempotent_under_redelivery(tmp_path: Path) -> None:
    signals = [
        _signal(signal_id="obs-1", observed_at=_dt(9, 0), protagonists=("alice",), heimdal_session_id="sess-a"),
        _signal(signal_id="obs-2", observed_at=_dt(9, 5), protagonists=("alice",), heimdal_session_id="sess-a"),
    ]
    vault_root = tmp_path / "vault"
    guard = _allow_guard()

    frontiers = _scope_frontier(_dt(10, 0))
    _, closed_first = fold_signals_into_segments(signals, open_segments=None, frontiers=frontiers)
    assert len(closed_first) == 1
    first_id = _emit_proposal(closed_first[0], vault_root=vault_root, write_guard=guard)
    assert first_id is not None

    # A full replay from cursor zero re-derives the SAME closed segment
    # (deterministic) -- re-emitting it must detect the existing note and
    # skip, never write a second one. This is also the assertion the
    # migration's recovery posture leans on: full both-stream replay from
    # event zero cannot double-propose.
    _, closed_second = fold_signals_into_segments(signals, open_segments=None, frontiers=frontiers)
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
    open_segments, closed = fold_signals_into_segments(same_session, open_segments=None, frontiers={})
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
    open_segments_2, closed_2 = fold_signals_into_segments(different_session, open_segments=None, frontiers={})
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
    _, closed_3 = fold_signals_into_segments(interleaved, open_segments=None, frontiers={})
    assert closed_3 == []  # still open, but never split mid-session


def test_session_never_split_by_delivery_lag() -> None:
    """PR #3508 review: quiescence closure is measured against a PER-SCOPE
    observed-time frontier -- a session-bound segment in scope 'work' closes
    only when scope 'work's OWN observed head moves past the gap. Another
    scope's frontier racing ahead (or wall-clock ticks passing) while the
    session's later observations are still in flight must never split the
    session. The mechanism is now 'scope work's own frontier has not
    advanced', not 'the Heimdal stream frontier lagged'."""
    # Tick 1: session sess-a starts at 09:00.
    tick1 = [
        _signal(signal_id="s1", observed_at=_dt(9, 0), heimdal_session_id="sess-a"),
    ]
    open_1, closed_1 = fold_signals_into_segments(tick1, open_segments=None, frontiers=_scope_frontier(_dt(9, 0)))
    assert closed_1 == []

    # Tick 2: NO scope-'work' delivery (lag), but vault activity in ANOTHER
    # scope has observedly moved to 10:30 -- >45min past the session's last
    # signal. The session-bound segment must NOT close: scope 'work' has no
    # frontier entry this tick, so its own head has not advanced.
    other_scope = [
        _signal(
            stream_id="vault.activity",
            signal_id="v-other",
            observed_at=_dt(10, 30),
            scope="personal",
        ),
    ]
    open_2, closed_2 = fold_signals_into_segments(
        other_scope, open_segments=open_1, frontiers={"personal": _dt(10, 30)}
    )
    assert closed_2 == []
    assert "work" in open_2  # sess-a segment survived the sibling scope's lag

    # Tick 3: the delayed sess-a observations (observed 10:00, >45min after
    # 09:00) finally arrive. Same session -> extends, never a new segment.
    late_same_session = [
        _signal(signal_id="s2", observed_at=_dt(10, 0), heimdal_session_id="sess-a"),
    ]
    open_3, closed_3 = fold_signals_into_segments(
        late_same_session,
        open_segments=open_2,
        frontiers={"work": _dt(10, 0), "personal": _dt(10, 30)},
    )
    assert closed_3 == []
    assert open_3["work"].signal_ids == frozenset({"s1", "s2"})

    # Tick 4: scope 'work's own frontier finally moves observedly past the
    # session -> ONE closed segment carrying the whole session.
    open_4, closed_4 = fold_signals_into_segments(
        [],
        open_segments=open_3,
        frontiers={"work": _dt(11, 0), "personal": _dt(10, 30)},
    )
    assert "work" not in open_4
    session_closed = [c for c in closed_4 if c.scope == "work"]
    assert len(session_closed) == 1
    assert set(session_closed[0].derived_from) == {
        "heimdal.observations:s1",
        "heimdal.observations:s2",
    }


# ---------------------------------------------------------------------------
# PR #3508 review round 2: per-scope closure frontier isolation
# ---------------------------------------------------------------------------


def test_sibling_scope_progress_never_closes_segment() -> None:
    """PR #3508 review round 2 (comment 3565317992): the quiescence frontier
    is PER-SCOPE, not the tick-wide max across scopes. A single batch on the
    SAME Heimdal stream carrying two DIFFERENT scopes must not let the later
    scope's observed instant close the other scope's just-created segment --
    otherwise a sibling scope's progress closes scope 'work's segment in the
    same tick, and because sess-a's own session can continue in a LATER tick
    the closed session reopens as a second proposal (AC3 violation)."""
    # One batch: scope 'work'/sess-a at 09:00 and scope 'other'/sess-b at
    # 09:50 -- 09:50-09:00 = 50min > the 45min gap. Under a tick-wide (max
    # across scopes) frontier this WOULD close 'work'; under per-scope it
    # must not.
    batch = [
        _signal(signal_id="s1", observed_at=_dt(9, 0), scope="work", heimdal_session_id="sess-a"),
        _signal(signal_id="s2", observed_at=_dt(9, 50), scope="other", heimdal_session_id="sess-b"),
    ]
    # The per-scope frontier the production tick builds from this batch.
    frontiers = {"work": _dt(9, 0), "other": _dt(9, 50)}
    open_1, closed_1 = fold_signals_into_segments(batch, open_segments=None, frontiers=frontiers)

    assert closed_1 == []  # neither scope's OWN head has moved past the gap
    assert set(open_1) == {"work", "other"}
    assert open_1["work"].signal_ids == frozenset({"s1"})
    assert open_1["other"].signal_ids == frozenset({"s2"})

    # Follow-up tick where scope 'work's OWN frontier advances past the gap
    # (no new 'work' signal, e.g. a later Heimdal delivery in another scope
    # advanced the wall while 'work's observed head reached 10:00) -> 'work'
    # closes, exactly once, carrying its single original signal.
    open_2, closed_2 = fold_signals_into_segments([], open_segments=open_1, frontiers={"work": _dt(10, 0)})
    work_closed = [c for c in closed_2 if c.scope == "work"]
    assert len(work_closed) == 1
    assert work_closed[0].derived_from == ("heimdal.observations:s1",)
    assert "work" not in open_2
    assert "other" in open_2  # 'other' had no frontier entry this tick -> stays open

    # Contrast: the SAME session continuing in a later tick extends rather
    # than closing -- one session never spans two proposals even after the gap.
    open_3, closed_3 = fold_signals_into_segments(
        [_signal(signal_id="s3", observed_at=_dt(11, 0), scope="other", heimdal_session_id="sess-b")],
        open_segments=open_1,
        frontiers={"other": _dt(11, 0)},
    )
    assert [c for c in closed_3 if c.scope == "other"] == []
    assert open_3["other"].signal_ids == frozenset({"s2", "s3"})


# ---------------------------------------------------------------------------
# PR #3508 review round 3: the PRODUCTION frontier is built from observed_at
# (read position), never observed_until (content-span end)
# ---------------------------------------------------------------------------


def _heimdal_row(
    *,
    observation_id: str,
    observed_at_start: datetime,
    observed_at_end: datetime | None = None,
    episode_id: str | None = None,
    protagonist: str | None = None,
    scope_hint: str = "work",
    sequence: int = 1,
) -> ObservationRow:
    payload: dict[str, Any] = {
        "observation_id": observation_id,
        "observed_at_start": observed_at_start.isoformat(),
        "scope_hint": scope_hint,
    }
    if observed_at_end is not None:
        payload["observed_at_end"] = observed_at_end.isoformat()
    if episode_id is not None:
        payload["episode_id"] = episode_id
    if protagonist is not None:
        payload["attributions"] = [{"mention_id": protagonist, "resolution": "resolved"}]
    return ObservationRow(
        id=f"log-{observation_id}",
        topic="heimdal.observation.published",
        idempotency_key=f"k-{observation_id}",
        envelope={"payload": payload},
        created_at=_dt(12, 0),
        sequence=sequence,
    )


def test_tick_long_observed_window_never_closes_nested_session_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #3508 review round 3 (comment 3565377855): ENFORCEMENT test that
    reaches the real ``run_segmentation_tick`` frontier construction (not a
    hand-built frontier dict).

    One tick, scope 'work':
      A: observed_at=09:00, observed_at_end=10:30 (a LONG content window),
         protagonist=alice, NO session.
      B: observed_at=09:10, protagonist=bob (disjoint -> shift closes A and
         opens B), session=sess-a.

    A's protagonist shift closes A and opens the session-bound segment B with
    last_signal_at=09:10. If the per-scope frontier were built from
    ``observed_until`` (=A's 10:30 span end), the quiescence loop would then
    close B in the SAME tick (10:30-09:10=80min>45) and sess-a's next-tick
    continuation would reopen as a SECOND proposal -- the within-scope form of
    the AC3 split. Built from ``observed_at`` (read position), the frontier is
    max(09:00, 09:10)=09:10, so B (last 09:10) is NOT closed and stays open.
    Expected: exactly ONE proposal (A) and ONE open segment (B)."""
    row_a = _heimdal_row(
        observation_id="obs-a",
        observed_at_start=_dt(9, 0),
        observed_at_end=_dt(10, 30),
        protagonist="alice",
        sequence=1,
    )
    row_b = _heimdal_row(
        observation_id="obs-b",
        observed_at_start=_dt(9, 10),
        episode_id="sess-a",
        protagonist="bob",
        sequence=2,
    )

    # Stub the I/O boundaries so the REAL tick body (frontier building, fold,
    # emission) runs without Postgres or live streams.
    monkeypatch.setattr(
        segmenter,
        "enumerate_consumable_streams",
        lambda *a, **k: (SimpleNamespace(stream_id=HEIMDAL_STREAM_ID),),
    )
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: [row_a, row_b])
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda *a, **k: None)
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    # ERE-05 assignment I/O boundaries (segmenter.py runs assignment after segmentation over the
    # same delta window) -- stub the DB reads/write so this stays a real-tick-body test without
    # Postgres; no prior persisted episodes and no prior ledger rows in this fixture.
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
    monkeypatch.setattr(
        segmenter,
        "commit_assignment_diff",
        lambda to_insert, to_correct, write_guard=None, vault_root=None: {
            "pending": len(to_insert),
            "corrected": len(to_correct),
        },
    )

    result = run_segmentation_tick(vault_root=tmp_path / "vault", write_guard=_allow_guard())

    # A proposed exactly once; B's session-bound segment survives the tick.
    assert len(result["proposed"]) == 1, result
    assert result["open_segments"] == 1, result
    # Exactly one note on disk (A) -- B was NOT emitted as a second proposal.
    notes = list((tmp_path / "vault" / "episodes").glob("*.md"))
    assert len(notes) == 1


# ---------------------------------------------------------------------------
# PR #3508 review round 2: observation-time parse guards (finding 2/4)
# ---------------------------------------------------------------------------


def test_parse_observation_time_guards_malformed_numeric() -> None:
    """PR #3508 review round 2 (comment 3565318043): the numeric branch of
    _parse_observation_time must not crash the tick on NaN/inf/out-of-range,
    and an epoch <= 0 (e.g. an mtime=0 sentinel) is treated as ABSENT so it
    never dates a signal to 1970 and drags `start` backward. A purely-numeric
    string is epoch seconds by design (finding 4)."""
    # Malformed / sentinel numeric mtimes -> None (skip fail-loud), never raise.
    assert _parse_observation_time(float("nan")) is None
    assert _parse_observation_time(float("inf")) is None
    assert _parse_observation_time(float("-inf")) is None
    assert _parse_observation_time(0) is None
    assert _parse_observation_time(0.0) is None
    assert _parse_observation_time(-5) is None
    assert _parse_observation_time(10**20) is None  # out of datetime range

    # Same guards through the string branch (watcher may serialize mtime as str).
    assert _parse_observation_time("0") is None
    assert _parse_observation_time("nan") is None
    assert _parse_observation_time("inf") is None
    assert _parse_observation_time("") is None
    assert _parse_observation_time("   ") is None

    # A positive numeric string is epoch seconds by design, not a bare year.
    epoch = _dt(9, 0).timestamp()
    assert _parse_observation_time(str(epoch)) == _dt(9, 0)
    assert _parse_observation_time(epoch) == _dt(9, 0)
    # ISO strings still parse.
    assert _parse_observation_time("2026-07-11T09:00:00+00:00") == _dt(9, 0)


def test_malformed_mtime_skips_row_but_batch_still_folds(tmp_path: Path) -> None:
    """A row with mtime=0 or mtime=NaN is skipped fail-loud (None), while the
    other rows in the same batch still normalize -- one poison row never
    crashes the tick nor drops the good signals."""
    good = _vault_row(
        {"relative_path": "note.md", "mtime": _dt(9, 0).timestamp()}, created_at=_dt(12, 0)
    )
    zero = _vault_row(
        {"relative_path": "note.md", "mtime": 0}, created_at=_dt(12, 0)
    )
    nan = _vault_row(
        {"relative_path": "note.md", "mtime": float("nan")}, created_at=_dt(12, 0)
    )
    assert _signal_from_vault_activity_row(zero, vault_root=tmp_path) is None
    assert _signal_from_vault_activity_row(nan, vault_root=tmp_path) is None
    good_signal = _signal_from_vault_activity_row(good, vault_root=tmp_path)
    assert good_signal is not None
    assert good_signal.observed_at == _dt(9, 0)


# ---------------------------------------------------------------------------
# PR #3508 review round 2: deterministic episode id is start-independent
# ---------------------------------------------------------------------------


def test_episode_id_stable_across_start_widening() -> None:
    """PR #3508 review round 2 (comment 3565318059): a resurrected stale
    segment (the documented crash-residual) whose `start` widens downward on
    replay must still mint the SAME episode_id, else the existence-check
    misses the original note and a duplicate proposal is written. The id is
    keyed on stable identity (scope | first-folded provenance_ref), not
    `start`."""
    base = ClosedSegment(
        scope="work",
        start=_dt(9, 0),
        end=_dt(9, 30),
        heimdal_session_id="sess-a",
        protagonists=(),
        goal=(),
        derived_from=("heimdal.observations:obs-1", "vault.activity:v1"),
    )
    # `start` widened downward (out-of-order fold on replay) -> SAME id.
    widened = replace(base, start=_dt(8, 0))
    assert _deterministic_episode_id(base) == _deterministic_episode_id(widened)
    # `end` moving (later signal folded) likewise does not change the id.
    extended_end = replace(base, end=_dt(10, 0))
    assert _deterministic_episode_id(base) == _deterministic_episode_id(extended_end)

    # Two distinct same-scope segments differ in their first-folded ref, so
    # their ids can never collide.
    other = replace(base, derived_from=("heimdal.observations:obs-2",))
    assert _deterministic_episode_id(base) != _deterministic_episode_id(other)


# ---------------------------------------------------------------------------
# Out-of-order arrival: bitemporal bounds cover every folded signal
# ---------------------------------------------------------------------------


def test_out_of_order_signal_widens_segment_start() -> None:
    """PR #3508 review round 1 (comment 3565218971): the two stream cursors
    are independent, so a late-delivered signal can carry an EARLIER
    observed_at than the segment's current start -- time.start must widen
    downward, never postdate a signal in the segment's own derived_from."""
    first = [_signal(signal_id="later", observed_at=_dt(9, 10), heimdal_session_id="sess-a")]
    open_1, _ = fold_signals_into_segments(first, open_segments=None, frontiers={})
    assert open_1["work"].start == _dt(9, 10)

    late_earlier = [
        _signal(
            stream_id="vault.activity",
            signal_id="earlier",
            observed_at=_dt(9, 0),
        )
    ]
    open_2, closed_2 = fold_signals_into_segments(late_earlier, open_segments=open_1, frontiers={})
    assert closed_2 == []
    assert open_2["work"].start == _dt(9, 0)
    assert "vault.activity:earlier" in open_2["work"].derived_from

    # And the closed segment's bounds reflect the widened window.
    _, closed = fold_signals_into_segments([], open_segments=open_2, frontiers=_scope_frontier(_dt(10, 30)))
    assert len(closed) == 1
    assert closed[0].start == _dt(9, 0)
    assert closed[0].end == _dt(9, 10)


def test_observed_at_end_extends_segment_bounds() -> None:
    """A source observation spanning a window (observed_at_start..end) must
    close with the window's END as the segment bound, not its start."""
    spanning = SegmentationSignal(
        stream_id="heimdal.observations",
        signal_id="span-1",
        observed_at=_dt(9, 0),
        observed_at_end=_dt(9, 30),
        scope="work",
        provenance_ref="heimdal.observations:span-1",
        heimdal_session_id="sess-a",
    )
    open_1, _ = fold_signals_into_segments([spanning], open_segments=None, frontiers={})
    assert open_1["work"].last_signal_at == _dt(9, 30)

    _, closed = fold_signals_into_segments([], open_segments=open_1, frontiers=_scope_frontier(_dt(10, 30)))
    assert len(closed) == 1
    assert closed[0].end == _dt(9, 30)


# ---------------------------------------------------------------------------
# AC7: signals lacking scope context never cross-scope fuse
# ---------------------------------------------------------------------------


def test_segments_keyed_per_scope_by_default() -> None:
    signals = [
        _signal(signal_id="w1", observed_at=_dt(9, 0), scope="work", protagonists=("alice",)),
        _signal(signal_id="p1", observed_at=_dt(9, 1), scope="personal", protagonists=("alice",)),
        _signal(signal_id="u1", observed_at=_dt(9, 2), scope="default", protagonists=("alice",)),
    ]
    open_segments, closed = fold_signals_into_segments(signals, open_segments=None, frontiers={})

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
        frontiers={},
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
    _, closed = fold_signals_into_segments(signals, open_segments=None, frontiers=_scope_frontier(_dt(10, 0)))
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


# ---------------------------------------------------------------------------
# Stream adapters: observation time comes from the payload, never emission time
# ---------------------------------------------------------------------------


def _vault_row(
    payload: dict[str, Any], *, created_at: datetime, topic: str = "ingest.vault.changed"
) -> VaultActivityRow:
    return VaultActivityRow(id="row-1", topic=topic, created_at=created_at, payload=payload)


def test_vault_activity_signal_uses_payload_mtime_not_row_created_at(tmp_path: Path) -> None:
    """PR #3508 review round 1 (comment 3565218942): the outbox row's
    created_at is emission/enqueue time; the observation time is the
    payload's mtime. A delayed/backfilled scan must not shift bounds."""
    observed = _dt(9, 0)
    row = _vault_row(
        {"relative_path": "note.md", "mtime": observed.timestamp()},
        created_at=_dt(12, 0),  # enqueue 3h later
    )
    signal = _signal_from_vault_activity_row(row, vault_root=tmp_path)
    assert signal is not None
    assert signal.observed_at == observed

    # No usable observation time -> fail-loud skip (None), NEVER a silent
    # substitution of the row's created_at.
    no_mtime = _vault_row({"path": "/somewhere/else.md"}, created_at=_dt(12, 0), topic="ingest.object.created")
    assert _signal_from_vault_activity_row(no_mtime, vault_root=tmp_path) is None


def test_heimdal_signal_skips_row_without_observed_at() -> None:
    """PR #3508 review round 1 (comment 3565218982): an observation row
    lacking observed_at_start is skipped fail-loud, never stamped with the
    log row's insert time."""
    row = ObservationRow(
        id="log-row-1",
        topic="heimdal.observation.published",
        idempotency_key="k1",
        envelope={"payload": {"observation_id": "obs-1", "episode_id": "sess-a"}},
        created_at=_dt(12, 0),
        sequence=1,
    )
    assert _signal_from_heimdal_row(row) is None

    ok_row = ObservationRow(
        id="log-row-2",
        topic="heimdal.observation.published",
        idempotency_key="k2",
        envelope={
            "payload": {
                "observation_id": "obs-2",
                "episode_id": "sess-a",
                "observed_at_start": "2026-07-11T09:00:00+00:00",
                "observed_at_end": "2026-07-11T09:30:00+00:00",
            }
        },
        created_at=_dt(12, 0),
        sequence=2,
    )
    signal = _signal_from_heimdal_row(ok_row)
    assert signal is not None
    assert signal.observed_at == _dt(9, 0)
    assert signal.observed_at_end == _dt(9, 30)
    assert signal.observed_until == _dt(9, 30)


# ---------------------------------------------------------------------------
# vault.activity path containment: ingest-time absolute paths never escape
# the current vault root
# ---------------------------------------------------------------------------


def test_vault_activity_absolute_paths_contained_to_vault_root(tmp_path: Path) -> None:
    """PR #3508 review round 1 (comment 3565216265): `ingest.object.created`/
    `deleted` payloads carry ABSOLUTE ingest-time paths. With a differing
    vault_root (relocated vault, --vault-root override) the ingest-time
    location must never be read; an absolute path under the CURRENT root is
    re-relativized and read normally."""
    ingest_root = tmp_path / "ingest-vault"
    ingest_root.mkdir()
    (ingest_root / "note.md").write_text("---\nscope: leaked-scope\n---\nbody\n", encoding="utf-8")

    current_root = tmp_path / "current-vault"
    current_root.mkdir()
    (current_root / "note.md").write_text(
        "---\nscope: work\nsphere_memberships: [proj-x]\n---\nbody\n", encoding="utf-8"
    )

    empty = {"scope": None, "sphere_memberships": [], "situated_identity": None}

    # created-shape payload: absolute ingest-time path under a DIFFERENT root
    # -> rejected (empty dims), never read from the other vault.
    created = _vault_row(
        {"path": str(ingest_root / "note.md")}, created_at=_dt(12, 0), topic="ingest.object.created"
    )
    assert resolve_activity_dimensions(created, vault_root=current_root) == empty

    # deleted-shape payload: same containment rule.
    deleted = _vault_row(
        {"path": str(ingest_root / "note.md"), "deleted": True},
        created_at=_dt(12, 0),
        topic="ingest.object.deleted",
    )
    assert resolve_activity_dimensions(deleted, vault_root=current_root) == empty

    # An absolute path UNDER the current root is accepted and read.
    under_current = _vault_row(
        {"path": str(current_root / "note.md")}, created_at=_dt(12, 0), topic="ingest.object.created"
    )
    dims = resolve_activity_dimensions(under_current, vault_root=current_root)
    assert dims["scope"] == "work"
    assert dims["sphere_memberships"] == ["proj-x"]

    # A relative path traversing out of the root is rejected too.
    traversal = _vault_row({"relative_path": "../ingest-vault/note.md"}, created_at=_dt(12, 0))
    assert resolve_activity_dimensions(traversal, vault_root=current_root) == empty


# ---------------------------------------------------------------------------
# engine_state: fail-loud schema preflight (invariant -> producers)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, regclass_result: Any) -> None:
        self._result = regclass_result

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        assert "to_regclass" in sql

    def fetchone(self) -> Any:
        return self._result


class _FakeConn:
    def __init__(self, regclass_result: Any) -> None:
        self._result = regclass_result

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._result)


def test_engine_state_schema_preflight_fails_loud_with_migration_hint() -> None:
    """PR #3508 review round 1 (comment 3565216282): a pre-migration database
    must fail with EngineStateSchemaMissingError naming the migration, never
    a raw UndefinedTable traceback from inside a query (mirrors
    app/heimdal/cursor_store._assert_pg_schema)."""
    with pytest.raises(EngineStateSchemaMissingError) as exc_info:
        _assert_schema(_FakeConn((None,)))
    assert "alembic upgrade head" in str(exc_info.value)
    assert "a1b2c3d4e5f6" in str(exc_info.value)

    with pytest.raises(EngineStateSchemaMissingError):
        _assert_schema(_FakeConn(None))  # no row at all

    # Table present (either row shape) -> no raise.
    _assert_schema(_FakeConn(("episode_engine_state",)))
    _assert_schema(_FakeConn({"to_regclass": "episode_engine_state"}))
