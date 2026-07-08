from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.builderops.epic_run_state import (
    DEFAULT_EPIC_RUNS_DIR,
    EpicRunStateError,
    apply_epic_run_update,
    create_epic_run_state,
    deserialize_epic_run_state,
    epic_run_state_path,
    load_epic_run_state,
    new_epic_run_state,
    record_dispatcher_status,
    serialize_epic_run_state,
    update_epic_run_state,
)


def test_create_load_update_round_trip_uses_temp_runtime(tmp_path: Path) -> None:
    run_id = "issue-3229-run-001"
    state = create_epic_run_state(
        3229,
        run_id,
        root=tmp_path,
        child_queue=[{"issue_number": 3230, "state": "queued"}],
        reusable_constraints=[
            {
                "id": "no-dispatcher-change",
                "text": "do not change dispatcher behavior in this slice",
            }
        ],
        stop_conditions=[
            {
                "id": "no-github-dry-run-writes",
                "text": "dry-run helpers must not perform GitHub mutations",
            }
        ],
    )

    path = epic_run_state_path(run_id, root=tmp_path)
    assert path == tmp_path / f"{run_id}.json"
    assert path.exists()
    assert load_epic_run_state(run_id, root=tmp_path) == state

    updated = update_epic_run_state(
        run_id,
        root=tmp_path,
        issue_mappings={
            "3230": {
                "branch": "codex/3230-run-state",
                "pr_number": 55,
                "worktree": "/tmp/agentic-pkm-mvp-3230",
            }
        },
        validation_status={"3230": {"pytest": "passed"}},
        review_findings=[
            {"id": "review-1", "severity": "low", "status": "resolved"}
        ],
        follow_ups=[{"id": "follow-up-1", "summary": "wire helper into skill"}],
        compact_receipts=[
            {"id": "receipt-1", "summary": "created local run-state file"}
        ],
        last_verified_head_sha="abc1234",
    )

    assert updated["epic_issue_number"] == 3229
    assert updated["issue_mappings"]["3230"]["pr_number"] == 55
    assert updated["validation_status"]["3230"]["pytest"] == "passed"
    assert updated["review_findings"] == [
        {"id": "review-1", "severity": "low", "status": "resolved"}
    ]
    assert updated["last_verified_head_sha"] == "abc1234"
    assert load_epic_run_state(run_id, root=tmp_path) == updated


def test_serialization_is_deterministic_and_sorted() -> None:
    state = new_epic_run_state(
        3229,
        "run-deterministic",
        issue_mappings={
            9: {"worktree": "/tmp/w9", "branch": "codex/9"},
            "2": {"branch": "codex/2", "pr_number": 22},
        },
        dispatcher_status={"tasks": 3, "db_exists": True, "running": False},
    )

    first = serialize_epic_run_state(state)
    second = serialize_epic_run_state(deserialize_epic_run_state(first))

    assert first == second
    assert first.endswith("\n")
    parsed = json.loads(first)
    assert list(parsed) == sorted(parsed)
    assert parsed["issue_mappings"] == {
        "2": {"branch": "codex/2", "pr_number": 22},
        "9": {"branch": "codex/9", "worktree": "/tmp/w9"},
    }


def test_update_helpers_are_idempotent_for_lists_and_mappings(
    tmp_path: Path,
) -> None:
    run_id = "run-idempotent"
    create_epic_run_state(3229, run_id, root=tmp_path)

    update = {
        "child_queue": [
            {"issue_number": 4000, "state": "queued", "title": "first child"}
        ],
        "issue_mappings": {"4000": {"branch": "codex/4000"}},
        "review_findings": [
            {"id": "finding-1", "status": "open", "summary": "needs test"}
        ],
        "compact_receipts": [
            {"id": "receipt-4000", "summary": "state update captured"}
        ],
    }

    first = update_epic_run_state(run_id, root=tmp_path, **update)
    second = update_epic_run_state(run_id, root=tmp_path, **update)

    assert first == second
    assert len(second["child_queue"]) == 1
    assert len(second["review_findings"]) == 1
    assert len(second["compact_receipts"]) == 1

    merged = update_epic_run_state(
        run_id,
        root=tmp_path,
        child_queue=[{"issue_number": 4000, "state": "done"}],
        issue_mappings={"4000": {"pr_number": 101, "worktree": "/tmp/wt"}},
    )

    assert len(merged["child_queue"]) == 1
    assert merged["child_queue"][0] == {
        "issue_number": 4000,
        "state": "done",
        "title": "first child",
    }
    assert merged["issue_mappings"]["4000"] == {
        "branch": "codex/4000",
        "pr_number": 101,
        "worktree": "/tmp/wt",
    }


def test_dispatcher_status_is_recorded_as_local_snapshot() -> None:
    state = new_epic_run_state(3229, "run-dispatcher-status")

    updated = record_dispatcher_status(
        state,
        {
            "db_exists": True,
            "events": True,
            "tasks_total": 7,
            "singleton": "demerzel",
        },
    )

    assert updated["dispatcher_status"] == {
        "db_exists": True,
        "events": True,
        "singleton": "demerzel",
        "tasks_total": 7,
    }
    assert state["dispatcher_status"] == {}


def test_default_runtime_path_shape_without_writing() -> None:
    assert epic_run_state_path("run-1") == DEFAULT_EPIC_RUNS_DIR / "run-1.json"


@pytest.mark.parametrize(
    "run_id",
    ["", " ", "../escape", "nested/run", "nested\\run", ".", "..", "-bad"],
)
def test_rejects_unsafe_run_ids(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(EpicRunStateError):
        epic_run_state_path(run_id, root=tmp_path)

    assert not (tmp_path.parent / "escape.json").exists()


def test_create_rejects_epic_mismatch_for_existing_run(tmp_path: Path) -> None:
    create_epic_run_state(3229, "run-owned", root=tmp_path)

    with pytest.raises(EpicRunStateError, match="already belongs to epic 3229"):
        create_epic_run_state(3230, "run-owned", root=tmp_path)


def test_apply_update_rejects_unknown_fields() -> None:
    state = new_epic_run_state(3229, "run-unknown")

    with pytest.raises(EpicRunStateError, match="unknown run-state update"):
        apply_epic_run_update(state, lifecycle_status="Review")

    with pytest.raises(EpicRunStateError, match="unknown run-state update"):
        apply_epic_run_update(state, run_id="other-run")
