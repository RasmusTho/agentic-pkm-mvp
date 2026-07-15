from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _deploy_harness(tmp_path: Path) -> tuple[Path, dict[str, str], str]:
    root = tmp_path / "repo"
    (root / "scripts/lib").mkdir(parents=True)
    (root / "config/deploy").mkdir(parents=True)
    (root / "app/alembic/versions").mkdir(parents=True)
    (root / "ops/deployments").mkdir(parents=True)

    for relative in (
        "scripts/deploy_channel.sh",
        "scripts/companion_ui_postdeploy_smoke.sh",
        "scripts/lib/deploy_channel_compose.sh",
    ):
        destination = root / relative
        shutil.copy2(REPO_ROOT / relative, destination)

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "scripts"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_marker = tmp_path / "docker-called"
    event_log = tmp_path / "deploy-events.log"
    _write_executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -eu
touch {docker_marker!s}
printf 'docker %s\\n' "$*" >> "${{FAKE_DEPLOY_EVENT_LOG:?}}"
case "$*" in
  *" ps -q "*) printf '%s\\n' fake-capture-watch ;;
  inspect*) printf '%s\\n' healthy ;;
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
  *"/version"*) printf '{"git_sha":"%s"}\\n' "$FAKE_SHA" ;;
  *"/api/health"*) printf '{"ok":true,"required_ok":true,"version":{"git_sha":"%s"},"checks":{}}\\n' "$FAKE_SHA" ;;
  *) printf '{"ok":true}\\n' ;;
esac
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
  exit 0
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "app.release_channels.fleet_model_fitness" ]; then
  printf '%s\\n' '{{"ok":true}}'
  exit 0
fi
exec {sys.executable!s} "$@"
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PYTHON": str(python_wrapper),
            "FAKE_SHA": sha,
            "FAKE_DEPLOY_EVENT_LOG": str(event_log),
            "DEPLOY_HEALTH_TIMEOUT_SECONDS": "1",
        }
    )
    return root, env, sha


def _run_deploy(root: Path, env: dict[str, str], sha: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "deploy", "dev", sha, *extra],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_deploy_preflights_companion_browser_before_pin_or_compose_mutation(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_PLAYWRIGHT_PREFLIGHT"] = "fail"

    result = _run_deploy(root, env, sha)

    assert result.returncode != 0
    assert "browser preflight failed before channel mutation" in result.stderr
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
        if event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch"
        )
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
