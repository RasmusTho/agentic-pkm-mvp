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


def _verified_merge_body_digest(body: str) -> str:
    canonical_body = body[:-1] if body.endswith("\n") else body
    return hashlib.sha256(canonical_body.encode()).hexdigest()


def _authority_comment(body: str | None = None) -> dict[str, object]:
    original = _body() if body is None else body
    neutralized = original.replace("Fixes #3820", "Refs #3820").replace(
        "Closes #3823", "Refs #3823"
    ) + "Verified-Closing-Issues: #3820, #3823\n"
    receipt = {
        "authenticated_supporting_issues": [3820, 3823],
        "body_sha256": _verified_merge_body_digest(original),
        "closing_issues": [3820, 3823],
        "contract": "verified_issue_set_merge_authority.v1",
        "governing_issue": 3821,
        "head_sha": HEAD,
        "live_supporting_issues": [3820, 3823],
        "neutralized_body_sha256": _verified_merge_body_digest(neutralized),
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


def _receipt_payload(comment: dict[str, object]) -> dict[str, object]:
    body = comment["body"]
    assert isinstance(body, str)
    return json.loads(body.split("```json\n", 1)[1].split("\n```", 1)[0])


def _phase_comment(
    authority_comment: dict[str, object],
    *,
    phase: str,
    merge_commit_sha: str | None,
) -> dict[str, object]:
    authority = _receipt_payload(authority_comment)
    reconciled = phase in {"reconciled", "restored"}
    receipt = {
        "authority_sha256": hashlib.sha256(
            json.dumps(authority, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "body_sha256": (
            authority["body_sha256"]
            if phase == "restored"
            else authority["neutralized_body_sha256"]
        ),
        "closed_issues": authority["closing_issues"] if reconciled else [],
        "contract": "verified_issue_set_merge_phase.v1",
        "head_sha": authority["head_sha"],
        "merge_commit_sha": merge_commit_sha,
        "phase": phase,
        "pr_number": authority["pr_number"],
        "reopened_unauthorized_issues": [],
        "repository": authority["repository"],
        "run_id": authority["run_id"],
    }
    return {
        "author_association": "OWNER",
        "body": (
            "verified issue-set merge phase:\n```json\n"
            + json.dumps(receipt, separators=(",", ":"), sort_keys=True)
            + "\n```"
        ),
    }


def _merged_pr(body: str) -> dict[str, object]:
    pr = _pr(body)
    pr.update(
        {
            "merge_commit_sha": "c" * 40,
            "merged": True,
            "merged_at": "2026-07-16T00:00:00Z",
            "state": "closed",
        }
    )
    return pr


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
        {"author_association": "OWNER", "body": "post-merge owner-doc check: no owner-doc change implied."},
        {"author_association": "MEMBER", "body": "post-merge owner-doc check: PR #1111; no owner-doc change implied."},
        {"author_association": "COLLABORATOR", "body": "post-merge owner-doc watchdog: check not yet run for PR #3822."},
        {"author_association": "OWNER", "body": "Expected: post-merge owner-doc check: PR #3822; <outcome>."},
        {"author_association": "NONE", "body": "post-merge owner-doc check: PR #3822; forged."},
    ]
    assert _node("hasReceiptForPr(inputs[0], inputs[1])", comments, 3822) is False
    comments.append(
        {"author_association": "COLLABORATOR", "body": "post-merge owner-doc check: PR #3822; no owner-doc change implied."}
    )
    assert _node("hasReceiptForPr(inputs[0], inputs[1])", comments, 3822) is True


def test_watchdog_untrusted_pr_specific_receipt_does_not_suppress_nudge() -> None:
    comments = [
        {
            "author_association": association,
            "body": "post-merge owner-doc check: PR #3822; forged suppression.",
        }
        for association in ("NONE", "CONTRIBUTOR", "FIRST_TIMER", None)
    ]

    assert _node("hasReceiptForPr(inputs[0], inputs[1])", comments, 3822) is False


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


def test_watchdog_body_digest_canonicalizes_only_one_terminal_lf() -> None:
    original = _body()
    comment = _authority_comment()
    assert original.endswith("\n")

    for equivalent_body in (original, original[:-1]):
        result = _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [comment],
            _pr(equivalent_body),
            REPOSITORY,
        )
        assert result["closing_issues"] == [3820, 3823]

    for changed_body in (
        original + "\n",
        original + " ",
        original + "substantive drift",
    ):
        assert (
            _node(
                "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
                [comment],
                _pr(changed_body),
                REPOSITORY,
            )
            is None
        )


def test_watchdog_accepts_legacy_authority_receipt_only_for_one_terminal_lf() -> None:
    original = _body()
    comment = _authority_comment()
    receipt = _receipt_payload(comment)
    receipt["body_sha256"] = hashlib.sha256(original.encode()).hexdigest()
    legacy_comment = {
        **comment,
        "body": "verified issue-set merge authority:\n```json\n"
        + json.dumps(receipt, separators=(",", ":"), sort_keys=True)
        + "\n```",
        "created_at": "2026-07-21T16:16:34Z",
        "updated_at": "2026-07-21T16:16:34Z",
    }

    assert _node(
        "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
        [legacy_comment],
        _pr(original[:-1]),
        REPOSITORY,
    ) == receipt
    for changed in (original, original[:-1] + " ", original[:-1] + "drift"):
        assert _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [legacy_comment], _pr(changed), REPOSITORY,
        ) is None
    assert _node(
        "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
        [legacy_comment], _pr(original + "\n"), REPOSITORY,
    ) == receipt

    for crlf_body in (original[:-1] + "\r", original[:-1].replace("Refs", "Refs\r", 1)):
        crlf_receipt = dict(receipt)
        crlf_receipt["body_sha256"] = hashlib.sha256(
            (crlf_body + "\n").encode()
        ).hexdigest()
        crlf_comment = {
            **legacy_comment,
            "body": "verified issue-set merge authority:\n```json\n"
            + json.dumps(crlf_receipt, separators=(",", ":"), sort_keys=True)
            + "\n```",
        }
        assert _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [crlf_comment], _pr(crlf_body), REPOSITORY,
        ) is None
    post_cutoff = {
        **legacy_comment,
        "created_at": "2026-07-21T16:32:11Z",
        "updated_at": "2026-07-21T16:32:11Z",
    }
    assert _node(
        "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
        [post_cutoff], _pr(original[:-1]), REPOSITORY,
    ) is None
    for noncanonical_timestamp in (
        "2026-07-21T16:16:34",
        "2026-07-21T18:16:34+02:00",
        "2026-07-21 16:16:34Z",
        "2026-07-21T16:16:34.000Z",
        "2026-02-30T16:16:34Z",
        "2025-02-29T16:16:34Z",
        "2026-13-01T16:16:34Z",
        "2026-07-00T16:16:34Z",
        "2026-07-21T24:16:34Z",
    ):
        malformed_provenance = {
            **legacy_comment,
            "updated_at": noncanonical_timestamp,
        }
        assert _node(
            "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
            [malformed_provenance], _pr(original[:-1]), REPOSITORY,
        ) is None
    valid_leap_day = {
        **legacy_comment,
        "created_at": "2024-02-29T16:16:34Z",
        "updated_at": "2024-02-29T16:16:34Z",
    }
    assert _node(
        "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
        [valid_leap_day], _pr(original[:-1]), REPOSITORY,
    ) == receipt

    double_lf = original + "\n"
    canonical_receipt = _receipt_payload(comment)
    canonical_receipt["body_sha256"] = _verified_merge_body_digest(double_lf)
    canonical_comment = {
        **comment,
        "body": "verified issue-set merge authority:\n```json\n"
        + json.dumps(canonical_receipt, separators=(",", ":"), sort_keys=True)
        + "\n```",
    }
    assert _node(
        "resolveAuthorityReceipt(inputs[0], inputs[1], inputs[2])",
        [canonical_comment], _pr(double_lf), REPOSITORY,
    ) == canonical_receipt

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


