from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts import project_status
from scripts import reconcile_project_status
from scripts.reconcile_project_status import (
    ProjectItemListDeferred,
    desired_issue_status,
    desired_pr_status,
    get_pr,
    list_project_items,
    load_governance_project_name,
    reconcile_issue,
    reconcile_migration,
    reconcile_pr,
)

FIXTURE_DIR = Path("tests/fixtures/issue_readiness")
VALID_READY_BODY = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
INVALID_READY_BODY = (FIXTURE_DIR / "missing_constraints.md").read_text(encoding="utf-8")


def test_desired_pr_status_open_non_draft_pr_is_review() -> None:
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": False, "mergedAt": None}, None) == "Review"
    )


def test_open_non_draft_pr_without_review_request_matches_documented_status() -> None:
    matrix = Path(".codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md").read_text(encoding="utf-8")
    setup = Path("docs/development/GITHUB_GOVERNANCE_SETUP.md").read_text(encoding="utf-8")

    assert "| PR | OPEN + non-draft, no review requested | `Review` |" in matrix
    assert (
        "- `In Progress`: active implementation Issue state; on PR items this covers open draft PRs"
        in setup
    )
    assert (
        "- `Review`: the Project state for open non-draft PRs, whether or not review was explicitly requested"
        in setup
    )
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": False, "mergedAt": None}, None) == "Review"
    )
    assert project_status.desired_status("opened", False) == "Review"


def test_desired_pr_status_open_draft_pr_is_in_progress() -> None:
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": True, "mergedAt": None}, None)
        == "In Progress"
    )


def test_desired_pr_status_closed_unmerged_pr_is_done() -> None:
    assert desired_pr_status({"state": "CLOSED", "mergedAt": None}, None) == "Done"


def test_desired_pr_status_explicit_status_applies_to_open_pr() -> None:
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": True, "mergedAt": None}, "Review")
        == "Review"
    )


def test_desired_pr_status_terminal_truth_precedes_explicit_status() -> None:
    assert desired_pr_status({"state": "CLOSED", "mergedAt": None}, "Review") == "Done"
    assert (
        desired_pr_status({"state": "CLOSED", "mergedAt": "2026-08-29T16:00:00Z"}, "Review")
        == "Done"
    )


def test_desired_status_closed_action_projects_done() -> None:
    # A `closed` pull_request event is terminal for both merged and
    # unmerged-closed PRs; the card must reach Done regardless of draft state.
    assert project_status.desired_status("closed", None) == "Done"
    assert project_status.desired_status("closed", True) == "Done"
    assert project_status.desired_status("closed", False) == "Done"


def test_desired_issue_status_requires_ready_candidate_body() -> None:
    valid_issue = {
        "number": 3212,
        "state": "OPEN",
        "labels": [{"name": "agent:ready"}],
        "body": VALID_READY_BODY,
    }
    invalid_issue = {
        "number": 3213,
        "state": "OPEN",
        "labels": [{"name": "agent:ready"}],
        "body": INVALID_READY_BODY,
    }

    assert desired_issue_status(valid_issue) == "Ready"
    assert desired_issue_status(invalid_issue) == "Backlog"


def test_desired_issue_status_splits_non_active_backlog_lanes() -> None:
    assert (
        desired_issue_status({"state": "OPEN", "labels": [{"name": "agent:needs-human"}]})
        == "Needs Human"
    )
    assert (
        desired_issue_status({"state": "OPEN", "labels": [{"name": "agent:blocked"}]}) == "Blocked"
    )
    assert (
        desired_issue_status({"state": "OPEN", "labels": [{"name": "agent:in-progress"}]})
        == "In Progress"
    )
    assert desired_issue_status({"state": "OPEN", "labels": []}) is None


def test_successful_pickup_label_transition_projects_in_progress() -> None:
    assert (
        desired_issue_status({"state": "OPEN", "labels": [{"name": "agent:in-progress"}]})
        == "In Progress"
    )


def test_desired_issue_status_projects_known_defect_registry_to_backlog() -> None:
    issue = {"state": "OPEN", "labels": [{"name": "state:known-defect"}]}

    assert desired_issue_status(issue) == "Backlog"
    assert desired_issue_status(issue, "Review") == "Review"


def test_scan_projects_known_defect_registry_to_backlog(monkeypatch, tmp_path) -> None:
    watermark_path = tmp_path / "project_status_reconcile_scan_watermark.json"
    monkeypatch.setattr(reconcile_project_status, "SCAN_WATERMARK_PATH", watermark_path)
    monkeypatch.setattr(
        reconcile_project_status,
        "list_project_items_for_scan",
        lambda *_args: [
            {
                "id": "known-defect-item",
                "content": {
                    "type": "Issue",
                    "number": 4172,
                    "updatedAt": "2026-08-29T15:00:00Z",
                },
                "status": "Needs Human",
            }
        ],
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda *_args: {
            "number": 4172,
            "state": "OPEN",
            "labels": [{"name": "state:known-defect"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4172",
            "body": "",
        },
    )
    status_calls = []
    monkeypatch.setattr(
        reconcile_project_status, "set_project_status", lambda *args: status_calls.append(args)
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "_scan_started_at",
        lambda: datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc),
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp", dry_run=False, status=None
    )
    project = {"id": "project-1", "number": 1, "title": "Agent Delivery Control Plane"}

    assert (
        reconcile_project_status.reconcile_scan(
            args, "RasmusTho", project, "field-id", {"Backlog": "backlog-id"}
        )
        == 0
    )
    assert status_calls == [
        ("RasmusTho", "project-1", "known-defect-item", "field-id", "backlog-id", False)
    ]


def test_epic_parent_projection_precedes_blocker_projection() -> None:
    assert (
        desired_issue_status(
            {"state": "OPEN", "labels": [{"name": "type:epic"}, {"name": "agent:blocked"}]}
        )
        == "Epic / Parent"
    )
    assert (
        desired_issue_status(
            {
                "state": "OPEN",
                "labels": [{"name": "agent:needs-human"}],
                "subIssues": {"totalCount": 1},
            }
        )
        == "Epic / Parent"
    )


def test_desired_issue_status_preserves_explicit_review_override() -> None:
    issue = {"state": "OPEN", "labels": [{"name": "agent:blocked"}]}
    assert desired_issue_status(issue, "Review") == "Review"
    assert desired_issue_status({**issue, "state": "CLOSED"}, "Review") == "Done"


def test_reconcile_issue_terminal_truth_precedes_explicit_status(monkeypatch) -> None:
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda *_args: {
            "number": 1,
            "state": "CLOSED",
            "labels": [{"name": "agent:ready"}],
            "url": "https://example.test/1",
            "body": "",
        },
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "list_project_items",
        lambda *_args: [
            {"id": "issue-1", "content": {"type": "Issue", "number": 1}, "status": "Review"}
        ],
    )
    calls = []
    monkeypatch.setattr(
        reconcile_project_status, "set_project_status", lambda *args: calls.append(args)
    )
    args = reconcile_project_status.argparse.Namespace(
        repo="owner/repo", issue=1, status="Ready", dry_run=False
    )

    assert (
        reconcile_project_status.reconcile_issue(
            args, "owner", {"id": "project", "number": 1, "title": "P"}, "field", {"Done": "done"}
        )
        == 0
    )
    assert calls == [("owner", "project", "issue-1", "field", "done", False)]


