from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.instance.mvr05_cutover import (
    Mvr05CutoverError,
    discover_db_producer_fence,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.not_pg


def test_all_old_scalar_db_clients_are_stopped_before_binding_keyed_migration() -> None:
    plan = discover_db_producer_fence(REPO_ROOT / "docker-compose.yaml")
    deployment = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text()
    floor_marker = "python -m app.instance.runtime mvr05-record-floor"
    migration = (REPO_ROOT / "scripts/deploy_channel.sh").read_text()

    assert plan.migration_runner == "migrate"
    assert set(plan.stopped_services) == {
        "api",
        "worker",
        "watcher",
        "heimdal-capture-watch",
    }
    assert 'compose-fence-plan' in deployment
    assert 'stop "${mvr05_stop_service_args[@]}"' in deployment
    assert deployment.index(floor_marker) < deployment.rindex("deployment-finish")
    assert migration.rindex("prepare_instance_state_deployment") < migration.rindex(
        "apply_changed_migrations"
    )


def test_fence_inventory_covers_every_enabled_db_outbox_process(tmp_path) -> None:
    compose_path = REPO_ROOT / "docker-compose.yaml"
    plan = discover_db_producer_fence(compose_path)
    compose = yaml.safe_load(compose_path.read_text())
    discovered = {
        name
        for name, service in compose["services"].items()
        if "db" in (service.get("depends_on") or {})
    }
    assert set(plan.db_clients) == discovered
    assert set(plan.stopped_services) | {plan.migration_runner} == discovered
    for service_name in plan.stopped_services:
        environment = compose["services"][service_name].get("environment") or {}
        if isinstance(environment, list):
            environment = {
                str(item).split("=", 1)[0]: str(item).split("=", 1)[-1]
                for item in environment
            }
        assert "INSTANCE_VAULT_REGISTRY_PATH" in environment, service_name
        assert "INSTANCE_OWNERSHIP_ROOT" in environment, service_name

    changed = yaml.safe_load(compose_path.read_text())
    changed["services"]["unfenced-writer"] = {
        "command": ["python", "-m", "app.some_writer"],
        "depends_on": {"db": {"condition": "service_healthy"}},
    }
    changed_path = tmp_path / "docker-compose.yaml"
    changed_path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(Mvr05CutoverError, match="lacks one valid"):
        discover_db_producer_fence(changed_path)

    changed["services"]["unfenced-writer"]["labels"] = {
        "com.agentic-pkm.mvr05.db-role": "client"
    }
    changed_path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    changed_plan = discover_db_producer_fence(changed_path)
    assert "unfenced-writer" in changed_plan.stopped_services

    del changed["services"]["migrate"]
    changed_path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(Mvr05CutoverError, match="exactly one migration runner"):
        discover_db_producer_fence(changed_path)
