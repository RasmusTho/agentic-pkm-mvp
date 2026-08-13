from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from typing import NoReturn

import pytest

from scripts.prod_deploy_retry_preflight import _PROD_DB_HOST_PUBLISHED_PORT


REPO_ROOT = Path(__file__).resolve().parents[2]
_MACOS_MALLOC_STACK_LOGGING_PREFIX = "MallocStackLogging"
_DEPLOY_READINESS_TIMEOUT_SECONDS = 30
_DEPLOY_CLEANUP_TIMEOUT_SECONDS = 5


def _without_macos_malloc_stack_logging(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if source is None else source
    return {
        name: value
        for name, value in source.items()
        if not name.startswith(_MACOS_MALLOC_STACK_LOGGING_PREFIX)
    }


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _install_writer_inventory_harness(root: Path) -> None:
    """Keep channel-flow tests independent of the shared runner process table.

    The real helper's Linux race and fail-closed contracts are exercised in
    test_instance_state_volume_contract.py. These tests instead verify the
    deploy script's command ordering and failure routing, so inspecting every
    unrelated GitHub-runner process would add nondeterminism without covering
    another deploy-channel behavior.
    """

    _write_executable(
        root / "scripts/instance_state_writer_inventory.py",
        """#!/usr/bin/env python3
import json
from pathlib import Path
import sys


def _value(flag: str) -> str:
    try:
        return sys.argv[sys.argv.index(flag) + 1]
    except (ValueError, IndexError):
        raise SystemExit(f"missing required fixture argument: {flag}")


command = sys.argv[1] if len(sys.argv) > 1 else ""
if command == "controller-token":
    int(_value("--pid"))
    print("0" * 64)
elif command in {
    "produce-legacy-owners",
    "prove-quiescent",
    "validate-legacy-owners",
}:
    output = Path(_value("--output"))
    output.write_text(
        json.dumps(
            {
                "fixture": "deploy-channel-writer-inventory",
                "inventory_complete": True,
                "writers_drained": True,
            },
            sort_keys=True,
        )
        + "\\n",
        encoding="utf-8",
    )
else:
    raise SystemExit(f"unsupported writer-inventory fixture command: {command}")
""",
    )


def _deploy_harness(tmp_path: Path) -> tuple[Path, dict[str, str], str]:
    root = tmp_path / "repo"
    (root / "scripts/lib").mkdir(parents=True)
    (root / "config/deploy").mkdir(parents=True)
    (root / "app/alembic/versions").mkdir(parents=True)
    (root / "app/instance").mkdir(parents=True)
    (root / "app/ops").mkdir(parents=True)
    (root / "app/release_channels").mkdir(parents=True)
    (root / "config/secrets").mkdir(parents=True)
    (root / "config/tts-disabled").mkdir(parents=True)
    (root / "config/tts-disabled/.gitkeep").touch()
    (root / "ops/deployments").mkdir(parents=True)
    (root / "tmp").mkdir(parents=True)
    (root / "tmp/runtime.env").write_text("TTS_ENABLED=false\n", encoding="utf-8")
    (root / "app/__init__.py").write_text(
        '"""Isolated deploy-harness application package."""\n'
        "from pkgutil import extend_path\n"
        "__path__ = extend_path(__path__, __name__)\n",
        encoding="utf-8",
    )
    (root / "app/release_channels/__init__.py").write_text(
        '"""Isolated release-channel package with fixture fallthrough."""\n'
        "from pkgutil import extend_path\n"
        "__path__ = extend_path(__path__, __name__)\n",
        encoding="utf-8",
    )

    for relative in (
        "app/release_channels/reversibility.py",
        "app/ops/__init__.py",
        "app/ops/host_secret_contract.py",
        "app/ops/host_secret_bootstrap.py",
        "config/secrets/host_secret_contract.json",
        "scripts/deploy_channel.sh",
        "scripts/companion_ui_postdeploy_smoke.sh",
        "scripts/dev_test_environment_clobber_preflight.py",
        "scripts/lib/deploy_channel_compose.sh",
        "scripts/lib/heimdal_cold_volume_preflight.sh",
        "scripts/lib/instance_state_deployment.sh",
        "scripts/lib/instance_ownership_host_state.sh",
        "scripts/lib/signboard_root.sh",
        "scripts/instance_state_writer_inventory.py",
    ):
        destination = root / relative
        shutil.copy2(REPO_ROOT / relative, destination)
    _install_writer_inventory_harness(root)
    # The host-volume mechanism itself is covered with a fully injected
    # command runner in tests/heimdal.  This channel harness owns deploy
    # ordering and rollback behavior, so provide the new required producer
    # input as a deterministic, value-free preflight boundary.
    (root / "scripts/lib/heimdal_cold_volume_preflight.sh").write_text(
        """heimdal_cold_volume_preflight() {
  printf 'archive-preflight %s\\n' "${1:-missing}" >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  local rc="${FAKE_ARCHIVE_PREFLIGHT_RC:-0}"
  if [ "${rc}" -ne 0 ]; then
    echo 'archive volume preflight failed: output=redacted' >&2
    return "${rc}"
  fi
  return 0
}
""",
        encoding="utf-8",
    )
    (root / "app/instance/runtime.py").write_text(
        '"""Fixture marker for a target with the instance-state preflight."""\n',
        encoding="utf-8",
    )
    shutil.copy2(
        REPO_ROOT / "docker-compose.scalar-rollback.yml",
        root / "docker-compose.scalar-rollback.yml",
    )
    (root / "ops/scalar-rollback").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        root / "ops/scalar-rollback/nginx.conf",
    )

    # The deploy harness has no active-vault fixture. Keep that state explicit
    # and process-free so the host-wide writer inventory cannot race a
    # short-lived resolver subprocess that exists only because of test setup.
    (root / "scripts/lib/signboard_root.sh").write_text(
        "resolve_signboard_root_env() { unset SIGNBOARD_ROOT; }\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "add",
            "scripts",
            "app/instance/runtime.py",
            "docker-compose.scalar-rollback.yml",
            "ops/scalar-rollback/nginx.conf",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_marker = tmp_path / "docker-called"
    event_log = tmp_path / "deploy-events.log"
    _write_executable(
        bin_dir / "security",
        """#!/usr/bin/env bash
set -eu
if [ -n "${FAKE_SECURITY_EVENT_LOG:-}" ]; then
  account=""
  previous=""
  for argument in "$@"; do
    if [ "${previous}" = "-a" ]; then
      account="${argument}"
      break
    fi
    previous="${argument}"
  done
  case "${account}" in
    *:heimdal-raw-migrate:heimdal.raw-store-key)
      printf 'security migrate-primary\n' >> "${FAKE_SECURITY_EVENT_LOG}"
      ;;
    *)
      printf 'security sibling-or-other\n' >> "${FAKE_SECURITY_EVENT_LOG}"
      ;;
  esac
fi
case "${FAKE_SECURITY_MODE:-matching}" in
  missing)
    echo 'fixture-private-lookup-detail' >&2
    exit 44
    ;;
  malformed)
    printf '%s\n' 'fixture-private-malformed-material'
    ;;
  divergent)
    case "$*" in
      *heimdal-api-ingress*) printf '%064d\n' 1 ;;
      *) printf '%064d\n' 0 ;;
    esac
    ;;
  matching)
    printf '%064d\n' 0
    ;;
  *)
    exit 45
    ;;
esac
""",
    )
    _write_executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -eu
touch {docker_marker!s}
printf 'docker %s\\n' "$*" >> "${{FAKE_DEPLOY_EVENT_LOG:?}}"
if [ -n "${{FAKE_DOCKER_FAIL_MATCH:-}}" ] && [[ "$*" == *"${{FAKE_DOCKER_FAIL_MATCH}}"* ]]; then
  exit 24
fi
case "$*" in
  *"ps -aq"*"com.docker.compose.service=scalar-rollback-gateway"*)
    [ "${{FAKE_SCALAR_CONTAINERS:-0}}" = "1" ] && printf '%s\\n' fake-scalar-gateway
    ;;
  *"ps -aq"*"com.docker.compose.service=scalar-rollback-guard"*)
    [ "${{FAKE_SCALAR_CONTAINERS:-0}}" = "1" ] && printf '%s\\n' fake-scalar-guard
    ;;
  *" ps -q "*) printf '%064d\\n' 0 ;;
  inspect*) printf '%s\\n' "${{FAKE_CAPTURE_WATCH_STATUS:-healthy}}" ;;
