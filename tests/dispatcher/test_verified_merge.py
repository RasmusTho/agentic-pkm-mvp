from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.dispatcher.verification_contract import (
    IssueAuthority,
    MAX_CLOSING_ISSUES,
    has_neutralized_closing_marker,
    resolve_neutralized_issue_authority,
)
from app.dispatcher.verified_merge import (
    NEUTRALIZED_BODY_RESTORATION_CONTRACT,
    VERIFIED_MERGE_AUTHORITY_CONTRACT,
    build_verified_merge_phase,
    plan_issue_free_post_merge_reconciliation,
    classify_neutralized_body_state,
    plan_post_merge_reconciliation,
    prepare_verified_merge,
    resolve_neutralized_body_restoration,
    resolve_post_merge_governing_issue,
    resolve_post_merge_issue_authority,
    resolve_verified_merge_authority_receipt,
    resolve_verified_merge_phase,
    restored_body_matches_authority,
)
from tests.dispatcher.verified_merge_projection_helpers import (
    projection_convergence_comment,
    projection_phase_kwargs,
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


def _readiness(head_sha: str = HEAD) -> dict[str, object]:
    return {
        "contract": "verified_issue_set_merge_readiness.v1",
        "further_commits_anticipated": False,
        "head_sha": head_sha,
        "required_checks_green": True,
        "review_gate_resolved": True,
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


def _issue_free_reviewed_lane_context() -> dict[str, object]:
    return {
        "contract": "verification_closer_dispatch_context.v2",
        "run_id": "vrun-issue-free",
        "repository": REPOSITORY,
        "pr_number": 4904,
        "governing_issue": None,
        "closing_issues": [],
        "supporting_issues": [],
        "head_sha": HEAD,
        "repair_budget": {"policy_version": "v2", "mechanisms": []},
    }


def _issue_free_reviewed_lane_pr(body: str | None = None) -> dict[str, object]:
    return {
        **_pr(
            body
            or (
                "## Change Lane\n- [x] Docs authoring lane\n\n"
                "Final-Review-Rounds: 1\n"
            )
        ),
        "number": 4904,
    }


def test_prepare_verified_merge_accepts_issue_free_reviewed_lane() -> None:
    plan = prepare_verified_merge(
        context=_issue_free_reviewed_lane_context(),
        pr=_issue_free_reviewed_lane_pr(),
        live_closing_issues=[],
        merge_readiness=_readiness(),
    )

    receipt = plan["issue_free_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["pr_number"] == 4904
    assert receipt["head_sha"] == HEAD
    assert "issue-free reviewed lane receipt:" in plan["issue_free_receipt_comment"]


def test_issue_free_reviewed_lane_does_not_create_issue_authority() -> None:
    plan = prepare_verified_merge(
        context=_issue_free_reviewed_lane_context(),
        pr=_issue_free_reviewed_lane_pr(),
        live_closing_issues=[],
        merge_readiness=_readiness(),
    )

    assert "authority_receipt" not in plan
    assert "neutralized_body" not in plan
    assert plan["original_body"] == _issue_free_reviewed_lane_pr()["body"]


def test_issue_free_reviewed_lane_rejects_closing_issue_authority() -> None:
    context = _issue_free_reviewed_lane_context()
    context["closing_issues"] = [3820]

    with pytest.raises(ValueError, match="issue-free reviewed lane authority"):
        prepare_verified_merge(
            context=context,
            pr=_issue_free_reviewed_lane_pr("Fixes #3820\n\nFinal-Review-Rounds: 1\n"),
            live_closing_issues=[3820],
            merge_readiness=_readiness(),
        )


def test_issue_free_reviewed_lane_reopens_only_pr_attributed_closures() -> None:
    plan = plan_issue_free_post_merge_reconciliation(
        pr_number=4904,
        observed_closing_issues=[3820, 3823],
        issue_evidence=[
            {"number": 3820, "state": "closed", "closed_by_pull_requests": [4904]},
            {"number": 3823, "state": "closed", "closed_by_pull_requests": [9999]},
        ],
    )

    assert plan == {
        "reopen_unauthorized": [3820],
        "unresolved_unauthorized_closures": [3823],
    }


def test_issue_free_post_merge_reconciliation_cli_uses_production_planner(
    tmp_path: Path,
) -> None:
    observed_path = tmp_path / "observed.json"
    evidence_path = tmp_path / "evidence.json"
    output_path = tmp_path / "plan.json"
    observed_path.write_text("[3820]", encoding="utf-8")
    evidence_path.write_text(
        json.dumps(
            [{"number": 3820, "state": "closed", "closed_by_pull_requests": [4904]}]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.plan_issue_free_post_merge_reconciliation",
            "--pr-number",
            "4904",
            "--observed-closing-json",
            str(observed_path),
            "--issue-evidence-json",
            str(evidence_path),
            "--output-json",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "reopen_unauthorized": [3820],
        "unresolved_unauthorized_closures": [],
    }


def _trusted_comment(body: str) -> dict[str, object]:
    return {"author_association": "COLLABORATOR", "body": body}


def _legacy_trusted_comment(body: str) -> dict[str, object]:
    return {
        "author_association": "COLLABORATOR",
        "body": body,
        "created_at": "2026-07-21T16:16:34Z",
        "updated_at": "2026-07-21T16:16:34Z",
    }


def test_prepare_verified_merge_neutralizes_closers_and_preserves_authority() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[
            {"number": 3823, "repository": REPOSITORY},
            {"number": 3820, "repository": REPOSITORY},
        ],
        merge_readiness=_readiness(),
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
        _body()[:-1].encode("utf-8")
    ).hexdigest()
    assert plan["authority_receipt_comment"].startswith(
        "verified issue-set merge authority:\n```json\n"
    )
    assert "Fixes" not in plan["fixed_commit_title"]
    assert "Closes" not in plan["fixed_commit_message"]


def test_verified_merge_body_digest_canonicalizes_terminal_newline() -> None:
    with_terminal_lf = _body()
    without_terminal_lf = with_terminal_lf[:-1]

    with_lf_plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(with_terminal_lf),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    without_lf_plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(without_terminal_lf),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )

    assert (
        with_lf_plan["authority_receipt"]["body_sha256"]
        == without_lf_plan["authority_receipt"]["body_sha256"]
    )
    assert (
        with_lf_plan["authority_receipt"]["neutralized_body_sha256"]
        == without_lf_plan["authority_receipt"]["neutralized_body_sha256"]
    )


def test_prepared_phase_accepts_github_terminal_newline_canonicalization() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutralized_body = str(plan["neutralized_body"])
    assert neutralized_body.endswith("\n")
    neutralized_without_terminal_lf = neutralized_body[:-1]
    neutral_pr = _pr(neutralized_without_terminal_lf)

    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
        **projection_phase_kwargs(authority, neutral_pr),
    )

    assert prepared["phase_receipt"]["head_sha"] == HEAD
    assert prepared["phase_receipt"]["closed_issues"] == []


def test_prepared_phase_rejects_substantive_body_drift_after_canonicalization() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))

    with pytest.raises(ValueError, match="is malformed"):
        build_verified_merge_phase(
            authority_receipt=authority,
            phase="prepared",
            pr=_pr(str(plan["neutralized_body"]) + "substantive drift"),
            **projection_phase_kwargs(authority, neutral_pr),
        )


