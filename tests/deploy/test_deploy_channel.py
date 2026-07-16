from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


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
if [ -n "${{FAKE_DOCKER_FAIL_MATCH:-}}" ] && [[ "$*" == *"${{FAKE_DOCKER_FAIL_MATCH}}"* ]]; then
  exit 24
fi
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
    if os.environ.get("FAKE_OUTBOX_DB_UNREACHABLE") == "1":
        raise OperationalError("fake: db unreachable")
    raw = os.environ.get("FAKE_OUTBOX_ROWS_JSON", "[]")
    rows = [tuple(row) for row in json.loads(raw)]
    return _FakeConnection(rows)
'''


# Deliberately credential-bearing: the redaction test asserts none of these
# identity fragments ever reach deploy output, and every other prod test rides
# the same DSN so any new leak path shows up loudly.
_FAKE_PROD_DSN = "postgresql://produser:sup3rsecret@prod-db.internal:5432/pkm_prod"


def _configure_prod_retry_preflight(
    root: Path,
    env: dict[str, str],
    tmp_path: Path,
    *,
    rows: list[tuple[str, dict, int]] | None = None,
    unreachable: bool = False,
    no_dsn: bool = False,
) -> None:
    """Copy the real preflight script into the fixture repo and fake its DB layer.

    ``rows`` is a list of ``(topic, payload, attempts)`` triples standing in
    for pending (``delivered_at is null``) outbox rows. The real
    scripts/prod_deploy_retry_preflight.py runs unmodified against these rows
    through the fake psycopg module below -- only the DB connection is faked,
    the classification logic under test is real.

    DSN sourcing mirrors the production mechanics (#3903 D1): the DSN lives in
    the channel's governed runtime env file, referenced from the channel pin
    file via WATCHER_RUNTIME_ENV_FILE -- not in the ambient shell env, which
    the real prod call chain never provides. ``no_dsn=True`` leaves the
    runtime env file without any DSN key (and the shell env is scrubbed in
    every mode), exercising the visible skipped:no_dsn path.
    """
    shutil.copy2(
        REPO_ROOT / "scripts/prod_deploy_retry_preflight.py",
        root / "scripts/prod_deploy_retry_preflight.py",
    )
    pylib_dir = tmp_path / "pylib"
    pylib_dir.mkdir(exist_ok=True)
    (pylib_dir / "psycopg.py").write_text(_FAKE_PSYCOPG_MODULE, encoding="utf-8")
    env["PYTHONPATH"] = str(pylib_dir)

    # The governed channel pin file references the runtime env file; the DSN
    # lives only in the latter, exactly like the real prod channel.
    (root / "config/deploy/prod.env").write_text(
        "WATCHER_RUNTIME_ENV_FILE=./runtime-prod.env\n", encoding="utf-8"
    )
    runtime_env_lines = "SOME_OTHER_KEY=untouched\n"
    if not no_dsn:
        runtime_env_lines += f"DATABASE_URL={_FAKE_PROD_DSN}\n"
    (root / "runtime-prod.env").write_text(runtime_env_lines, encoding="utf-8")
    env.pop("DATABASE_URL", None)
    env.pop("DB_DSN", None)

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

    assert result.returncode != 0
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

    assert result.returncode != 0
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
    _configure_prod_retry_preflight(
        root,
        env,
        tmp_path,
        rows=[("panel.scan.requested", {}, 4)],
    )

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode != 0
    assert "prod pending-retry preflight: blocked terminal_pending_count=1" in result.stdout
    assert "terminal retry boundary" in result.stderr
    # The pin file pre-exists to carry WATCHER_RUNTIME_ENV_FILE, so "no pin
    # mutation" means no APP_IMAGE_* lines were written to it.
    assert "APP_IMAGE_TAG" not in (root / "config/deploy/prod.env").read_text(encoding="utf-8")
    assert not (root / "config/deploy/prod.previous.env").exists()
    assert not (tmp_path / "docker-called").exists()


def test_prod_deploy_pending_retry_preflight_is_redacted(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    # Worker-retry mechanism, in the REAL writer shape: write_outbox_event
    # stores the Event ENVELOPE, so _worker_retry_count sits nested at
    # payload->'payload' (the #3124 rows looked exactly like this). The
    # secrets live in the nested payload and the DSN (with credentials) comes
    # from the governed runtime env file -- none of it may reach output.
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
    # Governed runtime env file carries no DATABASE_URL/DB_DSN and the shell
    # env is scrubbed: the preflight cannot inspect the outbox and must skip
    # visibly while the deploy proceeds.
    _configure_prod_retry_preflight(root, env, tmp_path, no_dsn=True)

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "prod pending-retry preflight: skipped:no_dsn" in result.stdout
    assert (tmp_path / "docker-called").exists()
