from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.ci_handoff_state import (
    build_ci_pending_handoff,
    plan_ci_handoff_resume,
    record_ci_pending_handoff,
)
from app.builderops.epic_run_state import (
    create_epic_run_state,
    load_epic_run_state,
    new_epic_run_state,
)


def _green_checks() -> list[dict[str, str]]:
    return [
        {"name": "Unit tests (not pg)", "status": "completed", "conclusion": "success"},
        {"name": "smoke", "status": "completed", "conclusion": "success"},
    ]


def test_record_ci_pending_handoff(tmp_path: Path) -> None:
    state = new_epic_run_state(3279, "run-ci-handoff")
    handoff = build_ci_pending_handoff(
        issue_number=3273,
        pr_number=3286,
        repo="RasmusTho/agentic-pkm-mvp",
        head_sha="abc123",
        local_validation=[
            "pytest -q tests/builderops/test_ci_handoff_state.py",
            "ruff check app/builderops tests/builderops/test_ci_handoff_state.py",
        ],
        review_state="no-review-comments-read-yet",
        pending_checks=[
            {"name": "Unit tests (not pg)", "status": "in_progress"},
            {"name": "smoke", "status": "queued"},
        ],
        next_closure_action="wait for CI, read review comments, then plan terminal closure",
        recorded_at="2026-07-09T19:45:00Z",
    )

    updated = record_ci_pending_handoff(state, handoff)

    assert updated["ci_handoffs"] == [
        {
            "authority_boundary": (
                "coordination-evidence-only; re-read GitHub PR head and checks before closure"
            ),
            "head_sha": "abc123",
            "id": "ci-handoff-pr-3286",
            "issue_number": 3273,
            "local_validation": [
                "pytest -q tests/builderops/test_ci_handoff_state.py",
                "ruff check app/builderops tests/builderops/test_ci_handoff_state.py",
            ],
            "next_closure_action": (
                "wait for CI, read review comments, then plan terminal closure"
            ),
            "pending_checks": [
                {
                    "conclusion": None,
                    "name": "Unit tests (not pg)",
                    "status": "in_progress",
                },
                {"conclusion": None, "name": "smoke", "status": "queued"},
            ],
            "pr_number": 3286,
            "recorded_at": "2026-07-09T19:45:00Z",
            "repo": "RasmusTho/agentic-pkm-mvp",
            "review_state": "no-review-comments-read-yet",
            "status": "ci_pending",
        }
    ]

    create_epic_run_state(3279, "run-ci-handoff", root=tmp_path, ci_handoffs=[handoff])
    persisted = load_epic_run_state("run-ci-handoff", root=tmp_path)
    assert persisted["ci_handoffs"][0]["pr_number"] == 3286


def test_resume_blocks_on_stale_head_sha() -> None:
    handoff = build_ci_pending_handoff(
        issue_number=3273,
        pr_number=3286,
        head_sha="oldsha",
        local_validation=["pytest -q tests/builderops/test_ci_handoff_state.py"],
        review_state="review-comments-clear",
        next_closure_action="merge after green CI",
    )

    plan = plan_ci_handoff_resume(
        handoff=handoff,
        live_pr={"number": 3286, "headRefOid": "newsha"},
        checks=_green_checks(),
    )

    assert plan["blocked"] is True
    assert "stale-head-sha" in plan["blocked_reasons"]
    assert plan["closure_plan_candidate"] is None
    assert plan["mutations_performed"] is False


def test_resume_plans_closure_after_green_ci_without_merging() -> None:
    handoff = build_ci_pending_handoff(
        issue_number=3273,
        pr_number=3286,
        head_sha="abc123",
        local_validation=["python3 scripts/docs_guard.py"],
        review_state="review-comments-clear",
        next_closure_action="read final PR state and perform explicit merge workflow",
    )

    plan = plan_ci_handoff_resume(
        handoff=handoff,
        live_pr={"number": 3286, "head": {"sha": "abc123"}},
        checks=_green_checks(),
    )

    assert plan["ok"] is True
    assert plan["blocked"] is False
    assert plan["check_verdict"] == "green"
    assert plan["mutations_performed"] is False
    assert plan["closure_plan_candidate"]["proposed_commands"] == []
    assert plan["closure_plan_candidate"]["next_closure_action"] == (
        "read final PR state and perform explicit merge workflow"
    )


