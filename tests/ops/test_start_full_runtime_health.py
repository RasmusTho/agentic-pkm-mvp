from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.helpers.runtime_start_harness import run_runtime_start


REPO_ROOT = Path(__file__).resolve().parents[2]
# This full-start fixture exercises later health/deferred-index behavior. The
# real inventory producer/finalizer is separately covered fail-loud, and traced
# fixture startup completes successfully in roughly 28-34 seconds on this host.
STARTUP_FIXTURE_TIMEOUT_SECONDS = 45


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
        import os
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
        progress_path = os.environ.get("STARTUP_HARNESS_PROGRESS_PATH")
        if progress_path:
            with open(progress_path, "a", encoding="utf-8") as handle:
                handle.write(f"docker {{' '.join(args)}}\\n")
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
        import os
        import sys

        HEALTH = {health_json!r}
        progress_path = os.environ.get("STARTUP_HARNESS_PROGRESS_PATH")
        if progress_path:
            with open(progress_path, "a", encoding="utf-8") as handle:
                handle.write(f"curl {{' '.join(sys.argv[1:])}}\\n")
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


def _fake_inventory_python_bin(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "python3",
        f"""
        #!/usr/bin/env bash
        set -eu
        case "${{1:-}}" in
          */scripts/instance_state_writer_inventory.py)
            command="${{2:-}}"
            if [ "$command" = controller-token ]; then
              printf 'darwin:%064d\n' 0
              exit 0
            fi
            case "$command" in
              produce-legacy-owners|prove-quiescent|validate-legacy-owners)
                while [ "$#" -gt 0 ]; do
                  if [ "$1" = --output ]; then
                    printf '{{}}\n' >"$2"
                    exit 0
                  fi
                  shift
                done
                exit 2
                ;;
            esac
            ;;
        esac
        exec {sys.executable!s} "$@"
        """,
    )
    # These tests assert deferred-index startup behavior, not the independent
    # Obsidian-required policy or startup-status receipt serialization. Avoid
    # only those exact repeated inline programs; every other stdin program
    # still runs on the real interpreter, and both skipped helpers have direct
    # coverage elsewhere (as does the real inventory helper).
    _write_executable(
        bin_dir / "python",
        f"""
        #!/usr/bin/env bash
        set -eu
        if [ "${{1:-}}" = - ]; then
          program="$(cat)"
          case "$program" in
            *"from app.cli.health import _obsidian_required"*"_obsidian_required()"*)
              printf '0\n'
              exit 0
              ;;
            *"STARTUP_STATUS_PATH"*"tmp_path.write_text(json.dumps(payload, ensure_ascii=False))"*)
              printf '{{}}\n' > "${{STARTUP_STATUS_PATH:?}}"
              exit 0
              ;;
          esac
          printf '%s\n' "$program" | {sys.executable!s} "$@"
          exit $?
        fi
        exec {sys.executable!s} "$@"
        """,
    )


