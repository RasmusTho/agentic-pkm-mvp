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
import json
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
    BINDING_TABLE,
    EPISODE_ASSIGNMENT_WRITE_ACTION,
    PROVENANCE_CONFIDENCE,
    TIME_OVERLAP_CONFIDENCE,
    ArtifactCandidate,
    AssignmentDecision,
    EpisodeAssignmentSchemaMissingError,
    EpisodeBoundsRecord,
    _assert_table_schema,
    commit_assignment_diff,
    compute_assignments,
    diff_assignments,
    read_existing_bindings_for_episodes,
)
from app.episodes.segmenter import HEIMDAL_STREAM_ID, OpenSegment, run_segmentation_tick
from app.jobs.episodes_projection import EPISODES_TABLE
from app.heimdal.observation_log import ObservationRow
from app.knowledge.errors import KnowledgeWriteConflict
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _no_closure_candidates(monkeypatch: pytest.MonkeyPatch):
    """ERE-06 (#3181) extended ``run_segmentation_tick`` with an unconditional closure step
    (``app.episodes.closure.run_closure_tick``) that reads the ``episodes`` DB projection. These
    ERE-05 tests predate closure and don't exercise it -- default to zero candidates so every
    existing ``run_segmentation_tick`` call here stays a ``not pg`` test; closure's own tests
    (``tests/episodes/test_closure.py``) override this explicitly."""
    import app.episodes.closure as closure_module

    monkeypatch.setattr(closure_module, "find_closable_episodes", lambda **k: [])


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
    """The pure RULE half of AC1: which (artifact, episode) pairs bind, and on what basis. The
    REAL bundle-write half (assign -> the artifact's persisted bundle actually shows
    ``episode_ref`` pending) is exercised end to end by
    ``test_commit_assignment_diff_stamps_pending_episode_ref_on_real_bundle`` below (Finding 1,
    review round 2) -- this function alone was never enough to prove AC1's "artifacts ... receive
    episode_ref: pending [ep-...]" against production storage."""
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
        def __init__(self) -> None:
            self._result: Any = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            executed.append((sql, params))
            # Schema preflight (Finding 2): commit_assignment_diff now asserts the ledger table
            # exists via to_regclass before issuing any real write -- a healthy fake DB reports the
            # table present.
            self._result = (
                (True, True, ["vault_binding_id", "artifact_ref", "episode_id"])
                if "to_regclass" in sql
                else None
            )

        def fetchone(self):
            return self._result

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _FakeConn())
    # No vault_root passed -- ledger-only, no bundle-mutation queries expected alongside the
    # preflight + insert.
    result = commit_assignment_diff([decision], [], write_guard=_allow_guard())
    assert result == {"pending": 1, "corrected": 0}
    assert any("to_regclass" in sql for sql, _ in executed)
    insert_calls = [
        (sql, params) for sql, params in executed if "INSERT INTO episode_artifact_binding" in sql
    ]
    assert len(insert_calls) == 1
    sql, params = insert_calls[0]
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
        def __init__(self) -> None:
            self._result: Any = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            executed.append((sql, params))
            self._result = (
                (True, True, ["vault_binding_id", "artifact_ref", "episode_id"])
                if "to_regclass" in sql
                else None
            )

        def fetchone(self):
            return self._result

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _FakeConn())

    key = ("vault.activity:recut", "ep-88888888-2222-4333-8444-555555555555")
    # No vault_root -- ledger-only correction (the bundle-mutation half of a correction is
    # exercised separately by test_commit_assignment_diff_correction_clears_episode_ref_from_bundle).
    result = commit_assignment_diff([], [key], write_guard=_allow_guard())

    assert result == {"pending": 0, "corrected": 1}
    assert any("to_regclass" in sql for sql, _ in executed)
    update_calls = [
        (sql, params) for sql, params in executed if "UPDATE episode_artifact_binding" in sql
    ]
    assert len(update_calls) == 1
    sql, params = update_calls[0]
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

    def _fake_commit(to_insert, to_correct, write_guard=None, vault_root=None):
        captured["to_insert"] = to_insert
        captured["to_correct"] = to_correct
        captured["vault_root"] = vault_root
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
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
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

    # Finding 1: the production tick always passes the real vault_root through to
    # commit_assignment_diff, so bundle mutation is reachable on the real path (not opt-in).
    assert captured["vault_root"] == tmp_path / "vault"

    # The episode record used for the binding decision is exactly what was read -- structurally
    # immutable (frozen dataclass) and never rewritten by the assignment path.
    assert persisted_episode.start == _dt(9, 0)
    assert persisted_episode.end == _dt(9, 30)