def _legacy_authority_fixture() -> tuple[dict[str, object], dict[str, object], str, str]:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = copy.deepcopy(plan["authority_receipt"])
    assert isinstance(authority, dict)
    original = str(plan["original_body"])
    neutralized = str(plan["neutralized_body"])
    authority["body_sha256"] = hashlib.sha256(original.encode("utf-8")).hexdigest()
    authority["neutralized_body_sha256"] = hashlib.sha256(
        neutralized.encode("utf-8")
    ).hexdigest()
    return authority, _pr(neutralized[:-1]), original[:-1], neutralized[:-1]


def test_legacy_authority_receipt_accepts_only_single_terminal_lf_digest_difference() -> None:
    authority, neutral_pr, _, neutralized = _legacy_authority_fixture()
    comment = _legacy_trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(authority, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )

    assert resolve_verified_merge_authority_receipt(
        [comment], pr=neutral_pr, repository=REPOSITORY
    ) == authority

    for body in (neutralized + "\n", neutralized + " ", neutralized + "\r\n", neutralized + "drift"):
        assert resolve_verified_merge_authority_receipt(
            [comment], pr=_pr(body), repository=REPOSITORY
        ) is None
    for mutated in (
        {**neutral_pr, "head": {"sha": "b" * 40}},
        {**neutral_pr, "number": 9999},
    ):
        assert resolve_verified_merge_authority_receipt(
            [comment], pr=mutated, repository=REPOSITORY
        ) is None
    forged = {**comment, "author_association": "NONE"}
    assert resolve_verified_merge_authority_receipt(
        [forged], pr=neutral_pr, repository=REPOSITORY
    ) is None
    post_cutoff = {
        **comment,
        "created_at": "2026-07-21T16:32:11Z",
        "updated_at": "2026-07-21T16:32:11Z",
    }
    assert resolve_verified_merge_authority_receipt(
        [post_cutoff], pr=neutral_pr, repository=REPOSITORY
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
            **comment,
            "updated_at": noncanonical_timestamp,
        }
        assert resolve_verified_merge_authority_receipt(
            [malformed_provenance], pr=neutral_pr, repository=REPOSITORY
        ) is None
    valid_leap_day = {
        **comment,
        "created_at": "2024-02-29T16:16:34Z",
        "updated_at": "2024-02-29T16:16:34Z",
    }
    assert resolve_verified_merge_authority_receipt(
        [valid_leap_day], pr=neutral_pr, repository=REPOSITORY
    ) == authority

    crlf_body = neutralized + "\r"
    crlf_authority = copy.deepcopy(authority)
    crlf_authority["neutralized_body_sha256"] = hashlib.sha256(
        (crlf_body + "\n").encode()
    ).hexdigest()
    crlf_comment = _legacy_trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(crlf_authority, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )
    assert resolve_verified_merge_authority_receipt(
        [crlf_comment], pr=_pr(crlf_body), repository=REPOSITORY
    ) is None


def test_legacy_authority_receipt_builds_prepared_phase_without_rebinding() -> None:
    authority, neutral_pr, _, neutralized = _legacy_authority_fixture()
    authority_comment = _legacy_trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(authority, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        authority_comment=authority_comment,
        phase="prepared",
        pr=neutral_pr,
        **projection_phase_kwargs(
            authority,
            neutral_pr,
            authority_comment=authority_comment,
        ),
    )
    assert prepared["phase_receipt"]["authority_sha256"] == hashlib.sha256(
        json.dumps(authority, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert prepared["phase_receipt"]["body_sha256"] == authority["neutralized_body_sha256"]
    assert prepared["phase_receipt"]["run_id"] == authority["run_id"]
    assert prepared["phase_receipt"]["closed_issues"] == []

    post_cutoff = {
        **authority_comment,
        "created_at": "2026-07-21T16:32:11Z",
        "updated_at": "2026-07-21T16:32:11Z",
    }
    with pytest.raises(ValueError, match="is malformed"):
        build_verified_merge_phase(
            authority_receipt=authority,
            authority_comment=post_cutoff,
            phase="prepared",
            pr=neutral_pr,
            **projection_phase_kwargs(
                authority,
                neutral_pr,
                authority_comment=authority_comment,
            ),
        )

    for cr_body in (neutralized + "\r", neutralized.replace("Refs", "Refs\r", 1)):
        cr_authority = copy.deepcopy(authority)
        cr_authority["neutralized_body_sha256"] = hashlib.sha256(
            (cr_body + "\n").encode()
        ).hexdigest()
        cr_comment = _legacy_trusted_comment(
            "verified issue-set merge authority:\n```json\n"
            + json.dumps(cr_authority, sort_keys=True, separators=(",", ":"))
            + "\n```"
        )
        with pytest.raises(ValueError, match="is malformed"):
            build_verified_merge_phase(
                authority_receipt=cr_authority,
                authority_comment=cr_comment,
                phase="prepared",
                pr=_pr(cr_body),
                **projection_phase_kwargs(
                    authority,
                    neutral_pr,
                    authority_comment=authority_comment,
                ),
            )


def test_legacy_authority_receipt_preserves_continuous_phase_recovery() -> None:
    authority, neutral_pr, original, _ = _legacy_authority_fixture()
    authority_comment = _legacy_trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(authority, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        authority_comment=authority_comment,
        phase="prepared",
        pr=neutral_pr,
        **projection_phase_kwargs(
            authority,
            neutral_pr,
            authority_comment=authority_comment,
        ),
    )
    convergence_kwargs = projection_phase_kwargs(
        authority,
        neutral_pr,
        authority_comment=authority_comment,
    )
    merged_pr = {
        **neutral_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-21T10:00:00Z",
        "merge_commit_sha": "b" * 40,
    }
    merged = build_verified_merge_phase(
        authority_receipt=authority,
        authority_comment=authority_comment,
        phase="merged",
        pr=merged_pr,
        **convergence_kwargs,
    )
    reconciled = build_verified_merge_phase(
        authority_receipt=authority,
        authority_comment=authority_comment,
        phase="reconciled",
        pr=merged_pr,
        closed_issues=[3820, 3823],
        **convergence_kwargs,
    )
    restored_pr = {**merged_pr, "body": original}
    restored = build_verified_merge_phase(
        authority_receipt=authority,
        authority_comment=authority_comment,
        phase="restored",
        pr=restored_pr,
        closed_issues=[3820, 3823],
        **convergence_kwargs,
    )
    comments = [
        _trusted_comment(str(item["phase_receipt_comment"]))
        for item in (prepared, merged, reconciled, restored)
    ]
    comments.insert(0, projection_convergence_comment(convergence_kwargs))
    comments.insert(0, authority_comment)

    assert resolve_verified_merge_phase(
        comments, authority_receipt=authority, pr=restored_pr
    ) == restored["phase_receipt"]
    assert resolve_verified_merge_phase(
        comments[:2] + comments[3:], authority_receipt=authority, pr=restored_pr
    ) is None


def test_canonical_authority_receipt_preserves_unchanged_double_terminal_lf() -> None:
    original = _body() + "\n"
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(original),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))
    restored_pr = {
        **_pr(original),
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-21T17:00:00Z",
        "merge_commit_sha": "b" * 40,
    }

    restored = build_verified_merge_phase(
        authority_receipt=authority,
        phase="restored",
        pr=restored_pr,
        closed_issues=[3820, 3823],
        **projection_phase_kwargs(authority, neutral_pr),
    )

    assert restored["phase_receipt"]["body_sha256"] == authority["body_sha256"]


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
            merge_readiness=_readiness(),
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
            merge_readiness=_readiness(),
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
        merge_readiness=_readiness(),
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
            merge_readiness=_readiness(),
        )