def test_get_issue_fetches_parent_projection_evidence(monkeypatch) -> None:
    commands = []

    def fake_run_gh(*args: str, **kwargs: bool) -> str:
        commands.append((args, kwargs))
        return reconcile_project_status.json.dumps(
            {
                "data": {
                    "repository": {
                        "issue": {
                            "number": 5177,
                            "labels": {"nodes": [{"name": "type:epic"}]},
                            "subIssues": {"totalCount": 1},
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    assert (
        reconcile_project_status.get_issue("RasmusTho/agentic-pkm-mvp", 5177)["subIssues"][
            "totalCount"
        ]
        == 1
    )
    assert commands == [
        (
            (
                "api",
                "graphql",
                "-f",
                "owner=RasmusTho",
                "-f",
                "name=agentic-pkm-mvp",
                "-F",
                "number=5177",
                "-f",
                f"query={reconcile_project_status.ISSUE_WITH_PARENT_EVIDENCE_QUERY}",
            ),
            {"use_repo_token": True},
        )
    ]


def test_reconcile_cli_accepts_split_backlog_statuses() -> None:
    assert set(reconcile_project_status.PROJECT_STATUS_VALUES) == {
        "Backlog",
        "Epic / Parent",
        "Blocked",
        "Needs Human",
        "Ready",
        "In Progress",
        "Review",
        "Done",
    }


def test_canonical_maintenance_surfaces_document_split_lane_precedence() -> None:
    maintenance_skill = Path(".codex/skills/issue-maintenance-change-control/SKILL.md").read_text(
        encoding="utf-8"
    )
    label_taxonomy = Path(".codex/skills/_shared/LABEL_TAXONOMY.md").read_text(encoding="utf-8")

    for content in (maintenance_skill, label_taxonomy):
        assert "Epic / Parent" in content
        assert "Needs Human" in content
        assert "Blocked" in content
        assert "explicit open-Issue `Review`" in content
    assert maintenance_skill.count("--remove-label agent:in-progress") >= 8
    issue_to_code = Path(".codex/skills/issue-to-code/SKILL.md").read_text(encoding="utf-8")
    assert (
        "--add-label agent:blocked --remove-label agent:ready --remove-label agent:needs-human --remove-label agent:in-progress"
        in issue_to_code
    )


def test_canonical_label_taxonomy_declares_projection_inputs() -> None:
    governance = yaml.safe_load(Path(".github/github-governance.yml").read_text(encoding="utf-8"))
    taxonomy = Path(".codex/skills/_shared/LABEL_TAXONOMY.md").read_text(encoding="utf-8")

    assert {"type:epic", "type:feature"} <= set(governance["labels"]["type"])
    assert "agent:in-progress" in governance["labels"]["agent"]
    for label in ("type:epic", "type:feature", "agent:in-progress"):
        assert f"| `{label}`" in taxonomy


def test_pr_stage_change_workflow_subscribes_to_closed_event() -> None:
    # Merge/close must be event-driven so terminal projection does not depend on
    # the best-effort hourly reconcile scan.
    workflow = Path(".github/workflows/project-pr-stage-change.yml").read_text(encoding="utf-8")
    assert "closed" in workflow, "stage-change workflow must subscribe to closed PRs"


def test_get_pr_fetches_draft_state(monkeypatch) -> None:
    commands = []

    def fake_run_gh(*args: str) -> str:
        commands.append(args)
        return reconcile_project_status.json.dumps(
            {
                "number": 1484,
                "state": "OPEN",
                "isDraft": False,
                "mergedAt": None,
                "url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/1484",
                "title": "Example PR",
            }
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    assert get_pr("RasmusTho/agentic-pkm-mvp", 1484)["isDraft"] is False
    assert commands == [
        (
            "pr",
            "view",
            "1484",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--json",
            "number,state,isDraft,mergedAt,url,title",
        )
    ]


def test_load_governance_project_name_reads_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    governance_dir = Path(".github")
    governance_dir.mkdir(parents=True)
    governance_file = governance_dir / "github-governance.yml"
    governance_file.write_text("project:\n  name: Custom Project\n", encoding="utf-8")
    assert load_governance_project_name() == "Custom Project"


def test_load_governance_project_name_falls_back_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOVERNANCE_PROJECT_NAME", raising=False)
    assert load_governance_project_name() == "Agent Delivery Control Plane"


def test_load_governance_project_name_uses_env_override_when_file_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOVERNANCE_PROJECT_NAME", "Override Project")
    assert load_governance_project_name() == "Override Project"


def test_list_project_items_fetches_beyond_initial_limit(monkeypatch) -> None:
    commands = []
    first_page_items = [
        {"id": f"item-{index}", "content": {"type": "Issue", "number": index}}
        for index in range(200)
    ]

    def fake_run_gh(*args: str) -> str:
        commands.append(args)
        return reconcile_project_status.json.dumps({"items": first_page_items, "totalCount": 201})

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    with pytest.raises(ProjectItemListDeferred):
        list_project_items("RasmusTho", 1)
    assert [command[command.index("--limit") + 1] for command in commands] == ["200"]


def test_reconcile_issue_does_not_add_item_found_after_initial_limit(monkeypatch, capsys) -> None:
    first_page_items = [
        {"id": f"item-{index}", "content": {"type": "Issue", "number": index}}
        for index in range(200)
    ]
    full_items = [
        *first_page_items,
        {
            "id": "item-495",
            "content": {"type": "Issue", "number": 495},
            "status": "Ready",
        },
    ]
    add_calls = []

    def fake_run_gh(*args: str) -> str:
        if args[:3] == ("project", "item-list", "1"):
            limit = args[args.index("--limit") + 1]
            if limit == "200":
                return reconcile_project_status.json.dumps(
                    {"items": first_page_items, "totalCount": 201}
                )
            if limit == "201":
                return reconcile_project_status.json.dumps({"items": full_items, "totalCount": 201})
        raise AssertionError(f"unexpected gh command: {args}")

    def fail_add_item_to_project(*_args) -> None:
        add_calls.append(_args)
        raise AssertionError("should not add an existing project item")

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 495,
            "state": "OPEN",
            "labels": [{"name": "agent:ready"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/495",
            "body": VALID_READY_BODY,
        },
    )
    monkeypatch.setattr(reconcile_project_status, "add_item_to_project", fail_add_item_to_project)

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        issue=495,
        dry_run=False,
        status=None,
    )

    assert reconcile_issue(args, "RasmusTho", {"number": 1}, "field", {"Ready": "opt"}) == 0
    assert add_calls == []
    assert (
        "skip issue #495: project item-list returned a partial board snapshot"
        in capsys.readouterr().out
    )


def test_reconcile_pr_does_not_add_item_found_after_initial_limit(monkeypatch, capsys) -> None:
    first_page_items = [
        {
            "id": f"item-{index}",
            "content": {"type": "PullRequest", "number": index},
        }
        for index in range(200)
    ]
    full_items = [
        *first_page_items,
        {
            "id": "item-501",
            "content": {"type": "PullRequest", "number": 501},
            "status": "Review",
        },
    ]
    add_calls = []

    def fake_run_gh(*args: str) -> str:
        if args[:3] == ("project", "item-list", "1"):
            limit = args[args.index("--limit") + 1]
            if limit == "200":
                return reconcile_project_status.json.dumps(
                    {"items": first_page_items, "totalCount": 201}
                )
            if limit == "201":
                return reconcile_project_status.json.dumps({"items": full_items, "totalCount": 201})
        raise AssertionError(f"unexpected gh command: {args}")

    def fail_add_item_to_project(*_args) -> None:
        add_calls.append(_args)
        raise AssertionError("should not add an existing project item")

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)
    monkeypatch.setattr(
        reconcile_project_status,
        "get_pr",
        lambda _repo, _number: {
            "number": 501,
            "state": "OPEN",
            "isDraft": False,
            "mergedAt": None,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/501",
        },
    )
    monkeypatch.setattr(reconcile_project_status, "add_item_to_project", fail_add_item_to_project)

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        pr=501,
        dry_run=False,
        status=None,
    )

    assert reconcile_pr(args, "RasmusTho", {"number": 1}, "field", {"Review": "opt"}) == 0
    assert add_calls == []
    assert (
        "skip pr #501: project item-list returned a partial board snapshot"
        in capsys.readouterr().out
    )


def test_reconcile_issue_stops_when_project_listing_fails_before_mutation(
    monkeypatch,
) -> None:
    add_calls = []

    def fake_run_gh(*args: str) -> str:
        if args[:3] == ("project", "item-list", "1"):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["gh", *args],
                stderr="GraphQL: API rate limit exceeded",
            )
        raise AssertionError(f"unexpected gh command: {args}")

    def fail_add_item_to_project(*_args) -> None:
        add_calls.append(_args)
        raise AssertionError("should not mutate project after list failure")

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 495,
            "state": "OPEN",
            "labels": [{"name": "agent:ready"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/495",
            "body": VALID_READY_BODY,
        },
    )
    monkeypatch.setattr(reconcile_project_status, "add_item_to_project", fail_add_item_to_project)

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        issue=495,
        dry_run=False,
        status=None,
    )

    with pytest.raises(subprocess.CalledProcessError):
        reconcile_issue(args, "RasmusTho", {"number": 1}, "field", {"Ready": "opt"})
    assert add_calls == []


def test_reconcile_issue_refuses_ready_for_invalid_agent_ready_body(
    monkeypatch,
    capsys,
) -> None:
    status_calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 495,
            "state": "OPEN",
            "labels": [{"name": "agent:ready"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/495",
            "body": INVALID_READY_BODY,
        },
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "list_project_items",
        lambda *_args: [
            {
                "id": "item-invalid",
                "content": {"type": "Issue", "number": 495},
                "status": "Ready",
            }
        ],
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "set_project_status",
        lambda *args: status_calls.append(args),
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        issue=495,
        dry_run=False,
        status=None,
    )

    assert (
        reconcile_issue(
            args,
            "RasmusTho",
            {"id": "project-1", "number": 1, "title": "Agent Delivery Control Plane"},
            "field",
            {"Backlog": "backlog-id", "Ready": "ready-id"},
        )
        == 1
    )
    assert status_calls == [
        ("RasmusTho", "project-1", "item-invalid", "field", "backlog-id", False)
    ]
    output = capsys.readouterr().out
    assert "invalid issue #495" in output
    assert "missing_required_sections" in output


def test_reconcile_pr_soft_fails_on_transient_project_add_failure(monkeypatch, capsys) -> None:
    add_calls = []
    edit_calls = []

    def fake_run_gh(*args: str) -> str:
        if args[:3] == ("project", "item-list", "1"):
            return reconcile_project_status.json.dumps({"items": [], "totalCount": 0})
        if args and args[0] == "project":
            edit_calls.append(args)
            return ""
        raise AssertionError(f"unexpected gh command: {args}")

    def transient_add_failure(*_args) -> None:
        add_calls.append(_args)
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["gh", "project", "item-add"],
            stderr="GraphQL: API rate limit exceeded",
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)
    monkeypatch.setattr(
        reconcile_project_status,
        "add_item_to_project",
        transient_add_failure,
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "get_pr",
        lambda _repo, _number: {
            "number": 2140,
            "state": "OPEN",
            "isDraft": False,
            "mergedAt": None,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/2140",
        },
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 2144,
            "state": "OPEN",
            "labels": [{"name": "agent:ready"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/2144",
            "body": VALID_READY_BODY,
        },
    )

    pr_args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        pr=2140,
        dry_run=False,
        status=None,
    )
    issue_args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        issue=2144,
        dry_run=False,
        status=None,
    )

    assert (
        reconcile_pr(
            pr_args,
            "RasmusTho",
            {"number": 1, "title": "Agent Delivery Control Plane"},
            "field",
            {"Review": "opt"},
        )
        == 0
    )
    assert (
        reconcile_issue(
            issue_args,
            "RasmusTho",
            {"number": 1, "title": "Agent Delivery Control Plane"},
            "field",
            {"Ready": "opt"},
        )
        == 0
    )
    assert len(add_calls) == 2
    assert edit_calls == []
    output = capsys.readouterr().out
    assert 'soft-fail pr #2140: failed to add to project "Agent Delivery Control Plane"' in output
    assert (
        'soft-fail issue #2144: failed to add to project "Agent Delivery Control Plane"' in output
    )