# ---------------------------------------------------------------------------
# Finding 2 (review round 1 CONFIRMED): fail-loud schema preflight
# (invariant -> producers, mirrors app.episodes.engine_state's precedent)
# ---------------------------------------------------------------------------


class _RegclassCursor:
    def __init__(self, regclass_result: Any) -> None:
        self._result = regclass_result

    def __enter__(self) -> "_RegclassCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = ()) -> None:
        assert "to_regclass" in sql

    def fetchone(self) -> Any:
        return self._result


class _RegclassConn:
    def __init__(self, regclass_result: Any) -> None:
        self._result = regclass_result

    def __enter__(self) -> "_RegclassConn":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def cursor(self) -> _RegclassCursor:
        return _RegclassCursor(self._result)


def test_assert_table_schema_fails_loud_with_migration_hint() -> None:
    """Review gate round 1 CONFIRMED (invariant->producers, as predicted): a pre-migration
    database must fail with EpisodeAssignmentSchemaMissingError naming the migration, never a raw
    UndefinedTable traceback from inside a query (mirrors
    app.episodes.engine_state.EngineStateSchemaMissingError / _assert_schema)."""
    with pytest.raises(EpisodeAssignmentSchemaMissingError) as exc_info:
        _assert_table_schema(_RegclassConn((False, False, [])), BINDING_TABLE)
    assert "alembic upgrade head" in str(exc_info.value)
    assert "b7c8d9e0f1a2" in str(exc_info.value)

    with pytest.raises(EpisodeAssignmentSchemaMissingError):
        _assert_table_schema(_RegclassConn(None), BINDING_TABLE)  # no row at all

    with pytest.raises(EpisodeAssignmentSchemaMissingError) as exc_info:
        _assert_table_schema(_RegclassConn((False, False, [])), EPISODES_TABLE)
    assert "alembic upgrade head" in str(exc_info.value)

    # Final MVR-05A5 table shape -> no raise.
    _assert_table_schema(
        _RegclassConn((True, True, ["vault_binding_id", "artifact_ref", "episode_id"])),
        BINDING_TABLE,
    )
    _assert_table_schema(
        _RegclassConn(
            {
                "table_exists": True,
                "binding_column_exists": True,
                "primary_key": ["vault_binding_id", "artifact_ref", "episode_id"],
            }
        ),
        BINDING_TABLE,
    )


def test_read_candidate_episodes_for_scopes_asserts_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.episodes.assignment import read_candidate_episodes_for_scopes

    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _RegclassConn((False, False, []))
    )
    with pytest.raises(EpisodeAssignmentSchemaMissingError):
        read_candidate_episodes_for_scopes(["work"])


def test_read_existing_bindings_asserts_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.episodes.assignment import read_existing_bindings

    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _RegclassConn((False, False, []))
    )
    with pytest.raises(EpisodeAssignmentSchemaMissingError):
        read_existing_bindings(["vault.activity:x"])


def test_read_existing_bindings_for_episodes_asserts_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _RegclassConn((False, False, []))
    )
    with pytest.raises(EpisodeAssignmentSchemaMissingError):
        read_existing_bindings_for_episodes(["ep-1"])


