from __future__ import annotations

import os
from pathlib import Path
import subprocess

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
    assert "from app.cli.health import _get_obsidian_installer_version, _obsidian_required" in script
    assert "obsidian_dependency_status(get_installer_version=_get_obsidian_installer_version)" in script
    assert '"required": _obsidian_required()' in script


def test_start_full_system_has_vault_rw_probe() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "probe_vault_mount_rw" in script
    assert "STARTUP_REQUIRE_VAULT_RW" in script


def test_start_full_system_preserves_explicit_env_over_dotenv() -> None:
    script = Path("scripts/lib/load_env_defaults.sh").read_text(encoding="utf-8")
    assert 'if key in os.environ' in script


def test_start_full_system_derives_watcher_scope_from_layout_inbox() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    helper = Path("scripts/lib/start_full_system_env.sh").read_text(encoding="utf-8")
    assert 'layout_scope_glob="$(derive_start_full_system_scope_glob "$layout_inbox")"' in script
    assert "derive_start_full_system_scope_glob()" in helper
    assert 'printf "WATCHER_SCOPE_GLOB=%s\\n" "$layout_scope_glob" >> "$runtime_env_path"' in script


def test_start_full_system_staggers_worker_before_watcher() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    startup_block = script.split('reset_runtime_state="${RESET_RUNTIME_STATE:-1}"', 1)[1]
    worker_start = startup_block.index('compose_up "${compose_up_build_args[@]}" worker')
    worker_probe = startup_block.index("run_worker_probe")
    watcher_start = startup_block.index('compose_up "${compose_up_build_args[@]}" watcher')
    assert worker_start < worker_probe < watcher_start


def test_start_full_system_notes_colima_memory_floor() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "Colima" in script
    assert "4 GB" in script or "at least 4 GB" in script


def test_start_full_system_has_host_disk_space_preflight() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "check_startup_disk_space()" in script
    assert "STARTUP_DISK_MIN_FREE_MIB" in script
    assert "STARTUP_DISK_WARN_FREE_MIB" in script
    assert "STARTUP_DISK_CHECK=0" in script
    assert "flightrecorder-*.log" in script
    assert "watcher_tick-*.jsonl" in script


def test_start_full_system_disk_preflight_fails_before_docker_work(tmp_path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env sh\necho docker should not run >&2\nexit 99\n", encoding="utf-8")
    docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env.get('PATH', '')}",
            "START_FLIGHT_RECORDER": "0",
            "STARTUP_DISK_CHECK": "1",
            "STARTUP_DISK_CHECK_PATH": str(Path.cwd()),
            "STARTUP_DISK_MIN_FREE_MIB": "999999999",
            "STARTUP_DISK_WARN_FREE_MIB": "0",
        }
    )

    result = subprocess.run(
        ["bash", "scripts/start_full_system.sh"],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 3
    assert "STARTUP_DISK_MIN_FREE_MIB" in result.stderr
    assert "Safe cleanup candidates" in result.stderr
    assert "docker should not run" not in result.stderr


def test_startup_runbook_documents_disk_and_colima_recovery() -> None:
    runbook = Path("docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md").read_text(
        encoding="utf-8"
    )
    assert "Dev host preflight and safe `tmp/` cleanup" in runbook
    assert "STARTUP_DISK_MIN_FREE_MIB" in runbook
    assert "flightrecorder-*.log" in runbook
    assert "watcher_tick-*.jsonl" in runbook
    assert "tmp/index-outbox.jsonl" in runbook
    assert "Dev Colima/Docker recovery without touching prod" in runbook
    assert "limactl stop -f colima" in runbook


def test_companion_dev_page_documents_uat_layout_path_boundary() -> None:
    doc = Path("companion-ui/docs/REAL_NOTE_WORKSPACE_DEV_PAGE.md").read_text(
        encoding="utf-8"
    )
    assert "UAT note staging paths" in doc
    assert "VAULT_DESK_DIR_REL=" in doc
    assert "Workbench" in doc
    assert "explicit non-layout throwaway path" in doc


def test_start_full_system_runs_runtime_verification_and_endpoint_probe() -> None:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    assert "auto_configure_ollama_runtime_endpoint" in script
    assert "bash scripts/verify_runtime_stack.sh" in script
    assert "make persist-runtime-repairs" in script
    assert 'API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"' in script


def test_runtime_scripts_default_test_project_to_tmp_test_runtime_env() -> None:
    for path in (
        "scripts/start_full_system.sh",
        "scripts/export_runtime_env.sh",
        "scripts/verify_runtime_stack.sh",
        "scripts/cold_boot.sh",
    ):
        script = Path(path).read_text(encoding="utf-8")
        assert 'pkm-test) runtime_env_path="tmp-test/runtime.env"' in script


def test_verify_runtime_stack_waits_for_service_health_transitions() -> None:
    script = Path("scripts/verify_runtime_stack.sh").read_text(encoding="utf-8")
    assert "wait_for_service_ok()" in script
    assert 'VERIFY_RUNTIME_SERVICE_WAIT_SECONDS' in script
    assert "starting|created|restarting|missing" in script


def test_verify_runtime_stack_extracts_health_json_from_mixed_output() -> None:
    script = Path("scripts/verify_runtime_stack.sh").read_text(encoding="utf-8")
    assert 'health_output=$(run_docker_compose exec -T api python -m app.cli health --json)' in script
    assert 'health json payload not found in output' in script


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
