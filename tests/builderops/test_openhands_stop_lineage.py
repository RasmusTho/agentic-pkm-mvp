"""Stop and checkpoint generation boundaries for a finished reviewer."""

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_pr_cycle_p2_repair import _review_release_setup


def _reviewer(tmp_path, monkeypatch, *, unique=True):
    layout, _, saved = _review_release_setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, branch="codex/example", started_at="2026-01-01T00:00:00Z",
                      image="agent-server@sha256:" + "c" * 64)
    observed = cycle._mapping(layout, "reviewer")
    engine = cycle._worker_runner
    real_stop = ew.stop_worker
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw:
                        real_stop(layout, worker, runner=engine, **kw))
    monkeypatch.setattr(ew, "_inspect", lambda *args, **kwargs:
                        ({"present": True, "readable": True, "unique_work": unique,
                          "branch": "codex/example"}, []))
    return layout, saved, observed, engine, real_stop


def test_same_reason_later_stop_and_checkpoint_survive_old_review_retry(tmp_path, monkeypatch):
    layout, saved, observed, engine, real_stop = _reviewer(tmp_path, monkeypatch)
    attempts = []

    def checkpoint(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ew.EpicWorkspaceError("checkpoint interrupted")
        return {"ref": "newer-checkpoint"}

    monkeypatch.setattr(ew, "_checkpoint", checkpoint)
    with pytest.raises(ew.EpicWorkspaceError, match="interrupted"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    old = cycle._mapping(layout, "reviewer")
    real_stop(layout, "reviewer", reason="review completed; release model capacity", runner=engine)
    newer = cycle._mapping(layout, "reviewer")
    assert newer["stop_id"] != old["stop_id"]
    with pytest.raises(cycle.CycleError, match="newer reviewer stop"):
        cycle._release_reviewer(layout, "reviewer", saved, newer)
    latest = cycle._mapping(layout, "reviewer")
    assert latest["stop_id"] == newer["stop_id"]
    assert latest["work_at_stop"] == newer["work_at_stop"]
    assert latest["work_at_stop"]["checkpoint"] == {"ref": "newer-checkpoint"}
    assert len(attempts) == 2
    assert not cycle._find(layout, 10, "release").get("stop_verified")


@pytest.mark.parametrize("reason", ["review completed; release model capacity", "maintenance"])
def test_new_incomplete_stop_invalidates_saved_receipt_and_verifier(tmp_path, monkeypatch, reason):
    layout, saved, observed, engine, real_stop = _reviewer(tmp_path, monkeypatch)
    attempts = []

    def checkpoint(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 2:
            raise ew.EpicWorkspaceError("new checkpoint interrupted")
        return {"ref": "first-checkpoint"}

    monkeypatch.setattr(ew, "_checkpoint", checkpoint)
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    original = cycle._mapping(layout, "reviewer")
    with pytest.raises(ew.EpicWorkspaceError, match="interrupted"):
        real_stop(layout, "reviewer", reason=reason, runner=engine)
    newer = cycle._mapping(layout, "reviewer")
    assert newer["stop_id"] != original["stop_id"]
    assert "checkpoint" not in newer["work_at_stop"]
    with pytest.raises(cycle.CycleError, match="generation changed"):
        cycle._release_reviewer(layout, "reviewer", saved, newer)
    monkeypatch.setattr(cycle, "_command", lambda *args, **kwargs: pytest.fail("verifier must not be created"))
    with pytest.raises(cycle.CycleError, match="generation changed"):
        cycle.sandbox_verify(layout, "reviewer", "a" * 40, ["tests/example.py"], "/approved/venv", saved)
    assert cycle._mapping(layout, "reviewer")["work_at_stop"] == newer["work_at_stop"]
    assert len(attempts) == 2


def test_retry_and_completed_receipt_preserve_same_stop_and_checkpoint(tmp_path, monkeypatch):
    layout, saved, observed, _, _ = _reviewer(tmp_path, monkeypatch)
    attempts = []

    def checkpoint(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ew.EpicWorkspaceError("checkpoint interrupted")
        return {"ref": "original-checkpoint"}

    monkeypatch.setattr(ew, "_checkpoint", checkpoint)
    with pytest.raises(ew.EpicWorkspaceError, match="interrupted"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    interrupted = cycle._mapping(layout, "reviewer")
    stop_id = interrupted["stop_id"]
    assert saved["stop_intent"]["stop_id"] == stop_id
    cycle._release_reviewer(layout, "reviewer", saved, interrupted)
    finished = cycle._mapping(layout, "reviewer")
    assert finished["stop_id"] == stop_id
    assert finished["work_at_stop"]["checkpoint"] == {"ref": "original-checkpoint"}
    assert cycle._find(layout, 10, "release")["stop_verified"] is True
    cycle._release_reviewer(layout, "reviewer", saved, finished)
    assert cycle._mapping(layout, "reviewer")["work_at_stop"] == finished["work_at_stop"]
    assert len(attempts) == 2


def test_crash_after_checkpoint_reuses_same_generation_before_receipt(tmp_path, monkeypatch):
    layout, saved, observed, _, _ = _reviewer(tmp_path, monkeypatch)
    attempts = []
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs:
                        attempts.append(1) or {"ref": "original-checkpoint"})
    monkeypatch.setattr(cycle, "_assert_stopped", lambda *args: (_ for _ in ()).throw(cycle.CycleError("lost readback")))
    with pytest.raises(cycle.CycleError, match="lost readback"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    completed = cycle._mapping(layout, "reviewer")
    assert not cycle._find(layout, 10, "release").get("stop_verified")
    monkeypatch.setattr(cycle, "_assert_stopped", lambda *args: None)
    cycle._release_reviewer(layout, "reviewer", saved, completed)
    assert cycle._mapping(layout, "reviewer")["work_at_stop"] == completed["work_at_stop"]
    assert saved["stop_intent"]["stop_id"] == completed["stop_id"]
    assert len(attempts) == 1


def test_clean_checkout_can_complete_without_checkpoint_and_reuse_receipt(tmp_path, monkeypatch):
    layout, saved, observed, _, _ = _reviewer(tmp_path, monkeypatch, unique=False)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: None)
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    stopped = cycle._mapping(layout, "reviewer")
    assert stopped["work_at_stop"]["checkpoint"] is None
    assert saved["stop_intent"]["checkpoint"] is None
    cycle._release_reviewer(layout, "reviewer", saved, stopped)


@pytest.mark.parametrize("verified", [False, True])
def test_legacy_review_intent_without_stop_token_is_actionably_refused(tmp_path, monkeypatch, verified):
    layout, saved, observed, _, _ = _reviewer(tmp_path, monkeypatch)
    saved["stop_intent"] = {"container_id": observed["container_id"], "assignment": ew.assignment_of(observed)}
    saved["stop_verified"] = verified
    monkeypatch.setattr(ew, "stop_worker", lambda *args, **kwargs: pytest.fail("ambiguous stop must not run"))
    with pytest.raises(cycle.CycleError, match="no exact stop generation.*reconcile"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    assert cycle._mapping(layout, "reviewer") == observed


def test_receipt_cannot_certify_a_changed_checkpoint_for_same_stop(tmp_path, monkeypatch):
    layout, saved, observed, _, _ = _reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: {"ref": "original-checkpoint"})
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    ew._mutate_mapping(layout, "reviewer", lambda row: row["work_at_stop"].update(checkpoint={"ref": "different-checkpoint"}))
    current = cycle._mapping(layout, "reviewer")
    with pytest.raises(cycle.CycleError, match="does not match the current completed checkpoint"):
        cycle._release_reviewer(layout, "reviewer", saved, current)


def test_intent_saved_before_stop_cannot_replace_a_later_stop(tmp_path, monkeypatch):
    layout, saved, observed, engine, real_stop = _reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: {"ref": "checkpoint"})
    original = ew.stop_worker
    monkeypatch.setattr(ew, "stop_worker", lambda *args, **kwargs:
                        (_ for _ in ()).throw(ew.EpicWorkspaceError("before removal")))
    with pytest.raises(ew.EpicWorkspaceError, match="before removal"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    real_stop(layout, "reviewer", reason="review completed; release model capacity", runner=engine)
    newer = cycle._mapping(layout, "reviewer")
    monkeypatch.setattr(ew, "stop_worker", original)
    with pytest.raises(cycle.CycleError, match="newer reviewer stop"):
        cycle._release_reviewer(layout, "reviewer", saved, newer)
    assert cycle._mapping(layout, "reviewer")["work_at_stop"] == newer["work_at_stop"]
    assert not cycle._find(layout, 10, "release").get("stop_verified")


def test_unreadable_checkout_does_not_create_stop_receipt(tmp_path, monkeypatch):
    layout, saved, observed, _, _ = _reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(ew, "_inspect", lambda *args, **kwargs:
                        ({"present": True, "readable": False, "unique_work": True}, []))
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: None)
    with pytest.raises(cycle.CycleError, match="checkpoint is incomplete"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    stopped = cycle._mapping(layout, "reviewer")
    assert stopped["work_at_stop"]["readable"] is False
    assert "checkpoint" not in stopped["work_at_stop"]
    assert not cycle._find(layout, 10, "release").get("stop_verified")


def test_merge_effect_cannot_use_verification_from_a_older_stop(tmp_path, monkeypatch):
    layout, saved, observed, engine, real_stop = _reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: {"ref": "checkpoint"})
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    saved["verification"] = {"passed": True, "stop_id": saved["stop_intent"]["stop_id"]}
    real_stop(layout, "reviewer", reason="maintenance", runner=engine)
    newer = cycle._mapping(layout, "reviewer")
    monkeypatch.setattr(cycle, "_premerge", lambda *args: {"number": 10})
    monkeypatch.setattr(cycle, "_command", lambda *args, **kwargs: pytest.fail("merge must not run"))
    with pytest.raises(cycle.CycleError, match="generation changed"):
        cycle.merge_once(layout, {"number": 10, "head_sha": "a" * 40}, {"worker": "reviewer"}, saved)
    assert "merge_intent" not in saved
    assert cycle._mapping(layout, "reviewer")["work_at_stop"] == newer["work_at_stop"]


def test_unresolved_checkpoint_holder_blocks_receipt_use_at_merge(tmp_path, monkeypatch):
    layout, saved, observed, _, _ = _reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: {"ref": "checkpoint"})
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    saved["verification"] = {"passed": True, "stop_id": saved["stop_intent"]["stop_id"]}
    marker = {"name": "epicws-git-123456789abc", "container_id": "e" * 64, "protocol": ew.LAUNCH_PROTOCOL}
    ew._mutate_mapping(layout, "reviewer", lambda row: row.update(checkpoint_inspection_unknown=marker))
    monkeypatch.setattr(cycle, "_premerge", lambda *args: {"number": 10})
    monkeypatch.setattr(cycle, "_command", lambda *args, **kwargs: pytest.fail("merge must not run"))
    with pytest.raises(cycle.CycleError, match="cleanup remains unresolved"):
        cycle.merge_once(layout, {"number": 10, "head_sha": "a" * 40}, {"worker": "reviewer"}, saved)
    assert "merge_intent" not in saved
    assert cycle._mapping(layout, "reviewer")["checkpoint_inspection_unknown"] == marker


def test_standalone_checkpoint_changes_generation_without_reusing_old_receipt(tmp_path, monkeypatch):
    layout, saved, observed, engine, _ = _reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: {"ref": "first-checkpoint"})
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    first = cycle._mapping(layout, "reviewer")

    def later_checkpoint(layout, issue, *args, **kwargs):
        return ew._record_checkpoint(layout, issue, {"ref": "later-checkpoint", "status": "preserved"})

    monkeypatch.setattr(ew, "_checkpoint", later_checkpoint)
    result = ew.checkpoint_worker(layout, "reviewer", reason="manual checkpoint", runner=engine)
    current = cycle._mapping(layout, "reviewer")
    assert result["ref"] == "later-checkpoint"
    assert current["stop_id"] == first["stop_id"]
    assert current["work_at_stop"]["checkpoint"] == result
    assert current["checkpoints"][-1] == result
    with pytest.raises(cycle.CycleError, match="does not match the current completed checkpoint"):
        cycle._release_reviewer(layout, "reviewer", saved, current)


def test_standalone_checkpoint_interruption_fences_then_recovers_same_snapshot(tmp_path, monkeypatch):
    layout, saved, observed, engine, _ = _reviewer(tmp_path, monkeypatch)
    checkpoint = {"ref": "checkpoint"}
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: checkpoint)
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    first = cycle._mapping(layout, "reviewer")
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs:
                        (_ for _ in ()).throw(ew.EpicWorkspaceError("checkpoint interrupted")))
    with pytest.raises(ew.EpicWorkspaceError, match="interrupted"):
        ew.checkpoint_worker(layout, "reviewer", reason="manual checkpoint", runner=engine)
    incomplete = cycle._mapping(layout, "reviewer")
    assert incomplete["stop_id"] == first["stop_id"] and "checkpoint" not in incomplete["work_at_stop"]
    with pytest.raises(cycle.CycleError, match="checkpoint is incomplete"):
        cycle._release_reviewer(layout, "reviewer", saved, incomplete)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: checkpoint)
    ew.checkpoint_worker(layout, "reviewer", reason="manual retry", runner=engine)
    recovered = cycle._mapping(layout, "reviewer")
    cycle._release_reviewer(layout, "reviewer", saved, recovered)
    assert recovered["work_at_stop"] == first["work_at_stop"]