def test_prepare_verified_merge_cli_uses_production_planner(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    pr_path = tmp_path / "pr.json"
    closing_path = tmp_path / "closing.json"
    readiness_path = tmp_path / "readiness.json"
    output_path = tmp_path / "plan.json"
    context_path.write_text(json.dumps(_context()), encoding="utf-8")
    pr_path.write_text(json.dumps(_pr()), encoding="utf-8")
    closing_path.write_text(json.dumps([3820, 3823]), encoding="utf-8")
    readiness_path.write_text(json.dumps(_readiness()), encoding="utf-8")

    def _run(readiness: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
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
                "--merge-readiness-json",
                str(readiness),
                "--output-json",
                str(output_path),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    completed = _run(readiness_path)

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(output_path.read_text(encoding="utf-8"))
    assert plan["authority_receipt"]["closing_issues"] == [3820, 3823]
    assert "Refs #3820" in plan["neutralized_body"]

    unmet_path = tmp_path / "unmet-readiness.json"
    unmet = _readiness()
    unmet["further_commits_anticipated"] = True
    unmet_path.write_text(json.dumps(unmet), encoding="utf-8")

    refused = _run(unmet_path)

    assert refused.returncode != 0
    assert "neutralization precondition is unmet" in refused.stderr


def test_authority_receipt_resolver_rejects_forged_stale_and_conflicting_comments() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    original_comment = _trusted_comment(str(plan["authority_receipt_comment"]))
    neutral_pr = _pr(str(plan["neutralized_body"]))

    resolved = resolve_verified_merge_authority_receipt(
        [original_comment],
        pr=neutral_pr,
        repository=REPOSITORY,
        expected_run_id="vrun-authority",
        expected_repair_budget=_context()["repair_budget"],
    )
    assert resolved == plan["authority_receipt"]

    assert (
        resolve_verified_merge_authority_receipt(
            [original_comment],
            pr=neutral_pr,
            repository=REPOSITORY,
            expected_run_id="vrun-authority",
            expected_repair_budget={"policy_version": "v2", "mechanisms": []},
        )
        is None
    )

    forged = dict(original_comment)
    forged["author_association"] = "NONE"
    assert (
        resolve_verified_merge_authority_receipt(
            [forged], pr=neutral_pr, repository=REPOSITORY
        )
        is None
    )
    assert (
        resolve_post_merge_issue_authority(
            [original_comment], pr=neutral_pr, repository=REPOSITORY
        )
        == IssueAuthority(
            governing_issue=3821,
            closing_issues=(3820, 3823),
            supporting_issues=(3820, 3823, 3900),
        )
    )
    assert (
        resolve_post_merge_issue_authority(
            [forged], pr=neutral_pr, repository=REPOSITORY
        )
        is None
    )
    assert (
        resolve_post_merge_governing_issue(
            [forged], pr=neutral_pr, repository=REPOSITORY
        )
        is None
    )
    assert (
        resolve_verified_merge_authority_receipt(
            [original_comment],
            pr={**neutral_pr, "head": {"sha": "b" * 40}},
            repository=REPOSITORY,
        )
        is None
    )
    with pytest.raises(ValueError, match="trusted verified merge authority"):
        resolve_post_merge_issue_authority(
            [original_comment],
            pr={**neutral_pr, "head": {"sha": "b" * 40}},
            repository=REPOSITORY,
        )
    conflicting_receipt = copy.deepcopy(plan["authority_receipt"])
    assert isinstance(conflicting_receipt, dict)
    conflicting_receipt["repair_budget"] = {
        "policy_version": "v2",
        "mechanisms": [],
    }
    conflicting_comment = _trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(conflicting_receipt, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )
    assert (
        resolve_verified_merge_authority_receipt(
            [original_comment, conflicting_comment],
            pr=neutral_pr,
            repository=REPOSITORY,
        )
        is None
    )
    with pytest.raises(ValueError, match="trusted verified merge authority"):
        resolve_post_merge_issue_authority(
            [original_comment, conflicting_comment],
            pr=neutral_pr,
            repository=REPOSITORY,
        )


@pytest.mark.parametrize("live_supporting", [[3820, 3823], [3820, 3823, 3900, 4999]])
def test_authority_receipt_requires_exact_live_supporting_body_authority(
    live_supporting: list[int],
) -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    receipt = copy.deepcopy(plan["authority_receipt"])
    assert isinstance(receipt, dict)
    receipt["live_supporting_issues"] = live_supporting
    comment = _trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )

    assert (
        resolve_verified_merge_authority_receipt(
            [comment],
            pr=_pr(str(plan["neutralized_body"])),
            repository=REPOSITORY,
        )
        is None
    )


def test_merge_phase_receipts_form_continuous_idempotent_recovery_chain() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
        **projection_phase_kwargs(authority, neutral_pr),
    )
    convergence_kwargs = projection_phase_kwargs(authority, neutral_pr)
    merged_pr = {
        **neutral_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-16T10:00:00Z",
        "merge_commit_sha": "b" * 40,
    }
    merged = build_verified_merge_phase(
        authority_receipt=authority,
        phase="merged",
        pr=merged_pr,
        **convergence_kwargs,
    )
    reconciled = build_verified_merge_phase(
        authority_receipt=authority,
        phase="reconciled",
        pr=merged_pr,
        closed_issues=[3820, 3823],
        reopened_unauthorized_issues=[4999],
        **convergence_kwargs,
    )
    restored_pr = {**merged_pr, "body": plan["original_body"]}
    restored = build_verified_merge_phase(
        authority_receipt=authority,
        phase="restored",
        pr=restored_pr,
        closed_issues=[3820, 3823],
        reopened_unauthorized_issues=[4999],
        **convergence_kwargs,
    )
    comments = [
        projection_convergence_comment(convergence_kwargs),
        *[
            _trusted_comment(str(item["phase_receipt_comment"]))
            for item in (prepared, prepared, merged, reconciled, restored)
        ],
    ]

    phase = resolve_verified_merge_phase(
        comments,
        authority_receipt=authority,
        pr=restored_pr,
    )

    assert phase == restored["phase_receipt"]
    assert phase["closed_issues"] == [3820, 3823]
    assert phase["reopened_unauthorized_issues"] == [4999]

    inconsistent_restored = build_verified_merge_phase(
        authority_receipt=authority,
        phase="restored",
        pr=restored_pr,
        closed_issues=[3820, 3823],
        **convergence_kwargs,
    )
    assert (
        resolve_verified_merge_phase(
            comments[:-1]
            + [_trusted_comment(str(inconsistent_restored["phase_receipt_comment"]))],
            authority_receipt=authority,
            pr=restored_pr,
        )
        is None
    )


