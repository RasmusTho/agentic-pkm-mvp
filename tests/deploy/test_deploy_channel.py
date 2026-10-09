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
elif command == "redact-compose-fence-config":
    output = Path(_value("--output"))
    output.write_text(
        '''services:
  api: {depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: client}}
  db: {depends_on: [], labels: {com.agentic-pkm.mvr05.db-role: server}}
  heimdal-capture-watch: {depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: client}}
  instance-state-init: {depends_on: [], labels: {com.agentic-pkm.mvr05.db-role: fence-controller}}
  migrate:
    command: [/app/scripts/run_migrations.sh]
    depends_on: [db]
    labels: {com.agentic-pkm.mvr05.db-role: migration-runner}
  watcher: {depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: client}}
  worker: {depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: client}}
''',
        encoding="utf-8",
    )
elif command == "compose-fence-plan":
    receipt = Path(_value("--receipt-output"))
    receipt.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.mvr05-cutover-fence.v1",
                "db_clients": ["api", "heimdal-capture-watch", "migrate", "watcher", "worker"],
                "migration_runner": "migrate",
                "stopped_services": ["api", "heimdal-capture-watch", "watcher", "worker"],
                "source_sha256": "0" * 64,
            },
            sort_keys=True,
        )
        + "\\n",
        encoding="utf-8",
    )
    print("api heimdal-capture-watch watcher worker")
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
    (root / "tmp/runtime.env").write_text(
        f"LOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\n"
        "TTS_ENABLED=false\nHEIMDAL_CAPTURE_WATCH_DIR=/fixture/capture-inbox\n",
        encoding="utf-8",
    )
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
        "app/ops/bws_secret_reader.py",
        "app/ops/host_secret_controller.py",
        "app/ops/host_secret_bootstrap.py",
        "config/secrets/host_secret_contract.json",
        "scripts/deploy_channel.sh",
        "scripts/compose_env.py",
        "scripts/companion_ui_postdeploy_smoke.sh",
        "scripts/dev_test_environment_clobber_preflight.py",
        "scripts/prod_devui_gateway_preflight.py",
        "scripts/lib/deploy_channel_compose.sh",
        "scripts/lib/heimdal_cold_volume_preflight.sh",
        "scripts/lib/instance_state_deployment.sh",
        "scripts/lib/instance_ownership_host_state.sh",
        "scripts/lib/signboard_root.sh",
        "scripts/instance_state_writer_inventory.py",
    ):
        destination = root / relative
        shutil.copy2(REPO_ROOT / relative, destination)
    shutil.copy2(
        REPO_ROOT / "docker-compose.prod.yml",
        root / "docker-compose.prod.yml",
    )
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
    (root / "app/instance/mvr05_cutover.py").write_text(
        '"""Fixture marker for an MVR-05 floor-capable target."""\n',
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
            "app/instance/mvr05_cutover.py",
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
if [ "${{FAKE_CAPTURE_RUNTIME_IDENTITY:-0}}" = "1" ] && [[ "$*" == compose* ]]; then
  printf 'compose identity uid=%s gid=%s cmd=%s\\n' \
    "${{LOCAL_UID:-unset}}" "${{LOCAL_GID:-unset}}" "$*" \
    >> "${{FAKE_DEPLOY_EVENT_LOG:?}}"
fi
if [ -n "${{FAKE_DOCKER_FAIL_MATCH:-}}" ] && [[ "$*" == *"${{FAKE_DOCKER_FAIL_MATCH}}"* ]]; then
  exit 24
fi
case "$*" in
  *"run --rm --no-deps -T -e MIGRATION_GATE_TOKEN_ONLY=1 migrate"*)
    probe_selector=1
    printf 'migration-token-probe selector=%s ack=%s\\n' \
      "${{probe_selector}}" \
      "${{PROD_MIGRATION_FORWARD_ONLY_ACK:-}}" \
      >> "${{FAKE_DEPLOY_EVENT_LOG:?}}"
    if [ "${{probe_selector}}" = "1" ]; then
      printf '%s\\n' "${{FAKE_MIGRATION_GATE_TOKEN:-prod-migration-ack.v1:0000000000000000000000000000000000000000000000000000000000000000}}"
      if [ -n "${{FAKE_MIGRATION_GATE_EXTRA_OUTPUT:-}}" ]; then
        printf '%s\\n' "${{FAKE_MIGRATION_GATE_EXTRA_OUTPUT}}"
      fi
    fi
    ;;
  *"exit-code-from migrate"*)
    printf 'migration-full ack=%s\\n' \
      "${{PROD_MIGRATION_FORWARD_ONLY_ACK:-}}" \
      >> "${{FAKE_DEPLOY_EVENT_LOG:?}}"
    ;;
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
  *"/api/health"*)
    if [ "${FAKE_REQUIRED_HEALTH:-pass}" = "fail" ]; then
      printf '{"ok":false,"required_ok":false,"version":{"git_sha":"%s"},"checks":{"embedding_index":{"ok":false,"required":true,"status":"rebuild_required"}},"runtime":{"api":{"ok":true}}}\\n' "${FAKE_HEALTH_VERSION_SHA:-$FAKE_SHA}"
    else
      printf '{"ok":true,"required_ok":true,"version":{"git_sha":"%s"},"checks":{}}\\n' "${FAKE_HEALTH_VERSION_SHA:-$FAKE_SHA}"
    fi
    ;;
  *"/status"*)
    if [ "${FAKE_PRODUCT_READINESS:-pass}" = "fail" ]; then
      printf '{"state":"running","product_readiness":{"ready":false,"state":"refused","reason":"product projection refused"}}\\n'
    else
      printf '{"state":"running","product_readiness":{"ready":true,"state":"ready","reason":"source-bound Product projection verified"}}\\n'
    fi
    ;;
  *"/readyz"*)
    if [[ "$*" == *"-w"* ]]; then
      if [ "${FAKE_READINESS:-pass}" = "fail" ]; then
        printf '503'
      else
        printf '200'
      fi
      exit 0
    fi
    if [ "${FAKE_READINESS:-pass}" = "fail" ]; then
      exit 22
    fi
    printf '{"ok":true}\\n'
    ;;
  *"/healthz"*)
    if [ "${FAKE_API_LIVENESS:-pass}" = "fail" ]; then
      if [ -n "${FAKE_REMOVE_SETTINGS_REBIND_RECEIPT:-}" ]; then
        rm -f -- "${FAKE_REMOVE_SETTINGS_REBIND_RECEIPT}"
      fi
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
  if [ -n "${{FAKE_FLEET_MODEL_FITNESS_ARGS_FILE:-}}" ]; then
    printf '%s\n' "$@" >"${{FAKE_FLEET_MODEL_FITNESS_ARGS_FILE}}"
  fi
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
            "HOST_SECRET_PROVIDER": "keychain",
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


def _settings_rebind_unsafe_and_safe_heads(root: Path) -> tuple[str, str]:
    """Create an abandoned module-only predecessor and one attested successor."""

    module_path = root / "app/instance/settings_rebind.py"
    module_path.write_text(
        '"""Unsafe predecessor: module presence was not compatibility proof."""\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "app/instance/settings_rebind.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "fixture unsafe settings predecessor"],
        cwd=root,
        check=True,
    )
    unsafe_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()

    shutil.copy2(REPO_ROOT / "app/instance/settings_rebind.py", module_path)
    capability_path = root / "app/instance/settings_rebind_runtime_capability.json"
    shutil.copy2(
        REPO_ROOT / "app/instance/settings_rebind_runtime_capability.json",
        capability_path,
    )
    subprocess.run(
        [
            "git",
            "add",
            "app/instance/settings_rebind.py",
            "app/instance/settings_rebind_runtime_capability.json",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "fixture attested settings runtime"],
        cwd=root,
        check=True,
    )
    safe_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return unsafe_sha, safe_sha