# --- GraphQL-budget incident remediation (GHAPI-C2 / GHAPI-H2 / GHAPI-H3) ---


def test_scan_is_daily_and_rate_limit_gated(monkeypatch, capsys) -> None:
    # The hourly full-board scan was the dominant GraphQL drain; cron must be daily.
    workflow = Path(".github/workflows/project-status-reconcile.yml").read_text(encoding="utf-8")
    assert "cron: '17 * * * *'" not in workflow, "hourly project scan must be removed"
    assert "cron: '17 7 * * *'" in workflow, "scan cron must be daily"

    # And a low GraphQL budget must skip the scan BEFORE project discovery,
    # which itself spends `gh project` GraphQL calls.
    def fail_discover(*_args, **_kwargs):
        raise AssertionError("must not discover the project when GraphQL budget is low")

    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 100)
    monkeypatch.setattr(reconcile_project_status, "discover_project", fail_discover)
    monkeypatch.setattr(sys, "argv", ["reconcile", "--repo", "RasmusTho/agentic-pkm-mvp", "--scan"])
    assert reconcile_project_status.main() == 0
    out = capsys.readouterr().out
    assert "skip project scan: GraphQL budget low" in out
    assert "before project discovery" in out


def test_scheduled_scan_restores_watermark_cache() -> None:
    workflow = Path(".github/workflows/project-status-reconcile.yml").read_text(encoding="utf-8")

    assert "uses: actions/cache@v4" in workflow
    assert "path: runtime/dispatcher/project_status_reconcile_scan_watermark.json" in workflow
    assert "key: project-status-reconcile-scan-watermark-${{ github.run_id }}" in workflow
    assert "project-status-reconcile-scan-watermark-" in workflow


