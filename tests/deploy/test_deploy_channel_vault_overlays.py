from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_HELPER = REPO_ROOT / "scripts/lib/deploy_channel_compose.sh"
DEPLOY_SCRIPT = REPO_ROOT / "scripts/deploy_channel.sh"
IMAGE_SHA = "fff07f13665d7e79270e20f8453b06da7b9f53d7"


def _render_deploy_compose(
    tmp_path: Path,
    *,
    channel: str,
    explicit_vault: bool,
) -> dict[str, object]:
    runtime_env = tmp_path / f"{channel}-runtime.env"
    runtime_lines = [
        "LLM_PROVIDER=mock",
        "DEPLOY_RUNTIME_SENTINEL=governed",
        "DATABASE_URL=postgresql+psycopg://app:app@db:5432/runtime_cross_channel",
        "DB_DSN=postgresql+psycopg://app:app@db:5432/runtime_cross_channel",
        f"WATCHER_ENABLE={'1' if channel == 'test' else '0'}",
        "WATCHER_VAULT_PATH=/app/vault" if channel == "test" else "WATCHER_VAULT_PATH=",
    ]
    selected_vault = tmp_path / "selected-vault"
    if explicit_vault:
        selected_vault.mkdir()
        runtime_lines.append(f"VAULT_HOST_ROOT={selected_vault}")
    runtime_env.write_text("\n".join(runtime_lines) + "\n", encoding="utf-8")

    channel_env = tmp_path / f"{channel}.env"
    channel_env.write_text(
        "\n".join(
            [
                f"WATCHER_RUNTIME_ENV_FILE={runtime_env}",
                "APP_IMAGE_REPOSITORY=ghcr.io/rasmustho/pkm-app",
                f"APP_IMAGE_TAG={IMAGE_SHA}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    overlay = f"docker-compose.{channel}.yml"
    project = f"pkm-{channel}-deploy-contract"
    command = f"""
set -euo pipefail
source {COMPOSE_HELPER!s}
deploy_channel_compose \
  {REPO_ROOT!s} \
  {channel} \
  {overlay} \
  {project} \
  {channel_env!s} \
  config --format json
"""
    env = os.environ.copy()
    hostile_vault = tmp_path / "hostile-parent-vault"
    hostile_vault.mkdir()
    hostile_runtime_env = tmp_path / "hostile-parent-runtime.env"
    hostile_runtime_env.write_text(
        "DEPLOY_RUNTIME_SENTINEL=hostile\n"
        "DATABASE_URL=postgresql+psycopg://app:app@db:5432/hostile_parent\n"
        "DB_DSN=postgresql+psycopg://app:app@db:5432/hostile_parent\n",
        encoding="utf-8",
    )
    for key in (
        "COMPOSE_FILE",
        "VAULT_ROOT",
        "VAULT_ROOT_TEST",
        "WATCHER_ENABLE",
        "WATCHER_VAULT_PATH",
    ):
        env.pop(key, None)
    env["VAULT_HOST_ROOT"] = str(hostile_vault)
    env["WATCHER_RUNTIME_ENV_FILE"] = str(hostile_runtime_env)
    result = subprocess.run(
        ["bash", "-c", command],
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


def _mount_source(service: dict[str, object], target: str) -> str | None:
    volumes = service.get("volumes", [])
    assert isinstance(volumes, list)
    for volume in volumes:
        if isinstance(volume, dict) and volume.get("target") == target:
            source = volume.get("source")
            return str(source) if source is not None else None
    return None


def test_deploy_channel_test_no_vault_keeps_idle_overlay_set(tmp_path: Path) -> None:
    services = _services(
        _render_deploy_compose(tmp_path, channel="test", explicit_vault=False)
    )

    for service_name in ("api", "worker", "watcher"):
        service = services[service_name]
        env = _environment(service)
        assert _mount_source(service, "/app/vault") is None
        assert "VAULT_ROOT" not in env
        assert "VAULT_ROOT_TEST" not in env
        assert env["WATCHER_ENABLE"] == "0"
        assert env["WATCHER_VAULT_PATH"] == ""
        assert env["DEPLOY_RUNTIME_SENTINEL"] == "governed"
        assert service["image"] == f"ghcr.io/rasmustho/pkm-app:{IMAGE_SHA}"


def test_deploy_channel_test_explicit_vault_uses_governed_overlay_order(
    tmp_path: Path,
) -> None:
    services = _services(
        _render_deploy_compose(tmp_path, channel="test", explicit_vault=True)
    )
    selected_vault = str(tmp_path / "selected-vault")

    for service_name in ("api", "worker", "watcher"):
        service = services[service_name]
        env = _environment(service)
        assert _mount_source(service, "/app/vault") == selected_vault
        assert env["VAULT_ROOT"] == "/app/vault"
        assert env["VAULT_ROOT_TEST"] == "/app/vault"
        assert env["WATCHER_ENABLE"] == "1"
        assert env["WATCHER_VAULT_PATH"] == "/app/vault"
        assert env["DEPLOY_RUNTIME_SENTINEL"] == "governed"
        assert service["image"] == f"ghcr.io/rasmustho/pkm-app:{IMAGE_SHA}"

    migrate = _environment(services["migrate"])
    assert migrate["DATABASE_URL"].endswith("/app_test")
    assert migrate["DB_DSN"].endswith("/app_test")
    assert migrate["LLM_PROVIDER"] == "mock"


def test_deploy_channel_non_test_explicit_vault_uses_legacy_overlay_only(
    tmp_path: Path,
) -> None:
    services = _services(
        _render_deploy_compose(tmp_path, channel="prod", explicit_vault=True)
    )
    selected_vault = str(tmp_path / "selected-vault")

    for service_name in ("api", "worker", "watcher"):
        service = services[service_name]
        env = _environment(service)
        assert _mount_source(service, "/app/vault") == selected_vault
        assert env["VAULT_ROOT"] == "/app/vault"
        assert env["WATCHER_ENABLE"] == "0"
        assert env["DEPLOY_RUNTIME_SENTINEL"] == "governed"
        assert env["DATABASE_URL"].endswith("/app")
        assert env["DB_DSN"].endswith("/app")


def test_deploy_and_rollback_share_vault_overlay_selection() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert script.count("deploy_channel_compose") == 2  # source path + one wrapper call
    assert "compose pull api worker watcher heimdal-capture-watch companion-ui" in script
    assert script.count("compose up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui") == 2
    assert 'if [ "${action}" = "rollback" ]' in script
