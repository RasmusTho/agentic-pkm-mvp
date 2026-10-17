"""The post-merge heavy-tests verdict stays authoritative and fail-loud (#6158)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts import post_merge_heavy_tests_verdict as verdict

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/post-merge-heavy-tests.yml"
SHA = "a" * 40
NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
INPUTS = {"sha": SHA, "verdict": "passed", "operation_id": "d00400e2-f07d-4fa1-a2a0-272903fdc693",
          "counts": "selected=500 passed=490 failed=0 skipped=10 docker_skipped=0", "reason": "", "failures": ""}


def _commit(sha: str, hours_ago: float) -> dict:
    date = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"sha": sha, "commit": {"committer": {"date": date}}}


def _api(compare_status: str = "ahead", commits=(), statuses=None):
    statuses = statuses or {}

    def api(path: str):
        if "/compare/" in path:
            return {"status": compare_status}
        if "/statuses" in path:
            sha = path.split("/commits/")[1].split("/")[0]
            return [{"context": c} for c in statuses.get(sha, ())]
        if "/commits?" in path:
            return list(commits)
        raise AssertionError(path)

    return api


def test_verdict_mode_and_watchdog_fail_loud() -> None:
    # A host verdict for a commit on main records a ygg status.
    resolution = verdict.resolve("workflow_dispatch", INPUTS, "f" * 40, "o/r", api=_api())
    assert (resolution.mode, resolution.sha) == ("verdict", SHA)
    assert resolution.description.startswith("ygg-test passed: selected=500")
    failed = verdict.resolve("workflow_dispatch", {**INPUTS, "verdict": "failed",
                                                   "failures": "tests/deploy/test_a.py::test_x"},
                             "f" * 40, "o/r", api=_api())
    assert failed.mode == "verdict" and "tests/deploy/test_a.py::test_x" in failed.reason
    refused = verdict.resolve("workflow_dispatch", {**INPUTS, "verdict": "refused", "counts": "",
                                                    "reason": "docker_cli_unavailable"}, "f" * 40, "o/r", api=_api())
    assert "docker_cli_unavailable" in refused.reason

    # Off-main or malformed verdicts are refused, never recorded as green.
    with pytest.raises(verdict.VerdictRefused):
        verdict.resolve("workflow_dispatch", INPUTS, "f" * 40, "o/r", api=_api(compare_status="diverged"))
    for broken in ({"sha": "abc"}, {"verdict": "green"}, {"operation_id": "x"}, {"counts": "selected=1; rm"},
                   {"verdict": "refused"}, {"failures": "tests/a.py::t"}, {"reason": "Bad Reason"},
                   {"failures": "x\ny", "verdict": "failed"}):
        with pytest.raises(verdict.VerdictRefused):
            verdict.validate_verdict({**INPUTS, **broken})

    # Manual dispatch without a verdict runs the GitHub-hosted job.
    manual = verdict.resolve("workflow_dispatch", {}, "f" * 40, "o/r", api=_api())
    assert (manual.mode, manual.sha) == ("fallback", "f" * 40)

    # Watchdog: nothing older than the grace period -> noop.
    commits = [_commit("c" * 40, 1), _commit("b" * 40, 2)]
    assert verdict.resolve("schedule", {}, "", "o/r", api=_api(commits=commits), now=NOW).mode == "noop"
    # A verdict on the due commit or any newer one -> noop.
    commits = [_commit("c" * 40, 1), _commit("b" * 40, 7), _commit(SHA, 9)]
    ok = _api(commits=commits, statuses={"c" * 40: {verdict.YGG_CONTEXT}})
    assert verdict.resolve("schedule", {}, "", "o/r", api=ok, now=NOW).mode == "noop"
    # Missing verdict -> fallback for the newest due commit.
    missing = verdict.resolve("schedule", {}, "", "o/r", api=_api(commits=commits), now=NOW)
    assert (missing.mode, missing.sha) == ("fallback", "b" * 40)
    assert "no ygg verdict" in missing.reason
    # An earlier fallback for that commit is not rerun every hour.
    done = _api(commits=commits, statuses={"b" * 40: {verdict.FALLBACK_CONTEXT}})
    assert verdict.resolve("schedule", {}, "", "o/r", api=done, now=NOW).mode == "noop"


def test_verdict_cli_routes_refusal_to_red_mode(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, "scripts/post_merge_heavy_tests_verdict.py", "--event", "workflow_dispatch",
         "--inputs", json.dumps({**INPUTS, "verdict": "green"}), "--github-sha", "f" * 40,
         "--repo", "o/r", "--github-output", str(output)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert fields["mode"] == "refused" and fields["sha"] == SHA, result.stdout


def test_workflow_records_status_and_keeps_rolling_alert() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]  # PyYAML parses the bare `on:` key as boolean True.
    assert "push" not in triggers, "the per-push GitHub-hosted run is retired"
    assert triggers["schedule"] and set(triggers["workflow_dispatch"]["inputs"]) == {
        "sha", "verdict", "operation_id", "counts", "reason", "failures"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]

    resolve = jobs["resolve"]["steps"][-1]
    assert "scripts/post_merge_heavy_tests_verdict.py" in resolve["run"]
    # Dispatch inputs reach the script through env, never interpolated into shell.
    assert "${{" not in resolve["run"]

    record = jobs["record-verdict"]
    assert record["permissions"] == {"statuses": "write"}
    script = record["steps"][-1]["run"]
    assert "post-merge-heavy-tests/ygg" in script and "${{" not in script
    assert 'exit 1' in script and script.rstrip().endswith('[[ "$state" == "success" ]]')

    fallback = jobs["heavy-tests"]
    assert fallback["if"] == "needs.resolve.outputs.mode == 'fallback'"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "post-merge-heavy-tests/fallback" in text

    alert = jobs["alert"]
    assert alert["needs"] == ["resolve", "record-verdict", "heavy-tests"]
    assert "always()" in alert["if"] and "cancelled" in alert["if"] and "'noop'" in alert["if"]
    assert alert["permissions"]["issues"] == "write"
    script = alert["steps"][-1]["run"]
    assert "gh issue create" in script and "scripts/post_merge_heavy_tests_alert.py" in script
    assert "gh issue comment" in script and "gh issue close" in script
    # Green only for a recorded passing verdict or a manual run; a watchdog
    # fallback is red even when its tests pass.
    assert 'MODE" == "verdict" && "$VERDICT_RESULT" == "success"' in script
    assert script.rstrip().endswith("exit 1")


def test_owner_docs_describe_vm_verdict() -> None:
    strategy = (ROOT / "docs/development/TEST_STRATEGY_HOT_PATH.md").read_text(encoding="utf-8")
    section = strategy.split("## Post-merge heavy tests", 1)[1].split("\n## ", 1)[0]
    for phrase in ("qualify-heavy", "postmerge-heavy.v1", "post-merge-heavy-tests/ygg",
                   "post-merge-heavy-tests/fallback", "6 hours", "per-push GitHub-hosted run is retired",
                   "prio:high"):
        assert phrase in section, phrase
    deployment = (ROOT / "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md").read_text(encoding="utf-8")
    assert "qualify-heavy test <operation-id>" in deployment
    testing = (ROOT / "docs/TESTING.md").read_text(encoding="utf-8")
    assert "post-merge-heavy-tests/ygg" in testing
