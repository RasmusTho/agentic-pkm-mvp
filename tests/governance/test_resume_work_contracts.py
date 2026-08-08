"""Regression guards for recovery instructions that affect dispatcher authority."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_stale_rescue_material_must_match_current_dispatcher_contracts() -> None:
    """Rescue guidance must not make stale local material claim dispatcher authority."""
    resume_work = _read(".codex/skills/resume-work/SKILL.md")
    issue_to_code = _read(".codex/skills/issue-to-code/SKILL.md")
    resume_work_flat = " ".join(resume_work.split())
    issue_to_code_flat = " ".join(issue_to_code.split())

    assert "### Rescue-stash contract gate" in resume_work
    assert "fetch `origin/main`" in resume_work
    assert ".codex/skills/issue-to-code/SKILL.md :: Dispatcher Integration" in resume_work_flat
    assert "cached ref alone" in resume_work_flat
    assert "do not apply it blindly" in resume_work_flat
    assert "Never apply or delete a rescue stash" in resume_work

    assert "Rescue-stash notes, stale local pickup plans" in issue_to_code_flat
    assert "fetch and compare against current `origin/main`" in issue_to_code_flat
    assert "cannot bypass the wrapper, its verified claim" in issue_to_code_flat
    assert "current stale-takeover semantics" in issue_to_code_flat
