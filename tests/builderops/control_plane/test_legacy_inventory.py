"""BCP-03 AC1: producer-derived inventory across the cutover-host universe.

These tests run without Postgres (`not pg`): the migration inventory layer is
pure/deterministic and operates on real on-disk fixture sources.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.control_plane.legacy_migration import (
    AcknowledgementRejected,
    EnumeratedRoot,
    ExpectedRoot,
    HostContext,
    InventoryAcknowledgement,
    InventoryCoverageError,
    RootKind,
    accept_acknowledgement,
    build_coverage_manifest,
    derive_expected_universe,
    producer,
)

from tests.builderops.control_plane import _legacy_fixtures as fx


def _two_host_universe(tmp_path: Path) -> tuple[HostContext, ...]:
    """MacBook (two worktrees) plus Demerzel (container + automation + vault),
    with real sources under every enumerated root."""

    mac_a = tmp_path / "mac/wt-a"
    mac_b = tmp_path / "mac/wt-b"
    demerzel_container = tmp_path / "demerzel/mount"
    demerzel_automation = tmp_path / "demerzel/launchd-state"
    demerzel_vault = tmp_path / "demerzel/vault"

    for root in (mac_a, mac_b, demerzel_container, demerzel_automation):
        fx.write_state_producers(root)
    fx.write_vault(demerzel_vault)

    return (
        HostContext(
            host="macbook",
            user="rasmus",
            roots=(
                EnumeratedRoot(RootKind.GIT_WORKTREE, str(mac_a), repo_identity=fx.REPO),
                EnumeratedRoot(RootKind.GIT_WORKTREE, str(mac_b), repo_identity=fx.REPO),
            ),
        ),
        HostContext(
            host="demerzel",
            user="rasmus",
            roots=(
                EnumeratedRoot(RootKind.CONTAINER_MOUNT, str(demerzel_container), repo_identity=fx.REPO),
                EnumeratedRoot(RootKind.AUTOMATION, str(demerzel_automation), repo_identity=fx.REPO),
                EnumeratedRoot(RootKind.VAULT, str(demerzel_vault), repo_identity=fx.REPO),
            ),
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
    assert {root.host for root in universe} == {"macbook", "demerzel"}

    # Both MacBook worktrees are enumerated (the #3686 fragmentation case): the
    # per-worktree builderops store appears once per worktree.
    builderops_worktrees = {
        root.path
        for root in universe
        if root.producer == "builderops_store" and root.root_kind == RootKind.GIT_WORKTREE
    }
    assert len(builderops_worktrees) == 2

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

    # Producer default-path rule is honored.
    spec = producer("builderops_store")
    assert any(root.path.endswith(spec.relative_default_path) for root in universe)


def test_caller_roots_can_add_but_cannot_subtract_coverage(tmp_path: Path) -> None:
    hosts = _two_host_universe(tmp_path)
    baseline = derive_expected_universe(hosts)

    # An extra caller-supplied host-stable candidate is ADDED.
    extra_path = str(tmp_path / "demerzel/host-stable/runtime/builderops/builderops.sqlite3")
    fx.write_builderops_sqlite(Path(extra_path))
    extra = ExpectedRoot(
        producer="builderops_store",
        source_class="builderops_sqlite",
        host="demerzel",
        user="rasmus",
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
    tampered = ExpectedRoot(
        producer=victim.producer,
        source_class=victim.source_class,
        host=victim.host,
        user=victim.user,
        root_kind=victim.root_kind,
        path=victim.path,
        authority_bearing=False,  # flips authority off => subtraction attempt
        repo_identity=victim.repo_identity,
    )
    with pytest.raises(InventoryCoverageError):
        derive_expected_universe(hosts, caller_roots=(tampered,))


def test_omitted_or_inaccessible_expected_root_blocks_acknowledgement(tmp_path: Path) -> None:
    hosts = _two_host_universe(tmp_path)
    universe = derive_expected_universe(hosts)
    freshness = fx._iso(fx.now())

    # Case A: a real expected source is deleted before freeze -> missing -> block.
    missing_root = next(r for r in universe if r.producer == "epic_run_state")
    import shutil

    shutil.rmtree(missing_root.path)
    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        universe, probe=probe, host="macbook", user="rasmus", freshness_at=freshness
    )
    assert manifest.is_blocking
    assert missing_root.key in manifest.blocking_roots
    ack = InventoryAcknowledgement(
        host="macbook",
        user="rasmus",
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
        universe2, probe=probe2, host="macbook", user="rasmus", freshness_at=freshness
    )
    assert locked.key in manifest2.blocking_roots
    ack2 = InventoryAcknowledgement(
        host="macbook",
        user="rasmus",
        manifest_hash=manifest2.manifest_hash,
        acknowledged_at=freshness,
        freshness_horizon_seconds=3600,
    )
    with pytest.raises(AcknowledgementRejected):
        accept_acknowledgement(manifest2, ack2)


def test_acknowledgement_binds_host_user_freshness_and_manifest_hash(tmp_path: Path) -> None:
    hosts = _two_host_universe(tmp_path)
    universe = derive_expected_universe(hosts)
    freshness = fx._iso(fx.now())
    probe = fx.make_probe(freshness_at=freshness)
    manifest = build_coverage_manifest(
        universe, probe=probe, host="demerzel", user="rasmus", freshness_at=freshness
    )
    assert not manifest.is_blocking

    good = InventoryAcknowledgement(
        host="demerzel",
        user="rasmus",
        manifest_hash=manifest.manifest_hash,
        acknowledged_at=freshness,
        freshness_horizon_seconds=3600,
    )
    accept_acknowledgement(manifest, good)  # binds cleanly

    # Foreign host / user.
    with pytest.raises(AcknowledgementRejected, match="host/user"):
        accept_acknowledgement(
            manifest,
            InventoryAcknowledgement(
                host="attacker-host",
                user="rasmus",
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
                host="demerzel",
                user="rasmus",
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
                host="demerzel",
                user="rasmus",
                manifest_hash=manifest.manifest_hash,
                acknowledged_at=stale,
                freshness_horizon_seconds=60,
            ),
        )
