"""Fixture-level tests for scripts/await_pr_checks.sh merge-gating fail-closed rules (#4605).

Defect class (LearningSignal lrn_20260729154323_f134857a, PR #4354): a `mergeable_state=dirty`
PR cannot compute `refs/pull/<n>/merge`, so the repo's pull_request workflows never schedule.
CodeQL can still attach green check-runs from `refs/pull/<n>/head`, leaving the waiter a short
all-success check-run list that it previously reported as "all required checks passed".

These tests stub `gh` on PATH so the real script (`scripts/await_pr_checks.sh`) runs unmodified
in its merge-gating mode (no `--sha`) against canned REST payloads, and assert on the script's
actual exit codes:

- exit 6: the PR is `mergeable_state=dirty` — pull_request workflows will not schedule.
- exit 7: expected required check contexts are absent from the head — absence is not success.

The fake `gh` applies `--jq` expressions with the real `jq` binary (a hard dependency of the
script itself), so the stub stays faithful for any REST call shape the script uses.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "await_pr_checks"
SCRIPT = REPO_ROOT / "scripts" / "await_pr_checks.sh"

FAKE_SHA = "9c1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e"

# Serves canned REST payloads for every endpoint the script touches in merge-gating mode:
# rate_limit, pulls/<pr> (head sha + base ref + mergeable_state), the branch-protection
# required_status_checks endpoint, commits/<sha>/check-runs, and commits/<sha>/status.
# `--jq` is applied with the real jq so both the pre-fix and post-fix script shapes work.
FAKE_GH = """#!/usr/bin/env bash
set -uo pipefail
[ "${1:-}" = "api" ] || { echo "unhandled fake gh call: $*" >&2; exit 1; }
path="$2"
shift 2
jq_expr=""
while [ $# -gt 0 ]; do
  case "$1" in
    --jq) jq_expr="$2"; shift 2 ;;
    *) shift ;;
  esac
