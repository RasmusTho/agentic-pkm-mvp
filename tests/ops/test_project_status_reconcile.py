from pathlib import Path
import subprocess

import pytest

from scripts import reconcile_project_status
from scripts.reconcile_project_status import (
    desired_pr_status,
    list_project_items,
    load_governance_project_name,
    reconcile_issue,
    reconcile_pr,
)


def test_desired_pr_status_open_pr_is_in_progress() -> None:
    assert desired_pr_status({"state": "OPEN", "mergedAt": None}, None) == "In Progress"


def test_desired_pr_status_closed_unmerged_pr_is_done() -> None:
    assert desired_pr_status({"state": "CLOSED", "mergedAt": None}, None) == "Done"


def test_desired_pr_status_explicit_status_wins() -> None:
    assert (
        desired_pr_status({"state": "CLOSED", "mergedAt": None}, "Review")
        == "Review"
    )


def test_load_governance_project_name_reads_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    governance_dir = Path(".github")
    governance_dir.mkdir(parents=True)
    governance_file = governance_dir / "github-governance.yml"
    governance_file.write_text("project:\n  name: Custom Project\n", encoding="utf-8")
    assert load_governance_project_name() == "Custom Project"


def test_load_governance_project_name_falls_back_when_file_missing(
    tmp_path, monkeypatch
) -> None:
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
    full_items = [
        *first_page_items,
        {"id": "item-201", "content": {"type": "Issue", "number": 201}},
    ]

    def fake_run_gh(*args: str) -> str:
        commands.append(args)
        limit = args[args.index("--limit") + 1]
        if limit == "200":
            return reconcile_project_status.json.dumps(
                {"items": first_page_items, "totalCount": 201}
            )
        if limit == "201":
            return reconcile_project_status.json.dumps(
                {"items": full_items, "totalCount": 201}
            )
        raise AssertionError(f"unexpected limit: {limit}")

    monkeypatch.setattr(reconcile_project_status, "run_gh", fake_run_gh)

    assert list_project_items("RasmusTho", 1) == full_items
    assert [command[command.index("--limit") + 1] for command in commands] == [
        "200",
        "201",
    ]


def test_reconcile_issue_does_not_add_item_found_after_initial_limit(
    monkeypatch, capsys
) -> None:
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
                return reconcile_project_status.json.dumps(
                    {"items": full_items, "totalCount": 201}
                )
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
        },
    )
    monkeypatch.setattr(
        reconcile_project_status, "add_item_to_project", fail_add_item_to_project
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        issue=495,
        dry_run=False,
        status=None,
    )

    assert reconcile_issue(args, "RasmusTho", {"number": 1}, "field", {"Ready": "opt"}) == 0
    assert add_calls == []
    assert "issue #495: already Ready" in capsys.readouterr().out


def test_reconcile_pr_does_not_add_item_found_after_initial_limit(
    monkeypatch, capsys
) -> None:
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
            "status": "In Progress",
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
                return reconcile_project_status.json.dumps(
                    {"items": full_items, "totalCount": 201}
                )
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
            "mergedAt": None,
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/501",
        },
    )
    monkeypatch.setattr(
        reconcile_project_status, "add_item_to_project", fail_add_item_to_project
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        pr=501,
        dry_run=False,
        status=None,
    )

    assert (
        reconcile_pr(args, "RasmusTho", {"number": 1}, "field", {"In Progress": "opt"})
        == 0
    )
    assert add_calls == []
    assert "pr #501: already In Progress" in capsys.readouterr().out


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
        },
    )
    monkeypatch.setattr(
        reconcile_project_status, "add_item_to_project", fail_add_item_to_project
    )

    args = reconcile_project_status.argparse.Namespace(
        repo="RasmusTho/agentic-pkm-mvp",
        issue=495,
        dry_run=False,
        status=None,
    )

    with pytest.raises(subprocess.CalledProcessError):
        reconcile_issue(args, "RasmusTho", {"number": 1}, "field", {"Ready": "opt"})
    assert add_calls == []