def _prefloor_and_preattestation_floor_heads(
    root: Path,
) -> tuple[str, str]:
    """Materialize a self-contained pre-floor -> pre-attestation transition."""

    runtime_path = root / "app/instance/runtime.py"
    module_path = root / "app/instance/settings_rebind.py"
    capability_path = root / "app/instance/settings_rebind_runtime_capability.json"

    runtime_path.write_text(
        "# Runtime before the dormant settings-rebind installer.\n",
        encoding="utf-8",
    )
    module_path.unlink(missing_ok=True)
    capability_path.unlink(missing_ok=True)
    subprocess.run(
        ["git", "add", "-A", "app/instance"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "fixture pre-floor runtime"],
        cwd=root,
        check=True,
    )
    prefloor_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()

    runtime_path.write_text(
        "# Runtime with settings-rebind-install-dormant support.\n",
        encoding="utf-8",
    )
    module_path.write_text(
        "# Dormant settings-rebind module before capability attestation.\n",
        encoding="utf-8",
    )
    capability_path.unlink(missing_ok=True)
    subprocess.run(
        ["git", "add", "-A", "app/instance"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "commit",
            "-qm",
            "fixture pre-attestation floor runtime",
        ],
        cwd=root,
        check=True,
    )
    floor_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    return prefloor_sha, floor_sha


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


def test_pending_settings_rebind_floor_blocks_older_rollback_before_compose(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    unsafe_sha, safe_sha = _settings_rebind_unsafe_and_safe_heads(root)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={safe_sha}\n",
        encoding="utf-8",
    )
    ownership_root = Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"])
    ownership_root.mkdir(mode=0o700)
    receipt = ownership_root / "settings-rebind-runtime-floor-dev.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.settings-rebind-runtime-floor.v1",
                "channel": "dev",
                "phase": "pending",
                "minimum_settings_rebind_runtime": "1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)

    result = _run_rollback(root, env, unsafe_sha)

    assert result.returncode == 78
    assert "settings rebind floor installation is pending" in result.stderr
    assert not Path(env["FAKE_DEPLOY_EVENT_LOG"]).exists()


def test_installed_settings_floor_routes_module_only_predecessor_to_legacy_guard(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    unsafe_sha, safe_sha = _settings_rebind_unsafe_and_safe_heads(root)
    (root / "config/deploy/dev.env").write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={safe_sha}\n",
        encoding="utf-8",
    )
    ownership_root = Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"])
    ownership_root.mkdir(mode=0o700)
    receipt = ownership_root / "settings-rebind-runtime-floor-dev.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.settings-rebind-runtime-floor.v1",
                "channel": "dev",
                "phase": "installed",
                "minimum_settings_rebind_runtime": "1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)

    result = _run_rollback(root, env, unsafe_sha)

    assert result.returncode == 78
    assert "scalar rollback requires SCALAR_ROLLBACK_VAULT_BINDING_ID" in result.stderr
    assert not Path(env["FAKE_DEPLOY_EVENT_LOG"]).exists()


def test_absent_settings_floor_receipt_blocks_module_only_predecessor(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    unsafe_sha, safe_sha = _settings_rebind_unsafe_and_safe_heads(root)
    (root / "config/deploy/dev.env").write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={safe_sha}\n",
        encoding="utf-8",
    )

    result = _run_rollback(root, env, unsafe_sha)

    assert result.returncode == 78
    assert "settings rebind runtime floor receipt is absent" in result.stderr
    assert not Path(env["FAKE_DEPLOY_EVENT_LOG"]).exists()


def test_absent_receipt_blocks_preattestation_floor_to_prefloor_rollback(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    prefloor_sha, floor_sha = _prefloor_and_preattestation_floor_heads(
        root
    )
    (root / "config/deploy/dev.env").write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={floor_sha}\n",
        encoding="utf-8",
    )

    result = _run_rollback(root, env, prefloor_sha)

    assert result.returncode == 78
    assert "settings rebind runtime floor receipt is absent" in result.stderr
    assert not Path(env["FAKE_DEPLOY_EVENT_LOG"]).exists()


def test_floor_capability_inspection_failure_blocks_manual_transition_rollback(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    prefloor_sha, floor_sha = _prefloor_and_preattestation_floor_heads(
        root
    )
    (root / "config/deploy/dev.env").write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={floor_sha}\n",
        encoding="utf-8",
    )
    env["FAKE_GIT_FAIL_MATCH"] = f"ls-tree -r --name-only {floor_sha}"
    env["FAKE_GIT_FAIL_RC"] = "87"

    result = _run_rollback(root, env, prefloor_sha)

    assert result.returncode == 87
    assert "floor capability inspection failed for current" in result.stderr
    assert not Path(env["FAKE_DEPLOY_EVENT_LOG"]).exists()


def test_malformed_settings_rebind_floor_receipt_blocks_rollback_before_compose(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    (root / "config/deploy/dev.env").write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={sha}\n",
        encoding="utf-8",
    )
    ownership_root = Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"])
    ownership_root.mkdir(mode=0o700)
    receipt = ownership_root / "settings-rebind-runtime-floor-dev.json"
    receipt.write_text("{}\n", encoding="utf-8")
    receipt.chmod(0o600)

    result = _run_rollback(root, env, sha)

    assert result.returncode != 0
    assert "settings rebind runtime floor receipt is invalid" in result.stderr
    assert not Path(env["FAKE_DEPLOY_EVENT_LOG"]).exists()