def test_current_phase_ledger_rejects_null_or_discontinuous_projection_digest() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))
    convergence_kwargs = projection_phase_kwargs(authority, neutral_pr)
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
        **convergence_kwargs,
    )["phase_receipt"]
    merged_pr = {
        **neutral_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-16T10:00:00Z",
        "merge_commit_sha": "b" * 40,
    }
    merged = build_verified_merge_phase(
        authority_receipt=authority,
        phase="merged",
        pr=merged_pr,
        **convergence_kwargs,
    )["phase_receipt"]
    assert isinstance(prepared, dict)
    assert isinstance(merged, dict)

    def comment(receipt: dict[str, object]) -> dict[str, object]:
        return _trusted_comment(
            "verified issue-set merge phase:\n```json\n"
            + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            + "\n```"
        )

    durable_convergence_comment = projection_convergence_comment(
        convergence_kwargs
    )
    assert resolve_verified_merge_phase(
        [durable_convergence_comment, comment(prepared), comment(merged)],
        authority_receipt=authority,
        pr=merged_pr,
    ) == merged

    malformed_reconciled = copy.deepcopy(merged)
    malformed_reconciled["phase"] = "reconciled"
    assert (
        resolve_verified_merge_phase(
            [
                durable_convergence_comment,
                comment(prepared),
                comment(merged),
                comment(malformed_reconciled),
            ],
            authority_receipt=authority,
            pr=merged_pr,
        )
        is None
    )

    for phase_receipt in (prepared, merged):
        null_projection = copy.deepcopy(phase_receipt)
        null_projection["projection_convergence_sha256"] = None
        null_projection["final_projection_observation_sha256"] = None
        comments = [
            durable_convergence_comment,
            comment(prepared),
            comment(merged),
        ]
        comments[1 if phase_receipt is prepared else 2] = comment(
            null_projection
        )
        assert (
            resolve_verified_merge_phase(
                comments,
                authority_receipt=authority,
                pr=merged_pr,
            )
            is None
        )

    discontinuous = copy.deepcopy(merged)
    discontinuous["projection_convergence_sha256"] = "f" * 64
    assert (
        resolve_verified_merge_phase(
            [
                durable_convergence_comment,
                comment(prepared),
                comment(discontinuous),
            ],
            authority_receipt=authority,
            pr=merged_pr,
        )
        is None
    )

    for field, forged in (
        ("repository", "foreign/example"),
        ("run_id", "forged-run"),
        ("pr_number", 4999),
        ("head_sha", "f" * 40),
    ):
        mismatched_identity = copy.deepcopy(prepared)
        mismatched_identity[field] = forged
        assert (
            resolve_verified_merge_phase(
                [
                    durable_convergence_comment,
                    comment(mismatched_identity),
                    comment(merged),
                ],
                authority_receipt=authority,
                pr=merged_pr,
            )
            is None
        )

    duplicate_convergence_marker = dict(durable_convergence_comment)
    duplicate_convergence_body = duplicate_convergence_marker["body"]
    assert isinstance(duplicate_convergence_body, str)
    duplicate_convergence_marker["body"] = (
        duplicate_convergence_body
        + "\nverified merge closing projection convergence:"
    )
    duplicate_phase_marker = comment(prepared)
    duplicate_phase_body = duplicate_phase_marker["body"]
    assert isinstance(duplicate_phase_body, str)
    duplicate_phase_marker["body"] = (
        duplicate_phase_body + "\nverified issue-set merge phase:"
    )
    for malformed_comment in (
        duplicate_convergence_marker,
        duplicate_phase_marker,
    ):
        assert (
            resolve_verified_merge_phase(
                [
                    malformed_comment
                    if malformed_comment is duplicate_convergence_marker
                    else durable_convergence_comment,
                    malformed_comment
                    if malformed_comment is duplicate_phase_marker
                    else comment(prepared),
                    comment(merged),
                ],
                authority_receipt=authority,
                pr=merged_pr,
            )
            is None
        )

    embedded_convergence_marker = dict(durable_convergence_comment)
    embedded_convergence_body = embedded_convergence_marker["body"]
    assert isinstance(embedded_convergence_body, str)
    embedded_convergence_marker["body"] = (
        embedded_convergence_body
        + "\n```json\n"
        + '{"audit":"verified merge closing projection convergence:"}'
        + "\n```"
    )
    embedded_phase_marker = comment(prepared)
    embedded_phase_body = embedded_phase_marker["body"]
    assert isinstance(embedded_phase_body, str)
    embedded_phase_marker["body"] = (
        embedded_phase_body
        + "\n```json\n"
        + '{"audit":"verified issue-set merge phase:"}'
        + "\n```"
    )
    for harmless_comment in (
        embedded_convergence_marker,
        embedded_phase_marker,
    ):
        assert (
            resolve_verified_merge_phase(
                [
                    harmless_comment
                    if harmless_comment is embedded_convergence_marker
                    else durable_convergence_comment,
                    harmless_comment
                    if harmless_comment is embedded_phase_marker
                    else comment(prepared),
                    comment(merged),
                ],
                authority_receipt=authority,
                pr=merged_pr,
            )
            == merged
        )


def test_explicit_legacy_phase_field_set_remains_continuous() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))
    convergence_kwargs = projection_phase_kwargs(authority, neutral_pr)
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
        **convergence_kwargs,
    )["phase_receipt"]
    merged_pr = {
        **neutral_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-16T10:00:00Z",
        "merge_commit_sha": "b" * 40,
    }
    merged = build_verified_merge_phase(
        authority_receipt=authority,
        phase="merged",
        pr=merged_pr,
        **convergence_kwargs,
    )["phase_receipt"]
    current_prepared = copy.deepcopy(prepared)
    for receipt in (prepared, merged):
        assert isinstance(receipt, dict)
        receipt.pop("projection_convergence_sha256")
        receipt.pop("final_projection_observation_sha256")

    comments = [
        _trusted_comment(
            "verified issue-set merge phase:\n```json\n"
            + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            + "\n```"
        )
        for receipt in (prepared, merged)
    ]
    assert resolve_verified_merge_phase(
        comments,
        authority_receipt=authority,
        pr=merged_pr,
    ) == merged

    current_prepared.pop("final_projection_observation_sha256")
    malformed_current_comment = _trusted_comment(
        "verified issue-set merge phase:\n```json\n"
        + json.dumps(
            current_prepared, sort_keys=True, separators=(",", ":")
        )
        + "\n```"
    )
    assert (
        resolve_verified_merge_phase(
            [malformed_current_comment, *comments],
            authority_receipt=authority,
            pr=merged_pr,
        )
        is None
    )


def test_merge_phase_resolver_stops_at_premerge_phase_after_merge_crash() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))
    convergence_kwargs = projection_phase_kwargs(authority, neutral_pr)
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
        **convergence_kwargs,
    )
    crashed_pr = {
        **neutral_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-16T10:00:00Z",
        "merge_commit_sha": "b" * 40,
    }

    phase = resolve_verified_merge_phase(
        [
            projection_convergence_comment(convergence_kwargs),
            _trusted_comment(str(prepared["phase_receipt_comment"])),
        ],
        authority_receipt=authority,
        pr=crashed_pr,
    )

    assert phase == prepared["phase_receipt"]


