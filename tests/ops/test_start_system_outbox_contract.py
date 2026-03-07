from __future__ import annotations

from pathlib import Path

import yaml


def _load_compose(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_compose_watcher_worker_have_db_outbox_env() -> None:
    compose = _load_compose("docker-compose.yaml")
    services = compose.get("services") or {}
    for service_name in ("watcher", "worker"):
        service = services.get(service_name) or {}
        env = service.get("environment") or {}
        assert env.get("DATABASE_URL")
        assert env.get("DB_DSN")
        assert env.get("STORE_BACKEND") == "pg"


def test_compose_watcher_has_auto_exec_env() -> None:
    compose = _load_compose("docker-compose.yaml")
    watcher = (compose.get("services") or {}).get("watcher") or {}
    env = watcher.get("environment") or {}
    assert "WATCHER_AUTO_EXEC" in env
    assert "WATCHER_AUTO_EXEC-1" in str(env.get("WATCHER_AUTO_EXEC"))


def test_compose_watcher_uses_registry_command() -> None:
    compose = _load_compose("docker-compose.yaml")
    watcher = (compose.get("services") or {}).get("watcher") or {}
    command = watcher.get("command") or []
    if isinstance(command, list):
        cmd_text = " ".join(command)
    else:
        cmd_text = str(command)
    assert "app.cli" in cmd_text
    assert "watcher" in cmd_text
    assert "run" in cmd_text


def test_export_runtime_env_sets_database_url() -> None:
    script = Path("scripts/export_runtime_env.sh").read_text(encoding="utf-8")
    assert "DATABASE_URL" in script
    assert "DB_DSN" in script


def test_export_runtime_env_propagates_watcher_auto_exec() -> None:
    script = Path("scripts/export_runtime_env.sh").read_text(encoding="utf-8")
    assert "WATCHER_AUTO_EXEC" in script


def test_start_full_system_requires_database_url_for_runtime() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "DATABASE_URL" in script
    assert "db outbox" in script or "DATABASE_URL is required" in script


def test_start_full_system_applies_watcher_auto_exec_default() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "scripts/lib/start_full_system_env.sh" in script
    assert "apply_start_full_system_defaults" in script


def test_start_full_system_clears_obsidian_gate_fields_in_status_merge() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert '"obsidian_gate_enabled"' in script
    assert '"obsidian_gate_ok"' in script
    assert '"obsidian_gate_detail"' in script


def test_start_full_system_strict_gate_checks_installer_version() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "from app.cli.health import _get_obsidian_installer_version" in script
    assert "obsidian_dependency_status(get_installer_version=_get_obsidian_installer_version)" in script


def test_compose_watcher_fallback_uses_registry_command() -> None:
    compose = _load_compose("docker-compose.watcher.yml")
    watcher = (compose.get("services") or {}).get("watcher") or {}
    command = watcher.get("command") or []
    if isinstance(command, list):
        cmd_text = " ".join(command)
    else:
        cmd_text = str(command)
    assert "app.cli" in cmd_text
    assert "watcher" in cmd_text
    assert "run" in cmd_text
