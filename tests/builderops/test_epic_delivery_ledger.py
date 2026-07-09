from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.epic_delivery_ledger import build_parent_epic_delivery_ledger


def _run_builderops(args: list[str]):
    return CliRunner().invoke(
        builderops_standalone_root,
        ["builderops", *args],
        catch_exceptions=False,
    )


def test_render_parent_epic_delivery_ledger() -> None:
    ledger = build_parent_epic_delivery_ledger(
        epic_issue_number=3279,
        children=[
            {
                "issue_number": 3274,
                "title": "builder: add CI stall classifier",
                "issue_status": "closed",
                "pr_number": 3296,
                "pr_status": "merged",
                "head_sha": "76a5ce66",
                "merge_sha": "73ec7128",
                "ci_state": "passed",
                "blocker": "none",
                "next_action": "pick #3275",
            }
        ],
    )

    assert ledger["authority"] == "coordination_evidence_only_live_github_issues_prs_ci_win"
    assert ledger["warnings"] == []
    assert "| #3274 builder: add CI stall classifier | closed | #3296 merged |" in ledger["markdown"]
    assert "Ledger authority: coordination evidence only" in ledger["markdown"]
    assert "merge `73ec7128`" in ledger["markdown"]


def test_ledger_warns_on_live_truth_conflict() -> None:
    ledger = build_parent_epic_delivery_ledger(
        epic_issue_number=3279,
        children=[
            {
                "issue_number": 3275,
                "title": "builder: generate PR body",
                "issue_status": "review",
                "pr_number": 3298,
                "pr_status": "open",
                "head_sha": "old",
                "ci_state": "pending",
            }
        ],
        live_truth={
            "children": {
                "3275": {
                    "issue_status": "closed",
                    "pr_status": "merged",
                    "head_sha": "new",
                    "ci_state": "passed",
                }
            }
        },
    )

    fields = {warning["field"] for warning in ledger["warnings"]}
    assert fields == {"issue_status", "pr_status", "head_sha", "ci_state"}
    assert "live_truth_conflict: #3275 issue_status ledger=review live=closed" in ledger["markdown"]


def test_ledger_accepts_github_style_child_issue_number() -> None:
    ledger = build_parent_epic_delivery_ledger(
        epic_issue_number=3279,
        children=[
            {
                "number": 3277,
                "title": "builder: add parent epic delivery ledger",
                "state": "open",
                "ci_state": "pending",
            }
        ],
    )

    assert ledger["children"][0]["issue_number"] == 3277
    assert "#3277 builder: add parent epic delivery ledger" in ledger["markdown"]


def test_ledger_rebuilds_from_coordination_inputs(tmp_path: Path) -> None:
    children_file = tmp_path / "children.json"
    children_file.write_text(
        json.dumps({
            "children": [
                {
                    "issue_number": 3276,
                    "title": "builder: enforce review-before-CI",
                    "issue_status": "closed",
                    "pr_number": 3303,
                    "pr_status": "merged",
                    "merge_sha": "a590739c",
                    "ci_state": "passed",
                    "blocker": "none",
                    "next_action": "pick #3277",
                }
            ]
        }),
        encoding="utf-8",
    )

    result = _run_builderops([
        "epic-run-state",
        "ledger",
        "render",
        "--epic-issue-number",
        "3279",
        "--children-file",
        str(children_file),
        "--json",
    ])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["child_count"] == 1
    assert payload["children"][0]["issue_number"] == 3276
    assert payload["children"][0]["merge_sha"] == "a590739c"
    assert "pick #3277" in payload["markdown"]