esac
exit 0
""",
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
set -eu
printf 'curl %s\n' "$*" >> "${FAKE_DEPLOY_EVENT_LOG:?}"
case "$*" in
  *"--user "*":definitely-invalid"*)
    printf '%s' "${FAKE_SCALAR_GATEWAY_HTTP_STATUS:-401}"
    ;;
  *"--netrc-file "*)
    if [ "${FAKE_SCALAR_GATEWAY_AUTH:-pass}" = "fail" ]; then
      exit 22
    fi
    printf '{"ok":true}\n'
    ;;
  *"/version"*)
    if [ "${FAKE_VERSION_CURL:-pass}" = "fail" ]; then
      echo 'fake version curl diagnostic' >&2
      exit "${FAKE_VERSION_CURL_RC:-7}"
    fi
    printf '{"git_sha":"%s"}\\n' "${FAKE_VERSION_SHA:-$FAKE_SHA}"
    ;;
  *"/api/health"*) printf '{"ok":true,"required_ok":true,"version":{"git_sha":"%s"},"checks":{}}\\n' "${FAKE_HEALTH_VERSION_SHA:-$FAKE_SHA}" ;;
  *"/healthz"*)
    if [ "${FAKE_API_LIVENESS:-pass}" = "fail" ]; then
      exit 22
    fi
    printf '{"ok":true}\\n'
    ;;
  *) printf '{"ok":true}\\n' ;;
esac
""",
    )
    _write_executable(
        bin_dir / "cp",
        """#!/usr/bin/env bash
set -eu
if [ "${FAKE_PROMOTION_RECEIPT_COPY:-pass}" = "fail" ] && [[ "${2:-}" == */ops/promotions/* ]]; then
  echo 'fake promotion receipt copy diagnostic' >&2
  exit "${FAKE_PROMOTION_RECEIPT_COPY_RC:-61}"
fi
exec /bin/cp "$@"
""",
    )
    real_git = shutil.which("git")
    assert real_git is not None
    _write_executable(
        bin_dir / "git",
        f"""#!/usr/bin/env bash
set -eu
if [ -n "${{FAKE_GIT_SLEEP_MATCH:-}}" ] && [[ "$*" == *"${{FAKE_GIT_SLEEP_MATCH}}"* ]]; then
  touch "${{FAKE_GIT_SLEEP_MARKER:?}}"
  while [ ! -f "${{FAKE_GIT_RELEASE_MARKER:?}}" ]; do
    # The parent deploy shell can be terminated while this fake git command is
    # paused. Exit with it so inherited stdout/stderr descriptors cannot keep
    # the harness Popen alive during failure cleanup.
    kill -0 "$PPID" 2>/dev/null || exit 143
    sleep 0.25
  done
fi
if [ -n "${{FAKE_GIT_FAIL_MATCH:-}}" ] && [[ "$*" == *"${{FAKE_GIT_FAIL_MATCH}}"* ]]; then
  echo 'fake git materialization failure' >&2
  exit "${{FAKE_GIT_FAIL_RC:-87}}"
fi
exec {real_git!s} "$@"
""",
    )
    real_mv = shutil.which("mv")
    assert real_mv is not None
    _write_executable(
        bin_dir / "mv",
        f"""#!/usr/bin/env bash
set -eu
if [ -n "${{FAKE_MV_FAIL_MATCH:-}}" ] && [[ "$*" == *"${{FAKE_MV_FAIL_MATCH}}"* ]]; then
  counter_file="${{FAKE_MV_COUNTER_FILE:?}}"
  count=0
  [ ! -f "${{counter_file}}" ] || count="$(cat "${{counter_file}}")"
  count=$((count + 1))
  printf '%s\n' "${{count}}" >"${{counter_file}}"
  if [ "${{count}}" -eq "${{FAKE_MV_FAIL_ON_COUNT:-1}}" ]; then
    echo 'fake mv failure' >&2
    exit "${{FAKE_MV_FAIL_RC:-62}}"
  fi
fi
exec {real_mv!s} "$@"
""",
    )
    python_wrapper = bin_dir / "python"
    _write_executable(
        python_wrapper,
        f"""#!/usr/bin/env bash
set -eu
if [ "${{1:-}}" = "-c" ] && [[ "${{2:-}}" == *sync_playwright* ]]; then
  if [ "${{FAKE_PLAYWRIGHT_PREFLIGHT:-pass}}" = "fail" ]; then
    echo 'playwright chromium unavailable' >&2
    exit 86
  fi
  exit 0
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "pytest" ]; then
  if [[ "$*" == *"--collect-only"* ]]; then
    case "${{FAKE_PYTEST_SMOKE_PREFLIGHT:-pass}}" in
      fail)
        echo 'fake pytest: live-smoke module collection failed' >&2
        exit 1
        ;;
      empty)
        echo 'no tests collected in 0.01s'
        exit 5
        ;;
      *)
        echo 'SKIPPED [1] tests/companion_ui/test_companion_ui_live_smoke.py: Set COMPANION_UI_SMOKE_URL'
        echo 'no tests collected in 0.01s'
        exit 5
        ;;
    esac
  fi
  if [ "${{FAKE_POSTDEPLOY_SMOKE:-pass}}" = "fail" ]; then
    echo 'fake postdeploy smoke diagnostic' >&2
    exit "${{FAKE_POSTDEPLOY_SMOKE_RC:-73}}"
  fi
  exit 0
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "app.release_channels.fleet_model_fitness" ]; then
  if [ "${{FAKE_FLEET_MODEL_FITNESS:-pass}}" = "fail" ]; then
    echo 'fake fleet-model fitness diagnostic' >&2
    exit "${{FAKE_FLEET_MODEL_FITNESS_RC:-41}}"
  fi
  printf '%s\\n' '{{"ok":true}}'
  exit 0
fi
if [ "${{1:-}}" = "-" ] && [[ "${{2:-}}" == */ops/deployments/* ]] && [ "${{FAKE_RECEIPT_WRITE:-pass}}" = "fail" ]; then
  echo 'fake receipt write diagnostic' >&2
  exit "${{FAKE_RECEIPT_WRITE_RC:-52}}"
fi
exec {sys.executable!s} "$@"
""",
    )

    # Malloc stack logging is a host-only debugging facility. Letting it
    # propagate into every short-lived fake command makes the concurrency
    # harness depend on macOS process-startup timing instead of the channel
    # lock it is meant to prove.
    env = _without_macos_malloc_stack_logging()
    for name in (
        "DESIGN_HANDOFF_APP_LOCAL_SETTINGS",
        "INSTANCE_LEGACY_OWNER_CONFIG_PATHS",
        "SIGNBOARD_ROOT",
        "VAULT_HOST_ROOT",
        "VAULT_ROOT",
        "VAULT_ROOT_DEV",
        "VAULT_ROOT_PROD",
        "VAULT_ROOT_TEST",
        "WATCHER_RUNTIME_ENV_FILE",
        "WATCHER_VAULT_PATH",
    ):
        env.pop(name, None)
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PYTHON": str(python_wrapper),
            "FAKE_SHA": sha,
            "FAKE_DEPLOY_EVENT_LOG": str(event_log),
            "DEPLOY_HEALTH_TIMEOUT_SECONDS": "1",
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(tmp_path / "instance-ownership"),
        }
    )
    return root, env, sha


def _run_deploy(
    root: Path, env: dict[str, str], sha: str, *extra: str, channel: str = "dev"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "deploy", channel, sha, *extra],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_rollback(
    root: Path, env: dict[str, str], sha: str, *, channel: str = "dev"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", channel, sha],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_archive_preflight_blocks_deploy_but_never_gates_rollback(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={sha}\n",
        encoding="utf-8",
    )
    env["FAKE_ARCHIVE_PREFLIGHT_RC"] = "78"

    deploy = _run_deploy(root, env, sha)
    assert deploy.returncode == 78
    assert "archive volume preflight failed: output=redacted" in deploy.stderr
    assert _deploy_events(env) == ["archive-preflight dev"]

    Path(env["FAKE_DEPLOY_EVENT_LOG"]).write_text("", encoding="utf-8")
    rollback = _run_rollback(root, env, sha)
    assert rollback.returncode == 0, rollback.stdout + rollback.stderr
    assert not any(event.startswith("archive-preflight") for event in _deploy_events(env))