def test_watchdog_target_selection_recovers_raced_body_from_continuous_phase_chain() -> None:
    authority = _authority_comment()
    merge_sha = "c" * 40
    comments = [
        authority,
        _phase_comment(authority, phase="prepared", merge_commit_sha=None),
        _phase_comment(authority, phase="merged", merge_commit_sha=merge_sha),
    ]
    raced_body = "Governing-Issue: #4999\n\nFixes #4999\n"

    selected = _node(
        "selectWatchdogAuthority(inputs[0])",
        {
            "comments": comments,
            "expectedRepository": REPOSITORY,
            "linkedIssues": [4999],
            "livePr": _merged_pr(raced_body),
        },
    )

    assert selected == {
        "closing_issues": [3820, 3823],
        "governing_issue": 3821,
        "mode": "durable_receipt",
    }


def test_watchdog_target_selection_fails_closed_on_raced_body_without_phase_chain() -> None:
    raced_body = "Governing-Issue: #4999\n\nFixes #4999\n"
    selected = _node(
        "selectWatchdogAuthority(inputs[0])",
        {
            "comments": [_authority_comment()],
            "expectedRepository": REPOSITORY,
            "linkedIssues": [4999],
            "livePr": _merged_pr(raced_body),
        },
    )
    assert selected == {
        "closing_issues": [],
        "governing_issue": None,
        "mode": "trusted_receipt_invalid",
    }