def test_standalone_checkpoint_keeps_detached_stop_preservation(tmp_path, monkeypatch):
    layout, saved, observed, engine, _ = _reviewer(tmp_path, monkeypatch, unique=False)
    monkeypatch.setattr(ew, "_inspect", lambda *args, **kwargs:
                        ({"present": True, "readable": True, "unique_work": False, "branch": None}, []))
    forces = []

    def checkpoint(*args, **kwargs):
        forces.append(kwargs["force"])
        return {"ref": "detached-checkpoint"} if kwargs["force"] else None

    monkeypatch.setattr(ew, "_checkpoint", checkpoint)
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    ew.checkpoint_worker(layout, "reviewer", reason="manual checkpoint", runner=engine)
    current = cycle._mapping(layout, "reviewer")
    cycle._release_reviewer(layout, "reviewer", saved, current)
    assert forces == [True, True]
    assert current["work_at_stop"]["checkpoint"] == {"ref": "detached-checkpoint"}


def test_standalone_checkpoint_of_changed_checkout_preserves_new_record_and_fences_old_stop(tmp_path, monkeypatch):
    layout, saved, observed, engine, _ = _reviewer(tmp_path, monkeypatch)
    monkeypatch.setattr(ew, "_checkpoint", lambda *args, **kwargs: {"ref": "first-checkpoint"})
    cycle._release_reviewer(layout, "reviewer", saved, observed)
    first = cycle._mapping(layout, "reviewer")
    monkeypatch.setattr(ew, "_inspect", lambda *args, **kwargs:
                        ({"present": True, "readable": True, "unique_work": True,
                          "branch": "codex/example", "head": "b" * 40}, []))

    def later_checkpoint(layout, issue, *args, **kwargs):
        return ew._record_checkpoint(layout, issue, {"ref": "newer-checkpoint", "status": "preserved"})

    monkeypatch.setattr(ew, "_checkpoint", later_checkpoint)
    result = ew.checkpoint_worker(layout, "reviewer", reason="manual checkpoint", runner=engine)
    current = cycle._mapping(layout, "reviewer")
    assert current["stop_id"] == first["stop_id"]
    assert current["checkpoints"][-1] == result
    assert "checkpoint" not in current["work_at_stop"]
    assert "head" not in current["work_at_stop"]
    with pytest.raises(cycle.CycleError, match="checkpoint is incomplete"):
        cycle._release_reviewer(layout, "reviewer", saved, current)
