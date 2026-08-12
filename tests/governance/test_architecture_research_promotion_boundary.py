from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_research_handoff_requires_promotion_intent() -> None:
    skill = (REPO_ROOT / ".codex/skills/architecture-research/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "Record an explicit disposition for every finding" in skill
    assert "transition the existing BuilderOps" in skill
    assert "`PromotionIntent` to `accepted`" in skill
    assert "PromotionIntent" in skill
    assert "chat transcript alone is not" in skill


def test_promoted_research_handoff_is_allowed() -> None:
    research_skill = (REPO_ROOT / ".codex/skills/architecture-research/SKILL.md").read_text(
        encoding="utf-8"
    )
    breakdown_skill = (REPO_ROOT / ".codex/skills/feature-breakdown/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "accepted-PromotionIntent-backed, reconciled backlog" in research_skill
    assert "accepted-transition `BuilderOpsReceipt`" in breakdown_skill
    assert "record its result references and transition the same intent to `promoted`" in breakdown_skill
    assert "does not add a PromotionIntent wrapper to ordinary breakdown" in breakdown_skill