def test_commit_assignment_diff_asserts_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _RegclassConn((False, False, []))
    )
    decision = AssignmentDecision(
        artifact_ref="vault.activity:schema-check",
        episode_id="ep-schema-1111-4333-8444-555555555555",
        scope="work",
        basis=BASIS_TIME_OVERLAP,
        confidence=TIME_OVERLAP_CONFIDENCE,
    )
    with pytest.raises(EpisodeAssignmentSchemaMissingError):
        commit_assignment_diff([decision], [], write_guard=_allow_guard())


# ---------------------------------------------------------------------------
# Finding 1 (CRITICAL, review round 2): the REAL bundle write, not the ledger alone
# ---------------------------------------------------------------------------


class _BundleCursor:
    """Fakes store_objects/store_vector_index/episode_artifact_binding against one shared
    in-memory ``rows`` dict keyed by ``(table, object_id)`` -- close enough to real
    read-modify-write semantics to prove the payload merge actually happens, without a live
    Postgres."""

    def __init__(
        self,
        rows: dict[tuple[str, str], dict[str, Any]],
        executed: list[tuple[str, tuple[Any, ...]]],
    ) -> None:
        self._rows = rows
        self._executed = executed
        self._result: Any = None

    def __enter__(self) -> "_BundleCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._executed.append((sql, params))
        stripped = sql.strip()
        if "to_regclass" in stripped:
            self._result = (True, True, ["vault_binding_id", "artifact_ref", "episode_id"])
            return
        if stripped.startswith("SELECT payload FROM store_objects") or stripped.startswith(
            "SELECT payload FROM store_vector_index"
        ):
            table = "store_objects" if "store_objects" in stripped else "store_vector_index"
            binding_id, object_id = params
            assert binding_id == assignment_module.COMPATIBILITY_BINDING_ID
            row = self._rows.get((table, object_id))
            self._result = (json.dumps(row),) if row is not None else None
            return
        if stripped.startswith("UPDATE store_objects") or stripped.startswith(
            "UPDATE store_vector_index"
        ):
            table = "store_objects" if "store_objects" in stripped else "store_vector_index"
            # Finding 3: the production write is a targeted jsonb_set on the episode_ref key ONLY,
            # never a full-column overwrite -- this fake models exactly that (params carry the new
            # episode_ref VALUE, not a whole payload; every other key is left in place), so a test
            # asserting a sibling key survives is meaningful.
            assert "jsonb_set" in stripped and "'{episode_ref}'" in stripped, stripped
            assert "SET payload = %s::jsonb" not in stripped, "must not blind-overwrite the column"
            episode_ref_json, binding_id, object_id = params
            assert binding_id == assignment_module.COMPATIBILITY_BINDING_ID
            existing = self._rows.get((table, object_id))
            if existing is not None:
                existing["episode_ref"] = json.loads(episode_ref_json)
            self._result = None
            return
        self._result = None

    def fetchone(self) -> Any:
        return self._result


class _BundleConn:
    def __init__(
        self, rows: dict[tuple[str, str], dict[str, Any]], executed: list[tuple[str, tuple[Any, ...]]]
    ) -> None:
        self._rows = rows
        self._executed = executed

    def __enter__(self) -> "_BundleConn":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def cursor(self) -> _BundleCursor:
        return _BundleCursor(self._rows, self._executed)


