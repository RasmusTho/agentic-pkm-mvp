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
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
MODEL_ACCESS_ENV_FILE = "/etc/yggdrasil/model-access/runtime.env"
MODEL_ACCESS_HOST_IDENTITY = "/etc/yggdrasil/model-access/codex-client"
MODEL_ACCESS_CONTAINER_IDENTITY = "/run/model-access/codex-client"
MODEL_ACCESS_ENV_KEYS = (
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT",
    "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY",
)
PRODUCT_CALLERS = ("api", "worker", "watcher")
pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker executable not found on PATH",
)


def _merged_prod_compose(
    tmp_path: Path,
    *,
    model_access_bindings: dict[str, str] | None = None,
) -> dict[str, object]:
    env = os.environ.copy()
    for key in (
        "COMPOSE_FILE",
        "LLM_PROVIDER",
        "LLM_PROVIDER_ENFORCE",
        "WATCHER_RUNTIME_ENV_FILE",
        "INSTANCE_OWNERSHIP_HOST_STATE_DIR",
        *MODEL_ACCESS_ENV_KEYS,
    ):
        env.pop(key, None)
    env["LLM_PROVIDER"] = "ambient-provider-must-not-win"
    env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"] = str(tmp_path / "instance-ownership")
    if model_access_bindings is not None:
        env.update(model_access_bindings)

    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(BASE_COMPOSE),
            "-f",
            str(PROD_COMPOSE),
            "-p",
            "pkm-prod-contract",
            "config",
            "--format",
            "json",
        ],
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


def _mount_for_target(service: dict[str, object], target: str) -> dict[str, object]:
    volumes = service.get("volumes", [])
    assert isinstance(volumes, list)
    mount = next(
        volume
        for volume in volumes
        if isinstance(volume, dict) and volume.get("target") == target
    )
    assert isinstance(mount, dict)
    return mount


def test_prod_model_access_bindings_are_scoped_to_product_callers(
    tmp_path: Path,
) -> None:
    services = _services(_merged_prod_compose(tmp_path))
    overlay_services = _load_compose(PROD_COMPOSE)["services"]
    assert isinstance(overlay_services, dict)

    for name in PRODUCT_CALLERS:
        service = services[name]
        overlay_service = overlay_services[name]
        overlay_environment = overlay_service.get("environment")
        assert isinstance(overlay_environment, dict)
        assert set(MODEL_ACCESS_ENV_KEYS).issubset(overlay_environment)
        for key in MODEL_ACCESS_ENV_KEYS:
            assert overlay_environment[key] == f"${{{key}:-}}"
        for env_files in (
            overlay_service.get("env_file", []),
            service.get("env_file", []),
        ):
            assert isinstance(env_files, list)
            assert not any(
                (entry.get("path") if isinstance(entry, dict) else entry)
                == MODEL_ACCESS_ENV_FILE
                for entry in env_files
            )

        mount = _mount_for_target(service, MODEL_ACCESS_CONTAINER_IDENTITY)
        assert mount["source"] == MODEL_ACCESS_HOST_IDENTITY
        assert mount["read_only"] is True
        bind = mount.get("bind")
        assert isinstance(bind, dict)
        assert bind["create_host_path"] is True

    for name, service in services.items():
        if name in PRODUCT_CALLERS:
            continue
        assert MODEL_ACCESS_CONTAINER_IDENTITY not in _mount_targets(service), name

    for name, service in overlay_services.items():
        if name in PRODUCT_CALLERS:
            continue
        environment = service.get("environment", {})
        assert isinstance(environment, dict)
        assert not set(MODEL_ACCESS_ENV_KEYS).intersection(environment), name

    expected_bindings = {
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT": "https://192.0.2.25:8443",
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE": "/run/model-access/codex-client/ca.pem",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT": "/run/model-access/codex-client/client.pem",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY": "/run/model-access/codex-client/client.key",
    }
    configured_services = _services(
        _merged_prod_compose(tmp_path, model_access_bindings=expected_bindings)
    )
    for name in PRODUCT_CALLERS:
        configured_environment = _environment(configured_services[name])
        for key, value in expected_bindings.items():
            assert configured_environment[key] == value


def test_prod_product_callers_allow_task_policy_with_mock_default(
    tmp_path: Path,
) -> None:
    services = _services(_merged_prod_compose(tmp_path))
    overlay_services = _load_compose(PROD_COMPOSE)["services"]
    assert isinstance(overlay_services, dict)

    for name in PRODUCT_CALLERS:
        environment = _environment(services[name])
        assert environment["LLM_PROVIDER"] == "mock"
        assert environment["LLM_PROVIDER_ENFORCE"] == "0"
        overlay_environment = overlay_services[name].get("environment")
        assert isinstance(overlay_environment, dict)
        assert overlay_environment["LLM_PROVIDER"] == "mock"
        assert overlay_environment["LLM_PROVIDER_ENFORCE"] == "0"

    for name, service in overlay_services.items():
        if name in PRODUCT_CALLERS:
            continue
        overlay_environment = service.get("environment", {})
        assert isinstance(overlay_environment, dict)
        assert "LLM_PROVIDER_ENFORCE" not in overlay_environment
