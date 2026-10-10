from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.release_channels.channel_isolation_preflight import _load_compose


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
TEST_COMPOSE = REPO_ROOT / "docker-compose.test.yml"
EXPLICIT_VAULT_COMPOSE = REPO_ROOT / "docker-compose.legacy-vault.yml"
TEST_VAULT_COMPOSE = REPO_ROOT / "docker-compose.test-vault.yml"
TEST_ENV = REPO_ROOT / "config/deploy/test.env"
MODEL_ACCESS_ENV_FILE = "/etc/yggdrasil/model-access/runtime.env"
MODEL_ACCESS_HOST_IDENTITY = "/etc/yggdrasil/model-access/codex-client"
MODEL_ACCESS_CONTAINER_IDENTITY = "/run/model-access/codex-client"
MODEL_ACCESS_ENV_KEYS = (
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT",
    "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY",
)
pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker executable not found on PATH",
)


def _merged_compose(
    runtime_env: Path,
    *,
    explicit_vault: Path | None = None,
    llm_provider: str | None = None,
    model_access_bindings: dict[str, str] | None = None,
    project_name: str = "pkm-test-contract",
) -> dict[str, object]:
    env = os.environ.copy()
    for key in (
        "COMPOSE_FILE",
        "LLM_PROVIDER",
        "TEST_VAULT_ROOT",
        "VAULT_HOST_ROOT",
        "VAULT_ROOT",
        "VAULT_ROOT_TEST",
        *MODEL_ACCESS_ENV_KEYS,
    ):
        env.pop(key, None)
    env["WATCHER_ENABLE"] = "1" if explicit_vault is None else "0"
    env["WATCHER_VAULT_PATH"] = "/hostile-inherited-vault"
    env["WATCHER_RUNTIME_ENV_FILE"] = str(runtime_env)
    if llm_provider is not None:
        env["LLM_PROVIDER"] = llm_provider
    if model_access_bindings is not None:
        env.update(model_access_bindings)
    env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"] = str(
        runtime_env.parent / "instance-ownership"
    )

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
    command.extend(["-p", project_name, "config", "--format", "json"])

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


def test_model_access_bindings_are_optional_and_scoped_to_product_callers(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")
    services = _services(_merged_compose(runtime_env))
    overlay_services = _load_compose(TEST_COMPOSE)["services"]
    assert isinstance(overlay_services, dict)

    for name in ("api", "worker", "watcher"):
        service = services[name]
        overlay_service = overlay_services[name]
        overlay_environment = overlay_service.get("environment")
        assert isinstance(overlay_environment, dict)
        assert set(MODEL_ACCESS_ENV_KEYS).issubset(overlay_environment)
        for key in MODEL_ACCESS_ENV_KEYS:
            assert overlay_environment[key] == f"${{{key}:-}}"
        env_files = overlay_service.get("env_file", [])
        assert isinstance(env_files, list)
        assert not any(
            (entry.get("path") if isinstance(entry, dict) else entry)
            == MODEL_ACCESS_ENV_FILE
            for entry in env_files
        )
        mount_targets = _mount_targets(service)
        assert MODEL_ACCESS_CONTAINER_IDENTITY in mount_targets
        assert (
            _mount_source(service, MODEL_ACCESS_CONTAINER_IDENTITY)
            == MODEL_ACCESS_HOST_IDENTITY
        )
        mounts = service.get("volumes", [])
        assert isinstance(mounts, list)
        identity_mount = next(
            volume
            for volume in mounts
            if isinstance(volume, dict)
            and volume.get("target") == MODEL_ACCESS_CONTAINER_IDENTITY
        )
        assert identity_mount["read_only"] is True
        bind = identity_mount.get("bind")
        assert isinstance(bind, dict)
        assert bind["create_host_path"] is True

    for name, service in services.items():
        if name in {"api", "worker", "watcher"}:
            continue
        assert MODEL_ACCESS_CONTAINER_IDENTITY not in _mount_targets(service), name

    for name, service in overlay_services.items():
        if name in {"api", "worker", "watcher"}:
            continue
        environment = service.get("environment", {})
        assert isinstance(environment, dict)
        assert not set(MODEL_ACCESS_ENV_KEYS).intersection(environment), name
        env_files = service.get("env_file", [])
        assert isinstance(env_files, list)
        assert not any(
            (entry.get("path") if isinstance(entry, dict) else entry)
            == MODEL_ACCESS_ENV_FILE
            for entry in env_files
        ), name

    runtime_env.write_text("", encoding="utf-8")
    expected_bindings = {
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT": "https://192.0.2.25:8443",
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE": "/run/model-access/codex-client/ca.pem",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT": "/run/model-access/codex-client/client.pem",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY": "/run/model-access/codex-client/client.key",
    }
    configured_services = _services(
        _merged_compose(runtime_env, model_access_bindings=expected_bindings)
    )
    for name in ("api", "worker", "watcher"):
        configured_environment = _environment(configured_services[name])
        for key, value in expected_bindings.items():
            assert configured_environment[key] == value


def test_test_runtime_services_use_configured_provider_with_mock_default(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")

    default_services = _services(_merged_compose(runtime_env))
    configured_services = _services(
        _merged_compose(runtime_env, llm_provider="governed-provider")
    )

    for name in ("api", "worker", "watcher"):
        assert _environment(default_services[name])["LLM_PROVIDER"] == "mock"
        assert (
            _environment(configured_services[name])["LLM_PROVIDER"]
            == "governed-provider"
        )

    for name in ("instance-state-init", "migrate", "heimdal-capture-watch"):
        assert _environment(default_services[name])["LLM_PROVIDER"] == "mock"
        assert _environment(configured_services[name])["LLM_PROVIDER"] == "mock"


def test_test_product_callers_allow_task_policy_with_mock_default(
    tmp_path: Path,
) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")

    default_services = _services(_merged_compose(runtime_env))
    configured_services = _services(
        _merged_compose(runtime_env, llm_provider="governed-provider")
    )

    for name in ("api", "worker", "watcher"):
        default_environment = _environment(default_services[name])
        configured_environment = _environment(configured_services[name])
        assert default_environment["LLM_PROVIDER"] == "mock"
        assert default_environment["LLM_PROVIDER_ENFORCE"] == "0"
        assert configured_environment["LLM_PROVIDER"] == "governed-provider"
        assert configured_environment["LLM_PROVIDER_ENFORCE"] == "0"

    for name, service in default_services.items():
        if name in {"api", "worker", "watcher"}:
            continue
        assert _environment(service).get("LLM_PROVIDER_ENFORCE") != "0"


def test_test_migrate_uses_app_test_dsn(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")
    services = _services(_merged_compose(runtime_env))
    migrate = _environment(services["migrate"])

    assert migrate["DATABASE_URL"] == "postgresql+psycopg://app:app@db:5432/app_test"
    assert migrate["DB_DSN"] == "postgresql+psycopg://app:app@db:5432/app_test"
    assert migrate["LLM_PROVIDER"] == "mock"


def test_test_db_uses_named_channel_volume(tmp_path: Path) -> None:
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("", encoding="utf-8")
    compose = _merged_compose(runtime_env, project_name="pkm-test")
    services = _services(compose)
    volumes = compose["volumes"]
    assert isinstance(volumes, dict)

    assert _mount_source(services["db"], "/var/lib/postgresql/data") == "pgdata"
    assert volumes["pgdata"]["name"] == "pkm-test_pgdata"


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