def test_commit_assignment_diff_stamps_pending_episode_ref_on_real_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 1 (CRITICAL, review round 2): commit_assignment_diff's ledger row alone never
    upgraded the artifact's OWN bundle -- retrieval (app/retrieval/envelope.py) would return
    'unbound' forever, and AC1's "receive episode_ref: pending [ep-...]" was never actually true on
    the production write path (the AC5 test previously hand-stamped via dataclasses.replace,
    exercising no real write path). This exercises the REAL bundle-write path end to end: the
    DB-side store_objects/store_vector_index payload rows (read-modify-write, captured here since a
    live Postgres isn't available in this lane) AND the vault note's own frontmatter through the
    REAL guarded write seam (app.knowledge.write_ops.write_note_from_absolute) -- a real file
    write, read back from disk afterward, never an in-memory stub."""
    vault_root = tmp_path / "vault"
    note_path = vault_root / "notes" / "artifact.md"
    note_path.parent.mkdir(parents=True)
    object_id = "11111111-1111-4111-8111-111111111111"
    note_path.write_text(f"---\nuuid: {object_id}\ntitle: t\n---\n\nbody text\n", encoding="utf-8")

    monkeypatch.setattr(
        assignment_module,
        "_resolve_bundle_object_id_and_note_path",
        lambda artifact_ref, *, vault_root: (object_id, note_path),
    )

    rows: dict[tuple[str, str], dict[str, Any]] = {
        ("store_objects", object_id): {"kind": "note", "evidence_role": "reference"},
        ("store_vector_index", object_id): {"kind": "note", "evidence_role": "reference"},
    }
    executed: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _BundleConn(rows, executed))

    decision = AssignmentDecision(
        artifact_ref="vault.activity:row-1",
        episode_id="ep-bundle-0001-4333-8444-555555555555",
        scope="work",
        basis=BASIS_TIME_OVERLAP,
        confidence=TIME_OVERLAP_CONFIDENCE,
    )

    result = commit_assignment_diff([decision], [], write_guard=_allow_guard(), vault_root=vault_root)
    assert result == {"pending": 1, "corrected": 0}

    # DB-side: BOTH store rows were upgraded, and nothing else in their payload was touched.
    for table in ("store_objects", "store_vector_index"):
        payload = rows[(table, object_id)]
        assert payload["episode_ref"] == [decision.episode_id]
        assert payload["evidence_role"] == "reference"
        assert payload["kind"] == "note"

    # Vault-serialized: the note's OWN frontmatter, read back from disk (not an in-memory stub),
    # now carries the real pending binding.
    from scripts.yaml_roundtrip import load_frontmatter

    frontmatter, _body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter["episode_ref"] == [decision.episode_id]
    assert frontmatter["uuid"] == object_id


def test_staged_frontmatter_conflict_stops_assignment_before_db_bookkeeping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    note_path = vault_root / "notes" / "artifact.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("---\nuuid: object-stale\n---\n\nbody\n", encoding="utf-8")
    decision = AssignmentDecision(
        artifact_ref="vault.activity:row-stale",
        episode_id="ep-stale-0001-4333-8444-555555555555",
        scope="work",
        basis=BASIS_TIME_OVERLAP,
        confidence=TIME_OVERLAP_CONFIDENCE,
    )
    monkeypatch.setattr(
        assignment_module,
        "_resolve_bundle_object_id_and_note_path",
        lambda artifact_ref, *, vault_root: ("object-stale", note_path),
    )
    monkeypatch.setattr(
        "app.knowledge.write_ops.write_note_from_absolute",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            KnowledgeWriteConflict("rewritten note conflict staged")
        ),
    )
    monkeypatch.setattr(
        assignment_module,
        "conn_rw",
        lambda: (_ for _ in ()).throw(AssertionError("DB bookkeeping must not start")),
    )

    with pytest.raises(KnowledgeWriteConflict, match="conflict staged"):
        commit_assignment_diff(
            [decision],
            [],
            write_guard=_allow_guard(),
            vault_root=vault_root,
        )


def test_commit_assignment_diff_correction_clears_episode_ref_from_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3 (a correction is an ordinary bundle update too, consistent with Finding 1): when a
    re-cut invalidates a binding, the artifact's bundle (DB rows + note frontmatter) is corrected
    right alongside the ledger row -- never left stale at the old pending id."""
    vault_root = tmp_path / "vault"
    note_path = vault_root / "notes" / "artifact.md"
    note_path.parent.mkdir(parents=True)
    object_id = "22222222-2222-4222-8222-222222222222"
    stale_episode_id = "ep-stale-0001-4333-8444-555555555555"
    note_path.write_text(
        f"---\nuuid: {object_id}\nepisode_ref:\n  - {stale_episode_id}\ntitle: t\n---\n\nbody text\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        assignment_module,
        "_resolve_bundle_object_id_and_note_path",
        lambda artifact_ref, *, vault_root: (object_id, note_path),
    )

    rows: dict[tuple[str, str], dict[str, Any]] = {
        ("store_objects", object_id): {"kind": "note", "episode_ref": [stale_episode_id]},
        ("store_vector_index", object_id): {"kind": "note", "episode_ref": [stale_episode_id]},
    }
    executed: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _BundleConn(rows, executed))

    key = ("vault.activity:row-recut", stale_episode_id)
    result = commit_assignment_diff([], [key], write_guard=_allow_guard(), vault_root=vault_root)
    assert result == {"pending": 0, "corrected": 1}

    # The corrected episode id is gone from BOTH DB-side bundle rows; an empty result reverts to
    # the honest 'unbound' sentinel, never an empty array (schema requires non-empty arrays).
    for table in ("store_objects", "store_vector_index"):
        assert rows[(table, object_id)]["episode_ref"] == "unbound"

    from scripts.yaml_roundtrip import load_frontmatter

    frontmatter, _body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter["episode_ref"] == "unbound"


