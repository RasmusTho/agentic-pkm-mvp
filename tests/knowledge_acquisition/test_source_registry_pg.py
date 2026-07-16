"""YSS-01 Postgres backend + migration posture (#3916).

``test_pg_backend_contract`` (marked ``pg``) runs the same service-layer
contract as the memory suite against the real ``acquisition_source_registry``
table (``tests/conftest.py`` provides the DSN and the
``STORE_SCHEMA_AUTOCREATE`` test opt-in), and asserts the Alembic migration
is forward-only. The migration-posture assertions also run in the default
suite via ``test_migration_is_forward_only`` so a missing Postgres never
hides them.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.knowledge_acquisition.source_registry import SourceRegistry
from tests.knowledge_acquisition.test_source_registry import run_service_layer_contract

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "alembic"
    / "versions"
    / "a7f3c2e9d1b4_yss01_acquisition_source_registry.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("yss01_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.not_pg
def test_migration_is_forward_only() -> None:
    module = _load_migration_module()
    assert module.reversibility == "forward-only"
    assert module.down_revision == "e1d2c3b4a5f6"
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()


@pytest.mark.pg
def test_pg_backend_contract() -> None:
    # Migration posture: the table is created forward-only; downgrade raises.
    module = _load_migration_module()
    assert module.reversibility == "forward-only"
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()

    # The pg backend passes the same service-layer suite as the memory backend.
    registry = SourceRegistry.for_runtime()
    run_service_layer_contract(registry)
