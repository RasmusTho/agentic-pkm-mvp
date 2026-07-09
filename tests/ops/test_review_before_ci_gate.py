from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.review_before_ci_gate import evaluate_review_before_ci_gate


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_PR_SKILL = REPO_ROOT / ".codex/skills/publish-pr/SKILL.md"


def test_docs_governance_changes_require_pre_ci_review_gate() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="governance",
        changed_files=[
            "docs/development/PR_HOT_PATH.md",
            ".github/workflows/issue-pr-governance.yml",
        ],
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


def test_bypass_requires_explicit_reason() -> None:
    required = evaluate_review_before_ci_gate(
        lane="direct-repair",
        changed_files=["docs/development/PR_HOT_PATH.md"],
    )
    bypassed = evaluate_review_before_ci_gate(
        lane="direct-repair",
        changed_files=["docs/development/PR_HOT_PATH.md"],
        bypass_reason="Emergency wording repair; receipt will name skipped local gate.",
    )

    assert required.may_handoff_to_ci is False
    assert required.bypass_reason is None
    assert bypassed.status == "bypassed"
    assert bypassed.may_handoff_to_ci is True
    assert bypassed.bypass_reason == "Emergency wording repair; receipt will name skipped local gate."
    assert bypassed.preserves_ci_authority is True


def test_cli_fails_until_review_gate_is_complete() -> None:
    blocked = subprocess.run(
        [
            sys.executable,
            "scripts/review_before_ci_gate.py",
            "--lane",
            "governance",
            "--changed-file",
            "docs/development/PR_HOT_PATH.md",
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
