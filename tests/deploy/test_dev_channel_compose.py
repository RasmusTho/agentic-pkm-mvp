"""Merged dev-compose regression contract for Issue #3659."""
from __future__ import annotations

from pathlib import Path

from app.release_channels.channel_isolation_preflight import _load_compose


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
DEV_DSN = "postgresql+psycopg://app:app@db:5432/app_dev"


def _merged_service_environment(service: str) -> dict[str, str]:
    """Model Compose's mapping merge for one service environment block."""
    base_service = _load_compose(BASE_COMPOSE)["services"][service]
    dev_service = _load_compose(DEV_COMPOSE)["services"][service]

    def environment_mapping(service_config: dict) -> dict[str, str]:
        environment = service_config.get("environment") or {}
        if isinstance(environment, dict):
            return environment
        return dict(item.split("=", 1) for item in environment)

    return {
        **environment_mapping(base_service),
        **environment_mapping(dev_service),
    }


def test_dev_migrate_uses_app_dev_dsn() -> None:
    """The one-shot migration gate must target the same DB as dev services."""
    migrate_environment = _merged_service_environment("migrate")

    assert migrate_environment["DATABASE_URL"] == DEV_DSN
    assert migrate_environment["DB_DSN"] == DEV_DSN
    assert "/app_dev" in migrate_environment["DATABASE_URL"]
    assert "/app_dev" in migrate_environment["DB_DSN"]


def test_dev_runtime_services_forward_deploy_vault_bindings() -> None:
    """Vault selection is deploy configuration, never a product-code path."""
    expected = {
        "VAULT_ROOT": "${VAULT_ROOT:-}",
        "VAULT_ROOT_DEV": "${VAULT_ROOT_DEV:-}",
    }

    for service in ("api", "worker", "watcher"):
        environment = _merged_service_environment(service)
        assert {key: environment.get(key) for key in expected} == expected
