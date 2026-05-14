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
        "Direct repair PRs are allowed without a governing issue when the change is bounded, immediate, and the PR body contains a complete Direct Repair block.",
        "If this block is present and complete, no separate lane checkbox is required.",
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
        "For issue-backed PRs, close or update the governing Issue as usual.",
        "For direct repair PRs, verify the `Direct Repair` block instead of issue ACs.",
        "Do not create an Issue after the fact solely for a bounded direct repair.",
        "Direct repair merged: PR #<n>, type=<type>, validation=<checks>.",
    ):
        assert fragment in text, fragment


def test_issue_to_code_skill_accepts_direct_repair_without_unconditional_issue_traceability() -> None:
    text = _read(".codex/skills/issue-to-code/SKILL.md")

    for fragment in (
        "Bounded direct repair PRs may proceed without a governing Issue when the PR body supplies the full contract via a complete Direct Repair block.",
        "For a bounded direct repair PR, treat the PR body as the contract and validate the Direct Repair block directly instead of requiring a governing Issue.",
        "Route only triggered cases to `docs/development/PR_ESCALATION_PATHS.md` or the heavier `pr-integration` path.",
    ):
        assert fragment in text, fragment


def test_issue_pr_governance_accepts_direct_repair_block_without_lane_checkbox() -> None:
    text = _read(".github/workflows/issue-pr-governance.yml")

    for fragment in (
        "const directRepairSectionMatch = body.match(/## Direct Repair",
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
    assert text.index("if (isDirectRepair) {") < text.index("const docsAuthoringPattern =")


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


def _is_direct_repair(body: str) -> bool:
    """Python port of the JavaScript `isDirectRepair` logic in issue-pr-governance.yml."""
    m = _DIRECT_REPAIR_REGEX.search(body)
    if not m:
        return False
    section = m.group(0)
    return all(p.search(section) for p in _REQUIRED_FIELDS_PATTERNS)


_VALID_DIRECT_REPAIR_FIELDS = (
    "Type: governance\nReason: bounded fix\nValidation: git diff --check\nIssue required: no"
)


def test_direct_repair_accepted_when_block_is_first_section() -> None:
    """AC1: Direct Repair block followed by another section."""
    body = f"## Direct Repair\n{_VALID_DIRECT_REPAIR_FIELDS}\n\n## Summary\nSome summary here."
    assert _is_direct_repair(body), "Expected direct repair to be accepted when block is first"


def test_direct_repair_accepted_when_block_is_last_section_no_trailing_newline() -> None:
    """AC2: Direct Repair block at end with no trailing newline (GitHub strips trailing whitespace)."""
    body = f"## Summary\nSome summary here.\n\n## Direct Repair\n{_VALID_DIRECT_REPAIR_FIELDS}"
    # No trailing newline — this was the failing case before the regex fix
    assert not body.endswith("\n"), "Fixture must have no trailing newline to reproduce the bug"
    assert _is_direct_repair(body), "Expected direct repair to be accepted when block is last with no trailing newline"


def test_direct_repair_accepted_when_block_is_middle_section() -> None:
    """AC3: Direct Repair block surrounded by other sections."""
    body = (
        "## Summary\nSome summary.\n\n"
        f"## Direct Repair\n{_VALID_DIRECT_REPAIR_FIELDS}\n\n"
        "## Runtime behavior\nNo change."
    )
    assert _is_direct_repair(body), "Expected direct repair to be accepted when block is in the middle"


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
