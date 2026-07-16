"""BCP-03 AC5: file-first authority imports envelope + receipts with hash-linked
artifacts (no file-only terminal state). Runs without Postgres (`not pg`)."""

from __future__ import annotations

from pathlib import Path

from app.builderops.control_plane.legacy_migration import (
    Disposition,
    InMemoryAuthoritySink,
    InventoryAcknowledgement,
    build_coverage_manifest,
    run_migration,
)

from tests.builderops.control_plane import _legacy_fixtures as fx


def test_file_first_authority_imports_envelope_and_receipts(tmp_path: Path) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    freshness = fx._iso(fx.now())
    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        expected, probe=probe, host="demerzel", user="rasmus", freshness_at=freshness
    )
    ack = InventoryAcknowledgement(
        host="demerzel",
        user="rasmus",
        manifest_hash=manifest.manifest_hash,
        acknowledged_at=freshness,
        freshness_horizon_seconds=3600,
    )
    sink = InMemoryAuthoritySink()
    run = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink, epoch_id="e1")

    # Both file-first authorities are represented in the sink: the inquiry
    # identity/manifest and the epic-run identity/state.
    inquiry = [r for r in run.records if r.object_kind == "model_inquiry"]
    epic = [r for r in run.records if r.object_kind == "epic_run"]
    assert inquiry, "model inquiry identity must be imported"
    assert epic, "epic-run identity must be imported"

    inquiry_record = inquiry[0]
    # Authoritative identity/state imports into the sink (PostgreSQL-authoritative
    # in production; the in-memory adapter mirrors that contract).
    assert run.import_result.dispositions[inquiry_record.source_ref] == Disposition.IMPORTED
    assert ("model_inquiry", inquiry_record.identity_key) in sink.applied

    # Immutable question/turn artifacts stay external, referenced by content hash
    # (no file-only terminal state): the authority row carries the artifact refs.
    assert inquiry_record.artifact_refs, "inquiry must carry hash-linked artifact refs"
    artifact_ids = {a.artifact_id for a in inquiry_record.artifact_refs}
    assert {"question", "turn-000001"} <= artifact_ids
    for artifact in inquiry_record.artifact_refs:
        assert artifact.content_hash  # every external artifact is content-addressed
        assert artifact.location  # and locatable

    # Inquiry receipts import as their own authority receipts (not file-only).
    receipts = [r for r in run.records if r.object_kind == "model_inquiry_receipt"]
    assert receipts, "inquiry receipts must be represented"
    for receipt in receipts:
        assert run.import_result.dispositions[receipt.source_ref] in {
            Disposition.IMPORTED,
            Disposition.DEDUPLICATED,
        }

    # Epic-run authoritative state imports with a content hash over the envelope.
    epic_record = epic[0]
    assert run.import_result.dispositions[epic_record.source_ref] in {
        Disposition.IMPORTED,
        Disposition.DEDUPLICATED,
    }
    assert epic_record.content_hash
    assert epic_record.payload["run_id"]

    # The import receipt is machine-readable for BCP-06 and preserves the
    # #3686 / PR #3695 fragmentation evidence.
    receipts_json = run.receipts.as_json()
    assert set(receipts_json) == {"preflight", "dry_run", "import_apply", "reconciliation"}
    assert receipts_json["preflight"]["evidence_refs"] == ["issue:3686", "pr:3695"]
