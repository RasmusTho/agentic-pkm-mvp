"""BCP-03 AC5: file-first authority imports envelope + receipts with hash-linked
artifacts (no file-only terminal state). Runs without Postgres (`not pg`)."""

from __future__ import annotations

import hashlib
import json
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
    freshness = fx.iso_now()
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

    # Immutable question/turn artifacts stay external, referenced by a content
    # hash COMPUTED from the artifact bytes — never trusted from the file's own
    # artifact_hash field (F5). The declared hash is carried as evidence.
    assert inquiry_record.artifact_refs, "inquiry must carry hash-linked artifact refs"
    refs_by_id = {a.artifact_id: a for a in inquiry_record.artifact_refs}
    assert {"question", "turn-000001"} <= set(refs_by_id)
    for artifact in inquiry_record.artifact_refs:
        computed = hashlib.sha256(Path(artifact.location).read_bytes()).hexdigest()
        assert artifact.content_hash == computed  # equality, not truthiness
    # The self-reported hash (the store's canonical-JSON scheme) is recorded
    # verbatim as declared evidence.
    declared = {
        "question": refs_by_id["question"].declared_hash,
        "turn-000001": refs_by_id["turn-000001"].declared_hash,
    }
    for artifact_id, declared_hash in declared.items():
        assert declared_hash is not None
        # Mirror of model_inquiry._artifact_hash over the on-disk payload.
        payload = json.loads(Path(refs_by_id[artifact_id].location).read_text("utf-8"))
        assert declared_hash == fx.model_inquiry_artifact_hash(payload)

    # Inquiry receipts live under receipts/<name>.json (the store's REAL layout,
    # mirroring _read_receipts) and import as their own authority receipts with
    # their real file names — not file-only, not silently dropped (F1).
    receipts = [r for r in run.records if r.object_kind == "model_inquiry_receipt"]
    receipt_files = {r.provenance["receipt_file"] for r in receipts}
    assert receipt_files == {"inquiry-started.json", "inquiry-run-terminal.json"}
    receipt_ids = {str(r.payload["id"]) for r in receipts}
    assert receipt_ids == {"rcpt-start", "rcpt-run-terminal"}
    for receipt in receipts:
        assert run.import_result.dispositions[receipt.source_ref] in {
            Disposition.IMPORTED,
            Disposition.DEDUPLICATED,
        }
    # And the receipts are NOT double-counted as opaque artifacts.
    assert not {"rcpt-start", "rcpt-run-terminal"} & set(refs_by_id)

    # Epic-run authoritative state imports with a content hash over the envelope.
    epic_record = epic[0]
    assert run.import_result.dispositions[epic_record.source_ref] in {
        Disposition.IMPORTED,
        Disposition.DEDUPLICATED,
    }
    assert epic_record.content_hash
    assert epic_record.payload["run_id"]

    # The import receipt is machine-readable for BCP-06, preserves the
    # #3686 / PR #3695 fragmentation evidence, and surfaces the remote-env
    # limitation for the env-less host.
    receipts_json = run.receipts.as_json()
    assert set(receipts_json) == {"preflight", "dry_run", "import_apply", "reconciliation"}
    assert receipts_json["preflight"]["evidence_refs"] == ["issue:3686", "pr:3695"]
    assert receipts_json["preflight"]["env_unknown_hosts"] == ["demerzel"]
