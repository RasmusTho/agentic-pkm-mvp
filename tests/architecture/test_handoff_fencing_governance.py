"""Regression coverage for lifecycle-owner handoff fencing."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_handoff_requires_authenticated_owner_and_current_evidence() -> None:
    """Replacement, publication, and closure require one authenticated current owner."""
    issue_to_code = _read(".codex/skills/issue-to-code/SKILL.md")
    resume_work = _read(".codex/skills/resume-work/SKILL.md")
    verification = _read(".codex/skills/verification-and-closure/SKILL.md")
    owner_doc = _read("docs/development/BUILDER_SUBAGENT_ROLES.md")

    for surface in (issue_to_code, resume_work, verification, owner_doc):
        assert "lifecycle_handoff_receipt.v1" in surface

    combined = "\n".join((issue_to_code, resume_work, verification, owner_doc))
    for required_evidence in (
        "current lifecycle owner",
        "writable worktree",
        "unpublished candidate head",
        "current review/receipt evidence",
        "next authorized action",
    ):
        assert required_evidence in combined

    assert "successor" in issue_to_code
    assert "acknowledgment" in issue_to_code
    assert "former lifecycle owner is then read-only" in issue_to_code
    assert "newer blocking review evidence fail closed" in issue_to_code

    for surface in (issue_to_code, resume_work):
        normalized = " ".join(surface.split())
        dispatcher_release = normalized.index("dispatcher release")
        dispatcher_claim = normalized.index("successor claim/readback", dispatcher_release)
        release = normalized.index("release --worktree")
        successor_registration = normalized.index("register --worktree", release)
        candidate_revalidation = normalized.index("candidate revalidation", successor_registration)
        acknowledgment = normalized.index("acknowledgment", candidate_revalidation)
        assert dispatcher_release < dispatcher_claim < release
        assert release < successor_registration < acknowledgment
        assert successor_registration < candidate_revalidation < acknowledgment
        assert "dispatcher release → successor claim/readback → worktree release → successor registration/readback → candidate revalidation sequence" in normalized
        assert "writable_worktree: none" in normalized
        assert "authority does not transfer" in normalized
        assert "neither side may publish" in normalized

    normalized_owner_doc = " ".join(owner_doc.split())
    assert "dispatcher release → successor claim/readback → worktree release → successor registration/readback → candidate revalidation sequence" in normalized_owner_doc
    assert "Neither side may publish, merge, or close" in normalized_owner_doc

    assert "former lifecycle owner is read-only" in verification
    assert "Newer blocking review evidence" in verification
    assert "fail closed" in verification
    assert "Do not merge or close" in verification