def test_manual_dispatch_scan_bypasses_watermark_cache() -> None:
    # workflow_dispatch is the documented manual full-scan escape hatch for a
    # GraphQL-budget incident (see the schedule comment). Restoring the
    # watermark cache on dispatch too would make that path skip the same
    # stale items an operator is dispatching to repair.
    workflow_data = yaml.safe_load(
        Path(".github/workflows/project-status-reconcile.yml").read_text(encoding="utf-8")
    )
    steps = workflow_data["jobs"]["reconcile-scan"]["steps"]
    cache_step = next(s for s in steps if s.get("uses", "").startswith("actions/cache"))
    assert cache_step.get("if") == "github.event_name == 'schedule'", (
        "watermark cache restore must be scheduled-run-only so workflow_dispatch "
        f"performs a full scan; got if={cache_step.get('if')!r}"
    )


def test_project_board_workflows_share_serial_concurrency_group() -> None:
    # All board reconcile/mutation workflows must serialize through one shared
    # concurrency group so they cannot stampede the GraphQL pool concurrently.
    for path in (
        ".github/workflows/project-status-reconcile.yml",
        ".github/workflows/project-pr-opened.yml",
        ".github/workflows/project-pr-stage-change.yml",
    ):
        content = Path(path).read_text(encoding="utf-8")
        assert (
            "group: github-project-board-reconcile" in content
        ), f"{path} must join the shared board concurrency group"
        assert (
            "cancel-in-progress: false" in content
        ), f"{path} must queue board updates, not cancel them"
        assert (
            "queue: max" in content
        ), f"{path} must keep pending board runs (queue: max); default queue: single drops them"


def test_main_reaches_discovery_when_budget_healthy(monkeypatch) -> None:
    # With healthy budget, main() proceeds to project discovery (which then
    # short-circuits via the unavailable path here).
    reached = {"discover": False}

    def fake_discover(_owner, _name):
        reached["discover"] = True
        raise RuntimeError("stop after discovery")

    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 5000)
    monkeypatch.setattr(reconcile_project_status, "discover_project", fake_discover)
    monkeypatch.setattr(sys, "argv", ["reconcile", "--repo", "RasmusTho/agentic-pkm-mvp", "--scan"])
    assert reconcile_project_status.main() == 0
    assert reached["discover"] is True


def test_main_skips_event_before_discovery_when_budget_low(monkeypatch, capsys) -> None:
    # Codex review fix: the budget guard must run BEFORE discover_project /
    # get_status_field, or a burst of low-budget events still spends GraphQL on
    # discovery before skipping.
    def fail_discover(*_args, **_kwargs):
        raise AssertionError("must not discover the project when GraphQL budget is low")

    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 100)
    monkeypatch.setattr(reconcile_project_status, "discover_project", fail_discover)
    monkeypatch.setattr(
        sys, "argv", ["reconcile", "--repo", "RasmusTho/agentic-pkm-mvp", "--issue", "495"]
    )
    assert reconcile_project_status.main() == 0
    out = capsys.readouterr().out
    assert "skip issue #495: GraphQL budget low" in out
    assert "before project discovery" in out


