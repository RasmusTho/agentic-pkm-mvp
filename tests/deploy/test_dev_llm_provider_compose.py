from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
DEV_ENV = REPO_ROOT / "config/deploy/dev.env"
pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker executable not found on PATH",
)


def _merged_dev_compose(
    tmp_path: Path,
    *,
    llm_provider: str | None = None,
) -> dict[str, object]:
    env = os.environ.copy()
    env.pop("LLM_PROVIDER", None)
    if llm_provider is not None:
        env["LLM_PROVIDER"] = llm_provider
    env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"] = str(tmp_path / "instance-ownership")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(DEV_ENV),
            "-f",
            str(BASE_COMPOSE),
            "-f",
            str(DEV_COMPOSE),
            "-p",
            "pkm-dev-llm-contract",
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


def _environment(service: dict[str, object]) -> dict[str, str]:
    environment = service["environment"]
    assert isinstance(environment, dict)
    return {str(key): str(value) for key, value in environment.items()}


def test_dev_runtime_services_use_configured_provider_with_mock_default(
    tmp_path: Path,
) -> None:
    default_services = _merged_dev_compose(tmp_path)["services"]
    configured_services = _merged_dev_compose(
        tmp_path, llm_provider="governed-provider"
    )["services"]
    assert isinstance(default_services, dict)
    assert isinstance(configured_services, dict)

    for name in ("api", "worker", "watcher"):
        default_service = default_services[name]
        configured_service = configured_services[name]
        assert isinstance(default_service, dict)
        assert isinstance(configured_service, dict)
        assert _environment(default_service)["LLM_PROVIDER"] == "mock"
        assert _environment(configured_service)["LLM_PROVIDER"] == "governed-provider"

    for name in ("instance-state-init", "migrate", "heimdal-capture-watch"):
        default_service = default_services[name]
        configured_service = configured_services[name]
        assert isinstance(default_service, dict)
        assert isinstance(configured_service, dict)
        assert _environment(default_service)["LLM_PROVIDER"] == "mock"
        assert _environment(configured_service)["LLM_PROVIDER"] == "mock"