def test_deploy_channel_preflights_embedding_provider_before_health_gate() -> None:
    script = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    preflight = 'run_postmutation_gate "embedding provider configuration preflight failed"'
    assert preflight in script
    assert "embedding_provider_preflight_gate()" in script
    assert "compose exec -T api python -m app.cli settings validate --json" in script
    assert script.index(preflight) < script.index('run_postmutation_gate "health gate failed"')


def test_deploy_channel_rolls_back_when_embedding_provider_preflight_fails(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_DOCKER_FAIL_MATCH"] = "exec -T api python -m app.cli settings validate --json"

    result = _run_deploy(root, env, sha)

    assert result.returncode == 24
    assert "embedding provider configuration preflight failed" in result.stderr


def _wait_for_path_or_process_exit(
    process: subprocess.Popen[str],
    path: Path,
    release_marker: Path,
    *,
    description: str,
) -> None:
    """Wait for an explicit harness signal, failing early if the child exits."""
    deadline = time.monotonic() + _DEPLOY_READINESS_TIMEOUT_SECONDS
    while not path.exists():
        if process.poll() is not None:
            try:
                stdout, stderr = process.communicate(
                    timeout=max(
                        0.001,
                        min(
                            _DEPLOY_CLEANUP_TIMEOUT_SECONDS,
                            deadline - time.monotonic(),
                        ),
                    )
                )
            except subprocess.TimeoutExpired:
                _fail_after_deploy_cleanup(
                    process,
                    release_marker,
                    f"slow deploy exited before {description}, but a descendant retained "
                    "captured pipes",
                )
            pytest.fail(
                f"slow deploy exited before {description}: {stdout}{stderr}",
                pytrace=False,
            )
        if time.monotonic() >= deadline:
            _fail_after_deploy_cleanup(
                process,
                release_marker,
                f"slow deploy remained alive without reaching {description} within "
                f"{_DEPLOY_READINESS_TIMEOUT_SECONDS}s",
            )
        time.sleep(0.02)


class _DeployCleanupError(RuntimeError):
    """Controlled cleanup failure that must be appended to the test trigger."""


def _signal_deploy_process_group(
    process: subprocess.Popen[str], sig: signal.Signals
) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        raise _DeployCleanupError(
            f"fake deploy process-group {sig.name} cleanup denied; "
            "refusing unsafe partial cleanup"
        ) from None


def _release_and_reap_deploy(
    process: subprocess.Popen[str], release_marker: Path
) -> tuple[str, str]:
    """Release, terminate, and reap the complete isolated fake-deploy process group."""
    release_marker.touch()
    _signal_deploy_process_group(process, signal.SIGTERM)
    try:
        return process.communicate(timeout=_DEPLOY_CLEANUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_deploy_process_group(process, signal.SIGKILL)
        try:
            return process.communicate(timeout=_DEPLOY_CLEANUP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise _DeployCleanupError(
                "fake deploy process group did not close captured pipes after SIGKILL",
            ) from None


def _fail_after_deploy_cleanup(
    process: subprocess.Popen[str], release_marker: Path, trigger: str
) -> NoReturn:
    try:
        stdout, stderr = _release_and_reap_deploy(process, release_marker)
    except _DeployCleanupError as cleanup_error:
        pytest.fail(f"{trigger}; cleanup failed: {cleanup_error}", pytrace=False)
    pytest.fail(f"{trigger}; cleanup output: {stdout}{stderr}", pytrace=False)


def _wait_for_deploy_exit(
    process: subprocess.Popen[str], release_marker: Path, *, description: str
) -> tuple[str, str]:
    """Wait for a released fake deploy to finish, then drain its closed pipes."""
    deadline = time.monotonic() + _DEPLOY_READINESS_TIMEOUT_SECONDS
    while process.poll() is None:
        if time.monotonic() >= deadline:
            _fail_after_deploy_cleanup(
                process,
                release_marker,
                f"slow deploy remained alive after {description} for "
                f"{_DEPLOY_READINESS_TIMEOUT_SECONDS}s",
            )
        time.sleep(0.02)

    try:
        stdout, stderr = process.communicate(
            timeout=max(
                0.001,
                min(
                    _DEPLOY_CLEANUP_TIMEOUT_SECONDS,
                    deadline - time.monotonic(),
                ),
            )
        )
    except subprocess.TimeoutExpired:
        _fail_after_deploy_cleanup(
            process,
            release_marker,
            f"slow deploy exited after {description}, but a descendant retained "
            "captured pipes",
        )
    assert process.returncode == 0, stdout + stderr
    return stdout, stderr


def test_channel_lock_covers_pin_snapshot_and_migration_classification(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/overlap_lock.py"
    migration.write_text(
        'revision = "overlap_lock"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "reversible"\n'
        'def downgrade():\n    pass\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add overlap migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    marker = tmp_path / "git-sleep-started"
    release_marker = tmp_path / "git-sleep-release"
    slow_env = dict(env)
    slow_env.update(
        {
            "FAKE_SHA": target_sha,
            "FAKE_GIT_SLEEP_MATCH": "diff --diff-filter",
            "FAKE_GIT_SLEEP_MARKER": str(marker),
            "FAKE_GIT_RELEASE_MARKER": str(release_marker),
        }
    )
    slow = subprocess.Popen(
        ["bash", "scripts/deploy_channel.sh", "deploy", "dev", target_sha],
        cwd=root,
        env=slow_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        _wait_for_path_or_process_exit(
            slow,
            marker,
            release_marker,
            description="migration classification",
        )

        overlapping = _run_deploy(root, env, target_sha)

        assert overlapping.returncode == 89
        assert "channel mutation blocked" in overlapping.stderr
        release_marker.touch()
        _wait_for_deploy_exit(
            slow,
            release_marker,
            description="the overlapping deploy rejection",
        )
        assert f"APP_IMAGE_TAG={target_sha}" in pin_path.read_text(encoding="utf-8")
    finally:
        _release_and_reap_deploy(slow, release_marker)


def _cleanup_fixture_env() -> dict[str, str]:
    fixture_env = _without_macos_malloc_stack_logging()
    removed_names = set(os.environ) - set(fixture_env)
    assert removed_names == {
        name
        for name in os.environ
        if name.startswith(_MACOS_MALLOC_STACK_LOGGING_PREFIX)
    }
    return fixture_env


def _assert_pid_gone(pid: int) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail(f"cleanup fixture descendant {pid} remained alive", pytrace=False)


def test_wait_for_path_reaps_descendant_holding_pipes_after_parent_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "_DEPLOY_CLEANUP_TIMEOUT_SECONDS", 0.2)
    child_pid_path = tmp_path / "readiness-child.pid"
    child_ready_path = tmp_path / "readiness-child-ready"
    parent_ready_path = tmp_path / "readiness-parent-ready"
    parent_exit_path = tmp_path / "readiness-parent-exit"
    release_marker = tmp_path / "readiness-release"
    fixture_env = _cleanup_fixture_env()
    fixture_env.update(
        {
            "CHILD_PID_PATH": str(child_pid_path),
            "CHILD_READY_PATH": str(child_ready_path),
            "PARENT_READY_PATH": str(parent_ready_path),
            "PARENT_EXIT_PATH": str(parent_exit_path),
        }
    )
    process = subprocess.Popen(
        [
            "bash",
            "-c",
            (
                "bash -c 'touch \"$CHILD_READY_PATH\"; sleep 60' & child=$!; "
                "printf '%s\\n' \"$child\" > \"$CHILD_PID_PATH\"; "
                "while [ ! -f \"$CHILD_READY_PATH\" ]; do sleep 0.01; done; "
                "touch \"$PARENT_READY_PATH\"; "
                "while [ ! -f \"$PARENT_EXIT_PATH\" ]; do sleep 0.01; done; "
                "printf 'original readiness failure\\n' >&2; "
                "exit 17"
            ),
        ],
        env=fixture_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _wait_for_path_or_process_exit(
        process,
        parent_ready_path,
        release_marker,
        description="the parent and child readiness markers",
    )
    assert child_ready_path.exists()
    parent_exit_path.touch()

    with pytest.raises(pytest.fail.Exception) as failure:
        _wait_for_path_or_process_exit(
            process,
            tmp_path / "never-ready",
            release_marker,
            description="the impossible readiness marker",
        )

    assert "descendant retained captured pipes" in str(failure.value)
    assert "original readiness failure" in str(failure.value)
    assert release_marker.exists()
    _assert_pid_gone(int(child_pid_path.read_text(encoding="utf-8").strip()))


def test_wait_for_exit_kills_term_ignoring_descendant_holding_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "_DEPLOY_CLEANUP_TIMEOUT_SECONDS", 0.2)
    child_pid_path = tmp_path / "exit-child.pid"
    child_ready_path = tmp_path / "exit-child-ready"
    parent_ready_path = tmp_path / "exit-parent-ready"
    parent_exit_path = tmp_path / "exit-parent-exit"
    release_marker = tmp_path / "exit-release"
    fixture_env = _cleanup_fixture_env()
    fixture_env.update(
        {
            "CHILD_PID_PATH": str(child_pid_path),
            "CHILD_READY_PATH": str(child_ready_path),
            "PARENT_READY_PATH": str(parent_ready_path),
            "PARENT_EXIT_PATH": str(parent_exit_path),
        }
    )
    process = subprocess.Popen(
        [
            "bash",
            "-c",
            (
                "bash -c 'trap \"\" TERM; touch \"$CHILD_READY_PATH\"; "
                "while :; do sleep 1; done' & child=$!; "
                "printf '%s\\n' \"$child\" > \"$CHILD_PID_PATH\"; "
                "while [ ! -f \"$CHILD_READY_PATH\" ]; do sleep 0.01; done; "
                "touch \"$PARENT_READY_PATH\"; "
                "while [ ! -f \"$PARENT_EXIT_PATH\" ]; do sleep 0.01; done; "
                "printf 'parent exited cleanly\\n'; exit 0"
            ),
        ],
        env=fixture_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    delivered_signals: list[signal.Signals] = []
    signal_group = _signal_deploy_process_group

    def record_signal(target: subprocess.Popen[str], sig: signal.Signals) -> None:
        delivered_signals.append(sig)
        signal_group(target, sig)

    monkeypatch.setattr(sys.modules[__name__], "_signal_deploy_process_group", record_signal)
    _wait_for_path_or_process_exit(
        process,
        parent_ready_path,
        release_marker,
        description="the parent and TERM-ignoring child readiness markers",
    )
    assert child_ready_path.exists()
    parent_exit_path.touch()

    with pytest.raises(pytest.fail.Exception) as failure:
        _wait_for_deploy_exit(
            process,
            release_marker,
            description="the parent process exit",
        )

    assert "descendant retained captured pipes" in str(failure.value)
    assert "parent exited cleanly" in str(failure.value)
    assert delivered_signals == [signal.SIGTERM, signal.SIGKILL]
    assert release_marker.exists()
    _assert_pid_gone(int(child_pid_path.read_text(encoding="utf-8").strip()))


def test_wait_preserves_trigger_when_group_cleanup_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "_DEPLOY_CLEANUP_TIMEOUT_SECONDS", 1)
    release_marker = tmp_path / "permission-release"
    child_pid_path = tmp_path / "permission-child.pid"
    child_ready_path = tmp_path / "permission-child-ready"
    parent_ready_path = tmp_path / "permission-parent-ready"
    fixture_env = _cleanup_fixture_env()
    fixture_env.update(
        {
            "CHILD_PID_PATH": str(child_pid_path),
            "CHILD_READY_PATH": str(child_ready_path),
            "PARENT_READY_PATH": str(parent_ready_path),
        }
    )
    process = subprocess.Popen(
        [
            "bash",
            "-c",
            (
                "bash -c 'trap \"\" TERM; touch \"$CHILD_READY_PATH\"; "
                "while :; do sleep 1; done' & child=$!; "
                "printf '%s\\n' \"$child\" > \"$CHILD_PID_PATH\"; "
                "while [ ! -f \"$CHILD_READY_PATH\" ]; do sleep 0.01; done; "
                "printf 'original cleanup failure\\n' >&2; "
                "touch \"$PARENT_READY_PATH\"; wait"
            ),
        ],
        env=fixture_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _wait_for_path_or_process_exit(
        process,
        parent_ready_path,
        release_marker,
        description="the PermissionError parent and child readiness markers",
    )
    assert child_ready_path.exists()
    child_pid = int(child_pid_path.read_text(encoding="utf-8").strip())
    parent_pid = process.pid
    real_killpg = os.killpg

    def deny_group_signal(_process_group: int, _sig: signal.Signals) -> None:
        raise PermissionError("denied by regression fixture")

    monkeypatch.setattr(os, "killpg", deny_group_signal)
    monkeypatch.setattr(sys.modules[__name__], "_DEPLOY_READINESS_TIMEOUT_SECONDS", 0.1)
    try:
        with pytest.raises(pytest.fail.Exception) as failure:
            _wait_for_deploy_exit(
                process,
                release_marker,
                description="the denied-cleanup regression trigger",
            )
    finally:
        real_killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=_DEPLOY_CLEANUP_TIMEOUT_SECONDS)

    assert "slow deploy remained alive after the denied-cleanup regression trigger" in str(
        failure.value
    )
    assert "cleanup failed" in str(failure.value)
    assert "process-group SIGTERM cleanup denied" in str(failure.value)
    assert "refusing unsafe partial cleanup" in str(failure.value)
    assert "PermissionError" not in str(failure.value)
    assert "denied by regression fixture" not in str(failure.value)
    assert stdout == ""
    assert "original cleanup failure" in stderr
    assert process.poll() is not None
    assert release_marker.exists()
    _assert_pid_gone(child_pid)
    _assert_pid_gone(parent_pid)


_FAKE_PSYCOPG_MODULE = '''\
"""Fake psycopg shim for tests/deploy/test_deploy_channel.py.

Shadows the real psycopg package via PYTHONPATH so
scripts/prod_deploy_retry_preflight.py's actual classification logic runs
against controlled, in-memory rows instead of a live Postgres -- this laptop
has no PostgreSQL/Docker by design (see AGENTS.md).
"""
import json
import os


class OperationalError(Exception):
    pass


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        return self

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def close(self):
        pass


def connect(dsn, **kwargs):
    # H3 (#3903 round 6): record the exact DSN every call actually received,
    # so a test can assert the real host:port rather than only "not the one
    # poison string" -- a hardcoded host-translation constant drifting from
    # docker-compose.yaml's real port mapping would otherwise still pass
    # every existing assertion here (any non-poison DSN accepted).
    log_path = os.environ.get("FAKE_OUTBOX_CONNECT_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(dsn + "\\n")
    if os.environ.get("FAKE_OUTBOX_DB_UNREACHABLE") == "1":
        raise OperationalError("fake: db unreachable")
    # Regression guard for the ambient-env-contamination bug (#3903 round 3):
    # a DSN this test marks "poison" must never actually be connected to. If
    # the preflight ever resolves an ambient/foreign runtime env file again,
    # this makes that mistake fail loud (skipped:db_unreachable) instead of
    # silently succeeding against the wrong database.
    if dsn == os.environ.get("FAKE_OUTBOX_POISON_DSN"):
        raise OperationalError("fake: connected to a DSN this test forbids")
    raw = os.environ.get("FAKE_OUTBOX_ROWS_JSON", "[]")
    rows = [tuple(row) for row in json.loads(raw)]
    return _FakeConnection(rows)
'''


# Deliberately credential-bearing: the redaction test asserts none of these
# identity fragments ever reach deploy output. Used as an ambient
# DATABASE_URL override -- the ONE legitimate way to steer the resolved DSN
# in a test, since Compose interpolation itself honors a shell-exported
# DATABASE_URL/DB_DSN identically for the preflight and the real deploy.
_FAKE_PROD_DSN = "postgresql://produser:sup3rsecret@prod-db.internal:5432/pkm_prod"

# A DSN standing in for a stale/foreign file (pin-file-referenced runtime env,
# tmp/runtime.env, or any other env_file layer) that must have NO EFFECT on
# resolution: docker-compose.prod.yml sets DATABASE_URL/DB_DSN directly in
# `environment:` for every channel-critical service, and Compose's own rule
# is that `environment:` always wins over `env_file:` for the same key
# (#3903 round 4). The fake DB layer refuses to connect to this DSN, so any
# test that poisons a file with it and still sees a successful connection
# proves the file was never consulted.
_ENV_FILE_POISON_DSN = "postgresql://env-file-should-never-be-used/poisoned"


def _configure_prod_retry_preflight(
    root: Path,
    env: dict[str, str],
    tmp_path: Path,
    *,
    rows: list[tuple[str, dict, int]] | None = None,
    unreachable: bool = False,
    dsn_override: str | None = None,
    compose_files_present: bool = True,
    pin_file_dsn_override: str | None = None,
) -> None:
    """Copy the real preflight script + real compose files into the fixture
    repo, and fake the DB connection layer.

    ``rows`` is a list of ``(topic, payload, attempts)`` triples standing in
    for pending (``delivered_at is null``) outbox rows. The real
    scripts/prod_deploy_retry_preflight.py runs unmodified against these rows
    through the fake psycopg module below -- only the DB connection is faked;
    the classification logic under test is real.

    DSN resolution (#3903 rounds 4 and 6): the preflight no longer reads any
    pin or runtime-env file BY HAND -- it asks the REAL, unmodified
    app.release_channels.channel_isolation_preflight module (imported via
    PYTHONPATH, not copied) what the REAL committed docker-compose.prod.yml's
    worker service actually binds, exactly as the production code path does.
    With ``compose_files_present=True`` (default) docker-compose.yaml and
    docker-compose.prod.yml are copied into the fixture repo so that
    resolution succeeds against the genuine, current compose definitions --
    resolving to the real literal default
    (``postgresql+psycopg://app:app@db:5432/app``, host-translated to
    ``127.0.0.1:15432`` by the preflight) unless ``dsn_override`` or
    ``pin_file_dsn_override`` is set. ``dsn_override`` sets an ambient
    DATABASE_URL, matching the one Compose interpolation itself allows
    overriding the resolved value with; ``pin_file_dsn_override`` instead
    writes a real ``DATABASE_URL=`` line into ``config/deploy/prod.env`` (the
    channel pin file), matching the OTHER genuine interpolation source the
    real deploy passes to Compose as ``--env-file`` -- Compose's own
    precedence has the ambient shell win over ``--env-file``, so setting both
    together exercises that ordering. ``compose_files_present=False`` omits
    the compose files entirely, exercising the visible skipped:no_dsn path
    for "resolution is impossible at all", not "a file was empty".
    """
    shutil.copy2(
        REPO_ROOT / "scripts/prod_deploy_retry_preflight.py",
        root / "scripts/prod_deploy_retry_preflight.py",
    )
    if compose_files_present:
        shutil.copy2(REPO_ROOT / "docker-compose.yaml", root / "docker-compose.yaml")
        shutil.copy2(REPO_ROOT / "docker-compose.prod.yml", root / "docker-compose.prod.yml")
    if pin_file_dsn_override is not None:
        pin_dir = root / "config" / "deploy"
        pin_dir.mkdir(parents=True, exist_ok=True)
        (pin_dir / "prod.env").write_text(
            "# deploy pin (H1 regression fixture: operator-added DSN key)\n"
            f"DATABASE_URL={pin_file_dsn_override}\n",
            encoding="utf-8",
        )

    pylib_dir = tmp_path / "pylib"
    pylib_dir.mkdir(exist_ok=True)
    (pylib_dir / "psycopg.py").write_text(_FAKE_PSYCOPG_MODULE, encoding="utf-8")
    # `import psycopg` must resolve to the fake; `import app.release_channels...`
    # must resolve to the REAL, unmodified module. A symlink to just the `app`
    # package (not the whole REPO_ROOT) on PYTHONPATH: REPO_ROOT itself carries
    # its own sitecustomize.py (runtime instrumentation, unrelated to this
    # test), and PYTHONPATH-ing REPO_ROOT directly makes Python's site
    # machinery import THAT sitecustomize.py instead of Homebrew's own --
    # which is what actually wires this interpreter's real site-packages
    # (PyYAML included) onto sys.path, breaking every third-party import
    # process-wide. Symlinking only `app/` sidesteps that entirely.
    if not (pylib_dir / "app").exists():
        (pylib_dir / "app").symlink_to(REPO_ROOT / "app")
    env["PYTHONPATH"] = str(pylib_dir)

    # H3 (#3903 round 6): always-on connect-attempt log so a test can assert
    # the EXACT host:port a connect() call received, not just "not poison".
    env["FAKE_OUTBOX_CONNECT_LOG"] = str(tmp_path / "outbox-connect.log")

    env.pop("DATABASE_URL", None)
    env.pop("DB_DSN", None)
    if dsn_override is not None:
        env["DATABASE_URL"] = dsn_override

    if unreachable:
        env["FAKE_OUTBOX_DB_UNREACHABLE"] = "1"
        env.pop("FAKE_OUTBOX_ROWS_JSON", None)
    else:
        env.pop("FAKE_OUTBOX_DB_UNREACHABLE", None)
        env["FAKE_OUTBOX_ROWS_JSON"] = json.dumps(list(rows or []))


def test_deploy_preflights_companion_browser_before_pin_or_compose_mutation(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_PLAYWRIGHT_PREFLIGHT"] = "fail"

    result = _run_deploy(root, env, sha)

    assert result.returncode != 0
    assert "companion UI preflight failed before channel mutation" in result.stderr
    assert not (root / "config/deploy/dev.env").exists()
    assert not (tmp_path / "docker-called").exists()


@pytest.mark.parametrize(
    "fake_mode",
    [
        # pytest missing / live-smoke module import failure (nonzero, not 5)
        "fail",
        # emptied-but-importable smoke module: exit 5 with no SKIPPED marker
        "empty",
    ],
)
def test_deploy_preflights_companion_pytest_smoke_before_pin_or_compose_mutation(
    tmp_path: Path, fake_mode: str
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_PYTEST_SMOKE_PREFLIGHT"] = fake_mode

    result = _run_deploy(root, env, sha)

    assert result.returncode != 0
    assert "companion UI pytest smoke preflight" in result.stderr
    assert not (root / "config/deploy/dev.env").exists()
    assert not (tmp_path / "docker-called").exists()


def test_deploy_receipt_records_embedding_cutover_acknowledgement(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)

    default_result = _run_deploy(root, env, sha)
    assert default_result.returncode == 0, default_result.stdout + default_result.stderr
    receipt_path = root / "ops/deployments/dev-latest.json"
    default_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert default_receipt["embedding_rebuild_required_acknowledged"] is False

    acknowledged_result = _run_deploy(
        root,
        env,
        sha,
        "--ack-embedding-rebuild-required",
    )
    assert acknowledged_result.returncode == 0, (
        acknowledged_result.stdout + acknowledged_result.stderr
    )
    acknowledged_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert acknowledged_receipt["embedding_rebuild_required_acknowledged"] is True


def _deploy_events(env: dict[str, str]) -> list[str]:
    return Path(env["FAKE_DEPLOY_EVENT_LOG"]).read_text(encoding="utf-8").splitlines()


def test_acknowledged_embedding_cutover_stages_compose_before_transition_smoke(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    runtime_up = next(
        index
        for index, event in enumerate(events)
        if event.endswith("up -d --force-recreate api worker watcher heimdal-capture-watch")
    )
    api_liveness = next(
        index
        for index, event in enumerate(events)
        if event.startswith("curl ") and "/healthz" in event
    )
    gateway_up = next(
        index
        for index, event in enumerate(events)
        if event.endswith("up -d --force-recreate --no-deps companion-ui")
    )
    assert runtime_up < api_liveness < gateway_up
    assert not any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )


def test_unacknowledged_deploy_keeps_strict_compose_startup(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    assert any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )
    assert not any("--no-deps companion-ui" in event for event in events)


def test_acknowledged_embedding_cutover_liveness_failure_rolls_back_candidate(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "1" * 40
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    env["FAKE_API_LIVENESS"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert "service recreate/liveness gate failed" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert any(
        event.endswith("up -d --force-recreate api worker watcher heimdal-capture-watch")
        for event in events
    )
    assert any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )


def test_acknowledged_embedding_cutover_gateway_failure_rolls_back_candidate(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "2" * 40
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    env["FAKE_DOCKER_FAIL_MATCH"] = "up -d --force-recreate --no-deps companion-ui"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 24
    assert "service recreate/liveness gate failed" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert any("--no-deps companion-ui" in event for event in events)
    assert any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )


def test_forward_only_migration_failure_retains_compatible_target_image(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_test.py"
    migration.write_text(
        'revision = "forward_only_test"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add forward-only migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_API_LIVENESS"] = "fail"

    result = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert result.returncode == 1
    assert "target pin is retained for a compatible forward fix" in result.stderr
    assert f"APP_IMAGE_TAG={target_sha}" in pin_path.read_text(encoding="utf-8")
    strict_recreates = [
        event
        for event in _deploy_events(env)
        if event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
    ]
    assert len(strict_recreates) == 1


def test_forward_only_pull_failure_restores_previous_pin_before_migration(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_test.py"
    migration.write_text(
        'revision = "forward_only_test"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add forward-only migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_DOCKER_FAIL_MATCH"] = "pull api worker"

    result = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert result.returncode == 24
    assert "attempting rollback to previous pin" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert not any(" stop api worker watcher" in event for event in events)
    assert not any("exit-code-from migrate" in event for event in events)


def test_target_commit_migration_is_classified_when_target_is_not_checked_out(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    migration = root / "app/alembic/versions/target_only.py"
    migration.write_text(
        'revision = "target_only"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add target-only migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    subprocess.run(["git", "checkout", "-q", previous_sha], cwd=root, check=True)

    result = _run_deploy(root, env, target_sha)

    assert result.returncode == 42
    assert "forward-only migrations require" in result.stderr
    assert "migration gate blocked before recreate" in result.stderr
    assert not (tmp_path / "docker-called").exists()


def test_migration_materialization_failure_blocks_before_pin_or_compose(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/materialization_failure.py"
    migration.write_text(
        'revision = "materialization_failure"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add failing materialization"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    subprocess.run(["git", "checkout", "-q", previous_sha], cwd=root, check=True)
    env["FAKE_GIT_FAIL_MATCH"] = f"show {target_sha}:app/alembic/versions/"

    result = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert result.returncode == 87
    assert "fake git materialization failure" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    assert not (tmp_path / "docker-called").exists()


def test_ambiguous_forward_only_migration_exit_retains_target_pin(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_test.py"
    migration.write_text(
        'revision = "forward_only_test"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add forward-only migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_DOCKER_FAIL_MATCH"] = "exit-code-from migrate"

    result = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert result.returncode == 24
    assert "commit state is ambiguous" in result.stderr
    assert f"APP_IMAGE_TAG={target_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert any("exit-code-from migrate" in event for event in events)
    assert not any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )


def test_same_sha_retry_replays_durable_pending_migration_epoch(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_retry.py"
    migration.write_text(
        'revision = "forward_only_retry"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add retry migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = target_sha
    env["FAKE_DOCKER_FAIL_MATCH"] = "exit-code-from migrate"

    first = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert first.returncode == 24
    pending = root / "config/deploy/dev.migration-pending.env"
    assert pending.exists()
    assert f"FROM_SHA={previous_sha}" in pending.read_text(encoding="utf-8")
    assert f"TARGET_SHA={target_sha}" in pending.read_text(encoding="utf-8")

    env.pop("FAKE_DOCKER_FAIL_MATCH")
    second = _run_deploy(root, env, target_sha)

    assert second.returncode == 0, second.stdout + second.stderr
    assert "migration retry: revalidating" in second.stdout
    assert not pending.exists()
    migrate_events = [event for event in _deploy_events(env) if "exit-code-from migrate" in event]
    assert len(migrate_events) == 2


def test_first_deploy_retry_replays_full_target_migration_inventory(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    migration = root / "app/alembic/versions/first_deploy_retry.py"
    migration.write_text(
        'revision = "first_deploy_retry"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add first-deploy migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = target_sha
    env["FAKE_DOCKER_FAIL_MATCH"] = "exit-code-from migrate"

    first = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert first.returncode == 24
    pending = root / "config/deploy/dev.migration-pending.env"
    assert "FROM_SHA=__NO_BASELINE__" in pending.read_text(encoding="utf-8")
    assert f"TARGET_SHA={target_sha}" in pending.read_text(encoding="utf-8")

    env.pop("FAKE_DOCKER_FAIL_MATCH")
    second = _run_deploy(root, env, target_sha)

    assert second.returncode == 0, second.stdout + second.stderr
    assert "migration retry: revalidating <no-baseline>" in second.stdout
    assert not pending.exists()
    migrate_events = [event for event in _deploy_events(env) if "exit-code-from migrate" in event]
    assert len(migrate_events) == 2


def test_first_deploy_pull_failure_preserves_no_baseline_retry_epoch(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    migration = root / "app/alembic/versions/first_deploy_pull_retry.py"
    migration.write_text(
        'revision = "first_deploy_pull_retry"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add first-deploy pull retry"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = target_sha
    env["FAKE_DOCKER_FAIL_MATCH"] = "pull api worker"

    first = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert first.returncode == 24
    pending = root / "config/deploy/dev.migration-pending.env"
    assert "FROM_SHA=__NO_BASELINE__" in pending.read_text(encoding="utf-8")
    pin_path = root / "config/deploy/dev.env"
    assert f"APP_IMAGE_TAG={target_sha}" in pin_path.read_text(encoding="utf-8")

    env.pop("FAKE_DOCKER_FAIL_MATCH")
    second = _run_deploy(root, env, target_sha)

    assert second.returncode == 0, second.stdout + second.stderr
    assert "migration retry: revalidating <no-baseline>" in second.stdout
    assert not pending.exists()
    migrate_events = [event for event in _deploy_events(env) if "exit-code-from migrate" in event]
    assert len(migrate_events) == 1


def test_pin_restore_failure_preserves_pending_migration_retry_epoch(tmp_path: Path) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/pin_restore_retry.py"
    migration.write_text(
        'revision = "pin_restore_retry"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add pin-restore retry"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = target_sha
    env["FAKE_DOCKER_FAIL_MATCH"] = "pull api worker"
    env["FAKE_MV_FAIL_MATCH"] = "config/deploy/dev.env"
    env["FAKE_MV_FAIL_ON_COUNT"] = "2"
    env["FAKE_MV_COUNTER_FILE"] = str(tmp_path / "mv-counter")

    first = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert first.returncode == 24
    assert "rollback pin restore failed" in first.stderr
    pending = root / "config/deploy/dev.migration-pending.env"
    assert pending.exists()
    assert f"FROM_SHA={previous_sha}" in pending.read_text(encoding="utf-8")
    assert f"APP_IMAGE_TAG={target_sha}" in pin_path.read_text(encoding="utf-8")

    for key in ("FAKE_DOCKER_FAIL_MATCH", "FAKE_MV_FAIL_MATCH", "FAKE_MV_FAIL_ON_COUNT"):
        env.pop(key)
    second = _run_deploy(root, env, target_sha)

    assert second.returncode == 0, second.stdout + second.stderr
    assert "migration retry: revalidating" in second.stdout
    assert not pending.exists()
    migrate_events = [event for event in _deploy_events(env) if "exit-code-from migrate" in event]
    assert len(migrate_events) == 1


def test_applied_reversible_migration_retains_target_for_governed_reversal(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/reversible_test.py"
    migration.write_text(
        'revision = "reversible_test"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "reversible"\n'
        "def downgrade():\n    pass\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add reversible migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = target_sha
    env["FAKE_POSTDEPLOY_SMOKE"] = "fail"

    result = _run_deploy(root, env, target_sha)

    assert result.returncode == 73
    assert "reversible migration(s) were applied" in result.stderr
    assert "rollback-promotion" in result.stderr
    assert f"APP_IMAGE_TAG={target_sha}" in pin_path.read_text(encoding="utf-8")
    assert f"APP_IMAGE_TAG={previous_sha}" not in pin_path.read_text(encoding="utf-8")
    strict_recreates = [
        event
        for event in _deploy_events(env)
        if event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
    ]
    assert len(strict_recreates) == 1


def test_changed_migration_drains_writers_before_cutover_and_runtime_restart(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_test.py"
    migration.write_text(
        'revision = "forward_only_test"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add forward-only migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = target_sha

    result = _run_deploy(root, env, target_sha, "--ack-forward-only")

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    stop_index = next(i for i, event in enumerate(events) if " stop api worker watcher" in event)
    migrate_index = next(i for i, event in enumerate(events) if "exit-code-from migrate" in event)
    runtime_index = next(
        i
        for i, event in enumerate(events)
        if event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
    )
    assert stop_index < migrate_index < runtime_index


def test_prod_deploy_blocks_pending_retry_exhaustion_before_pin_or_compose_mutation(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    # Dispatch-attempt mechanism at the corrected terminal boundary: the
    # worker bumps attempts then dead-letters+acks in the same cycle, so a
    # PENDING row tops out at attempts == max - 1 (4 with the default budget
    # of 5) -- and that IS the state whose next non-transient failure
    # dead-letters. attempts == 5 is only observable in a crash window.
    # No dsn_override: exercises the real docker-compose.prod.yml literal
    # default, host-translated -- the normal-case resolution path.
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[("panel.scan.requested", {}, 4)],
    )

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode != 0
    assert "prod pending-retry preflight: blocked terminal_pending_count=1" in result.stdout
    assert "skipped:no_dsn" not in result.stdout
    assert "skipped:db_unreachable" not in result.stdout
    assert "terminal retry boundary" in result.stderr
    # No pin mutation: the pin file is never created/written before the block.
    assert not (root / "config/deploy/prod.env").exists()
    assert not (root / "config/deploy/prod.previous.env").exists()
    assert not (tmp_path / "docker-called").exists()
    # H3 (#3903 round 6): assert the EXACT host:port the fake DB layer
    # received, not just "not the poison string" -- the real-compose-path
    # resolution must actually translate to the pinned host-published port.
    connect_log = (tmp_path / "outbox-connect.log").read_text(encoding="utf-8")
    assert f"127.0.0.1:{_PROD_DB_HOST_PUBLISHED_PORT}" in connect_log
    assert "@db:5432" not in connect_log


def test_prod_deploy_pending_retry_preflight_uses_compose_environment_not_env_file(
    tmp_path: Path,
) -> None:
    """Regression test for #3903 round 4: `environment:` always wins over
    `env_file:` for the same key, and docker-compose.prod.yml sets
    DATABASE_URL/DB_DSN directly in `environment:` for every channel-critical
    service. Rounds 2 and 3 read a pin-file-referenced (or compose-default)
    runtime env file directly for those keys -- but the real containers never
    actually consult that file for DATABASE_URL/DB_DSN, because the explicit
    `environment:` binding always supersedes it. A preflight that reads the
    file anyway can silently evaluate an entirely different database's
    outbox state.

    Setup: the file at every location earlier rounds would have read (the
    pin-file-referenced runtime env AND the compose-default ./tmp/runtime.env)
    carries a DIFFERENT DSN that the fake DB layer refuses to connect to. The
    deploy must still block using the compose environment:-resolved value
    (the real literal default, host-translated) -- never touching either
    file's DSN.
    """
    root, env, sha = _deploy_harness(tmp_path)
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[("panel.scan.requested", {}, 4)],
    )

    # Populate every file location rounds 2/3's bash-level resolution would
    # have read -- present, DSN-bearing, and must have zero effect now that
    # resolution goes through channel_isolation_preflight instead.
    (root / "config/deploy/prod.env").write_text(
        "WATCHER_RUNTIME_ENV_FILE=./runtime-prod.env\n", encoding="utf-8"
    )
    (root / "runtime-prod.env").write_text(
        f"DATABASE_URL={_ENV_FILE_POISON_DSN}\n", encoding="utf-8"
    )
    (root / "tmp").mkdir(exist_ok=True)
    (root / "tmp/runtime.env").write_text(
        f"DATABASE_URL={_ENV_FILE_POISON_DSN}\n", encoding="utf-8"
    )
    env["FAKE_OUTBOX_POISON_DSN"] = _ENV_FILE_POISON_DSN

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode != 0
    assert "prod pending-retry preflight: blocked terminal_pending_count=1" in result.stdout
    assert "skipped:db_unreachable" not in result.stdout
    assert "skipped:no_dsn" not in result.stdout


def test_prod_deploy_pending_retry_preflight_ignores_ambient_runtime_env_file(
    tmp_path: Path,
) -> None:
    """Regression test for #3903 round 3: an earlier revision fell back to an
    exported shell WATCHER_RUNTIME_ENV_FILE when the pin file lacked the key.
    The real deploy path never does this -- scripts/lib's compose helper
    resolves that variable from the pin file or its governed channel default
    (`./tmp/runtime.env` for PROD), never from the ambient shell. Round 4
    removed the whole DSN file-reading mechanism this bug lived in, but an
    ambient WATCHER_RUNTIME_ENV_FILE pointing at a poisoned DSN must still
    have no effect -- the current resolution path does not consult that
    variable at all (docker-compose.prod.yml's explicit `environment:`
    binding short-circuits before any env_file chain is examined).
    """
    root, env, sha = _deploy_harness(tmp_path)
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[("panel.scan.requested", {}, 4)],
    )

    ambient_env_file = tmp_path / "ambient-foreign-runtime.env"
    ambient_env_file.write_text(f"DATABASE_URL={_ENV_FILE_POISON_DSN}\n", encoding="utf-8")
    env["WATCHER_RUNTIME_ENV_FILE"] = str(ambient_env_file)
    env["FAKE_OUTBOX_POISON_DSN"] = _ENV_FILE_POISON_DSN

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode != 0
    assert "prod pending-retry preflight: blocked terminal_pending_count=1" in result.stdout
    assert "skipped:db_unreachable" not in result.stdout
    assert "skipped:no_dsn" not in result.stdout


def test_prod_deploy_pending_retry_preflight_honors_pin_file_dsn_override(
    tmp_path: Path,
) -> None:
    """H1 (#3903 round 6): the real prod deploy passes config/deploy/prod.env
    to Compose as --env-file (scripts/lib/deploy_channel_compose.sh:76) -- a
    genuine interpolation source for docker-compose.prod.yml's own
    ${DATABASE_URL:-default} expression, separate from (and layered under)
    the ambient shell environment. Committed pin files carry only
    APP_IMAGE_* keys today, but nothing prevents an operator adding
    DATABASE_URL/DB_DSN there directly (write_pin() only strips APP_IMAGE_*
    keys on rewrite, preserving every other key -- the same mechanism
    WATCHER_RUNTIME_ENV_FILE/VAULT_HOST_ROOT already use to persist there).
    If that ever happens, the real deploy honors it (--env-file wins over
    the compose file's own literal default); this preflight must resolve
    identically, or it would silently keep checking the compose file's own
    default DSN instead -- the same wrong-database bug class rounds 1-4
    fixed, reopened one layer deeper.
    """
    root, env, sha = _deploy_harness(tmp_path)
    pin_dsn = "postgresql+psycopg://app:app@pin-file-designated-host:5432/app"
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[("panel.scan.requested", {}, 4)],
        pin_file_dsn_override=pin_dsn,
    )
    # Poison the compose file's OWN literal default, host-translated: if the
    # preflight ever regresses to ignoring the pin file's --env-file
    # contribution, it resolves and connects to THIS instead, and the fake
    # DB layer refuses it -- rc 0 / skipped:db_unreachable, not blocked.
    env["FAKE_OUTBOX_POISON_DSN"] = (
        f"postgresql+psycopg://app:app@127.0.0.1:{_PROD_DB_HOST_PUBLISHED_PORT}/app"
    )

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode != 0
    assert "prod pending-retry preflight: blocked terminal_pending_count=1" in result.stdout
    assert "skipped:db_unreachable" not in result.stdout
    assert "skipped:no_dsn" not in result.stdout
    connect_log = (tmp_path / "outbox-connect.log").read_text(encoding="utf-8")
    assert "pin-file-designated-host" in connect_log


def test_prod_deploy_pending_retry_preflight_ambient_env_wins_over_pin_file(
    tmp_path: Path,
) -> None:
    """Companion to the pin-file-override test above: Compose's own
    precedence is ambient shell wins over --env-file. An operator-added pin
    file DSN and an ambient shell DSN present together must resolve to the
    ambient value, exactly as the real `docker compose` invocation would."""
    root, env, sha = _deploy_harness(tmp_path)
    pin_dsn = "postgresql+psycopg://app:app@pin-file-should-lose:5432/app"
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[("panel.scan.requested", {}, 4)],
        pin_file_dsn_override=pin_dsn,
        dsn_override="postgresql+psycopg://app:app@ambient-should-win:5432/app",
    )
    env["FAKE_OUTBOX_POISON_DSN"] = pin_dsn

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode != 0
    assert "prod pending-retry preflight: blocked terminal_pending_count=1" in result.stdout
    assert "skipped:db_unreachable" not in result.stdout
    connect_log = (tmp_path / "outbox-connect.log").read_text(encoding="utf-8")
    assert "ambient-should-win" in connect_log
    assert "pin-file-should-lose" not in connect_log


def test_prod_deploy_pending_retry_preflight_is_redacted(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    # Worker-retry mechanism, in the REAL writer shape: write_outbox_event
    # stores the Event ENVELOPE, so _worker_retry_count sits nested at
    # payload->'payload' (the #3124 rows looked exactly like this). The
    # secrets live in the nested payload; the DSN (with credentials) comes
    # from an ambient override -- none of it may reach output.
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[
            (
                "panel.scan.requested",
                {
                    "event_type": "panel.scan.requested",
                    "event_id": "e" * 32,
                    "trace_id": "trace-should-not-leak",
                    "payload": {
                        "_worker_retry_count": 3,
                        "note_path": "/private/secret/vault/Some Secret Note.md",
                        "text": "the quick brown fox jumped over some secret content",
                    },
                },
                0,
            )
        ],
        dsn_override=_FAKE_PROD_DSN,
    )

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Some Secret Note" not in combined
    assert "/private/secret/vault" not in combined
    assert "sup3rsecret" not in combined
    assert "prod-db.internal" not in combined
    assert "produser" not in combined
    assert "trace-should-not-leak" not in combined
    assert "quick brown fox" not in combined
    assert "terminal_pending_count" in combined
    assert "panel.scan.requested" in combined


def test_prod_deploy_allows_nonterminal_pending_outbox_work(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[
            # Worker-retry counter below the budget (flat legacy shape).
            ("panel.scan.requested", {"_worker_retry_count": 1}, 0),
            # Ordinary healthy pending work.
            ("ingest.vault_changed", {}, 2),
            # Dispatch-attempt negative boundary: attempts == max - 2 (3) is
            # NOT terminal -- the row still has a whole retry cycle left. Only
            # attempts >= max - 1 (4) blocks (see the blocks-test).
            ("panel.scan.requested", {}, 3),
        ],
    )

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "prod pending-retry preflight: ok" in result.stdout
    assert "APP_IMAGE_TAG" in (root / "config/deploy/prod.env").read_text(encoding="utf-8")
    assert (tmp_path / "docker-called").exists()


def test_prod_deploy_pending_retry_preflight_fails_open_when_db_unreachable(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    _configure_prod_retry_preflight(root, env, tmp_path, unreachable=True)

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    # Fail-open must be VISIBLE, never silent: a skip line is emitted so a
    # skipped safety gate can never masquerade as a pass in the deploy log.
    assert "prod pending-retry preflight: skipped:db_unreachable" in result.stdout
    assert (tmp_path / "docker-called").exists()


def test_prod_deploy_pending_retry_preflight_fails_open_without_dsn(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    # No compose files at all: resolution is impossible (not merely "a file
    # was empty"), so the preflight must skip visibly rather than block or
    # crash.
    _configure_prod_retry_preflight(root, env, tmp_path, compose_files_present=False)

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "prod pending-retry preflight: skipped:no_dsn" in result.stdout
    assert (tmp_path / "docker-called").exists()


# ---------------------------------------------------------------------------
# Dev/test environment:-vs-env_file: clobber preflight (Issue #4230)
# ---------------------------------------------------------------------------

#: Reproduces the pre-f95a6811 heimdal-capture-watch shape: an
#: `environment:` entry interpolating from an unset shell variable shadows
#: the real value the same key would otherwise receive from the env_file
#: chain.
_HEIMDAL_CLOBBER_OVERLAY = """\
services:
  heimdal-capture-watch:
    env_file:
      - path: ${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
    environment:
      HEIMDAL_CAPTURE_WATCH_DIR: ${HEIMDAL_CAPTURE_WATCH_DIR:-}
"""

#: The fixed shape (commit f95a6811): no `environment:` override at all for
#: the host-specific key -- it rides the env_file chain untouched.
_HEIMDAL_FIXED_OVERLAY = """\
services:
  heimdal-capture-watch:
    env_file:
      - path: ${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
"""


def _configure_dev_test_environment_clobber_preflight(
    root: Path,
    env: dict[str, str],
    tmp_path: Path,
    *,
    channel: str,
    overlay_content: str,
) -> None:
    """Copy the real checker module into the fixture repo and write a
    synthetic compose overlay reproducing (or not) the heimdal-capture-watch
    clobber shape, so the real, unmodified
    app.release_channels.channel_isolation_preflight resolves it exactly as
    the production deploy path would.
    """
    overlay_filename = "docker-compose.dev.yml" if channel == "dev" else "docker-compose.test.yml"
    dest = root / "app" / "release_channels" / "channel_isolation_preflight.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "app/release_channels/channel_isolation_preflight.py", dest
    )
    (root / overlay_filename).write_text(overlay_content, encoding="utf-8")
    # The overlay's env_file chain merges with the base compose's -- absent a
    # base docker-compose.yaml here, check_environment_env_file_clobber models
    # the base layer as this single required file (Issue #1655's contract);
    # it must exist (even empty) or the whole chain is unverifiable and the
    # check would skip rather than detect the clobber.
    (root / "config").mkdir(exist_ok=True)
    (root / "config/runtime.defaults.env").write_text("", encoding="utf-8")
    runtime_dir = root / ("tmp-test" if channel == "test" else "tmp")
    runtime_dir.mkdir(exist_ok=True)
    (runtime_dir / "runtime.env").write_text(
        "HEIMDAL_CAPTURE_WATCH_DIR=/real/capture/dir\n", encoding="utf-8"
    )
    # Ambient interpolation sources this preflight must resolve against must
    # match what the real Compose invocation would see -- neither key is
    # ever set by deploy_channel_compose.sh (#3875), so a stray host export
    # must not leak into the subprocess and mask the clobber.
    env.pop("HEIMDAL_CAPTURE_WATCH_DIR", None)
    env.pop("WATCHER_RUNTIME_ENV_FILE", None)


def test_dev_deploy_preflight_rejects_environment_override_clobbering_env_file(
    tmp_path: Path,
) -> None:
    """AC1 (#4230): a dev-channel deploy fails loud, before pin write or
    migration execution, when a CHANNEL_SERVICES service's `environment:`
    override resolves blank while its env_file chain supplies a non-empty
    value for the same key -- the exact shape that crash-looped
    heimdal-capture-watch on every dev-channel deploy before commit
    f95a6811 deleted the offending `environment:` entries.
    """
    root, env, sha = _deploy_harness(tmp_path)
    _configure_dev_test_environment_clobber_preflight(
        root, env, tmp_path, channel="dev", overlay_content=_HEIMDAL_CLOBBER_OVERLAY
    )

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode != 0
    assert "dev/test environment clobber preflight: blocked violation_count=1" in result.stdout
    assert "heimdal-capture-watch" in result.stderr
    assert "HEIMDAL_CAPTURE_WATCH_DIR" in result.stderr
    # No pin mutation: the pin file is never created/written before the block.
    assert not (root / "config/deploy/dev.env").exists()
    assert not (root / "config/deploy/dev.previous.env").exists()
    assert not (tmp_path / "docker-called").exists()


def test_dev_deploy_preflight_passes_fixed_shape(tmp_path: Path) -> None:
    """The post-f95a6811 shape (no blank `environment:` override) must not
    be blocked -- a regression here would make every ordinary dev deploy
    fail."""
    root, env, sha = _deploy_harness(tmp_path)
    _configure_dev_test_environment_clobber_preflight(
        root, env, tmp_path, channel="dev", overlay_content=_HEIMDAL_FIXED_OVERLAY
    )

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "dev/test environment clobber preflight: ok" in result.stdout


def test_test_channel_deploy_preflight_rejects_environment_override_clobbering_env_file(
    tmp_path: Path,
) -> None:
    """The deploy path checks the wrapper-derived ``tmp-test`` env file."""
    root, env, sha = _deploy_harness(tmp_path)
    _configure_dev_test_environment_clobber_preflight(
        root, env, tmp_path, channel="test", overlay_content=_HEIMDAL_CLOBBER_OVERLAY
    )

    result = _run_deploy(root, env, sha, channel="test")

    assert result.returncode != 0
    assert "dev/test environment clobber preflight: blocked violation_count=1" in result.stdout
    assert not (root / "config/deploy/test.env").exists()
    assert not (tmp_path / "docker-called").exists()
