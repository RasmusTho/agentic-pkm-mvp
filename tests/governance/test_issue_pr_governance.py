from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.dispatcher.verification_contract import (
    IssueAuthority,
    MAX_CLOSING_ISSUES,
    neutralize_closing_issue_references,
    resolve_builderops_routing_status,
    resolve_issue_authority,
    resolve_issue_contract,
    resolve_neutralized_issue_authority,
    resolve_pr_contract_final_review_rounds,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# The `_BUILDEROPS_ROUTING_REGEX`/`_BUILDEROPS_ROUTING_FIELDS`/`_TIER1_LANE_REGEX`
# duplicate copies formerly declared here (issue #4272) are retired in favor of
# the canonical `app.dispatcher.verification_contract` twins imported above,
# proven against the workflow's own JS by
# `test_final_review_rounds_check_executes_via_canonical_implementation` and
# `test_builderops_routing_stub_detection_matches_workflow_js` below.


def test_final_review_rounds_check_executes_via_canonical_implementation() -> None:
    """Behavioral parity test replacing the former source-text tripwire.

    Exercises `resolve_pr_contract_final_review_rounds` (the canonical Python
    twin of the `pr-contract` gate's `// final-review-rounds:start`/`:end`
    JS block) against the same JS via marker-extraction, mirroring
    `test_javascript_and_python_authority_grammar_are_identical`.
    """
    fixture_bodies = [
        "Final-Review-Rounds: 0\n",
        "Final-Review-Rounds: 1\n",
        "Final-Review-Rounds: 2\n",
        "Final-Review-Rounds: 3\n",
        "no declaration here\n",
        "Final-Review-Rounds: 0\nFinal-Review-Rounds: 1\n",
        "Final-Review-Rounds:0\n",
        "Final-Review-Rounds:  2  \n",
        "prose mentioning Final-Review-Rounds: 1 mid-line\n",
        # Non-LF line terminators (issue #4341): JS `$`/`^` under `/m` treat
        # every ECMAScript `LineTerminator` as a line break, not only `\n`.
        "Final-Review-Rounds: 1\r\n",
        "Final-Review-Rounds: 1\r",
        "Final-Review-Rounds: 1 ",
        "Final-Review-Rounds: 1 ",
        "Final-Review-Rounds: 0\r\nFinal-Review-Rounds: 1\r\n",
        "prose\r\nFinal-Review-Rounds: 2\r\nmore prose\r\n",
    ]
    for body in fixture_bodies:
        js_result = _js_final_review_rounds(body)
        py_result = resolve_pr_contract_final_review_rounds(body)
        assert js_result["satisfied"] == py_result.satisfied, body
        assert js_result["declaredCount"] == py_result.declared_count, body
        assert js_result["validCount"] == py_result.valid_count, body

    # Semantic assertion (issue #4342), not only JS-vs-Python agreement: `3`
    # must actually be rejected by the real gate, not merely agreed-upon
    # between the twins. Widening `[012]` -> `[0-9]` identically on both
    # sides would still pass every assertion above.
    assert resolve_pr_contract_final_review_rounds("Final-Review-Rounds: 3\n").satisfied is False


def test_final_review_rounds_workflow_accepts_only_012() -> None:
    """Semantic pin: the live workflow JS accepts exactly `{0, 1, 2}` (issue #4342).

    Restores the pin PR #4331 deleted (`assert r"Final-Review-Rounds:[ \\t]*
    [012][ \\t]*$" in workflow`). Asserts against the workflow's own JS text
    directly via `_js_final_review_rounds`, independent of JS-vs-Python
    equality, so a value set widened identically on both twins (e.g.
    `[012]` -> `[0-9]`) still fails this test even though the twins would
    still agree with each other.
    """
    for value in ("0", "1", "2"):
        result = _js_final_review_rounds(f"Final-Review-Rounds: {value}\n")
        assert result["satisfied"] is True, value

    for value in ("3", "4", "5", "9", "-1", "01", "10"):
        result = _js_final_review_rounds(f"Final-Review-Rounds: {value}\n")
        assert result["satisfied"] is False, value


def test_builderops_routing_stub_detection_matches_workflow_js() -> None:
    """Behavioral parity test for the `## BuilderOps Routing` filled-vs-stub check.

    Exercises `resolve_builderops_routing_status` (the canonical Python twin of
    the `pr-contract` gate's `// builderops-routing:start`/`:end` JS block)
    against the same JS via marker-extraction.
    """
    fixture_cases = [
        ("## BuilderOps Routing\n- Records/projections/receipts: none\n- Reason: nothing routed\n", True),
        ("## BuilderOps Routing\n- Records/projections/receipts: <...>\n- Reason: <...>\n", True),
        ("## BuilderOps Routing\n", True),
        ("", True),
        ("- [x] Governance lane\n", False),
        ("- [x] Docs authoring lane\n", True),
        (
            "- [x] Governance lane\n## BuilderOps Routing\n"
            "- Records/projections/receipts: x\n- Reason: y\n",
            True,
        ),
        # \x1c-\x1f "information separator" controls (issue #4341): Python's
        # Unicode-mode `\s` matches them, JS's `\s` does not, so a body using
        # one as the checkbox/lane-name separator must NOT be treated as the
        # Tier 1 lane the way a real space is.
        ("- [x]\x1cGovernance lane\n", False),
        ("-\x1f[x]\x1fDocs authoring lane\n", False),
        # \r-terminated / CRLF lane declarations must still be recognized
        # (line-terminator canonicalization, not the whitespace-class fix).
        ("- [x] Governance lane\r\n", False),
        ("- [x] Docs authoring lane\r", True),
    ]
    for body, has_issue_authority in fixture_cases:
        js_result = _js_builderops_routing(body, has_issue_authority)
        py_result = resolve_builderops_routing_status(
            body, has_issue_authority=has_issue_authority
        )
        assert js_result["satisfied"] == py_result.satisfied, (body, has_issue_authority)
        assert js_result["isTier1Lane"] == py_result.is_tier1_lane, (body, has_issue_authority)
        assert js_result["hasSection"] == py_result.has_section, (body, has_issue_authority)


def test_pr_contract_trigger_excludes_review_requested_and_cancels_stale_runs() -> None:
    """`pr-contract` has no assertion that reads anything `review_requested` changes (not the
    body, file list, commits, or title), so re-running it on that event only burns CI minutes
    and the shared Actions queue. Keep `opened`/`edited`/`reopened`/`synchronize` — `edited` is
    how body repairs re-trigger the gate and `synchronize` is when the diff can change."""
    workflow = _read_workflow()

    assert "types: [opened, edited, reopened, synchronize]" in workflow
    assert "review_requested" not in workflow

    pr_contract_job = workflow[workflow.index("\n  pr-contract:") :]
    assert "concurrency:" in pr_contract_job
    concurrency_block = pr_contract_job[: pr_contract_job.index("runs-on:")]
    assert "group: pr-contract-${{ github.event.pull_request.number }}" in concurrency_block
    assert "cancel-in-progress: true" in concurrency_block


def _read_workflow() -> str:
    return (REPO_ROOT / ".github/workflows/issue-pr-governance.yml").read_text(
        encoding="utf-8"
    )


def _sbs_impact_warnings(body: str, changed_files: list[str]) -> list[str]:
    workflow = _read_workflow()
    checker = workflow.split("// sbs-impact-consistency:start", 1)[1].split(
        "// sbs-impact-consistency:end", 1
    )[0]
    script = (
        checker
        + "\nconst body = JSON.parse(process.argv[1]);"
        + "\nconst changedFiles = JSON.parse(process.argv[2]);"
        + "\nprocess.stdout.write(JSON.stringify(sbsImpactWarnings(body, changedFiles)));"
    )
    completed = subprocess.run(
        ["node", "-e", script, json.dumps(body), json.dumps(changed_files)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_sbs_impact_cross_check_warns_for_contradictory_migration_diff() -> None:
    warnings = _sbs_impact_warnings(
        "## SBS Impact\n- Persistence impact: none\n- New or changed contract: none\n",
        ["app/alembic/versions/1234_add_table.py"],
    )

    assert warnings == [
        "SBS Impact declares `Persistence impact: none` or `unaffected`, "
        "but this PR adds an Alembic migration."
    ]


def test_sbs_impact_cross_check_warns_for_contradictory_contract_diff() -> None:
    warnings = _sbs_impact_warnings(
        "## SBS Impact\n- Persistence impact: none\n"
        "- New or changed contract: unaffected\n",
        ["docs/contracts/NEW_CONTRACT.md"],
    )

    assert warnings == [
        "SBS Impact declares `New or changed contract: none` or `unaffected`, "
        "but this PR changes a contract document."
    ]


def test_sbs_impact_cross_check_is_silent_for_consistent_diff() -> None:
    warnings = _sbs_impact_warnings(
        "## SBS Impact\n- Persistence impact: durable schema migration\n"
        "- New or changed contract: updated\n",
        ["app/alembic/versions/1234_add_table.py", "docs/contracts/NEW_CONTRACT.md"],
    )

    assert warnings == []


def _js_issue_shape_errors(issue: dict[str, object]) -> list[str]:
    workflow = _read_workflow()
    validator = workflow.split("// issue-shape-validator:start", 1)[1].split(
        "// issue-shape-validator:end", 1
    )[0]
    script = (
        validator
        + "\nconst issue = JSON.parse(process.argv[1]);"
        + "\nprocess.stdout.write(JSON.stringify(validateIssueShape(issue)));"
    )
    completed = subprocess.run(
        ["node", "-e", script, json.dumps(issue)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _known_defects_registry_body() -> str:
    helper_path = (
        REPO_ROOT
        / ".codex"
        / "skills"
        / "bug-to-issue"
        / "scripts"
        / "known_defects.py"
    )
    spec = importlib.util.spec_from_file_location(
        "known_defects_for_governance_test",
        helper_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.render_registry_body()


def test_issue_shape_workflow_accepts_only_exact_known_defects_container() -> None:
    body = _known_defects_registry_body()
    canonical = {
        "body": body,
        "locked": True,
        "title": "Known Defects Registry (rolling)",
        "labels": [
            {"name": "type:bug"},
            {"name": "state:known-defect"},
        ],
    }

    assert _js_issue_shape_errors(canonical) == []
    assert _js_issue_shape_errors(
        {
            **canonical,
            "body": body + "\nmanual suffix",
        }
    ) == ["Known Defects registry body must match the exact v1 container schema"]
    assert _js_issue_shape_errors(
        {
            **canonical,
            "labels": canonical["labels"] + [{"name": "agent:blocked"}],
        }
    ) == [
        "Known Defects registry must carry exactly type:bug and state:known-defect"
    ]
    assert _js_issue_shape_errors(
        {
            **canonical,
            "locked": False,
        }
    ) == ["Known Defects registry must remain locked"]
    assert _js_issue_shape_errors(
        {
            **canonical,
            "title": "Renamed registry",
        }
    ) == ["Known Defects registry title must match the exact v1 identity"]
    assert _js_issue_shape_errors(
        {
            **canonical,
            "labels": [{"name": "type:bug"}],
        }
    ) == [
        "Known Defects registry must carry exactly type:bug and state:known-defect"
    ]


def test_issue_shape_workflow_rechecks_registry_lock_transitions_from_live_issue() -> None:
    workflow = _read_workflow()

    assert "types: [opened, edited, reopened, labeled, unlabeled, locked, unlocked, closed]" in workflow
    assert "let { data: liveIssue } = await github.rest.issues.get" in workflow
    assert "validateIssueShape(liveIssue)" in workflow
    assert 'context.payload.action === "opened"' in workflow
    assert "hasKnownDefectsIdentity" in workflow
    assert 'issue.title === "Known Defects Registry (rolling)"' in workflow
    assert "isUnlockedRegistryBootstrap" in workflow
    assert "const maxLockPolls = 10" in workflow
    assert "attempt < maxLockPolls && liveIssue.locked !== true" in workflow
    assert "setTimeout(resolve, 1000)" in workflow
    assert "({ data: liveIssue } = await github.rest.issues.get" in workflow


def test_issue_shape_workflow_keeps_normal_issue_contract_strict() -> None:
    errors = _js_issue_shape_errors(
        {
            "body": "# Not a task contract",
            "labels": [{"name": "type:bug"}],
        }
    )

    assert len(errors) == 1
    assert errors[0].startswith("Issue is missing required sections:")
    assert "Acceptance Criteria" in errors[0]


def _verified_merge_body_digest(body: str) -> str:
    canonical_body = body[:-1] if body.endswith("\n") else body
    return hashlib.sha256(canonical_body.encode()).hexdigest()


def _js_final_review_rounds(body: str) -> dict[str, object]:
    """Marker-extraction twin runner for `// final-review-rounds:start`/`:end`.

    Mirrors `_js_issue_authority` below: extract the workflow's own pure JS
    function and run it under Node so the parity assertion exercises the
    literal CI code, not a hand-copied re-transcription of it.
    """
    workflow = _read_workflow()
    block = workflow.split("// final-review-rounds:start", 1)[1].split(
        "// final-review-rounds:end", 1
    )[0]
    script = (
        block
        + "\nconst candidate = JSON.parse(process.argv[1]);"
        + "\nprocess.stdout.write(JSON.stringify(resolveFinalReviewRounds(candidate)));"
    )
    completed = subprocess.run(
        ["node", "-e", script, json.dumps(body)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _js_builderops_routing(body: str, has_issue_authority: bool) -> dict[str, object]:
    """Marker-extraction twin runner for `// builderops-routing:start`/`:end`."""
    workflow = _read_workflow()
    block = workflow.split("// builderops-routing:start", 1)[1].split(
        "// builderops-routing:end", 1
    )[0]
    script = (
        block
        + "\nconst inputs = JSON.parse(process.argv[1]);"
        + "\nprocess.stdout.write(JSON.stringify("
        + "resolveBuilderOpsRouting(inputs.body, inputs.hasIssueAuthority)));"
    )
    completed = subprocess.run(
        [
            "node",
            "-e",
            script,
            json.dumps({"body": body, "hasIssueAuthority": has_issue_authority}),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _js_issue_authority(body: str) -> dict[str, object]:
    workflow = _read_workflow()
    classifier = workflow.split("// authority-classifier:start", 1)[1].split(
        "// authority-classifier:end", 1
    )[0]
    script = (
        classifier
        + "\nconst candidate = JSON.parse(process.argv[1]);"
        + "\nprocess.stdout.write(JSON.stringify(classifyIssueAuthority(candidate)));"
    )
    completed = subprocess.run(
        ["node", "-e", script, json.dumps(body)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _js_neutralized_merge_authority(
    comments: list[dict[str, object]],
    pull_request: dict[str, object],
    repository: str,
) -> dict[str, object] | None:
    workflow = _read_workflow()
    classifier = workflow.split("// authority-classifier:start", 1)[1].split(
        "// authority-classifier:end", 1
    )[0]
    validator = workflow.split(
        "// neutralized-authority-validator:start", 1
    )[1].split("// neutralized-authority-validator:end", 1)[0]
    script = (
        'const crypto = require("crypto");\n'
        + classifier
        + validator
        + "\nconst inputs = JSON.parse(process.argv[1]);"
        + "\nconst issueAuthority = classifyIssueAuthority(inputs.pullRequest.body);"
        + "\nconst result = resolveNeutralizedMergeAuthority({"
        + "comments: inputs.comments, issueAuthority, "
        + "pullRequest: inputs.pullRequest, repository: inputs.repository});"
        + "\nprocess.stdout.write(JSON.stringify(result));"
    )
    completed = subprocess.run(
        [
            "node",
            "-e",
            script,
            json.dumps(
                {
                    "comments": comments,
                    "pullRequest": pull_request,
                    "repository": repository,
                }
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _neutralized_authority_fixture() -> tuple[
    dict[str, object], dict[str, object], dict[str, object]
]:
    repository = "RasmusTho/agentic-pkm-mvp"
    head = "a" * 40
    original = (
        "Governing-Issue: #3821\n"
        "Refs #3821\n"
        "Fixes #3820\n"
        "Refs #3900\n"
    )
    neutralized = (
        "Governing-Issue: #3821\n"
        "Refs #3821\n"
        "Refs #3820\n"
        "Refs #3900\n"
        "Verified-Closing-Issues: #3820\n"
    )
    receipt = {
        "authenticated_supporting_issues": [3820],
        "body_sha256": _verified_merge_body_digest(original),
        "closing_issues": [3820],
        "contract": "verified_issue_set_merge_authority.v1",
        "governing_issue": 3821,
        "head_sha": head,
        "live_supporting_issues": [3820, 3900],
        "neutralized_body_sha256": _verified_merge_body_digest(neutralized),
        "pr_number": 3822,
        "repair_budget": {"policy_version": "v2", "mechanisms": []},
        "repository": repository,
        "run_id": "vrun-authority",
    }
    comment = {
        "author_association": "COLLABORATOR",
        "body": (
            "verified issue-set merge authority:\n```json\n"
            + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            + "\n```"
        ),
    }
    pull_request = {
        "body": neutralized,
        "head": {"sha": head},
        "number": 3822,
    }
    return pull_request, comment, receipt


def _read_development_workflow() -> str:
    return (REPO_ROOT / "docs/development/DEV_WORKFLOW.md").read_text(
        encoding="utf-8"
    )


def _companion_design_audit_path(filename: str) -> Path:
    return (
        REPO_ROOT
        / "companion-ui/design_handoff/2026-07-07-uat-design-audit"
        / filename
    )


def test_companion_design_audit_handoff_has_durable_sources() -> None:
    readme = _companion_design_audit_path("README.md").read_text(encoding="utf-8")
    audit = _companion_design_audit_path("DESIGN_AUDIT.md").read_text(encoding="utf-8")
    archive = (REPO_ROOT / "companion-ui/design_handoff/README.md").read_text(
        encoding="utf-8"
    )
    sources_path = _companion_design_audit_path("SOURCES.md")
    sources = sources_path.read_text(encoding="utf-8")

    assert sources_path.is_file()
    assert "pull/3359" in sources
    assert "issues/3431" in sources
    for issue_number in range(3360, 3365):
        assert f"issues/{issue_number}" in sources
    assert "not retained as durable evidence" in sources.lower()
    assert "not reproducible repo evidence" in readme.lower()
    archive_row = next(
        line
        for line in archive.splitlines()
        if "`2026-07-07-uat-design-audit/`" in line
    )
    assert "not retained as reproducible repo evidence" in archive_row.lower()
    assert "2026-07-07-uat-design-audit/SOURCES.md" in archive_row
    assert "#3360–#3364" in archive_row
    for missing_input in (
        "CLAUDE_DESIGN_AUDIT_PROMPT.md",
        "UAT_REPORT.md",
        "findings.json",
        "findings2.json",
    ):
        assert missing_input not in readme
        assert missing_input not in audit


def test_companion_design_audit_handoff_declares_guidance_not_sot() -> None:
    handoff = "\n".join(
        _companion_design_audit_path(filename).read_text(encoding="utf-8")
        for filename in ("README.md", "DESIGN_AUDIT.md", "SOURCES.md")
    )
    lowered = handoff.lower()

    assert "design guidance/input" in lowered
    assert "not a source of truth" in lowered
    assert "handoff package -> normalized spec -> github issue -> pr -> validation receipt" in lowered
    assert "#3360" in handoff
    for issue_number in range(3361, 3365):
        assert f"#{issue_number}" in handoff
    assert "durable design source-of-truth" not in lowered


def _builderops_routing_satisfied(body: str) -> bool:
    """Test oracle delegating to the canonical implementation (issue #4272).

    Previously this reimplemented the `## BuilderOps Routing` filled-vs-stub
    regex a fourth time; it now calls `resolve_builderops_routing_status`
    directly so this test file cannot silently drift from the workflow's own
    JS (proven by `test_builderops_routing_stub_detection_matches_workflow_js`).
    """
    has_issue_authority = bool(_js_issue_authority(body)["hasIssueAuthority"])
    return resolve_builderops_routing_status(
        body, has_issue_authority=has_issue_authority
    ).satisfied


def _governing_issue_identity_satisfied(body: str) -> bool:
    authority = _js_issue_authority(body)
    return not authority["hasIssueAuthority"] or bool(authority["valid"])


@pytest.mark.parametrize(
    "body",
    [
        "Fixes #123",
        "Governing-Issue: #\nFixes #123",
        "Governing-Issue: #0\nFixes #123",
        "Governing-Issue: #-1\nFixes #123",
        "Governing-Issue: #123\nGoverning-Issue: #456\nFixes #123",
        "Governing-Issue : #123\nFixes #123",
        "Governing-Issue: #123",
        "Governing-Issue: #123\nFixes #0",
        "Governing-Issue: #123\nFixes #-1",
        "Governing-Issue: #123\nFixes #abc",
        "Governing-Issue:\n#123\nFixes #123",
        "- [x] Governance lane\nFixes #0",
    ],
)
def test_issue_backed_pr_rejects_missing_ambiguous_or_invalid_governing_identity(
    body: str,
) -> None:
    assert not _governing_issue_identity_satisfied(body)


def test_issue_backed_pr_accepts_single_and_multi_issue_authority() -> None:
    single = "Governing-Issue: #123\n\nFixes #123"
    multi = "Governing-Issue: #3603\n\nRefs #3603\nFixes #3626\nCloses #3698"

    assert _governing_issue_identity_satisfied(single)
    assert _governing_issue_identity_satisfied(multi)
    authority = resolve_issue_authority(multi)
    assert authority is not None
    assert authority.governing_issue == 3603
    assert authority.closing_issues == (3626, 3698)
    assert authority.supporting_issues == (3626, 3698)


def test_narrative_closer_is_rejected_by_javascript_and_python_authority() -> None:
    """The shared resolver must not authenticate closure authority from prose."""
    body = (
        "Governing-Issue: #4211\n\n"
        "Fixes #4211\n\n"
        "Daily audit says PR #4141 closed #4140 while review comments remain."
    )

    assert _js_issue_authority(body)["valid"] is False
    assert resolve_issue_authority(body) is None


def test_verified_merge_neutralized_authority_matches_javascript_and_python() -> None:
    body = (
        "Governing-Issue: #3821\n"
        "Refs #3821\n"
        "Fixes #3820\n"
        "Closes #3823\n"
        "Refs #3900"
    )
    expected = IssueAuthority(
        governing_issue=3821,
        closing_issues=(3820, 3823),
        supporting_issues=(3820, 3823, 3900),
    )

    neutralized = neutralize_closing_issue_references(body, expected)
    javascript = _js_issue_authority(neutralized)

    assert "Verified-Closing-Issues: #3820, #3823" in neutralized
    assert resolve_neutralized_issue_authority(neutralized) == expected
    assert javascript["valid"] is False
    assert javascript["neutralizedValid"] is True
    assert javascript["closingIssueCount"] == 2
    assert javascript["issueLinkMentions"] == []


def test_neutralized_pr_contract_requires_trusted_exact_head_authority_receipt() -> None:
    pull_request, comment, receipt = _neutralized_authority_fixture()
    repository = str(receipt["repository"])

    resolved = _js_neutralized_merge_authority(
        [comment], pull_request, repository
    )

    assert resolved == receipt


def test_neutralized_pr_contract_canonicalizes_only_one_terminal_lf() -> None:
    pull_request, comment, receipt = _neutralized_authority_fixture()
    repository = str(receipt["repository"])
    body = str(pull_request["body"])
    assert body.endswith("\n")

    for equivalent_body in (body, body[:-1]):
        candidate = {**pull_request, "body": equivalent_body}
        assert _js_neutralized_merge_authority(
            [comment], candidate, repository
        ) == receipt

    for changed_body in (body + "\n", body + " ", body + "substantive drift"):
        substantive_drift = {**pull_request, "body": changed_body}
        assert (
            _js_neutralized_merge_authority(
                [comment], substantive_drift, repository
            )
            is None
        )


def test_neutralized_pr_contract_accepts_legacy_authority_receipt_only_for_one_terminal_lf() -> None:
    pull_request, comment, receipt = _neutralized_authority_fixture()
    body = str(pull_request["body"])
    legacy = copy.deepcopy(receipt)
    legacy["neutralized_body_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    legacy_comment = copy.deepcopy(comment)
    legacy_comment["body"] = (
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(legacy, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )
    legacy_comment["created_at"] = "2026-07-21T16:16:34Z"
    legacy_comment["updated_at"] = "2026-07-21T16:16:34Z"
    lf_less = {**pull_request, "body": body[:-1]}

    assert _js_neutralized_merge_authority(
        [legacy_comment], lf_less, str(legacy["repository"])
    ) == legacy
    for changed in (body, body[:-1] + " ", body[:-1] + "drift"):
        assert _js_neutralized_merge_authority(
            [legacy_comment], {**pull_request, "body": changed}, str(legacy["repository"])
        ) is None
    assert _js_neutralized_merge_authority(
        [legacy_comment], {**pull_request, "body": body + "\n"}, str(legacy["repository"])
    ) == legacy

    for crlf_body in (body[:-1] + "\r", body[:-1].replace("Refs", "Refs\r", 1)):
        crlf_receipt = copy.deepcopy(legacy)
        crlf_receipt["neutralized_body_sha256"] = hashlib.sha256(
            (crlf_body + "\n").encode()
        ).hexdigest()
        crlf_comment = {
            **legacy_comment,
            "body": "verified issue-set merge authority:\n```json\n"
            + json.dumps(crlf_receipt, sort_keys=True, separators=(",", ":"))
            + "\n```",
        }
        assert _js_neutralized_merge_authority(
            [crlf_comment], {**pull_request, "body": crlf_body}, str(legacy["repository"])
        ) is None
    post_cutoff = {
        **legacy_comment,
        "created_at": "2026-07-21T16:32:11Z",
        "updated_at": "2026-07-21T16:32:11Z",
    }
    assert _js_neutralized_merge_authority(
        [post_cutoff], lf_less, str(legacy["repository"])
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
        assert _js_neutralized_merge_authority(
            [malformed_provenance], lf_less, str(legacy["repository"])
        ) is None
    valid_leap_day = {
        **legacy_comment,
        "created_at": "2024-02-29T16:16:34Z",
        "updated_at": "2024-02-29T16:16:34Z",
    }
    assert _js_neutralized_merge_authority(
        [valid_leap_day], lf_less, str(legacy["repository"])
    ) == legacy

    double_lf = body + "\n"
    canonical_double_lf = copy.deepcopy(receipt)
    canonical_double_lf["neutralized_body_sha256"] = _verified_merge_body_digest(
        double_lf
    )
    canonical_comment = copy.deepcopy(comment)
    canonical_comment["body"] = (
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(canonical_double_lf, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )
    assert _js_neutralized_merge_authority(
        [canonical_comment], {**pull_request, "body": double_lf}, str(receipt["repository"])
    ) == canonical_double_lf


def test_neutralized_pr_contract_rejects_forged_stale_missing_and_conflicting_authority() -> None:
    pull_request, comment, receipt = _neutralized_authority_fixture()
    repository = str(receipt["repository"])
    forged = copy.deepcopy(comment)
    forged["author_association"] = "NONE"
    stale_pr = copy.deepcopy(pull_request)
    stale_pr["head"] = {"sha": "b" * 40}
    conflicting_receipt = copy.deepcopy(receipt)
    conflicting_receipt["run_id"] = "vrun-conflict"
    conflicting = copy.deepcopy(comment)
    conflicting["body"] = (
        "verified issue-set merge authority:\n```json\n"
        + json.dumps(conflicting_receipt, sort_keys=True, separators=(",", ":"))
        + "\n```"
    )

    cases = (
        ([forged], pull_request),
        ([comment], stale_pr),
        ([], pull_request),
        ([comment, conflicting], pull_request),
    )
    for comments, candidate_pr in cases:
        assert (
            _js_neutralized_merge_authority(
                comments, candidate_pr, repository
            )
            is None
        )


def test_production_pr_contract_authenticates_neutralized_merge_authority() -> None:
    workflow = _read_workflow()
    for fragment in (
        "github.rest.issues.listComments",
        "resolveNeutralizedMergeAuthority",
        "TRUSTED_ASSOCIATIONS",
        "receipt.head_sha === pullRequest.head?.sha",
        "liveBody, receipt.neutralized_body_sha256, {allowLegacy}",
        "valid.map(entry => canonicalJson(entry.receipt))",
        "one trusted, non-conflicting exact-head verified-merge authority receipt",
    ):
        assert fragment in workflow


def _read_base_side_recovery() -> str:
    return (REPO_ROOT / "scripts/base_side_pr_contract_recovery.js").read_text(encoding="utf-8")


def test_base_side_pr_contract_recovery_accepts_only_legacy_prepared_immutable_context() -> None:
    recovery = _read_base_side_recovery()
    assert 'prNumber: 4052' in recovery
    assert 'head: "a159571da2ce9068131810aedc1ea05107d7bfaf"' in recovery
    assert 'receipt.phase === "prepared"' in recovery
    assert "requireUniquePreparedPhase(comments, authority)" in recovery


def test_base_side_pr_contract_recovery_binds_live_exact_head_and_receipts() -> None:
    recovery = _read_base_side_recovery()
    for fragment in ("pullRequest.head?.sha !== TARGET.head", "pullRequest.title !== TARGET.title", "closingIssuesReferences(first:20)", "resolveNeutralizedMergeAuthority({comments, issueAuthority, pullRequest, repository: TARGET.repository})", "receipt.authority_sha256 === authoritySha", "receipt.body_sha256 === authority.neutralized_body_sha256", "canonicalJson(authorityRecords[0].receipt) !== canonicalJson(authority)"):
        assert fragment in recovery


def test_base_side_pr_contract_recovery_rejects_noneligible_or_drifted_contexts() -> None:
    recovery = _read_base_side_recovery()
    for fragment in ("repository default branch drifted from main", "recovery must execute from the current default-branch head", "live closing references are not empty", "authority receipt is missing, forged, stale, or conflicting", "prepared phase is missing, stale, forged, conflicting, or non-continuous", 'pullRequest.state !== "open"', "pullRequest.head?.repo?.full_name !== TARGET.repository", "pullRequest.base?.repo?.full_name !== TARGET.repository", "pullRequest.base?.ref !== TARGET.defaultBranch"):
        assert fragment in recovery


def test_base_side_pr_contract_recovery_publishes_only_scoped_auditable_equivalent_check() -> None:
    workflow = (REPO_ROOT / ".github/workflows/base-side-pr-contract-recovery.yml").read_text(encoding="utf-8")
    recovery = _read_base_side_recovery()
    assert "checks: write" in workflow
    assert "workflow_dispatch:" in workflow
    assert 'name: "pr-contract"' in recovery
    assert "head_sha: reread.pull_request.head.sha" in recovery
    assert "base-side-pr-contract-recovery:${authority.run_id}:${reread.pull_request.head.sha}" in recovery
    assert "/statuses" not in recovery
    assert 'method: "PATCH"' not in recovery
    action_refs = re.findall(r"^\s*- uses:\s*([^\s#]+)", workflow, re.MULTILINE)
    assert action_refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)


def test_base_side_pr_contract_recovery_posts_nothing_when_snapshot_mutates() -> None:
    recovery_path = REPO_ROOT / "scripts/base_side_pr_contract_recovery.js"
    script = r"""
const {publishStableSnapshot} = require(process.argv[1]);
const base = {
  default_branch: "main", default_branch_sha: "a".repeat(40),
  pull_request: {number: 4052, state: "open", draft: false, title: "title", body: "body",
    head: {sha: "b".repeat(40), ref: "head", repository: "RasmusTho/agentic-pkm-mvp"},
    base: {sha: "c".repeat(40), ref: "main", repository: "RasmusTho/agentic-pkm-mvp"}},
  closing_issues: [],
  authority: {comment: {id: 1, actor: "owner", association: "OWNER", created_at: "2026-07-21T00:00:00Z", updated_at: "2026-07-21T00:00:00Z"}, receipt: {run_id: "run", repair_budget: {policy_version: "v2"}}},
  phase: {comment: {id: 2, actor: "owner", association: "OWNER", created_at: "2026-07-21T00:00:01Z", updated_at: "2026-07-21T00:00:01Z"}, receipt: {run_id: "run", phase: "prepared"}}
};
const paths = JSON.parse(process.argv[2]);
(async () => {
  const results = [];
  for (const path of paths) {
    const second = JSON.parse(JSON.stringify(base));
    let cursor = second;
    for (const key of path.slice(0, -1)) cursor = cursor[key];
    cursor[path.at(-1)] = typeof cursor[path.at(-1)] === "string" ? `${cursor[path.at(-1)]}-drift` : [4056];
    let reads = 0, posts = 0, failed = false;
    const capture = async () => (++reads === 1 ? base : second);
    const request = async (method, url) => { if (method === "POST" && url.endsWith("/check-runs")) posts += 1; };
    try { await publishStableSnapshot({request, env: {}, capture}); } catch (_) { failed = true; }
    results.push({path, posts, failed});
  }
  process.stdout.write(JSON.stringify(results));
})();
"""
    mutation_paths = [
        ["default_branch_sha"], ["pull_request", "title"],
        ["closing_issues"], ["pull_request", "body"],
        ["pull_request", "head", "sha"], ["pull_request", "base", "ref"],
        ["authority", "comment", "updated_at"],
        ["authority", "receipt", "repair_budget"],
        ["phase", "comment", "actor"], ["phase", "receipt", "phase"],
    ]
    completed = subprocess.run(
        ["node", "-e", script, str(recovery_path), json.dumps(mutation_paths)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    results = json.loads(completed.stdout)
    assert all(result["failed"] and result["posts"] == 0 for result in results)


def test_base_side_pr_contract_recovery_rejects_default_or_pr_base_retarget() -> None:
    recovery_path = REPO_ROOT / "scripts/base_side_pr_contract_recovery.js"
    script = r"""
const {requireExactBaseIdentity} = require(process.argv[1]);
const repo = {default_branch: "main"};
const branch = {commit: {sha: "c".repeat(40)}};
const pr = {number: 4052, state: "open", draft: false,
  title: "Fix CKM metric schema bundle refusal",
  head: {sha: "a159571da2ce9068131810aedc1ea05107d7bfaf", repo: {full_name: "RasmusTho/agentic-pkm-mvp"}},
  base: {ref: "main", repo: {full_name: "RasmusTho/agentic-pkm-mvp"}}};
const env = {GITHUB_REF: "refs/heads/main", GITHUB_SHA: "c".repeat(40)};
const candidates = [
  [{...repo, default_branch: "trunk"}, pr],
  [repo, {...pr, base: {...pr.base, ref: "stable"}}],
  [repo, {...pr, base: {...pr.base, repo: {full_name: "foreign/repo"}}}],
];
const rejected = candidates.map(([candidateRepo, candidatePr]) => {
  try { requireExactBaseIdentity(candidateRepo, branch, candidatePr, env); return false; }
  catch (_) { return true; }
});
process.stdout.write(JSON.stringify(rejected));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(recovery_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [True, True, True]


@pytest.mark.parametrize("separator", [",", ", ", ",\t", ", \t\t"])
def test_verified_merge_neutralized_separator_grammar_matches_javascript_and_python(
    separator: str,
) -> None:
    body = (
        "Governing-Issue: #3821\n"
        "Refs #3820\n"
        "Refs #3823\n"
        f"Verified-Closing-Issues: #3820{separator}#3823\n"
    )

    assert resolve_neutralized_issue_authority(body) == IssueAuthority(
        governing_issue=3821,
        closing_issues=(3820, 3823),
        supporting_issues=(3820, 3823),
    )
    assert _js_issue_authority(body)["neutralizedValid"] is True


@pytest.mark.parametrize(
    "marker",
    [
        "#3820,,#3823",
        "#3820,",
        "#3820,\v#3823",
        "#3820, #invalid",
    ],
)
def test_verified_merge_malformed_neutralized_separator_fails_closed(
    marker: str,
) -> None:
    body = (
        "Governing-Issue: #3821\n"
        "Refs #3820\n"
        "Refs #3823\n"
        f"Verified-Closing-Issues: {marker}\n"
    )

    assert resolve_neutralized_issue_authority(body) is None
    assert _js_issue_authority(body)["neutralizedValid"] is False


@pytest.mark.parametrize(
    "body",
    [
        (
            "Governing-Issue: #3821\nRefs #3820\nRefs #3823\n"
            "Verified-Closing-Issues: #3823, #3820\n"
        ),
        (
            "Governing-Issue: #3821\nRefs #3820\n"
            "Verified-Closing-Issues: #3820, #3820\n"
        ),
        "Governing-Issue: #3821\nVerified-Closing-Issues: #3820\n",
        (
            "Governing-Issue: #3821\nRefs #3820\nFixes #3820\n"
            "Verified-Closing-Issues: #3820\n"
        ),
        (
            "Governing-Issue: #3821\nRefs #3820\n"
            "Verified-Closing-Issues : #3820\n"
        ),
        (
            "Governing-Issue: #3821\n"
            + "\n".join(f"Refs #{4000 + index}" for index in range(11))
            + "\nVerified-Closing-Issues: "
            + ", ".join(f"#{4000 + index}" for index in range(11))
            + "\n"
        ),
    ],
)
def test_verified_merge_neutralized_authority_fails_closed(body: str) -> None:
    assert resolve_neutralized_issue_authority(body) is None
    assert _js_issue_authority(body)["neutralizedValid"] is False


def test_closing_authority_limit_matches_javascript_and_python_contracts() -> None:
    allowed = "\n".join(
        ["Governing-Issue: #3603"]
        + [f"Fixes #{4000 + index}" for index in range(MAX_CLOSING_ISSUES)]
    )
    over_limit = allowed + f"\nFixes #{5000 + MAX_CLOSING_ISSUES}"

    assert _js_issue_authority(allowed)["valid"] is True
    assert resolve_issue_authority(allowed) is not None
    assert _js_issue_authority(over_limit)["valid"] is False
    assert _js_issue_authority(over_limit)["closingIssueCount"] == (
        MAX_CLOSING_ISSUES + 1
    )
    assert resolve_issue_authority(over_limit) is None


@pytest.mark.parametrize(
    "body",
    [
        "- [x] Governance lane",
        "- [x] Docs authoring lane",
        (
            "## Direct Repair\n"
            "Type: governance\n"
            "Reason: bounded\n"
            "Validation: tests\n"
            "Issue required: no"
        ),
    ],
)
def test_issue_free_lanes_do_not_require_governing_identity(body: str) -> None:
    assert _governing_issue_identity_satisfied(body)


def test_default_template_preserves_issue_free_lane_authority() -> None:
    template = (REPO_ROOT / ".github/pull_request_template.md").read_text(
        encoding="utf-8"
    )

    assert not _js_issue_authority(template)["hasIssueAuthority"]
    assert "Fixes #" not in template


@pytest.mark.parametrize(
    ("body", "accepted"),
    [
        ("Governing-Issue: #123\nFixes #123", True),
        ("Governing-Issue: #123\r\nFixes #123\r\n", True),
        ("Governing-Issue: #3603\nRefs #3603\nFixes #3626", True),
        ("Governing-Issue: #3603\nFixed #3626\nCloses: #3698", True),
        ("Governing-Issue: #3603\nfix #3626\nresolved: #3698", True),
        ("Governing-Issue: #123", False),
        ("Governing-Issue: #123\nRefs #123", False),
        ("Governing-Issue: #123\nGoverning-Issue : #456\nFixes #123", False),
        ("Governing-Issue: #123\nGoverning-Issue:\n#456\nFixes #123", False),
        ("Governing-Issue: #123\nGoverning-Issue: #0\nFixes #123", False),
        ("Governing-Issue: #123\nFixes #123é", False),
        ("Governing-Issue: #123\nFixeſ #123", False),
        ("Governıng-Issue: #123\nFixes #123", False),
        ("Governing-Issue: #123\rFixes #123", False),
        ("Governing-Issue: #123\u2028Fixes #123", False),
        ("Governing-Issue: #123\u2029Fixes #123", False),
        ("Governing-Issue: #123\nFixes #123\nCloses #", False),
        ("Governing-Issue: #123\nFixes #123\nCloses # 456", False),
        ("Governing-Issue: #123\nFixes #123\nCloses #\u00a0", False),
        ("Governing-Issue: #123\nFixes #123\nCloses #\u0085", False),
        ("Governing-Issue: #123\nFixes #123\nCloses #\ufeff", False),
        (
            "Governing-Issue: #123\nFixes #123\n"
            "Fixes RasmusTho/agentic-pkm-mvp#456",
            False,
        ),
        (
            "Governing-Issue: #123\nFixes #123\n"
            "Closes: octo-org/octo-repo#456",
            False,
        ),
        (
            "Governing-Issue: #123\nFixes #123\n"
            "Resolves https://github.com/octo-org/octo-repo/issues/456",
            False,
        ),
    ],
)
def test_javascript_and_python_authority_grammar_are_identical(
    body: str,
    accepted: bool,
) -> None:
    assert bool(_js_issue_authority(body)["valid"]) is accepted
    assert (resolve_issue_contract(body) is not None) is accepted


def test_issue_backed_code_pr_requires_builderops_routing_even_with_tier1_checkbox() -> None:
    body = (
        "Fixes #123\n\n"
        "- [x] Governance lane\n\n"
        "## Summary\n"
        "Implementation change."
    )

    assert not _builderops_routing_satisfied(body)


def test_pr_contract_rejects_commit_message_closure_authority() -> None:
    workflow = _read_workflow()

    assert "github.rest.pulls.listCommits" in workflow
    assert "commitClosureAttempt" in workflow
    assert "commit-message closing references are forbidden" in workflow


def test_commit_message_closing_keywords_are_forbidden() -> None:
    guidance = (
        REPO_ROOT / ".codex" / "skills" / "publish-pr" / "SKILL.md"
    ).read_text(encoding="utf-8")
    workflow = _read_workflow()

    for keyword in (
        "Fix",
        "Fixes",
        "Fixed",
        "Close",
        "Closes",
        "Closed",
        "Resolve",
        "Resolves",
        "Resolved",
    ):
        assert f"`{keyword}`" in guidance
    assert "as an issue-closing reference" in guidance
    assert "Ordinary non-target prose such as `Fix runtime env` is allowed" in guidance
    assert "Start with imperative verb (Add, Update, Rebuild, etc.)" in guidance
    assert "Start with imperative verb (Fix, Add, Update, Rebuild, etc.)" not in guidance
    assert "Never include any issue-closing keyword in the commit subject or body" not in guidance
    # The citation targets the workflow's `// authority-classifier:start`
    # marker so it stays resolvable under the section-citation lint (#4297).
    assert ".github/workflows/issue-pr-governance.yml :: authority-classifier" in guidance
    assert "const closingKeyword =" in workflow
    assert "closingAttemptSeparator" in workflow
    assert "closingAttemptTarget" in workflow
    assert "Use evidence-only `Refs #<id>`" in guidance


def test_pr_body_closing_keywords_remain_required_for_issue_backed_prs() -> None:
    guidance = (
        REPO_ROOT / ".codex" / "skills" / "publish-pr" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "Governing-Issue: #<ISSUE_NUMBER>" in guidance
    assert "Fixes #<ISSUE_NUMBER>" in guidance
    assert "closing keywords only for fully delivered" in guidance


def test_pr_contract_rejects_incomplete_commit_enumeration() -> None:
    workflow = _read_workflow()

    assert "commits.length !== pullRequest.commits" in workflow
    assert "PR commit enumeration is incomplete or malformed" in workflow
    assert "GitHub caps the pull-request commit list" in workflow


def test_pr_contract_rejects_title_closure_authority() -> None:
    workflow = _read_workflow()

    assert "const titleClosureAttempt = classifyIssueAuthority(" in workflow
    assert 'pullRequest.title || ""' in workflow
    assert "Closing keywords are forbidden in the PR title" in workflow


def test_pr_contract_rejects_repository_qualified_closure_authority() -> None:
    workflow = _read_workflow()

    assert "closingAttemptTarget" in workflow
    assert "[0-9A-Za-z_.-]+/[0-9A-Za-z_.-]+#" in workflow


@pytest.mark.parametrize("surface", ["body", "title", "commit"])
def test_pr_contract_rejects_github_url_closure_on_every_production_surface(
    surface: str,
) -> None:
    url_attempt = "Fixes https://github.com/octo-org/octo-repo/issues/456"
    candidate = (
        f"Governing-Issue: #123\nFixes #123\n{url_attempt}"
        if surface == "body"
        else url_attempt
    )

    authority = _js_issue_authority(candidate)

    assert authority["hasIssueAuthority"] is True
    assert authority["issueLinkMentions"]
    if surface == "body":
        assert authority["valid"] is False
    else:
        workflow = _read_workflow()
        production_check = {
            "title": "titleClosureAttempt",
            "commit": "commitClosureAttempt",
        }[surface]
        assert production_check in workflow


def test_mixed_tier_pr_uses_highest_required_tier() -> None:
    mixed_without_routing = (
        "Closes #456\n\n"
        "- [x] Docs authoring lane\n\n"
        "## Summary\n"
        "Changes code and docs."
    )
    tier1_without_issue = "- [x] Docs authoring lane\n\n## Summary\nDocs-only wording."
    mixed_with_routing = (
        "Closes #456\n\n"
        "- [x] Docs authoring lane\n\n"
        "## BuilderOps Routing\n"
        "- Records/projections/receipts: none\n"
        "- Reason: no operational BuilderOps material produced\n"
    )

    assert not _builderops_routing_satisfied(mixed_without_routing)
    assert _builderops_routing_satisfied(tier1_without_issue)
    assert _builderops_routing_satisfied(mixed_with_routing)


def test_workflow_checks_issue_link_before_allowing_tier1_builderops_omission() -> None:
    text = _read_workflow()

    assert "// authority-classifier:start" in text
    assert "const issueAuthority = classifyIssueAuthority(body);" in text
    assert "isTier1Lane && !hasIssueAuthority && !builderOpsRoutingSection" in text
    # resolveBuilderOpsRouting is a pure function (defined ahead of body-execution
    # order, see // builderops-routing:start/:end); the ordering invariant that
    # matters is the *call site* using the already-classified hasIssueAuthority,
    # not the function definition.
    assert text.index("const issueAuthority = classifyIssueAuthority(body);") < text.index(
        "const builderOpsRouting = resolveBuilderOpsRouting(body, hasIssueAuthority);"
    )


def test_workflow_requires_exactly_one_positive_governing_identity_for_issue_backed_prs() -> None:
    text = _read_workflow()

    for fragment in (
        "const governingIssueLines =",
        "const exactGoverningIssueMatches =",
        "const issueLinkMentions =",
        "const exactIssueLinkMatches =",
        "const hasIssueAuthority =",
        "const valid =",
        "if (!issueAuthority.valid && !issueAuthority.neutralizedValid)",
        "exactly one positive `Governing-Issue: #<id>` line",
        "Verified-Closing-Issues: #<id>[, #<id>]",
    ):
        assert fragment in text, fragment


def test_issue_readiness_workflow_is_strict_for_agent_ready_only() -> None:
    text = _read_workflow()
    readiness_job = text.split("  issue-readiness:", 1)[1].split("\n  pr-contract:", 1)[0]

    assert "permissions:" in readiness_job
    assert "contents: read" in readiness_job
    assert "issues: read" in readiness_job
    assert "issues: write" not in readiness_job
    assert "actions/upload-artifact@v4" in readiness_job
    assert "if: always()" in readiness_job
    assert 'if [[ ",$LABELS," == *",agent:ready,"* ]]; then' in readiness_job
    assert "validate_issue_readiness.py" in readiness_job
    ready_branch = readiness_job.split(
        'if [[ ",$LABELS," == *",agent:ready,"* ]]; then',
        1,
    )[1].split("else", 1)[0]
    observe_branch = readiness_job.split("else", 1)[1].split("fi", 1)[0]
    assert "--observe-only" not in ready_branch
    assert 'python3 scripts/validate_issue_readiness.py "${readiness_args[@]}"' in ready_branch
    assert "--observe-only" in observe_branch
    assert "gh issue edit" not in readiness_job
    assert "removeLabel" not in readiness_job
    assert "addLabels" not in readiness_job
    assert "graphql" not in readiness_job.lower()
    assert "dispatcher" not in readiness_job.lower()


def test_issue_readiness_checker_is_governance_lane_allowed() -> None:
    text = _read_workflow()

    assert '"scripts/validate_issue_readiness.py"' in text
    assert '"tests/scripts/test_validate_issue_readiness.py"' in text
    assert '"tests/fixtures/issue_readiness/"' in text


def test_pr_body_generator_fixtures_are_governance_lane_allowed() -> None:
    text = _read_workflow()

    assert '"scripts/pr_body_generator.py"' in text
    assert '"tests/scripts/test_pr_body_generator.py"' in text
    assert '"tests/fixtures/pr_body_generator/"' in text


def test_autonomous_runner_prompt_is_governance_lane_allowed() -> None:
    text = _read_workflow()
    exact = text.split("const governanceAllowedExact = new Set([", 1)[1].split("]);", 1)[0]
    prefixes = text.split("const governanceAllowedPrefixes = [", 1)[1].split("];", 1)[0]

    assert '"companion-ui/prompts/codex/deliver-epic-autonomous-runner.md"' in exact
    assert '"companion-ui/prompts/codex/deliver-epic-autonomous-runner.md"' not in prefixes


def test_yggdrasil_design_handoff_surfaces_are_governance_lane_allowed() -> None:
    text = _read_workflow()
    exact = text.split("const governanceAllowedExact = new Set([", 1)[1].split("]);", 1)[0]
    prefixes = text.split("const governanceAllowedPrefixes = [", 1)[1].split("];", 1)[0]

    assert '"companion-ui/design_handoff/README.md"' in exact
    assert '"companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md"' in exact
    assert '"companion-ui/prompts/claude-design/"' in prefixes


def test_governance_lane_companion_prompt_surface_matches_owner_doc() -> None:
    workflow = _read_development_workflow()
    governance_lane = workflow.split("## Governance lane", 1)[1].split(
        "## Runtime separation", 1
    )[0]

    assert (
        "`companion-ui/prompts/codex/deliver-epic-autonomous-runner.md`"
        in governance_lane
    )


def test_governance_lane_allowed_surfaces_match_owner_doc() -> None:
    workflow = _read_development_workflow()
    governance_lane = workflow.split("## Governance lane", 1)[1].split(
        "Governance-lane rules:", 1
    )[0]
    documented = set(re.findall(r"^  - `([^`]+)`$", governance_lane, re.MULTILINE))
    documented_exact = {path for path in documented if not path.endswith("**")}
    documented_prefixes = {
        path.removesuffix("**") for path in documented if path.endswith("**")
    }

    contract = _read_workflow()
    exact_block = contract.split("const governanceAllowedExact = new Set([", 1)[1].split(
        "]);", 1
    )[0]
    prefix_block = contract.split("const governanceAllowedPrefixes = [", 1)[1].split(
        "];", 1
    )[0]
    executable_exact = set(re.findall(r'^\s+"([^"]+)",?$', exact_block, re.MULTILINE))
    executable_prefixes = set(
        re.findall(r'^\s+"([^"]+)",?$', prefix_block, re.MULTILINE)
    )

    assert documented_exact == executable_exact
    assert documented_prefixes == executable_prefixes


def test_review_before_ci_gate_is_governance_lane_allowed() -> None:
    text = _read_workflow()

    assert '"scripts/review_before_ci_gate.py"' in text
    assert '"tests/ops/test_review_before_ci_gate.py"' in text


def test_host_global_lease_is_governance_lane_allowed() -> None:
    text = _read_workflow()

    assert '"scripts/run_with_host_lease.py"' in text
    assert '"scripts/py312_smoke_test.sh"' in text
    assert '"scripts/verify_runtime_chain.sh"' in text
    assert '"tests/ops/test_host_global_lease.py"' in text
