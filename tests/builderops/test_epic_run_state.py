from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
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


def _run_builderops(args: list[str]):
    return CliRunner().invoke(
        builderops_standalone_root,
        ["builderops", *args],
        catch_exceptions=False,
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
        "reusable_constraints": [
            {
                "id": "constraint-1",
                "text": "run-state is coordination evidence only",
            }
        ],
        "follow_ups": [
            {"id": "follow-up-1", "summary": "integrate state into epic runner"}
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
    assert len(second["reusable_constraints"]) == 1
    assert len(second["follow_ups"]) == 1
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


def test_concurrent_updates_are_serialized(tmp_path: Path) -> None:
    run_id = "run-concurrent"
    create_epic_run_state(3229, run_id, root=tmp_path)
    start = threading.Event()

    def write_issue(issue_number: int) -> None:
        start.wait(timeout=5)

        def add_mapping(state: dict[str, object]) -> dict[str, object]:
            updated = apply_epic_run_update(
                state,
                issue_mappings={
                    str(issue_number): {
                        "branch": f"codex/{issue_number}",
                        "pr_number": issue_number + 100,
                    }
                },
                validation_status={
                    str(issue_number): {"pytest": "passed"},
                },
            )
            time.sleep(0.01)
            return updated

        update_epic_run_state(run_id, root=tmp_path, updater=add_mapping)

    issue_numbers = list(range(4100, 4112))
    with ThreadPoolExecutor(max_workers=len(issue_numbers)) as executor:
        futures = [executor.submit(write_issue, issue) for issue in issue_numbers]
        start.set()
        for future in futures:
            future.result(timeout=5)

    final_state = load_epic_run_state(run_id, root=tmp_path)

    assert sorted(final_state["issue_mappings"]) == [
        str(issue) for issue in issue_numbers
    ]
    assert sorted(final_state["validation_status"]) == [
        str(issue) for issue in issue_numbers
    ]
    assert final_state["issue_mappings"]["4100"]["pr_number"] == 4200
    assert final_state["validation_status"]["4111"] == {"pytest": "passed"}


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


def test_cli_dry_run_previews_state_without_writing(tmp_path: Path) -> None:
    result = _run_builderops(
        [
            "epic-run-state",
            "record",
            "--epic-issue-number",
            "3229",
            "--run-id",
            "run-dry",
            "--root",
            str(tmp_path),
            "--update-json",
            json.dumps(
                {
                    "child_queue": [
                        {"issue_number": 3247, "state": "queued"},
                    ],
                    "dispatcher_status": {"db_exists": False},
                }
            ),
            "--dry-run",
            "--json",
        ]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["state_exists"] is False
    assert payload["state"]["child_queue"] == [
        {"issue_number": 3247, "state": "queued"}
    ]
    assert payload["state"]["dispatcher_status"] == {"db_exists": False}
    assert not epic_run_state_path("run-dry", root=tmp_path).exists()


def test_cli_record_resume_is_idempotent_for_epic_runner_fields(
    tmp_path: Path,
) -> None:
    update = {
        "child_queue": [{"issue_number": 3247, "state": "queued"}],
        "issue_mappings": {
            "3247": {
                "branch": "codex/3247-deliver-issue-set-run-state",
                "pr_number": 3250,
                "worktree": "/tmp/wt-3247",
            }
        },
        "validation_status": {"3247": {"pytest": "passed"}},
        "review_findings": [{"id": "finding-3247", "status": "resolved"}],
        "reusable_constraints": [
            {"id": "state-not-authority", "text": "state is evidence only"}
        ],
        "follow_ups": [{"id": "follow-up-3247", "summary": "wire dispatcher later"}],
        "stop_conditions": [
            {"id": "no-github-dry-run-writes", "summary": "dry-run is local only"}
        ],
        "dispatcher_status": {"db_exists": False},
        "compact_receipts": [{"id": "receipt-3247", "summary": "state recorded"}],
        "last_verified_head_sha": "abc1234",
    }
    args = [
        "epic-run-state",
        "record",
        "--epic-issue-number",
        "3229",
        "--run-id",
        "run-resume",
        "--root",
        str(tmp_path),
        "--update-json",
        json.dumps(update),
        "--json",
    ]

    first = _run_builderops(args)
    second = _run_builderops(args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_payload = json.loads(first.output)
    second_payload = json.loads(second.output)
    assert first_payload["state"] == second_payload["state"]
    state = second_payload["state"]
    assert len(state["child_queue"]) == 1
    assert len(state["review_findings"]) == 1
    assert len(state["reusable_constraints"]) == 1
    assert len(state["follow_ups"]) == 1
    assert len(state["compact_receipts"]) == 1
    assert state["issue_mappings"]["3247"]["pr_number"] == 3250
    assert state["validation_status"]["3247"] == {"pytest": "passed"}
    assert state["stop_conditions"] == update["stop_conditions"]
    assert state["last_verified_head_sha"] == "abc1234"

    shown = _run_builderops(
        [
            "epic-run-state",
            "show",
            "run-resume",
            "--root",
            str(tmp_path),
            "--json",
        ]
    )
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output) == state


def test_cli_recreates_deleted_state_from_supplied_evidence(tmp_path: Path) -> None:
    update = {
        "child_queue": [{"issue_number": 3247, "state": "queued"}],
        "reusable_constraints": [
            {
                "id": "rebuildable",
                "text": "missing local state must be rebuilt from explicit evidence",
            }
        ],
    }
    args = [
        "epic-run-state",
        "record",
        "--epic-issue-number",
        "3229",
        "--run-id",
        "run-recreate",
        "--root",
        str(tmp_path),
        "--update-json",
        json.dumps(update),
        "--json",
    ]

    created = _run_builderops(args)
    assert created.exit_code == 0, created.output
    epic_run_state_path("run-recreate", root=tmp_path).unlink()

    recreated = _run_builderops(args)

    assert recreated.exit_code == 0, recreated.output
    state = json.loads(recreated.output)["state"]
    assert state["epic_issue_number"] == 3229
    assert state["child_queue"] == update["child_queue"]
    assert state["reusable_constraints"] == update["reusable_constraints"]


def test_cli_rejects_epic_mismatch_before_writing(tmp_path: Path) -> None:
    create_epic_run_state(
        3229,
        "run-owned-by-3229",
        root=tmp_path,
        child_queue=[{"issue_number": 3247, "state": "queued"}],
    )

    result = _run_builderops(
        [
            "epic-run-state",
            "record",
            "--epic-issue-number",
            "3230",
            "--run-id",
            "run-owned-by-3229",
            "--root",
            str(tmp_path),
            "--update-json",
            json.dumps(
                {
                    "child_queue": [
                        {"issue_number": 9999, "state": "should-not-write"}
                    ]
                }
            ),
            "--json",
        ]
    )

    assert result.exit_code != 0
    assert "already belongs to epic 3229" in result.output
    state = load_epic_run_state("run-owned-by-3229", root=tmp_path)
    assert state["child_queue"] == [{"issue_number": 3247, "state": "queued"}]
