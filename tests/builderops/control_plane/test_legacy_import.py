"""BCP-03 import-engine acceptance tests (AC2, AC3, AC4, CKM/CEG, AC6).

All tests run without Postgres (`not pg`): the deterministic import engine targets
the domain-neutral :class:`AuthoritySink`, exercised here through the in-memory
adapter, and reads real on-disk legacy fixture sources.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.control_plane.legacy_migration import (
    AuthorityReplayError,
    ConflictResolution,
    Disposition,
    InMemoryAuthoritySink,
    InventoryAcknowledgement,
    NormalizedRecord,
    SourceChangedError,
    build_coverage_manifest,
    import_records,
    run_migration,
)

from tests.builderops.control_plane import _legacy_fixtures as fx


def _manifest_and_ack(universe, *, host="demerzel"):
    freshness = fx._iso(fx.now())
    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        universe, probe=probe, host=host, user="rasmus", freshness_at=freshness
    )
    ack = InventoryAcknowledgement(
        host=host,
        user="rasmus",
        manifest_hash=manifest.manifest_hash,
        acknowledged_at=freshness,
        freshness_horizon_seconds=3600,
    )
    return manifest, ack


def _authority_record(
    source_ref: str,
    *,
    identity_key: str = "dispatcher_task:shared-3789",
    content_hash: str,
    repo_ref: str | None = fx.REPO,
    idempotency_keys: tuple[str, ...] = (),
    operation_keys: tuple[str, ...] = (),
    authority_bearing: bool = True,
    object_kind: str = "dispatcher_task",
) -> NormalizedRecord:
    return NormalizedRecord(
        source_ref=source_ref,
        object_kind=object_kind,
        identity_key=identity_key,
        authority_bearing=authority_bearing,
        content_hash=content_hash,
        repo_ref=repo_ref,
        scope="legacy:dispatcher_store",
        stack="builderops-legacy",
        provenance={"path": source_ref},
        payload={"task_id": "shared-3789", "marker": content_hash},
        idempotency_keys=idempotency_keys,
        operation_keys=operation_keys,
    )


# ---------------------------------------------------------------------------
# AC2: restart-safe / idempotent and rejects a changed source
# ---------------------------------------------------------------------------


def test_import_is_restart_safe_and_rejects_changed_source(tmp_path: Path) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    manifest, ack = _manifest_and_ack(expected)

    sink_a = InMemoryAuthoritySink()
    run_a = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink_a, epoch_id="e1")
    applied_after_first = dict(sink_a.applied)
    assert applied_after_first  # something was imported
    assert not run_a.cutover_blocked

    # Deterministic: a fresh sink over the same frozen inputs yields the same
    # normalized result and the same applied authority set.
    sink_b = InMemoryAuthoritySink()
    run_b = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink_b, epoch_id="e1")
    assert run_a.import_result.result_hash == run_b.import_result.result_hash
    assert run_a.ledger.ledger_hash == run_b.ledger.ledger_hash
    assert sink_a.applied == sink_b.applied

    # Restart-safe/idempotent: re-running the SAME sink imports nothing new; every
    # authority row is a dedup no-op and no state changes.
    rerun = run_migration(
        expected_roots=expected, manifest=manifest, ack=ack, sink=sink_a, epoch_id="e2", fencing_base=2
    )
    assert rerun.import_result.imported == ()
    assert sink_a.applied == applied_after_first

    # A source changed after freeze fails hash verification and imports nothing.
    macbook_builderops = universe["macbook_worktree"] / "runtime/builderops/builderops.sqlite3"
    from app.builderops.store import SqliteBuilderOpsStore

    tamper = SqliteBuilderOpsStore(macbook_builderops)
    tamper.create_agent_worklog(
        summary="post-freeze mutation",
        body="changed after freeze",
        task_context={},
        source_refs=[{"ref_type": "github_issue", "ref": "#3789"}],
        created_by={"actor_type": "agent", "id": "codex-fixture"},
        idempotency_key="post-freeze-1",
    )
    sink_c = InMemoryAuthoritySink()
    with pytest.raises(SourceChangedError):
        run_migration(
            expected_roots=expected, manifest=manifest, ack=ack, sink=sink_c, epoch_id="e1"
        )
    assert sink_c.applied == {}
    assert sink_c.epoch_id is None


# ---------------------------------------------------------------------------
# AC3: divergent equal authority-bearing identities block cutover
# ---------------------------------------------------------------------------


def test_conflicting_identity_requires_resolution_or_duplicate_preventing_tombstone() -> None:
    left = _authority_record(
        "wt-a#dispatcher_tasks:shared-3789",
        content_hash="hash-left",
        idempotency_keys=("idem-left",),
        operation_keys=("op-left",),
    )
    right = _authority_record(
        "wt-b#dispatcher_tasks:shared-3789",
        content_hash="hash-right",
        idempotency_keys=("idem-right",),
        operation_keys=("op-right",),
    )

    # No resolution: neither wins; cutover blocks (not last-write-wins, not
    # plain quarantine).
    sink = InMemoryAuthoritySink()
    blocked = import_records([left, right], sink=sink, epoch_id="e1")
    assert blocked.cutover_blocked
    assert blocked.blocked and blocked.blocked[0].identity_key == "dispatcher_task:shared-3789"
    assert blocked.dispositions["wt-a#dispatcher_tasks:shared-3789"] == Disposition.BLOCKED
    assert ("dispatcher_task", "dispatcher_task:shared-3789") not in sink.applied

    # Evidence resolution: an explicit winner is imported, the other deduplicated.
    sink_ev = InMemoryAuthoritySink()
    resolved = import_records(
        [left, right],
        sink=sink_ev,
        epoch_id="e1",
        resolutions=[
            ConflictResolution(
                object_kind="dispatcher_task",
                identity_key="dispatcher_task:shared-3789",
                kind="evidence",
                winner_source_ref=left.source_ref,
                reason="operator picked worktree-a as canonical",
            )
        ],
    )
    assert not resolved.cutover_blocked
    assert resolved.dispositions[left.source_ref] == Disposition.IMPORTED
    assert resolved.dispositions[right.source_ref] == Disposition.DEDUPLICATED
    assert sink_ev.applied[("dispatcher_task", "dispatcher_task:shared-3789")] == "hash-left"

    # Duplicate-preventing tombstone: reserves every legacy identity/idempotency/
    # operation key, cannot authorize, and makes replay fail closed.
    sink_tomb = InMemoryAuthoritySink()
    tombstoned = import_records(
        [left, right],
        sink=sink_tomb,
        epoch_id="e1",
        resolutions=[
            ConflictResolution(
                object_kind="dispatcher_task",
                identity_key="dispatcher_task:shared-3789",
                kind="tombstone",
                reason="unresolvable without more evidence",
            )
        ],
    )
    assert not tombstoned.cutover_blocked
    assert set(tombstoned.tombstoned) == {left.source_ref, right.source_ref}
    tombstone = sink_tomb.tombstones[("dispatcher_task", "dispatcher_task:shared-3789")]
    assert tombstone.authorizes_effect() is False
    assert {"idem-left", "idem-right"} <= tombstone.reserved_idempotency_keys
    assert {"op-left", "op-right"} <= tombstone.reserved_operation_keys
    assert "dispatcher_task:shared-3789" in tombstone.reserved_identity_keys
    assert tombstone.source_hashes == ("hash-left", "hash-right")

    # Replay of any reserved legacy key fails closed as a manual conflict.
    assert sink_tomb.is_reserved(idempotency_key="idem-left")
    replay = _authority_record(
        "wt-a#dispatcher_tasks:shared-3789",
        content_hash="hash-left",
        idempotency_keys=("idem-left",),
    )
    with pytest.raises(AuthorityReplayError):
        sink_tomb.apply_authority_record(replay)


# ---------------------------------------------------------------------------
# AC4: live legacy leases never cross the authority epoch
# ---------------------------------------------------------------------------


def test_live_legacy_leases_do_not_cross_authority_epoch(tmp_path: Path) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    manifest, ack = _manifest_and_ack(expected)

    sink = InMemoryAuthoritySink()
    run = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink, epoch_id="epoch-1")

    # The fixtures wrote LIVE leases (future expiry): they must be observed live
    # at freeze yet imported only as expired evidence.
    live_leases = [r for r in run.records if r.is_lease and r.lease_state == "live"]
    assert live_leases, "fixture must contain at least one live lease"

    # No lease crosses the epoch as a live authority row.
    assert not any(kind == "lease" for (kind, _identity) in sink.applied)
    assert sink.has_live_lease("anything") is False
    assert sink.expired_leases  # imported as expired evidence

    for lease in live_leases:
        assert run.import_result.dispositions[lease.source_ref] == Disposition.EXPIRED_LEASE
        evidence = sink.expired_leases[lease.source_ref]
        assert evidence.authorizes_mutation() is False
        assert evidence.legacy_state == "live"

    # A new authority epoch/fencing base was established for the imported state.
    assert sink.epoch_id == "epoch-1"
    assert sink.fencing_base == 1

    # An expired-lease evidence row can never be applied as live authority.
    lease_record = live_leases[0]
    with pytest.raises(Exception):
        sink.apply_authority_record(lease_record)


# ---------------------------------------------------------------------------
# CKM/CEG (spec AC): CKM tables inventoried and imported with schema growth
# ---------------------------------------------------------------------------


def test_ckm_ceg_tables_are_inventoried_and_imported(tmp_path: Path) -> None:
    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]

    # Add a CKM schema-growth capability (a new column) BEFORE freeze, proving the
    # generic adapter covers additions made between spec acceptance and freeze.
    macbook_builderops = universe["macbook_worktree"] / "runtime/builderops/builderops.sqlite3"
    grown_id = fx.add_ckm_schema_growth_row(macbook_builderops)

    manifest, ack = _manifest_and_ack(expected)
    sink = InMemoryAuthoritySink()
    run = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink, epoch_id="epoch-1")

    ckm_records = [r for r in run.records if r.object_kind.endswith("ckm_capability")]
    ckm_artifacts = [r for r in run.records if r.object_kind.endswith("ckm_artifact")]
    assert ckm_records, "CKM capability tables must be inventoried"
    assert ckm_artifacts, "CKM artifact tables must be inventoried"

    # Same identity/provenance discipline: CKM rows are authority-bearing, carry
    # evidence-bound repo provenance, and import into the sink.
    for record in ckm_records + ckm_artifacts:
        assert record.authority_bearing is True
        assert record.repo_ref == fx.REPO
        assert record.provenance["producer"] == "builderops_store"

    # The post-freeze schema addition (new column) is imported, payload included.
    grown = [r for r in ckm_records if grown_id in r.identity_key]
    assert grown, "grown CKM capability must be inventoried"
    assert "confidence_note" in grown[0].payload
    assert any(
        kind[0].startswith("builderops_store:ckm_capability")
        and grown_id in kind[1]
        for kind in sink.applied
    )


# ---------------------------------------------------------------------------
# AC6: authority-bearing ambiguity resolved/tombstoned; evidence-only quarantined
# ---------------------------------------------------------------------------


def test_authority_ambiguity_requires_resolution_or_duplicate_preventing_tombstone() -> None:
    # Authority-bearing record with NO evidence-bound repo provenance.
    ambiguous = _authority_record(
        "host-stable#dispatcher_tasks:orphan-9001",
        identity_key="dispatcher_task:orphan-9001",
        content_hash="hash-orphan",
        repo_ref=None,
        idempotency_keys=("idem-orphan",),
        operation_keys=("op-orphan",),
    )

    # Never defaulted from CWD/import target: with no evidence, cutover blocks.
    sink = InMemoryAuthoritySink()
    blocked = import_records([ambiguous], sink=sink, epoch_id="e1")
    assert blocked.cutover_blocked
    assert blocked.blocked[0].reason.startswith("authority-bearing ambiguous repo")
    assert ("dispatcher_task", "dispatcher_task:orphan-9001") not in sink.applied

    # Evidence-bound mapping backfills repo provenance -> imports cleanly.
    sink_map = InMemoryAuthoritySink()
    resolved_map = import_records(
        [ambiguous],
        sink=sink_map,
        epoch_id="e1",
        repo_mappings={ambiguous.source_ref: fx.REPO},
    )
    assert not resolved_map.cutover_blocked
    assert resolved_map.dispositions[ambiguous.source_ref] == Disposition.IMPORTED

    # A duplicate-preventing tombstone is the other admissible outcome; it cannot
    # authorize a lease/effect/promotion/merge.
    sink_tomb = InMemoryAuthoritySink()
    tombstoned = import_records(
        [ambiguous],
        sink=sink_tomb,
        epoch_id="e1",
        resolutions=[
            ConflictResolution(
                object_kind="dispatcher_task",
                identity_key="dispatcher_task:orphan-9001",
                kind="tombstone",
                reason="no repo evidence available",
            )
        ],
    )
    assert not tombstoned.cutover_blocked
    tombstone = sink_tomb.tombstones[("dispatcher_task", "dispatcher_task:orphan-9001")]
    assert tombstone.authorizes_effect() is False
    assert "idem-orphan" in tombstone.reserved_idempotency_keys
    with pytest.raises(AuthorityReplayError):
        sink_tomb.apply_authority_record(ambiguous)

    # Evidence-ONLY ambiguity (non-authority-bearing) may remain plain,
    # non-authoritative quarantine — it does not block cutover.
    evidence_only = _authority_record(
        "host-stable#dispatcher_events:orphan-evt",
        identity_key="host-stable#dispatcher_event:orphan-evt",
        content_hash="hash-evt",
        repo_ref=None,
        authority_bearing=False,
        object_kind="dispatcher_event",
    )
    sink_q = InMemoryAuthoritySink()
    quarantined = import_records([evidence_only], sink=sink_q, epoch_id="e1")
    assert not quarantined.cutover_blocked
    assert quarantined.dispositions[evidence_only.source_ref] == Disposition.EVIDENCE_QUARANTINED
    item = sink_q.quarantines[evidence_only.source_ref]
    assert item.authorizes_effect() is False
