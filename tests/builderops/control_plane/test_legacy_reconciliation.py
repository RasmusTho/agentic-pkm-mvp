"""BCP-03 AC7: reconciliation accounts for the whole expected universe and blocks
cutover on any coverage or authority-replay gap. Runs without Postgres (`not pg`).
"""

from __future__ import annotations

from pathlib import Path

from app.builderops.control_plane.legacy_migration import (
    Disposition,
    InMemoryAuthoritySink,
    InventoryAcknowledgement,
    build_coverage_manifest,
    import_records,
    normalize_sources,
    reconcile,
    run_migration,
)

from tests.builderops.control_plane import _legacy_fixtures as fx

_ACCOUNTED = {
    Disposition.IMPORTED,
    Disposition.DEDUPLICATED,
    Disposition.EVIDENCE_QUARANTINED,
    Disposition.AUTHORITY_TOMBSTONED,
    Disposition.EXPIRED_LEASE,
    Disposition.MISSING,
    Disposition.INACCESSIBLE,
    Disposition.EXCLUDED,
    Disposition.ARCHIVED,
    Disposition.BLOCKED,
}


def _ack(manifest, host="demerzel"):
    return InventoryAcknowledgement(
        host=host,
        user="rasmus",
        manifest_hash=manifest.manifest_hash,
        acknowledged_at=manifest.freshness_at,
        freshness_horizon_seconds=3600,
    )


def test_reconciliation_accounts_for_expected_universe_and_blocks_coverage_gaps(
    tmp_path: Path,
) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    manifest, ack = _reconcilable(expected)

    sink = InMemoryAuthoritySink()
    run = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink, epoch_id="e1")
    ledger = run.ledger

    # Every expected producer is accounted for, with a root count.
    assert set(ledger.producers_accounted) == {
        "builderops_store",
        "dispatcher_store",
        "dispatcher_events",
        "epic_run_state",
        "model_inquiry",
    }
    # Every expected root has a disposition.
    assert set(ledger.roots) == {root.key for root in expected}
    assert all(disposition in _ACCOUNTED for disposition in ledger.roots.values())
    # Every source item is accounted with an admissible disposition.
    assert ledger.items
    assert all(disposition in _ACCOUNTED for disposition in ledger.items.values())
    # A clean universe imports without blocking cutover.
    assert not ledger.cutover_blocked
    assert ledger.coverage_gaps == ()
    assert ledger.authority_replay_gaps == ()


def test_reconciliation_blocks_on_missing_root_coverage_gap(tmp_path: Path) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    freshness = fx._iso(fx.now())

    # Delete one expected source so it is missing at freeze.
    missing = next(r for r in expected if r.producer == "dispatcher_store")
    Path(missing.path).unlink()

    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        expected, probe=probe, host="demerzel", user="rasmus", freshness_at=freshness
    )
    # Import only the usable sources; the missing root is a coverage gap.
    records = normalize_sources(manifest)
    sink = InMemoryAuthoritySink()
    import_result = import_records(records, sink=sink, epoch_id="e1")
    ledger = reconcile(
        expected_roots=expected,
        manifest=manifest,
        records=records,
        import_result=import_result,
    )
    assert missing.key in ledger.coverage_gaps
    assert ledger.roots[missing.key] == Disposition.MISSING
    assert ledger.cutover_blocked


def test_reconciliation_blocks_on_authority_replay_gap(tmp_path: Path) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    manifest, ack = _reconcilable(expected)
    records = list(normalize_sources(manifest))

    # Inject an unresolved authority conflict (two divergent authority-bearing
    # records sharing one identity) into the record set.
    from app.builderops.control_plane.legacy_migration import NormalizedRecord

    def _clash(source_ref: str, marker: str) -> NormalizedRecord:
        return NormalizedRecord(
            source_ref=source_ref,
            object_kind="dispatcher_task",
            identity_key="dispatcher_task:clash-1",
            authority_bearing=True,
            content_hash=f"hash-{marker}",
            repo_ref=fx.REPO,
            scope="legacy:dispatcher_store",
            stack="builderops-legacy",
            provenance={"path": source_ref},
            payload={"marker": marker},
        )

    records.extend([_clash("wt-a#clash", "a"), _clash("wt-b#clash", "b")])
    sink = InMemoryAuthoritySink()
    import_result = import_records(records, sink=sink, epoch_id="e1")
    ledger = reconcile(
        expected_roots=expected,
        manifest=manifest,
        records=records,
        import_result=import_result,
    )
    # The unresolved authority conflict is an authority-replay gap that blocks
    # cutover even though coverage is complete.
    assert "dispatcher_task:clash-1" in ledger.authority_replay_gaps
    assert ledger.coverage_gaps == ()
    assert ledger.cutover_blocked


def test_reconciliation_accounts_excluded_and_archived_roots(tmp_path: Path) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    freshness = fx._iso(fx.now())

    # Intentionally exclude the dispatcher event log; treat one epic-run root as
    # already archived. Both must remain ACCOUNTED (never silently subtracted).
    excluded = next(r for r in expected if r.producer == "dispatcher_events")
    archived_root = next(r for r in expected if r.producer == "epic_run_state")
    exclusions = {excluded.key: "superseded audit log, not migrated"}

    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        expected,
        probe=probe,
        host="demerzel",
        user="rasmus",
        freshness_at=freshness,
        exclusions=exclusions,
    )
    # An excluded root does not make the manifest blocking even if unusable.
    records = normalize_sources(manifest)
    sink = InMemoryAuthoritySink()
    import_result = import_records(records, sink=sink, epoch_id="e1")
    ledger = reconcile(
        expected_roots=expected,
        manifest=manifest,
        records=records,
        import_result=import_result,
        archived={archived_root.key: "cold-stored 2026-07"},
    )
    assert ledger.roots[excluded.key] == Disposition.EXCLUDED
    assert ledger.roots[archived_root.key] == Disposition.ARCHIVED
    # Excluded/archived roots are accounted, so they are not coverage gaps.
    assert excluded.key not in ledger.coverage_gaps
    assert archived_root.key not in ledger.coverage_gaps


def _reconcilable(expected):
    freshness = fx._iso(fx.now())
    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        expected, probe=probe, host="demerzel", user="rasmus", freshness_at=freshness
    )
    return manifest, _ack(manifest)
