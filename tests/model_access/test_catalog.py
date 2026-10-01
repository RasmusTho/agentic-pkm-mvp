from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
import time

import pytest

from app.model_access.catalog import (
    CATALOG_MAX_STALE_AGE,
    CATALOG_REFRESH_TTL,
    CatalogCache,
    CatalogError,
    CatalogModelDescriptor,
    CatalogSelectionPolicy,
    CatalogSnapshot,
    select_latest_compatible,
)
from app.model_access.catalog_discovery import codex_catalog_snapshot
from llm_contract import ModelCapabilities, ModelCapabilityRequirements


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _descriptor(
    model: str,
    *,
    release_at: datetime | None = None,
    replacement_model: str | None = None,
    deprecated: bool = False,
    structured_output: bool = True,
    efforts: tuple[str, ...] = ("low",),
) -> CatalogModelDescriptor:
    return CatalogModelDescriptor(
        provider="openai",
        model=model,
        transports=("codex_cli",),
        capabilities=ModelCapabilities(
            structured_output=structured_output,
            system_prompt_channel=True,
        ),
        reasoning_efforts=efforts,
        release_at=release_at,
        replacement_model=replacement_model,
        deprecated=deprecated,
    )


def _snapshot(*models: CatalogModelDescriptor, fetched_at: datetime = NOW) -> CatalogSnapshot:
    return CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=fetched_at,
        models=models,
    )


def _policy(*, accepted: tuple[str, ...] = ("gpt-luna", "gpt-nova")) -> CatalogSelectionPolicy:
    return CatalogSelectionPolicy(
        provider="openai",
        accepted_models=accepted,
        accepted_transports=("codex_cli",),
        required_capabilities=ModelCapabilityRequirements(structured_output=True),
        reasoning_effort="low",
        pinned_model="gpt-luna",
    )


def test_snapshot_hash_binds_complete_provider_descriptor() -> None:
    first = _snapshot(_descriptor("gpt-luna"))
    changed_capability = _snapshot(
        _descriptor("gpt-luna", structured_output=False)
    )
    changed_effort = _snapshot(_descriptor("gpt-luna", efforts=("high",)))

    assert first.snapshot_hash == first.compute_hash()
    assert first.snapshot_hash != changed_capability.snapshot_hash
    assert first.snapshot_hash != changed_effort.snapshot_hash
    payload = first.model_dump()
    payload["models"][0]["model"] = "gpt-forged"
    with pytest.raises(ValueError, match="hash"):
        CatalogSnapshot.model_validate(payload)


def test_refresh_ttl_and_max_stale_fail_closed() -> None:
    cache = CatalogCache()
    calls = 0

    def loader(now: datetime) -> CatalogSnapshot:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise CatalogError("catalog_unavailable")
        return _snapshot(
            _descriptor("gpt-luna", release_at=NOW - timedelta(days=3)),
            _descriptor("gpt-nova", release_at=NOW - timedelta(days=1)),
            fetched_at=now,
        )

    first = cache.get(
        provider="openai", transport_id="codex_cli", loader=loader, now=NOW
    )
    within_ttl = cache.get(
        provider="openai",
        transport_id="codex_cli",
        loader=loader,
        now=NOW + CATALOG_REFRESH_TTL,
    )
    stale = cache.get(
        provider="openai",
        transport_id="codex_cli",
        loader=loader,
        now=NOW + CATALOG_REFRESH_TTL + timedelta(seconds=1),
    )

    assert calls == 2
    assert first.snapshot_hash == within_ttl.snapshot_hash
    assert select_latest_compatible(first, _policy(), now=NOW).model == "gpt-nova"
    assert stale.freshness == "stale"
    assert stale.snapshot_hash != first.snapshot_hash
    pinned = select_latest_compatible(
        stale,
        _policy(),
        now=NOW + CATALOG_REFRESH_TTL + timedelta(seconds=1),
    )
    assert pinned.model == "gpt-luna"

    with pytest.raises(CatalogError, match="catalog_stale"):
        cache.get(
            provider="openai",
            transport_id="codex_cli",
            loader=loader,
            now=NOW + CATALOG_MAX_STALE_AGE + timedelta(seconds=1),
        )


def test_cold_refresh_accepts_snapshot_timestamped_during_discovery() -> None:
    cache = CatalogCache()

    def loader(refresh_started_at: datetime) -> CatalogSnapshot:
        snapshot = _snapshot(
            _descriptor("gpt-luna"),
            fetched_at=datetime.now(timezone.utc),
        )
        assert snapshot.fetched_at >= refresh_started_at
        return snapshot

    refreshed = cache.get(
        provider="openai", transport_id="codex_cli", loader=loader
    )

    assert refreshed.freshness == "fresh"
    assert refreshed.fetched_at <= datetime.now(timezone.utc)


def test_invalid_refresh_is_not_downgraded_to_a_stale_route() -> None:
    cache = CatalogCache()
    cache.get(
        provider="openai",
        transport_id="codex_cli",
        loader=lambda now: _snapshot(_descriptor("gpt-luna"), fetched_at=now),
        now=NOW,
    )

    def invalid_loader(_now: datetime) -> CatalogSnapshot:
        raise CatalogError("catalog_invalid")

    with pytest.raises(CatalogError, match="catalog_invalid"):
        cache.get(
            provider="openai",
            transport_id="codex_cli",
            loader=invalid_loader,
            now=NOW + CATALOG_REFRESH_TTL + timedelta(seconds=1),
        )


