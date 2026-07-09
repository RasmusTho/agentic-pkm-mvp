from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.epic_lifecycle_plan import build_lifecycle_transition_plan


def _issue(
    *,
    state: str = "OPEN",
    labels: list[str] | None = None,
    project_status: str | None = "Ready",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": 3257,
        "state": state,
        "labels": labels if labels is not None else ["agent:ready", "type:task"],
        "assignees": [],
    }
    if project_status is not None:
        payload["project_status"] = project_status
    return payload


def _pr(
    *,
    state: str = "OPEN",
    is_draft: bool = False,
    merged: bool = False,
    project_status: str | None = "In Progress",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "number": 101,
        "state": state,
        "isDraft": is_draft,
        "merged": merged,
    }
    if project_status is not None:
        payload["project_status"] = project_status
    return payload


def _run_builderops(args: list[str]):
    return CliRunner().invoke(
        builderops_standalone_root,
        ["builderops", *args],
        catch_exceptions=False,
    )


def test_claim_plan_separates_required_reads_and_projection_writes() -> None:
    plan = build_lifecycle_transition_plan(
        transition="claim",
        issue=_issue(),
        actor="RasmusTho",
        repo="RasmusTho/agentic-pkm-mvp",
    )

    assert plan["dry_run"] is True
    assert plan["required_reads"][0]["name"] == "read_issue_claim_state"
    assert plan["verification_reads"][0]["name"] == "verify_issue_claim_projection"
    assert [item["action"] for item in plan["proposed_writes"]["issue_labels"]] == [
        "remove_label",
        "assign",
    ]
    assert plan["proposed_writes"]["issue_project_status"][0]["value"] == "In Progress"
    assert plan["github_mutations"] == []
    assert plan["project_mutations"] == []
    assert plan["dispatcher_mutations"] == []
    assert plan["agent_spawns"] == []
    assert plan["summary"]["no_mutations_performed"] is True


def test_review_handoff_plans_issue_and_pr_project_review_only() -> None:
    plan = build_lifecycle_transition_plan(
        transition="review-handoff",
        issue=_issue(labels=["type:task"], project_status="In Progress"),
        pull_request=_pr(project_status="In Progress"),
        repo="RasmusTho/agentic-pkm-mvp",
    )

    assert plan["blocked_reasons"] == []
    assert plan["proposed_writes"]["issue_project_status"][0]["value"] == "Review"
    assert plan["proposed_writes"]["pr_project_status"][0]["target"] == "pr:101"
    assert plan["proposed_writes"]["pr_project_status"][0]["value"] == "Review"
    assert plan["proposed_writes"]["pr_state"] == []
    assert {item["name"] for item in plan["verification_reads"]} == {
        "verify_issue_review_projection",
        "verify_pr_review_projection",
    }


def test_done_plan_uses_github_terminal_truth_over_stale_project_status() -> None:
    plan = build_lifecycle_transition_plan(
        transition="done",
        issue=_issue(
            state="CLOSED",
            labels=["agent:blocked", "lane:governance"],
            project_status="Ready",
        ),
        pull_request=_pr(state="CLOSED", merged=True, project_status="Review"),
        checks=[{"name": "unit", "status": "completed", "conclusion": "success"}],
        repo="RasmusTho/agentic-pkm-mvp",
    )

    assert plan["blocked_reasons"] == []
    assert plan["proposed_writes"]["issue_labels"][0]["value"] == "agent:blocked"
    assert plan["proposed_writes"]["issue_project_status"][0]["value"] == "Done"
    assert plan["proposed_writes"]["pr_project_status"][0]["value"] == "Done"
    assert "github_project_projection" in plan["authority_order"]
    assert plan["authority_order"].index("github_pr_state") < plan["authority_order"].index(
        "github_project_projection"
    )


def test_done_plan_does_not_project_open_issue_done_from_pr_alone() -> None:
    plan = build_lifecycle_transition_plan(
        transition="terminal",
        issue=_issue(labels=["type:task"], project_status="In Progress"),
        pull_request=_pr(state="CLOSED", merged=True, project_status="Review"),
        checks=[{"name": "unit", "status": "completed", "conclusion": "success"}],
        repo="RasmusTho/agentic-pkm-mvp",
    )

    assert "issue-not-closed" in plan["blocked_reasons"]
    assert plan["proposed_writes"]["issue_project_status"] == []
    assert plan["proposed_writes"]["pr_project_status"][0]["value"] == "Done"


def test_done_plan_blocks_terminal_projection_when_ci_is_not_green() -> None:
    plan = build_lifecycle_transition_plan(
        transition="done",
        issue=_issue(state="CLOSED", labels=["type:task"], project_status="Review"),
        pull_request=_pr(state="CLOSED", merged=True, project_status="Review"),
        checks=[{"name": "unit", "status": "completed", "conclusion": "failure"}],
        repo="RasmusTho/agentic-pkm-mvp",
    )

    assert "ci-checks-not-green" in plan["blocked_reasons"]
    assert plan["proposed_writes"]["issue_project_status"] == []
    assert plan["proposed_writes"]["pr_project_status"] == []


def test_cli_lifecycle_plan_is_dry_run_and_does_not_write_run_state(tmp_path: Path) -> None:
    issue_file = tmp_path / "issue.json"
    pr_file = tmp_path / "pr.json"
    checks_file = tmp_path / "checks.json"
    issue_file.write_text(json.dumps({"issue": _issue()}), encoding="utf-8")
    pr_file.write_text(json.dumps({"pull_request": _pr()}), encoding="utf-8")
    checks_file.write_text(json.dumps({"checks": []}), encoding="utf-8")

    result = _run_builderops(
        [
            "epic-run-state",
            "lifecycle-plan",
            "--transition",
            "claim",
            "--issue-file",
            str(issue_file),
            "--pr-file",
            str(pr_file),
            "--checks-file",
            str(checks_file),
            "--actor",
            "RasmusTho",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--json",
        ]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["transition"] == "claim"
    assert payload["summary"]["no_mutations_performed"] is True
    assert not (tmp_path / "run-cli-lifecycle.json").exists()
