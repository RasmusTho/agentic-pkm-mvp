from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.builderops.control_plane import (
    ExplicitSqliteAdapter,
    PostgresBuilderOpsStore,
    StorePort,
    production_store,
)


def test_production_store_fails_closed_without_postgres(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="BUILDEROPS_DATABASE_URL"):
        production_store({})
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        production_store({"BUILDEROPS_DATABASE_URL": str(tmp_path / "builderops.sqlite3")})

    store = production_store({"BUILDEROPS_DATABASE_URL": "postgresql://user:pass@db/builderops"})
    assert isinstance(store, PostgresBuilderOpsStore)
    assert not (tmp_path / "builderops.sqlite3").exists()
    adapter = ExplicitSqliteAdapter(tmp_path / "migration-source.sqlite3")
    assert adapter.path.name == "migration-source.sqlite3"


def test_store_port_exposes_complete_recovery_and_durability_surface() -> None:
    required_parameters = {
        "claim_lease": ("self", "envelope", "resource_id", "holder", "ttl_seconds"),
        "release_lease": ("self", "lease"),
        "commit_record": (
            "self",
            "envelope",
            "record_id",
            "record_type",
            "state",
            "payload",
            "idempotency_key",
            "lease",
            "expected_states",
            "fault_at",
        ),
        "commit_attempt": (
            "self",
            "envelope",
            "task_id",
            "attempt_id",
            "state",
            "payload",
            "idempotency_key",
            "lease",
            "expected_states",
            "fault_at",
        ),
        "commit_promotion": (
            "self",
            "envelope",
            "promotion_id",
            "status",
            "payload",
            "idempotency_key",
            "lease",
            "expected_states",
            "fault_at",
        ),
        "get_record": ("self", "repository", "record_id"),
        "get_attempt": ("self", "repository", "task_id", "attempt_id"),
        "get_promotion": ("self", "repository", "promotion_id"),
        "replay": ("self", "repository", "idempotency_key", "watermark"),
        "outbox_claim": ("self", "repository", "operation_key"),
        "mark_effect_unknown": ("self", "claim", "detail"),
        "outbox_status": ("self", "repository", "operation_key", "watermark"),
    }

    for method_name, parameters in required_parameters.items():
        method = StorePort.__dict__.get(method_name)
        assert method is not None, f"StorePort is missing {method_name}"
        assert tuple(inspect.signature(method).parameters) == parameters
        implementation = getattr(PostgresBuilderOpsStore, method_name)
        assert tuple(inspect.signature(implementation).parameters) == parameters

    store = PostgresBuilderOpsStore("postgresql://user:pass@db/builderops")
    assert isinstance(store, StorePort)
