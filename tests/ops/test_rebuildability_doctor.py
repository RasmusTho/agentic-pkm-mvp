"""RSC-04 acceptance coverage for the read-only rebuildability doctor."""

from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli import cli
from app.rebuildability.mirror_doctor import (
    DurablePath,
    DurablePathClass,
    MirrorFindingCode,
    ProjectionRecord,
    SourceRecord,
    diagnose_mirror_corruption,
)


def _inventory() -> list[DurablePath]:
    return [
        DurablePath(
            path="product-object-projection",
            classification=DurablePathClass.DERIVED,
            owner="Product StorePort",
            rebuild_or_retention_source="retained Product note",
        ),
        DurablePath(
            path="governance-receipt-log",
            classification=DurablePathClass.RECEIPT_TRACE,
            owner="governance receipts",
            rebuild_or_retention_source="vault receipt log",
        ),
    ]


def _source() -> SourceRecord:
    return SourceRecord(identity="Notes/product.md", generation="source-generation")


def _projection(**changes: object) -> ProjectionRecord:
    values: dict[str, object] = {
        "projection_id": "object-row-1",
        "source_identity": "Notes/product.md",
        "source_generation": "source-generation",
        "recipe_version": "product-object-replay-v1",
        "index_identity": "test:test-model:3",
        "expected_index_identity": "test:test-model:3",
        "db_source_generation": "source-generation",
    }
    values.update(changes)
    return ProjectionRecord(**values)  # type: ignore[arg-type]


def test_inventory_requires_owner_and_rebuild_or_retention_source() -> None:
    report = diagnose_mirror_corruption(
        inventory=[*_inventory(), DurablePath(path="unknown-cache")],
        sources=[_source()],
        projections=[_projection()],
    )

    assert report.healthy is False
    assert [finding.code for finding in report.findings] == [
        MirrorFindingCode.UNCLASSIFIED_PATH,
    ]
    assert report.findings[0].subject_digest


def test_doctor_detects_projection_corruption_and_drift() -> None:
    report = diagnose_mirror_corruption(
        inventory=_inventory(),
        sources=[_source()],
        projections=[
            _projection(
                projection_id="missing-provenance",
                recipe_version="",
                source_generation="old-generation",
                db_source_generation="db-old-generation",
            ),
            _projection(projection_id="stale", source_generation="old-generation"),
            _projection(projection_id="orphan", source_identity="Notes/missing.md"),
            _projection(
                projection_id="index-drift",
                index_identity="test:wrong-model:3",
            ),
            _projection(projection_id="db-mismatch", db_source_generation="db-old-generation"),
            _projection(projection_id="hidden-authority", sole_meaning_authority=True),
        ],
    )

    assert report.healthy is False
    assert {finding.code for finding in report.findings} == {
        MirrorFindingCode.MISSING_PROVENANCE,
        MirrorFindingCode.STALE_GENERATION,
        MirrorFindingCode.ORPHANED_PROJECTION,
        MirrorFindingCode.INDEX_IDENTITY_DRIFT,
        MirrorFindingCode.DB_SOURCE_MISMATCH,
        MirrorFindingCode.HIDDEN_AUTHORITY,
    }
    missing_subject = next(
        finding.subject_digest
        for finding in report.findings
        if finding.code is MirrorFindingCode.MISSING_PROVENANCE
    )
    assert {
        finding.code
        for finding in report.findings
        if finding.subject_digest == missing_subject
    } == {
        MirrorFindingCode.MISSING_PROVENANCE,
        MirrorFindingCode.STALE_GENERATION,
        MirrorFindingCode.DB_SOURCE_MISMATCH,
    }
    assert tuple(report.findings) == tuple(sorted(report.findings, key=lambda item: item.sort_key))


def test_doctor_is_redacted_and_non_mutating() -> None:
    inventory = [
        *_inventory(),
        DurablePath(
            path="queue",
            classification=DurablePathClass.OPERATIONAL_EXCEPTION,
            owner="queue owner",
            rebuild_or_retention_source="owner-native queue receipt",
            sole_action_authority=True,
        ),
    ]
    report = diagnose_mirror_corruption(
        inventory=inventory,
        sources=[_source()],
        projections=[
            _projection(
                source_generation="secret-source-generation",
                db_source_generation="secret-db-generation",
                recipe_version="secret-recipe",
            )
        ],
    )

    assert report.healthy is False
    assert MirrorFindingCode.HIDDEN_AUTHORITY in {finding.code for finding in report.findings}
    rendered = repr(report) + repr(report.as_dict())
    for secret in ("secret-source-generation", "secret-db-generation", "secret-recipe", "Notes/product.md"):
        assert secret not in rendered
    assert all(len(finding.subject_digest) == 64 for finding in report.findings)


def test_rebuildability_doctor_command_is_read_only_and_redacted(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.json"
    payload = {
        "inventory": [
            {
                "path": "queue",
                "classification": "operational_exception",
                "owner": "queue owner",
                "rebuild_or_retention_source": "owner-native queue receipt",
                "sole_action_authority": True,
            }
        ],
        "sources": [],
        "projections": [],
        "secret": "must-not-be-rendered",
    }
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    before = snapshot.read_bytes()

    result = CliRunner().invoke(
        cli,
        ["rebuildability-doctor", "--snapshot", str(snapshot), "--json", "--strict"],
    )

    assert result.exit_code == 2
    assert snapshot.read_bytes() == before
    assert "must-not-be-rendered" not in result.output
    assert "queue owner" not in result.output
    assert json.loads(result.output)["healthy"] is False
