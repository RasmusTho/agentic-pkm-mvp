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
README = REPO_ROOT / "docs" / "RELEASE_CHANNELS" / "README.md"


def test_active_promotion_docs_agree_on_migration_applicability() -> None:
    """Keep the active policy distinct from deferred automated promotion hardening."""
    classification = CLASSIFICATION.read_text(encoding="utf-8")
    promotion_plan = PROMOTION_PLAN.read_text(encoding="utf-8")
    prepare_promotion = PREPARE_PROMOTION.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "active production promotion path" in classification
    assert "`app` DB" in classification
    assert "`pkm-prod`" in classification
    assert "Current: protected `stable` authority" in readme
    assert (
        "unclassified migration blocks the current prod migration operation"
        in readme.replace("\n", " ")
    )
    assert "Migration delta" in promotion_plan
    assert "active (`app` DB, compose project `pkm-prod`)" in promotion_plan
    assert (
        "each classified as **reversible** or **forward-only** per "
        "`DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION`"
        in promotion_plan
    )
    assert "For each migration: reads its reversibility marker" in prepare_promotion
    assert "flags forward-only ones explicitly" in prepare_promotion

    migration_applicability = " ".join(
        readme.split("#### Current migration reversibility applicability", 1)[1]
        .split("\n### ", 1)[0]
        .split()
    )
    assert (
        "current baseline now enforces that check in the canonical production startup path"
        in migration_applicability
    )
    assert "`scripts/run_migrations.sh` resolves and classifies" in migration_applicability
    assert "`scripts/deploy_channel.sh` checks the live pending migrations" in migration_applicability


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
