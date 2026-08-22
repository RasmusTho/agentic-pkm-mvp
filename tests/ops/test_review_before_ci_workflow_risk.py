from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.workflow_review_risk import (
    WorkflowReviewRiskError,
    infer_workflow_risks,
    workflow_risk_evidence_from_git,
    validate_workflow_review_receipt,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_governance_allowlist_admits_classifier_surfaces() -> None:
    workflow = (REPO_ROOT / ".github/workflows/issue-pr-governance.yml").read_text(
        encoding="utf-8"
    )
    allowlist = workflow.split("const governanceAllowedExact = new Set([", 1)[1].split(
        "]);", 1
    )[0]

    assert '"scripts/workflow_review_risk.py"' in allowlist
    assert '"tests/ops/test_review_before_ci_workflow_risk.py"' in allowlist


def test_quoted_and_block_scalar_concurrency_semantics_infer_risk() -> None:
    before = "name: check\n'on': pull_request\n\n'concurrency': old\n"
    after = "name: check\n'on': pull_request\n\n'concurrency': |\n  new-${{ github.ref }}\n"

    assert infer_workflow_risks(before, after) == {"concurrency"}


def test_all_supported_pull_request_trigger_forms_infer_state_machine_risk() -> None:
    forms = (
        "'on': pull_request\n",
        "'on': [push, pull_request]\n",
        "'on': {push: {}, pull_request: {branches: [main]}}\n",
        "'on':\n  push:\n  pull_request:\n    types: [opened]\n",
        "'on':\n  - push\n  - pull_request\n",
    )
    for form in forms:
        assert infer_workflow_risks("name: check\n", f"name: check\n{form}") == {
            "state-machine"
        }


def test_structural_admission_scope_avoids_false_high_and_false_low() -> None:
    before = """'on': workflow_call
jobs:
  steps:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - if: github.event_name == 'push'
        run: echo ok
  reusable:
    uses: owner/repo/.github/workflows/reusable.yml@main
    with:
      pull_request: ignored
"""
    job_change = before.replace("github.event_name == 'pull_request'", "github.event_name == 'push'", 1)
    step_change = before.replace("github.event_name == 'push'", "github.event_name == 'workflow_dispatch'")
    nested_change = before.replace("pull_request: ignored", "pull_request: still-ignored")

    assert infer_workflow_risks(before, job_change) == {"state-machine"}
    assert infer_workflow_risks(before, step_change) == set()
    assert infer_workflow_risks(before, nested_change) == set()


def test_renamed_workflow_preserves_both_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
    ):
        subprocess.run(command, cwd=repo, check=True)
    old_workflow = repo / ".github/workflows/old-name.yml"
    old_workflow.parent.mkdir(parents=True)
    old_workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    new_workflow = old_workflow.with_name("new-name.yml")
    subprocess.run(["git", "mv", str(old_workflow), str(new_workflow)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "rename"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    evidence = workflow_risk_evidence_from_git(repo, base=base, head=head)

    assert evidence.workflow_paths == (
        ".github/workflows/old-name.yml",
        ".github/workflows/new-name.yml",
    )


def test_structural_forms_require_exact_bound_receipt_from_actual_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
    ):
        subprocess.run(command, cwd=repo, check=True)
    workflow = repo / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    workflow.write_text("name: check\n'on': {push: {}, pull_request: {}}\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "head", "-q"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    evidence = workflow_risk_evidence_from_git(repo, base=base, head=head)
    assert evidence.risks == ("state-machine",)
    receipt = {
        "version": 1,
        "base_sha": evidence.base_sha,
        "head_sha": evidence.head_sha,
        "diff_digest": evidence.diff_digest,
        "risks": list(evidence.risks),
        "verdict": "pass",
        "reviewer": "independent reviewer",
        "scenario_matrix_complete": True,
    }
    assert validate_workflow_review_receipt(json.dumps(receipt), evidence) == receipt
    receipt["head_sha"] = "0" * 40
    with pytest.raises(WorkflowReviewRiskError, match="head_sha"):
        validate_workflow_review_receipt(json.dumps(receipt), evidence)


def test_moving_base_does_not_invent_candidate_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
    ):
        subprocess.run(command, cwd=repo, check=True)
    workflow = repo / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    requested_base_branch = subprocess.check_output(
        ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, text=True
    ).strip()
    merge_base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()

    subprocess.run(["git", "checkout", "-qb", "candidate"], cwd=repo, check=True)
    workflow.write_text("name: check\n'on': pull_request\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "candidate", "-q"], cwd=repo, check=True)
    candidate_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()

    subprocess.run(["git", "checkout", "-q", requested_base_branch], cwd=repo, check=True)
    (repo / "unrelated.txt").write_text("moving endpoint\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "moving base"], cwd=repo, check=True)
    requested_base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()

    evidence = workflow_risk_evidence_from_git(
        repo, base=requested_base, head=candidate_head
    )
    assert evidence.base_sha == merge_base
    assert evidence.base_sha != requested_base
    assert evidence.head_sha == candidate_head

    receipt = {
        "version": 1,
        "base_sha": evidence.base_sha,
        "head_sha": evidence.head_sha,
        "diff_digest": evidence.diff_digest,
        "risks": list(evidence.risks),
        "verdict": "pass",
        "reviewer": "independent reviewer",
        "scenario_matrix_complete": True,
    }
    assert validate_workflow_review_receipt(json.dumps(receipt), evidence) == receipt
    receipt["base_sha"] = requested_base
    with pytest.raises(WorkflowReviewRiskError, match="base_sha"):
        validate_workflow_review_receipt(json.dumps(receipt), evidence)


def test_review_gate_consumes_actual_workflow_risk_and_requires_exact_receipt(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
    ):
        subprocess.run(command, cwd=repo, check=True)
    workflow = repo / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    workflow.write_text("name: check\n'on': [push, pull_request]\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "head", "-q"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    evidence = workflow_risk_evidence_from_git(repo, base=base, head=head)
    receipt_path = repo / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "version": 1,
                "base_sha": evidence.base_sha,
                "head_sha": evidence.head_sha,
                "diff_digest": evidence.diff_digest,
                "risks": list(evidence.risks),
                "verdict": "pass",
                "reviewer": "independent reviewer",
                "scenario_matrix_complete": True,
            }
        ),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/review_before_ci_gate.py"),
        "--lane",
        "governance",
        "--changed-file",
        ".github/workflows/check.yml",
        "--risk-assessment-complete",
        "--review-gate-complete",
        "--workflow-risk-base",
        base,
        "--workflow-risk-head",
        head,
    ]
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    missing = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    allowed = subprocess.run(
        [*command, "--workflow-review-receipt", str(receipt_path)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2
    assert "actual workflow risk" in missing.stderr
    assert allowed.returncode == 0, allowed.stderr
    assert "risk:state-machine" in json.loads(allowed.stdout)["matched_surfaces"]
