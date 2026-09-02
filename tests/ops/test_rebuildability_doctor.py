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
from app.rebuildability.product_total_loss import PRODUCT_REPLAY_RECIPE_VERSION


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
        "recipe_version": PRODUCT_REPLAY_RECIPE_VERSION,
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


def test_doctor_rejects_unsupported_recipe_version_but_accepts_current() -> None:
    healthy = diagnose_mirror_corruption(
        inventory=_inventory(), sources=[_source()], projections=[_projection()]
    )
    stale = diagnose_mirror_corruption(
        inventory=_inventory(),
        sources=[_source()],
        projections=[_projection(recipe_version="product-object-replay-v0")],
    )

    assert PRODUCT_REPLAY_RECIPE_VERSION == "product-object-replay-v1"
    assert healthy.healthy is True
    assert {finding.code for finding in stale.findings} == {
        MirrorFindingCode.RECIPE_VERSION_MISMATCH
    }


def test_snapshot_cannot_self_bless_unsupported_recipe_version() -> None:
    report = diagnose_mirror_corruption(
        inventory=_inventory(),
        sources=[_source()],
        projections=[
            _projection(
                recipe_version="product-object-replay-v0",
                # A snapshot must not choose the version that validates it.
            )
        ],
    )

    assert report.healthy is False
    assert MirrorFindingCode.RECIPE_VERSION_MISMATCH in {
        finding.code for finding in report.findings
    }


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
        "complete": True,
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


def test_rebuildability_doctor_rejects_incomplete_snapshot(tmp_path) -> None:
    snapshot = tmp_path / "incomplete.json"
    snapshot.write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(cli, ["rebuildability-doctor", "--snapshot", str(snapshot)])

    assert result.exit_code == 1
    assert "must include the 'inventory' collection" in result.output


def test_rebuildability_doctor_reports_unknown_classification(tmp_path) -> None:
    snapshot = tmp_path / "unknown-classification.json"
    snapshot.write_text(
        json.dumps(
            {
                "complete": True,
                "inventory": [
                    {
                        "path": "skewed-path",
                        "classification": "from-a-newer-owner",
                        "owner": "owner",
                        "rebuild_or_retention_source": "source",
                    }
                ],
                "sources": [],
                "projections": [],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["rebuildability-doctor", "--snapshot", str(snapshot), "--json", "--strict"],
    )

    assert result.exit_code == 2
    assert json.loads(result.output)["findings"][0]["code"] == "unclassified_path"


def test_rebuildability_doctor_reports_incomplete_empty_snapshot(tmp_path) -> None:
    snapshot = tmp_path / "empty.json"
    snapshot.write_text(
        json.dumps({"inventory": [], "sources": [], "projections": []}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["rebuildability-doctor", "--snapshot", str(snapshot), "--json", "--strict"],
    )

    assert result.exit_code == 2
    assert json.loads(result.output)["findings"][0]["code"] == "incomplete_snapshot"


def test_doctor_requires_db_generation_evidence() -> None:
    report = diagnose_mirror_corruption(
        inventory=_inventory(),
        sources=[_source()],
        projections=[_projection(db_source_generation=None)],
    )

    assert {finding.code for finding in report.findings} == {MirrorFindingCode.MISSING_PROVENANCE}


def test_doctor_rejects_conflicting_source_generations_order_independently() -> None:
    sources = [
        SourceRecord(identity="Notes/product.md", generation="generation-a"),
        SourceRecord(identity="Notes/product.md", generation="generation-b"),
    ]
    first = diagnose_mirror_corruption(
        inventory=_inventory(), sources=sources, projections=[_projection()]
    )
    reversed_sources = diagnose_mirror_corruption(
        inventory=_inventory(), sources=list(reversed(sources)), projections=[_projection()]
    )

    assert first.healthy is False
    assert first == reversed_sources
    assert {
        finding.code for finding in first.findings
    } == {MirrorFindingCode.CONFLICTING_SOURCE_GENERATION}


def test_doctor_reports_missing_projection_identity() -> None:
    report = diagnose_mirror_corruption(
        inventory=_inventory(), sources=[_source()], projections=[_projection(projection_id=" ")]
    )

    assert MirrorFindingCode.MISSING_IDENTITY in {finding.code for finding in report.findings}


def test_doctor_reports_unreferenced_malformed_source_records() -> None:
    report = diagnose_mirror_corruption(
        inventory=_inventory(),
        sources=[
            SourceRecord(identity=" ", generation="generation"),
            SourceRecord(identity="Notes/product.md", generation=" "),
        ],
        projections=[],
    )

    assert {finding.code for finding in report.findings} == {
        MirrorFindingCode.MISSING_IDENTITY,
        MirrorFindingCode.MISSING_PROVENANCE,
    }


def test_doctor_reports_missing_path_identity() -> None:
    report = diagnose_mirror_corruption(
        inventory=[
            DurablePath(
                path=" ",
                classification=DurablePathClass.DERIVED,
                owner="owner",
                rebuild_or_retention_source="source",
            )
        ],
        sources=[],
        projections=[],
    )

    assert report.findings[0].code is MirrorFindingCode.UNCLASSIFIED_PATH


def test_rebuildability_doctor_rejects_malformed_authority_flag(tmp_path) -> None:
    snapshot = tmp_path / "malformed-flag.json"
    snapshot.write_text(
        json.dumps(
            {
                "complete": True,
                "inventory": [
                    {
                        "path": "queue",
                        "classification": "operational_exception",
                        "owner": "owner",
                        "rebuild_or_retention_source": "source",
                        "sole_action_authority": "true",
                    }
                ],
                "sources": [],
                "projections": [],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["rebuildability-doctor", "--snapshot", str(snapshot)])

    assert result.exit_code == 1
    assert "authority flags must be boolean" in result.output