def test_prod_archive_preflight_precedes_keychain_lookup(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/prod.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={sha}\n",
        encoding="utf-8",
    )
    env["FAKE_ARCHIVE_PREFLIGHT_RC"] = "78"
    env["FAKE_SECURITY_EVENT_LOG"] = env["FAKE_DEPLOY_EVENT_LOG"]

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 78
    assert _deploy_events(env) == ["archive-preflight prod"]


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
        if os.environ.get("FAKE_OUTBOX_QUERY_UNAVAILABLE") == "1":
            raise OperationalError("fake: initial schema unavailable")
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
    expected = os.environ.get("FAKE_OUTBOX_EXPECTED_FIELDS")
    if expected:
        # Use the real libpq parser. The old permissive fake hid unsupported
        # SQLAlchemy URLs, missing file passwords and untranslated query hosts.
        from psycopg.conninfo import conninfo_to_dict
        fields = conninfo_to_dict(dsn)
        if fields != json.loads(expected):
            raise OperationalError("fake: unexpected connection fields")
    # H3 (#3903 round 6): record the exact DSN every call actually received,
    # so a test can assert the real host:port rather than only "not the one
    # poison string" -- a hardcoded host-translation constant drifting from
    # docker-compose.yaml's real port mapping would otherwise still pass
    # every existing assertion here (any non-poison DSN accepted).
    log_path = os.environ.get("FAKE_OUTBOX_CONNECT_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(("validated-file-connection" if expected else dsn) + "\\n")
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


def _configure_bws_retry_driver(tmp_path: Path, env: dict[str, str], *, host: str = "db") -> None:
    """Patch only connect; retain the real psycopg conninfo parser and resolver."""
    import json
    from urllib.parse import urlencode
    pylib = tmp_path / "pylib"
    (pylib / "psycopg.py").unlink()
    # Avoid replacing the interpreter's sitecustomize hook. A tiny explicit
    # launcher imports real psycopg then runs the unchanged preflight script.
    (pylib / "fake_connection.py").write_text(_FAKE_PSYCOPG_MODULE)
    launcher = tmp_path / "bws-python"
    launcher.write_text(
        "#!" + sys.executable + "\n"
        "import os,runpy,sys\n"
        "if not sys.argv[1].endswith('prod_deploy_retry_preflight.py'):\n"
        f"    os.execv({env['PYTHON']!r},[{env['PYTHON']!r},*sys.argv[1:]])\n"
        "import psycopg\n"
        "from fake_connection import connect\n"
        "psycopg.connect=connect\n"
        "sys.argv=sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0],run_name='__main__')\n"
    )
    launcher.chmod(0o755)
    env["PYTHON"] = str(launcher)
    password = tmp_path / "postgres-password"
    password.write_text("fake-preflight-canary")
    password.chmod(0o600)
    fields = {"host": host, "port": "5432", "user": "reporter", "dbname": "custom",
              "sslmode": "require", "application_name": "bws-retry-check"}
    env["DATABASE_URL"] = env["DB_DSN"] = "postgresql+psycopg:///?" + urlencode(fields)
    env["BWS_POSTGRES_PASSWORD_SOURCE"] = str(password)
    env["BWS_DATABASE_TARGET"] = "local" if host == "db" else "external"
    env["COMPOSE_PROFILES"] = ""
    expected = dict(fields, password="fake-preflight-canary")
    if host == "db":
        expected.update(hostaddr="127.0.0.1", port="15432")
    env["FAKE_OUTBOX_EXPECTED_FIELDS"] = json.dumps(expected)


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


@pytest.mark.parametrize(
    "legacy_path",
    [
        "/Users/operator/agentic-pkm/app-local.md",
        "/Volumes/legacy/agentic-pkm/app-local.md",
        "/app/tmp/../tmp/agentic-pkm/app-local.md",
        "/app/tmp/agentic-pkm/legacy/app-local.md",
        "/app/tmp/legacy-link/app-local.md",
    ],
)
def test_deploy_preflights_configured_legacy_settings_before_pin_or_compose_mutation(
    tmp_path: Path, legacy_path: str
) -> None:
    """The effective channel env file cannot hide a legacy host source."""

    root, env, sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_before = (
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={sha}\n"
        f"DESIGN_HANDOFF_APP_LOCAL_SETTINGS={legacy_path}\n"
    )
    pin_path.write_text(pin_before, encoding="utf-8")

    result = _run_deploy(root, env, sha)

    assert result.returncode == 78, result.stdout + result.stderr
    assert "configured DESIGN_HANDOFF_APP_LOCAL_SETTINGS" in result.stderr
    assert legacy_path not in result.stderr
    assert pin_path.read_text(encoding="utf-8") == pin_before
    assert _deploy_events(env) == ["archive-preflight dev"]
    assert not (tmp_path / "docker-called").exists()
    assert not (root / "config/deploy/dev.env.lock").exists()
    assert not (root / "config/deploy/dev.previous.env").exists()
    assert not (root / "config/deploy/dev.migration-pending.env").exists()


def test_deploy_preflights_duplicate_legacy_settings_before_pin_or_compose_mutation(
    tmp_path: Path,
) -> None:
    """A later unsafe duplicate cannot be hidden by an earlier canonical value."""

    root, env, sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_before = (
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={sha}\n"
        "  DESIGN_HANDOFF_APP_LOCAL_SETTINGS=/app/tmp/agentic-pkm/app-local.md\n"
        "\texport DESIGN_HANDOFF_APP_LOCAL_SETTINGS = /Users/operator/agentic-pkm/app-local.md\n"
    )
    pin_path.write_text(pin_before, encoding="utf-8")

    result = _run_deploy(root, env, sha)

    assert result.returncode == 78, result.stdout + result.stderr
    assert "duplicate DESIGN_HANDOFF_APP_LOCAL_SETTINGS" in result.stderr
    assert pin_path.read_text(encoding="utf-8") == pin_before
    assert _deploy_events(env) == ["archive-preflight dev"]
    assert not (tmp_path / "docker-called").exists()
    assert not (root / "config/deploy/dev.env.lock").exists()


def test_deploy_passes_configured_canonical_legacy_settings_to_init(
    tmp_path: Path,
) -> None:
    """A supported channel-file path remains the init CLI value."""

    root, env, sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={sha}\n"
        "export DESIGN_HANDOFF_APP_LOCAL_SETTINGS = /app/tmp/agentic-pkm/app-local.md\n",
        encoding="utf-8",
    )

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    assert any(
        "instance-state-init" in event
        and "--legacy-path /app/tmp/agentic-pkm/app-local.md" in event
        for event in _deploy_events(env)
    )


@pytest.mark.parametrize(
    "assignment",
    [
        "DESIGN_HANDOFF_APP_LOCAL_SETTINGS=/app/tmp/agentic-pkm/app-local.md # canonical",
        'DESIGN_HANDOFF_APP_LOCAL_SETTINGS="/app/tmp/agentic-pkm/app-local.md" # canonical',
    ],
)
def test_deploy_accepts_compose_inline_comment_on_canonical_legacy_settings(
    tmp_path: Path, assignment: str
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={sha}\n"
        f"{assignment}\n",
        encoding="utf-8",
    )

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    assert any(
        "instance-state-init" in event
        and "--legacy-path /app/tmp/agentic-pkm/app-local.md" in event
        for event in _deploy_events(env)
    )


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


