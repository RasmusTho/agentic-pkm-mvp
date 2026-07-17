"""YSS-01 (#3916): source registry service-layer contract, memory backend.

Covers the issue's six behavioral Acceptance Criteria against the in-process
memory backend (never selected in a configured runtime -- tests only, per
`ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md :: Restart / Durability Posture`).
The same assertions run against the real Postgres backend in
`tests/knowledge_acquisition/test_source_registry_pg.py::test_pg_backend_contract`
via the shared helper module `_source_registry_contract.py`, so both backends
are proven to honor the identical service-layer contract (AC8).

All collection_ref/account_binding_id values below are synthetic fixture ids
(`PLfixture...`, `UCfixture...`, `acct-<uuid4>`) -- never a real personal
playlist/channel/account identifier (INV-YSS-9).
"""

from __future__ import annotations

import pytest

from app.knowledge_acquisition.source_registry import SourceRegistry, reset_memory_source_registry
from tests.knowledge_acquisition._source_registry_contract import (
    assert_duplicate_binding_refused,
    assert_invalid_interval_and_policy_fail_loud,
    assert_memory_json_isolation,
    assert_round_trip_and_contract_fields,
    assert_single_enabled_inbox_and_swap,
    assert_title_rename_preserves_binding,
    assert_watch_later_and_history_refused,
)

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _memory_registry(monkeypatch: pytest.MonkeyPatch):
    # tests/conftest.py::force_memory_store_for_non_pg already forces
    # STORE_BACKEND=memory for every not_pg test; set it explicitly here too
    # so this file's backend selection is self-evident on its own.
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_source_registry()
    yield
    reset_memory_source_registry()


def _make_registry() -> SourceRegistry:
    return SourceRegistry.for_runtime()


def test_registry_round_trip_memory_and_contract_fields() -> None:
    assert_round_trip_and_contract_fields(_make_registry)


def test_single_enabled_inbox_enforced_and_swap_atomic() -> None:
    assert_single_enabled_inbox_and_swap(_make_registry)


def test_duplicate_binding_refused() -> None:
    assert_duplicate_binding_refused(_make_registry)


def test_watch_later_and_history_refused_unsupported() -> None:
    assert_watch_later_and_history_refused(_make_registry)


def test_title_rename_does_not_break_binding() -> None:
    assert_title_rename_preserves_binding(_make_registry)


def test_invalid_interval_and_policy_fail_loud() -> None:
    assert_invalid_interval_and_policy_fail_loud(_make_registry)


def test_memory_json_isolation_matches_postgres_contract() -> None:
    assert_memory_json_isolation(_make_registry)
