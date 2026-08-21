from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.workflow_review_risk import workflow_risk_evidence_from_git


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ("init", "-q"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "test"),
    ):
        subprocess.run(["git", *command], cwd=repo, check=True)
    return repo


def test_moving_base_does_not_invent_candidate_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workflow = repo / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    merge_base = _commit(repo, "base")

    _git(repo, "checkout", "-qb", "candidate")
    (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    candidate = _commit(repo, "candidate change")

    _git(repo, "checkout", "-q", merge_base)
    workflow.write_text("name: check\n'on': pull_request\n", encoding="utf-8")
    moving_base = _commit(repo, "upstream workflow change")

    evidence = workflow_risk_evidence_from_git(repo, base=moving_base, head=candidate)

    assert evidence.base_sha == merge_base
    assert evidence.workflow_paths == ()
    assert evidence.risks == ()


def test_workflow_risk_digest_binds_candidate_diff(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workflow = repo / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    merge_base = _commit(repo, "base")

    _git(repo, "checkout", "-qb", "candidate")
    workflow.write_text("name: check\n'on': push\nconcurrency: first\n", encoding="utf-8")
    first_candidate = _commit(repo, "first candidate workflow change")
    first = workflow_risk_evidence_from_git(repo, base=merge_base, head=first_candidate)

    workflow.write_text("name: check\n'on': push\nconcurrency: second\n", encoding="utf-8")
    second_candidate = _commit(repo, "second candidate workflow change")
    second = workflow_risk_evidence_from_git(repo, base=merge_base, head=second_candidate)

    assert first.base_sha == second.base_sha == merge_base
    assert first.diff_digest != second.diff_digest


def test_real_workflow_change_remains_risky(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workflow = repo / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    base = _commit(repo, "base")

    workflow.write_text("name: check\n'on': pull_request\n", encoding="utf-8")
    candidate = _commit(repo, "candidate workflow change")

    evidence = workflow_risk_evidence_from_git(repo, base=base, head=candidate)

    assert evidence.workflow_paths == (".github/workflows/check.yml",)
    assert evidence.risks == ("state-machine",)
