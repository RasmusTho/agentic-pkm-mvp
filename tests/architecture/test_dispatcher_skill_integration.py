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


def test_issue_pickup_records_dispatcher_or_fallback_mode() -> None:
    """Issue pickup guidance records the coordination path used."""
    repo_root = Path(__file__).parent.parent.parent
    skill = (repo_root / ".codex/skills/issue-to-code/SKILL.md").read_text()
    script = (repo_root / "scripts/issue_pickup_claim.sh").read_text()

    assert "coordination_mode" in skill
    assert "fallback_reason" in skill
    assert "dispatcher-backed" in skill
    assert "github-label-only-fallback" in skill
    assert "coordination_mode=$RECEIPT_COORDINATION_MODE" in script
    assert "fallback_reason=$RECEIPT_FALLBACK_REASON" in script


def test_issue_pickup_receipt_requires_real_claim_evidence() -> None:
    """Canonical guidance delegates acquisition and evidence to one wrapper call."""
    repo_root = Path(__file__).parent.parent.parent
    skill = (repo_root / ".codex/skills/issue-to-code/SKILL.md").read_text()
    script = (repo_root / "scripts/issue_pickup_claim.sh").read_text()

    assert "scripts/issue_pickup_claim.sh --issue <N> --agent <agent_id>" in skill
    assert "python -m app.dispatcher claim <task_id>" not in skill
    assert "lease_id=$RECEIPT_LEASE_ID" in script
    assert "holder=$RECEIPT_HOLDER" in script
    assert "evidence=verified-dispatcher-lease" in script
