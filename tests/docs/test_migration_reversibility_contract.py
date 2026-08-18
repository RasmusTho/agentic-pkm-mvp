"""Keep migration reversibility documentation aligned with active promotion."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLASSIFICATION = (
    REPO_ROOT
    / "docs"
    / "RELEASE_CHANNELS"
    / "DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md"
)
PROMOTION_PLAN = (
    REPO_ROOT / "docs" / "RELEASE_CHANNELS" / "DEFINE_PROMOTION_PLAN_CONTRACT.md"
)
PREPARE_PROMOTION = (
    REPO_ROOT / ".codex" / "skills" / "prepare-promotion" / "SKILL.md"
)


def test_active_promotion_path_is_covered_by_reversibility_contract() -> None:
    classification = CLASSIFICATION.read_text(encoding="utf-8")
    promotion_plan = PROMOTION_PLAN.read_text(encoding="utf-8")
    prepare_promotion = PREPARE_PROMOTION.read_text(encoding="utf-8")

    assert "active production promotion path" in classification
    assert "`app` DB" in classification
    assert "`pkm-prod`" in classification
    assert "planned per-channel DB split remains future state" in classification
    assert "`app` DB, compose project `pkm-prod`" in promotion_plan
    assert "`app` DB, compose project `pkm-prod`, port 15432" in prepare_promotion
    scope = classification.split("- **Scope**:", 1)[1].split("\n\n", 1)[0]
    assert "pkm_prod" not in scope
