from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/post-merge-owner-doc-watchdog.yml"
REPOSITORY = "RasmusTho/agentic-pkm-mvp"
HEAD = "a" * 40


def _helpers() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("// owner-doc-watchdog-helpers:start", 1)[1].split(
        "// owner-doc-watchdog-helpers:end", 1
    )[0]


def _node(expression: str, *values: object) -> object:
    script = (
        'const crypto = require("crypto");\n'
        + _helpers()
        + "\nconst inputs = JSON.parse(process.argv[1]);\n"
        + f"process.stdout.write(JSON.stringify({expression}));"
    )
    completed = subprocess.run(
        ["node", "-e", script, json.dumps(values)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _body() -> str:
    return (
        "Governing-Issue: #3821\n\n"
        "Refs #3821\n"
        "Fixes #3820\n"
        "Closes #3823\n"
    )


def _authority_comment(body: str | None = None) -> dict[str, object]:
    original = _body() if body is None else body
    neutralized = original.replace("Fixes #3820", "Refs #3820").replace(
        "Closes #3823", "Refs #3823"
    ) + "Verified-Closing-Issues: #3820, #3823\n"
    receipt = {
        "authenticated_supporting_issues": [3820, 3823],
        "body_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "closing_issues": [3820, 3823],
        "contract": "verified_issue_set_merge_authority.v1",
        "governing_issue": 3821,
        "head_sha": HEAD,
        "live_supporting_issues": [3820, 3823],
        "neutralized_body_sha256": hashlib.sha256(neutralized.encode()).hexdigest(),
        "pr_number": 3822,
        "repair_budget": {"policy_version": "v2", "mechanisms": []},
        "repository": REPOSITORY,
        "run_id": "vrun-authority",
    }
    return {
        "author_association": "OWNER",
        "body": (
            "verified issue-set merge authority:\n```json\n"
            + json.dumps(receipt, separators=(",", ":"), sort_keys=True)
            + "\n```"
        ),
    }


def _pr(body: str | None = None) -> dict[str, object]:
    return {
        "number": 3822,
        "body": _body() if body is None else body,
        "head": {"sha": HEAD},
    }


def test_watchdog_targets_closed_children_and_distinct_open_governing_parent() -> None:
    targets = _node(
        "receiptTargets(inputs[0])",
        {
            "closingIssues": [3820, 3823],
            "governingIssue": 3821,
            "governingState": "open",
        },
    )
    assert targets == [3820, 3821, 3823]


def test_watchdog_deduplicates_closing_governor_and_preserves_issue_free_lane() -> None:
    closing_governor = _node(
        "receiptTargets(inputs[0])",
        {
            "closingIssues": [3821],
            "governingIssue": 3821,
            "governingState": "closed",
        },
    )
    issue_free = _node(
        "receiptTargets(inputs[0])",
        {"closingIssues": [], "governingIssue": None, "governingState": None},
    )
    assert closing_governor == [3821]
    assert issue_free == []


def test_watchdog_requires_pr_specific_receipt_not_generic_or_other_pr() -> None:
    comments = [
        {"body": "post-merge owner-doc check: no owner-doc change implied."},
        {"body": "post-merge owner-doc check: PR #1111; no owner-doc change implied."},
        {"body": "post-merge owner-doc watchdog: check not yet run for PR #3822."},
        {"body": "Expected: post-merge owner-doc check: PR #3822; <outcome>."},
    ]
    assert _node("hasReceiptForPr(inputs[0], inputs[1])", comments, 3822) is False
    comments.append(
        {"body": "post-merge owner-doc check: PR #3822; no owner-doc change implied."}
    )
    assert _node("hasReceiptForPr(inputs[0], inputs[1])", comments, 3822) is True


def test_watchdog_accepts_authenticated_receipt_for_original_or_neutral_body() -> None:
    original = _body()
    neutralized = original.replace("Fixes #3820", "Refs #3820").replace(
        "Closes #3823", "Refs #3823"
    ) + "Verified-Closing-Issues: #3820, #3823\n"
    comment = _authority_comment()

    for body in (original, neutralized):
        result = _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [comment],
            _pr(body),
            REPOSITORY,
        )
        assert result["closing_issues"] == [3820, 3823]
        assert result["repair_budget"]["policy_version"] == "v2"


def test_watchdog_rejects_forged_stale_or_conflicting_authority_receipts() -> None:
    untrusted = _authority_comment()
    untrusted["author_association"] = "NONE"
    stale_pr = _pr()
    stale_pr["head"] = {"sha": "b" * 40}
    repeated_attempts = [_authority_comment(), _authority_comment()]
    conflicting = _authority_comment()
    conflicting_body = conflicting["body"]
    assert isinstance(conflicting_body, str)
    conflicting["body"] = conflicting_body.replace(
        '"run_id":"vrun-authority"',
        '"run_id":"vrun-conflict"',
    )

    assert (
        _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [untrusted],
            _pr(),
            REPOSITORY,
        )
        is None
    )
    assert (
        _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [_authority_comment()],
            stale_pr,
            REPOSITORY,
        )
        is None
    )
    repeated = _node(
        "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
        repeated_attempts,
        _pr(),
        REPOSITORY,
    )
    assert repeated["closing_issues"] == [3820, 3823]
    assert _node(
        "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
        [_authority_comment(), conflicting],
        _pr(),
        REPOSITORY,
    ) is None


def test_watchdog_rejects_single_receipt_that_mismatches_live_authority() -> None:
    mismatched = _authority_comment()
    mismatched_body = mismatched["body"]
    assert isinstance(mismatched_body, str)
    mismatched["body"] = mismatched_body.replace(
        '"closing_issues":[3820,3823]',
        '"closing_issues":[3820,4999]',
    ).replace(
        '"authenticated_supporting_issues":[3820,3823]',
        '"authenticated_supporting_issues":[3820,4999]',
    ).replace(
        '"live_supporting_issues":[3820,3823]',
        '"live_supporting_issues":[3820,4999]',
    )

    assert (
        _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [mismatched],
            _pr(),
            REPOSITORY,
        )
        is None
    )


def test_watchdog_rejects_receipt_that_omits_live_supporting_authority() -> None:
    body = _body() + "Refs #4999\n"
    assert (
        _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [_authority_comment(body)],
            _pr(body),
            REPOSITORY,
        )
        is None
    )


def test_watchdog_governing_parser_matches_canonical_line_constraints() -> None:
    accepted = _node("resolveGoverningIssue(inputs[0])", "Governing-Issue: #3821\r\n")
    assert accepted == 3821
    for body in (
        "Governing-Issue : #3821\n",
        "Governing-Issue: #0\n",
        "Governing-Issue: #3821\nGoverning-Issue: #3822\n",
        "Governing-Issue: #3821\rRefs #3821",
        "Governing-Issue: #3821\u2028Refs #3821",
    ):
        assert _node("resolveGoverningIssue(inputs[0])", body) is None


def test_watchdog_production_path_uses_authority_receipt_and_pr_specific_targets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for fragment in (
        "const authorityReceipt = resolveAuthorityReceipt",
        'liveAuthority?.mode === "canonical"',
        "authorityReceipt.closing_issues",
        "governingState = governing.state",
        "const targets = receiptTargets",
        "if (targets.length === 0)",
        "hasReceiptForPr(prComments, prNumber)",
        "for (const issueNumber of targets)",
    ):
        assert fragment in text
