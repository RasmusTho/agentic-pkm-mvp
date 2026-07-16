from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.dispatcher.verification_contract import MAX_CLOSING_ISSUES
from app.dispatcher.verified_merge import (
    VERIFIED_MERGE_AUTHORITY_CONTRACT,
    plan_post_merge_reconciliation,
    prepare_verified_merge,
)


HEAD = "a" * 40
REPOSITORY = "RasmusTho/agentic-pkm-mvp"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _context() -> dict[str, object]:
    return {
        "contract": "verification_closer_dispatch_context.v2",
        "run_id": "vrun-authority",
        "repository": REPOSITORY,
        "pr_number": 3822,
        "governing_issue": 3821,
        "closing_issues": [3820, 3823],
        "supporting_issues": [3820, 3823],
        "head_sha": HEAD,
        "repair_budget": {
            "policy_version": "v2",
            "mechanisms": [
                {
                    "mechanism_id": "mutable-body-closure",
                    "standard_attempts_used": 2,
                    "escalated_attempts_used": 2,
                }
            ],
        },
    }


def _body() -> str:
    return (
        "Governing-Issue: #3821\n\n"
        "Refs #3821\n"
        "Fixes #3820\n"
        "Closes: #3823\n"
        "Refs #3900\n"
    )


def _pr(body: str | None = None) -> dict[str, object]:
    return {
        "number": 3822,
        "state": "open",
        "merged_at": None,
        "draft": False,
        "title": "governance: deterministic issue-set closure",
        "body": _body() if body is None else body,
        "head": {"sha": HEAD},
    }


def test_prepare_verified_merge_neutralizes_closers_and_preserves_authority() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[
            {"number": 3823, "repository": REPOSITORY},
            {"number": 3820, "repository": REPOSITORY},
        ],
    )

    assert "Fixes #3820" not in plan["neutralized_body"]
    assert "Closes: #3823" not in plan["neutralized_body"]
    assert "Refs #3820" in plan["neutralized_body"]
    assert "Refs #3823" in plan["neutralized_body"]
    assert "Verified-Closing-Issues: #3820, #3823" in plan["neutralized_body"]
    receipt = plan["authority_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["contract"] == VERIFIED_MERGE_AUTHORITY_CONTRACT
    assert receipt["governing_issue"] == 3821
    assert receipt["closing_issues"] == [3820, 3823]
    assert receipt["authenticated_supporting_issues"] == [3820, 3823]
    assert receipt["live_supporting_issues"] == [3820, 3823, 3900]
    assert receipt["repair_budget"] == _context()["repair_budget"]
    assert receipt["body_sha256"] == hashlib.sha256(
        _body().encode("utf-8")
    ).hexdigest()
    assert plan["authority_receipt_comment"].startswith(
        "verified issue-set merge authority:\n```json\n"
    )
    assert "Fixes" not in plan["fixed_commit_title"]
    assert "Closes" not in plan["fixed_commit_message"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda context, pr, closing: pr.update(
                body=_body().replace("Closes: #3823", "Refs #3823")
            ),
            "live PR authority changed",
        ),
        (
            lambda context, pr, closing: pr.update(title="Fixes #9999"),
            "live PR snapshot is ineligible",
        ),
        (
            lambda context, pr, closing: closing.append(9999),
            "GitHub closing links changed",
        ),
        (
            lambda context, pr, closing: context.update(head_sha="b" * 40),
            "live PR snapshot is ineligible",
        ),
    ],
)
def test_prepare_verified_merge_fails_closed_on_mutable_authority_races(
    mutate,
    message: str,
) -> None:
    context = _context()
    pr = _pr()
    closing = [3820, 3823]
    mutate(context, pr, closing)

    with pytest.raises(ValueError, match=message):
        prepare_verified_merge(
            context=context,
            pr=pr,
            live_closing_issues=closing,
        )


@pytest.mark.parametrize(
    "suffix",
    [
        "\nCloses #",
        "\nCloses #\u00a0",
        "\nFixes owner/repo#9999",
        "\nResolves https://github.com/owner/repo/issues/9999",
        "\u2028Closes #9999",
    ],
)
def test_prepare_verified_merge_rejects_noncanonical_closure_attempts(
    suffix: str,
) -> None:
    with pytest.raises(ValueError, match="live PR authority changed"):
        prepare_verified_merge(
            context=_context(),
            pr=_pr(_body() + suffix),
            live_closing_issues=[3820, 3823],
        )


def test_prepare_verified_merge_keeps_ten_issue_limit() -> None:
    context = _context()
    closing = list(range(4000, 4000 + MAX_CLOSING_ISSUES))
    context["closing_issues"] = closing
    context["supporting_issues"] = closing
    body = "Governing-Issue: #3821\n" + "\n".join(
        f"Fixes #{number}" for number in closing
    )
    plan = prepare_verified_merge(
        context=context,
        pr=_pr(body),
        live_closing_issues=closing,
    )
    assert plan["authority_receipt"]["closing_issues"] == closing

    over_limit = copy.deepcopy(context)
    over_limit["closing_issues"] = [*closing, 5000]
    over_limit["supporting_issues"] = [*closing, 5000]
    with pytest.raises(ValueError, match="closing issues is malformed"):
        prepare_verified_merge(
            context=over_limit,
            pr=_pr(body + "\nFixes #5000"),
            live_closing_issues=[*closing, 5000],
        )


def test_prepare_verified_merge_cli_uses_production_planner(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    pr_path = tmp_path / "pr.json"
    closing_path = tmp_path / "closing.json"
    output_path = tmp_path / "plan.json"
    context_path.write_text(json.dumps(_context()), encoding="utf-8")
    pr_path.write_text(json.dumps(_pr()), encoding="utf-8")
    closing_path.write_text(json.dumps([3820, 3823]), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.prepare_verified_issue_set_merge",
            "--context-json",
            str(context_path),
            "--pr-json",
            str(pr_path),
            "--live-closing-json",
            str(closing_path),
            "--output-json",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(output_path.read_text(encoding="utf-8"))
    assert plan["authority_receipt"]["closing_issues"] == [3820, 3823]
    assert "Refs #3820" in plan["neutralized_body"]


def test_post_merge_race_reopens_only_closures_attributed_to_current_pr() -> None:
    plan = plan_post_merge_reconciliation(
        pr_number=3822,
        authenticated_closing_issues=[3820, 3823],
        observed_closing_issues=[3820, 3823, 4999, 5000, 5001],
        issue_evidence=[
            {"number": 3820, "state": "closed", "closed_by_pull_requests": [3822]},
            {"number": 3823, "state": "open", "closed_by_pull_requests": []},
            {"number": 4999, "state": "closed", "closed_by_pull_requests": [3822]},
            {"number": 5000, "state": "closed", "closed_by_pull_requests": [3000]},
            {"number": 5001, "state": "open", "closed_by_pull_requests": []},
        ],
    )

    assert plan == {
        "explicitly_close": [3820, 3823],
        "reopen_unauthorized": [4999],
        "unexpected_open_references": [5001],
        "unresolved_unauthorized_closures": [5000],
    }


def test_post_merge_reconciliation_requires_complete_issue_evidence() -> None:
    with pytest.raises(ValueError, match="evidence is incomplete"):
        plan_post_merge_reconciliation(
            pr_number=3822,
            authenticated_closing_issues=[3820],
            observed_closing_issues=[3820, 4999],
            issue_evidence=[
                {"number": 3820, "state": "closed", "closed_by_pull_requests": [3822]}
            ],
        )
