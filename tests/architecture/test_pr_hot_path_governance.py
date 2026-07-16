"""Architecture tests for the hot-path PR governance contract.

These checks are intentionally cheap and text-based. They protect the direct-repair
and lightweight workflow invariants without pulling runtime smoke into docs or
skill-only changes.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    assert path.exists(), f"Missing expected file: {rel_path}"
    return path.read_text(encoding="utf-8")


def test_hot_path_doc_defers_escalation_and_names_direct_repair_contract() -> None:
    text = _read("docs/development/PR_HOT_PATH.md")

    for fragment in (
        "PR_ESCALATION_PATHS.md",
        "## Direct Repair",
        "Type: docs | governance | code",
        "Validation: <checks run>",
        "## BuilderOps Routing",
        "Records/projections/receipts:",
        "Direct repair PRs are allowed without a governing issue when the change is bounded, immediate, and the PR body contains a complete Direct Repair block.",
        "The `Direct Repair` block is the contract for bounded direct repair PRs. The `BuilderOps Routing`",
        "If the `Direct Repair` block is present and complete, no separate lane checkbox is required.",
        "failing required tests or checks must be classified before merge",
        "delivery traceability must be preserved through either an issue-backed PR or a direct repair block",
    ):
        assert fragment in text, fragment


def test_pr_integration_skill_allows_issue_backed_or_direct_repair_prs() -> None:
    text = _read(".codex/skills/pr-integration/SKILL.md")

    for fragment in (
        "an issue-backed PR exists with a bounded governing slice Issue",
        "a bounded direct repair PR exists whose body contains a complete `Direct Repair` block.",
        "A governing issue is required for normal planned workflow; a bounded direct repair PR may proceed without one",
        "Do not require a separate governance/docs lane checkbox when the `Direct Repair` block already states `Type` and `Validation`.",
        "Missing issue traceability is an escalation trigger only when the PR is neither issue-backed nor a valid direct repair PR.",
    ):
        assert fragment in text, fragment


def test_verification_skill_distinguishes_issue_backed_and_direct_repair_modes() -> None:
    text = _read(".codex/skills/verification-and-closure/SKILL.md")

    for fragment in (
        "For issue-backed PRs, close the exact closing issues and update the governing issue",
        "For direct repair PRs, verify the `Direct Repair` block instead of issue ACs.",
        "Do not create an Issue after the fact solely for a bounded direct repair.",
        "Direct repair merged: PR #<n>, type=<type>, validation=<checks>.",
    ):
        assert fragment in text, fragment


def test_verification_execution_checklist_uses_exact_closing_issue_set() -> None:
    text = _read(".codex/skills/verification-and-closure/SKILL.md")

    for fragment in (
        "explicitly close every and only the authenticated `closing_issues`",
        "remove all agent labels from every closed issue",
        "never project an unclosed governing parent `Done`",
        "same PR-specific\n    result on every exact closed issue",
        "governing/closing identities equal the\n   durable receipt",
        "bounded monotonic supporting additions may be retained only as evidence",
    ):
        assert fragment in text


def test_verification_merge_uses_fixed_non_closing_commit_identity() -> None:
    text = _read(".codex/skills/verification-and-closure/SKILL.md")
    normalized_text = " ".join(text.split())

    for fragment in (
        "reject any mismatch or title closing attempt",
        "exact-head REST endpoint using the verified SHA",
        "fixed non-closing commit title/message",
        "Never use GitHub-synthesized or caller-supplied free-form merge text",
        "prove its title/message contains no canonical or malformed closing attempt",
        "converts every authenticated closer to evidence-only `Refs`",
        "`closingIssuesReferences` is empty",
    ):
        assert fragment in normalized_text


def test_issue_to_code_skill_accepts_direct_repair_without_unconditional_issue_traceability() -> None:
    text = _read(".codex/skills/issue-to-code/SKILL.md")

    for fragment in (
        "Bounded direct repair PRs may proceed without a governing Issue when the PR body supplies the full contract via a complete Direct Repair block.",
        "For a bounded direct repair PR, treat the PR body as the contract and validate the Direct Repair block directly instead of requiring a governing Issue.",
        "Route only triggered cases to `docs/development/PR_ESCALATION_PATHS.md` or the heavier `pr-integration` path.",
    ):
        assert fragment in text, fragment


def test_issue_to_code_requires_canonical_issue_authority_at_publication() -> None:
    text = _read(".codex/skills/issue-to-code/SKILL.md")

    for fragment in (
        "exactly one `Governing-Issue: #<issue>` line",
        "closing-keyword line for fully delivered work",
        "approved multi-Issue PR",
        "PR_HOT_PATH.md :: Multi-Issue PR Scope",
    ):
        assert fragment in " ".join(text.split())


def test_issue_pr_governance_accepts_direct_repair_block_without_lane_checkbox() -> None:
    text = _read(".github/workflows/issue-pr-governance.yml")

    for fragment in (
        "const directRepairSectionMatch = body.match(/## Direct Repair",
        "const builderOpsRoutingMatch = body.match(/(?:^|\\n)## BuilderOps Routing",
        "const hasBuilderOpsRouting =",
        "const tier1LanePattern =",
        "const classifyIssueAuthority =",
        "const hasIssueAuthority =",
        "const builderOpsRoutingSatisfied =",
        "PR body must include `## BuilderOps Routing`",
        "const isDirectRepair =",
        "if (isDirectRepair) {",
        "includes a complete `Direct Repair` block",
        "Docs authoring lane",
        "Governance lane",
        "tests/architecture/test_pr_hot_path_governance.py",
    ):
        assert fragment in text, fragment

    assert text.index("const directRepairSectionMatch = body.match(/## Direct Repair") < text.index(
        "const docsAuthoringPattern ="
    )
    assert text.index("const builderOpsRoutingMatch = body.match(/(?:^|\\n)## BuilderOps Routing") < text.index(
        "const classifyIssueAuthority ="
    )
    assert text.index("if (isDirectRepair) {") < text.index("const docsAuthoringPattern =")


def test_pr_template_includes_builderops_routing_receipt() -> None:
    text = _read(".github/pull_request_template.md")

    for fragment in (
        "## BuilderOps Routing",
        "Records/projections/receipts:",
        "Reason:",
    ):
        assert fragment in text, fragment


def test_publication_surfaces_require_governing_issue_identity() -> None:
    template = _read(".github/pull_request_template.md")
    publish_skill = _read(".codex/skills/publish-pr/SKILL.md")

    assert "Governing-Issue: #" in template
    assert "Governing-Issue: #<ISSUE_NUMBER>" in publish_skill
    assert "Fixes #<ISSUE_NUMBER>" in publish_skill


def test_canonical_agent_rules_allow_open_multi_issue_governor() -> None:
    agents = _read("AGENTS.md")
    normalized_agents = " ".join(agents.split())

    for fragment in (
        "exactly one `Governing-Issue: #<id>` line",
        "the governing parent may remain open",
        "closing keywords name only the fully delivered issues",
        "PR_HOT_PATH.md :: Multi-Issue PR Scope",
    ):
        assert fragment in normalized_agents


def test_open_governing_parent_uses_issue_set_gate_not_unfinished_feature_acs() -> None:
    agents = " ".join(_read("AGENTS.md").split())
    hot_path = " ".join(_read("docs/development/PR_HOT_PATH.md").split())
    closure_skill = " ".join(
        _read(".codex/skills/verification-and-closure/SKILL.md").split()
    )

    for text in (agents, hot_path, closure_skill):
        assert "exact closing" in text
        assert "issue-set contract" in text
        assert "unfinished feature" in text
        assert "do not block delivery" in text
    assert "all acceptance criteria from the governing Issue" not in closure_skill


def test_canonical_merge_policy_neutralizes_mutable_body_closers() -> None:
    agents = " ".join(_read("AGENTS.md").split())
    hot_path = " ".join(_read("docs/development/PR_HOT_PATH.md").split())
    closure_skill = " ".join(
        _read(".codex/skills/verification-and-closure/SKILL.md").split()
    )

    for fragment in (
        "neutralize",
        "fixed non-closing",
        "explicitly close",
        "authenticated issue set",
        "race-added",
        "restoring the authenticated body",
        "durable receipt",
    ):
        assert (
            fragment in agents.lower()
            or fragment in hot_path.lower()
            or fragment in closure_skill.lower()
        )
    for fragment in (
        "scripts/prepare_verified_issue_set_merge.py",
        "closingIssuesReferences` is empty",
        "latest `pr-contract` run triggered by that `edited` event",
        "Never reuse the pre-edit green `pr-contract` result",
        "explicitly close every and only",
        "plan_post_merge_reconciliation",
        "restore the authenticated original PR body",
    ):
        assert fragment in closure_skill


def test_owner_doc_policy_requires_pr_specific_child_and_open_parent_receipts() -> None:
    agents = " ".join(_read("AGENTS.md").split())
    hot_path = " ".join(_read("docs/development/PR_HOT_PATH.md").split())
    closure_skill = " ".join(
        _read(".codex/skills/verification-and-closure/SKILL.md").split()
    )
    owner_doc_skill = " ".join(
        _read(".codex/skills/post-merge-owner-doc/SKILL.md").split()
    )

    assert "post-merge owner-doc result is PR-specific" in agents
    assert "every exact closed issue" in agents
    assert "distinct open governing parent" in agents
    assert "generic receipt or one for another PR" in agents
    assert "PR-specific receipt on every closed child" in hot_path
    assert "every exact closed issue" in closure_skill
    assert "post-merge owner-doc check: PR #<PR>;" in closure_skill
    assert "every exact authenticated closing issue" in owner_doc_skill
    assert "distinct open governing parent" in owner_doc_skill
    assert "generic receipt" in owner_doc_skill


import re as _re


_REQUIRED_FIELDS_PATTERNS = [
    _re.compile(r"(?:^|\n)Type:\s*(docs|governance|code)\s*(?:\n|$)", _re.IGNORECASE),
    _re.compile(r"(?:^|\n)Reason:\s*\S", _re.IGNORECASE),
    _re.compile(r"(?:^|\n)Validation:\s*\S", _re.IGNORECASE),
    _re.compile(r"(?:^|\n)Issue required:\s*no\b", _re.IGNORECASE),
]

_DIRECT_REPAIR_REGEX = _re.compile(
    r"## Direct Repair[\s\S]*?(?=\n##\s|\n---)|## Direct Repair[\s\S]*",
    _re.IGNORECASE,
)
_BUILDEROPS_ROUTING_REGEX = _re.compile(
    r"(?:^|\n)## BuilderOps Routing[\s\S]*?(?=\n##\s|\n---)|(?:^|\n)## BuilderOps Routing[\s\S]*",
    _re.IGNORECASE,
)
_BUILDEROPS_ROUTING_FIELDS = [
    _re.compile(r"(?:^|\n)\s*-\s*Records/projections/receipts:\s*(.*?)\s*(?:\n|$)", _re.IGNORECASE),
    _re.compile(r"(?:^|\n)\s*-\s*Reason:\s*(.*?)\s*(?:\n|$)", _re.IGNORECASE),
]


def _is_direct_repair(body: str) -> bool:
    """Python port of the JavaScript `isDirectRepair` logic in issue-pr-governance.yml."""
    m = _DIRECT_REPAIR_REGEX.search(body)
    if not m:
        return False
    section = m.group(0)
    return all(p.search(section) for p in _REQUIRED_FIELDS_PATTERNS)


def _has_builderops_routing(body: str) -> bool:
    """Python port of the JavaScript `hasBuilderOpsRouting` logic."""
    m = _BUILDEROPS_ROUTING_REGEX.search(body)
    if not m:
        return False
    section = m.group(0)
    for pattern in _BUILDEROPS_ROUTING_FIELDS:
        match = pattern.search(section)
        if not match:
            return False
        value = match.group(1).strip()
        if not value or _re.fullmatch(r"<.*>", value):
            return False
    return True


_TIER1_LANE_REGEX = _re.compile(
    r"^\-\s+\[x\]\s+(?:Docs authoring|Governance) lane\b",
    _re.IGNORECASE | _re.MULTILINE,
)


def _builderops_routing_satisfied(body: str) -> bool:
    """Python port of the JavaScript `builderOpsRoutingSatisfied` logic.

    Tier 1 lane PRs (docs/development/GOVERNANCE_PROPORTIONALITY.md) may omit the
    BuilderOps Routing section entirely only when they are not issue-backed —
    absence means "none". A present but unfilled section is still rejected at
    every tier, and issue-backed PRs use the higher Tier 2+ requirement.
    """
    if _has_builderops_routing(body):
        return True
    section_present = bool(_BUILDEROPS_ROUTING_REGEX.search(body))
    has_issue_link = _re.search(r"(Fixes|Closes|Resolves)\s+#\d+", body, _re.IGNORECASE)
    return (
        _TIER1_LANE_REGEX.search(body) is not None
        and has_issue_link is None
        and not section_present
    )


_VALID_DIRECT_REPAIR_FIELDS = (
    "Type: governance\nReason: bounded fix\nValidation: git diff --check\nIssue required: no"
)

_VALID_BUILDEROPS_ROUTING = (
    "## BuilderOps Routing\n"
    "- Records/projections/receipts: none\n"
    "- Reason: no operational BuilderOps material produced"
)


def test_direct_repair_accepted_when_block_is_first_section() -> None:
    """AC1: Direct Repair block followed by another section."""
    body = (
        f"## Direct Repair\n{_VALID_DIRECT_REPAIR_FIELDS}\n\n"
        f"{_VALID_BUILDEROPS_ROUTING}\n\n"
        "## Summary\nSome summary here."
    )
    assert _is_direct_repair(body), "Expected direct repair to be accepted when block is first"
    assert _has_builderops_routing(body), "Expected BuilderOps routing to be accepted"


def test_direct_repair_accepted_when_block_is_last_section_no_trailing_newline() -> None:
    """AC2: Direct Repair block at end with no trailing newline (GitHub strips trailing whitespace)."""
    body = (
        "## Summary\nSome summary here.\n\n"
        f"{_VALID_BUILDEROPS_ROUTING}\n\n"
        f"## Direct Repair\n{_VALID_DIRECT_REPAIR_FIELDS}"
    )
    # No trailing newline — this was the failing case before the regex fix
    assert not body.endswith("\n"), "Fixture must have no trailing newline to reproduce the bug"
    assert _is_direct_repair(body), "Expected direct repair to be accepted when block is last with no trailing newline"
    assert _has_builderops_routing(body), "Expected BuilderOps routing to be accepted"


def test_direct_repair_accepted_when_block_is_middle_section() -> None:
    """AC3: Direct Repair block surrounded by other sections."""
    body = (
        "## Summary\nSome summary.\n\n"
        f"## Direct Repair\n{_VALID_DIRECT_REPAIR_FIELDS}\n\n"
        f"{_VALID_BUILDEROPS_ROUTING}\n\n"
        "## Runtime behavior\nNo change."
    )
    assert _is_direct_repair(body), "Expected direct repair to be accepted when block is in the middle"
    assert _has_builderops_routing(body), "Expected BuilderOps routing to be accepted"


def test_builderops_routing_required_fields() -> None:
    """PR contract requires an explicit BuilderOps routing receipt."""
    valid_body = f"Fixes #123\n\n{_VALID_BUILDEROPS_ROUTING}"
    assert _has_builderops_routing(valid_body), "Expected BuilderOps routing section to be accepted"

    missing_records = "## BuilderOps Routing\n- Reason: no operational BuilderOps material produced"
    assert not _has_builderops_routing(missing_records), "Expected missing records line to be rejected"

    missing_reason = "## BuilderOps Routing\n- Records/projections/receipts: none"
    assert not _has_builderops_routing(missing_reason), "Expected missing reason line to be rejected"

    template_placeholders = (
        '## BuilderOps Routing\n'
        '- Records/projections/receipts: <ids or "none">\n'
        "- Reason: <why no BuilderOps material was created, or what was routed>"
    )
    assert not _has_builderops_routing(template_placeholders), "Expected unchanged template placeholders to be rejected"


def test_tier1_lane_pr_may_omit_builderops_routing() -> None:
    """Proportionality Tier 1: docs/governance lane PRs pass without the section (absence = none)."""
    governance_body = "- [x] Governance lane\n\n## Summary\nSkill text fix."
    assert _builderops_routing_satisfied(governance_body), "Expected governance-lane PR without section to pass"

    docs_body = "- [x] Docs authoring lane\n\n## Summary\nDocs clarification."
    assert _builderops_routing_satisfied(docs_body), "Expected docs-lane PR without section to pass"


def test_tier1_lane_pr_with_unfilled_section_still_rejected() -> None:
    """A present-but-placeholder BuilderOps Routing section fails even on Tier 1."""
    body = (
        "- [x] Governance lane\n\n"
        '## BuilderOps Routing\n'
        '- Records/projections/receipts: <ids or "none">\n'
        "- Reason: <why no BuilderOps material was created, or what was routed>"
    )
    assert not _builderops_routing_satisfied(body), "Expected unfilled section to be rejected on Tier 1"


def test_inline_section_name_mention_is_not_mistaken_for_the_section() -> None:
    """An inline prose mention of `## BuilderOps Routing` before the real section must not
    shadow it (regression: PR #1813 body described this very check and tripped the
    unanchored first-occurrence match)."""
    body = (
        "Fixes #123\n\n"
        "## Changes\n"
        "2. CI: `## BuilderOps Routing` remains required for Tier 2+.\n\n"
        f"{_VALID_BUILDEROPS_ROUTING}\n\n"
        "---"
    )
    assert _has_builderops_routing(body), "Expected the real section to be found despite inline mention"


def test_non_tier1_pr_still_requires_builderops_routing() -> None:
    """Tier 2+ (no lane checkbox) keeps the unconditional requirement."""
    body = "Fixes #123\n\n## Summary\nImplementation change."
    assert not _builderops_routing_satisfied(body), "Expected implementation PR without section to be rejected"

    valid_body = f"Fixes #123\n\n{_VALID_BUILDEROPS_ROUTING}"
    assert _builderops_routing_satisfied(valid_body), "Expected concrete section to satisfy at any tier"


def test_issue_backed_tier1_lane_pr_still_requires_builderops_routing() -> None:
    body = "Fixes #123\n\n- [x] Governance lane\n\n## Summary\nImplementation change."
    assert not _builderops_routing_satisfied(body), (
        "Expected issue-backed PR with stale Tier 1 checkbox to require BuilderOps routing"
    )


def test_direct_repair_rejected_when_fields_incomplete() -> None:
    """AC4: Body with Direct Repair block but missing required fields is rejected."""
    # Missing 'Issue required: no'
    body = "## Direct Repair\nType: governance\nReason: bounded fix\nValidation: git diff --check"
    assert not _is_direct_repair(body), "Expected direct repair to be rejected when fields are incomplete"

    # Missing 'Validation:'
    body2 = "## Direct Repair\nType: governance\nReason: bounded fix\nIssue required: no"
    assert not _is_direct_repair(body2), "Expected direct repair to be rejected when Validation is missing"

    # Missing 'Reason:'
    body3 = "## Direct Repair\nType: governance\nValidation: git diff\nIssue required: no"
    assert not _is_direct_repair(body3), "Expected direct repair to be rejected when Reason is missing"

    # Invalid Type value
    body4 = "## Direct Repair\nType: feature\nReason: fix\nValidation: git diff\nIssue required: no"
    assert not _is_direct_repair(body4), "Expected direct repair to be rejected when Type value is invalid"


def test_parent_issue_closure_keeps_delivery_scope_above_future_adoption() -> None:
    text = _read("docs/development/PARENT_ISSUE_CLOSURE.md")

    for fragment in (
        "Parent closure is not part of the default PR hot path unless this PR is the final child slice.",
        "Future adoption over N deliveries must not block closure of delivered, repo-verifiable scope.",
        "If the delivered scope is complete and the remaining work is only observation or follow-up learning, close the parent",
    ):
        assert fragment in text, fragment