def test_merged_body_race_recovers_only_from_trusted_authority_bound_phase() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))
    convergence_kwargs = projection_phase_kwargs(authority, neutral_pr)
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
        **convergence_kwargs,
    )
    raced_pr = {
        **neutral_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-16T10:00:00Z",
        "merge_commit_sha": "b" * 40,
        "body": "Governing-Issue: #3821\n\nRefs #3820\nFixes #4999",
    }
    authority_comment = _trusted_comment(str(plan["authority_receipt_comment"]))
    convergence_comment = projection_convergence_comment(convergence_kwargs)
    prepared_comment = _trusted_comment(str(prepared["phase_receipt_comment"]))

    resolved = resolve_verified_merge_authority_receipt(
        [authority_comment, convergence_comment, prepared_comment],
        pr=raced_pr,
        repository=REPOSITORY,
        expected_run_id="vrun-authority",
        expected_repair_budget=_context()["repair_budget"],
    )

    assert resolved == authority
    assert resolve_verified_merge_phase(
        [convergence_comment, prepared_comment],
        authority_receipt=authority,
        pr=raced_pr,
        allow_merged_body_drift=True,
    ) == prepared["phase_receipt"]
    assert (
        resolve_verified_merge_authority_receipt(
            [authority_comment, convergence_comment, prepared_comment],
            pr={**raced_pr, "state": "open", "merged": False, "merged_at": None},
            repository=REPOSITORY,
        )
        is None
    )


def test_merged_body_race_rejects_forged_stale_and_conflicting_evidence() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority = plan["authority_receipt"]
    assert isinstance(authority, dict)
    neutral_pr = _pr(str(plan["neutralized_body"]))
    merged_neutral = {
        **neutral_pr,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-16T10:00:00Z",
        "merge_commit_sha": "b" * 40,
    }
    raced_pr = {
        **merged_neutral,
        "body": "Governing-Issue: #3821\n\nRefs #3820\nFixes #4999",
    }
    prepared = build_verified_merge_phase(
        authority_receipt=authority,
        phase="prepared",
        pr=neutral_pr,
        **projection_phase_kwargs(authority, neutral_pr),
    )
    convergence_kwargs = projection_phase_kwargs(authority, neutral_pr)
    merged = build_verified_merge_phase(
        authority_receipt=authority,
        phase="merged",
        pr=merged_neutral,
        **convergence_kwargs,
    )
    reconciled_a = build_verified_merge_phase(
        authority_receipt=authority,
        phase="reconciled",
        pr=merged_neutral,
        closed_issues=[3820, 3823],
        reopened_unauthorized_issues=[4999],
        **convergence_kwargs,
    )
    reconciled_b = build_verified_merge_phase(
        authority_receipt=authority,
        phase="reconciled",
        pr=merged_neutral,
        closed_issues=[3820, 3823],
        reopened_unauthorized_issues=[5000],
        **convergence_kwargs,
    )
    authority_comment = _trusted_comment(str(plan["authority_receipt_comment"]))
    prepared_comment = _trusted_comment(str(prepared["phase_receipt_comment"]))

    def comment_for(receipt: dict[str, object]) -> dict[str, object]:
        return _trusted_comment(
            "verified issue-set merge phase:\n```json\n"
            + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            + "\n```"
        )

    forged_authority = {**authority_comment, "author_association": "NONE"}
    forged_phase = {**prepared_comment, "author_association": "NONE"}
    stale_phase = copy.deepcopy(prepared["phase_receipt"])
    assert isinstance(stale_phase, dict)
    stale_phase["head_sha"] = "c" * 40
    conflicting_authority = copy.deepcopy(authority)
    conflicting_authority["repair_budget"] = {
        "policy_version": "v2",
        "mechanisms": [],
    }
    conflicting_authority_comment = _trusted_comment(
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(
            conflicting_authority, sort_keys=True, separators=(",", ":")
        )
        + "\n```"
    )
    raced_context = _context()
    raced_context["closing_issues"] = [4999]
    raced_context["supporting_issues"] = [4999]
    body_matching_conflict = prepare_verified_merge(
        context=raced_context,
        pr=_pr(str(raced_pr["body"])),
        live_closing_issues=[4999],
        merge_readiness=_readiness(),
    )
    body_matching_conflict_comment = _trusted_comment(
        str(body_matching_conflict["authority_receipt_comment"])
    )
    cases = [
        [authority_comment],
        [forged_authority, prepared_comment],
        [authority_comment, forged_phase],
        [authority_comment, comment_for(stale_phase)],
        [authority_comment, conflicting_authority_comment, prepared_comment],
        [authority_comment, prepared_comment, body_matching_conflict_comment],
        [
            authority_comment,
            prepared_comment,
            _trusted_comment(str(merged["phase_receipt_comment"])),
            _trusted_comment(str(reconciled_a["phase_receipt_comment"])),
            _trusted_comment(str(reconciled_b["phase_receipt_comment"])),
        ],
    ]

    for comments in cases:
        assert (
            resolve_verified_merge_authority_receipt(
                comments,
                pr=raced_pr,
                repository=REPOSITORY,
                expected_run_id="vrun-authority",
            )
            is None
        )
    assert (
        resolve_verified_merge_authority_receipt(
            [authority_comment, conflicting_authority_comment, prepared_comment],
            pr=raced_pr,
            repository=REPOSITORY,
            expected_run_id="vrun-authority",
            expected_repair_budget=_context()["repair_budget"],
        )
        is None
    )


