from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
DEV_ENV = REPO_ROOT / "config/deploy/dev.env"


def _merged_dev_compose() -> dict[str, object]:
    env = os.environ.copy()
    env.pop("LLM_PROVIDER", None)
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


def test_dev_services_use_documented_mock_provider() -> None:
    compose = _merged_dev_compose()
    services = compose["services"]
    assert isinstance(services, dict)

    for name in ("migrate", "api", "worker", "watcher", "heimdal-capture-watch"):
        service = services[name]
        assert isinstance(service, dict)
        assert _environment(service)["LLM_PROVIDER"] == "mock"
