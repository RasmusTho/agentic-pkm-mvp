from __future__ import annotations

import ast
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

try:  # pragma: no cover - POSIX-only, mirrors app.builderops.epic_run_state
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX host
    fcntl = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]

from app.builderops import cli as builderops_cli
from app.builderops import epic_run_state as epic_run_state_module
from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.epic_run_state import (
    DEFAULT_EPIC_RUNS_DIR,
    EpicRunStateError,
    TERMINAL_LEARNING_EVALUATION_OUTCOMES,
    assert_learning_evaluation_candidates_terminal,
    apply_epic_run_update,
    create_epic_run_state,
    create_independent_issue_run_state,
    new_independent_issue_run_state,
    deserialize_epic_run_state,
    save_epic_run_state,
    epic_run_state_path,
    load_epic_run_state,
    new_epic_run_state,
    record_dispatcher_status,
    serialize_epic_run_state,
    unresolved_learning_evaluation_candidates,
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


def test_learning_evaluation_candidates_update_and_terminal_outcomes(
    tmp_path: Path,
) -> None:
    run_id = "run-learning-candidates"
    create_epic_run_state(3229, run_id, root=tmp_path)

    unresolved = update_epic_run_state(
        run_id,
        root=tmp_path,
        learning_evaluation_candidates=[
            {
                "id": "learn-1",
                "source_refs": [
                    {"ref_type": "github_issue", "ref": "#3261"},
                    {"ref_type": "ci_check", "ref": "Unit tests (not pg)"},
                ],
                "upstream_artifact_hint": ".codex/skills/deliver-issue-set/SKILL.md",
                "evidence_kind": "review_finding",
                "summary": "Repeated context reload should become a reusable constraint.",
            }
        ],
    )

    assert unresolved_learning_evaluation_candidates(unresolved) == [
        unresolved["learning_evaluation_candidates"][0]
    ]
    with pytest.raises(EpicRunStateError, match="learn-1"):
        assert_learning_evaluation_candidates_terminal(unresolved)

    resolved = update_epic_run_state(
        run_id,
        root=tmp_path,
        learning_evaluation_candidates=[
            {
                "id": "learn-1",
                "source_refs": [
                    {"ref_type": "github_issue", "ref": "#3261"},
                    {"ref_type": "ci_check", "ref": "Unit tests (not pg)"},
                ],
                "upstream_artifact_hint": ".codex/skills/deliver-issue-set/SKILL.md",
                "evidence_kind": "review_finding",
                "summary": "Repeated context reload should become a reusable constraint.",
                "outcome": "issue_created",
                "outcome_ref": "github_issue:#3262",
            }
        ],
    )

    assert resolved["learning_evaluation_candidates"] == [
        {
            "id": "learn-1",
            "source_refs": [
                {"ref_type": "github_issue", "ref": "#3261"},
                {"ref_type": "ci_check", "ref": "Unit tests (not pg)"},
            ],
            "upstream_artifact_hint": ".codex/skills/deliver-issue-set/SKILL.md",
            "evidence_kind": "review_finding",
            "summary": "Repeated context reload should become a reusable constraint.",
            "outcome": "issue_created",
            "outcome_ref": "github_issue:#3262",
        }
    ]
    assert unresolved_learning_evaluation_candidates(resolved) == []
    assert_learning_evaluation_candidates_terminal(resolved)


@pytest.mark.parametrize("outcome", TERMINAL_LEARNING_EVALUATION_OUTCOMES)
def test_learning_evaluation_candidates_accept_each_terminal_outcome(
    tmp_path: Path,
    outcome: str,
) -> None:
    run_id = f"run-learning-outcome-{outcome}"
    create_epic_run_state(3229, run_id, root=tmp_path)

    resolved = update_epic_run_state(
        run_id,
        root=tmp_path,
        learning_evaluation_candidates=[
            {
                "id": f"learn-{outcome}",
                "source_refs": [{"ref_type": "github_issue", "ref": "#3261"}],
                "upstream_artifact_hint": "docs/development/DELIVERY_FEEDBACK_LOOP.md",
                "evidence_kind": "reevaluation_candidate",
                "outcome": outcome,
            }
        ],
    )

    assert resolved["learning_evaluation_candidates"][0]["outcome"] == outcome
    assert unresolved_learning_evaluation_candidates(resolved) == []
    assert_learning_evaluation_candidates_terminal(resolved)


def test_learning_evaluation_candidates_merge_by_candidate_id(tmp_path: Path) -> None:
    run_id = "run-learning-candidate-id"
    create_epic_run_state(3229, run_id, root=tmp_path)

    update_epic_run_state(
        run_id,
        root=tmp_path,
        learning_evaluation_candidates=[
            {
                "candidate_id": "learn-candidate-id",
                "source_refs": [{"ref_type": "github_issue", "ref": "#3261"}],
                "upstream_artifact_hint": "docs/development/DELIVERY_FEEDBACK_LOOP.md",
                "evidence_kind": "reevaluation_candidate",
            }
        ],
    )
    resolved = update_epic_run_state(
        run_id,
        root=tmp_path,
        learning_evaluation_candidates=[
            {
                "candidate_id": "learn-candidate-id",
                "source_refs": [{"ref_type": "github_issue", "ref": "#3261"}],
                "upstream_artifact_hint": "docs/development/DELIVERY_FEEDBACK_LOOP.md",
                "evidence_kind": "reevaluation_candidate",
                "outcome": "applied",
            }
        ],
    )

    assert len(resolved["learning_evaluation_candidates"]) == 1
    assert resolved["learning_evaluation_candidates"][0]["outcome"] == "applied"
    assert unresolved_learning_evaluation_candidates(resolved) == []


def test_learning_evaluation_candidates_merge_mixed_id_and_candidate_id(
    tmp_path: Path,
) -> None:
    run_id = "run-learning-mixed-ids"
    create_epic_run_state(3229, run_id, root=tmp_path)

    update_epic_run_state(
        run_id,
        root=tmp_path,
        learning_evaluation_candidates=[
            {
                "id": "learn-1",
                "candidate_id": "stable-candidate-1",
                "source_refs": [{"ref_type": "github_issue", "ref": "#3261"}],
                "upstream_artifact_hint": "docs/development/DELIVERY_FEEDBACK_LOOP.md",
                "evidence_kind": "reevaluation_candidate",
            }
        ],
    )
    resolved = update_epic_run_state(
        run_id,
        root=tmp_path,
        learning_evaluation_candidates=[
            {
                "candidate_id": "stable-candidate-1",
                "outcome": "debt_or_fitness_recorded",
                "outcome_ref": "docs/architecture/SBS_TRANSITION_DEBT.md::D12",
            }
        ],
    )

    assert resolved["learning_evaluation_candidates"] == [
        {
            "id": "learn-1",
            "candidate_id": "stable-candidate-1",
            "source_refs": [{"ref_type": "github_issue", "ref": "#3261"}],
            "upstream_artifact_hint": "docs/development/DELIVERY_FEEDBACK_LOOP.md",
            "evidence_kind": "reevaluation_candidate",
            "outcome": "debt_or_fitness_recorded",
            "outcome_ref": "docs/architecture/SBS_TRANSITION_DEBT.md::D12",
        }
    ]
    assert unresolved_learning_evaluation_candidates(resolved) == []


def test_learning_evaluation_candidate_validation_rejects_missing_refs_and_bad_outcome() -> None:
    state = new_epic_run_state(3229, "run-learning-invalid")

    with pytest.raises(EpicRunStateError, match="id or .*candidate_id"):
        apply_epic_run_update(
            state,
            learning_evaluation_candidates=[
                {
                    "source_refs": [{"ref_type": "github_issue", "ref": "#3261"}],
                    "upstream_artifact_hint": "AGENTS.md",
                    "evidence_kind": "tcd_signal",
                }
            ],
        )

    with pytest.raises(EpicRunStateError, match="source_refs"):
        apply_epic_run_update(
            state,
            learning_evaluation_candidates=[
                {
                    "id": "learn-bad",
                    "source_refs": [],
                    "upstream_artifact_hint": "AGENTS.md",
                    "evidence_kind": "tcd_signal",
                }
            ],
        )

    with pytest.raises(EpicRunStateError, match=r"source_refs\[0\]\.ref_type"):
        apply_epic_run_update(
            state,
            learning_evaluation_candidates=[
                {
                    "id": "learn-bad",
                    "source_refs": [{"ref": "#3261"}],
                    "upstream_artifact_hint": "AGENTS.md",
                    "evidence_kind": "tcd_signal",
                }
            ],
        )

    with pytest.raises(EpicRunStateError, match=r"source_refs\[0\]\.ref"):
        apply_epic_run_update(
            state,
            learning_evaluation_candidates=[
                {
                    "id": "learn-bad",
                    "source_refs": [{"ref_type": "github_issue", "ref": " "}],
                    "upstream_artifact_hint": "AGENTS.md",
                    "evidence_kind": "tcd_signal",
                }
            ],
        )

    with pytest.raises(EpicRunStateError, match="outcome must be one of"):
        apply_epic_run_update(
            state,
            learning_evaluation_candidates=[
                {
                    "id": "learn-bad",
                    "source_refs": [{"ref_type": "github_issue", "ref": "#3261"}],
                    "upstream_artifact_hint": "AGENTS.md",
                    "evidence_kind": "tcd_signal",
                    "outcome": "maybe_later",
                }
            ],
        )


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


def test_update_cannot_retarget_the_locked_run_path(tmp_path: Path) -> None:
    source_run_id = "run-identity-source"
    target_run_id = "run-identity-target"
    create_epic_run_state(
        3229,
        source_run_id,
        root=tmp_path,
        child_queue=[{"issue_number": 3247, "state": "source"}],
    )
    create_epic_run_state(
        3230,
        target_run_id,
        root=tmp_path,
        child_queue=[{"issue_number": 3250, "state": "target"}],
    )
    source_path = epic_run_state_path(source_run_id, root=tmp_path)
    target_path = epic_run_state_path(target_run_id, root=tmp_path)
    source_before = source_path.read_bytes()
    target_before = target_path.read_bytes()

    def retarget(state: dict[str, object]) -> dict[str, object]:
        state["run_id"] = target_run_id
        return state

    with pytest.raises(EpicRunStateError, match="must not change run_id"):
        update_epic_run_state(source_run_id, root=tmp_path, updater=retarget)

    assert source_path.read_bytes() == source_before
    assert target_path.read_bytes() == target_before


def test_update_cannot_change_loaded_owner_without_an_expected_owner(
    tmp_path: Path,
) -> None:
    epic_run_id = "run-identity-epic-owner"
    independent_run_id = "run-identity-independent-owner"
    create_epic_run_state(3229, epic_run_id, root=tmp_path)
    create_independent_issue_run_state(
        [4164, 4165], independent_run_id, root=tmp_path
    )

    def change_epic_owner(state: dict[str, object]) -> dict[str, object]:
        state["epic_issue_number"] = 3230
        return state

    def change_independent_owner(state: dict[str, object]) -> dict[str, object]:
        state["independent_issue_numbers"] = [4200]
        return state

    for run_id, updater in (
        (epic_run_id, change_epic_owner),
        (independent_run_id, change_independent_owner),
    ):
        path = epic_run_state_path(run_id, root=tmp_path)
        before = path.read_bytes()
        with pytest.raises(EpicRunStateError, match="must not change run owner"):
            update_epic_run_state(run_id, root=tmp_path, updater=updater)
        assert path.read_bytes() == before


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


def test_create_has_no_overwrite_owner_transfer_escape_hatch(tmp_path: Path) -> None:
    run_id = "run-owner-cannot-be-overwritten"
    create_epic_run_state(
        3229,
        run_id,
        root=tmp_path,
        child_queue=[{"issue_number": 3247, "state": "queued"}],
    )
    path = epic_run_state_path(run_id, root=tmp_path)
    before = path.read_bytes()

    with pytest.raises(EpicRunStateError, match="already belongs to epic 3229"):
        create_epic_run_state(3230, run_id, root=tmp_path, overwrite=True)

    assert path.read_bytes() == before


def test_public_save_cannot_transfer_existing_run_owner(tmp_path: Path) -> None:
    run_id = "run-public-save-owner"
    create_epic_run_state(3229, run_id, root=tmp_path)
    path = epic_run_state_path(run_id, root=tmp_path)
    before = path.read_bytes()

    with pytest.raises(EpicRunStateError, match="must not change run owner"):
        save_epic_run_state(new_epic_run_state(3230, run_id), root=tmp_path)

    assert path.read_bytes() == before


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
    assert payload["learning_evaluation_candidates_terminal"] is True
    assert payload["unresolved_learning_evaluation_candidates"] == []
    assert not epic_run_state_path("run-dry", root=tmp_path).exists()


def test_cli_surfaces_unresolved_learning_evaluation_candidates(tmp_path: Path) -> None:
    result = _run_builderops(
        [
            "epic-run-state",
            "record",
            "--epic-issue-number",
            "3229",
            "--run-id",
            "run-unresolved-candidate",
            "--root",
            str(tmp_path),
            "--update-json",
            json.dumps(
                {
                    "learning_evaluation_candidates": [
                        {
                            "id": "candidate-1",
                            "source_refs": [
                                {"ref_type": "github_issue", "ref": "#3261"}
                            ],
                            "upstream_artifact_hint": "docs/development/DELIVERY_FEEDBACK_LOOP.md",
                            "evidence_kind": "reevaluation_candidate",
                        }
                    ]
                }
            ),
            "--dry-run",
            "--json",
        ]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["learning_evaluation_candidates_terminal"] is False
    assert payload["unresolved_learning_evaluation_candidates"] == [
        payload["state"]["learning_evaluation_candidates"][0]
    ]


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


def test_fast_lane_state_never_becomes_delivery_authority(tmp_path: Path) -> None:
    candidates_file = tmp_path / "candidates.json"
    candidates = []
    for issue_number, touched_file in ((4164, "app/a.py"), (4165, "app/b.py")):
        candidates.append(
            {
                "issue_number": issue_number,
                "title": f"independent child {issue_number}",
                "url": f"https://example.test/issues/{issue_number}",
                "state": "OPEN",
                "labels": ["agent:ready", "type:task"],
                "project_status": "Ready",
                "risk": "high",
                "expected_value": "medium",
                "runtime_hint": None,
                "likely_touched_files": [touched_file],
                "validation_resources": [],
                "owner_docs": ["docs/development/BUILDER_SUBAGENT_ROLES.md"],
                "owner_doc_writeback_required": False,
                "dependencies": [],
                "dependencies_satisfied": False,
                "dependencies_known": True,
                "strict_ready": True,
                "authority_ambiguous": False,
                "has_migration": False,
                "contract_surfaces": [],
                "source_anchors": [f"#{issue_number}"],
                "known_constraints": ["run-state remains evidence-only"],
                "validation": ["pytest -q tests/builderops/test_epic_run_state.py"],
                "issue_local_helper_budget": 0,
                "issue_local_helper_rationale": None,
            }
        )
    candidates_file.write_text(json.dumps({"candidates": candidates}), encoding="utf-8")

    result = _run_builderops(
        [
            "epic-run-state",
            "dispatch-plan",
            "--independent-issue",
            "4164",
            "--independent-issue",
            "4165",
            "--run-id",
            "fast-lane-state",
            "--root",
            str(tmp_path),
            "--candidates-file",
            str(candidates_file),
            "--json",
        ]
    )

    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["scope"] == {
        "kind": "independent_issue_set",
        "issue_numbers": [4164, 4165],
        "parent_closure": "prohibited-without-real-governed-parent",
    }
    assert plan["github_mutations"] == []
    assert plan["agent_spawns"] == []
    assert not epic_run_state_path("fast-lane-state", root=tmp_path).exists()


def test_no_unlocked_run_state_writer_in_app() -> None:
    violations: list[str] = []
    for source_path in sorted((REPO_ROOT / "app").rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if function_name == "save_epic_run_state":
                violations.append(
                    f"{source_path.relative_to(REPO_ROOT)}:{node.lineno}:public-save"
                )
                continue
            if function_name != "_save_epic_run_state_to_path":
                continue

            ancestor = parents.get(node)
            inside_run_state_lock = False
            while ancestor is not None:
                if isinstance(ancestor, ast.With):
                    inside_run_state_lock = any(
                        isinstance(item.context_expr, ast.Call)
                        and isinstance(item.context_expr.func, ast.Name)
                        and item.context_expr.func.id == "_locked_run_state"
                        for item in ancestor.items
                    )
                    if inside_run_state_lock:
                        break
                ancestor = parents.get(ancestor)
            if not inside_run_state_lock:
                violations.append(
                    f"{source_path.relative_to(REPO_ROOT)}:{node.lineno}:raw-save"
                )

    assert violations == []


def test_all_app_run_state_update_callers_supply_locked_owner_expectation() -> None:
    defining_module = REPO_ROOT / "app/builderops/epic_run_state.py"
    violations: list[str] = []
    for source_path in sorted((REPO_ROOT / "app").rglob("*.py")):
        if source_path == defining_module:
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if function_name != "update_epic_run_state":
                continue
            keyword_names = {keyword.arg for keyword in node.keywords}
            if not {
                "expected_epic_issue_number",
                "expected_independent_issue_numbers",
            }.intersection(keyword_names):
                violations.append(f"{source_path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert violations == []


def test_run_owner_is_rechecked_inside_the_update_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "owner-recheck"
    create_epic_run_state(
        3229,
        run_id,
        root=tmp_path,
        child_queue=[{"issue_number": 3247, "state": "queued"}],
    )
    monkeypatch.setattr(
        builderops_cli,
        "load_epic_run_state",
        lambda *_args, **_kwargs: new_epic_run_state(3230, run_id),
    )

    result = _run_builderops(
        [
            "epic-run-state",
            "record",
            "--epic-issue-number",
            "3230",
            "--run-id",
            run_id,
            "--root",
            str(tmp_path),
            "--update-json",
            json.dumps(
                {"child_queue": [{"issue_number": 9999, "state": "must-not-write"}]}
            ),
            "--json",
        ]
    )

    assert result.exit_code != 0
    assert "already belongs to epic 3229" in result.output
    persisted = load_epic_run_state(run_id, root=tmp_path)
    assert persisted["epic_issue_number"] == 3229
    assert persisted["child_queue"] == [{"issue_number": 3247, "state": "queued"}]


def _record_run_state(
    *,
    run_id: str,
    issue_numbers: tuple[int, ...],
    root: Path,
    updates: dict[str, object],
) -> None:
    """Invoke the `epic-run-state record` implementation without Click's runner.

    Two concurrent `CliRunner.invoke` calls would race on the globally patched
    stdout, so the concurrency tests drive the command callback directly.
    """

    builderops_cli.record_epic_run_state.callback(
        epic_issue_number=None,
        independent_issues=issue_numbers,
        run_id=run_id,
        root=root,
        update_json=json.dumps(updates),
        update_file=None,
        dry_run=False,
        as_json=True,
    )


def _install_create_race(
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str,
    first_call_started: threading.Event,
    second_call_dispatched: threading.Event,
) -> None:
    """Hold the first independent create open until a second create is in flight.

    The delay is injected into `new_independent_issue_run_state`, which both the
    unlocked and the locked create paths call, so the window between the
    existence check and the write is observable from a second writer.
    """

    original_new = epic_run_state_module.new_independent_issue_run_state
    first_call_seen = threading.Event()

    def delayed_new(
        issue_numbers: list[int], state_run_id: str, **updates: object
    ) -> dict[str, object]:
        state = original_new(issue_numbers, state_run_id, **updates)
        if state_run_id == run_id and not first_call_seen.is_set():
            first_call_seen.set()
            first_call_started.set()
            assert second_call_dispatched.wait(timeout=5)
            time.sleep(0.3)
        return state

    monkeypatch.setattr(
        epic_run_state_module, "new_independent_issue_run_state", delayed_new
    )
    monkeypatch.setattr(
        builderops_cli, "new_independent_issue_run_state", delayed_new
    )


def test_independent_run_state_creation_is_locked_and_rechecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-independent-concurrent"
    issue_numbers = (4164, 4165)
    first_call_started = threading.Event()
    second_call_dispatched = threading.Event()
    _install_create_race(
        monkeypatch,
        run_id=run_id,
        first_call_started=first_call_started,
        second_call_dispatched=second_call_dispatched,
    )

    errors: list[BaseException] = []

    def record(child_issue: int, ready: threading.Event | None = None) -> None:
        if ready is not None:
            ready.set()
        try:
            _record_run_state(
                run_id=run_id,
                issue_numbers=issue_numbers,
                root=tmp_path,
                updates={
                    "child_queue": [
                        {"issue_number": child_issue, "state": "queued"}
                    ]
                },
            )
        except BaseException as exc:  # noqa: BLE001 - reported by the assertions
            errors.append(exc)

    first = threading.Thread(target=record, args=(4164,))
    first.start()
    assert first_call_started.wait(timeout=5)
    second = threading.Thread(target=record, args=(4165, second_call_dispatched))
    second.start()
    first.join(timeout=15)
    second.join(timeout=15)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []

    final_state = load_epic_run_state(run_id, root=tmp_path)
    assert final_state["epic_issue_number"] is None
    assert final_state["independent_issue_numbers"] == [4164, 4165]
    assert sorted(
        entry["issue_number"] for entry in final_state["child_queue"]
    ) == [4164, 4165]


def test_independent_record_rejects_conflicting_run_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-independent-owner"
    first_call_started = threading.Event()
    second_call_dispatched = threading.Event()
    _install_create_race(
        monkeypatch,
        run_id=run_id,
        first_call_started=first_call_started,
        second_call_dispatched=second_call_dispatched,
    )

    results: dict[str, BaseException | None] = {}

    def record(
        name: str,
        issue_numbers: tuple[int, ...],
        child_issue: int,
        ready: threading.Event | None = None,
    ) -> None:
        if ready is not None:
            ready.set()
        try:
            _record_run_state(
                run_id=run_id,
                issue_numbers=issue_numbers,
                root=tmp_path,
                updates={
                    "child_queue": [
                        {"issue_number": child_issue, "state": "queued"}
                    ]
                },
            )
        except BaseException as exc:  # noqa: BLE001 - reported by the assertions
            results[name] = exc
        else:
            results[name] = None

    owner = threading.Thread(target=record, args=("owner", (4164, 4165), 4164))
    owner.start()
    assert first_call_started.wait(timeout=5)
    intruder = threading.Thread(
        target=record, args=("intruder", (4200,), 4200, second_call_dispatched)
    )
    intruder.start()
    owner.join(timeout=15)
    intruder.join(timeout=15)

    assert not owner.is_alive()
    assert not intruder.is_alive()
    assert results["owner"] is None
    intruder_error = results["intruder"]
    assert intruder_error is not None, (
        "a conflicting independent scope must not silently replace the run-state file"
    )
    assert "already belongs to" in str(intruder_error)

    final_state = load_epic_run_state(run_id, root=tmp_path)
    assert final_state["epic_issue_number"] is None
    assert final_state["independent_issue_numbers"] == [4164, 4165]
    assert final_state["child_queue"] == [
        {"issue_number": 4164, "state": "queued"}
    ]

    # The same in-lock owner check must also reject an epic-owned run id.
    create_epic_run_state(3229, "run-epic-owned", root=tmp_path)
    with pytest.raises(EpicRunStateError, match="already belongs to epic 3229"):
        create_independent_issue_run_state([4164], "run-epic-owned", root=tmp_path)


@pytest.mark.skipif(
    epic_run_state_module.fcntl is None,
    reason="cross-process run-state locking requires fcntl",
)
def test_independent_run_state_creation_serializes_across_processes(
    tmp_path: Path,
) -> None:
    """Prove the `fcntl.flock` arm, not just the in-process thread lock.

    `epic-run-state record` runs as separate OS processes, so the real race is
    cross-process. A second process that observes the run-state file as absent
    must block on the file lock and then honour the winner's file.
    """

    run_id = "run-independent-cross-process"
    path = epic_run_state_path(run_id, root=tmp_path)
    lock_path = path.with_name(f".{path.name}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.builderops",
                "builderops",
                "epic-run-state",
                "record",
                "--independent-issue",
                "4200",
                "--run-id",
                run_id,
                "--root",
                str(tmp_path),
                "--json",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            # The lock is held, so the create must not complete or write.
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            assert not path.exists()

            # The winner writes a different independent scope while this test
            # already holds the production lock; the public save wrapper would
            # correctly try to acquire that same non-reentrant lock again.
            path.write_text(
                serialize_epic_run_state(
                    new_independent_issue_run_state([4164, 4165], run_id)
                ),
                encoding="utf-8",
            )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        output, _ = process.communicate(timeout=60)

    assert process.returncode != 0
    assert "already belongs to" in output

    final_state = load_epic_run_state(run_id, root=tmp_path)
    assert final_state["epic_issue_number"] is None
    assert final_state["independent_issue_numbers"] == [4164, 4165]
