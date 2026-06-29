from pathlib import Path
import subprocess
import sys

import pytest

from scripts import project_status
from scripts import reconcile_project_status
from scripts.reconcile_project_status import (
    desired_pr_status,
    get_pr,
    list_project_items,
    load_governance_project_name,
    reconcile_issue,
    reconcile_pr,
)


def test_desired_pr_status_open_non_draft_pr_is_review() -> None:
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": False, "mergedAt": None}, None)
        == "Review"
    )


def test_open_non_draft_pr_without_review_request_matches_documented_status() -> None:
    matrix = Path(".codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md").read_text(
        encoding="utf-8"
    )

    assert "| PR | OPEN + non-draft, no review requested | `Review` |" in matrix
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": False, "mergedAt": None}, None)
        == "Review"
    )
    assert project_status.desired_status("opened", False) == "Review"


def test_desired_pr_status_open_draft_pr_is_in_progress() -> None:
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": True, "mergedAt": None}, None)
        == "In Progress"
    )


def test_desired_pr_status_closed_unmerged_pr_is_done() -> None:
    assert desired_pr_status({"state": "CLOSED", "mergedAt": None}, None) == "Done"


def test_desired_pr_status_explicit_status_wins() -> None:
    assert (
        desired_pr_status({"state": "CLOSED", "mergedAt": None}, "Review")
        == "Review"
    )


def test_desired_status_closed_action_projects_done() -> None:
    # A `closed` pull_request event is terminal for both merged and
    # unmerged-closed PRs; the card must reach Done regardless of draft state.
    assert project_status.desired_status("closed", None) == "Done"
    assert project_status.desired_status("closed", True) == "Done"
    assert project_status.desired_status("closed", False) == "Done"


def test_pr_stage_change_workflow_subscribes_to_closed_event() -> None:
    # Merge/close must be event-driven so terminal projection does not depend on
    # the best-effort hourly reconcile scan.
    workflow = Path(".github/workflows/project-pr-stage-change.yml").read_text(
        encoding="utf-8"
    )
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
            "isDraft": False,
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
        reconcile_pr(args, "RasmusTho", {"number": 1}, "field", {"Review": "opt"})
        == 0
    )
    assert add_calls == []
    assert "pr #501: already Review" in capsys.readouterr().out


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


def test_reconcile_pr_soft_fails_on_transient_project_add_failure(
    monkeypatch, capsys
) -> None:
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
    assert 'soft-fail issue #2144: failed to add to project "Agent Delivery Control Plane"' in output


# --- GraphQL-budget incident remediation (GHAPI-C2 / GHAPI-H2 / GHAPI-H3) ---


def test_scan_is_daily_and_rate_limit_gated(monkeypatch, capsys) -> None:
    # The hourly full-board scan was the dominant GraphQL drain; cron must be daily.
    workflow = Path(".github/workflows/project-status-reconcile.yml").read_text(
        encoding="utf-8"
    )
    assert "cron: '17 * * * *'" not in workflow, "hourly project scan must be removed"
    assert "cron: '17 7 * * *'" in workflow, "scan cron must be daily"

    # And a low GraphQL budget must skip the scan BEFORE project discovery,
    # which itself spends `gh project` GraphQL calls.
    def fail_discover(*_args, **_kwargs):
        raise AssertionError("must not discover the project when GraphQL budget is low")

    monkeypatch.setattr(reconcile_project_status, "graphql_budget_remaining", lambda: 100)
    monkeypatch.setattr(reconcile_project_status, "discover_project", fail_discover)
    monkeypatch.setattr(
        sys, "argv", ["reconcile", "--repo", "RasmusTho/agentic-pkm-mvp", "--scan"]
    )
    assert reconcile_project_status.main() == 0
    out = capsys.readouterr().out
    assert "skip project scan: GraphQL budget low" in out
    assert "before project discovery" in out


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
    monkeypatch.setattr(
        sys, "argv", ["reconcile", "--repo", "RasmusTho/agentic-pkm-mvp", "--scan"]
    )
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
    monkeypatch.setattr(
        reconcile_project_status, "graphql_rate_limit", lambda: (0, 10**12)
    )
    exc = subprocess.CalledProcessError(
        returncode=1,
        cmd=["gh"],
        stderr="You have exceeded a secondary rate limit. Retry-After: 7",
    )
    # Explicit Retry-After wins over the (far) reset epoch.
    assert reconcile_project_status._rate_limit_wait_seconds(exc) == 7