def test_resume_deduplicates_stale_failed_rerun_checks() -> None:
    handoff = build_ci_pending_handoff(
        issue_number=3273,
        pr_number=3286,
        head_sha="abc123",
        local_validation=["python3 scripts/docs_guard.py"],
        review_state="review-comments-clear",
        next_closure_action="read final PR state and perform explicit merge workflow",
    )

    plan = plan_ci_handoff_resume(
        handoff=handoff,
        live_pr={"number": 3286, "headRefOid": "abc123"},
        checks=[
            {
                "id": 1,
                "name": "pr-contract",
                "status": "completed",
                "conclusion": "failure",
                "started_at": "2026-07-09T19:00:00Z",
            },
            {
                "id": 2,
                "name": "pr-contract",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-07-09T19:05:00Z",
            },
            {
                "id": 3,
                "name": "Unit tests (not pg)",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-07-09T19:03:00Z",
            },
        ],
    )

    assert plan["ok"] is True
    assert plan["blocked_reasons"] == []
    check_names = [item["name"] for item in plan["closure_plan_candidate"]["checks"]]
    assert check_names == ["pr-contract", "Unit tests (not pg)"]
    assert plan["closure_plan_candidate"]["checks"][0]["conclusion"] == "success"


def test_ci_handoff_cli_record_and_resume_plan(tmp_path: Path) -> None:
    runner = CliRunner()
    pr_file = tmp_path / "pr.json"
    pending_checks = tmp_path / "pending-checks.json"
    green_checks = tmp_path / "green-checks.json"
    pr_file.write_text(
        json.dumps({"number": 3286, "headRefOid": "abc123"}),
        encoding="utf-8",
    )
    pending_checks.write_text(
        json.dumps({"checks": [{"name": "Unit tests (not pg)", "status": "queued"}]}),
        encoding="utf-8",
    )
    green_checks.write_text(json.dumps({"checks": _green_checks()}), encoding="utf-8")

    record = runner.invoke(
        builderops_standalone_root,
        [
            "builderops",
            "epic-run-state",
            "ci-handoff",
            "record",
            "--epic-issue-number",
            "3279",
            "--run-id",
            "run-cli-ci-handoff",
            "--root",
            str(tmp_path),
            "--pr-file",
            str(pr_file),
            "--checks-file",
            str(pending_checks),
            "--issue-number",
            "3273",
            "--validation-command",
            "pytest -q tests/builderops/test_ci_handoff_state.py",
            "--review-state",
            "review-pending",
            "--next-closure-action",
            "resume closure after checks complete",
            "--json",
        ],
        catch_exceptions=False,
    )

    assert record.exit_code == 0, record.output
    record_payload = json.loads(record.output)
    assert record_payload["handoff"]["pending_checks"][0]["name"] == (
        "Unit tests (not pg)"
    )
    assert record_payload["dry_run"] is False

    resume = runner.invoke(
        builderops_standalone_root,
        [
            "builderops",
            "epic-run-state",
            "ci-handoff",
            "resume-plan",
            "--run-id",
            "run-cli-ci-handoff",
            "--root",
            str(tmp_path),
            "--pr-number",
            "3286",
            "--pr-file",
            str(pr_file),
            "--checks-file",
            str(green_checks),
            "--json",
        ],
        catch_exceptions=False,
    )

    assert resume.exit_code == 0, resume.output
    resume_payload = json.loads(resume.output)
    assert resume_payload["ok"] is True
    assert resume_payload["mutations_performed"] is False
