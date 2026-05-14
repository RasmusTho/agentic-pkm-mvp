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
    ):
        assert fragment in text, fragment

    assert text.index("const directRepairSectionMatch = body.match(/## Direct Repair") < text.index(
        "const docsAuthoringPattern ="
    )
    assert text.index("if (isDirectRepair) {") < text.index("const docsAuthoringPattern =")


def test_parent_issue_closure_keeps_delivery_scope_above_future_adoption() -> None:
    text = _read("docs/development/PARENT_ISSUE_CLOSURE.md")

    for fragment in (
        "Parent closure is not part of the default PR hot path unless this PR is the final child slice.",
        "Future adoption over N deliveries must not block closure of delivered, repo-verifiable scope.",
        "If the delivered scope is complete and the remaining work is only observation or follow-up learning, close the parent",
    ):
        assert fragment in text, fragment