done
emit() {
  if [ -n "$jq_expr" ]; then
    printf '%s' "$1" | jq -r "$jq_expr"
  else
    printf '%s' "$1"
  fi
}
case "$path" in
  rate_limit)
    emit '{"resources":{"core":{"remaining":4999},"graphql":{"remaining":4999}}}'
    ;;
  */branches/*/protection/required_status_checks)
    if [ "${FAKE_PROTECTION_JSON:-}" = "" ]; then
      # Mimic gh's non-admin/absent-protection behavior: error, no payload.
      echo "gh: Not Found (HTTP 404)" >&2
      exit 1
    fi
    emit "$FAKE_PROTECTION_JSON"
    ;;
  *check-runs*)
    emit "$(cat "$FAKE_CHECK_RUNS_JSON")"
    if [ -n "${FAKE_AFTER_FIRST_CHECKS_JSON:-}" ]; then
      cp "$FAKE_AFTER_FIRST_CHECKS_JSON" "$FAKE_CHECK_RUNS_JSON"
    fi
    ;;
  */status)
    emit '{"state":"pending","total_count":0,"statuses":[]}'
    ;;
  */pulls/*)
    emit "{\\"head\\":{\\"sha\\":\\"$FAKE_SHA\\"},\\"base\\":{\\"ref\\":\\"${FAKE_BASE_REF:-main}\\"},\\"mergeable_state\\":\\"${FAKE_MERGEABLE_STATE:-clean}\\"}"
    ;;
  *)
    echo "unhandled fake gh api path: $path" >&2
    exit 1
    ;;
esac
"""


def _make_fake_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh_path = bin_dir / "gh"
    gh_path.write_text(FAKE_GH, encoding="utf-8")
    gh_path.chmod(gh_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_merge_gating(
    tmp_path: Path,
    fixture_name: str,
    *,
    mergeable_state: str = "clean",
    base_ref: str = "main",
    protection_json: str = "",
    repo: str | None = None,
    required_checks: tuple[str, ...] = (),
    pinned_sha: str | None = None,
) -> subprocess.CompletedProcess[str]:
    fake_bin_dir = _make_fake_gh(tmp_path)
    fixture_path = FIXTURES_DIR / fixture_name
    assert fixture_path.exists(), f"missing fixture: {fixture_path}"

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_SHA"] = FAKE_SHA
    env["FAKE_CHECK_RUNS_JSON"] = str(fixture_path)
    env["FAKE_MERGEABLE_STATE"] = mergeable_state
    env["FAKE_BASE_REF"] = base_ref
    env["FAKE_PROTECTION_JSON"] = protection_json
    env["GH_REPO"] = "RasmusTho/agentic-pkm-mvp"

    # No --sha: this is the merge-gating mode the issue's fail-closed rules apply to.
    # --timeout 0 makes the deadline immediate, so a missing-required outcome resolves on
    # the first classification pass instead of sleeping through a >=60s backoff interval.
    command = [
        "bash",
        str(SCRIPT),
        "4321",
        "--initial-wait",
        "0",
        "--interval",
        "60",
        "--timeout",
        "0",
    ]
    if repo is not None:
        command.extend(["--repo", repo])
    for required_check in required_checks:
        command.extend(["--required-check", required_check])
    if pinned_sha is not None:
        command.extend(["--sha", pinned_sha])

    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dirty_pr_state_fails_before_false_green(tmp_path: Path) -> None:
    """AC1: mergeable_state=dirty fails closed (exit 6) before any green report.

    The head carries only unrelated green check-runs (the CodeQL-from-head shape of the
    PR #4354 false green); the script must refuse before classifying them as the suite.
    """
    result = _run_merge_gating(
        tmp_path, "head_only_unrelated_green.json", mergeable_state="dirty"
    )
    assert result.returncode == 6, result.stdout + result.stderr
    assert "dirty" in result.stderr
    assert "will not schedule" in result.stderr
    assert "all required checks passed" not in result.stdout


def test_default_wait_allows_long_unit_job_to_complete_without_real_sleep(tmp_path: Path) -> None:
    fake_bin = _make_fake_gh(tmp_path)
    # First date call creates the deadline. The next observes 45 elapsed minutes:
    # the old 30-minute default exited before observing the successful next poll.
    for name, source in {
        "date": '#!/usr/bin/env bash\nif [ -f "$FAKE_CLOCK_USED" ]; then echo 2700; else touch "$FAKE_CLOCK_USED"; echo 0; fi\n',
        "sleep": "#!/usr/bin/env bash\nexit 0\n",
    }.items():
        path = fake_bin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
    checks = tmp_path / "checks.json"
    checks.write_text(
        (FIXTURES_DIR / "required_running_then_skipped_duplicate.json").read_text(),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_CLOCK_USED": str(tmp_path / "clock-used"),
        "FAKE_SHA": FAKE_SHA,
        "FAKE_CHECK_RUNS_JSON": str(checks),
        "FAKE_AFTER_FIRST_CHECKS_JSON": str(FIXTURES_DIR / "head_required_present_green.json"),
        "FAKE_MERGEABLE_STATE": "clean",
        "FAKE_BASE_REF": "main",
        "FAKE_PROTECTION_JSON": "",
        "GH_REPO": "RasmusTho/agentic-pkm-mvp",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "4321", "--initial-wait", "0"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=10, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "still running: Unit tests (not pg)" in result.stdout
    assert f"all required checks passed on {FAKE_SHA}" in result.stdout


def test_missing_required_check_names_fail_closed(tmp_path: Path) -> None:
    """AC2: a head with only unrelated green checks cannot pass — exit 7, naming the gap.

    Branch protection is unreadable (404), so the documented fallback set for base `main`
    applies: `Unit tests (not pg)`. It is absent from the head's contexts.
    """
    result = _run_merge_gating(tmp_path, "head_only_unrelated_green.json")
    assert result.returncode == 7, result.stdout + result.stderr
    assert "REQUIRED CHECKS MISSING" in result.stderr
    assert "Unit tests (not pg)" in result.stderr
    assert "all required checks passed" not in result.stdout


def test_target_repo_profile_prevents_hub_fallback(tmp_path: Path) -> None:
    """A foreign repo checks its explicit profile, even when Hub fallback checks are green."""
    result = _run_merge_gating(
        tmp_path,
        "head_required_present_green.json",
        repo="RasmusTho/bifrost",
        required_checks=("Swift lint + package + app builds",),
    )
    assert result.returncode == 7, result.stdout + result.stderr
    assert "required checks (caller-profile:RasmusTho/bifrost)" in result.stdout
    assert "Swift lint + package + app builds" in result.stderr
    assert "Unit tests (not pg)" not in result.stdout + result.stderr
    assert "all required checks passed" not in result.stdout


def test_hub_main_uses_documented_fallback(tmp_path: Path) -> None:
    """An unreadable Hub main protection endpoint retains the documented context."""
    result = _run_merge_gating(tmp_path, "head_required_present_green.json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "required checks (documented-fallback:main): Unit tests (not pg)" in result.stdout
    assert "all required checks passed" in result.stdout


def test_missing_foreign_repo_profile_fails_closed(tmp_path: Path) -> None:
    """Foreign-repo green checks cannot pass without readable protection or a profile."""
    result = _run_merge_gating(
        tmp_path,
        "head_required_present_green.json",
        repo="RasmusTho/bifrost",
    )
    assert result.returncode == 64, result.stdout + result.stderr
    assert "required-check configuration unavailable" in result.stderr
    assert "--required-check '<context>'" in result.stderr
    assert "all required checks passed" not in result.stdout


def test_invalid_foreign_repo_profile_fails_closed(tmp_path: Path) -> None:
    """A blank caller context is rejected as configuration error, not ignored."""
    result = _run_merge_gating(
        tmp_path,
        "head_required_present_green.json",
        repo="RasmusTho/bifrost",
        required_checks=("   ",),
    )
    assert result.returncode == 64, result.stdout + result.stderr
    assert "--required-check needs one non-empty context" in result.stderr
    assert "all required checks passed" not in result.stdout


def test_foreign_repo_sha_mode_remains_diagnostic_without_profile(tmp_path: Path) -> None:
    """Pinned-SHA inspection skips merge-gating config and presence checks."""
    result = _run_merge_gating(
        tmp_path,
        "head_only_unrelated_green.json",
        repo="RasmusTho/bifrost",
        pinned_sha=FAKE_SHA,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "diagnostic, NOT a merge gate" in result.stderr
    assert "required-check configuration unavailable" not in result.stderr


def test_live_branch_protection_overrides_foreign_repo_profile(tmp_path: Path) -> None:
    """Readable target protection remains authoritative over a caller-supplied profile."""
    result = _run_merge_gating(
        tmp_path,
        "head_required_present_green.json",
        repo="RasmusTho/bifrost",
        required_checks=("Unit tests (not pg)",),
        protection_json='{"contexts":["Swift required"],"checks":[]}',
    )
    assert result.returncode == 7, result.stdout + result.stderr
    assert "required checks (branch-protection:main): Swift required" in result.stdout
    assert "Swift required" in result.stderr
    assert "all required checks passed" not in result.stdout


def test_required_checks_present_green_still_passes(tmp_path: Path) -> None:
    """Regression guard: a head carrying the required context green still exits 0."""
    result = _run_merge_gating(tmp_path, "head_required_present_green.json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all required checks passed" in result.stdout


def test_live_branch_protection_contexts_take_precedence(tmp_path: Path) -> None:
    """Resolution order: readable branch-protection contexts override the documented fallback.

    Live protection requires `smoke`, which the head lacks even though the fallback set's
    `Unit tests (not pg)` is present and green — so the waiter must still fail closed.
    """
    result = _run_merge_gating(
        tmp_path,
        "head_required_present_green.json",
        protection_json='{"contexts":["smoke"],"checks":[{"context":"smoke","app_id":15368}]}',
    )
    assert result.returncode == 7, result.stdout + result.stderr
    assert "smoke" in result.stderr
    assert "all required checks passed" not in result.stdout
