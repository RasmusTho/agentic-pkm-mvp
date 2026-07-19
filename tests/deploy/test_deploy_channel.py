from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.prod_deploy_retry_preflight import _PROD_DB_HOST_PUBLISHED_PORT


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _deploy_harness(tmp_path: Path) -> tuple[Path, dict[str, str], str]:
    root = tmp_path / "repo"
    (root / "scripts/lib").mkdir(parents=True)
    (root / "config/deploy").mkdir(parents=True)
    (root / "app/alembic/versions").mkdir(parents=True)
    (root / "app/release_channels").mkdir(parents=True)
    (root / "ops/deployments").mkdir(parents=True)

    for relative in (
        "app/release_channels/__init__.py",
        "app/release_channels/reversibility.py",
        "scripts/deploy_channel.sh",
        "scripts/companion_ui_postdeploy_smoke.sh",
        "scripts/lib/deploy_channel_compose.sh",
        "scripts/lib/instance_state_deployment.sh",
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
if [ -n "${{FAKE_DOCKER_FAIL_MATCH:-}}" ] && [[ "$*" == *"${{FAKE_DOCKER_FAIL_MATCH}}"* ]]; then
  exit 24
fi
case "$*" in
  *" ps -q "*) printf '%s\\n' fake-capture-watch ;;
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
        shutil.copy2(
            REPO_ROOT / "docker-compose.prod.yml", root / "docker-compose.prod.yml"
        )
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


def test_acknowledged_embedding_cutover_liveness_failure_rolls_back_candidate(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "1" * 40
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    env["FAKE_API_LIVENESS"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-embedding-rebuild-required")

    assert result.returncode == 1
    assert "service recreate/liveness gate failed" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch"
        )
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
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    env["FAKE_DOCKER_FAIL_MATCH"] = (
        "up -d --force-recreate --no-deps companion-ui"
    )

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
    resolves that variable ONLY from the pin file and explicitly `unset`s it
    before invoking Compose whenever the pin file lacks the key. Round 4
    removed the whole file-reading mechanism this bug lived in, but an
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
    ambient_env_file.write_text(
        f"DATABASE_URL={_ENV_FILE_POISON_DSN}\n", encoding="utf-8"
    )
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
    _configure_prod_retry_preflight(
        root, env, tmp_path, compose_files_present=False
    )

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "prod pending-retry preflight: skipped:no_dsn" in result.stdout
    assert (tmp_path / "docker-called").exists()
