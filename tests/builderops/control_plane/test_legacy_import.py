"""BCP-03 import-engine acceptance tests (AC2, AC3, AC4, CKM/CEG, AC6) plus the
review-round regression tests for repo evidence, hash re-verification, epic-run
normalization, cross-group reservations, crash-resume, and repo_ref validation.

All tests run without Postgres (`not pg`): the deterministic import engine targets
the domain-neutral :class:`AuthoritySink`, exercised here through the in-memory
adapter, and reads real on-disk legacy fixture sources.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.builderops.control_plane.models import EnvelopeValidationError
from app.builderops.control_plane.legacy_migration import (
    AuthorityReplayError,
    ConflictResolution,
    Disposition,
    InMemoryAuthoritySink,
    InventoryAcknowledgement,
    NormalizedRecord,
    RootKind,
    SourceChangedError,
    build_coverage_manifest,
    default_reader,
    import_records,
    normalize_sources,
    read_builderops_sqlite,
    read_dispatcher_sqlite,
    read_epic_run_json,
    run_migration,
)

from tests.builderops.control_plane import _legacy_fixtures as fx


def _manifest_and_ack(universe, *, host="demerzel"):
    freshness = fx.iso_now()
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


def _expected_root_for(path: Path, *, producer: str, source_class: str, repo=None):
    return fx.ExpectedRoot(
        producer=producer,
        source_class=source_class,
        host="macbook",
        user="rasmus",
        root_kind=RootKind.GIT_WORKTREE,
        path=str(path),
        authority_bearing=True,
        repo_identity=repo,
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
    assert run_a.import_result.replayed == ()  # first pass applied everything

    # Deterministic: a fresh sink over the same frozen inputs yields the same
    # normalized plan and the same applied authority set.
    sink_b = InMemoryAuthoritySink()
    run_b = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink_b, epoch_id="e1")
    assert run_a.import_result.result_hash == run_b.import_result.result_hash
    assert run_a.ledger.ledger_hash == run_b.ledger.ledger_hash
    assert sink_a.applied == sink_b.applied

    # Restart-safe/idempotent: re-running the SAME sink with IDENTICAL args
    # resumes the epoch as a no-op, changes nothing in the sink, reports every
    # authority row as replayed, and returns the identical result hash.
    rerun = run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink_a, epoch_id="e1")
    assert rerun.import_result.result_hash == run_a.import_result.result_hash
    assert sink_a.applied == applied_after_first
    assert set(rerun.import_result.replayed) == set(run_a.import_result.imported)

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
        run_migration(expected_roots=expected, manifest=manifest, ack=ack, sink=sink_c, epoch_id="e1")
    assert sink_c.applied == {}
    assert sink_c.epoch_id is None


def test_source_mutated_mid_read_fails_post_read_verification(tmp_path: Path) -> None:
    """Adapters hash-verify before AND after the read (F4): a multi-file source
    mutated between its pre-check and the end of its read fails closed."""

    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    manifest, _ack = _manifest_and_ack(expected)
    mutated = {"done": False}

    def mid_read_mutating_reader(observed):
        records = default_reader(observed)
        if observed.expected.producer == "epic_run_state" and not mutated["done"]:
            # Simulates a concurrent writer landing a file DURING the read,
            # after the pre-read hash check already passed.
            (Path(observed.expected.path) / "sneaky.json").write_text("{}", encoding="utf-8")
            mutated["done"] = True
        return records

    with pytest.raises(SourceChangedError, match="changed during read"):
        normalize_sources(manifest, reader=mid_read_mutating_reader)
    assert mutated["done"]


def test_crash_mid_apply_resumes_with_identical_args_and_result_hash(tmp_path: Path) -> None:
    """F9: a crash mid-apply retried with IDENTICAL args resumes the epoch,
    completes, and returns the same result hash as an uncrashed run."""

    universe = fx.build_full_universe(tmp_path)
    expected = universe["expected_roots"]
    manifest, ack = _manifest_and_ack(expected)

    clean_sink = InMemoryAuthoritySink()
    clean = run_migration(
        expected_roots=expected, manifest=manifest, ack=ack, sink=clean_sink, epoch_id="e1"
    )

    crash_sink = InMemoryAuthoritySink()
    original_apply = crash_sink.apply_authority_record
    calls = {"n": 0}

    def flaky_apply(record):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated crash mid-apply")
        return original_apply(record)

    crash_sink.apply_authority_record = flaky_apply  # instance-level shadow
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_migration(
            expected_roots=expected, manifest=manifest, ack=ack, sink=crash_sink, epoch_id="e1"
        )
    del crash_sink.apply_authority_record  # restore the real method
    assert crash_sink.applied  # partial state survived the crash
    assert len(crash_sink.applied) < len(clean_sink.applied)

    # Retry with IDENTICAL arguments: same epoch resumes (no-op begin_epoch),
    # completion is reached, the plan hash is identical, and the rows applied
    # before the crash come back as replayed.
    resumed = run_migration(
        expected_roots=expected, manifest=manifest, ack=ack, sink=crash_sink, epoch_id="e1"
    )
    assert resumed.import_result.result_hash == clean.import_result.result_hash
    assert crash_sink.applied == clean_sink.applied
    assert resumed.import_result.replayed  # pre-crash applies acknowledged as replays
    assert not resumed.cutover_blocked


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


def test_cross_group_reserved_key_collision_blocks_at_planning_time() -> None:
    """F7: a clean record in ANOTHER group sharing a legacy key (here a lease_id
    operation key) with a tombstoned group must block at planning time — the run
    completes, the sink never raises mid-apply."""

    left = _authority_record(
        "wt-a#dispatcher_tasks:shared-3789",
        content_hash="hash-left",
        operation_keys=("lease-shared-1",),
    )
    right = _authority_record(
        "wt-b#dispatcher_tasks:shared-3789",
        content_hash="hash-right",
        operation_keys=("lease-shared-1",),
    )
    # A CLEAN verification_run group whose row carries the same lease_id.
    bystander = _authority_record(
        "wt-a#verification_runs:vrun-9",
        identity_key="verification_runs:vrun-9",
        content_hash="hash-vrun",
        object_kind="verification_run",
        operation_keys=("lease-shared-1",),
    )

    sink = InMemoryAuthoritySink()
    result = import_records(  # completes: no mid-apply AuthorityReplayError
        [left, right, bystander],
        sink=sink,
        epoch_id="e1",
        resolutions=[
            ConflictResolution(
                object_kind="dispatcher_task",
                identity_key="dispatcher_task:shared-3789",
                kind="tombstone",
                reason="divergent, tombstoned",
            )
        ],
    )
    assert result.dispositions[bystander.source_ref] == Disposition.BLOCKED
    collision = [b for b in result.blocked if b.identity_key == "verification_runs:vrun-9"]
    assert collision and "cross-group reserved-key collision" in collision[0].reason
    assert ("verification_run", "verification_runs:vrun-9") not in sink.applied
    assert result.cutover_blocked


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
# F2: repo evidence is row-bound, never root-defaulted
# ---------------------------------------------------------------------------


def test_repo_evidence_is_row_bound_for_dispatcher_and_builderops(tmp_path: Path) -> None:
    """Under a root with NO registered repo identity, repo evidence must come
    from the rows: dispatcher `repo`, verification_runs `repository`, attempts/
    exceptions joined via run_id, and the decoded BuilderOps record payload."""

    freshness = fx.iso_now()
    probe = fx.make_probe(freshness_at=freshness)

    dispatcher_db = tmp_path / "runtime/dispatcher/dispatcher.sqlite3"
    fx.write_dispatcher_sqlite(dispatcher_db)  # includes verification rows
    dispatcher_root = _expected_root_for(
        dispatcher_db, producer="dispatcher_store", source_class="dispatcher_sqlite", repo=None
    )
    dispatcher_records = read_dispatcher_sqlite(probe(dispatcher_root))
    by_kind = {}
    for record in dispatcher_records:
        by_kind.setdefault(record.object_kind, []).append(record)

    # dispatcher_tasks.repo column.
    assert all(r.repo_ref == fx.REPO_CANON for r in by_kind["dispatcher_task"])
    # verification_runs.repository column (F2a).
    assert all(r.repo_ref == fx.REPO_CANON for r in by_kind["verification_run"])
    # attempts/exceptions have NO repo column: joined via run_id (F2b).
    assert all(r.repo_ref == fx.REPO_CANON for r in by_kind["verification_attempt"])
    assert all(r.repo_ref == fx.REPO_CANON for r in by_kind["verification_exception"])
    # dispatcher_meta rows carry no evidence and the root has none: ambiguous.
    assert all(r.repo_ref is None for r in by_kind["dispatcher_meta"])

    # BuilderOps record payload is a JSON TEXT column: decoded for evidence (F2c).
    builderops_db = tmp_path / "runtime/builderops/builderops.sqlite3"
    fx.write_builderops_sqlite(builderops_db, payload_repo=fx.REPO)
    builderops_root = _expected_root_for(
        builderops_db, producer="builderops_store", source_class="builderops_sqlite", repo=None
    )
    builderops_records = read_builderops_sqlite(probe(builderops_root))
    worklogs = [r for r in builderops_records if r.object_kind == "builderops_record"]
    assert worklogs and all(r.repo_ref == fx.REPO_CANON for r in worklogs)


def test_malformed_repo_evidence_fails_closed() -> None:
    """F12: a malformed repo reference never imports cleanly — normalization
    (and mapping/resolution entry validation) fails closed."""

    with pytest.raises(EnvelopeValidationError):
        _authority_record("x#task:1", content_hash="h", repo_ref="not-a-repo-reference")

    clean = _authority_record("x#task:1", content_hash="h", repo_ref=None)
    sink = InMemoryAuthoritySink()
    with pytest.raises(EnvelopeValidationError):
        import_records(
            [clean], sink=sink, epoch_id="e1", repo_mappings={"x#task:1": "garbage repo!!"}
        )
    with pytest.raises(EnvelopeValidationError):
        import_records(
            [clean],
            sink=sink,
            epoch_id="e1",
            resolutions=[
                ConflictResolution(
                    object_kind="dispatcher_task",
                    identity_key="dispatcher_task:shared-3789",
                    kind="evidence",
                    winner_source_ref="x#task:1",
                    repo_ref="also garbage",
                )
            ],
        )


# ---------------------------------------------------------------------------
# F6: epic-run states import via producer validation
# ---------------------------------------------------------------------------


def test_epic_run_old_shape_normalizes_and_invalid_fails_closed(tmp_path: Path) -> None:
    freshness = fx.iso_now()
    probe = fx.make_probe(freshness_at=freshness)

    # Root A: current-shape state written by the real producer.
    root_a = tmp_path / "wt-a/runtime/builderops/epic-runs"
    fx.write_epic_run_json(root_a, run_id="epic-3788-run-9")
    # Root B: an OLD-SHAPE file of the same run — several later-added list
    # fields absent (the _STATE_FIELDS growth case). deserialize fills defaults.
    root_b = tmp_path / "wt-b/runtime/builderops/epic-runs"
    root_b.mkdir(parents=True)
    old_shape = {
        "schema_version": 1,
        "epic_issue_number": 3788,
        "run_id": "epic-3788-run-9",
        "child_queue": [3789, 3790],
    }
    (root_b / "epic-3788-run-9.json").write_text(json.dumps(old_shape), encoding="utf-8")
    # Root B also holds a file the producer REJECTS (unknown field).
    (root_b / "epic-bad.json").write_text(
        json.dumps({"schema_version": 1, "run_id": "epic-bad", "epic_issue_number": 1, "hax": 1}),
        encoding="utf-8",
    )

    records_a = read_epic_run_json(
        probe(_expected_root_for(root_a, producer="epic_run_state", source_class="epic_run_json", repo=fx.REPO))
    )
    records_b = read_epic_run_json(
        probe(_expected_root_for(root_b, producer="epic_run_state", source_class="epic_run_json", repo=fx.REPO))
    )

    # The old-shape file normalizes to the same envelope -> same content hash ->
    # dedup, not a spurious authority-divergence block.
    run_a = next(r for r in records_a if r.identity_key == "epic_run:epic-3788-run-9")
    run_b = next(r for r in records_b if r.identity_key == "epic_run:epic-3788-run-9")
    assert run_a.content_hash == run_b.content_hash

    sink = InMemoryAuthoritySink()
    result = import_records([*records_a, *records_b], sink=sink, epoch_id="e1")
    assert not result.cutover_blocked
    assert result.dispositions[run_a.source_ref] == Disposition.IMPORTED
    assert result.dispositions[run_b.source_ref] == Disposition.DEDUPLICATED

    # The producer-rejected file failed closed: quarantined evidence, never
    # imported as authority.
    invalid = next(r for r in records_b if r.invalid_reason is not None)
    assert invalid.authority_bearing is False
    assert result.dispositions[invalid.source_ref] == Disposition.EVIDENCE_QUARANTINED
    assert not any("epic-bad" in identity for (_kind, identity) in sink.applied)
    assert sink.quarantines[invalid.source_ref].authorizes_effect() is False


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
        assert record.repo_ref == fx.REPO_CANON
        assert record.provenance["producer"] == "builderops_store"

    # The post-freeze schema addition (new column) is imported, payload included.
    grown = [r for r in ckm_records if grown_id in r.identity_key]
    assert grown, "grown CKM capability must be inventoried"
    assert "confidence_note" in grown[0].payload
    assert any(
        kind[0].startswith("builderops_store:ckm_capability") and grown_id in kind[1]
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
