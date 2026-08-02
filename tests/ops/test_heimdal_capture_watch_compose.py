"""Heimdal capture-watch deploy wiring (#3098, follow-up to #3094/#3025).

#3094 built the runtime driver (`app.heimdal.capture_runtime` + `app heimdal
capture-watch`) but left process supervision out of scope. This issue adds a
`heimdal-capture-watch` service to the compose topology, modeled directly on
the existing `watcher` service: same host-filesystem binds, `env_file`
convention, and `restart: unless-stopped` supervision.

Covers:
- the base service is defined with the expected command, mounts, and
  supervision shape (``test_base_service_defined``);
- each channel overlay (dev/test/prod) binds ``PKM_ENVIRONMENT`` and the
  channel's DSN, mirroring the existing `watcher` overlay in each file
  (``test_channel_overlays_bind_expected_environment``);
- the *real* channel-isolation preflight guard
  (`app.release_channels.channel_isolation_preflight`) recognizes and
  validates the new service against the committed prod/test compose files --
  the production enforcement call site, not a reimplemented check
  (``test_channel_isolation_preflight_covers_new_service``,
  ``test_real_prod_and_test_compose_still_pass_preflight``).

Reuses `app.release_channels.channel_isolation_preflight`'s own
`_load_compose` (rather than a second, independently-maintained
`!override`/`!reset`-tolerant YAML loader) so this test parses compose files
exactly the way the real preflight guard does.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from app.release_channels.channel_isolation_preflight import (
    CHANNEL_SERVICES,
    _load_compose,
    check_compose_channel_isolation,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_COMPOSE = _REPO_ROOT / "docker-compose.yaml"
_PROD_COMPOSE = _REPO_ROOT / "docker-compose.prod.yml"
_DEV_COMPOSE = _REPO_ROOT / "docker-compose.dev.yml"
_TEST_COMPOSE = _REPO_ROOT / "docker-compose.test.yml"

_SERVICE = "heimdal-capture-watch"


def _service(compose: Path, name: str = _SERVICE) -> dict:
    return _load_compose(compose)["services"][name]


def _healthcheck_test_command() -> str:
    """Extract the shell one-liner Docker actually runs for this healthcheck.

    ``healthcheck.test`` is ``["CMD-SHELL", "<script>"]``; the script is what
    the container's healthcheck executes on its own interval, independent of
    the supervised process (#4362).
    """
    svc = _service(_BASE_COMPOSE)
    test = svc["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL"
    return test[1]


def test_base_service_defined() -> None:
    svc = _service(_BASE_COMPOSE)

    assert svc["command"][:2] == ["/bin/bash", "-c"]
    assert "app.instance.runtime preflight" in svc["command"][2]
    assert "--consumer heimdal-capture-watch" in svc["command"][2]
    assert "INSTANCE_STATE_LEGACY_ROLLBACK" in svc["command"][2]
    assert "exec python -m app.cli heimdal capture-watch" in svc["command"][2]
    assert svc["restart"] == "unless-stopped"
    assert "/Users:/Users" in svc["volumes"]
    assert "/Volumes:/Volumes" in svc["volumes"]
    assert "runtime-tmp:/app/tmp" in svc["volumes"]
    assert "instance-state:/app/instance-state" in svc["volumes"]
    assert svc["depends_on"]["db"]["condition"] == "service_healthy"
    assert svc["depends_on"]["migrate"]["condition"] == "service_completed_successfully"

    env_file_paths = [
        entry if isinstance(entry, str) else entry["path"] for entry in svc["env_file"]
    ]
    assert "./config/runtime.defaults.env" in env_file_paths
    assert any("WATCHER_RUNTIME_ENV_FILE" in p for p in env_file_paths)

    # Runtime values ride the service env_file chain. Declaring them under
    # `environment` would shadow that chain with CLI interpolation (#3885).
    environment = svc.get("environment") or {}
    assert "HEIMDAL_CAPTURE_WATCH_DIR" not in environment
    assert "HEIMDAL_CAPTURE_INTERVAL_SECONDS" not in environment
    assert "HEIMDAL_RAW_STORE_KEY" not in environment


def test_channel_overlays_bind_expected_environment() -> None:
    prod = _service(_PROD_COMPOSE)
    assert prod["environment"]["PKM_ENVIRONMENT"] == "prod"
    assert "5432/app" in prod["environment"]["DATABASE_URL"]
    assert "app_test" not in prod["environment"]["DATABASE_URL"]
    assert "app_dev" not in prod["environment"]["DATABASE_URL"]

    dev = _service(_DEV_COMPOSE)
    assert dev["environment"]["PKM_ENVIRONMENT"] == "dev"
    assert "app_dev" in dev["environment"]["DATABASE_URL"]

    test = _service(_TEST_COMPOSE)
    assert test["environment"]["PKM_ENVIRONMENT"] == "test"
    assert "app_test" in test["environment"]["DATABASE_URL"]
    # #2991 test-channel runtime-artifact-path convention: api/worker/watcher
    # all remap to /app/tmp-test in this file; heimdal-capture-watch matches
    # even though it writes no artifacts under /app/tmp today, so it doesn't
    # silently regress the moment it grows one (e.g. a future heartbeat file).
    assert "runtime-tmp:/app/tmp-test" in test["volumes"]


def test_channel_isolation_preflight_covers_new_service() -> None:
    assert _SERVICE in CHANNEL_SERVICES


def test_real_prod_and_test_compose_still_pass_preflight() -> None:
    """The real enforcement call site validates the new service correctly.

    Mirrors `tests/release_channels/test_channel_isolation_preflight.py`'s
    own `test_real_prod_compose_passes_preflight` /
    `test_real_test_compose_passes_preflight` -- this is a regression guard
    that the new service's channel bindings, once resolved through the real
    merged compose model (base + overlay), do not introduce a violation.
    """
    prod_result = check_compose_channel_isolation(
        _PROD_COMPOSE, "prod", environ={}, load_dotenv=False,
    )
    assert prod_result.ok, prod_result.summary()

    test_result = check_compose_channel_isolation(_TEST_COMPOSE, "test")
    assert test_result.ok, test_result.summary()


def test_deploy_script_recreates_the_new_service() -> None:
    """`scripts/deploy_channel.sh` must pull/recreate this service like its siblings.

    Otherwise a prod image update ships new code to api/worker/watcher but
    heimdal-capture-watch keeps running its old image indefinitely --
    unversioned drift the standard promotion path would silently miss.
    """
    text = (_REPO_ROOT / "scripts" / "deploy_channel.sh").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    pull_lines = [line for line in lines if line.startswith("compose pull")]
    runtime_recreate_lines = [
        line
        for line in lines
        if line.startswith("compose up -d --force-recreate")
        and " api " in f" {line} "
    ]

    assert pull_lines, "deploy script must pull channel service images"
    assert runtime_recreate_lines, "deploy script must recreate runtime services"
    ordinary_lines = [
        line
        for line in [*pull_lines, *runtime_recreate_lines]
        if "scalar-rollback-guard" not in line
    ]
    for line in ordinary_lines:
        assert _SERVICE in line, line
    scalar_lines = [
        line for line in [*pull_lines, *runtime_recreate_lines]
        if "scalar-rollback-guard" in line
    ]
    assert scalar_lines
    assert all(_SERVICE not in line for line in scalar_lines)


def test_deploy_script_health_gates_the_new_service() -> None:
    """A broken heimdal-capture-watch must fail the deploy, not sit unhealthy and silent (#3111).

    Before this, `health_gate` only checked api + companion-ui, so a capture-watch
    container that crash-loops on a bad ``HEIMDAL_RAW_STORE_KEY`` would deploy "green"
    and only be noticed later via ``docker ps``. A dedicated gate must exist, reference
    the service's container health, and actually run in the deploy flow.
    """
    text = (_REPO_ROOT / "scripts" / "deploy_channel.sh").read_text(encoding="utf-8")
    assert "capture_watch_gate()" in text, "capture_watch_gate function is missing"
    body = text.split("capture_watch_gate()", 1)[1].split("\n}", 1)[0]
    assert _SERVICE in body, "capture_watch_gate must reference the heimdal-capture-watch service"
    invoked = [
        ln for ln in text.splitlines()
        if ln.strip().startswith("capture_watch_gate") and "()" not in ln
    ]
    assert invoked, "capture_watch_gate is defined but never invoked in the deploy flow"


def test_healthcheck_fails_honestly_on_missing_watch_dir() -> None:
    """#4362: the healthcheck must fail (nonzero exit) when
    HEIMDAL_CAPTURE_WATCH_DIR is absent -- the exact config-missing shape
    that crash-looped pkm-test-heimdal-capture-watch-1 for 72h+. This proves
    the healthcheck mechanism itself is honest; the CLI-level fix (see
    tests/heimdal/test_capture_runtime.py ::
    test_resolve_config_for_supervised_run_retries_instead_of_raising) is
    what keeps the container resident long enough for Docker's
    interval/retries window to actually observe this failure instead of
    racing a crash-loop restart."""
    env = os.environ.copy()
    env.pop("HEIMDAL_CAPTURE_WATCH_DIR", None)
    env.pop("HEIMDAL_RAW_STORE_KEY", None)
    env["PYTHONPATH"] = str(_REPO_ROOT)

    result = subprocess.run(
        ["sh", "-c", _healthcheck_test_command()],
        cwd=_REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert "HEIMDAL_CAPTURE_WATCH_DIR" in result.stderr


def test_healthcheck_succeeds_when_config_is_present(tmp_path: Path) -> None:
    """Counterpart to the failure case above: a fully-configured environment
    must report healthy, so the honest-failure fix above is not just always
    failing."""
    watch_dir = tmp_path / "capture-inbox"
    watch_dir.mkdir()
    env = os.environ.copy()
    env["HEIMDAL_CAPTURE_WATCH_DIR"] = str(watch_dir)
    env["HEIMDAL_RAW_STORE_KEY"] = "a" * 64
    env["PYTHONPATH"] = str(_REPO_ROOT)

    result = subprocess.run(
        ["sh", "-c", _healthcheck_test_command()],
        cwd=_REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