def test_merge_phase_cli_uses_production_phase_builder(tmp_path: Path) -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    merged_pr = {
        **_pr(str(plan["original_body"])),
        "state": "closed",
        "merged": True,
        "merged_at": "2026-07-16T10:00:00Z",
        "merge_commit_sha": "b" * 40,
    }
    authority_path = tmp_path / "authority.json"
    pr_path = tmp_path / "pr.json"
    closed_path = tmp_path / "closed.json"
    convergence_path = tmp_path / "convergence.json"
    comments_path = tmp_path / "comments.json"
    output_path = tmp_path / "phase.json"
    authority_path.write_text(
        json.dumps(plan["authority_receipt"]), encoding="utf-8"
    )
    pr_path.write_text(json.dumps(merged_pr), encoding="utf-8")
    closed_path.write_text(json.dumps([3820, 3823]), encoding="utf-8")
    convergence = projection_phase_kwargs(
        plan["authority_receipt"],
        _pr(str(plan["neutralized_body"])),
    )["projection_convergence_receipt"]
    convergence_path.write_text(json.dumps(convergence), encoding="utf-8")
    comments_path.write_text(
        json.dumps(
            [
                {
                    "author_association": "OWNER",
                    "body": (
                        "verified merge closing projection convergence:\n"
                        "```json\n"
                        + json.dumps(
                            convergence, sort_keys=True, separators=(",", ":")
                        )
                        + "\n```"
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.build_verified_issue_set_merge_phase",
            "--authority-json",
            str(authority_path),
            "--phase",
            "restored",
            "--projection-convergence-json",
            str(convergence_path),
            "--comments-json",
            str(comments_path),
            "--pr-json",
            str(pr_path),
            "--closed-issues-json",
            str(closed_path),
            "--output-json",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["phase_receipt"]["phase"] == "restored"
    assert result["phase_receipt"]["closed_issues"] == [3820, 3823]


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


NEXT_HEAD = "b" * 40


def _authority_comment(receipt: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    return _trusted_comment(
        "verified issue-set merge authority:\n```json\n" + payload + "\n```"
    )


@pytest.mark.parametrize(
    ("field", "unmet"),
    [
        ("further_commits_anticipated", True),
        ("required_checks_green", False),
        ("review_gate_resolved", False),
    ],
)
def test_neutralization_is_refused_until_the_head_is_final(
    field: str, unmet: bool
) -> None:
    readiness = _readiness()
    readiness[field] = unmet

    with pytest.raises(ValueError, match="neutralization precondition is unmet"):
        prepare_verified_merge(
            context=_context(),
            pr=_pr(),
            live_closing_issues=[3820, 3823],
            merge_readiness=readiness,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda readiness: readiness.update(head_sha=NEXT_HEAD),
            id="readiness-bound-to-another-head",
        ),
        pytest.param(
            lambda readiness: readiness.update(contract="unknown.v1"),
            id="unknown-contract",
        ),
        pytest.param(
            lambda readiness: readiness.update(further_commits_anticipated="false"),
            id="non-boolean-assertion",
        ),
        pytest.param(
            lambda readiness: readiness.pop("review_gate_resolved"),
            id="missing-assertion",
        ),
        pytest.param(
            lambda readiness: readiness.update(merged_by="agent"),
            id="unknown-field",
        ),
    ],
)
def test_neutralization_readiness_fails_closed_on_malformed_statements(
    mutate,
) -> None:
    readiness = _readiness()
    mutate(readiness)

    with pytest.raises(ValueError, match="readiness is malformed"):
        prepare_verified_merge(
            context=_context(),
            pr=_pr(),
            live_closing_issues=[3820, 3823],
            merge_readiness=readiness,
        )


def test_neutralized_body_outliving_its_head_is_surfaced_as_restorable() -> None:
    """Reproduce PR #4021: neutralize at head A, then push head B.

    There, the body stayed neutralized across six later heads for about seven
    hours because nothing detected that it had outlived the merge attempt that
    justified it, so `pr-contract` failed deterministically on every head.
    """

    original_body = _body()
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(original_body),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority_receipt = plan["authority_receipt"]
    assert isinstance(authority_receipt, dict)
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    neutralized_body = str(plan["neutralized_body"])
    head_a_pr = _pr(neutralized_body)

    # Inside the merge attempt the receipt covers the live head; nothing to restore.
    assert (
        resolve_verified_merge_authority_receipt(
            comments, pr=head_a_pr, repository=REPOSITORY
        )
        == authority_receipt
    )
    assert (
        resolve_neutralized_body_restoration(
            comments, pr=head_a_pr, repository=REPOSITORY
        )
        is None
    )

    # A further commit lands. The exact-head binding is unchanged, so the
    # receipt stops resolving while the body still advertises neutralization.
    head_b_pr = {**head_a_pr, "head": {"sha": NEXT_HEAD}}
    assert (
        resolve_verified_merge_authority_receipt(
            comments, pr=head_b_pr, repository=REPOSITORY
        )
        is None
    )

    restoration = resolve_neutralized_body_restoration(
        comments, pr=head_b_pr, repository=REPOSITORY
    )
    assert restoration == {
        "closing_issues": [3820, 3823],
        "contract": NEUTRALIZED_BODY_RESTORATION_CONTRACT,
        "governing_issue": 3821,
        "head_sha": NEXT_HEAD,
        "matching_attempts": 1,
        "neutralized_body_sha256": authority_receipt["neutralized_body_sha256"],
        "neutralized_head_sha": HEAD,
        "pr_number": 3822,
        "reason": "neutralized-body-outlived-merge-attempt",
        "repository": REPOSITORY,
        "restore_body_sha256": authority_receipt["body_sha256"],
        "run_id": "vrun-authority",
    }

    # Only the authenticated original body is an accepted restoration, and the
    # durable authority trail stays untouched evidence.
    assert restored_body_matches_authority(original_body, restoration=restoration)
    assert not restored_body_matches_authority(
        neutralized_body, restoration=restoration
    )
    assert not restored_body_matches_authority(
        original_body.replace("Refs #3900", "Refs #3901"), restoration=restoration
    )
    assert comments == [_trusted_comment(str(plan["authority_receipt_comment"]))]

    # A restored-then-reneutralized body still resumes normally on the new head.
    restored_pr = {**head_b_pr, "body": original_body}
    assert (
        resolve_neutralized_body_restoration(
            comments, pr=restored_pr, repository=REPOSITORY
        )
        is None
    )
    next_plan = prepare_verified_merge(
        context={**_context(), "head_sha": NEXT_HEAD},
        pr=restored_pr,
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(NEXT_HEAD),
    )
    next_comments = [
        *comments,
        _trusted_comment(str(next_plan["authority_receipt_comment"])),
    ]
    reneutralized_pr = {**restored_pr, "body": str(next_plan["neutralized_body"])}
    assert (
        resolve_verified_merge_authority_receipt(
            next_comments, pr=reneutralized_pr, repository=REPOSITORY
        )
        == next_plan["authority_receipt"]
    )
    assert (
        resolve_neutralized_body_restoration(
            next_comments, pr=reneutralized_pr, repository=REPOSITORY
        )
        is None
    )


def test_neutralized_body_restoration_cli_uses_production_resolver(
    tmp_path: Path,
) -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    pr_path = tmp_path / "pr.json"
    comments_path = tmp_path / "comments.json"
    output_path = tmp_path / "restoration.json"
    comments_path.write_text(
        json.dumps([_trusted_comment(str(plan["authority_receipt_comment"]))]),
        encoding="utf-8",
    )

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.resolve_neutralized_body_restoration",
                "--pr-json",
                str(pr_path),
                "--comments-json",
                str(comments_path),
                "--repository",
                REPOSITORY,
                "--output-json",
                str(output_path),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    pr_path.write_text(
        json.dumps(_pr(str(plan["neutralized_body"]))), encoding="utf-8"
    )
    inside_attempt = _run()

    assert inside_attempt.returncode == 0, inside_attempt.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "restoration": None,
        "restoration_required": False,
        "status": "no_restoration_required",
    }

    pr_path.write_text(json.dumps(_pr()), encoding="utf-8")
    canonical = _run()

    assert canonical.returncode == 0, canonical.stderr
    assert (
        json.loads(output_path.read_text(encoding="utf-8"))["status"]
        == "no_restoration_required"
    )

    pr_path.write_text(
        json.dumps(
            {
                **_pr(str(plan["neutralized_body"])),
                "head": {"sha": NEXT_HEAD},
            }
        ),
        encoding="utf-8",
    )
    outlived = _run()

    assert outlived.returncode == 2, outlived.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "restoration_required"
    assert payload["restoration_required"] is True
    assert payload["restoration"]["neutralized_head_sha"] == HEAD
    assert payload["restoration"]["head_sha"] == NEXT_HEAD

    # A neutralized body whose evidence cannot prove a restore target is
    # indeterminate, never a safe exit 0.
    comments_path.write_text(json.dumps([]), encoding="utf-8")
    ambiguous = _run()

    assert ambiguous.returncode == 3, ambiguous.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "restoration": None,
        "restoration_required": False,
        "status": "ambiguous_neutralized_body",
    }


def test_neutralized_body_restoration_fails_closed_without_unambiguous_evidence() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    authority_receipt = plan["authority_receipt"]
    assert isinstance(authority_receipt, dict)
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    head_b_pr = {**_pr(str(plan["neutralized_body"])), "head": {"sha": NEXT_HEAD}}

    # No receipt at all: the restore target cannot be proven.
    assert (
        resolve_neutralized_body_restoration([], pr=head_b_pr, repository=REPOSITORY)
        is None
    )

    # Untrusted authorship never names a restore target.
    untrusted = [{**comments[0], "author_association": "NONE"}]
    assert (
        resolve_neutralized_body_restoration(
            untrusted, pr=head_b_pr, repository=REPOSITORY
        )
        is None
    )

    # A canonical body is not a restorable state.
    assert (
        resolve_neutralized_body_restoration(
            comments,
            pr={**head_b_pr, "body": _body()},
            repository=REPOSITORY,
        )
        is None
    )

    # A merged PR stays owned by the `restored` phase of its own attempt.
    assert (
        resolve_neutralized_body_restoration(
            comments,
            pr={
                **head_b_pr,
                "state": "closed",
                "merged": True,
                "merged_at": "2026-07-27T08:18:08Z",
            },
            repository=REPOSITORY,
        )
        is None
    )

    # Foreign repository, foreign run, and conflicting restore targets fail closed.
    assert (
        resolve_neutralized_body_restoration(
            comments, pr=head_b_pr, repository="RasmusTho/other"
        )
        is None
    )
    assert (
        resolve_neutralized_body_restoration(
            comments,
            pr=head_b_pr,
            repository=REPOSITORY,
            expected_run_id="vrun-other",
        )
        is None
    )
    conflicting = dict(authority_receipt)
    conflicting["body_sha256"] = "c" * 64
    assert (
        resolve_neutralized_body_restoration(
            [*comments, _authority_comment(conflicting)],
            pr=head_b_pr,
            repository=REPOSITORY,
        )
        is None
    )

    # Every one of those `None` outcomes is still an indeterminate live
    # neutralized body, distinct from a canonical or already-merged body.
    def _status(pr: dict[str, object]) -> object:
        return classify_neutralized_body_state(
            comments, pr=pr, repository=REPOSITORY
        )["status"]

    assert _status(head_b_pr) == "restoration_required"
    assert _status({**head_b_pr, "body": _body()}) == "no_restoration_required"
    assert (
        _status(
            {
                **head_b_pr,
                "state": "closed",
                "merged": True,
                "merged_at": "2026-07-27T08:18:08Z",
            }
        )
        == "no_restoration_required"
    )


def test_neutralized_body_state_never_reports_ambiguity_as_safe() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    neutralized_body = str(plan["neutralized_body"])
    head_a_pr = _pr(neutralized_body)
    head_b_pr = {**head_a_pr, "head": {"sha": NEXT_HEAD}}

    def _status(
        candidate_comments: list[dict[str, object]],
        pr: dict[str, object],
    ) -> object:
        return classify_neutralized_body_state(
            candidate_comments, pr=pr, repository=REPOSITORY
        )["status"]

    # In flight on the head the receipt covers, and a canonical body, are both
    # positively safe.
    assert _status(comments, head_a_pr) == "no_restoration_required"
    assert _status(comments, _pr()) == "no_restoration_required"
    assert _status([], _pr()) == "no_restoration_required"

    # Outlived its attempt with a provable restore target.
    assert _status(comments, head_b_pr) == "restoration_required"

    # Neutralized with unusable evidence is indeterminate, not safe.
    assert _status([], head_b_pr) == "ambiguous_neutralized_body"
    assert (
        _status(
            [{**comments[0], "author_association": "NONE"}],
            head_b_pr,
        )
        == "ambiguous_neutralized_body"
    )
    assert (
        classify_neutralized_body_state(
            comments,
            pr=head_b_pr,
            repository=REPOSITORY,
            expected_run_id="vrun-other",
        )["status"]
        == "ambiguous_neutralized_body"
    )
    assert classify_neutralized_body_state(
        comments, pr=head_a_pr, repository=REPOSITORY
    ) == {
        "restoration": None,
        "restoration_required": False,
        "status": "no_restoration_required",
    }


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, "restoration_required", id="positively-open"),
        pytest.param(
            {
                "state": "closed",
                "merged": True,
                "merged_at": "2026-07-27T08:18:08Z",
            },
            "no_restoration_required",
            id="positively-merged",
        ),
        pytest.param({"state": None}, "ambiguous_neutralized_body", id="no-state"),
        pytest.param(
            {"state": "unknown"}, "ambiguous_neutralized_body", id="unknown-state"
        ),
        pytest.param(
            {"state": "open", "merged": True},
            "ambiguous_neutralized_body",
            id="open-but-merged",
        ),
        pytest.param(
            {"state": "closed", "merged": True, "merged_at": None},
            "ambiguous_neutralized_body",
            id="merged-without-timestamp",
        ),
        pytest.param(
            {"state": "closed"}, "ambiguous_neutralized_body", id="closed-unmerged"
        ),
    ],
)
def test_incomplete_or_contradictory_snapshots_are_never_reported_safe(
    overrides: dict[str, object], expected: str
) -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    pr = {
        **_pr(str(plan["neutralized_body"])),
        "head": {"sha": NEXT_HEAD},
        **overrides,
    }
    if overrides.get("state") is None and "state" in overrides:
        del pr["state"]

    result = classify_neutralized_body_state(
        comments, pr=pr, repository=REPOSITORY
    )

    assert result["status"] == expected
    if expected != "restoration_required":
        assert result["restoration"] is None
        assert (
            resolve_neutralized_body_restoration(
                comments, pr=pr, repository=REPOSITORY
            )
            is None
        )


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(
            lambda body: body + "Governing-Issue: #3821\n",
            id="second-governing-issue-line",
        ),
        pytest.param(
            # Drops the evidence line for a closing issue, so the marker's
            # closing set is no longer a subset of governing + supporting.
            lambda body: body.replace("Refs #3820\n", ""),
            id="deleted-closing-evidence-line",
        ),
        pytest.param(
            lambda body: body + "Verified-Closing-Issues: #3820, #3823\n",
            id="duplicated-marker-line",
        ),
        pytest.param(lambda body: body + "\ra\n", id="lone-carriage-return"),
        pytest.param(
            lambda body: body.replace("Governing-Issue: #3821", "Governing-Issue: x"),
            id="unparseable-governing-issue",
        ),
    ],
)
def test_a_marker_that_no_longer_parses_is_stranded_not_canonical(damage) -> None:
    """A body can keep its marker while its grammar stops resolving.

    `resolve_neutralized_issue_authority` answers `None` for a canonical body and
    for a damaged one alike. Treating that shared `None` as "canonical" strands a
    neutralization that carries no closing authority at all, so `pr-contract`
    fails on every head — issue #4185 reproduced by its own fix. The realistic
    source is an agent re-pasting the PR template after a merge hard stop.
    """

    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    damaged = damage(str(plan["neutralized_body"]))
    pr = {**_pr(damaged), "head": {"sha": NEXT_HEAD}}

    # Precondition: the damage really did break the strict grammar, so this test
    # exercises the conflation rather than an intact body.
    assert resolve_neutralized_issue_authority(damaged) is None
    assert has_neutralized_closing_marker(damaged)

    assert (
        classify_neutralized_body_state(comments, pr=pr, repository=REPOSITORY)[
            "status"
        ]
        == "ambiguous_neutralized_body"
    )