def test_bundle_object_id_resolution_returns_none_for_heimdal_refs_and_no_vault_root() -> None:
    """Heimdal-sourced artifact_refs never resolve to a bundle today (no "Heimdal observation's
    downstream candidate" bundle-minting path exists yet, HEIM-2 boundary) -- a documented scope
    boundary, never a fabricated write. ``vault_root=None`` short-circuits unconditionally too."""
    from app.episodes.assignment import _resolve_bundle_object_id_and_note_path

    assert _resolve_bundle_object_id_and_note_path(
        "heimdal.observations:obs-1", vault_root="/tmp/vault"
    ) == (None, None)
    assert _resolve_bundle_object_id_and_note_path(
        "vault.activity:row-1", vault_root=None
    ) == (None, None)


# ---------------------------------------------------------------------------
# Round-2 Finding 2: vault-canonical frontmatter stamped FIRST, then DB commit
# ---------------------------------------------------------------------------


def _note_with_uuid(tmp_path: Path, object_id: str) -> Path:
    vault_root = tmp_path / "vault"
    note_path = vault_root / "notes" / "artifact.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(f"---\nuuid: {object_id}\ntitle: t\n---\n\nbody\n", encoding="utf-8")
    return vault_root


def test_commit_stamps_frontmatter_before_touching_the_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-2 Finding 2 (ordering): the vault-canonical frontmatter stamp must happen BEFORE the
    DB ledger+payload transaction, so a frontmatter failure aborts before any commit rather than
    leaving a committed ledger row in front of an un-stamped note."""
    object_id = "66666666-6666-4666-8666-666666666666"
    vault_root = _note_with_uuid(tmp_path, object_id)
    note_path = vault_root / "notes" / "artifact.md"
    monkeypatch.setattr(
        assignment_module,
        "_resolve_bundle_object_id_and_note_path",
        lambda artifact_ref, *, vault_root: (object_id, note_path),
    )

    order: list[str] = []

    import app.knowledge.write_ops as write_ops

    real_write = write_ops.write_note_from_absolute

    def _tracking_write(*args: Any, **kwargs: Any):
        order.append("frontmatter")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(write_ops, "write_note_from_absolute", _tracking_write)

    class _OrderCursor:
        def __init__(self) -> None:
            self._result: Any = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            order.append("db")
            self._result = (
                (True, True, ["vault_binding_id", "artifact_ref", "episode_id"])
                if "to_regclass" in sql
                else None
            )

        def fetchone(self):
            return self._result

    class _OrderConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _OrderCursor()

    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _OrderConn())

    decision = AssignmentDecision(
        artifact_ref="vault.activity:row-order",
        episode_id="ep-order-0001-4333-8444-555555555555",
        scope="work",
        basis=BASIS_TIME_OVERLAP,
        confidence=TIME_OVERLAP_CONFIDENCE,
    )
    commit_assignment_diff([decision], [], write_guard=_allow_guard(), vault_root=vault_root)

    assert "frontmatter" in order and "db" in order
    assert order.index("frontmatter") < order.index("db"), (
        "the canonical frontmatter stamp must precede any DB statement (Finding 2 ordering)"
    )


def test_commit_frontmatter_write_failure_aborts_before_any_db_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-2 Finding 2: if the frontmatter write raises (OSError, concurrent editor, note
    moved), the whole tick aborts BEFORE the DB transaction opens -- zero ledger rows -- so a
    later tick re-computes and idempotently re-stamps, never a committed ledger row wedged in
    front of an un-stamped note."""
    object_id = "77777777-7777-4777-8777-777777777777"
    vault_root = _note_with_uuid(tmp_path, object_id)
    note_path = vault_root / "notes" / "artifact.md"
    monkeypatch.setattr(
        assignment_module,
        "_resolve_bundle_object_id_and_note_path",
        lambda artifact_ref, *, vault_root: (object_id, note_path),
    )

    import app.knowledge.write_ops as write_ops

    def _boom_write(*args: Any, **kwargs: Any):
        raise OSError("disk full / note locked mid-tick")

    monkeypatch.setattr(write_ops, "write_note_from_absolute", _boom_write)
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _fake_conn_that_must_not_be_called()
    )

    decision = AssignmentDecision(
        artifact_ref="vault.activity:row-fail",
        episode_id="ep-fail-0001-4333-8444-555555555555",
        scope="work",
        basis=BASIS_TIME_OVERLAP,
        confidence=TIME_OVERLAP_CONFIDENCE,
    )
    with pytest.raises(OSError):
        commit_assignment_diff([decision], [], write_guard=_allow_guard(), vault_root=vault_root)