def test_catalog_cache_is_process_local_and_empty_after_reconstruction() -> None:
    snapshots = []

    def loader(now: datetime) -> CatalogSnapshot:
        snapshot = _snapshot(_descriptor("gpt-luna"), fetched_at=now)
        snapshots.append(snapshot)
        return snapshot

    first_process_cache = CatalogCache()
    first = first_process_cache.get(
        provider="openai", transport_id="codex_cli", loader=loader, now=NOW
    )
    reconstructed_process_cache = CatalogCache()
    second = reconstructed_process_cache.get(
        provider="openai", transport_id="codex_cli", loader=loader, now=NOW
    )

    assert len(snapshots) == 2
    assert first.snapshot_hash == second.snapshot_hash


def test_concurrent_cache_miss_publishes_one_immutable_snapshot() -> None:
    cache = CatalogCache()
    start = Barrier(8)
    calls = 0
    calls_lock = Lock()

    def loader(now: datetime) -> CatalogSnapshot:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.02)
        return _snapshot(_descriptor("gpt-luna"), fetched_at=now)

    def read_snapshot(_worker: int) -> CatalogSnapshot:
        start.wait(timeout=2)
        return cache.get(
            provider="openai",
            transport_id="codex_cli",
            loader=loader,
            now=NOW,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        snapshots = list(executor.map(read_snapshot, range(8)))

    assert calls == 1
    assert len({snapshot.snapshot_hash for snapshot in snapshots}) == 1


def test_latest_compatible_selection_uses_verified_release_metadata() -> None:
    snapshot = _snapshot(
        _descriptor("gpt-luna", release_at=NOW - timedelta(days=3)),
        _descriptor("gpt-nova", release_at=NOW - timedelta(days=1)),
        _descriptor(
            "gpt-deprecated",
            release_at=NOW,
            deprecated=True,
        ),
        _descriptor(
            "gpt-no-json",
            release_at=NOW - timedelta(minutes=30),
            structured_output=False,
        ),
    )

    target = select_latest_compatible(snapshot, _policy(), now=NOW)

    assert target.model == "gpt-nova"
    assert target.catalog_snapshot_hash == snapshot.snapshot_hash
    assert target.transport_id == "codex_cli"


def test_latest_compatible_selection_uses_explicit_replacement_edge() -> None:
    snapshot = _snapshot(
        _descriptor("gpt-luna", replacement_model="gpt-nova"),
        _descriptor("gpt-nova"),
    )

    assert select_latest_compatible(snapshot, _policy(), now=NOW).model == "gpt-nova"


def test_unordered_single_non_pinned_candidate_does_not_auto_promote() -> None:
    snapshot = _snapshot(_descriptor("gpt-nova"))

    with pytest.raises(CatalogError, match="catalog_unavailable"):
        select_latest_compatible(snapshot, _policy(), now=NOW)


def test_replacement_order_must_cover_every_candidate_without_cycles() -> None:
    snapshot = _snapshot(
        _descriptor("gpt-luna", replacement_model="gpt-nova"),
        _descriptor("gpt-nova", replacement_model="gpt-luna"),
        _descriptor("gpt-unrelated"),
    )
    policy = _policy(accepted=("gpt-luna", "gpt-nova", "gpt-unrelated"))

    assert select_latest_compatible(snapshot, policy, now=NOW).model == "gpt-luna"


def test_conflicting_release_and_replacement_evidence_keeps_pinned_model() -> None:
    snapshot = _snapshot(
        _descriptor(
            "gpt-luna",
            release_at=NOW - timedelta(days=3),
        ),
        _descriptor(
            "gpt-nova",
            release_at=NOW - timedelta(days=1),
            replacement_model="gpt-luna",
        ),
    )

    assert select_latest_compatible(snapshot, _policy(), now=NOW).model == "gpt-luna"


def test_two_requests_bind_distinct_catalog_versions() -> None:
    old_snapshot = _snapshot(
        _descriptor("gpt-luna", release_at=NOW - timedelta(days=1)),
        fetched_at=NOW,
    )
    new_snapshot = _snapshot(
        _descriptor("gpt-luna", release_at=NOW - timedelta(days=1)),
        _descriptor("gpt-nova", release_at=NOW),
        fetched_at=NOW + timedelta(seconds=1),
    )

    before = select_latest_compatible(old_snapshot, _policy(), now=NOW)
    after_not_accepted = select_latest_compatible(
        new_snapshot,
        _policy(accepted=("gpt-luna",)),
        now=NOW + timedelta(seconds=1),
    )
    after_accepted = select_latest_compatible(
        new_snapshot,
        _policy(),
        now=NOW + timedelta(seconds=1),
    )

    assert before.model == after_not_accepted.model == "gpt-luna"
    assert after_accepted.model == "gpt-nova"
    assert before.catalog_snapshot_hash != after_accepted.catalog_snapshot_hash


def test_codex_replacement_edge_promotes_independent_of_list_order() -> None:
    entries = [
        {
            "model": "gpt-nova",
            "structuredOutputSupported": True,
            "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
        },
        {
            "model": "gpt-luna",
            "structuredOutputSupported": True,
            "upgrade": "gpt-nova",
            "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
        },
    ]

    snapshot = codex_catalog_snapshot(entries, fetched_at=NOW)
    target = select_latest_compatible(snapshot, _policy(), now=NOW)

    assert target.model == "gpt-nova"
