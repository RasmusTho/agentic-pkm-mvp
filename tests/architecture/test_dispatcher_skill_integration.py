"""Architecture tests for dispatcher integration in issue-to-code skill.

Verifies that the issue-to-code skill references dispatcher steps in the correct order
and that the skill cannot silently drift back to label-only pickup.
"""

from __future__ import annotations

from pathlib import Path


def test_skill_references_dispatcher_status() -> None:
    """Dispatcher integration subsection exists and references dispatcher status."""
    skill_path = Path(__file__).parent.parent.parent / ".codex/skills/issue-to-code/SKILL.md"
    assert skill_path.exists(), "issue-to-code/SKILL.md not found"
    content = skill_path.read_text()
    assert "#### Dispatcher Integration" in content, "Dispatcher Integration subsection missing"
    assert "dispatcher status" in content, "dispatcher status step missing"


def test_skill_references_dispatcher_next() -> None:
    """Dispatcher integration includes dispatcher next step."""
    skill_path = Path(__file__).parent.parent.parent / ".codex/skills/issue-to-code/SKILL.md"
    content = skill_path.read_text()
    assert "dispatcher next" in content, "dispatcher next step missing"


def test_skill_references_dispatcher_claim() -> None:
    """Dispatcher integration includes dispatcher claim step."""
    skill_path = Path(__file__).parent.parent.parent / ".codex/skills/issue-to-code/SKILL.md"
    content = skill_path.read_text()
    assert "dispatcher claim" in content, "dispatcher claim step missing"


def test_skill_references_dispatcher_heartbeat() -> None:
    """Dispatcher integration includes dispatcher heartbeat step."""
    skill_path = Path(__file__).parent.parent.parent / ".codex/skills/issue-to-code/SKILL.md"
    content = skill_path.read_text()
    assert "dispatcher heartbeat" in content, "dispatcher heartbeat step missing"


def test_skill_references_dispatcher_complete() -> None:
    """Dispatcher integration includes dispatcher complete step."""
    skill_path = Path(__file__).parent.parent.parent / ".codex/skills/issue-to-code/SKILL.md"
    content = skill_path.read_text()
    assert "dispatcher complete" in content, "dispatcher complete step missing"


def test_skill_dispatcher_steps_in_order() -> None:
    """Dispatcher steps appear in the correct order in the skill."""
    skill_path = Path(__file__).parent.parent.parent / ".codex/skills/issue-to-code/SKILL.md"
    assert skill_path.exists()
    content = skill_path.read_text()

    # Find positions of each step
    status_pos = content.find("dispatcher status")
    next_pos = content.find("dispatcher next")
    claim_pos = content.find("dispatcher claim")
    heartbeat_pos = content.find("dispatcher heartbeat")
    complete_pos = content.find("dispatcher complete")

    # All must be found
    assert status_pos >= 0, "dispatcher status not found"
    assert next_pos >= 0, "dispatcher next not found"
    assert claim_pos >= 0, "dispatcher claim not found"
    assert heartbeat_pos >= 0, "dispatcher heartbeat not found"
    assert complete_pos >= 0, "dispatcher complete not found"

    # Must appear in the correct order
    assert (
        status_pos < next_pos < claim_pos < heartbeat_pos < complete_pos
    ), f"Dispatcher steps out of order: status({status_pos}) next({next_pos}) claim({claim_pos}) heartbeat({heartbeat_pos}) complete({complete_pos})"
