"""Release-channel / CI harness fidelity tests (issue #2193).

These guard the residual harness-fidelity defects flagged by the 2026-06-18
terminal review-thread audit (#2148). Each test asserts the *fixed* behaviour
on the production call path — the committed scripts, the committed workflow, and
the production preflight function — so a regression to any of the old
hard-codings / vacuous checks fails here.

Anchors covered (see issue #2193 Acceptance Criteria):
- AC1 scripts/init_test_vault.sh:11   — seed the selected test vault, not the default.
- AC2 scripts/start_full_system.sh    — probe the watcher heartbeat in tmp-test.
- AC3 .github/workflows/harness-selfverify.yml — include release-channel files in paths.
- AC4 scripts/ci/harness_gate_fault_injection.sh — distinguish crashes from rejections.
- AC5 scripts/ci/harness_gate_fault_injection.sh — isolate env / reject only the injected fault.
- AC6 tests/release_channels/test_channel_isolation_preflight.py:1038 — disable dotenv for the committed fallback.
- AC7 scripts/project_status.py:31    — guard closed events against reopened PRs.

All tests are static or in-process (no Docker, no network).
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from app.release_channels.channel_isolation_preflight import (
    check_compose_channel_isolation,
)
from scripts import project_status

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_TEST_VAULT = REPO_ROOT / "scripts" / "init_test_vault.sh"
START_FULL_SYSTEM = REPO_ROOT / "scripts" / "start_full_system.sh"
HARNESS_SELFVERIFY = REPO_ROOT / ".github" / "workflows" / "harness-selfverify.yml"
FAULT_INJECTION = REPO_ROOT / "scripts" / "ci" / "harness_gate_fault_injection.sh"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"


def _extract_shell_assignment(script: Path, var: str) -> str:
    """Return the right-hand side of the first ``VAR=...`` assignment in *script*.

    Lets a test evaluate the *committed* parameter-expansion expression in a real
    shell, rather than hand-copying it (which could drift from the script).
    """
    prefix = f"{var}="
    for line in script.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):]
    raise AssertionError(f"no `{var}=` assignment found in {script}")


# ---------------------------------------------------------------------------
# AC1 — init_test_vault.sh seeds the SELECTED test vault, not the repo default.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "env, expected",
    [
        # Per-channel override wins over everything.
        ({"VAULT_ROOT_TEST": "/srv/a", "TEST_VAULT_ROOT": "/srv/b", "VAULT_ROOT": "/srv/c"}, "/srv/a"),
        # TEST_VAULT_ROOT is next.
        ({"TEST_VAULT_ROOT": "/srv/b", "VAULT_ROOT": "/srv/c"}, "/srv/b"),
        # Base VAULT_ROOT after that.
        ({"VAULT_ROOT": "/srv/c"}, "/srv/c"),
        # Nothing configured -> repo-local scratch fallback.
        ({}, "vault-test"),
    ],
)
def test_init_test_vault_honors_configured_root(env: dict[str, str], expected: str) -> None:
    """The committed VAULT_TEST expression resolves the operator-selected root.

    Evaluates the actual parameter-expansion from init_test_vault.sh in a clean
    shell with each env combination, proving precedence
    VAULT_ROOT_TEST -> TEST_VAULT_ROOT -> VAULT_ROOT -> vault-test.
    """
    rhs = _extract_shell_assignment(INIT_TEST_VAULT, "VAULT_TEST")
    proc = subprocess.run(
        ["bash", "-c", f'VAULT_TEST={rhs}\nprintf "%s" "$VAULT_TEST"'],
        env={"PATH": os.environ.get("PATH", ""), **env},
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout == expected


def test_init_test_vault_has_no_hardcoded_vault_test_assignment() -> None:
    """Regression guard: the bare `VAULT_TEST="vault-test"` hard-coding is gone."""
    text = INIT_TEST_VAULT.read_text(encoding="utf-8")
    assert 'VAULT_TEST="vault-test"' not in text
    # The committed assignment must honor the per-channel override first.
    assert "VAULT_ROOT_TEST" in _extract_shell_assignment(INIT_TEST_VAULT, "VAULT_TEST")


# ---------------------------------------------------------------------------
# AC2 — start_full_system.sh probes the watcher heartbeat under tmp-test.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "project, expected",
    [
        ("pkm-test", "/app/tmp-test/watcher_heartbeat.json"),
        ("pkm-prod", "/app/tmp/watcher_heartbeat.json"),
        ("", "/app/tmp/watcher_heartbeat.json"),
    ],
)
def test_start_full_system_heartbeat_path_is_channel_specific(
    project: str, expected: str
) -> None:
    """The committed container-tmp derivation yields the channel-correct path.

    Evaluates the exact `case` block + `container_watcher_heartbeat_path=`
    assignment from start_full_system.sh, proving pkm-test probes
    /app/tmp-test/ while other channels keep /app/tmp/.
    """
    text = START_FULL_SYSTEM.read_text(encoding="utf-8")
    # The container-tmp case statement that seeds _container_tmp_dir.
    assert 'pkm-test) _container_tmp_dir="/app/tmp-test" ;;' in text
    hb_rhs = _extract_shell_assignment(START_FULL_SYSTEM, "container_watcher_heartbeat_path")

    snippet = textwrap.dedent(
        """\
        case "${COMPOSE_PROJECT_NAME:-}" in
          pkm-test) _container_tmp_dir="/app/tmp-test" ;;
          *)        _container_tmp_dir="/app/tmp" ;;
        esac
        container_watcher_heartbeat_path=%s
        printf "%%s" "$container_watcher_heartbeat_path"
        """
    ) % hb_rhs
    proc = subprocess.run(
        ["bash", "-c", snippet],
        env={"PATH": os.environ.get("PATH", ""), "COMPOSE_PROJECT_NAME": project},
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout == expected


def test_start_full_system_readiness_probe_uses_channel_variable() -> None:
    """The readiness loop must NOT hard-code /app/tmp/watcher_heartbeat.json.

    Regression guard for the pkm-test false-negative: the probe + timeout error
    must reference the channel-specific variable.
    """
    text = START_FULL_SYSTEM.read_text(encoding="utf-8")
    assert "test -s ${container_watcher_heartbeat_path}" in text
    # The timeout error message reports the channel-specific path too.
    assert (
        "watcher heartbeat not detected at ${container_watcher_heartbeat_path}"
        in text
    )
    # No surviving hard-coded probe against the prod/dev tmp path in the loop.
    assert "test -s /app/tmp/watcher_heartbeat.json" not in text


# ---------------------------------------------------------------------------
# AC3 — harness-selfverify.yml PR paths include the release-channel surfaces.
# ---------------------------------------------------------------------------

def test_harness_selfverify_paths_include_release_channels() -> None:
    """The PR `paths` filter must trigger on app/ + tests/ release_channels.

    The smoke job invokes channel_isolation_preflight directly, so a change to
    those files must run this workflow. Parse the committed YAML and assert the
    globs are present.
    """
    data = yaml.safe_load(HARNESS_SELFVERIFY.read_text(encoding="utf-8"))
    # PyYAML parses the bare `on:` key as boolean True.
    on_block = data.get("on") if "on" in data else data.get(True)
    paths = on_block["pull_request"]["paths"]
    assert "app/release_channels/**" in paths
    assert "tests/release_channels/**" in paths


# ---------------------------------------------------------------------------
# AC4 / AC5 — fault injection distinguishes a CRASH from a real rejection and
# isolates the env per case (so the unset case is genuinely unset).
# ---------------------------------------------------------------------------

def _run_fault_injection(python: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHON"] = python
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    return subprocess.run(
        ["bash", str(FAULT_INJECTION)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_fault_injection_passes_with_real_preflight() -> None:
    """With a real interpreter the gate baselines a PASS and rejects every fault."""
    proc = _run_fault_injection(sys.executable)
    assert proc.returncode == 0, (
        "fault-injection gate should pass with a real interpreter\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "baseline known-good test env accepted" in proc.stdout
    assert "the gate is real" in proc.stdout


def test_fault_injection_fails_when_preflight_crashes(tmp_path: Path) -> None:
    """A command-not-found / crashing preflight must NOT count as a rejection.

    The old gate treated any non-zero exit (incl. rc=127) as a rejection, so a
    broken interpreter made every fault look 'rejected' and the gate go vacuously
    green. Point PYTHON at a stub that always exits 127: the gate must now FAIL
    (it cannot even baseline-accept a known-good env), proving crashes are
    distinguished from real rejections.
    """
    stub = tmp_path / "always-127"
    stub.write_text("#!/usr/bin/env bash\nexit 127\n", encoding="utf-8")
    stub.chmod(0o755)

    proc = _run_fault_injection(str(stub))
    assert proc.returncode != 0, (
        "a crashing preflight must fail the gate, not pass vacuously\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    combined = proc.stdout + proc.stderr
    # The failure is reported as a crash/baseline failure, not a clean rejection.
    assert "BASELINE FAILED" in combined or "CRASHED" in combined


def test_fault_injection_isolates_env_per_case() -> None:
    """The gate must run each case under a hermetic `env -i` shell.

    Without isolation a caller-exported INDEX_OUTBOX_PATH would mask the
    'unset' case and the gate would silently stop testing it.
    """
    text = FAULT_INJECTION.read_text(encoding="utf-8")
    assert "env -i" in text
    # The discriminator asserts the specific marker, not a bare non-zero exit.
    assert "channel-env preflight" in text


# ---------------------------------------------------------------------------
# AC6 — committed-fallback preflight test is isolated from a repo-root .env.
# ---------------------------------------------------------------------------

def test_check_compose_isolation_can_disable_dotenv(tmp_path: Path) -> None:
    """`load_dotenv=False` makes resolution hermetic from a stray repo `.env`.

    Mirrors the real committed-fallback topology: the base layering is the
    committed ``config/runtime.defaults.env`` (carrying a correct prod DSN), and
    every service appends an *optional* runtime layer gated on
    ``${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}``. A repo-root ``.env``
    points WATCHER_RUNTIME_ENV_FILE at a layer carrying a *cross-channel*
    ``app_test`` DSN. With dotenv honored that later layer wins and corrupts the
    prod binding (ok=False); with dotenv disabled the ``.env`` cannot inject a
    winning layer, the committed prod defaults stand, and the check passes
    (ok=True). The committed-fallback AC6 test depends on this OFF behaviour so a
    runner-local ``.env`` cannot turn the guard vacuous.
    """
    compose_dir = tmp_path
    (compose_dir / "config").mkdir()
    # Committed base fallback: a correct prod DSN.
    (compose_dir / "config" / "runtime.defaults.env").write_text(
        "DATABASE_URL=postgresql+psycopg://app:app@db:5432/app\n"
        "DB_DSN=postgresql+psycopg://app:app@db:5432/app\n",
        encoding="utf-8",
    )
    # A later optional layer carrying a CROSS-CHANNEL app_test DSN.
    (compose_dir / "runtime.env").write_text(
        "DATABASE_URL=postgresql+psycopg://app:app@db:5432/app_test\n"
        "DB_DSN=postgresql+psycopg://app:app@db:5432/app_test\n",
        encoding="utf-8",
    )
    (compose_dir / ".env").write_text(
        "WATCHER_RUNTIME_ENV_FILE=./runtime.env\n", encoding="utf-8"
    )
    services = "\n".join(
        textwrap.indent(
            textwrap.dedent(
                f"""\
                {svc}:
                  env_file:
                    - path: config/runtime.defaults.env
                      required: true
                    - path: ${{WATCHER_RUNTIME_ENV_FILE:-./missing-default.env}}
                      required: false
                """
            ),
            "  ",
        )
        for svc in ("api", "worker", "watcher")
    )
    compose_path = compose_dir / "docker-compose.prod.yml"
    compose_path.write_text("services:\n" + services, encoding="utf-8")

    # dotenv ON: the .env injects the winning app_test layer and corrupts prod.
    with_dotenv = check_compose_channel_isolation(
        compose_path, "prod", environ={}, load_dotenv=True
    )
    # dotenv OFF: the .env is ignored; the committed prod defaults stand.
    without_dotenv = check_compose_channel_isolation(
        compose_path, "prod", environ={}, load_dotenv=False
    )

    assert not with_dotenv.ok, (
        "with dotenv honored, a stray .env injects a winning cross-channel layer "
        f"that must be detected:\n{with_dotenv.summary()}"
    )
    assert without_dotenv.ok, (
        "with dotenv disabled, the committed prod defaults must verify without "
        f"interference from a stray .env:\n{without_dotenv.summary()}"
    )


def test_real_prod_compose_committed_fallback_is_dotenv_isolated() -> None:
    """The committed prod compose passes the prod preflight via its committed
    fallback even when dotenv is disabled — the hermetic path the AC6 test uses.
    """
    result = check_compose_channel_isolation(
        PROD_COMPOSE, "prod", environ={}, load_dotenv=False
    )
    assert result.ok, result.summary()


# ---------------------------------------------------------------------------
# AC7 — closed events do not force Done on a now-reopened PR.
# ---------------------------------------------------------------------------

def _run_project_status(monkeypatch, pr: int, action: str, draft: str | None) -> list[list[str]]:
    """Run project_status.main() capturing the reconcile subprocess argv."""
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001
        calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    argv = [
        "project_status.py",
        "--repo",
        "RasmusTho/agentic-pkm-mvp",
        "--pr",
        str(pr),
        "--action",
        action,
    ]
    if draft is not None:
        argv += ["--draft", draft]
    monkeypatch.setattr(project_status.subprocess, "run", fake_run)
    monkeypatch.setattr(project_status.sys, "argv", argv)
    rc = project_status.main()
    assert rc == 0
    return calls


def test_closed_event_does_not_force_explicit_done(monkeypatch) -> None:
    """A `closed` event must NOT pass `--status Done`.

    Forcing Done would slam a reopened (now-OPEN) PR card to Done. The closed
    branch must instead let reconcile derive status from the LIVE PR state, so
    project_status passes NO `--status` for `closed`.
    """
    calls = _run_project_status(monkeypatch, pr=2000, action="closed", draft=None)
    assert len(calls) == 1
    cmd = calls[0]
    assert "--status" not in cmd, (
        "closed event must defer to live PR state, not force an explicit status: "
        f"{cmd}"
    )
    assert cmd[-2:] == ["--pr", "2000"]


def test_non_closed_events_still_force_explicit_status(monkeypatch) -> None:
    """Non-terminal events keep forwarding their explicit derived status."""
    calls = _run_project_status(monkeypatch, pr=2001, action="ready_for_review", draft=None)
    cmd = calls[0]
    assert "--status" in cmd
    assert cmd[cmd.index("--status") + 1] == "Review"

    calls = _run_project_status(monkeypatch, pr=2002, action="opened", draft="false")
    cmd = calls[0]
    assert "--status" in cmd
    assert cmd[cmd.index("--status") + 1] == "Review"


def test_reconcile_derives_done_only_for_still_closed_pr() -> None:
    """The live-state derivation yields Done for a closed PR but NOT for a
    reopened (OPEN) one — proving the close->reopen race is handled.
    """
    from scripts.reconcile_project_status import desired_pr_status

    # Still closed (the common case): terminal Done.
    assert desired_pr_status({"state": "CLOSED", "mergedAt": None}, None) == "Done"
    # Reopened before reconcile runs: derive a non-terminal status, not Done.
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": False, "mergedAt": None}, None)
        == "Review"
    )
    assert (
        desired_pr_status({"state": "OPEN", "isDraft": True, "mergedAt": None}, None)
        == "In Progress"
    )
