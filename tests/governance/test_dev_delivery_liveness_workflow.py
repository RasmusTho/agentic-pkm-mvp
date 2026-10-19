"""The post-merge dev controller liveness check stays fail-loud (#6222)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

from scripts import dev_delivery_liveness as liveness
from scripts import postmerge_dev_test as controller

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/dev-delivery-liveness.yml"
NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
SHA = "a" * 40


def _build(hours_ago: float) -> liveness.AdmittedBuild:
    return liveness.AdmittedBuild(SHA, NOW - timedelta(hours=hours_ago), 123)


def _status(context: str, hours_ago: float, state: str = "success") -> dict[str, str]:
    stamp = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"context": context, "state": state, "created_at": stamp, "updated_at": stamp}


def test_liveness_check_reds_on_missing_dev_verdict() -> None:
    result = liveness.evaluate(
        _build(7),
        heartbeat_statuses=[_status(liveness.HEARTBEAT_CONTEXT, 0.1)],
        verdict_statuses=[],
        now=NOW,
    )
    assert not result.ok
    assert result.reason == "missing_dev_verdict"


def test_liveness_check_reds_on_missing_heartbeat() -> None:
    build = _build(1)
    verdict = [_status(liveness.VERDICT_CONTEXT, 0.5)]
    stale = liveness.evaluate(
        build,
        heartbeat_statuses=[],
        verdict_statuses=[],
        now=NOW,
    )
    assert not stale.ok
    assert stale.reason == "heartbeat_missing"

    fresh = liveness.evaluate(
        build,
        heartbeat_statuses=[],
        verdict_statuses=verdict,
        now=NOW,
    )
    assert fresh.ok
    assert fresh.reason == "fresh_dev_verdict"


def test_workflow_is_scheduled_read_only_and_calls_production_checker() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]
    assert triggers["schedule"] and "workflow_dispatch" in triggers
    assert workflow["permissions"] == {"contents": "read", "actions": "read", "statuses": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["liveness"]
    run = job["steps"][-1]["run"]
    assert "scripts/dev_delivery_liveness.py" in run
    assert "deployment" not in run.lower()
    assert "secrets" not in WORKFLOW.read_text(encoding="utf-8")


def test_controller_latest_entrypoint_publishes_heartbeat_and_wires_dev_verdict(monkeypatch, tmp_path: Path) -> None:
    heartbeat = []
    poll_kwargs = []
    monkeypatch.setattr(controller, "_current_main", lambda: SHA)
    monkeypatch.setattr(controller, "publish_heartbeat", heartbeat.append)

    def fake_poll(path: Path, **kwargs: object) -> int:
        poll_kwargs.append((path, kwargs))
        return 0

    monkeypatch.setattr(controller, "poll", fake_poll)
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 0
    assert heartbeat == [SHA]
    assert poll_kwargs[0][1]["signal"] is controller.publish_dev_verdict


def test_controller_status_signals_use_bounded_github_status_calls(monkeypatch) -> None:
    calls = []

    def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", run)
    candidate = controller.Candidate(SHA, "sha256:" + "b" * 64, 123, 1, 456)
    controller.publish_heartbeat(SHA)
    controller.publish_dev_verdict(candidate, {"result": "passed"})
    contexts = [call[0][6].split("=", 1)[1] for call in calls]
    assert contexts == [controller.DEV_HEARTBEAT_CONTEXT, controller.DEV_VERDICT_CONTEXT]
    assert all(call[0][:3] == ["gh", "api", f"repos/{controller.REPOSITORY}/statuses/{SHA}"] for call in calls)


def test_checker_reads_latest_admitted_build_and_both_status_surfaces() -> None:
    completed = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    head_sha = "c" * 40
    seen = []

    def api(path: str):
        seen.append(path)
        if "actions/workflows" in path:
            return {"workflow_runs": [{"id": 123, "status": "completed", "conclusion": "success",
                                       "head_branch": "main", "head_sha": SHA, "path": liveness.BUILD_WORKFLOW,
                                       "updated_at": completed, "repository": {"full_name": "o/r"}}]}
        if path.endswith(f"commits/{SHA}/statuses?per_page=100"):
            return [_status(liveness.VERDICT_CONTEXT, 0.5)]
        return [_status(liveness.HEARTBEAT_CONTEXT, 0.1)]

    result = liveness.check("o/r", head_sha, api=api, now=NOW)
    assert result.ok and result.reason == "fresh_dev_verdict"
    assert any("actions/workflows/app-image-build.yml/runs" in path for path in seen)
    assert any(path.endswith(f"commits/{SHA}/statuses?per_page=100") for path in seen)
    assert any(path.endswith(f"commits/{head_sha}/statuses?per_page=100") for path in seen)
