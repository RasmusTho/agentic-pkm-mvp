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
        "Direct PR Rationale",
        "Validation:",
        "Direct repair PRs are allowed without a governing issue",
        "failing required tests or checks must be classified before merge",
        "delivery traceability must be preserved through either an issue-backed PR or a direct repair PR rationale",
    ):
        assert fragment in text, fragment


def test_pr_integration_skill_allows_issue_backed_or_direct_repair_prs() -> None:
    text = _read(".codex/skills/pr-integration/SKILL.md")

    for fragment in (
        "an issue-backed PR exists with a bounded governing slice Issue",
        "a bounded direct repair PR exists whose body contains `Direct PR Rationale` and `Validation`",
        "A governing issue is required for normal planned workflow; a bounded direct repair PR may proceed without one",
        "Missing issue traceability is an escalation trigger only when the PR is neither issue-backed nor a valid direct repair PR.",
    ):
        assert fragment in text, fragment


def test_verification_skill_distinguishes_issue_backed_and_direct_repair_modes() -> None:
    text = _read(".codex/skills/verification-and-closure/SKILL.md")

    for fragment in (
        "For issue-backed PRs, close or update the governing Issue as usual.",
        "For direct repair PRs, verify the PR body contract and validation instead of issue closure.",
        "Do not create an Issue after the fact solely for a bounded direct repair.",
        "if direct repair, write a direct repair delivery receipt instead of issue-closure state changes",
    ):
        assert fragment in text, fragment


def test_issue_to_code_skill_accepts_direct_repair_without_unconditional_issue_traceability() -> None:
    text = _read(".codex/skills/issue-to-code/SKILL.md")

    for fragment in (
        "Bounded direct repair PRs may proceed without a governing Issue when the PR body supplies the full contract via direct repair rationale and validation.",
        "For a bounded direct repair PR, treat the PR body as the contract and validate it directly instead of requiring a governing Issue.",
        "Route only triggered cases to `docs/development/PR_ESCALATION_PATHS.md` or the heavier `pr-integration` path.",
    ):
        assert fragment in text, fragment


def test_parent_issue_closure_keeps_delivery_scope_above_future_adoption() -> None:
    text = _read("docs/development/PARENT_ISSUE_CLOSURE.md")

    for fragment in (
        "Parent closure is not part of the default PR hot path unless this PR is the final child slice.",
        "Future adoption over N deliveries must not block closure of delivered, repo-verifiable scope.",
        "If the delivered scope is complete and the remaining work is only observation or follow-up learning, close the parent",
    ):
        assert fragment in text, fragment
