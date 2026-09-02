"""Static guards for the RSC-01 continuity-authority classification."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
CONTINUITY_README = ROOT / "docs/REBUILDABLE_SYSTEM_CONTINUITY/README.md"
OWNER_DOCS = (
    ROOT / "docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md",
    ROOT / "docs/SEMANTIC_AUTHORITY_MATRIX.md",
    ROOT / "docs/OPERATIONS.md",
    ROOT / "docs/DEPENDENCIES.md",
    ROOT / "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md",
    ROOT / "docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md",
    ROOT / "docs/BUILDEROPS_CONTROL_PLANE/README.md",
    ROOT / "docs/GOVERNED_ARCHIVAL_FLOW/README.md",
    ROOT / "docs/GOVERNED_ARCHIVAL_FLOW/ADAPT_HUMAN_ARTIFACT_RECOVERY.md",
)

CLASSIFICATION_MARKER = "rsc-01 continuity classification"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).lower().split())


def test_owner_docs_share_one_continuity_classification() -> None:
    canonical = _normalized(CONTINUITY_README)
    assert CLASSIFICATION_MARKER in canonical
    for phrase in (
        "retained human artifacts, companions, and document-backed governance receipts",
        "machine mirrors and coordination projections are rebuildable",
        "optional backups are evidence/ergonomics only",
        "operational safety state",
        "new fenced bootstrap epoch",
    ):
        assert phrase in canonical

    for path in OWNER_DOCS:
        text = _read(path).lower()
        assert CLASSIFICATION_MARKER in text, path


def test_diagnostic_retention_is_not_recovery_authority() -> None:
    canonical = _normalized(CONTINUITY_README)
    operations = _normalized(ROOT / "docs/OPERATIONS.md")
    dependencies = _normalized(ROOT / "docs/DEPENDENCIES.md")
    snapshot_spec = _normalized(
        ROOT / "docs/OBSERVABILITY_STABILIZATION/DEV_DB_SNAPSHOT_RESTORE.md"
    )

    for text in (canonical, operations, dependencies, snapshot_spec):
        assert "evidence/ergonomics only" in text
        assert "semantic authority" in text
        assert "mandatory restore proof" in text
    assert "must not be used as the worker queue" in operations
    assert "not a scheduled disaster-recovery or readiness requirement" in dependencies


def test_historical_recovery_material_cannot_claim_active_capability() -> None:
    bcp_owner = _read(
        ROOT / "docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md"
    )
    bcp_readme = _read(ROOT / "docs/BUILDEROPS_CONTROL_PLANE/README.md")
    hka_recovery = _read(
        ROOT / "docs/GOVERNED_ARCHIVAL_FLOW/ADAPT_HUMAN_ARTIFACT_RECOVERY.md"
    )
    historical = _read(ROOT / "docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md")

    for text in (bcp_owner, bcp_readme, hka_recovery):
        assert "historical" in text.lower()
        assert "superseded" in text.lower() or "blocked" in text.lower()
        assert (
            "not shipped" in text.lower()
            or "not an active capability" in text.lower()
            or "not an active shipped capability" in text.lower()
        )
    assert "historical" in historical.lower()
    assert "superseded" in historical.lower()
    assert "not a current recovery requirement" in historical
