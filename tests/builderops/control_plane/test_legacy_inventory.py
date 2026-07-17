"""BCP-03 AC1: producer-derived inventory across the cutover-host universe.

These tests run without Postgres (`not pg`): the migration inventory layer is
pure/deterministic and operates on real on-disk fixture sources.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

from app.builderops.control_plane.legacy_migration import (
    AcknowledgementRejected,
    EnumeratedRoot,
    HostContext,
    InventoryAcknowledgement,
    InventoryCoverageError,
    RootKind,
    accept_acknowledgement,
    build_coverage_manifest,
    derive_expected_universe,
    producer,
    read_builderops_sqlite,
)

from tests.builderops.control_plane import _legacy_fixtures as fx


def _two_host_universe(tmp_path: Path) -> tuple[HostContext, ...]:
    """MacBook (one clone-set: primary wt-a + linked wt-b) plus a server-host
    (container + automation + vault), with real sources under every enumerated
    root, matching each producer's real resolution semantics: the dispatcher
    writes ONLY at the clone-set primary; builderops/epic-run state is
    CWD-relative per worktree."""

    mac_a = tmp_path / "mac/wt-a"
    mac_b = tmp_path / "mac/wt-b"
    demerzel_container = tmp_path / f"{fx.HOST_REMOTE}/mount"
    demerzel_automation = tmp_path / f"{fx.HOST_REMOTE}/launchd-state"
    demerzel_vault = tmp_path / f"{fx.HOST_REMOTE}/vault"

    fx.write_state_producers(mac_a)  # primary: all producers incl. dispatcher
    fx.write_state_producers(mac_b, dispatcher=False)  # linked: no dispatcher
    fx.write_state_producers(demerzel_container)
    fx.write_state_producers(demerzel_automation)
    fx.write_vault(demerzel_vault)

    return (
        HostContext(
            host="macbook",
            user=fx.OPERATOR,
            roots=(
                EnumeratedRoot(RootKind.GIT_WORKTREE, str(mac_a), repo_identity=fx.REPO),
                EnumeratedRoot(
                    RootKind.GIT_WORKTREE,
                    str(mac_b),
                    repo_identity=fx.REPO,
                    primary_worktree=str(mac_a),
                ),
            ),
            env={},
        ),
        HostContext(
            host=fx.HOST_REMOTE,
            user=fx.OPERATOR,
            roots=(
                EnumeratedRoot(
                    RootKind.CONTAINER_MOUNT, str(demerzel_container), repo_identity=fx.REPO
                ),
                EnumeratedRoot(
                    RootKind.AUTOMATION, str(demerzel_automation), repo_identity=fx.REPO
                ),
                EnumeratedRoot(RootKind.VAULT, str(demerzel_vault), repo_identity=fx.REPO),
            ),
            env={},
        ),
    )


def test_producer_derived_inventory_covers_hosts_worktrees_containers_and_automations(
    tmp_path: Path,
) -> None:
    hosts = _two_host_universe(tmp_path)
    universe = derive_expected_universe(hosts)

    # Every producer is represented.
    producers_seen = {root.producer for root in universe}
    assert producers_seen == {
        "builderops_store",
        "dispatcher_store",
        "dispatcher_events",
        "epic_run_state",
        "model_inquiry",
    }

    # Every enumerated root KIND is represented: hosts x worktrees x containers x
    # automations x vault. This is the "expected universe" proof.
    root_kinds_seen = {root.root_kind for root in universe}
    assert root_kinds_seen == {
        RootKind.GIT_WORKTREE,
        RootKind.CONTAINER_MOUNT,
        RootKind.AUTOMATION,
        RootKind.VAULT,
    }
    assert {root.host for root in universe} == {"macbook", fx.HOST_REMOTE}

    # CWD-resolved producers multiply per worktree (the #3686 fragmentation
    # case): the per-worktree builderops store appears once per worktree.
    builderops_worktrees = {
        root.path
        for root in universe
        if root.producer == "builderops_store" and root.root_kind == RootKind.GIT_WORKTREE
    }
    assert len(builderops_worktrees) == 2

    # The dispatcher resolves to the clone-set PRIMARY worktree
    # (app/dispatcher/config.py::_default_state_dir): exactly ONE expected
    # dispatcher root per clone-set, at the primary, even with two worktrees —
    # the linked worktree never gets a dispatcher path the runtime never writes.
    dispatcher_worktree_paths = {
        root.path
        for root in universe
        if root.producer == "dispatcher_store" and root.root_kind == RootKind.GIT_WORKTREE
    }
    assert len(dispatcher_worktree_paths) == 1
    assert next(iter(dispatcher_worktree_paths)).startswith(str(tmp_path / "mac/wt-a"))

    # The per-worktree producers expand under container + automation roots too.
    dispatcher_container = [
        r
        for r in universe
        if r.producer == "dispatcher_store" and r.root_kind == RootKind.CONTAINER_MOUNT
    ]
    dispatcher_automation = [
        r for r in universe if r.producer == "dispatcher_store" and r.root_kind == RootKind.AUTOMATION
    ]
    assert dispatcher_container and dispatcher_automation

    # The file-first inquiry store is vault-scoped only.
    inquiry_roots = [r for r in universe if r.producer == "model_inquiry"]
    assert inquiry_roots and all(r.root_kind == RootKind.VAULT for r in inquiry_roots)

    # Producer default-path rule and authority flag are honored in the projection.
    spec = producer("builderops_store")
    assert any(root.path.endswith(spec.relative_default_path) for root in universe)
    for root in universe:
        assert root.authority_bearing == producer(root.producer).authority_bearing

    # The derived universe is probe-complete: freezing it observes every root as
    # present and usable (nothing expected that the producers never write).
    freshness = fx.iso_now()
    manifest = build_coverage_manifest(
        universe,
        probe=fx.make_probe(freshness_at=freshness),
        host="macbook",
        user=fx.OPERATOR,
        freshness_at=freshness,
    )
    assert not manifest.is_blocking


def test_env_overrides_pin_producers_and_record_consulted_keys(tmp_path: Path) -> None:
    """A host env snapshot pins env-overridden producers to their real resolver
    target (one expected root per host, kind producer_default, repo unknown) and
    records the consulted keys; an env-less host records env_known=False."""

    state_dir = tmp_path / "ops/dispatcher-state"
    fx.write_dispatcher_sqlite(state_dir / "dispatcher.sqlite3")
    fx.write_dispatcher_events_jsonl(state_dir / "events.jsonl")
    worktree = tmp_path / "wt"
    fx.write_state_producers(worktree, dispatcher=False)

    hosts = (
        HostContext(
            host="macbook",
            user=fx.OPERATOR,
            roots=(EnumeratedRoot(RootKind.GIT_WORKTREE, str(worktree), repo_identity=fx.REPO),),
            env={"DISPATCHER_STATE_DIR": str(state_dir)},
        ),
    )
    universe = derive_expected_universe(hosts)

    dispatcher_roots = [r for r in universe if r.producer == "dispatcher_store"]
    events_roots = [r for r in universe if r.producer == "dispatcher_events"]
    assert len(dispatcher_roots) == 1 and len(events_roots) == 1
    assert dispatcher_roots[0].path == str(state_dir / "dispatcher.sqlite3")
    assert events_roots[0].path == str(state_dir / "events.jsonl")
    assert dispatcher_roots[0].root_kind == RootKind.PRODUCER_DEFAULT
    # Consulted env keys are recorded; env-resolved roots have no worktree
    # binding, so repo provenance must come from row evidence, never the root.
    assert "DISPATCHER_STATE_DIR" in dispatcher_roots[0].env_keys_consulted
    assert dispatcher_roots[0].env_known is True
    assert dispatcher_roots[0].repo_identity is None

    # Non-overridden producers still derive per-root defaults.
    assert any(r.producer == "builderops_store" for r in universe)

    # The env-pinned universe freezes clean (the env target is where data IS).
    freshness = fx.iso_now()
    manifest = build_coverage_manifest(
        universe,
        probe=fx.make_probe(freshness_at=freshness),
        host="macbook",
        user=fx.OPERATOR,
        freshness_at=freshness,
    )
    assert not manifest.is_blocking
    entry_by_key = {e["key"]: e for s in manifest.sources for e in [s.as_manifest_entry()]}
    assert entry_by_key[dispatcher_roots[0].key]["env_keys_consulted"] == [
        "DISPATCHER_STATE_DIR"
    ]

    # An env-less host derives defaults only and is marked env_known=False.
    remote_wt = tmp_path / "remote-wt"
    fx.write_state_producers(remote_wt)
    remote = HostContext(
        host=fx.HOST_REMOTE,
        user=fx.OPERATOR,
        roots=(EnumeratedRoot(RootKind.GIT_WORKTREE, str(remote_wt), repo_identity=fx.REPO),),
        env=None,
    )
    remote_universe = derive_expected_universe((remote,))
    assert remote_universe and all(r.env_known is False for r in remote_universe)


def test_dispatcher_sibling_env_key_poisons_state_dir_default(tmp_path: Path) -> None:
    """G1: app/dispatcher/config.py::_default_state_dir poisons state_dir's OWN
    fallback (from primary-worktree-relative to the BARE CWD-relative default)
    whenever ANY of DISPATCHER_STATE_DIR/DISPATCHER_DB_PATH/DISPATCHER_EVENTS_PATH
    is present -- even a SIBLING key unrelated to the field being resolved.
    Setting only DISPATCHER_EVENTS_PATH must still move dispatcher_store's
    resolution off the clone-set primary onto per-root (CWD-relative)
    derivation, and vice versa for dispatcher_events with only
    DISPATCHER_DB_PATH set. Cross-checked empirically against the real
    app.dispatcher.config.load_paths resolver, the same way the review found
    the bug: side-by-side against derive_expected_universe's output.
    """

    from app.dispatcher.config import load_paths as real_load_paths

    primary = tmp_path / "clone-a" / "wt-primary"
    linked = tmp_path / "clone-a" / "wt-linked"
    fx.write_state_producers(primary)
    fx.write_state_producers(linked, dispatcher=False)

    def _hosts_for(env: dict[str, str]) -> tuple[HostContext, ...]:
        return (
            HostContext(
                host="macbook",
                user=fx.OPERATOR,
                roots=(
                    EnumeratedRoot(RootKind.GIT_WORKTREE, str(primary), repo_identity=fx.REPO),
                    EnumeratedRoot(
                        RootKind.GIT_WORKTREE,
                        str(linked),
                        repo_identity=fx.REPO,
                        primary_worktree=str(primary),
                    ),
                ),
                env=env,
            ),
        )

    # --- Scenario A: only DISPATCHER_EVENTS_PATH set. ----------------------
    events_override = tmp_path / "custom-events" / "events.jsonl"
    env_a = {"DISPATCHER_EVENTS_PATH": str(events_override)}

    # Sanity: confirm the REAL resolver is actually poisoned for this env
    # (db_path stays a bare relative path, never touching cwd/primary at all).
    real_a = real_load_paths(env=dict(env_a), cwd=primary)
    assert not real_a.db_path.is_absolute()
    assert real_a.events_path == events_override

    universe_a = derive_expected_universe(_hosts_for(env_a))

    # dispatcher_events: its OWN key is set -> one absolute override, unaffected
    # by poisoning (own key always wins).
    events_roots = [r for r in universe_a if r.producer == "dispatcher_events"]
    assert len(events_roots) == 1
    assert events_roots[0].path == str(events_override)
    assert events_roots[0].root_kind == RootKind.PRODUCER_DEFAULT

    # dispatcher_store: neither its own key nor DISPATCHER_STATE_DIR is set, but
    # the sibling DISPATCHER_EVENTS_PATH poisons state_dir -> per-root
    # (CWD-relative) resolution, NOT collapsed onto the clone-set primary. Two
    # enumerated worktrees now produce TWO expected dispatcher_store roots.
    dispatcher_roots = {r.path: r for r in universe_a if r.producer == "dispatcher_store"}
    assert len(dispatcher_roots) == 2
    for worktree in (primary, linked):
        real = real_load_paths(env=dict(env_a), cwd=worktree)
        expected_path = str(worktree / real.db_path)
        assert expected_path in dispatcher_roots
        root = dispatcher_roots[expected_path]
        assert root.root_kind == RootKind.GIT_WORKTREE
        assert "DISPATCHER_EVENTS_PATH" in root.env_keys_consulted
        assert root.env_known is True

    # --- Scenario B: only DISPATCHER_DB_PATH set (symmetric direction). ----
    db_override = tmp_path / "custom-db" / "dispatcher.sqlite3"
    env_b = {"DISPATCHER_DB_PATH": str(db_override)}

    real_b = real_load_paths(env=dict(env_b), cwd=primary)
    assert not real_b.events_path.is_absolute()
    assert real_b.db_path == db_override

    universe_b = derive_expected_universe(_hosts_for(env_b))

    dispatcher_roots_b = [r for r in universe_b if r.producer == "dispatcher_store"]
    assert len(dispatcher_roots_b) == 1
    assert dispatcher_roots_b[0].path == str(db_override)
    assert dispatcher_roots_b[0].root_kind == RootKind.PRODUCER_DEFAULT

    events_roots_b = {r.path: r for r in universe_b if r.producer == "dispatcher_events"}
    assert len(events_roots_b) == 2
    for worktree in (primary, linked):
        real = real_load_paths(env=dict(env_b), cwd=worktree)
        expected_path = str(worktree / real.events_path)
        assert expected_path in events_roots_b
        assert events_roots_b[expected_path].root_kind == RootKind.GIT_WORKTREE
        assert "DISPATCHER_DB_PATH" in events_roots_b[expected_path].env_keys_consulted


def test_producer_authority_flag_is_load_bearing_for_readers(tmp_path: Path) -> None:
    """Flipping the producer authority flag flows through to every record the
    reader emits (F10): table refinements may only narrow, never exceed it."""

    db = tmp_path / "runtime/builderops/builderops.sqlite3"
    fx.write_builderops_sqlite(db)
    base = fx.ExpectedRoot(
        producer="builderops_store",
        source_class="builderops_sqlite",
        host="macbook",
        user=fx.OPERATOR,
        root_kind=RootKind.GIT_WORKTREE,
        path=str(db),
        authority_bearing=True,
        repo_identity=fx.REPO,
    )
    probe = fx.make_probe(freshness_at=fx.iso_now())

    with_authority = read_builderops_sqlite(probe(base))
    assert any(r.authority_bearing for r in with_authority)
    # Table refinement still narrows inside an authority-bearing producer.
    assert all(
        not r.authority_bearing for r in with_authority if r.object_kind == "builderops_meta"
    )

    flipped = dataclasses.replace(base, authority_bearing=False)
    without_authority = read_builderops_sqlite(probe(flipped))
    assert without_authority
    assert all(not r.authority_bearing for r in without_authority)


def test_caller_roots_can_add_but_cannot_subtract_coverage(tmp_path: Path) -> None:
    hosts = _two_host_universe(tmp_path)
    baseline = derive_expected_universe(hosts)

    # An extra caller-supplied host-stable candidate is ADDED.
    extra_path = str(tmp_path / f"{fx.HOST_REMOTE}/host-stable/runtime/builderops/builderops.sqlite3")
    fx.write_builderops_sqlite(Path(extra_path))
    extra = fx.ExpectedRoot(
        producer="builderops_store",
        source_class="builderops_sqlite",
        host=fx.HOST_REMOTE,
        user=fx.OPERATOR,
        root_kind=RootKind.HOST_STABLE,
        path=extra_path,
        authority_bearing=True,
        repo_identity=fx.REPO,
    )
    widened = derive_expected_universe(hosts, caller_roots=(extra,))
    assert len(widened) == len(baseline) + 1
    # Every producer-derived root survives — caller input never removes coverage.
    assert {r.key for r in baseline}.issubset({r.key for r in widened})

    # A caller root that reuses a producer-derived key but changes its identity
    # (an attempt to redefine/subtract coverage) fails closed.
    victim = next(r for r in baseline if r.producer == "dispatcher_store")
    tampered = dataclasses.replace(victim, authority_bearing=False)
    with pytest.raises(InventoryCoverageError):
        derive_expected_universe(hosts, caller_roots=(tampered,))


def test_omitted_or_inaccessible_expected_root_blocks_acknowledgement(tmp_path: Path) -> None:
    hosts = _two_host_universe(tmp_path)
    universe = derive_expected_universe(hosts)
    freshness = fx.iso_now()

    # Case A: a real expected source is deleted before freeze -> missing -> block.
    missing_root = next(r for r in universe if r.producer == "epic_run_state")
    shutil.rmtree(missing_root.path)
    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        universe, probe=probe, host="macbook", user=fx.OPERATOR, freshness_at=freshness
    )
    assert manifest.is_blocking
    assert missing_root.key in manifest.blocking_roots
    ack = InventoryAcknowledgement(
        host="macbook",
        user=fx.OPERATOR,
        manifest_hash=manifest.manifest_hash,
        acknowledged_at=freshness,
        freshness_horizon_seconds=3600,
    )
    with pytest.raises(AcknowledgementRejected, match="missing or inaccessible"):
        accept_acknowledgement(manifest, ack)

    # Case B: an expected source that exists but is inaccessible also blocks.
    hosts2 = _two_host_universe(tmp_path / "b")
    universe2 = derive_expected_universe(hosts2)
    locked = next(r for r in universe2 if r.producer == "dispatcher_store")
    probe2 = fx.make_probe(freshness_at=freshness, inaccessible=frozenset({locked.path}))
    manifest2 = build_coverage_manifest(
        universe2, probe=probe2, host="macbook", user=fx.OPERATOR, freshness_at=freshness
    )
    assert locked.key in manifest2.blocking_roots
    ack2 = InventoryAcknowledgement(
        host="macbook",
        user=fx.OPERATOR,
        manifest_hash=manifest2.manifest_hash,
        acknowledged_at=freshness,
        freshness_horizon_seconds=3600,
    )
    with pytest.raises(AcknowledgementRejected):
        accept_acknowledgement(manifest2, ack2)


def test_acknowledgement_binds_host_user_freshness_and_manifest_hash(tmp_path: Path) -> None:
    hosts = _two_host_universe(tmp_path)
    universe = derive_expected_universe(hosts)
    freshness = fx.iso_now()
    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        universe, probe=probe, host=fx.HOST_REMOTE, user=fx.OPERATOR, freshness_at=freshness
    )
    assert not manifest.is_blocking

    good = InventoryAcknowledgement(
        host=fx.HOST_REMOTE,
        user=fx.OPERATOR,
        manifest_hash=manifest.manifest_hash,
        acknowledged_at=freshness,
        freshness_horizon_seconds=3600,
    )
    accept_acknowledgement(manifest, good)  # binds cleanly

    # The freeze timestamp is bound into the manifest hash (F8): the same file
    # set frozen at a different time is a DIFFERENT acknowledged identity.
    refrozen = build_coverage_manifest(
        universe,
        probe=probe,
        host=fx.HOST_REMOTE,
        user=fx.OPERATOR,
        freshness_at=fx._iso(fx.now().replace(hour=13)),
    )
    assert refrozen.manifest_hash != manifest.manifest_hash

    # Foreign host / user.
    with pytest.raises(AcknowledgementRejected, match="host/user"):
        accept_acknowledgement(
            manifest,
            InventoryAcknowledgement(
                host="attacker-host",
                user=fx.OPERATOR,
                manifest_hash=manifest.manifest_hash,
                acknowledged_at=freshness,
                freshness_horizon_seconds=3600,
            ),
        )

    # Wrong manifest hash (foreign/stale inventory).
    with pytest.raises(AcknowledgementRejected, match="manifest hash"):
        accept_acknowledgement(
            manifest,
            InventoryAcknowledgement(
                host=fx.HOST_REMOTE,
                user=fx.OPERATOR,
                manifest_hash="deadbeef",
                acknowledged_at=freshness,
                freshness_horizon_seconds=3600,
            ),
        )

    # Stale acknowledgement (outside the freshness horizon).
    stale = fx._iso(fx.now().replace(hour=23))
    with pytest.raises(AcknowledgementRejected, match="stale"):
        accept_acknowledgement(
            manifest,
            InventoryAcknowledgement(
                host=fx.HOST_REMOTE,
                user=fx.OPERATOR,
                manifest_hash=manifest.manifest_hash,
                acknowledged_at=stale,
                freshness_horizon_seconds=60,
            ),
        )
