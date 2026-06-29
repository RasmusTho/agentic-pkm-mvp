from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _deferred_index_health() -> dict[str, object]:
    return {
        "ok": False,
        "required_ok": False,
        "checks": {
            "embedding_index": {
                "ok": False,
                "required": True,
                "rebuild_required": True,
                "detail": "Identity mismatch",
            }
        },
        "runtime": {
            "watcher": {"ok": True, "status": "fresh"},
            "worker": {"ok": True, "status": "fresh"},
            "db": {"ok": True, "status": "ok"},
            "llm": {"ok": True, "status": "mock"},
        },
        "suggested_actions": [
            {
                "id": "index_rebuild",
                "severity": "required",
                "message": "Embedding/index identity mismatch detected",
                "command_hint": "python -m app.cli index rebuild --profile default",
            }
        ],
    }


def _hard_failure_health() -> dict[str, object]:
    payload = _deferred_index_health()
    payload["checks"] = {
        "embedding_index": {
            "ok": False,
            "required": True,
            "rebuild_required": True,
        },
        "llm_task_routes": {
            "ok": False,
            "required": True,
            "detail": "provider route unavailable",
        },
    }
    return payload


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_docker_bin(bin_dir: Path, health: dict[str, object]) -> None:
    health_json = json.dumps(health)
    _write_executable(
        bin_dir / "docker",
        f"""
        #!/usr/bin/env python3
        import json
        import sys

        HEALTH = {health_json!r}

        def compose_args(args):
            rest = args[1:]
            while rest and rest[0].startswith("-"):
                option = rest.pop(0)
                if option in {{"--env-file", "-f", "--project-name", "-p"}} and rest:
                    rest.pop(0)
            return rest

        def emit_service_table():
            print("NAME                 SERVICE   STATUS")
            for service in ("db", "api", "worker", "watcher"):
                print(f"pkm-dev-{{service}}-1    {{service}}   running")

        args = sys.argv[1:]
        if not args:
            raise SystemExit(0)
        if args[0] == "info":
            raise SystemExit(0)
        if args[0] == "ps":
            raise SystemExit(0)
        if args[0] == "inspect":
            print("healthy")
            raise SystemExit(0)
        if args[0] == "exec":
            cid = args[1] if len(args) > 1 else ""
            command = " ".join(args[2:])
            if "POSTGRES_USER" in command:
                print("app", end="")
            elif "POSTGRES_DB" in command:
                print("app", end="")
            elif "POSTGRES_PASSWORD" in command:
                print("app", end="")
            elif "psql" in command:
                print(" current_user | current_database ")
                print(" app          | app")
            elif "llm check" in command:
                print('{{"ok": true, "url": "mock", "latency_ms": 1}}')
            else:
                print(f"exec {{cid}}")
            raise SystemExit(0)
        if args[0] != "compose":
            raise SystemExit(0)

        rest = compose_args(args)
        if not rest:
            raise SystemExit(0)
        cmd = rest[0]
        if cmd == "config":
            print('{{"services": {{"db": {{"ports": []}}, "api": {{"ports": []}}, "worker": {{"ports": []}}, "watcher": {{"ports": []}}}}}}')
            raise SystemExit(0)
        if cmd == "up":
            raise SystemExit(0)
        if cmd == "logs":
            print("logs")
            raise SystemExit(0)
        if cmd == "ps":
            if "-q" in rest:
                service = rest[-1]
                print(f"{{service}}-cid")
            else:
                emit_service_table()
            raise SystemExit(0)
        if cmd == "exec":
            exec_rest = rest[rest.index("exec") + 1:]
            while exec_rest and exec_rest[0].startswith("-"):
                exec_rest.pop(0)
            service = exec_rest[0] if exec_rest else ""
            command = " ".join(exec_rest[1:])
            if service == "api" and "app.cli health --json" in command:
                print("health prelude")
                print(HEALTH)
                raise SystemExit(0 if json.loads(HEALTH).get("ok") else 1)
            elif service == "api" and "app.cli status" in command:
                print("runtime status ok")
            elif service == "api" and "app.cli store stats --json" in command:
                print('{{"objects": 1, "vectors": 0}}')
            elif service == "api" and "vault-layout-ensure" in command:
                print('{{"inbox_folder": "Inbox", "system_folder": "System", "layout_note": "System/vault.layout.md"}}')
            elif service == "api" and "vault-alpha-ingest" in command:
                print('{{"ingested": 0, "skipped_locked": 0}}')
            elif service == "api" and "find /app/vault" in command:
                print("1")
            elif service == "api" and "[ -d /app/vault ]" in command:
                raise SystemExit(0)
            elif service == "api" and "read_outbox" in command:
                print("0")
            elif service == "api" and ".startup_rw_probe" in command:
                print('{{"ok": true}}')
            else:
                print("ok")
            raise SystemExit(0)
        raise SystemExit(0)
        """,
    )


