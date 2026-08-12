from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_research_handoff_requires_promotion_intent() -> None:
    skill = (REPO_ROOT / ".codex/skills/architecture-research/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "Record an explicit disposition for every finding" in skill
    assert "create and durably transition the existing BuilderOps" in skill
    assert "PromotionIntent" in skill
    assert "A research audit, task list, or chat transcript alone is not authority" in skill


def test_promoted_research_handoff_is_allowed() -> None:
    research_skill = (REPO_ROOT / ".codex/skills/architecture-research/SKILL.md").read_text(
        encoding="utf-8"
    )
    breakdown_skill = (REPO_ROOT / ".codex/skills/feature-breakdown/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "PromotionIntent-backed, reconciled backlog" in research_skill
    assert "source and result references" in breakdown_skill
    assert "does not add a PromotionIntent wrapper to ordinary breakdown" in breakdown_skill
