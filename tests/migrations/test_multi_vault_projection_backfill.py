from __future__ import annotations

from pathlib import Path

import pytest

from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.mvr05_cutover import (
    discover_db_producer_fence,
    record_mvr05_runtime_floor,
)
from app.instance.runtime import _require_runtime_floor
from app.instance.vault_registry import VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.not_pg


def test_projection_upgrade_blocks_scalar_rollback_before_first_write(tmp_path) -> None:
    store = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    floor = record_mvr05_runtime_floor(
        store,
        fence=discover_db_producer_fence(REPO_ROOT / "docker-compose.yaml"),
        channel_id="dev",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert floor.extensions["runtimeFloors"]["minimumRuntimeSchema"] == "mvr-05"
    with pytest.raises(CapabilityNotReadyError, match="blocks scalar"):
        _require_runtime_floor(floor, scalar_runtime=True)
