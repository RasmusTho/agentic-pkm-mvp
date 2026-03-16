from __future__ import annotations

from pathlib import Path

import yaml


def _load_compose(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _compose_env(service: dict) -> dict[str, str | None]:
    raw_env = service.get("environment") or {}
    if isinstance(raw_env, dict):
        return raw_env

    env: dict[str, str | None] = {}
    for entry in raw_env:
        key, sep, value = str(entry).partition("=")
        env[key] = value if sep else None
    return env


def test_compose_watcher_worker_have_db_outbox_env() -> None:
    compose = _load_compose("docker-compose.yaml")
    services = compose.get("services") or {}
    for service_name in ("api", "watcher", "worker"):
        service = services.get(service_name) or {}
        env = _compose_env(service)
        env_file = service.get("env_file") or []
        assert "./config/runtime.defaults.env" in env_file
        assert "VAULT_SYSTEM_DIR_REL" in env
        assert "VAULT_INBOX_DIR_REL" in env
        assert "VAULT_DESK_DIR_REL" in env


def test_compose_watcher_has_auto_exec_env() -> None:
    compose = _load_compose("docker-compose.yaml")
    watcher = (compose.get("services") or {}).get("watcher") or {}
    env = _compose_env(watcher)
    assert "WATCHER_AUTO_EXEC" in env
    assert "WATCHER_AUTO_EXEC-1" in str(env.get("WATCHER_AUTO_EXEC"))


def test_compose_watcher_scope_glob_is_optional_passthrough() -> None:
    compose = _load_compose("docker-compose.yaml")
    watcher = (compose.get("services") or {}).get("watcher") or {}
    env = _compose_env(watcher)
    assert "WATCHER_SCOPE_GLOB" not in env
    env_file = watcher.get("env_file") or []
    assert env_file
    assert env_file[1]["path"] == "${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}"
    assert env_file[1]["required"] is False


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


def test_export_runtime_env_propagates_vault_folder_env() -> None:
    script = Path("scripts/export_runtime_env.sh").read_text(encoding="utf-8")
    assert "VAULT_SYSTEM_DIR_REL" in script
    assert "VAULT_INBOX_DIR_REL" in script
    assert "VAULT_DESK_DIR_REL" in script


def test_start_full_system_requires_database_url_for_runtime() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "DATABASE_URL" in script
    assert "db outbox" in script or "DATABASE_URL is required" in script


def test_start_full_system_applies_watcher_auto_exec_default() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "scripts/lib/start_full_system_env.sh" in script
    assert "scripts/lib/runtime_endpoint_probe.sh" in script
    assert "apply_start_full_system_defaults" in script


def test_start_full_system_clears_obsidian_gate_fields_in_status_merge() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert '"obsidian_gate_enabled"' in script
    assert '"obsidian_gate_ok"' in script
    assert '"obsidian_gate_detail"' in script
    assert '"startup_succeeded"' in script
    assert '"runtime_verified"' in script
    assert '"operator_interrupted"' in script
    assert '"ollama_endpoint_repaired"' in script
    assert '"ollama_effective_base_url"' in script


def test_start_full_system_strict_gate_checks_installer_version() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "STARTUP_CHECK_OBSIDIAN" in script
    assert "from app.cli.health import _get_obsidian_installer_version" in script
    assert "obsidian_dependency_status(get_installer_version=_get_obsidian_installer_version)" in script


def test_start_full_system_has_vault_rw_probe() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "probe_vault_mount_rw" in script
    assert "STARTUP_REQUIRE_VAULT_RW" in script


def test_start_full_system_preserves_explicit_env_over_dotenv() -> None:
    script = Path("scripts/lib/load_env_defaults.sh").read_text(encoding="utf-8")
    assert 'if key in os.environ' in script


def test_start_full_system_derives_watcher_scope_from_layout_inbox() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert 'layout_scope_glob="${layout_inbox}/*.md,${layout_inbox}/**/*.md"' in script
    assert 'printf "WATCHER_SCOPE_GLOB=%s\\n" "$layout_scope_glob" >> "$runtime_env_path"' in script


def test_start_full_system_runs_runtime_verification_and_endpoint_probe() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "auto_configure_ollama_runtime_endpoint" in script
    assert "bash scripts/verify_runtime_stack.sh" in script
    assert "make persist-runtime-repairs" in script
    assert 'API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"' in script


def test_runtime_endpoint_probe_checks_docker_safe_candidates() -> None:
    script = Path("scripts/lib/runtime_endpoint_probe.sh").read_text(encoding="utf-8")
    assert "http://host.docker.internal:11434" in script
    assert "http://ollama:11434" in script
    assert "OLLAMA_URL" in script
    assert "OLLAMA_HOST" in script


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