def test_scan_item_list_fetches_updated_at_from_graphql(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run_gh(*args: str) -> str:
        commands.append(args)
        if args[:2] == ("api", "users/RasmusTho"):
            return '{"type":"User"}'
        return reconcile_project_status.json.dumps(
            {
                "data": {
                    "user": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [
                                    {
                                        "id": "item-1",
                                        "content": {
                                            "__typename": "Issue",
                                            "number": 101,
                                            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/101",
                                            "updatedAt": "2026-06-30T12:00:00Z",
                                        },
                                        "fieldValues": {
                                            "nodes": [
                                                {
                                                    "name": "Ready",
                                                    "field": {"name": "Status"},
                                                }
                                            ]
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    assert reconcile_project_status.list_project_items_for_scan("RasmusTho", 1) == [
        {
            "id": "item-1",
            "content": {
                "type": "Issue",
                "number": 101,
                "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/101",
                "updatedAt": "2026-06-30T12:00:00Z",
            },
            "status": "Ready",
        }
    ]
    assert commands[0][:2] == ("api", "users/RasmusTho")
    assert commands[1][:2] == ("api", "graphql")
    assert "user(login: $owner)" in commands[1][3]


def test_scan_item_list_reads_organization_project(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run_gh(*args: str) -> str:
        commands.append(args)
        if args[:2] == ("api", "users/Yggdrasil-PKM"):
            return '{"type":"Organization"}'
        return reconcile_project_status.json.dumps(
            {
                "data": {
                    "organization": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [],
                            }
                        }
                    },
                    "user": None,
                }
            }
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    assert reconcile_project_status.list_project_items_for_scan("Yggdrasil-PKM", 1) == []
    assert commands[0][:2] == ("api", "users/Yggdrasil-PKM")
    assert "organization(login: $owner)" in commands[1][3]
    assert "user(login: $owner)" not in commands[1][3]
    assert len(commands) == 2


def test_migration_dry_run_plans_repo_items_without_writes(monkeypatch, capsys) -> None:
    source_items = [
        {
            "id": "source-issue",
            "content": {
                "type": "Issue",
                "number": 10,
                "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
                "updatedAt": "2026-09-04T12:00:00Z",
            },
            "status": "Blocked",
        },
        {
            "id": "source-pr",
            "content": {
                "type": "PullRequest",
                "number": 20,
                "url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/20",
                "updatedAt": "2026-09-04T12:00:00Z",
            },
            "status": "In Progress",
        },
        {
            "id": "other-repo",
            "content": {
                "type": "Issue",
                "number": 30,
                "url": "https://github.com/example/other/issues/30",
                "updatedAt": "2026-09-04T12:00:00Z",
            },
            "status": "Backlog",
        },
    ]
    destination_items = [
        {
            "id": "destination-pr",
            "content": source_items[1]["content"],
            "status": "In Progress",
        }
    ]

    monkeypatch.setattr(
        reconcile_project_status,
        "list_project_items_for_scan",
        lambda owner, _number: source_items if owner == "RasmusTho" else destination_items,
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 10,
            "state": "OPEN",
            "labels": [{"name": "agent:blocked"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
            "body": "",
        },
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "get_pr",
        lambda _repo, _number: {
            "number": 20,
            "state": "OPEN",
            "isDraft": False,
            "mergedAt": None,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/20",
        },
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "add_item_to_project",
        lambda *_args: pytest.fail("dry-run must not add project items"),
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "set_project_status",
        lambda *_args: pytest.fail("dry-run must not edit project items"),
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp", dry_run=True
    )
    result = reconcile_migration(
        args,
        "Yggdrasil-PKM",
        {"id": "destination", "number": 1, "title": "Agent Delivery Control Plane"},
        "status-field",
        {"Blocked": "blocked", "Review": "review"},
        "RasmusTho",
        {"id": "source", "number": 1, "title": "Agent Delivery Control Plane"},
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "plan issue #10: add; set Blocked" in output
    assert "plan pullrequest #20: keep; set Review" in output
    assert (
        "migration plan: source=2 already_present=1 add=1 status_update=2 "
        "unsupported=1 invalid_ready=0"
    ) in output
    assert "migration dry-run complete: no Project items were changed" in output


def test_migration_apply_is_idempotent_and_verifies_postconditions(monkeypatch, capsys) -> None:
    source_item = {
        "id": "source-issue",
        "content": {
            "type": "Issue",
            "number": 10,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
            "updatedAt": "2026-09-04T12:00:00Z",
        },
        "status": "Blocked",
    }
    state = {"added": False, "status": None}
    add_calls: list[tuple[object, ...]] = []
    status_calls: list[tuple[object, ...]] = []

    def fake_list(owner: str, _number: int) -> list[dict[str, object]]:
        if owner == "RasmusTho":
            return [source_item]
        if not state["added"]:
            return []
        return [
            {
                "id": "destination-issue",
                "content": source_item["content"],
                "status": state["status"] or "Backlog",
            }
        ]

    def fake_add(*call_args: object) -> None:
        add_calls.append(call_args)
        state["added"] = True

    def fake_set(*call_args: object) -> None:
        status_calls.append(call_args)
        state["status"] = "Blocked"

    monkeypatch.setattr(reconcile_project_status, "list_project_items_for_scan", fake_list)
    monkeypatch.setattr(reconcile_project_status, "add_item_to_project", fake_add)
    monkeypatch.setattr(reconcile_project_status, "set_project_status", fake_set)
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 10,
            "state": "OPEN",
            "labels": [{"name": "agent:blocked"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
            "body": "",
        },
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp", dry_run=False
    )
    call = lambda: reconcile_migration(
        args,
        "Yggdrasil-PKM",
        {"id": "destination", "number": 1, "title": "Agent Delivery Control Plane"},
        "status-field",
        {"Blocked": "blocked"},
        "RasmusTho",
        {"id": "source", "number": 1, "title": "Agent Delivery Control Plane"},
    )

    assert call() == 0
    assert call() == 0
    assert len(add_calls) == 1
    assert len(status_calls) == 1
    output = capsys.readouterr().out
    assert "missing_after=0 status_drift_after=0" in output
    assert "migration plan: source=1 already_present=1 add=0 status_update=0" in output


def test_migration_replaces_stale_done_status_with_live_issue_truth(monkeypatch) -> None:
    source_item = {
        "id": "source-issue",
        "content": {
            "type": "Issue",
            "number": 10,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
        },
        "status": "Done",
    }
    state = {"status": "Done"}
    status_calls: list[tuple[object, ...]] = []

    def fake_list(owner: str, _number: int) -> list[dict[str, object]]:
        if owner == "RasmusTho":
            return [source_item]
        return [
            {
                "id": "destination-issue",
                "content": source_item["content"],
                "status": state["status"],
            }
        ]

    def fake_set(*call_args: object) -> None:
        status_calls.append(call_args)
        state["status"] = "Backlog"

    monkeypatch.setattr(reconcile_project_status, "list_project_items_for_scan", fake_list)
    monkeypatch.setattr(reconcile_project_status, "set_project_status", fake_set)
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 10,
            "state": "OPEN",
            "labels": [],
            "body": "",
        },
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp", dry_run=False
    )
    result = reconcile_migration(
        args,
        "Yggdrasil-PKM",
        {"id": "destination", "number": 1},
        "status-field",
        {"Backlog": "backlog"},
        "RasmusTho",
        {"id": "source", "number": 1},
    )

    assert result == 0
    assert len(status_calls) == 1
    assert state["status"] == "Backlog"


def test_migration_retry_preserves_source_review_after_interrupted_add(monkeypatch) -> None:
    source_item = {
        "id": "source-issue",
        "content": {
            "type": "Issue",
            "number": 10,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
        },
        "status": "Review",
    }
    state = {"status": "Backlog"}
    status_calls: list[tuple[object, ...]] = []

    def fake_list(owner: str, _number: int) -> list[dict[str, object]]:
        item = (
            source_item
            if owner == "RasmusTho"
            else {
                "id": "destination-issue",
                "content": source_item["content"],
                "status": state["status"],
            }
        )
        return [item]

    def fake_set(*call_args: object) -> None:
        status_calls.append(call_args)
        state["status"] = "Review"

    monkeypatch.setattr(reconcile_project_status, "list_project_items_for_scan", fake_list)
    monkeypatch.setattr(reconcile_project_status, "set_project_status", fake_set)
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 10,
            "state": "OPEN",
            "labels": [],
            "body": "",
        },
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp", dry_run=False
    )
    result = reconcile_migration(
        args,
        "Yggdrasil-PKM",
        {"id": "destination", "number": 1},
        "status-field",
        {"Review": "review"},
        "RasmusTho",
        {"id": "source", "number": 1},
    )

    assert result == 0
    assert len(status_calls) == 1
    assert state["status"] == "Review"


def test_migration_final_verification_detects_lifecycle_race(monkeypatch, capsys) -> None:
    source_item = {
        "id": "source-issue",
        "content": {
            "type": "Issue",
            "number": 10,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
        },
        "status": "Blocked",
    }
    issue_reads = iter(
        [
            {"number": 10, "state": "OPEN", "labels": [{"name": "agent:blocked"}], "body": ""},
            {"number": 10, "state": "CLOSED", "labels": [], "body": ""},
        ]
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "list_project_items_for_scan",
        lambda _owner, _number: [
            {
                "id": "destination-issue",
                "content": source_item["content"],
                "status": "Blocked",
            }
        ],
    )
    monkeypatch.setattr(reconcile_project_status, "get_issue", lambda *_args: next(issue_reads))

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp", dry_run=False
    )
    result = reconcile_migration(
        args,
        "Yggdrasil-PKM",
        {"id": "destination", "number": 1},
        "status-field",
        {"Blocked": "blocked", "Done": "done"},
        "RasmusTho",
        {"id": "source", "number": 1},
    )

    assert result == 1
    assert "status_drift_after=1" in capsys.readouterr().out


def test_migration_final_verification_detects_source_growth(monkeypatch, capsys) -> None:
    first_source_item = {
        "id": "source-10",
        "content": {
            "type": "Issue",
            "number": 10,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/10",
        },
        "status": "Backlog",
    }
    late_source_item = {
        "id": "source-11",
        "content": {
            "type": "Issue",
            "number": 11,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/11",
        },
        "status": "Backlog",
    }
    source_reads = 0

    def fake_list(owner: str, _number: int) -> list[dict[str, object]]:
        nonlocal source_reads
        if owner == "RasmusTho":
            source_reads += 1
            return (
                [first_source_item] if source_reads == 1 else [first_source_item, late_source_item]
            )
        return [
            {
                "id": "destination-10",
                "content": first_source_item["content"],
                "status": "Backlog",
            }
        ]

    monkeypatch.setattr(reconcile_project_status, "list_project_items_for_scan", fake_list)
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, number: {
            "number": number,
            "state": "OPEN",
            "labels": [],
            "body": "",
        },
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp", dry_run=False
    )
    result = reconcile_migration(
        args,
        "Yggdrasil-PKM",
        {"id": "destination", "number": 1},
        "status-field",
        {"Backlog": "backlog"},
        "RasmusTho",
        {"id": "source", "number": 1},
    )

    assert result == 1
    output = capsys.readouterr().out
    assert "source=2" in output
    assert "missing_after=1" in output
    assert "https://github.com/RasmusTho/agentic-pkm-mvp/issues/11" in output


def test_migration_cli_is_dry_run_by_default(monkeypatch) -> None:
    observed: dict[str, object] = {}

    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 5000)
    monkeypatch.setattr(
        reconcile_project_status,
        "discover_project",
        lambda owner, _title: {"id": owner, "number": 1, "title": "Agent Delivery Control Plane"},
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "get_status_field",
        lambda _owner, _number: ("status-field", {"Backlog": "backlog"}),
    )

    def fake_migration(args, *_rest):
        observed["dry_run"] = args.dry_run
        return 0

    monkeypatch.setattr(reconcile_project_status, "reconcile_migration", fake_migration)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reconcile",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--owner",
            "Yggdrasil-PKM",
            "--migrate-from-owner",
            "RasmusTho",
        ],
    )

    assert reconcile_project_status.main() == 0
    assert observed == {"dry_run": True}


