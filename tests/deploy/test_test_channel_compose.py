from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
TEST_COMPOSE = REPO_ROOT / "docker-compose.test.yml"
EXPLICIT_VAULT_COMPOSE = REPO_ROOT / "docker-compose.legacy-vault.yml"
TEST_VAULT_COMPOSE = REPO_ROOT / "docker-compose.test-vault.yml"
TEST_ENV = REPO_ROOT / "config/deploy/test.env"


def _merged_compose(
    runtime_env: Path,
    *,
    explicit_vault: Path | None = None,
) -> dict[str, object]:
    env = os.environ.copy()
    for key in (
        "COMPOSE_FILE",
        "LLM_PROVIDER",
        "TEST_VAULT_ROOT",
        "VAULT_HOST_ROOT",
        "VAULT_ROOT",
        "VAULT_ROOT_TEST",
    ):
        env.pop(key, None)
    env["WATCHER_ENABLE"] = "1" if explicit_vault is None else "0"
    env["WATCHER_VAULT_PATH"] = "/hostile-inherited-vault"
    env["WATCHER_RUNTIME_ENV_FILE"] = str(runtime_env)

    command = [
        "docker",
        "compose",
        "--env-file",
        str(TEST_ENV),
        "-f",
        str(BASE_COMPOSE),
        "-f",
        str(TEST_COMPOSE),
    ]
    if explicit_vault is not None:
        env["VAULT_HOST_ROOT"] = str(explicit_vault)
        command.extend(
            [
                "-f",
                str(EXPLICIT_VAULT_COMPOSE),
                "-f",
                str(TEST_VAULT_COMPOSE),
            ]
        )
    command.extend(["-p", "pkm-test-contract", "config", "--format", "json"])

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _services(compose: dict[str, object]) -> dict[str, dict[str, object]]:
    services = compose["services"]
    assert isinstance(services, dict)
    return services  # type: ignore[return-value]


def _environment(service: dict[str, object]) -> dict[str, str]:
    environment = service["environment"]
    assert isinstance(environment, dict)
    return {str(key): str(value) for key, value in environment.items()}


def _mount_targets(service: dict[str, object]) -> set[str]:
    volumes = service.get("volumes", [])
    assert isinstance(volumes, list)
    return {
        str(volume["target"])
        for volume in volumes
        if isinstance(volume, dict) and "target" in volume
    }


def _mount_source(service: dict[str, object], target: str) -> str | None:
    volumes = service.get("volumes", [])
    assert isinstance(volumes, list)
    for volume in volumes:
        if isinstance(volume, dict) and volume.get("target") == target:
            source = volume.get("source")
            return str(source) if source is not None else None
    return None


def test_test_migrate_uses_app_test_dsn(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")
    services = _services(_merged_compose(runtime_env))
    migrate = _environment(services["migrate"])

    assert migrate["DATABASE_URL"] == "postgresql+psycopg://app:app@db:5432/app_test"
    assert migrate["DB_DSN"] == "postgresql+psycopg://app:app@db:5432/app_test"
    assert migrate["LLM_PROVIDER"] == "mock"


def test_test_runtime_services_idle_without_vault_binding(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")
    services = _services(_merged_compose(runtime_env))

    for service in ("api", "worker", "watcher"):
        runtime_env = _environment(services[service])

        assert runtime_env["LLM_PROVIDER"] == "mock"
        assert "VAULT_ROOT" not in runtime_env
        assert "VAULT_ROOT_TEST" not in runtime_env
        assert runtime_env["WATCHER_ENABLE"] == "0"
        assert runtime_env["WATCHER_VAULT_PATH"] == ""
        assert "/app/vault" not in _mount_targets(services[service])

    assert _environment(services["heimdal-capture-watch"])["LLM_PROVIDER"] == "mock"


def test_test_runtime_services_have_mock_provider_and_vault_binding(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")
    selected_vault = tmp_path / "selected-test-vault"
    selected_vault.mkdir()
    services = _services(_merged_compose(runtime_env, explicit_vault=selected_vault))

    for service in ("api", "worker", "watcher"):
        service_env = _environment(services[service])

        assert service_env["LLM_PROVIDER"] == "mock"
        assert service_env["VAULT_ROOT"] == "/app/vault"
        assert service_env["VAULT_ROOT_TEST"] == "/app/vault"
        assert service_env["WATCHER_ENABLE"] == "1"
        assert service_env["WATCHER_VAULT_PATH"] == "/app/vault"
        assert "/app/vault" in _mount_targets(services[service])
        assert _mount_source(services[service], "/app/vault") == str(selected_vault)

    assert _environment(services["migrate"])["LLM_PROVIDER"] == "mock"
    assert _environment(services["heimdal-capture-watch"])["LLM_PROVIDER"] == "mock"