# ---------------------------------------------------------------------------
# Round-2 Finding 3: targeted jsonb_set never clobbers a concurrent sibling-key write
# ---------------------------------------------------------------------------


def test_commit_jsonb_set_preserves_concurrent_sibling_key_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-2 Finding 3 (concurrency): the DB payload update is a targeted jsonb_set on the
    episode_ref key only -- a concurrent writer changing a DIFFERENT key (evidence_role) between
    our SELECT and our UPDATE is NOT clobbered. A blind read-modify-write of the whole payload
    column WOULD write back the stale evidence_role; jsonb_set does not."""
    object_id = "88888888-8888-4888-8888-888888888888"
    vault_root = _note_with_uuid(tmp_path, object_id)
    note_path = vault_root / "notes" / "artifact.md"
    monkeypatch.setattr(
        assignment_module,
        "_resolve_bundle_object_id_and_note_path",
        lambda artifact_ref, *, vault_root: (object_id, note_path),
    )

    rows: dict[tuple[str, str], dict[str, Any]] = {
        ("store_objects", object_id): {"kind": "note", "evidence_role": "reference"},
        ("store_vector_index", object_id): {"kind": "note", "evidence_role": "reference"},
    }

    class _RaceCursor:
        def __init__(self) -> None:
            self._result: Any = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            stripped = sql.strip()
            if "to_regclass" in stripped:
                self._result = (True, True, ["vault_binding_id", "artifact_ref", "episode_id"])
                return
            if stripped.startswith("SELECT payload FROM store_"):
                table = "store_objects" if "store_objects" in stripped else "store_vector_index"
                binding_id, obj = params
                assert binding_id == assignment_module.COMPATIBILITY_BINDING_ID
                row = rows.get((table, obj))
                self._result = (json.dumps(row),) if row is not None else None
                # A concurrent writer lands a DIFFERENT-key change AFTER our read, BEFORE our
                # jsonb_set UPDATE -- exactly the READ COMMITTED window Finding 3 is about.
                if row is not None:
                    row["evidence_role"] = "evidence"
                return
            if stripped.startswith("UPDATE store_"):
                assert "jsonb_set" in stripped and "'{episode_ref}'" in stripped, stripped
                table = "store_objects" if "store_objects" in stripped else "store_vector_index"
                episode_ref_json, binding_id, obj = params
                assert binding_id == assignment_module.COMPATIBILITY_BINDING_ID
                existing = rows.get((table, obj))
                if existing is not None:
                    existing["episode_ref"] = json.loads(episode_ref_json)
                self._result = None
                return
            self._result = None

        def fetchone(self):
            return self._result

    class _RaceConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _RaceCursor()

    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _RaceConn())

    decision = AssignmentDecision(
        artifact_ref="vault.activity:row-race",
        episode_id="ep-race-0001-4333-8444-555555555555",
        scope="work",
        basis=BASIS_TIME_OVERLAP,
        confidence=TIME_OVERLAP_CONFIDENCE,
    )
    commit_assignment_diff([decision], [], write_guard=_allow_guard(), vault_root=vault_root)

    for table in ("store_objects", "store_vector_index"):
        # Our episode_ref landed AND the concurrent writer's evidence_role change survived --
        # jsonb_set touched only its own key.
        assert rows[(table, object_id)]["episode_ref"] == [decision.episode_id]
        assert rows[(table, object_id)]["evidence_role"] == "evidence"


# ---------------------------------------------------------------------------
# PR #3520 review round 1 P1 (comment 3565551866) + Finding 3 (AC6 correction
# reachability): both reached through the REAL production tick, not just the pure diff layer.
# ---------------------------------------------------------------------------


def test_tick_backfills_closed_segment_founding_artifacts_into_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #3520 review round 1 P1 (comment 3565551866): a segment's own founding artifacts (its
    ``derived_from``) may have folded in on an EARLIER tick and are therefore absent from THIS
    tick's ``signals`` -- without the backfill, a provenance-anchored source artifact never earns
    an ``episode_artifact_binding`` row unless it happens to be re-delivered. A carried-over open
    segment (scope 'work', founded by 'heimdal.observations:founding-1' on an earlier tick) closes
    THIS tick via a >45min gap against a brand-new signal; the founding ref must still appear in
    ``to_insert``, bound by PROVENANCE to the newly-closed episode -- even though it is absent from
    this tick's own ``signals``."""
    existing_open = OpenSegment(
        scope="work",
        start=_dt(8, 0),
        last_signal_at=_dt(8, 30),
        derived_from=("heimdal.observations:founding-1",),
        signal_ids=frozenset({"founding-1"}),
    )
    new_row = _heimdal_row(observation_id="new-2", observed_at_start=_dt(10, 0), sequence=1)

    captured: dict[str, Any] = {}

    def _fake_commit(to_insert, to_correct, write_guard=None, vault_root=None):
        captured["to_insert"] = to_insert
        captured["to_correct"] = to_correct
        return {"pending": len(to_insert), "corrected": len(to_correct)}

    monkeypatch.setattr(
        segmenter, "enumerate_consumable_streams", lambda *a, **k: (SimpleNamespace(stream_id=HEIMDAL_STREAM_ID),)
    )
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: [new_row])
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda *a, **k: None)
    monkeypatch.setattr(
        segmenter.engine_state,
        "all_state_with_prefix",
        lambda prefix: {"open_segment:work": existing_open.to_state()},
    )
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
    monkeypatch.setattr(segmenter, "commit_assignment_diff", _fake_commit)

    result = run_segmentation_tick(vault_root=tmp_path / "vault", write_guard=_allow_guard())

    # The old segment (founding-1) shift-closed via the >45min gap; the new signal opened its own
    # segment, still open at tick end.
    assert len(result["proposed"]) == 1, result
    assert result["open_segments"] == 1, result

    by_ref = {d.artifact_ref: d for d in captured["to_insert"]}
    assert "heimdal.observations:founding-1" in by_ref, (
        "the closed segment's own founding artifact must be backfilled into assignment even "
        "though it is absent from this tick's own signals"
    )
    founding_decision = by_ref["heimdal.observations:founding-1"]
    assert founding_decision.basis == BASIS_PROVENANCE
    assert founding_decision.confidence == PROVENANCE_CONFIDENCE
    assert founding_decision.episode_id == result["proposed"][0]


