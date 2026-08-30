from pathlib import Path

from app.builderops.blocker_actions import ACTION_LABELS, BLOCKED_ACTIONS, HUMAN_ACTIONS

ROOT = Path(__file__).resolve().parents[2]


def test_operational_skills_reference_canonical_blocker_action_contract() -> None:
    for skill in ("issue-to-code", "issue-maintenance-change-control", "owner-decision-brief", "deliver-issue-set", "feature-breakdown", "bug-to-issue", "docs-to-issue", "learning-to-issue", "post-merge-owner-doc", "verification-and-closure"):
        text = (ROOT / ".codex" / "skills" / skill / "SKILL.md").read_text()
        assert "BLOCKER_ACTION_CONTRACT.md" in text


def test_canonical_action_labels_and_receipt_schema_are_complete() -> None:
    taxonomy = (ROOT / ".codex/skills/_shared/LABEL_TAXONOMY.md").read_text()
    receipt = (ROOT / ".codex/skills/_shared/BLOCKER_ACTION_CONTRACT.md").read_text()
    assert len(ACTION_LABELS) == 10 and len(BLOCKED_ACTIONS) == len(HUMAN_ACTIONS) == 5
    for label in ACTION_LABELS:
        assert label in taxonomy
    for key in ("receipt: blocker_action.v1", "action:", "owner:", "next_action:", "unblocks_when:", "dependency_refs:", "last_verified_at:"):
        assert key in receipt
