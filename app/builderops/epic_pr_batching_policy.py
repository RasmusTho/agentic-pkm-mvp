"""Epic child PR batching policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


RUNTIME_PREFIXES = ("app/", "companion-ui/companion-app/src/", "alembic/")
GOVERNANCE_PREFIXES = (".github/", ".codex/", "scripts/", "tests/governance/", "tests/ops/")
DOCS_PREFIXES = ("docs/", "README.md", "AGENTS.md", "CLAUDE.md")
TEST_PREFIXES = ("tests/",)


@dataclass(frozen=True)
class EpicPrBatchingDecision:
    allowed: bool
    classification: str
    reasons: list[str]
    required_pr_body_notes: list[str]


def evaluate_epic_pr_batching_policy(
    *,
    child_issues: Sequence[int],
    changed_files: Sequence[str],
) -> EpicPrBatchingDecision:
    """Classify whether multiple epic children may share one PR."""

    issues = _issue_numbers(child_issues)
    files = [_normalize_path(path) for path in changed_files]
    if len(issues) <= 1:
        return _decision(True, "single_child", ["single child slice"], issues)

    touches_runtime = any(path.startswith(RUNTIME_PREFIXES) for path in files)
    touches_governance = any(path.startswith(GOVERNANCE_PREFIXES) for path in files)
    docs_only = all(path.startswith(DOCS_PREFIXES) for path in files)
    shared_helper = _is_shared_helper_batch(files)

    if docs_only:
        return _decision(
            True,
            "coherent_docs_batch",
            ["docs-only children may batch when owner-doc scope, review, validation, and rollback match"],
            issues,
        )
    if shared_helper:
        return _decision(
            True,
            "coherent_shared_helper_batch",
            ["shared helper plus direct tests may batch when the same helper owns every child change"],
            issues,
        )
    if touches_runtime and touches_governance:
        return _decision(
            False,
            "mixed_boundary_forbidden",
            ["runtime and governance surfaces require separate review, test, rollback, and owners"],
            issues,
        )
    return _decision(
        False,
        "unclear_batch_boundary",
        ["batch lacks a single obvious owner, review surface, test set, and rollback behavior"],
        issues,
    )


def _decision(
    allowed: bool,
    classification: str,
    reasons: list[str],
    issues: Sequence[int],
) -> EpicPrBatchingDecision:
    return EpicPrBatchingDecision(
        allowed=allowed,
        classification=classification,
        reasons=reasons,
        required_pr_body_notes=[
            "list every child issue in the PR body",
            "use one closing keyword only for issues fully delivered by this PR",
            "name parent receipt expectations and any children intentionally not closed",
            f"children considered: {', '.join(f'#{issue}' for issue in issues)}",
        ],
    )


def _is_shared_helper_batch(files: Sequence[str]) -> bool:
    allowed_prefixes = ("app/builderops/", "scripts/", *TEST_PREFIXES)
    if not all(path.startswith(allowed_prefixes) for path in files):
        return False
    helper_files = [path for path in files if path.startswith("app/builderops/") or path.startswith("scripts/")]
    test_files = [path for path in files if path.startswith(TEST_PREFIXES)]
    return bool(helper_files) and bool(test_files) and len(helper_files) <= 2


def _issue_numbers(values: Sequence[int]) -> list[int]:
    issues: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("child issue numbers must be positive integers")
        if value not in issues:
            issues.append(value)
    return issues


def _normalize_path(path: str) -> str:
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise ValueError("changed files must be non-empty paths")
    return normalized
