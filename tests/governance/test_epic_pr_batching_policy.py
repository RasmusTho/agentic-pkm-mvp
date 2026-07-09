from __future__ import annotations

from app.builderops.epic_pr_batching_policy import evaluate_epic_pr_batching_policy


def test_mixed_runtime_and_governance_batch_is_flagged() -> None:
    decision = evaluate_epic_pr_batching_policy(
        child_issues=[3278, 3301],
        changed_files=[
            "app/runtime/service.py",
            ".github/workflows/issue-pr-governance.yml",
        ],
    )

    assert decision.allowed is False
    assert decision.classification == "mixed_boundary_forbidden"
    assert "runtime and governance surfaces" in decision.reasons[0]


def test_coherent_docs_or_shared_helper_batch_is_allowed() -> None:
    docs = evaluate_epic_pr_batching_policy(
        child_issues=[3278, 3302],
        changed_files=[
            "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md",
            "docs/development/PR_HOT_PATH.md",
        ],
    )
    helper = evaluate_epic_pr_batching_policy(
        child_issues=[3278, 3303],
        changed_files=[
            "app/builderops/epic_pr_batching_policy.py",
            "tests/governance/test_epic_pr_batching_policy.py",
        ],
    )

    assert docs.allowed is True
    assert docs.classification == "coherent_docs_batch"
    assert helper.allowed is True
    assert helper.classification == "coherent_shared_helper_batch"
    assert "use one closing keyword only" in helper.required_pr_body_notes[1]


def test_shared_helper_batch_rejects_unrelated_runtime_file() -> None:
    decision = evaluate_epic_pr_batching_policy(
        child_issues=[3278, 3304],
        changed_files=[
            "app/builderops/epic_pr_batching_policy.py",
            "tests/governance/test_epic_pr_batching_policy.py",
            "app/runtime/service.py",
        ],
    )

    assert decision.allowed is False
    assert decision.classification == "mixed_boundary_forbidden"
