"""Episode-ref assignment tests (ERE-05, #3180).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md``.

- AC1: in-bounds artifacts get pending bindings; out-of-bounds artifacts get none. Verify:
  ``test_in_bounds_artifacts_get_pending_binding``
- AC2: a ``derived_from``-anchored artifact binds even with imperfect time overlap; a
  time-overlap-only artifact in a DIFFERENT scope never binds. Verify:
  ``test_binding_basis_provenance_beats_overlap_and_respects_scope``
- AC3: nested/overlapping episodes yield multiple refs, schema-valid. Verify:
  ``test_overlapping_episodes_yield_multiple_refs``
- AC4 (enforcement): the assignment write path asserts the guard AT the production seam and
  never emits an AuthorityReceipt for a pending binding. Verify:
  ``test_assignment_write_guarded_proposal_class``
- AC6: assignment is idempotent per (artifact, episode); re-ticks don't duplicate refs;
  corrections carry provenance. Verify:
  ``test_assignment_idempotent_and_corrections_provenanced``
- AC7: late-arriving artifacts bind to already-closed episodes without altering episode bounds.
  Verify: ``test_late_artifact_binds_without_recutting_bounds``

Pure-core tests (AC1/AC2/AC3/AC6-diff) need no vault/DB, matching the ``not pg`` lane precedent
set by ``tests/episodes/test_segmentation_core.py``/``test_episode_store.py``. The guard test
(AC4) and the tick-integration test (AC7) stub every DB/vault I/O boundary explicitly (same
monkeypatch discipline as ``test_segmentation_core.py::test_tick_long_observed_window_...``), so
none of this file needs a live Postgres either.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.episodes import assignment as assignment_module
from app.episodes import segmenter
from app.episodes.assignment import (
    ASSIGNMENT_RULE,
    BASIS_PROVENANCE,
    BASIS_TIME_OVERLAP,
    BINDING_STATE_ACTIVE,
    BINDING_STATE_CORRECTED,
    EPISODE_ASSIGNMENT_WRITE_ACTION,
    PROVENANCE_CONFIDENCE,
    TIME_OVERLAP_CONFIDENCE,
    ArtifactCandidate,
    AssignmentDecision,
    EpisodeBoundsRecord,
    commit_assignment_diff,
    compute_assignments,
    diff_assignments,
)
from app.episodes.segmenter import HEIMDAL_STREAM_ID, run_segmentation_tick
from app.heimdal.observation_log import ObservationRow
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


def _dt(hour: int, minute: int, day: int = 11) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-blocked"})


def _heimdal_row(
    *,
    observation_id: str,
    observed_at_start: datetime,
    scope_hint: str = "work",
    sequence: int = 1,
) -> ObservationRow:
    payload: dict[str, Any] = {
        "observation_id": observation_id,
        "observed_at_start": observed_at_start.isoformat(),
        "scope_hint": scope_hint,
    }
    return ObservationRow(
        id=f"log-{observation_id}",
        topic="heimdal.observation.published",
        idempotency_key=f"k-{observation_id}",
        envelope={"payload": payload},
        created_at=_dt(12, 0),
        sequence=sequence,
    )


# ---------------------------------------------------------------------------
# AC1: in-bounds artifacts get pending bindings; out-of-bounds get none
# ---------------------------------------------------------------------------


def test_in_bounds_artifacts_get_pending_binding() -> None:
    episode = EpisodeBoundsRecord(
        episode_id="ep-11111111-2222-4333-8444-555555555555",
        scope="work",
        start=_dt(10, 0),
        end=_dt(11, 0),
        derived_from=("vault.activity:seed",),
    )
    inside = ArtifactCandidate(
        artifact_ref="vault.activity:inside", scope="work", observed_at=_dt(10, 30)
    )
    outside = ArtifactCandidate(
        artifact_ref="vault.activity:outside", scope="work", observed_at=_dt(12, 30)
    )

    decisions = compute_assignments([inside, outside], [episode])

    assert [d.artifact_ref for d in decisions] == ["vault.activity:inside"]
    decision = decisions[0]
    assert decision.episode_id == episode.episode_id
    assert decision.basis == BASIS_TIME_OVERLAP
    assert decision.confidence == TIME_OVERLAP_CONFIDENCE


def test_artifact_in_different_scope_never_binds_even_in_time_bounds() -> None:
    episode = EpisodeBoundsRecord(
        episode_id="ep-22222222-2222-4333-8444-555555555555",
        scope="work",
        start=_dt(10, 0),
        end=_dt(11, 0),
        derived_from=(),
    )
    other_scope = ArtifactCandidate(
        artifact_ref="vault.activity:elsewhere", scope="personal", observed_at=_dt(10, 30)
    )
    assert compute_assignments([other_scope], [episode]) == []


# ---------------------------------------------------------------------------
# AC2: provenance beats imperfect overlap; scope discipline still applies
# ---------------------------------------------------------------------------


def test_binding_basis_provenance_beats_overlap_and_respects_scope() -> None:
    episode = EpisodeBoundsRecord(
        episode_id="ep-33333333-2222-4333-8444-555555555555",
        scope="work",
        start=_dt(10, 0),
        end=_dt(11, 0),
        derived_from=("heimdal.observations:anchor",),
    )
    # Provenance-anchored, but its own observed_at sits OUTSIDE [start, end] -- an imperfect time
    # overlap must never override a real provenance anchor.
    anchored_outside_bounds = ArtifactCandidate(
        artifact_ref="heimdal.observations:anchor", scope="work", observed_at=_dt(13, 0)
    )
    # Same scope, genuinely in-bounds by time, but not the derived_from anchor -- weaker basis.
    overlap_only = ArtifactCandidate(
        artifact_ref="heimdal.observations:other", scope="work", observed_at=_dt(10, 30)
    )
    # In-bounds by time, but a DIFFERENT scope -- must never bind (deny-by-default cross-scope,
    # ERE-08 pins the full posture; this task never crosses scopes unflowed).
    cross_scope = ArtifactCandidate(
        artifact_ref="heimdal.observations:cross", scope="personal", observed_at=_dt(10, 30)
    )

    decisions = compute_assignments(
        [anchored_outside_bounds, overlap_only, cross_scope], [episode]
    )
    by_ref = {d.artifact_ref: d for d in decisions}

    assert by_ref["heimdal.observations:anchor"].basis == BASIS_PROVENANCE
    assert by_ref["heimdal.observations:anchor"].confidence == PROVENANCE_CONFIDENCE
    assert by_ref["heimdal.observations:other"].basis == BASIS_TIME_OVERLAP
    assert by_ref["heimdal.observations:other"].confidence == TIME_OVERLAP_CONFIDENCE
    assert "heimdal.observations:cross" not in by_ref


# ---------------------------------------------------------------------------
# AC3: nested/overlapping episodes yield multiple refs, schema-valid
# ---------------------------------------------------------------------------


def test_overlapping_episodes_yield_multiple_refs() -> None:
    e1 = EpisodeBoundsRecord(
        episode_id="ep-44444444-2222-4333-8444-555555555555",
        scope="work",
        start=_dt(9, 0),
        end=_dt(11, 0),
        derived_from=(),
    )
    e2 = EpisodeBoundsRecord(
        episode_id="ep-55555555-2222-4333-8444-555555555555",
        scope="work",
        start=_dt(10, 30),
        end=_dt(12, 0),
        derived_from=(),
    )
    artifact = ArtifactCandidate(
        artifact_ref="vault.activity:nested", scope="work", observed_at=_dt(10, 45)
    )

    decisions = compute_assignments([artifact], [e1, e2])

    assert {d.episode_id for d in decisions} == {e1.episode_id, e2.episode_id}
    assert all(d.artifact_ref == artifact.artifact_ref for d in decisions)
    assert all(d.basis == BASIS_TIME_OVERLAP for d in decisions)

    # Schema-valid: a bundle carrying both refs validates against metadata-bundle.schema.json
    # (schemas/_defs.schema.json :: episode_ref -- a non-empty array of episode_id strings).
    from tests.invariants._helpers import assert_validates

    bundle = {
        "object_id": "artifact:nested-multi",
        "object_type": "artifact",
        "scope_id": "scope:work",
        "source_role": "work_project",
        "authority_state": "captured",
        "evidence_role": "reference",
        "sensitivity": "internal",
        "suppression_state": "visible",
        "created_by": "p-1",
        "created_at": "2026-07-11T00:00:00+00:00",
        "provenance_event_ids": ["prov:1"],
        "episode_ref": sorted(d.episode_id for d in decisions),
    }
    assert_validates(bundle, "metadata-bundle.schema.json")


# ---------------------------------------------------------------------------
# AC4 (enforcement) -- guard-at-seam, proposal class, no authority receipt
# ---------------------------------------------------------------------------


def _fake_conn_that_must_not_be_called():
    class _Boom:
        def __enter__(self):
            raise AssertionError("commit_assignment_diff must not touch the DB when blocked")

        def __exit__(self, *exc):
            return False

    return _Boom()


def test_assignment_write_guarded_proposal_class(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = AssignmentDecision(
        artifact_ref="vault.activity:1",
        episode_id="ep-66666666-2222-4333-8444-555555555555",
        scope="work",
        basis=BASIS_TIME_OVERLAP,
        confidence=TIME_OVERLAP_CONFIDENCE,
    )

    # Guard-at-seam: a blocked guard raises BEFORE any DB statement runs -- zero rows touched.
    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _fake_conn_that_must_not_be_called())
    with pytest.raises(WritesBlockedError) as exc_info:
        commit_assignment_diff([decision], [], write_guard=_blocking_guard())
    assert exc_info.value.action == EPISODE_ASSIGNMENT_WRITE_ACTION
    assert exc_info.value.state == "safe_mode"

    # An allowed guard succeeds and reaches the (here, faked-real) DB seam.
    executed: list[tuple[str, tuple[Any, ...]]] = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            executed.append((sql, params))

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _FakeConn())
    result = commit_assignment_diff([decision], [], write_guard=_allow_guard())
    assert result == {"pending": 1, "corrected": 0}
    assert len(executed) == 1
    sql, params = executed[0]
    assert "INSERT INTO episode_artifact_binding" in sql
    assert ASSIGNMENT_RULE in params
    assert BINDING_STATE_ACTIVE in params


def test_assignment_write_asserted_inside_the_production_seam_not_a_helper() -> None:
    """Mirrors ``test_episode_store.py``'s equivalent probe: the guard assertion must live
    inside ``commit_assignment_diff`` itself (the real production seam), not a caller-side
    wrapper a different call path could route around."""
    source = inspect.getsource(commit_assignment_diff)
    tree = ast.parse(source)
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert "write_guard.assert_writes_allowed" in calls


def test_assignment_module_never_imports_governance_or_authority_receipt() -> None:
    """Structural guarantee: a `pending`/proposal-class binding cannot reach governed_write --
    the module has no import path to it, mirroring
    ``test_episode_store.py::test_proposed_episode_is_proposal_class_no_authority_receipt``."""
    source = inspect.getsource(assignment_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert not any("governed_write" in m for m in imported_modules)

    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "DecisionToken" not in referenced
    assert "AuthorityReceipt" not in referenced
    assert "PolicyDecision" not in referenced


# ---------------------------------------------------------------------------
# AC6: idempotent per (artifact, episode); corrections carry provenance
# ---------------------------------------------------------------------------


def test_assignment_idempotent_and_corrections_provenanced() -> None:
    episode = EpisodeBoundsRecord(
        episode_id="ep-77777777-2222-4333-8444-555555555555",
        scope="work",
        start=_dt(10, 0),
        end=_dt(11, 0),
        derived_from=(),
    )
    artifact = ArtifactCandidate(
        artifact_ref="vault.activity:re-tick", scope="work", observed_at=_dt(10, 30)
    )

    decisions = compute_assignments([artifact], [episode])
    key = (artifact.artifact_ref, episode.episode_id)

    # First tick: nothing recorded yet -- a fresh insert.
    to_insert, to_correct = diff_assignments({}, decisions)
    assert [d.artifact_ref for d in to_insert] == [artifact.artifact_ref]
    assert to_correct == []

    # Second tick, same inputs, now with the ledger reflecting what tick 1 committed: a re-tick
    # of an unchanged, already-active, same-basis pair must produce NOTHING (AC6: re-ticks don't
    # duplicate refs).
    existing_after_tick_1 = {
        key: {"binding_state": BINDING_STATE_ACTIVE, "basis": BASIS_TIME_OVERLAP}
    }
    to_insert_2, to_correct_2 = diff_assignments(existing_after_tick_1, decisions)
    assert to_insert_2 == []
    assert to_correct_2 == []

    # Third tick: a re-cut narrowed the episode so it no longer covers this artifact -- the
    # existing ACTIVE binding is no longer supported by any current decision. It must be
    # corrected (never silently dropped): diff_assignments reports it for correction, carrying
    # its own key (provenance of exactly which pair changed).
    to_insert_3, to_correct_3 = diff_assignments(existing_after_tick_1, [])
    assert to_insert_3 == []
    assert to_correct_3 == [key]

    # A binding a PRIOR tick already corrected, and that current decisions still do not support,
    # is not re-reported (idempotent on the correction side too).
    existing_after_correction = {
        key: {"binding_state": BINDING_STATE_CORRECTED, "basis": BASIS_TIME_OVERLAP}
    }
    to_insert_4, to_correct_4 = diff_assignments(existing_after_correction, [])
    assert to_insert_4 == []
    assert to_correct_4 == []

    # If the artifact comes back into bounds later (bounds widened again), a corrected binding is
    # REINSTATED as a fresh insert, not silently left corrected.
    to_insert_5, to_correct_5 = diff_assignments(existing_after_correction, decisions)
    assert [d.artifact_ref for d in to_insert_5] == [artifact.artifact_ref]
    assert to_correct_5 == []


def test_commit_assignment_diff_persists_correction_with_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The commit seam actually issues the UPDATE that flips binding_state -> corrected and
    stamps corrected_at -- the correction is a durable, provenanced ledger update, not just a
    diff-layer computation."""
    executed: list[tuple[str, tuple[Any, ...]]] = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            executed.append((sql, params))

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _FakeConn())

    key = ("vault.activity:recut", "ep-88888888-2222-4333-8444-555555555555")
    result = commit_assignment_diff([], [key], write_guard=_allow_guard())

    assert result == {"pending": 0, "corrected": 1}
    assert len(executed) == 1
    sql, params = executed[0]
    assert "UPDATE episode_artifact_binding" in sql
    assert BINDING_STATE_CORRECTED in params
    assert key[0] in params and key[1] in params