def test_a_snapshot_without_a_body_is_never_reported_safe() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    pr = {**_pr(), "head": {"sha": NEXT_HEAD}}
    del pr["body"]

    assert (
        classify_neutralized_body_state(comments, pr=pr, repository=REPOSITORY)[
            "status"
        ]
        == "ambiguous_neutralized_body"
    )


def test_restored_body_proof_binds_contract_identities_and_lf_equivalence() -> None:
    original_body = _body()
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(original_body),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    restoration = resolve_neutralized_body_restoration(
        comments,
        pr={**_pr(str(plan["neutralized_body"])), "head": {"sha": NEXT_HEAD}},
        repository=REPOSITORY,
    )
    assert restoration is not None

    assert restored_body_matches_authority(original_body, restoration=restoration)
    # GitHub may return the same body without its single terminal LF.
    assert original_body.endswith("\n")
    assert restored_body_matches_authority(
        original_body[:-1], restoration=restoration
    )

    # A payload that is not this contract proves nothing, even with a digest hit.
    assert not restored_body_matches_authority(
        original_body,
        restoration={**restoration, "contract": "some_other_contract.v1"},
    )
    # Digest and identities must agree; neither alone is sufficient.
    assert not restored_body_matches_authority(
        original_body,
        restoration={**restoration, "governing_issue": 4185},
    )
    assert not restored_body_matches_authority(
        original_body,
        restoration={**restoration, "closing_issues": [3820]},
    )
    assert not restored_body_matches_authority(
        original_body + "trailing drift\n", restoration=restoration
    )
    assert not restored_body_matches_authority(None, restoration=restoration)