def test_migration_cli_fails_when_budget_gate_skips_execution(monkeypatch, capsys) -> None:
    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 0)
    monkeypatch.setattr(
        reconcile_project_status,
        "discover_project",
        lambda *_args: pytest.fail("budget gate must stop before Project discovery"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reconcile",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--owner",
            "Yggdrasil-PKM",
            "--migrate-from-owner",
            "RasmusTho",
            "--apply",
        ],
    )

    assert reconcile_project_status.main() == 1
    assert "skip project migration from RasmusTho" in capsys.readouterr().out


def test_scan_item_list_uses_typed_query_for_legacy_user_project(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run_gh(*args: str) -> str:
        commands.append(args)
        if args[:2] == ("api", "users/RasmusTho"):
            return '{"type":"User"}'
        return reconcile_project_status.json.dumps(
            {
                "data": {
                    "user": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [],
                            }
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    assert reconcile_project_status.list_project_items_for_scan("RasmusTho", 1) == []
    assert len(commands) == 2
    assert commands[0][:2] == ("api", "users/RasmusTho")
    assert "organization(login: $owner)" not in commands[1][3]
    assert "user(login: $owner)" in commands[1][3]


def test_run_gh_uses_repository_token_for_issue_reads(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(_command, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess([], 0, stdout="{}", stderr="")

    monkeypatch.setenv("REPO_GH_TOKEN", "repository-token")
    monkeypatch.setattr(reconcile_project_status.subprocess, "run", fake_run)

    reconcile_project_status.run_gh("issue", "view", "2680")

    assert calls[0]["env"]["GH_TOKEN"] == "repository-token"


def test_run_gh_uses_repository_token_for_issue_graphql(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(_command, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess([], 0, stdout="{}", stderr="")

    monkeypatch.setenv("REPO_GH_TOKEN", "repository-token")
    monkeypatch.setattr(reconcile_project_status.subprocess, "run", fake_run)

    reconcile_project_status.run_gh("api", "graphql", use_repo_token=True)

    assert calls[0]["env"]["GH_TOKEN"] == "repository-token"


def test_project_status_forwards_explicit_organization_owner(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(project_status.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "project_status",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--owner",
            "Yggdrasil-PKM",
            "--pr",
            "5193",
            "--action",
            "ready_for_review",
        ],
    )

    assert project_status.main() == 0
    assert calls == [
        [
            sys.executable,
            "scripts/reconcile_project_status.py",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--owner",
            "Yggdrasil-PKM",
            "--pr",
            "5193",
            "--status",
            "Review",
        ]
    ]


def test_project_status_defaults_owner_to_repository_owner(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(project_status.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "project_status",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--pr",
            "5193",
            "--action",
            "ready_for_review",
        ],
    )

    assert project_status.main() == 0
    assert "--owner" in calls[0]
    assert calls[0][calls[0].index("--owner") + 1] == "RasmusTho"


def test_scan_item_list_fails_loud_without_updated_at(monkeypatch) -> None:
    def fake_run_gh(*_args: str) -> str:
        if _args[:2] == ("api", "users/RasmusTho"):
            return '{"type":"User"}'
        return reconcile_project_status.json.dumps(
            {
                "data": {
                    "user": {
                        "projectV2": {
                            "items": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "item-1",
                                        "content": {
                                            "__typename": "PullRequest",
                                            "number": 202,
                                            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/202",
                                        },
                                        "fieldValues": {"nodes": []},
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        )

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    with pytest.raises(RuntimeError, match="missing Issue/PullRequest updatedAt"):
        reconcile_project_status.list_project_items_for_scan("RasmusTho", 1)


def test_scan_is_incremental_by_updated_at(monkeypatch, tmp_path) -> None:
    watermark_path = tmp_path / "project_status_reconcile_scan_watermark.json"
    monkeypatch.setattr(reconcile_project_status, "SCAN_WATERMARK_PATH", watermark_path)

    items = [
        {
            "id": "item-old",
            "content": {
                "type": "Issue",
                "number": 101,
                "updatedAt": "2026-06-28T12:00:00Z",
            },
            "status": "Ready",
        },
        {
            "id": "item-new",
            "content": {
                "type": "PullRequest",
                "number": 202,
                "updatedAt": "2026-06-30T13:00:00Z",
            },
            "status": "In Progress",
        },
    ]
    issue_calls: list[int] = []
    pr_calls: list[int] = []
    status_calls: list[tuple[str, str, str, str, str, bool]] = []

    def fake_get_issue(_repo: str, number: int) -> dict[str, object]:
        issue_calls.append(number)
        return {
            "number": number,
            "state": "OPEN",
            "labels": [{"name": "agent:ready"}],
            "url": f"https://github.com/RasmusTho/agentic-pkm-mvp/issues/{number}",
            "body": VALID_READY_BODY,
        }

    def fake_get_pr(_repo: str, number: int) -> dict[str, object]:
        pr_calls.append(number)
        return {
            "number": number,
            "state": "OPEN",
            "isDraft": False,
            "mergedAt": None,
            "url": f"https://github.com/RasmusTho/agentic-pkm-mvp/pull/{number}",
        }

    def fake_set_project_status(owner, project_id, item_id, field_id, option_id, dry_run):
        status_calls.append((owner, project_id, item_id, field_id, option_id, dry_run))

    monkeypatch.setattr(
        reconcile_project_status,
        "list_project_items_for_scan",
        lambda _owner, _project_number: items,
    )
    monkeypatch.setattr(reconcile_project_status, "get_issue", fake_get_issue)
    monkeypatch.setattr(reconcile_project_status, "get_pr", fake_get_pr)
    monkeypatch.setattr(reconcile_project_status, "set_project_status", fake_set_project_status)
    monkeypatch.setattr(
        reconcile_project_status,
        "_scan_started_at",
        lambda: datetime(2026, 6, 30, 12, 30, tzinfo=timezone.utc),
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        dry_run=False,
        status=None,
    )
    project = {"id": "project-1", "number": 1, "title": "Agent Delivery Control Plane"}
    status_options = {"Ready": "ready-id", "Review": "review-id"}

    watermark_path.write_text(
        json.dumps({"last_scan_started_at": "2026-06-29T00:00:00Z"}),
        encoding="utf-8",
    )
    assert (
        reconcile_project_status.reconcile_scan(
            args, "RasmusTho", project, "field-id", status_options
        )
        == 0
    )
    assert issue_calls == []
    assert pr_calls == [202]
    assert status_calls == [("RasmusTho", "project-1", "item-new", "field-id", "review-id", False)]
    assert json.loads(watermark_path.read_text(encoding="utf-8")) == {
        "last_scan_started_at": "2026-06-30T12:30:00Z"
    }

    issue_calls.clear()
    pr_calls.clear()
    status_calls.clear()
    watermark_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(
        reconcile_project_status,
        "_scan_started_at",
        lambda: datetime(2026, 7, 1, 8, 45, tzinfo=timezone.utc),
    )

    assert (
        reconcile_project_status.reconcile_scan(
            args, "RasmusTho", project, "field-id", status_options
        )
        == 0
    )
    assert issue_calls == [101]
    assert pr_calls == [202]
    assert status_calls == [("RasmusTho", "project-1", "item-new", "field-id", "review-id", False)]
    assert json.loads(watermark_path.read_text(encoding="utf-8")) == {
        "last_scan_started_at": "2026-07-01T08:45:00Z"
    }


@pytest.mark.parametrize("current_status", ["Backlog", "Ready"])
def test_scan_refuses_project_ready_for_invalid_agent_ready_issue(
    monkeypatch,
    tmp_path,
    capsys,
    current_status: str,
) -> None:
    watermark_path = tmp_path / "project_status_reconcile_scan_watermark.json"
    monkeypatch.setattr(reconcile_project_status, "SCAN_WATERMARK_PATH", watermark_path)
    item = {
        "id": "item-invalid",
        "content": {
            "type": "Issue",
            "number": 3213,
            "updatedAt": "2026-07-01T12:00:00Z",
        },
        "status": current_status,
    }
    status_calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        reconcile_project_status,
        "list_project_items_for_scan",
        lambda _owner, _project_number: [item],
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "get_issue",
        lambda _repo, _number: {
            "number": 3213,
            "state": "OPEN",
            "labels": [{"name": "agent:ready"}],
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/3213",
            "body": INVALID_READY_BODY,
        },
    )
    monkeypatch.setattr(
        reconcile_project_status,
        "set_project_status",
        lambda *args: status_calls.append(args),
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        dry_run=False,
        status=None,
    )
    project = {"id": "project-1", "number": 1, "title": "Agent Delivery Control Plane"}

    assert (
        reconcile_project_status.reconcile_scan(
            args,
            "RasmusTho",
            project,
            "field-id",
            {"Backlog": "backlog-id", "Ready": "ready-id"},
        )
        == 1
    )
    if current_status == "Ready":
        assert status_calls == [
            ("RasmusTho", "project-1", "item-invalid", "field-id", "backlog-id", False)
        ]
    else:
        assert status_calls == []
    assert not watermark_path.exists()
    output = capsys.readouterr().out
    assert "invalid issue #3213" in output
    assert "missing_required_sections" in output
    assert "scan failed: 1 invalid agent:ready issue(s)" in output


def test_reconcile_skips_graphql_when_kill_switch_active(monkeypatch, capsys) -> None:
    # AC1 (#2746 / GHAPI-C2): the shared GitHub-API kill switch must stop the
    # reconcile BEFORE any `gh project` GraphQL is issued, with an explicit
    # skip receipt (never a silent no-op).
    def fail_discover(*_args, **_kwargs):
        raise AssertionError("must not issue GraphQL when the kill switch is active")

    monkeypatch.delenv("GITHUB_RATELIMIT_KILL_THRESHOLD", raising=False)
    # remaining=100 is below the shared default threshold (200) -> switch active.
    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 100)
    monkeypatch.setattr(reconcile_project_status, "discover_project", fail_discover)
    monkeypatch.setattr(sys, "argv", ["reconcile", "--repo", "RasmusTho/agentic-pkm-mvp", "--scan"])
    assert reconcile_project_status.main() == 0
    captured = capsys.readouterr()
    assert "skip project scan" in captured.out
    assert "kill switch active" in captured.out
    receipts = [
        json.loads(line) for line in captured.err.splitlines() if '"github.budget.skip"' in line
    ]
    assert len(receipts) == 1, "kill-switch skip must emit a structured receipt"
    assert receipts[0]["kill_switch_active"] is True
    assert receipts[0]["remaining"] == 100


def test_budget_gate_uses_shared_kill_switch(monkeypatch, capsys) -> None:
    # AC2 (#2746): the block decision comes from ONE source of truth —
    # app.dispatcher.github_call_logger — at the production call site (main()).
    # The shared threshold is raised ABOVE this script's own budget floors:
    # remaining=700 passes both floors (500 scan / 250 optional), so the skip
    # can only come from the shared kill switch, not duplicated local parsing.
    def fail_discover(*_args, **_kwargs):
        raise AssertionError("shared kill switch must gate before project discovery")

    monkeypatch.setenv("GITHUB_RATELIMIT_KILL_THRESHOLD", "1000")
    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 700)
    monkeypatch.setattr(reconcile_project_status, "discover_project", fail_discover)
    monkeypatch.setattr(sys, "argv", ["reconcile", "--repo", "RasmusTho/agentic-pkm-mvp", "--scan"])
    assert reconcile_project_status.main() == 0
    out = capsys.readouterr().out
    assert "GitHub API kill switch active" in out

    # No duplicated threshold/env parsing in the reconcile script itself.
    source = Path("scripts/reconcile_project_status.py").read_text(encoding="utf-8")
    assert (
        "GITHUB_RATELIMIT_KILL_THRESHOLD" not in source
    ), "kill-switch threshold must live only in app/dispatcher/github_call_logger.py"


def test_run_gh_aborts_retry_when_reset_beyond_cap(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(reconcile_project_status.time, "sleep", lambda s: slept.append(s))

    def always_rate_limited(cmd, **_kwargs):
        raise subprocess.CalledProcessError(
            returncode=1, cmd=cmd, stderr="GraphQL: secondary rate limit"
        )

    monkeypatch.setattr(reconcile_project_status.subprocess, "run", always_rate_limited)
    # Reset is far in the future -> wait exceeds the cap -> stop, never sleep.
    monkeypatch.setattr(
        reconcile_project_status,
        "graphql_rate_limit",
        lambda: (0, int(reconcile_project_status.time.time()) + 100_000),
    )
    with pytest.raises(subprocess.CalledProcessError):
        reconcile_project_status.run_gh("project", "item-list", "1")
    assert slept == [], "must not block the runner waiting on a far-off reset"


def test_run_gh_waits_until_reset_within_cap_then_succeeds(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(reconcile_project_status.time, "sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    def rate_limited_then_ok(cmd, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.CalledProcessError(
                returncode=1, cmd=cmd, stderr="API rate limit exceeded"
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(reconcile_project_status.subprocess, "run", rate_limited_then_ok)
    monkeypatch.setattr(
        reconcile_project_status,
        "graphql_rate_limit",
        lambda: (0, int(reconcile_project_status.time.time()) + 5),
    )
    assert reconcile_project_status.run_gh("project", "item-list", "1") == "ok"
    assert slept, "must wait until reset before retrying"
    assert 1 <= slept[0] <= reconcile_project_status.GH_MAX_RATE_LIMIT_WAIT_SECONDS + 1


def test_rate_limit_wait_prefers_retry_after_header(monkeypatch) -> None:
    monkeypatch.setattr(reconcile_project_status, "graphql_rate_limit", lambda: (0, 10**12))
    exc = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh"],
        stderr="You have exceeded a secondary rate limit. Retry-After: 7",
    )
    # Explicit Retry-After wins over the (far) reset epoch.
    assert reconcile_project_status._rate_limit_wait_seconds(exc) == 7
