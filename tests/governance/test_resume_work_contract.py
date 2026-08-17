"""Regression guards for isolated rescue-stash replay evidence."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_rescue_stash_requires_exact_hash_dry_run_and_conflict_inventory() -> None:
    """Only a clean isolated replay can make a rescue candidate rebase-ready."""
    resume_work = (REPO_ROOT / ".codex/skills/resume-work/SKILL.md").read_text(
        encoding="utf-8"
    )
    contract = " ".join(resume_work.split())

    assert "replay its exact stash hash" in contract
    assert "isolated disposable worktree" in contract
    assert "dry-run that does not apply or delete the stash" in contract
    assert "conflict inventory" in contract
    assert "replay-safe candidate has no conflicts and no deleted or stale paths" in contract
    assert "deleted, stale, or conflicting path keeps the candidate out of the rebase-ready state" in contract