def test_conflicting_current_head_authority_never_falls_back_to_a_stale_head() -> None:
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    stale_receipt = plan["authority_receipt"]
    assert isinstance(stale_receipt, dict)
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    head_b_pr = {
        **_pr(str(plan["neutralized_body"])),
        "head": {"sha": NEXT_HEAD},
    }

    # Baseline: the stale head alone names a restore target.
    assert (
        resolve_neutralized_body_restoration(
            comments, pr=head_b_pr, repository=REPOSITORY
        )
        is not None
    )

    # Two conflicting trusted receipts for the live head. The exact-head resolver
    # correctly refuses to pick one, so a merge for this attempt may still be in
    # flight and restoration must not race it.
    current_a = {**stale_receipt, "head_sha": NEXT_HEAD}
    current_b = {**current_a, "run_id": "vrun-other"}
    conflicted = [
        *comments,
        _authority_comment(current_a),
        _authority_comment(current_b),
    ]

    assert (
        resolve_verified_merge_authority_receipt(
            conflicted, pr=head_b_pr, repository=REPOSITORY
        )
        is None
    )
    assert (
        resolve_neutralized_body_restoration(
            conflicted, pr=head_b_pr, repository=REPOSITORY
        )
        is None
    )
    assert (
        classify_neutralized_body_state(
            conflicted, pr=head_b_pr, repository=REPOSITORY
        )["status"]
        == "ambiguous_neutralized_body"
    )


@pytest.mark.parametrize(
    "live_head_evidence",
    [
        pytest.param(
            lambda receipt: [_authority_comment({**receipt, "surprise": True})],
            id="extra-key",
        ),
        pytest.param(
            lambda receipt: [
                _authority_comment(
                    {
                        field: value
                        for field, value in receipt.items()
                        if field != "repair_budget"
                    }
                )
            ],
            id="missing-repair-budget",
        ),
        pytest.param(
            lambda receipt: [
                _trusted_comment(
                    2
                    * (
                        "verified issue-set merge authority:\n```json\n"
                        + json.dumps(
                            receipt, sort_keys=True, separators=(",", ":")
                        )
                        + "\n```\n"
                    )
                )
            ],
            id="two-receipt-blocks-in-one-comment",
        ),
    ],
)
def test_malformed_live_head_evidence_still_blocks_a_stale_fallback(
    live_head_evidence,
) -> None:
    """A structural filter must not be able to discard the race guard.

    Each of these receipts is invalid as authority, so the exact-head resolver
    ignores it. But it is still trusted evidence that a merge attempt exists on
    the live head, and answering from an older head there is the merge race the
    restore contract forbids.
    """

    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    stale_receipt = plan["authority_receipt"]
    assert isinstance(stale_receipt, dict)
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    head_b_pr = {**_pr(str(plan["neutralized_body"])), "head": {"sha": NEXT_HEAD}}

    assert (
        resolve_neutralized_body_restoration(
            comments, pr=head_b_pr, repository=REPOSITORY
        )
        is not None
    )

    guarded = [
        *comments,
        *live_head_evidence({**stale_receipt, "head_sha": NEXT_HEAD}),
    ]

    assert (
        resolve_verified_merge_authority_receipt(
            guarded, pr=head_b_pr, repository=REPOSITORY
        )
        is None
    )
    assert (
        resolve_neutralized_body_restoration(
            guarded, pr=head_b_pr, repository=REPOSITORY
        )
        is None
    )
    assert (
        classify_neutralized_body_state(
            guarded, pr=head_b_pr, repository=REPOSITORY
        )["status"]
        == "ambiguous_neutralized_body"
    )

    # Untrusted authorship is not evidence and must not block a real restore.
    untrusted = [
        *comments,
        *[
            {**comment, "author_association": "NONE"}
            for comment in live_head_evidence(
                {**stale_receipt, "head_sha": NEXT_HEAD}
            )
        ],
    ]
    assert (
        resolve_neutralized_body_restoration(
            untrusted, pr=head_b_pr, repository=REPOSITORY
        )
        is not None
    )


def test_restored_body_proof_cli_uses_production_verifier(tmp_path: Path) -> None:
    original_body = _body()
    plan = prepare_verified_merge(
        context=_context(),
        pr=_pr(original_body),
        live_closing_issues=[3820, 3823],
        merge_readiness=_readiness(),
    )
    comments = [_trusted_comment(str(plan["authority_receipt_comment"]))]
    restoration = resolve_neutralized_body_restoration(
        comments,
        pr={**_pr(str(plan["neutralized_body"])), "head": {"sha": NEXT_HEAD}},
        repository=REPOSITORY,
    )
    restoration_path = tmp_path / "restoration.json"
    body_path = tmp_path / "candidate.md"
    # The resolver CLI's wrapper shape must be accepted directly.
    restoration_path.write_text(
        json.dumps({"restoration": restoration, "restoration_required": True}),
        encoding="utf-8",
    )

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.verify_restored_pr_body",
                "--restoration-json",
                str(restoration_path),
                "--restored-body-file",
                str(body_path),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    body_path.write_text(original_body, encoding="utf-8")
    accepted = _run()

    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["restored_body_matches_authority"] is True

    body_path.write_text(str(plan["neutralized_body"]), encoding="utf-8")
    refused = _run()

    assert refused.returncode == 1
    assert json.loads(refused.stdout)["restored_body_matches_authority"] is False