def test_acknowledged_embedding_cutover_allows_transitional_health(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_READINESS"] = "fail"
    env["FAKE_REQUIRED_HEALTH"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    assert any("/healthz" in event for event in events)
    assert any("/readyz" in event for event in events)
    assert any("/api/health" in event for event in events)


def test_acknowledged_embedding_cutover_keeps_required_health_strict_when_readyz_is_green(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_READINESS"] = "pass"
    env["FAKE_REQUIRED_HEALTH"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert "health gate failed" in result.stderr
    events = _deploy_events(env)
    assert any("/readyz" in event for event in events)
    assert any("/api/health" in event for event in events)


def test_acknowledged_embedding_cutover_keeps_independent_readiness_failure_blocking(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_READINESS"] = "fail"
    env["FAKE_REQUIRED_HEALTH"] = "fail"
    env["FAKE_PRODUCT_READINESS"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert "health gate failed" in result.stderr
    events = _deploy_events(env)
    assert any("/readyz" in event for event in events)


@pytest.mark.parametrize(
    ("action", "failure_env", "failed_endpoint"),
    [
        ("deploy", "FAKE_READINESS", "/readyz"),
        ("deploy", "FAKE_REQUIRED_HEALTH", "/api/health"),
        ("rollback", "FAKE_READINESS", "/readyz"),
        ("rollback", "FAKE_REQUIRED_HEALTH", "/api/health"),
    ],
)
def test_unacknowledged_deploy_keeps_strict_health_gates_for_deploy_and_rollback(
    tmp_path: Path, action: str, failure_env: str, failed_endpoint: str
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env[failure_env] = "fail"

    if action == "deploy":
        result = _run_deploy(root, env, sha)
    else:
        result = _run_rollback(root, env, sha)

    assert result.returncode == 1
    assert "health gate failed" in result.stderr
    events = _deploy_events(env)
    assert any(failed_endpoint in event for event in events)
    assert any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )
    assert not any("--no-deps companion-ui" in event for event in events)


def test_acknowledged_embedding_cutover_liveness_failure_retains_floored_candidate(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    previous_sha, sha = _settings_rebind_unsafe_and_safe_heads(root)
    env["FAKE_SHA"] = sha
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    env["FAKE_API_LIVENESS"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert "service recreate/liveness gate failed" in result.stderr
    assert f"APP_IMAGE_TAG={sha}" in pin_path.read_text(encoding="utf-8")
    assert "settings rebind floor is installed" in result.stderr
    events = _deploy_events(env)
    assert any(
        event.endswith("up -d --force-recreate api worker watcher heimdal-capture-watch")
        for event in events
    )
    assert not any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )


def test_missing_settings_floor_receipt_never_auto_restarts_module_only_predecessor(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    previous_sha, sha = _settings_rebind_unsafe_and_safe_heads(root)
    env["FAKE_SHA"] = sha
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    receipt = (
        Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"])
        / "settings-rebind-runtime-floor-dev.json"
    )
    env["FAKE_REMOVE_SETTINGS_REBIND_RECEIPT"] = str(receipt)
    env["FAKE_API_LIVENESS"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert not receipt.exists()
    assert "settings rebind floor receipt is absent" in result.stderr
    assert f"APP_IMAGE_TAG={sha}" in pin_path.read_text(encoding="utf-8")
    strict_recreates = [
        event
        for event in _deploy_events(env)
        if event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
    ]
    assert strict_recreates == []


def test_missing_receipt_never_auto_rolls_floor_candidate_back_to_prefloor(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    previous_sha, sha = _prefloor_and_preattestation_floor_heads(root)
    env["FAKE_SHA"] = sha
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    receipt = (
        Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"])
        / "settings-rebind-runtime-floor-dev.json"
    )
    env["FAKE_REMOVE_SETTINGS_REBIND_RECEIPT"] = str(receipt)
    env["FAKE_API_LIVENESS"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert not receipt.exists()
    assert "settings rebind floor receipt is absent" in result.stderr
    assert f"APP_IMAGE_TAG={sha}" in pin_path.read_text(encoding="utf-8")
    assert not any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in _deploy_events(env)
    )


def test_floor_capability_inspection_failure_retains_deploy_candidate(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    previous_sha, sha = _prefloor_and_preattestation_floor_heads(root)
    env["FAKE_SHA"] = sha
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    receipt = (
        Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"])
        / "settings-rebind-runtime-floor-dev.json"
    )
    env["FAKE_REMOVE_SETTINGS_REBIND_RECEIPT"] = str(receipt)
    env["FAKE_API_LIVENESS"] = "fail"
    env["FAKE_GIT_FAIL_MATCH"] = f"ls-tree -r --name-only {sha}"
    env["FAKE_GIT_FAIL_RC"] = "87"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert not receipt.exists()
    assert "floor capability inspection failed for the target (status 87)" in result.stderr
    assert f"APP_IMAGE_TAG={sha}" in pin_path.read_text(encoding="utf-8")
    assert not any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in _deploy_events(env)
    )


def test_acknowledged_embedding_cutover_gateway_failure_retains_floored_candidate(
    tmp_path: Path,
) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    previous_sha, sha = _settings_rebind_unsafe_and_safe_heads(root)
    env["FAKE_SHA"] = sha
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    env["FAKE_DOCKER_FAIL_MATCH"] = "up -d --force-recreate --no-deps companion-ui"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 24
    assert "service recreate/liveness gate failed" in result.stderr
    assert f"APP_IMAGE_TAG={sha}" in pin_path.read_text(encoding="utf-8")
    assert "settings rebind floor is installed" in result.stderr
    events = _deploy_events(env)
    assert any("--no-deps companion-ui" in event for event in events)
    assert not any(
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


def test_prod_forward_only_ack_is_bound_before_writer_stop_and_full_migrate(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/prod.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_prod.py"
    migration.write_text(
        'revision = "forward_only_prod"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add prod forward-only migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    token = "prod-migration-ack.v1:" + "1" * 64
    env.update(
        {
            "FAKE_SHA": target_sha,
            "FAKE_MIGRATION_GATE_TOKEN": token,
            "DEPLOY_ACK_FORWARD_ONLY": "1",
        }
    )
    _configure_prod_retry_preflight(root, env, tmp_path, rows=[])

    result = _run_deploy(root, env, target_sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    probe_index = next(
        index for index, event in enumerate(events) if event.startswith("migration-token-probe ")
    )
    stop_index = next(index for index, event in enumerate(events) if " stop api worker watcher" in event)
    full_index = next(index for index, event in enumerate(events) if event.startswith("migration-full "))
    assert probe_index < stop_index < full_index
    assert "selector=1 ack=" in events[probe_index]
    assert events[full_index] == f"migration-full ack={token}"


def test_prod_forward_only_token_probe_failure_prevents_writer_stop(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/prod.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_probe_failure.py"
    migration.write_text(
        'revision = "forward_only_probe_failure"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add probe failure migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env.update(
        {
            "FAKE_SHA": target_sha,
            "FAKE_MIGRATION_GATE_TOKEN": "not-a-decision-token",
            "DEPLOY_ACK_FORWARD_ONLY": "1",
        }
    )
    _configure_prod_retry_preflight(root, env, tmp_path, rows=[])

    result = _run_deploy(root, env, target_sha, channel="prod")

    assert result.returncode == 78
    assert "invalid decision token before writer stop" in result.stderr
    events = _deploy_events(env)
    assert any(event.startswith("migration-token-probe ") for event in events)
    assert not any(" stop api worker watcher" in event for event in events)
    assert not any(event.startswith("migration-full ") for event in events)
    assert not (root / "config/deploy/prod.migration-pending.env").exists()
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")


def test_prod_forward_only_ambiguous_token_probe_prevents_writer_stop(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/prod.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_ambiguous_probe.py"
    migration.write_text(
        'revision = "forward_only_ambiguous_probe"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "add ambiguous probe migration"], cwd=root, check=True
    )
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env.update(
        {
            "FAKE_SHA": target_sha,
            "FAKE_MIGRATION_GATE_TOKEN": "prod-migration-ack.v1:" + "2" * 64,
            "FAKE_MIGRATION_GATE_EXTRA_OUTPUT": "unexpected second line",
            "DEPLOY_ACK_FORWARD_ONLY": "1",
        }
    )
    _configure_prod_retry_preflight(root, env, tmp_path, rows=[])

    result = _run_deploy(root, env, target_sha, channel="prod")

    assert result.returncode == 78
    assert "ambiguous output before writer stop" in result.stderr
    events = _deploy_events(env)
    assert any(event.startswith("migration-token-probe ") for event in events)
    assert not any(" stop api worker watcher" in event for event in events)
    assert not any(event.startswith("migration-full ") for event in events)
    assert not (root / "config/deploy/prod.migration-pending.env").exists()
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")


def test_prod_forward_only_requires_existing_ack_before_token_probe(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/prod.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    migration = root / "app/alembic/versions/forward_only_requires_ack.py"
    migration.write_text(
        'revision = "forward_only_requires_ack"\n'
        f'down_revision = "{previous_sha[:12]}"\n'
        'reversibility = "forward-only"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add ack-required migration"], cwd=root, check=True)
    target_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = target_sha

    result = _run_deploy(root, env, target_sha, channel="prod")

    assert result.returncode == 42
    assert "forward-only migrations require" in result.stderr
    events = _deploy_events(env)
    assert not any(event.startswith("migration-token-probe ") for event in events)
    assert not any(" stop api worker watcher" in event for event in events)
    assert not (root / "config/deploy/prod.migration-pending.env").exists()
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")


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
    # No compose files at all: the older pending-retry preflight would skip,
    # but production now has an earlier fail-loud gateway-producer invariant.
    # Missing the canonical overlay must block before any mutation.
    _configure_prod_retry_preflight(root, env, tmp_path, compose_files_present=False)
    (root / "docker-compose.prod.yml").unlink()

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 78
    assert "prod devUI gateway preflight: blocked" in result.stderr
    assert not (tmp_path / "docker-called").exists()


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

# Reproduces the retained base-service layout-note shape from the #5364 fix:
# an unset shell interpolation shadows the generated runtime env value.
_LAYOUT_NOTE_CLOBBER_OVERLAY = """\
services:
  api:
    env_file:
      - path: ${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
    environment:
      VAULT_LAYOUT_NOTE_REL: ${VAULT_LAYOUT_NOTE_REL:-}
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
        f"LOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\n"
        "HEIMDAL_CAPTURE_WATCH_DIR=/real/capture/dir\n"
        "VAULT_LAYOUT_NOTE_REL=custom/vault.layout.md\n",
        encoding="utf-8",
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
    """AC2 (#5376): a dev deploy rejects a blank layout-note override before
    pin write or migration execution when the generated runtime env supplies
    the same key.
    """
    root, env, sha = _deploy_harness(tmp_path)
    _configure_dev_test_environment_clobber_preflight(
        root,
        env,
        tmp_path,
        channel="dev",
        overlay_content=_LAYOUT_NOTE_CLOBBER_OVERLAY,
    )

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode != 0
    assert "dev/test environment clobber preflight: blocked violation_count=1" in result.stdout
    assert "api" in result.stderr
    assert "VAULT_LAYOUT_NOTE_REL" in result.stderr
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


def _postgres_entrypoint_fixture(tmp_path, *, initialized=False, root_reexec=False):
    """Execute the real upstream shell branches with fake init/client/server binaries."""
    if subprocess.run(['bash', '-c', 'declare -g _bws_fixture=1'], capture_output=True).returncode:
        pytest.skip('upstream PostgreSQL entrypoint requires Bash 4.2+; hosted Linux CI is the proof route')
    data = tmp_path / 'data'
    data.mkdir()
    if initialized:
        (data / 'PG_VERSION').write_text('16')
    password = tmp_path / 'password'
    password.write_text('fake-file-password-canary')
    upstream = tmp_path / 'docker-entrypoint.sh'
    upstream.write_text((REPO_ROOT / 'tests/fixtures/postgres_entrypoint/docker-entrypoint.sh').read_text() + '''
# Fixture-only filesystem/initialization client seams; server starts stay real shell calls.
docker_create_db_directories() { :; }
docker_init_database_dir() { printf '%s' "$POSTGRES_PASSWORD" > "$PGDATA/role-password"; }
docker_setup_db() { :; }
docker_process_init_files() { :; }
''')
    wrapper = tmp_path / 'wrapper.sh'
    wrapper.write_text((REPO_ROOT / 'scripts/postgres_entrypoint.sh').read_text()
                       .replace('/usr/local/bin/docker-entrypoint.sh', str(upstream))
                       .replace('/usr/local/bin/yggdrasil-postgres-entrypoint.sh', str(wrapper)))
    wrapper.chmod(0o755)
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    for name in ('postgres', 'pg_ctl'):
        program = binaries / name
        program.write_text(f'''#!{sys.executable}
import json,os,sys
if '-C' in sys.argv:
    print('scram-sha-256')
else:
    with open(os.environ['RECORD'], 'a') as f:
        f.write(json.dumps({{'program': {name!r}, 'password': os.environ.get('POSTGRES_PASSWORD'), 'pgpassword': os.environ.get('PGPASSWORD')}})+'\\n')
''')
        program.chmod(0o755)
    _write_executable(binaries / 'id', '#!/bin/bash\nprintf "%s\\n" "${FAKE_UID:-999}"\n')
    _write_executable(binaries / 'ls', '#!/bin/bash\nexit 0\n')
    _write_executable(binaries / 'gosu', '#!/bin/bash\nshift\nexport FAKE_UID=999\nexec "$@"\n')
    record = tmp_path / 'server-env.jsonl'
    env = {'PATH': str(binaries) + ':' + os.environ['PATH'], 'PGDATA': str(data),
           'POSTGRES_PASSWORD_FILE': str(password), 'PGPASSWORD': 'fake-ambient-password-canary',
           'RECORD': str(record), 'FAKE_UID': '0' if root_reexec else '999'}
    return wrapper, data, password, record, env


@pytest.mark.parametrize('root_reexec', [False, True])
def test_postgres_initialization_server_process_environment_omits_password(tmp_path, root_reexec):
    wrapper, data, password, record, env = _postgres_entrypoint_fixture(tmp_path, root_reexec=root_reexec)
    result = subprocess.run(['bash', str(wrapper), 'postgres'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    assert any(row['program'] == 'pg_ctl' for row in rows)
    assert all(row['password'] is None and row['pgpassword'] is None for row in rows)
    assert (data / 'role-password').read_text() == password.read_text()
    assert password.read_text() not in result.stdout + result.stderr
    assert 'fake-ambient-password-canary' not in result.stdout + result.stderr


@pytest.mark.parametrize('initialized,root_reexec', [(False, False), (False, True), (True, False), (True, True)])
def test_postgres_server_process_environment_omits_password(tmp_path, initialized, root_reexec):
    wrapper, _, password, record, env = _postgres_entrypoint_fixture(tmp_path, initialized=initialized, root_reexec=root_reexec)
    result = subprocess.run(['bash', str(wrapper), 'postgres'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    assert rows[-1] == {'program': 'postgres', 'password': None, 'pgpassword': None}
    assert password.read_text() not in result.stdout + result.stderr


def test_initialized_database_role_is_not_changed_by_password_file(tmp_path):
    wrapper, data, password, _, env = _postgres_entrypoint_fixture(tmp_path, initialized=True)
    (data / 'role-password').write_text('already-active-role-canary')
    password.write_text('different-store-canary')
    result = subprocess.run(['bash', str(wrapper), 'postgres'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (data / 'role-password').read_text() == 'already-active-role-canary'
    assert 'different-store-canary' not in result.stdout + result.stderr


def test_initialized_role_authentication_uses_password_file_and_password_auth(tmp_path):
    from types import SimpleNamespace
    from psycopg.conninfo import conninfo_to_dict
    from app.ops.postgres_deploy import PostgresDeployError, password_authenticate
    path = tmp_path / 'password'
    path.write_text('fake-auth-canary')
    env = {'DATABASE_URL': 'postgresql://app@db:5432/app_test', 'DATABASE_PASSWORD_FILE': str(path)}
    calls = []

    class Connection:
        pgconn = SimpleNamespace(used_password=True)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def cursor(self): return self
        def execute(self, sql): calls.append(sql)
        def fetchone(self): return (1,)

    def connect(url, **kwargs):
        assert conninfo_to_dict(url)['password'] == 'fake-auth-canary'
        assert kwargs == {'connect_timeout': 5}
        return Connection()

    password_authenticate(env, connect=connect)
    assert calls == ['SELECT 1']
    Connection.pgconn.used_password = False
    with pytest.raises(PostgresDeployError):
        password_authenticate(env, connect=connect)
    def wrong_password(*args, **kwargs):
        raise RuntimeError('fake-auth-canary')
    with pytest.raises(PostgresDeployError) as failure:
        password_authenticate(env, connect=wrong_password)
    assert 'fake-auth-canary' not in str(failure.value)
    assert set(env) == {'DATABASE_URL', 'DATABASE_PASSWORD_FILE'}


def _render_bws_compose(tmp_path, channel, overrides=None):
    if shutil.which('docker') is None:
        pytest.skip('Docker Compose config parser unavailable; hosted CI must render')
    password = tmp_path / 'password'
    password.write_text('fake-file-canary-not-in-compose')
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('LLM_PROVIDER=mock\n')
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
           'WATCHER_RUNTIME_ENV_FILE': str(runtime),
           'BWS_POSTGRES_PASSWORD_SOURCE': str(password),
           'BWS_DATABASE_NAME': {'dev': 'app_dev', 'test': 'app_test', 'prod': 'app'}[channel],
           'BWS_DATABASE_VOLUME': 'pkm-' + channel + '_fixture',
           'LOCAL_UID': '1000', 'LOCAL_GID': '1000',
           'INSTANCE_OWNERSHIP_HOST_STATE_DIR': str(tmp_path / 'ownership'),
           'LLM_PROVIDER': 'mock'}
    env.update(overrides or {})
    command = ['docker', 'compose', '--env-file', str(REPO_ROOT / 'config/deploy' / (channel + '.env')),
               '-f', str(REPO_ROOT / 'docker-compose.yaml'), '-f', str(REPO_ROOT / ('docker-compose.' + channel + '.yml')),
               '-f', str(REPO_ROOT / 'docker-compose.bws.yml'), '-p', 'pkm-' + channel, 'config', '--format', 'json']
    result = subprocess.run(command, env=env, cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert password.read_text() not in result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('channel', ['dev', 'test', 'prod'])
@pytest.mark.parametrize('host', ['db', 'database.example.invalid'])
def test_bws_effective_target_controls_generated_compose_dependency_graph(tmp_path, monkeypatch, channel, host):
    """Run real effect selection and shell-generated up commands through Compose's parser.

    Only the credential/lock guard and Docker mutation are fake. The Docker shim
    converts each actual generated up invocation to config using the exact same
    files/environment; it never starts a container or contacts a Docker engine.
    """
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    real_docker = shutil.which('docker')
    if real_docker is None:
        pytest.skip('Docker Compose config parser unavailable; hosted CI must render')
    root = tmp_path / 'repo'
    (root / 'config/deploy').mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / 'config/runtime.defaults.env', root / 'config/runtime.defaults.env')
    for name in ('docker-compose.yaml', 'docker-compose.' + channel + '.yml',
                 'docker-compose.bws.yml', 'docker-compose.bws-external.yml'):
        shutil.copyfile(REPO_ROOT / name, root / name)
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('LLM_PROVIDER=mock\nLOCAL_UID=1000\nLOCAL_GID=1000\n')
    pin = root / 'config/deploy' / (channel + '.env')
    pin.write_text('WATCHER_RUNTIME_ENV_FILE=' + str(runtime) + '\nAPP_IMAGE_REPOSITORY=ghcr.io/rasmustho/pkm-app\nAPP_IMAGE_TAG=' + 'a' * 40 + '\n')
    password = tmp_path / 'password'
    password.write_text('fake-external-graph-password')
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'], 'LLM_PROVIDER': 'mock',
           'WATCHER_RUNTIME_ENV_FILE': str(runtime), 'DATABASE_URL': 'postgresql://app@' + host + ':5432/custom',
           'INSTANCE_OWNERSHIP_HOST_STATE_DIR': str(tmp_path / 'ownership'),
           'COMPOSE_PROFILES': 'bws-local-database-disabled' if host != 'db' else ''}
    monkeypatch.setattr(os, 'environ', env)
    cfg = SimpleNamespace(root=root, channel=channel, uid=1000, gid=1000, password_file=password)
    effects = linux.LinuxEffects(cfg)
    produced = effects.environment()
    assert produced['BWS_DATABASE_TARGET'] == ('local' if host == 'db' else 'external')
    assert produced['COMPOSE_PROFILES'] == ''
    direct_graph = json.loads(effects.compose('config', '--format', 'json'))

    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    graph_log = tmp_path / 'graphs.jsonl'
    _write_executable(bin_dir / 'docker', '#!' + sys.executable + '\n' + '''
import json,os,subprocess,sys
from pathlib import Path
args=sys.argv[1:]
assert args[0] == 'compose' and 'up' in args
index=args.index('up')
result=subprocess.run([os.environ['REAL_DOCKER'],*args[:index],'config','--format','json'],
                      text=True,capture_output=True,check=True)
with Path(os.environ['GRAPH_LOG']).open('a') as stream:
    stream.write(json.dumps({'argv':args,'graph':json.loads(result.stdout)})+'\\n')
''')
    python_guard = bin_dir / 'guard-python'
    _write_executable(python_guard, '#!' + sys.executable + '\n' + '''
import os,sys
if sys.argv[1:3] == ['-m','app.ops.postgres_deploy_linux']:
    assert sys.argv[3] == 'guard'
else:
    os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
''')
    produced.update(PATH=str(bin_dir) + ':' + env['PATH'], PYTHON=str(python_guard),
                    REAL_DOCKER=real_docker, GRAPH_LOG=str(graph_log))
    script = '''
set -euo pipefail
source "$1/scripts/lib/deploy_channel_compose.sh"
deploy_channel_compose "$2" "$3" "docker-compose.$3.yml" "pkm-$3" "$4" up --abort-on-container-exit --exit-code-from migrate --force-recreate migrate
deploy_channel_compose "$2" "$3" "docker-compose.$3.yml" "pkm-$3" "$4" up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui
'''
    result = subprocess.run(['bash', '-c', script, '--', str(REPO_ROOT), str(root), channel, str(pin)],
                            env=produced, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in graph_log.read_text().splitlines()]
    assert len(records) == 2
    for graph in (direct_graph, *(record['graph'] for record in records)):
        services = graph['services']
        for name in ('migrate', 'api', 'worker', 'watcher', 'heimdal-capture-watch'):
            assert ('db' in services[name].get('depends_on', {})) == (host == 'db')
        for name in ('api', 'worker', 'watcher', 'heimdal-capture-watch'):
            assert services[name]['depends_on']['migrate']['condition'] == 'service_completed_successfully'
            assert services[name]['depends_on']['instance-state-init']['condition'] == 'service_completed_successfully'
        if channel == 'prod':
            assert services['api']['depends_on']['ollama']['condition'] == 'service_healthy'
        if host != 'db':
            assert 'db' not in services
            assert 'bws_pgdata' not in graph.get('volumes', {})
        assert password.read_text() not in json.dumps(graph)
    for record in records:
        assert ('docker-compose.bws-external.yml' in ' '.join(record['argv'])) == (host != 'db')


@pytest.mark.parametrize(
    ('overrides', 'expected'),
    [
        ({}, '/home/runtime/.local/state/agentic-pkm/instance-ownership'),
        ({'XDG_STATE_HOME': '/srv/state'}, '/srv/state/agentic-pkm/instance-ownership'),
        ({'INSTANCE_OWNERSHIP_HOST_STATE_DIR': '/custom/state'}, '/custom/state'),
    ],
)
def test_root_bws_supervisor_uses_runtime_state_path(tmp_path, monkeypatch, overrides, expected):
    """The root supervisor avoids /root defaults and preserves explicit state roots."""
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux

    root = tmp_path / 'repo'
    (root / 'config/deploy').mkdir(parents=True)
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('LLM_PROVIDER=mock\n')
    password = tmp_path / 'password'
    password.write_text('fixture-password')
    monkeypatch.setattr(os, 'environ', {'HOME': '/root', **overrides})
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(linux.pwd, 'getpwuid', lambda uid: SimpleNamespace(pw_dir='/home/runtime'))

    cfg = SimpleNamespace(
        root=root,
        channel='dev',
        uid=1000,
        gid=1000,
        password_file=password,
        runtime_env_file=runtime,
    )

    produced = linux.LinuxEffects(cfg).environment()

    assert produced['INSTANCE_OWNERSHIP_HOST_STATE_DIR'] == expected
    assert produced['LOCAL_UID'] == '1000'


def test_non_root_bws_caller_uses_own_home_without_runtime_passwd_lookup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux

    root = tmp_path / 'repo'
    (root / 'config/deploy').mkdir(parents=True)
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('LLM_PROVIDER=mock\n')
    password = tmp_path / 'password'
    password.write_text('fixture-password')
    monkeypatch.setattr(os, 'environ', {'HOME': '/home/caller'})
    monkeypatch.setattr(os, 'geteuid', lambda: 501)
    monkeypatch.setattr(linux.pwd, 'getpwuid', lambda uid: pytest.fail('runtime passwd lookup is root-only'))

    cfg = SimpleNamespace(
        root=root,
        channel='dev',
        uid=1000,
        gid=1000,
        password_file=password,
        runtime_env_file=runtime,
    )

    produced = linux.LinuxEffects(cfg).environment()

    assert produced['INSTANCE_OWNERSHIP_HOST_STATE_DIR'] == (
        '/home/caller/.local/state/agentic-pkm/instance-ownership'
    )


@pytest.mark.parametrize('channel', ['dev', 'test', 'prod'])
def test_rendered_compose_uses_postgres_secret_file_without_value(tmp_path, channel):
    rendered = _render_bws_compose(tmp_path, channel)
    for service in rendered['services'].values():
        environment = service.get('environment', {})
        assert not environment.get('POSTGRES_PASSWORD')
        assert not environment.get('PGPASSWORD')
        for name in ('DATABASE_URL', 'DB_DSN'):
            if environment.get(name):
                from app.config.database import credential_free_database_fields
                credential_free_database_fields(environment[name])
    assert rendered['services']['db']['environment']['POSTGRES_PASSWORD_FILE'] == '/run/secrets/postgres_password'


def test_postgres_secret_mount_is_limited_to_database_clients(tmp_path):
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    rendered = _render_bws_compose(tmp_path, 'test')
    recipients = {name for name, service in rendered['services'].items()
                  if any(item['source'] == 'postgres_password' for item in service.get('secrets', []))}
    assert recipients == set(DATABASE_CONSUMERS.values())
    for name in recipients:
        assert rendered['services'][name]['restart'] == 'no'


def test_database_services_map_to_declared_password_consumers():
    import yaml
    from app.ops.host_secret_contract import DATABASE_CONSUMERS, load_host_secret_contract
    overlay = yaml.safe_load((REPO_ROOT / 'docker-compose.bws.yml').read_text())
    contract = load_host_secret_contract()
    for channel in ('dev', 'test', 'prod'):
        for consumer, service in DATABASE_CONSUMERS.items():
            actual_service, variable = contract.file_binding(channel=channel, consumer=consumer, secret='postgres.password')
            assert actual_service == service
            assert overlay['services'][service]['environment'][variable] == '/run/secrets/postgres_password'


def test_postgres_entrypoint_password_file_isolated_from_application_environment(tmp_path):
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    rendered = _render_bws_compose(tmp_path, 'dev')
    for service in set(DATABASE_CONSUMERS.values()) - {'db'}:
        environment = rendered['services'][service]['environment']
        assert environment['DATABASE_PASSWORD_FILE'] == '/run/secrets/postgres_password'
        assert 'POSTGRES_PASSWORD_FILE' not in environment
        assert not environment.get('POSTGRES_PASSWORD')


def _password_source_fixture(tmp_path, monkeypatch):
    """Exercise actual file writes; model root metadata/UID switch without privilege."""
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    directory = tmp_path / 'tmpfs' / 'test'
    cfg = SimpleNamespace(source_directory=directory, password_file=directory / 'password', uid=1011, gid=1012)
    source = linux.PasswordSource(cfg)
    events = []
    def root_directory(path):
        events.append(('root-directory', path))
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    def command(argv, **kwargs):
        events.append(('filesystem', argv))
        return 'tmpfs\n'
    actual_fstat = os.fstat
    def fstat(fd):
        info = actual_fstat(fd)
        return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_gid=cfg.gid, st_nlink=info.st_nlink)
    actual_stat = Path.stat
    def path_stat(path, *args, **kwargs):
        info = actual_stat(path, *args, **kwargs)
        if path == directory:
            return SimpleNamespace(st_mode=info.st_mode, st_uid=0)
        return info
    def non_root_probe(argv, **kwargs):
        events.append(('probe', kwargs))
        assert os.read(kwargs['pass_fds'][0], 65537) == b'fake-file-canary'
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(linux, '_root_directory', root_directory)
    monkeypatch.setattr(linux, '_command', command)
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(os, 'fchown', lambda fd, uid, gid: events.append(('chown', uid, gid)))
    monkeypatch.setattr(os, 'fstat', fstat)
    monkeypatch.setattr(Path, 'stat', path_stat)
    monkeypatch.setattr(linux.subprocess, 'run', non_root_probe)
    return source, cfg, events


def test_postgres_secret_source_uses_root_only_tmpfs_and_service_gid(tmp_path, monkeypatch):
    source, cfg, events = _password_source_fixture(tmp_path, monkeypatch)
    source.materialize('fake-file-canary')
    assert cfg.source_directory.stat().st_mode & 0o777 == 0o700
    assert cfg.password_file.stat().st_mode & 0o777 == 0o440
    assert ('chown', 0, cfg.gid) in events
    assert any(event[0] == 'filesystem' for event in events)


def test_postgres_secret_is_readable_by_configured_non_root_service_user(tmp_path, monkeypatch):
    from app.ops.postgres_deploy import PostgresDeployError
    source, cfg, events = _password_source_fixture(tmp_path, monkeypatch)
    source.materialize('fake-file-canary')
    probe = next(event[1] for event in events if event[0] == 'probe')
    assert (probe['user'], probe['group'], probe['extra_groups']) == (cfg.uid, cfg.gid, [])
    assert probe['capture_output'] is True
    cfg.password_file.chmod(0o444)
    with pytest.raises(PostgresDeployError):
        source.verify()


def test_postgres_secret_file_is_private_and_cleaned_after_consumers_stop(tmp_path, monkeypatch):
    from app.ops.postgres_deploy import PostgresDeployError
    source, cfg, _ = _password_source_fixture(tmp_path, monkeypatch)
    source.materialize('fake-file-canary')
    with pytest.raises(PostgresDeployError):
        source.cleanup(all_consumers_stopped=False)
    assert cfg.password_file.exists()
    source.cleanup(all_consumers_stopped=True)
    assert not cfg.password_file.exists()


def test_postgres_secret_source_is_ephemeral_and_nonpersistent(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError
    source, cfg, _ = _password_source_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(linux, '_command', lambda *args, **kwargs: 'ext4\n')
    with pytest.raises(PostgresDeployError):
        source.materialize('fake-file-canary')
    assert not cfg.password_file.exists()
    config = linux.LinuxConfig('test', tmp_path, tmp_path, 1000, 1000, '', '')
    assert str(config.password_file) == '/run/yggdrasil/postgres/test/password'
    assert str(config.journal.directory).startswith('/var/lib/')


def test_compose_secret_source_lifecycle_covers_restart_recreate_and_boot(tmp_path, monkeypatch):
    from app.ops.postgres_deploy import PostgresDeployError
    source, cfg, _ = _password_source_fixture(tmp_path, monkeypatch)
    source.materialize('fake-file-canary')
    inode = cfg.password_file.stat().st_ino
    source.materialize('fake-file-canary')
    assert cfg.password_file.stat().st_ino == inode  # bind-mounted consumers retain their inode
    with pytest.raises(PostgresDeployError):
        source.materialize('different-password')
    assert cfg.password_file.stat().st_ino == inode
    source.cleanup(all_consumers_stopped=True)
    source.materialize('fake-file-canary')  # a stopped/booted host rehydrates before activation
    assert cfg.password_file.read_bytes() == b'fake-file-canary'
    import yaml
    overlay = yaml.safe_load((REPO_ROOT / 'docker-compose.bws.yml').read_text())
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    assert all(overlay['services'][name]['restart'] == 'no' for name in DATABASE_CONSUMERS.values())
    unit = (REPO_ROOT / 'config/systemd/yggdrasil-bws-deploy@.service').read_text()
    assert 'KillMode=control-group' in unit
    assert 'ExecStopPost=/usr/local/libexec/yggdrasil-bws-deploy cleanup %i' in unit
    assert 'LoadCredentialEncrypted=' in unit and 'BWS_ACCESS_TOKEN_FILE=%d/' in unit


def test_bws_supervisor_launcher_uses_declared_runtime_dependencies():
    runtime_python = '/opt/yggdrasil/bws-deploy-runtime/bin/python3'
    manifest = (REPO_ROOT / 'requirements-bws-deploy.txt').read_text(encoding='utf-8')
    launcher = (REPO_ROOT / 'scripts/postgres_deploy_service.py').read_text(encoding='utf-8')
    unit = (REPO_ROOT / 'config/systemd/yggdrasil-bws-deploy@.service').read_text(encoding='utf-8')

    assert manifest.splitlines() == [
        'bitwarden-sdk==2.1.0',
        'psycopg[binary]==3.2.10',
        'python-dateutil==2.9.0.post0',
        'six==1.17.0',
        'typing-extensions==4.15.0',
    ]
    assert launcher.splitlines()[0] == f'#!{runtime_python}'
    assert 'ExecStart=/usr/local/libexec/yggdrasil-bws-deploy serve %i' in unit
    assert 'ExecStopPost=/usr/local/libexec/yggdrasil-bws-deploy cleanup %i' in unit


def _write_fake_bws_runtime_python(fake_bin):
    fake_bin.mkdir()
    bootstrap_python = fake_bin / 'python3.12'
    bootstrap_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ \"$1\" == \"-c\" ]]; then
  printf 'bootstrap:%s\\n' \"$*\" >> \"$BWS_SETUP_TRACE\"
  [[ \"${BWS_FAIL_BOOTSTRAP_CHECK:-0}\" != \"1\" ]]
  exit
fi
if [[ \"$1\" == \"-m\" && \"$2\" == \"venv\" ]]; then
  if [[ \"$3\" == \"--upgrade\" ]]; then runtime_root=\"$4\"; else runtime_root=\"$3\"; fi
  mkdir -p \"$runtime_root/bin\"
  cat > \"$runtime_root/bin/python3\" <<'RUNTIME_PYTHON'
#!/usr/bin/env bash
set -euo pipefail
printf 'runtime:%s\\n' \"$*\" >> \"$BWS_SETUP_TRACE\"
if [[ \"$1\" == \"-m\" && \"$2\" == \"pip\" && \"${BWS_FAIL_RUNTIME_PIP:-0}\" == \"1\" ]]; then exit 1; fi
if [[ \"$1\" == \"-c\" && \"${BWS_FAIL_RUNTIME_VERSION:-0}\" == \"1\" ]]; then exit 1; fi
if [[ \"$1\" == \"-c\" && \"$*\" == *bitwarden_sdk* && \"${BWS_FAIL_RUNTIME_CHECK:-0}\" == \"1\" ]]; then exit 1; fi
RUNTIME_PYTHON
  chmod 755 \"$runtime_root/bin/python3\"
  printf 'bootstrap:%s\\n' \"$*\" >> \"$BWS_SETUP_TRACE\"
  exit 0
fi
echo 'unexpected bootstrap invocation' >&2
exit 1
""",
        encoding='utf-8',
    )
    bootstrap_python.chmod(0o755)


def _bws_setup_environment(fake_bin, trace, **overrides):
    return {
        **_without_macos_malloc_stack_logging(),
        'PATH': f'{fake_bin}{os.pathsep}{os.environ.get("PATH", "")}',
        'BWS_SETUP_TRACE': str(trace),
        **overrides,
    }


def test_bws_supervisor_runtime_setup_is_idempotent_and_preserves_credentials(tmp_path):
    fake_bin = tmp_path / 'fake-bin'
    _write_fake_bws_runtime_python(fake_bin)
    trace = tmp_path / 'setup.trace'
    runtime_root = tmp_path / 'runtime'
    install_root = tmp_path / 'libexec'
    env = _bws_setup_environment(fake_bin, trace)
    setup = REPO_ROOT / 'scripts/install_bws_deploy_runtime.sh'
    unit_path = REPO_ROOT / 'config/systemd/yggdrasil-bws-deploy@.service'
    original_unit = unit_path.read_bytes()
    source_launcher = REPO_ROOT / 'scripts/postgres_deploy_service.py'
    installed_launcher = install_root / 'yggdrasil-bws-deploy'

    for _ in range(2):
        result = subprocess.run(
            [
                'bash',
                str(setup),
                '--runtime-root',
                str(runtime_root),
                '--install-root',
                str(install_root),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    calls = trace.read_text(encoding='utf-8').splitlines()
    requirements = REPO_ROOT / 'requirements-bws-deploy.txt'
    bootstrap_check = 'bootstrap:-c import sys; sys.version_info >= (3, 12) or sys.exit(78)'
    runtime_version_check = 'runtime:-c import sys; sys.version_info >= (3, 12) or sys.exit(78)'
    runtime_import_check = 'runtime:-c import bitwarden_sdk, psycopg, app.ops.postgres_deploy_linux'
    assert len(calls) == 10
    assert calls[0] == bootstrap_check
    assert calls[1] == f'bootstrap:-m venv {runtime_root}'
    assert calls[2] == runtime_version_check
    assert calls[3] == (
        f'runtime:-m pip install --disable-pip-version-check --requirement {requirements}'
    )
    assert calls[4].startswith(runtime_import_check)
    assert calls[5] == bootstrap_check
    assert calls[6] == f'bootstrap:-m venv --upgrade {runtime_root}'
    assert calls[7] == runtime_version_check
    assert calls[8] == (
        f'runtime:-m pip install --disable-pip-version-check --requirement {requirements}'
    )
    assert calls[9].startswith(runtime_import_check)
    source_body = source_launcher.read_bytes().partition(b'\n')[2]
    assert installed_launcher.read_bytes() == f'#!{runtime_root}/bin/python3\n'.encode() + source_body
    assert installed_launcher.stat().st_mode & 0o777 == 0o755
    assert unit_path.read_bytes() == original_unit
    assert 'LoadCredentialEncrypted=bws-machine-account-token:/var/lib/yggdrasil/bws-tokens/%i/current' in original_unit.decode()


def test_bws_supervisor_runtime_rejects_old_bootstrap_python_before_mutation(tmp_path):
    fake_bin = tmp_path / 'fake-bin'
    _write_fake_bws_runtime_python(fake_bin)
    trace = tmp_path / 'setup.trace'
    runtime_root = tmp_path / 'runtime'
    install_root = tmp_path / 'libexec'
    installed_launcher = install_root / 'yggdrasil-bws-deploy'
    installed_launcher.parent.mkdir()
    installed_launcher.write_bytes(b'previous-launcher\n')

    result = subprocess.run(
        ['bash', str(REPO_ROOT / 'scripts/install_bws_deploy_runtime.sh'),
         '--runtime-root', str(runtime_root), '--install-root', str(install_root)],
        cwd=REPO_ROOT,
        env=_bws_setup_environment(fake_bin, trace, BWS_FAIL_BOOTSTRAP_CHECK='1'),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 78
    assert trace.read_text(encoding='utf-8').splitlines() == [
        'bootstrap:-c import sys; sys.version_info >= (3, 12) or sys.exit(78)'
    ]
    assert not runtime_root.exists()
    assert installed_launcher.read_bytes() == b'previous-launcher\n'


@pytest.mark.parametrize(
    'failure',
    ['BWS_FAIL_RUNTIME_VERSION', 'BWS_FAIL_RUNTIME_PIP', 'BWS_FAIL_RUNTIME_CHECK'],
)
def test_bws_supervisor_runtime_failure_keeps_installed_launcher(tmp_path, failure):
    fake_bin = tmp_path / 'fake-bin'
    _write_fake_bws_runtime_python(fake_bin)
    trace = tmp_path / 'setup.trace'
    runtime_root = tmp_path / 'runtime'
    install_root = tmp_path / 'libexec'
    installed_launcher = install_root / 'yggdrasil-bws-deploy'
    installed_launcher.parent.mkdir()
    installed_launcher.write_bytes(b'previous-launcher\n')

    result = subprocess.run(
        ['bash', str(REPO_ROOT / 'scripts/install_bws_deploy_runtime.sh'),
         '--runtime-root', str(runtime_root), '--install-root', str(install_root)],
        cwd=REPO_ROOT,
        env=_bws_setup_environment(fake_bin, trace, **{failure: '1'}),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert installed_launcher.read_bytes() == b'previous-launcher\n'


def _bws_runtime_export_fixture(tmp_path):
    root = tmp_path / 'export'
    for relative in ('scripts/export_runtime_env.sh', 'scripts/lib/load_env_defaults.sh', 'scripts/compose_env.py', 'config/runtime.defaults.env'):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    output = tmp_path / 'runtime.env'
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'], 'PYTHONPATH': str(REPO_ROOT),
           'HOST_SECRET_PROVIDER': 'bws', 'PKM_ENVIRONMENT': 'test', 'NO_VAULT_MODE': '1',
           'RUNTIME_ENV_PATH': str(output), 'LLM_PROVIDER': 'mock', 'PYTEST_CURRENT_TEST': 'bws-producer'}
    return root, output, env


def test_bws_runtime_export_produces_only_credential_free_database_defaults(tmp_path):
    root, output, env = _bws_runtime_export_fixture(tmp_path)
    result = subprocess.run(['bash', 'scripts/export_runtime_env.sh'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    text = output.read_text()
    assert 'DATABASE_URL=postgresql+psycopg://app@db:5432/app_test' in text
    assert 'DB_DSN=postgresql+psycopg://app@db:5432/app_test' in text
    assert 'PASSWORD' not in text


@pytest.mark.parametrize('location', ['ambient', 'dotenv'])
def test_bws_runtime_export_rejects_password_dsn_before_output(tmp_path, location):
    root, output, env = _bws_runtime_export_fixture(tmp_path)
    forbidden = 'postgresql://app:fake-export-canary@db/app_test'
    if location == 'ambient':
        env['DATABASE_URL'] = forbidden
    else:
        (root / '.env').write_text('DATABASE_URL=' + forbidden + '\n')
    result = subprocess.run(['bash', 'scripts/export_runtime_env.sh'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'fake-export-canary' not in result.stdout + result.stderr
    assert not output.exists()


@pytest.mark.parametrize('overrides,expected', [
    ({'DATABASE_URL': 'postgresql://url-user@url.example.invalid/url-db'}, 'postgresql://url-user@url.example.invalid/url-db'),
    ({'DB_DSN': 'postgresql://dsn-user@dsn.example.invalid/dsn-db'}, 'postgresql://dsn-user@dsn.example.invalid/dsn-db'),
    ({'DATABASE_URL': 'postgresql://url-user@url.example.invalid/url-db', 'DB_DSN': 'postgresql://dsn-user@dsn.example.invalid/dsn-db'}, 'postgresql://url-user@url.example.invalid/url-db'),
])
def test_bws_compose_preserves_database_alias_precedence(tmp_path, overrides, expected):
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    rendered = _render_bws_compose(tmp_path, 'test', overrides)
    for service in set(DATABASE_CONSUMERS.values()) - {'db'}:
        environment = rendered['services'][service]['environment']
        assert environment['DATABASE_URL'] == environment['DB_DSN'] == expected


@pytest.mark.parametrize('channel,database', [('dev', 'app_dev'), ('test', 'app_test'), ('prod', 'app')])
def test_bws_compose_initialization_matches_empty_target_proof(tmp_path, channel, database):
    rendered = _render_bws_compose(tmp_path, channel, {'POSTGRES_USER': 'foreign', 'POSTGRES_DB': 'foreign'})
    environment = rendered['services']['db']['environment']
    assert environment['POSTGRES_USER'] == 'app'
    assert environment['POSTGRES_DB'] == database