def _fake_curl_bin(bin_dir: Path, health: dict[str, object]) -> None:
    health_json = json.dumps(health)
    _write_executable(
        bin_dir / "curl",
        f"""
        #!/usr/bin/env python3
        import sys

        HEALTH = {health_json!r}
        url = next((arg for arg in reversed(sys.argv[1:]) if arg.startswith("http")), "")
        if "/api/health" in url:
            print(HEALTH)
        elif "/readyz" in url:
            print('{{"state": "ready"}}')
        elif "/search" in url:
            print('{{"results": [{{"id": "note-1"}}]}}')
        raise SystemExit(0)
        """,
    )


def _runtime_env(tmp_path: Path, health: dict[str, object]) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_docker_bin(bin_dir, health)
    _fake_curl_bin(bin_dir, health)

    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "Inbox").mkdir(parents=True)
    (vault / "System" / "vault.layout.md").write_text("---\n---\n", encoding="utf-8")
    (vault / "Inbox" / "note.md").write_text("hello\n", encoding="utf-8")
    (REPO_ROOT / "tmp").mkdir(exist_ok=True)
    (REPO_ROOT / "tmp" / "worker_heartbeat.json").write_text("{}", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "VAULT_ROOT": str(vault),
            "DATABASE_URL": "postgresql://app:app@db:5432/app",
            "DB_DSN": "postgresql://app:app@db:5432/app",
            "LLM_PROVIDER": "mock",
            "LLM_MODEL": "mock",
            "LLM_PROVIDER_ENFORCE": "1",
            "STARTUP_CHECK_OBSIDIAN": "0",
            "STARTUP_DISK_CHECK": "0",
            "START_FLIGHT_RECORDER": "0",
            "BUILDEROPS_BOOTSTRAP": "0",
            "RESET_RUNTIME_STATE": "0",
            "HEALTH_MAX_ATTEMPTS": "1",
            "WATCHER_HEARTBEAT_TIMEOUT": "1",
            "WORKER_HEARTBEAT_TIMEOUT": "1",
            "VERIFY_RUNTIME_SERVICE_WAIT_SECONDS": "1",
            "VERIFY_RUNTIME_SERVICE_WAIT_SLEEP_SECONDS": "1",
        }
    )
    return env


def test_runtime_verify_tolerates_deferred_index_rebuild(tmp_path: Path) -> None:
    env = _runtime_env(tmp_path, _deferred_index_health())
    env["RUNTIME_VERIFY_ALLOW_DEFERRED_INDEX_REBUILD"] = "1"

    result = subprocess.run(
        ["bash", "scripts/verify_runtime_stack.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "deferred index rebuild tolerated" in result.stdout
    assert "API_READY=true" in result.stdout


def test_dev_start_full_returns_zero_with_deferred_index_rebuild(tmp_path: Path) -> None:
    env = _runtime_env(tmp_path, _deferred_index_health())

    result = subprocess.run(
        ["make", "dev-start-full"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "INFO: index rebuild is required but deferred" in result.stdout
    assert "runtime verified: true" in result.stdout


def test_prod_start_full_rejects_deferred_index_rebuild(tmp_path: Path) -> None:
    env = _runtime_env(tmp_path, _deferred_index_health())
    env["COMPOSE_FILE"] = "docker-compose.yaml:docker-compose.prod.yml"
    env["COMPOSE_PROJECT_NAME"] = "pkm-prod"
    env["PKM_ENVIRONMENT"] = "prod"

    result = subprocess.run(
        ["bash", "scripts/start_full_system.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "required health ok=true not met" in result.stdout
    assert "runtime verified: true" not in result.stdout


def test_runtime_verify_rejects_hard_health_failures(tmp_path: Path) -> None:
    env = _runtime_env(tmp_path, _hard_failure_health())
    env["RUNTIME_VERIFY_ALLOW_DEFERRED_INDEX_REBUILD"] = "1"

    result = subprocess.run(
        ["bash", "scripts/verify_runtime_stack.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "required health ok=true not met" in result.stdout
    assert "API_READY=false" in result.stdout
