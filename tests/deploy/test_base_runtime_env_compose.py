"""Effective Compose regressions for governed base runtime env values (#3885)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

from app.release_channels.channel_isolation_preflight import _load_compose


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
COMPOSE_HELPER = REPO_ROOT / "scripts/lib/deploy_channel_compose.sh"
IMAGE_SHA = "f" * 40

WATCHER_GOVERNED_KEYS = {
    "WATCHER_STATE_DIR",
    "WATCHER_MAX_SCANNED_FILES_PER_TICK",
}
CAPTURE_GOVERNED_KEYS = {
    "HEIMDAL_CAPTURE_WATCH_DIR",
    "HEIMDAL_CAPTURE_INTERVAL_SECONDS",
    "HEIMDAL_RAW_STORE_KEY",
}

requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker executable not found on PATH",
)


def _environment(service: dict[str, object]) -> dict[str, str]:
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    assert isinstance(environment, list)
    normalized: dict[str, str] = {}
    for entry in environment:
        key, separator, value = str(entry).partition("=")
        normalized[key] = value if separator else ""
    return normalized


def _render_prod_with_synthetic_runtime_env(tmp_path: Path) -> dict[str, object]:
    runtime_env = tmp_path / "prod-runtime.env"
    runtime_env.write_text(
        "LLM_PROVIDER=synthetic-provider\n"
        "HEIMDAL_CAPTURE_WATCH_DIR=/synthetic/capture/inbox\n"
        "HEIMDAL_CAPTURE_INTERVAL_SECONDS=17\n"
        f"HEIMDAL_RAW_STORE_KEY={'a' * 64}\n",
        encoding="utf-8",
    )
    channel_env = tmp_path / "prod.env"
    channel_env.write_text(
        f"WATCHER_RUNTIME_ENV_FILE={runtime_env}\n"
        "APP_IMAGE_REPOSITORY=ghcr.io/rasmustho/pkm-app\n"
        f"APP_IMAGE_TAG={IMAGE_SHA}\n",
        encoding="utf-8",
    )

    command = "\n".join(
        (
            "set -euo pipefail",
            f"source {shlex.quote(str(COMPOSE_HELPER))}",
            "deploy_channel_compose "
            f"{shlex.quote(str(REPO_ROOT))} prod docker-compose.prod.yml "
            f"pkm-prod-issue-3885 {shlex.quote(str(channel_env))} "
            "config --format json",
        )
    )
    env = os.environ.copy()
    env["WATCHER_RUNTIME_ENV_FILE"] = str(tmp_path / "hostile-runtime.env")
    env["LLM_PROVIDER"] = "hostile-parent-provider"
    for key in WATCHER_GOVERNED_KEYS | CAPTURE_GOVERNED_KEYS:
        env[key] = f"hostile-parent-{key.lower()}"
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_base_services_do_not_shadow_governed_runtime_env_keys() -> None:
    services = _load_compose(BASE_COMPOSE)["services"]
    watcher_environment = _environment(services["watcher"])
    capture_environment = _environment(services["heimdal-capture-watch"])

    assert WATCHER_GOVERNED_KEYS.isdisjoint(watcher_environment)
    assert CAPTURE_GOVERNED_KEYS.isdisjoint(capture_environment)


def test_base_watcher_retains_llm_provider_cli_forwarding() -> None:
    watcher = _load_compose(BASE_COMPOSE)["services"]["watcher"]

    assert _environment(watcher)["LLM_PROVIDER"] == "${LLM_PROVIDER}"


@requires_docker
def test_prod_watcher_effective_render_preserves_runtime_env_and_defaults(
    tmp_path: Path,
) -> None:
    rendered = _render_prod_with_synthetic_runtime_env(tmp_path)
    services = rendered["services"]
    assert isinstance(services, dict)
    watcher = _environment(services["watcher"])

    assert watcher["LLM_PROVIDER"] == "synthetic-provider"
    assert watcher["WATCHER_STATE_DIR"] == "tmp"
    assert watcher["WATCHER_MAX_SCANNED_FILES_PER_TICK"] == "500"


@requires_docker
def test_prod_capture_watch_effective_render_preserves_runtime_env_values(
    tmp_path: Path,
) -> None:
    rendered = _render_prod_with_synthetic_runtime_env(tmp_path)
    services = rendered["services"]
    assert isinstance(services, dict)
    capture = _environment(services["heimdal-capture-watch"])

    assert capture["HEIMDAL_CAPTURE_WATCH_DIR"] == "/synthetic/capture/inbox"
    assert capture["HEIMDAL_CAPTURE_INTERVAL_SECONDS"] == "17"
    assert capture["HEIMDAL_RAW_STORE_KEY"] == "a" * 64