def _read_optional_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _runtime_env(tmp_path: Path, health: dict[str, object]) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_docker_bin(bin_dir, health)
    _fake_curl_bin(bin_dir, health)
    _fake_inventory_python_bin(bin_dir)

    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "Inbox").mkdir(parents=True)
    (vault / "System" / "vault.layout.md").write_text("---\n---\n", encoding="utf-8")
    (vault / "Inbox" / "note.md").write_text("hello\n", encoding="utf-8")
    (REPO_ROOT / "tmp").mkdir(exist_ok=True)
    (REPO_ROOT / "tmp" / "worker_heartbeat.json").write_text("{}", encoding="utf-8")

    env = os.environ.copy()
    for name in (
        "DESIGN_HANDOFF_APP_LOCAL_SETTINGS",
        "INSTANCE_LEGACY_OWNER_CONFIG_PATHS",
        "RUNTIME_ENV_PATH",
        "VAULT_HOST_ROOT",
        "VAULT_ROOT_DEV",
        "VAULT_ROOT_PROD",
        "VAULT_ROOT_TEST",
        "WATCHER_RUNTIME_ENV_FILE",
        "WATCHER_VAULT_PATH",
    ):
        env.pop(name, None)
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            # #4519 — scope the launcher's runtime env write to this test's
            # tmp_path. export_runtime_env.sh derives its default output path
            # from its own repo location, so without this override a launcher
            # subprocess overwrites the repository's real tmp/runtime.env with
            # pytest tmp paths that later dangle and block channel deploys.
            "RUNTIME_ENV_PATH": str(tmp_path / "runtime.env"),
            "VAULT_ROOT": str(vault),
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
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
            "STARTUP_HARNESS_PROGRESS_PATH": str(tmp_path / "startup-progress.log"),
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

    result = run_runtime_start(
        ["make", "dev-start-full"],
        cwd=REPO_ROOT,
        env=env,
        progress_path=Path(env["STARTUP_HARNESS_PROGRESS_PATH"]),
        total_timeout=STARTUP_FIXTURE_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "INFO: index rebuild is required but deferred" in result.stdout
    assert "runtime verified: true" in result.stdout


def test_dev_channel_alias_returns_zero_with_deferred_index_rebuild(tmp_path: Path) -> None:
    env = _runtime_env(tmp_path, _deferred_index_health())
    env["ENVIRONMENT"] = "dev"

    result = run_runtime_start(
        ["bash", "scripts/start_full_system.sh"],
        cwd=REPO_ROOT,
        env=env,
        progress_path=Path(env["STARTUP_HARNESS_PROGRESS_PATH"]),
        total_timeout=STARTUP_FIXTURE_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "INFO: index rebuild is required but deferred" in result.stdout
    assert "runtime verified: true" in result.stdout


def test_prod_start_full_rejects_deferred_index_rebuild(tmp_path: Path) -> None:
    env = _runtime_env(tmp_path, _deferred_index_health())
    env["COMPOSE_FILE"] = "docker-compose.yaml:docker-compose.prod.yml"
    env["COMPOSE_PROJECT_NAME"] = "pkm-prod"
    env["PKM_ENVIRONMENT"] = "prod"

    result = run_runtime_start(
        ["bash", "scripts/start_full_system.sh"],
        cwd=REPO_ROOT,
        env=env,
        progress_path=Path(env["STARTUP_HARNESS_PROGRESS_PATH"]),
        total_timeout=STARTUP_FIXTURE_TIMEOUT_SECONDS,
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


def test_launcher_tests_do_not_write_repo_runtime_env(tmp_path: Path) -> None:
    """#4519 enforcement: a real launcher run leaves the repo's runtime env alone.

    Runs the same prod launcher invocation whose temp vault path was found in
    the host's real ``tmp/runtime.env`` and asserts against the real repo paths
    afterwards — no mocked writer. The launcher must instead write the
    ``tmp_path``-scoped file selected via ``RUNTIME_ENV_PATH``.
    """
    repo_runtime_env = REPO_ROOT / "tmp" / "runtime.env"
    repo_test_runtime_env = REPO_ROOT / "tmp-test" / "runtime.env"
    before = _read_optional_bytes(repo_runtime_env)
    before_test = _read_optional_bytes(repo_test_runtime_env)

    env = _runtime_env(tmp_path, _deferred_index_health())
    env["COMPOSE_FILE"] = "docker-compose.yaml:docker-compose.prod.yml"
    env["COMPOSE_PROJECT_NAME"] = "pkm-prod"
    env["PKM_ENVIRONMENT"] = "prod"

    result = run_runtime_start(
        ["bash", "scripts/start_full_system.sh"],
        cwd=REPO_ROOT,
        env=env,
        progress_path=Path(env["STARTUP_HARNESS_PROGRESS_PATH"]),
        total_timeout=STARTUP_FIXTURE_TIMEOUT_SECONDS,
    )

    # Same launcher conclusion as the deferred-index prod rejection scenario;
    # a launcher that failed before exporting the runtime env would make the
    # invariance below vacuous, so prove the scoped write actually happened.
    assert result.returncode == 1, result.stderr + result.stdout
    scoped_runtime_env = tmp_path / "runtime.env"
    assert scoped_runtime_env.exists(), result.stderr + result.stdout
    scoped_content = scoped_runtime_env.read_text(encoding="utf-8")
    assert f"VAULT_HOST_ROOT={tmp_path / 'vault'}" in scoped_content

    # The repository's own operator state stayed byte-identical.
    assert _read_optional_bytes(repo_runtime_env) == before
    assert _read_optional_bytes(repo_test_runtime_env) == before_test


def test_unscoped_runtime_env_write_is_refused_under_pytest(tmp_path: Path) -> None:
    """#4519 guard: without RUNTIME_ENV_PATH, a pytest-driven export fails loud.

    A future launcher test that forgets to scope its runtime env must be
    refused before any write to the repository's real ``tmp/runtime.env`` —
    not silently redirected.
    """
    repo_runtime_env = REPO_ROOT / "tmp" / "runtime.env"
    repo_test_runtime_env = REPO_ROOT / "tmp-test" / "runtime.env"
    before = _read_optional_bytes(repo_runtime_env)
    before_test = _read_optional_bytes(repo_test_runtime_env)

    env = _runtime_env(tmp_path, _deferred_index_health())
    env.pop("RUNTIME_ENV_PATH", None)
    env.pop("COMPOSE_PROJECT_NAME", None)
    # The guard keys on the marker pytest itself exports to subprocesses; the
    # harness env must still carry it for the guard to be reachable at all.
    assert "PYTEST_CURRENT_TEST" in env

    result = subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3, result.stderr + result.stdout
    assert "refusing to write" in result.stderr
    assert "RUNTIME_ENV_PATH" in result.stderr
    assert _read_optional_bytes(repo_runtime_env) == before
    assert _read_optional_bytes(repo_test_runtime_env) == before_test


def test_operator_invocation_still_writes_repo_runtime_env(tmp_path: Path) -> None:
    """#4519 non-regression: a real operator invocation writes the repo default.

    The exporter is copied into a tmp_path-scoped fake repo root so the
    repo-relative default (``<root>/tmp/runtime.env``, derived from the
    script's own location) can be exercised end-to-end without touching this
    repository's real file. The pytest markers are removed from the child
    environment exactly as an operator shell would lack them.
    """
    fake_root = tmp_path / "fake-repo"
    (fake_root / "scripts" / "lib").mkdir(parents=True)
    for rel in ("scripts/export_runtime_env.sh", "scripts/lib/load_env_defaults.sh"):
        (fake_root / rel).write_bytes((REPO_ROOT / rel).read_bytes())

    # The exporter's inline Python needs the interpreter that carries the app
    # dependencies; expose it as `python3` the way an operator PATH would.
    bin_dir = tmp_path / "operator-bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "python3",
        f"""
        #!/usr/bin/env bash
        exec {sys.executable!s} "$@"
        """,
    )

    vault = tmp_path / "operator-vault"
    vault.mkdir()

    env = os.environ.copy()
    for name in (
        "COMPOSE_PROJECT_NAME",
        "NO_VAULT_MODE",
        "PYTEST_CURRENT_TEST",
        "PYTEST_VERSION",
        "RUNTIME_ENV_PATH",
        "VAULT_HOST_ROOT",
        "WATCHER_RUNTIME_ENV_FILE",
    ):
        env.pop(name, None)
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "PYTHONPATH": str(REPO_ROOT),
            "VAULT_ROOT": str(vault),
            "DATABASE_URL": "postgresql://app:app@db:5432/app",
            "DB_DSN": "postgresql://app:app@db:5432/app",
            "LLM_PROVIDER": "mock",
        }
    )

    result = subprocess.run(
        ["bash", str(fake_root / "scripts" / "export_runtime_env.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    written = fake_root / "tmp" / "runtime.env"
    assert written.exists(), result.stderr + result.stdout
    content = written.read_text(encoding="utf-8")
    assert f"VAULT_HOST_ROOT={vault}" in content
    assert "VAULT_ROOT=/app/vault" in content