def test_watchdog_target_selection_rejects_forged_stale_or_conflicting_phase_chain() -> None:
    authority = _authority_comment()
    prepared = _phase_comment(authority, phase="prepared", merge_commit_sha=None)
    merged = _phase_comment(
        authority, phase="merged", merge_commit_sha="c" * 40
    )

    forged = _phase_comment(
        authority, phase="merged", merge_commit_sha="c" * 40
    )
    forged_body = forged["body"]
    assert isinstance(forged_body, str)
    forged["body"] = forged_body.replace(
        '"authority_sha256":"', '"authority_sha256":"0'
    )

    stale = _phase_comment(
        authority, phase="merged", merge_commit_sha="d" * 40
    )

    reconciled = _phase_comment(
        authority, phase="reconciled", merge_commit_sha="c" * 40
    )
    conflicting = _phase_comment(
        authority, phase="reconciled", merge_commit_sha="c" * 40
    )
    conflicting_payload = _receipt_payload(conflicting)
    conflicting_payload["reopened_unauthorized_issues"] = [4999]
    conflicting["body"] = (
        "verified issue-set merge phase:\n```json\n"
        + json.dumps(conflicting_payload, separators=(",", ":"), sort_keys=True)
        + "\n```"
    )

    raced_body = "Governing-Issue: #4999\n\nFixes #4999\n"
    cases = (
        [authority, prepared, forged],
        [authority, prepared, stale],
        [authority, prepared, merged, reconciled, conflicting],
    )
    for comments in cases:
        selected = _node(
            "selectWatchdogAuthority(inputs[0])",
            {
                "comments": comments,
                "expectedRepository": REPOSITORY,
                "linkedIssues": [4999],
                "livePr": _merged_pr(raced_body),
            },
        )
        assert selected == {
            "closing_issues": [],
            "governing_issue": None,
            "mode": "trusted_receipt_invalid",
        }


def test_watchdog_target_selection_never_falls_back_for_forged_stale_or_conflicting_receipt() -> None:
    forged = _authority_comment()
    forged_body = forged["body"]
    assert isinstance(forged_body, str)
    forged["body"] = forged_body.replace(REPOSITORY, "attacker/example")

    stale = _authority_comment()
    stale_body = stale["body"]
    assert isinstance(stale_body, str)
    stale["body"] = stale_body.replace(HEAD, "b" * 40)

    conflicting = _authority_comment()
    conflicting_body = conflicting["body"]
    assert isinstance(conflicting_body, str)
    conflicting["body"] = conflicting_body.replace(
        '"run_id":"vrun-authority"',
        '"run_id":"vrun-conflict"',
    )

    authority = _authority_comment()
    raced_body = "Governing-Issue: #4999\n\nFixes #4999\n"
    cases = (
        [forged],
        [stale],
        [
            authority,
            _phase_comment(authority, phase="prepared", merge_commit_sha=None),
            _phase_comment(authority, phase="merged", merge_commit_sha="c" * 40),
            conflicting,
        ],
    )
    for comments in cases:
        selected = _node(
            "selectWatchdogAuthority(inputs[0])",
            {
                "comments": comments,
                "expectedRepository": REPOSITORY,
                "linkedIssues": [4999],
                "livePr": _merged_pr(raced_body),
            },
        )
        assert selected == {
            "closing_issues": [],
            "governing_issue": None,
            "mode": "trusted_receipt_invalid",
        }


def test_watchdog_target_selection_keeps_legacy_fallback_without_trusted_receipt() -> None:
    selected = _node(
        "selectWatchdogAuthority(inputs[0])",
        {
            "comments": [],
            "expectedRepository": REPOSITORY,
            "linkedIssues": [4999],
            "livePr": _pr("Governing-Issue: #4999\n\nFixes #4999\n"),
        },
    )
    assert selected == {
        "closing_issues": [4999],
        "governing_issue": 4999,
        "mode": "canonical_body",
    }


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
        "const selectedAuthority = selectWatchdogAuthority",
        'selectedAuthority.mode === "trusted_receipt_invalid"',
        'liveAuthority?.mode === "canonical"',
        "authorityReceipt.closing_issues",
        "governingState = governing.state",
        "const targets = receiptTargets",
        "if (targets.length === 0)",
        "hasReceiptForPr(prComments, prNumber)",
        "for (const issueNumber of targets)",
    ):
        assert fragment in text
