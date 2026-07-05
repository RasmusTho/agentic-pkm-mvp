"""Fixture-level test for scripts/await_pr_checks.sh check-run dedupe (#2933).

Real bug: after a body/config-fix rerun, GitHub keeps BOTH the stale failed check-run record
and the newer successful one for the same check name on the same head SHA. Classifying on the
raw (undeduped) list fails closed on a check that already went green on its latest run.

The fixtures here are trimmed real data pulled from PR #2915's head SHA `2b68f435...`
(`repos/{owner}/{repo}/commits/2b68f435/check-runs`), which genuinely carries a `failure` record
(id 85168129582, started_at 21:23:38Z) and a later `success` record (id 85168580472, started_at
21:30:36Z) for the `pr-contract` check name on one SHA.

This test stubs `gh` on PATH so the real script (`scripts/await_pr_checks.sh`) runs unmodified
against the canned check-runs JSON, and asserts on the script's actual exit code.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "await_pr_checks"
SCRIPT = REPO_ROOT / "scripts" / "await_pr_checks.sh"

FAKE_SHA = "2b68f435b078c7ce7ce37125945e4ab31cbfc51a"

FAKE_GH = """#!/usr/bin/env bash
# Fake `gh` for await_pr_checks.sh fixture testing: serves a canned check-runs response and a
# constant-success classic commit status, so the real script's dedupe/classification logic runs
# unmodified against real historical data.
set -uo pipefail
if [ "$1" = "api" ] && [ "$2" = "rate_limit" ]; then
  echo '{"resources":{"core":{"remaining":4999},"graphql":{"remaining":4999}}}'
  exit 0
fi
if [ "$1" = "api" ]; then
  path="$2"
  case "$path" in
    *check-runs*) cat "$FAKE_CHECK_RUNS_JSON"; exit 0 ;;
    */status) echo '{"state":"success","total_count":1}'; exit 0 ;;
    */pulls/*) echo "{\\"head\\":{\\"sha\\":\\"$FAKE_SHA\\"}}"; exit 0 ;;
  esac
fi
echo "unhandled fake gh call: $*" >&2
exit 1
"""


def _make_fake_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh_path = bin_dir / "gh"
    gh_path.write_text(FAKE_GH, encoding="utf-8")
    gh_path.chmod(gh_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_await_script(tmp_path: Path, fixture_name: str) -> subprocess.CompletedProcess[str]:
    fake_bin_dir = _make_fake_gh(tmp_path)
    fixture_path = FIXTURES_DIR / fixture_name
    assert fixture_path.exists(), f"missing fixture: {fixture_path}"

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_SHA"] = FAKE_SHA
    env["FAKE_CHECK_RUNS_JSON"] = str(fixture_path)
    env["GH_REPO"] = "RasmusTho/agentic-pkm-mvp"

    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "1",
            "--sha",
            FAKE_SHA,
            "--initial-wait",
            "0",
            "--interval",
            "60",
            "--timeout",
            "30",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_stale_failure_superseded_by_newer_success_classifies_green(tmp_path: Path) -> None:
    """AC1: {failed old run, successful newer run} for one check name -> classified GREEN."""
    result = _run_await_script(tmp_path, "pr2915_stale_failure_then_success.json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHECKS FAILED" not in result.stdout
    assert "all required checks passed" in result.stdout


def test_genuine_latest_failure_still_fails_closed(tmp_path: Path) -> None:
    """AC2: a genuinely failed LATEST record (inverted fixture) still fails closed."""
    result = _run_await_script(tmp_path, "pr2915_genuine_latest_failure.json")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "CHECKS FAILED: pr-contract: failure" in result.stderr
