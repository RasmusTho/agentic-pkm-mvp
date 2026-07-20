from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.review_before_ci_gate import (
    ReviewBeforeCiGateError,
    evaluate_review_before_ci_gate,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_PR_SKILL = REPO_ROOT / ".codex/skills/publish-pr/SKILL.md"
ISSUE_TO_CODE_SKILL = REPO_ROOT / ".codex/skills/issue-to-code/SKILL.md"
VERIFICATION_SKILL = REPO_ROOT / ".codex/skills/verification-and-closure/SKILL.md"
REVIEW_REPAIR_CONTRACT = (
    REPO_ROOT / "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md"
)
DEV_WORKFLOW = REPO_ROOT / "docs/development/DEV_WORKFLOW.md"
AGENTS = REPO_ROOT / "AGENTS.md"


def test_docs_governance_changes_require_pre_ci_review_gate() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="governance",
        changed_files=[
            "docs/development/PR_HOT_PATH.md",
            ".github/workflows/issue-pr-governance.yml",
        ],
        risk_assessment_complete=True,
    )

    assert gate.requires_review_gate is True
    assert gate.review_gate_complete is False
    assert gate.may_handoff_to_ci is False
    assert gate.status == "required"
    assert "surface:docs" in gate.matched_surfaces
    assert "surface:governance" in gate.matched_surfaces
    assert "generate or preflight the PR body" in gate.required_local_checks[0]


def test_gate_output_preserves_ci_authority() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="docs-authoring",
        changed_files=["docs/development/PR_HOT_PATH.md"],
        review_gate_complete=True,
    )

    assert gate.status == "satisfied"
    assert gate.may_handoff_to_ci is True
    assert gate.preserves_ci_authority is True
    assert "GitHub CI" in gate.summary


def test_high_risk_implementation_requires_convergence_review_before_expensive_gates() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="implementation",
        changed_files=["app/oauth/service.py", "tests/oauth/test_service.py"],
        risk_surfaces=["auth", "credential-durability", "state-machine"],
        risk_assessment_complete=True,
    )

    assert gate.status == "required"
    assert gate.may_handoff_to_ci is False
    assert "risk:auth" in gate.matched_surfaces
    assert "risk:credential-durability" in gate.matched_surfaces
    assert any("convergence packet" in check for check in gate.required_local_checks)
    assert any("before the full suite" in check for check in gate.required_local_checks)


def test_standard_implementation_keeps_existing_hot_path() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="implementation",
        changed_files=["app/panel/formatting.py", "tests/panel/test_formatting.py"],
        risk_assessment_complete=True,
    )

    assert gate.status == "not_required"
    assert gate.may_handoff_to_ci is True


def test_unknown_lane_is_rejected_instead_of_failing_open() -> None:
    with pytest.raises(ReviewBeforeCiGateError, match="unknown lane: implmentation"):
        evaluate_review_before_ci_gate(
            lane="implmentation",
            changed_files=["app/oauth/service.py"],
        )


def test_governance_concurrency_requires_convergence_review() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="governance",
        changed_files=["scripts/run_with_host_lease.py"],
        risk_surfaces=["concurrency"],
        risk_assessment_complete=True,
    )

    assert gate.status == "required"
    assert gate.may_handoff_to_ci is False
    assert "risk:concurrency" in gate.matched_surfaces
    assert any("convergence packet" in check for check in gate.required_local_checks)


def test_bypass_requires_explicit_reason() -> None:
    required = evaluate_review_before_ci_gate(
        lane="direct-repair",
        changed_files=["docs/development/PR_HOT_PATH.md"],
        risk_assessment_complete=True,
    )
    bypassed = evaluate_review_before_ci_gate(
        lane="direct-repair",
        changed_files=["docs/development/PR_HOT_PATH.md"],
        bypass_reason="Emergency wording repair; receipt will name skipped local gate.",
        risk_assessment_complete=True,
    )

    assert required.may_handoff_to_ci is False
    assert required.bypass_reason is None
    assert bypassed.status == "bypassed"
    assert bypassed.may_handoff_to_ci is True
    assert bypassed.bypass_reason == "Emergency wording repair; receipt will name skipped local gate."
    assert bypassed.preserves_ci_authority is True


