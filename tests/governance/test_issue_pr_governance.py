from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

_BUILDEROPS_ROUTING_REGEX = re.compile(
    r"(?:^|\n)## BuilderOps Routing[\s\S]*?(?=\n##\s|\n---)|(?:^|\n)## BuilderOps Routing[\s\S]*",
    re.IGNORECASE,
)
_BUILDEROPS_ROUTING_FIELDS = (
    re.compile(
        r"(?:^|\n)\s*-\s*Records/projections/receipts:\s*(.*?)\s*(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:^|\n)\s*-\s*Reason:\s*(.*?)\s*(?:\n|$)", re.IGNORECASE),
)
_TIER1_LANE_REGEX = re.compile(
    r"^\-\s+\[x\]\s+(?:Docs authoring|Governance) lane\b",
    re.IGNORECASE | re.MULTILINE,
)
_ISSUE_LINK_REGEX = re.compile(r"(Fixes|Closes|Resolves)\s+#\d+", re.IGNORECASE)
_GOVERNING_ISSUE_LINE_REGEX = re.compile(
    r"^\s*Governing-Issue\s*:.*$", re.IGNORECASE | re.MULTILINE
)
_EXACT_GOVERNING_ISSUE_REGEX = re.compile(
    r"^\s*Governing-Issue:\s*#([1-9][0-9]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _read_workflow() -> str:
    return (REPO_ROOT / ".github/workflows/issue-pr-governance.yml").read_text(
        encoding="utf-8"
    )


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


def _has_builderops_routing(body: str) -> bool:
    match = _BUILDEROPS_ROUTING_REGEX.search(body)
    if not match:
        return False
    section = match.group(0)
    for pattern in _BUILDEROPS_ROUTING_FIELDS:
        field = pattern.search(section)
        if not field:
            return False
        value = field.group(1).strip()
        if not value or re.fullmatch(r"<.*>", value):
            return False
    return True


def _builderops_routing_satisfied(body: str) -> bool:
    if _has_builderops_routing(body):
        return True
    return (
        _TIER1_LANE_REGEX.search(body) is not None
        and _ISSUE_LINK_REGEX.search(body) is None
        and _BUILDEROPS_ROUTING_REGEX.search(body) is None
    )


def _governing_issue_identity_satisfied(body: str) -> bool:
    if _ISSUE_LINK_REGEX.search(body) is None:
        return True
    return (
        len(_GOVERNING_ISSUE_LINE_REGEX.findall(body)) == 1
        and len(_EXACT_GOVERNING_ISSUE_REGEX.findall(body)) == 1
    )


@pytest.mark.parametrize(
    "body",
    [
        "Fixes #123",
        "Governing-Issue: #\nFixes #123",
        "Governing-Issue: #0\nFixes #123",
        "Governing-Issue: #-1\nFixes #123",
        "Governing-Issue: #123\nGoverning-Issue: #456\nFixes #123",
        "Governing-Issue : #123\nFixes #123",
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


def test_issue_free_governance_pr_does_not_require_governing_identity() -> None:
    assert _governing_issue_identity_satisfied("- [x] Governance lane")


def test_issue_backed_code_pr_requires_builderops_routing_even_with_tier1_checkbox() -> None:
    body = (
        "Fixes #123\n\n"
        "- [x] Governance lane\n\n"
        "## Summary\n"
        "Implementation change."
    )

    assert not _builderops_routing_satisfied(body)


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

    assert "const hasIssueLink = issueLinkPattern.test(body);" in text
    assert "isTier1Lane && !hasIssueLink && !builderOpsRoutingSection" in text
    assert text.index("const hasIssueLink = issueLinkPattern.test(body);") < text.index(
        "const builderOpsRoutingSatisfied ="
    )


def test_workflow_requires_exactly_one_positive_governing_identity_for_issue_backed_prs() -> None:
    text = _read_workflow()

    for fragment in (
        "const governingIssueLines =",
        "const exactGoverningIssueMatches =",
        "governingIssueLines.length !== 1",
        "exactGoverningIssueMatches.length !== 1",
        "exactly one positive `Governing-Issue: #<id>` line",
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


def test_governance_lane_companion_prompt_surface_matches_owner_doc() -> None:
    workflow = _read_development_workflow()
    governance_lane = workflow.split("## Governance lane", 1)[1].split(
        "## Runtime separation", 1
    )[0]

    assert (
        "`companion-ui/prompts/codex/deliver-epic-autonomous-runner.md`"
        in governance_lane
    )


def test_review_before_ci_gate_is_governance_lane_allowed() -> None:
    text = _read_workflow()

    assert '"scripts/review_before_ci_gate.py"' in text
    assert '"tests/ops/test_review_before_ci_gate.py"' in text
