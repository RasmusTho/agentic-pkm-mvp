from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.ready_repair_batch import build_ready_repair_batch


REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_BODY = (REPO_ROOT / "tests/fixtures/issue_readiness/valid_ready_candidate.md").read_text(
    encoding="utf-8"
)
INVALID_BODY = (
    REPO_ROOT / "tests/fixtures/issue_readiness/ac_without_verify.md"
).read_text(encoding="utf-8")


def _issue(
    number: int,
    *,
    body: str = VALID_BODY,
    labels: list[str] | None = None,
    project_status: str = "Backlog",
) -> dict[str, object]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": body,
        "state": "OPEN",
        "labels": labels if labels is not None else ["type:task"],
        "project_status": project_status,
    }


def test_batch_reports_ready_and_blocked_children(tmp_path: Path) -> None:
    children_file = tmp_path / "children.json"
    children_file.write_text(
        json.dumps({
            "issues": [
                _issue(3271),
                _issue(3272, body=INVALID_BODY, labels=["type:task", "agent:ready"]),
            ]
        }),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "ready-repair-batch",
            "plan",
            "--children-file",
            str(children_file),
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["summary"]["ready_candidate_count"] == 1
    assert payload["summary"]["blocked_count"] == 1
    ready = payload["issues"][0]
    blocked = payload["issues"][1]
    assert ready["status"] == "ready_candidate"
    assert [item["name"] for item in ready["proposed_commands"]] == [
        "add_agent_ready_label",
        "set_project_ready",
    ]
    assert blocked["status"] == "blocked"
    assert blocked["proposed_commands"] == []


def test_batch_blocks_non_ready_candidate_without_writes() -> None:
    report = build_ready_repair_batch(
        issues=[
            _issue(
                3272,
                body=INVALID_BODY,
                labels=["type:task", "agent:ready"],
                project_status="Backlog",
            )
        ],
        repo="RasmusTho/agentic-pkm-mvp",
    )

    issue_report = report["issues"][0]
    assert issue_report["status"] == "blocked"
    assert "readiness-missing_verify_markers" in issue_report["blocked_reasons"]
    assert issue_report["proposed_commands"] == []
    assert report["summary"]["planned_command_count"] == 0
    assert report["mutations_performed"] is False


def test_batch_keeps_empty_body_child_as_blocked_report_item() -> None:
    report = build_ready_repair_batch(
        issues=[
            _issue(3271),
            _issue(3272, body="", labels=["type:task"]),
        ],
        repo="RasmusTho/agentic-pkm-mvp",
    )

    assert report["summary"]["issue_count"] == 2
    assert report["summary"]["ready_candidate_count"] == 1
    assert report["summary"]["blocked_count"] == 1
    blocked = report["issues"][1]
    assert blocked["status"] == "blocked"
    assert "readiness-unknown" in blocked["blocked_reasons"]
    assert blocked["proposed_commands"] == []


def test_apply_mode_only_executes_validator_gated_repairs() -> None:
    executed: list[list[str]] = []

    def runner(argv: list[str]) -> dict[str, object]:
        executed.append(list(argv))
        return {"returncode": 0, "ok": True, "stdout": "", "stderr": ""}

    report = build_ready_repair_batch(
        issues=[
            _issue(3271),
            _issue(3272, body=INVALID_BODY, labels=["type:task", "agent:ready"]),
        ],
        repo="RasmusTho/agentic-pkm-mvp",
        apply=True,
        command_runner=runner,
    )

    assert report["apply"] is True
    assert report["dry_run"] is False
    assert report["summary"]["ready_candidate_count"] == 1
    assert report["summary"]["blocked_count"] == 1
    assert report["summary"]["executed_command_count"] == 2
    assert report["summary"]["failed_command_count"] == 0
    assert [command[0:3] for command in executed] == [
        ["gh", "issue", "edit"],
        ["python3", "scripts/reconcile_project_status.py", "--repo"],
    ]
    assert {item["issue_number"] for item in report["command_results"]} == {3271}


def test_apply_mode_stops_issue_repairs_after_failed_command() -> None:
    executed: list[list[str]] = []

    def runner(argv: list[str]) -> dict[str, object]:
        executed.append(list(argv))
        return {
            "returncode": 1,
            "ok": False,
            "stdout": "",
            "stderr": "rate limited",
        }

    report = build_ready_repair_batch(
        issues=[_issue(3271)],
        repo="RasmusTho/agentic-pkm-mvp",
        apply=True,
        command_runner=runner,
    )

    assert report["summary"]["executed_command_count"] == 1
    assert report["summary"]["failed_command_count"] == 1
    assert [item["name"] for item in report["command_results"]] == ["add_agent_ready_label"]
    assert executed == [
        [
            "gh",
            "issue",
            "edit",
            "3271",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--add-label",
            "agent:ready",
        ]
    ]