def test_high_risk_implementation_cannot_bypass_convergence_review() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="only for an emergency direct-repair",
    ):
        evaluate_review_before_ci_gate(
            lane="implementation",
            changed_files=["app/oauth/service.py"],
            risk_surfaces=["auth"],
            risk_assessment_complete=True,
            bypass_reason="Skip convergence review.",
        )


def test_implementation_requires_explicit_risk_assessment_even_when_no_risk_declared() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="require an explicit completed risk assessment",
    ):
        evaluate_review_before_ci_gate(
            lane="implementation",
            changed_files=["app/oauth/service.py"],
        )


def test_high_risk_direct_repair_cannot_use_emergency_bypass() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="no declared high-risk surface",
    ):
        evaluate_review_before_ci_gate(
            lane="direct-repair",
            changed_files=["app/oauth/service.py"],
            risk_surfaces=["auth"],
            bypass_reason="Emergency auth repair.",
            risk_assessment_complete=True,
        )


def test_direct_repair_cannot_omit_risk_assessment_to_reach_bypass() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="require an explicit completed risk assessment",
    ):
        evaluate_review_before_ci_gate(
            lane="direct-repair",
            changed_files=["app/oauth/service.py"],
            bypass_reason="Emergency auth repair.",
        )


def test_cli_fails_until_review_gate_is_complete() -> None:
    blocked = subprocess.run(
        [
            sys.executable,
            "scripts/review_before_ci_gate.py",
            "--lane",
            "governance",
            "--changed-file",
            "docs/development/PR_HOT_PATH.md",
            "--risk-assessment-complete",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    allowed = subprocess.run(
        [
            sys.executable,
            "scripts/review_before_ci_gate.py",
            "--lane",
            "governance",
            "--changed-file",
            "docs/development/PR_HOT_PATH.md",
            "--risk-assessment-complete",
            "--review-gate-complete",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["may_handoff_to_ci"] is False
    assert allowed.returncode == 0
    assert json.loads(allowed.stdout)["may_handoff_to_ci"] is True


def test_publish_pr_skill_runs_review_gate_before_push() -> None:
    text = PUBLISH_PR_SKILL.read_text(encoding="utf-8")

    assert "Review-Before-CI Gate" in text
    assert "scripts/review_before_ci_gate.py" in text
    assert text.index("Review-Before-CI Gate") < text.index("### Step 5: Push Branch")


def test_mechanism_convergence_contract_is_wired_across_delivery_skills() -> None:
    agents = AGENTS.read_text(encoding="utf-8")
    issue_to_code = ISSUE_TO_CODE_SKILL.read_text(encoding="utf-8")
    publish_pr = PUBLISH_PR_SKILL.read_text(encoding="utf-8")
    verification = VERIFICATION_SKILL.read_text(encoding="utf-8")
    contract = REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8")

    assert "## Mechanism Convergence Gate" in contract
    assert "mechanism/convergence review before an expensive" in agents
    assert "risk-convergence form" in issue_to_code
    assert "TCD_RISK_SURFACES" in publish_pr
    assert "Low-convergence circuit breaker" in verification


def test_pr_hot_path_requires_explicit_risk_classification_before_bypass() -> None:
    hot_path = (REPO_ROOT / "docs/development/PR_HOT_PATH.md").read_text(
        encoding="utf-8"
    )

    assert "--risk-assessment-complete" in hot_path
    assert "A declared high-risk surface is never bypassable" in hot_path


def test_host_global_full_suite_uses_atomic_wrapper_in_canonical_workflow() -> None:
    agents = AGENTS.read_text(encoding="utf-8")
    workflow = DEV_WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/run_with_host_lease.py" in agents
    assert "Chat reservations" in agents
    assert "--resource pytest-not-pg" in workflow
    assert "is not mutual exclusion" in workflow