def test_tick_reconciles_stale_binding_for_recut_episode_without_signal_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review gate round 1 CONFIRMED (Finding 3, AC6 correction reachability): a binding recorded
    on a PRIOR tick for an artifact that does not resurface as a signal THIS tick (the common
    re-cut-invalidation case -- ERE-07 narrows an episode without re-delivering the original
    signal) must still be reachable for correction via the PRODUCTION tick, not just the pure
    ``diff_assignments`` layer. A persisted episode (already narrowed so it no longer covers the
    stale artifact) is the only candidate this tick; the stale binding is fed in via
    ``read_existing_bindings_for_episodes`` (keyed by episode_id, not this-tick artifact_refs) and
    must surface in ``to_correct``."""
    persisted_episode = EpisodeBoundsRecord(
        episode_id="ep-recut-0001-4333-8444-555555555555",
        scope="work",
        start=_dt(9, 0),
        end=_dt(9, 15),  # re-cut narrower: no longer covers the stale artifact's 09:20
        derived_from=(),
    )
    # A signal THIS tick for a DIFFERENT artifact in the same scope -- touches the scope (so the
    # persisted episode is read as a candidate) without re-delivering the stale artifact itself.
    fresh_row = _heimdal_row(observation_id="fresh-1", observed_at_start=_dt(9, 5), sequence=1)

    stale_key = ("heimdal.observations:stale-1", persisted_episode.episode_id)
    stale_row_for_episode = {
        stale_key: {
            "binding_state": BINDING_STATE_ACTIVE,
            "basis": BASIS_TIME_OVERLAP,
            "artifact_ref": stale_key[0],
            "episode_id": stale_key[1],
        }
    }

    captured: dict[str, Any] = {}

    def _fake_commit(to_insert, to_correct, write_guard=None, vault_root=None):
        captured["to_insert"] = to_insert
        captured["to_correct"] = to_correct
        return {"pending": len(to_insert), "corrected": len(to_correct)}

    monkeypatch.setattr(
        segmenter, "enumerate_consumable_streams", lambda *a, **k: (SimpleNamespace(stream_id=HEIMDAL_STREAM_ID),)
    )
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: [fresh_row])
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda *a, **k: None)
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    monkeypatch.setattr(
        segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [persisted_episode]
    )
    # THIS tick's own artifact_refs (just 'fresh-1') never surface the stale binding -- only the
    # by-episode read does, proving the reconciliation is reachable without signal replay.
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(
        segmenter,
        "read_existing_bindings_for_episodes",
        lambda episode_ids: dict(stale_row_for_episode) if persisted_episode.episode_id in episode_ids else {},
    )
    monkeypatch.setattr(segmenter, "commit_assignment_diff", _fake_commit)

    run_segmentation_tick(vault_root=tmp_path / "vault", write_guard=_allow_guard())

    assert captured["to_correct"] == [stale_key], (
        "a prior-tick binding for an artifact absent from this tick's signals must still be "
        "reconciled for correction once its episode is re-cut out from under it"
    )