# ---------------------------------------------------------------------------
# AC7: late-arriving artifacts bind to already-closed episodes without re-cutting bounds
# ---------------------------------------------------------------------------


def test_late_artifact_binds_without_recutting_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A signal read on a LATER tick than the one that closed its episode still binds, resolved
    against the persisted `episodes` projection (not this tick's empty in-memory
    closed_segments) -- and the episode's own bounds are never touched by the assignment path."""
    persisted_episode = EpisodeBoundsRecord(
        episode_id="ep-99999999-2222-4333-8444-555555555555",
        scope="work",
        start=_dt(9, 0),
        end=_dt(9, 30),
        derived_from=("heimdal.observations:obs-early",),
    )
    late_row = _heimdal_row(observation_id="obs-late", observed_at_start=_dt(9, 15))

    captured: dict[str, Any] = {}

    def _fake_commit(to_insert, to_correct, write_guard=None):
        captured["to_insert"] = to_insert
        captured["to_correct"] = to_correct
        return {"pending": len(to_insert), "corrected": len(to_correct)}

    monkeypatch.setattr(
        segmenter, "enumerate_consumable_streams", lambda *a, **k: (SimpleNamespace(stream_id=HEIMDAL_STREAM_ID),)
    )
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: [late_row])
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda *a, **k: None)
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    monkeypatch.setattr(
        segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [persisted_episode]
    )
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "commit_assignment_diff", _fake_commit)

    result = run_segmentation_tick(vault_root=tmp_path / "vault", write_guard=_allow_guard())

    # Nothing closed this tick -- the late signal just opens a segment; segmentation bounds are
    # untouched by assignment.
    assert result["proposed"] == []
    assert result["open_segments"] == 1
    assert not (tmp_path / "vault" / "episodes").exists() or not list(
        (tmp_path / "vault" / "episodes").glob("*.md")
    )

    assert len(captured["to_insert"]) == 1
    decision = captured["to_insert"][0]
    assert decision.episode_id == persisted_episode.episode_id
    assert decision.basis == BASIS_TIME_OVERLAP
    assert result["assigned"] == {"pending": 1, "corrected": 0}

    # The episode record used for the binding decision is exactly what was read -- structurally
    # immutable (frozen dataclass) and never rewritten by the assignment path.
    assert persisted_episode.start == _dt(9, 0)
    assert persisted_episode.end == _dt(9, 30)
