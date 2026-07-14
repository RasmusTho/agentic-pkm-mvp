from __future__ import annotations

import re
from pathlib import Path


COMPOSE_PATH = Path("docker-compose.test.yml")


def _service_block(service: str) -> str:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [\w-]+:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"service {service!r} is missing from {COMPOSE_PATH}"
    return match.group("body")


def test_test_migrate_uses_app_test_dsn() -> None:
    migrate = _service_block("migrate")

    assert "DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test" in migrate
    assert "DB_DSN: postgresql+psycopg://app:app@db:5432/app_test" in migrate


def test_test_runtime_services_have_mock_provider_and_vault_binding() -> None:
    for service in ("api", "worker", "watcher"):
        runtime_service = _service_block(service)

        assert "LLM_PROVIDER: mock" in runtime_service
        assert "VAULT_ROOT: /app/vault" in runtime_service
        assert "VAULT_ROOT_TEST: /app/vault" in runtime_service

    assert "LLM_PROVIDER: mock" in _service_block("migrate")
    assert "LLM_PROVIDER: mock" in _service_block("heimdal-capture-watch")
