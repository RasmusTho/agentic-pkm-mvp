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
    pending_verdict = [_status(liveness.VERDICT_CONTEXT, 0.5, state="pending")]
    stale = liveness.evaluate(
        build,
        heartbeat_statuses=[],
        verdict_statuses=[],
        now=NOW,
    )
    assert not stale.ok
    assert stale.reason == "heartbeat_missing"

    pending = liveness.evaluate(
        build,
        heartbeat_statuses=[],
        verdict_statuses=pending_verdict,
        now=NOW,
    )
    assert not pending.ok
    assert pending.reason == "heartbeat_missing"

    fresh = liveness.evaluate(
        build,
        heartbeat_statuses=[],
        verdict_statuses=verdict,
        now=NOW,
    )
    assert fresh.ok
    assert fresh.reason == "fresh_dev_verdict"

    stale_verdict = liveness.evaluate(
        build,
        heartbeat_statuses=[],
        verdict_statuses=[_status(liveness.VERDICT_CONTEXT, 3)],
        now=NOW,
    )
    assert not stale_verdict.ok
    assert stale_verdict.reason == "heartbeat_missing"

    future_verdict = liveness.evaluate(
        build,
        heartbeat_statuses=[],
        verdict_statuses=[_status(liveness.VERDICT_CONTEXT, -1)],
        now=NOW,
    )
    assert not future_verdict.ok
    assert future_verdict.reason == "heartbeat_missing"


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


def test_signal_writer_uses_approved_actions_dispatch_boundary() -> None:
    heavy_workflow = yaml.safe_load((ROOT / ".github/workflows/post-merge-heavy-tests.yml").read_text())
    signal_job = heavy_workflow["jobs"]["record-liveness-signal"]
    assert signal_job["permissions"] == {"statuses": "write"}
    assert signal_job["if"] == (
        "github.event_name == 'workflow_dispatch' && "
        "github.event.inputs.liveness_signal == 'status'"
    )
    resolve = heavy_workflow["jobs"]["resolve"]
    assert "liveness_signal != 'status'" in resolve["if"]


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


def test_controller_status_signals_use_bounded_actions_dispatch(monkeypatch) -> None:
    calls = []

    def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(controller.subprocess, "run", run)
    candidate = controller.Candidate(SHA, "sha256:" + "b" * 64, 123, 1, 456)
    controller.publish_heartbeat(SHA)
    controller.publish_dev_verdict(candidate, {"result": "passed"})
    contexts = [next(arg.split("=", 1)[1] for arg in call[0] if arg.startswith("liveness_context="))
                for call in calls]
    assert contexts[0].startswith(controller.DEV_HEARTBEAT_CONTEXT + "/")
    assert contexts[1] == controller.DEV_VERDICT_CONTEXT
    assert all(call[0][:3] == ["gh", "workflow", "run"] for call in calls)
    assert all("post-merge-heavy-tests.yml" in call[0] for call in calls)
    assert all("liveness_signal=status" in call[0] for call in calls)


def test_checker_reads_latest_admitted_build_and_both_status_surfaces() -> None:
    completed = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    head_sha = "c" * 40
    seen = []

    def api(path: str):
        seen.append(path)
        if "actions/workflows" in path:
            return {"workflow_runs": [{"id": 123, "status": "completed", "conclusion": "success",
                                       "event": "push", "head_branch": "main", "head_sha": SHA,
                                       "path": liveness.BUILD_WORKFLOW, "completed_at": completed,
                                       "repository": {"full_name": "o/r"},
                                       "head_repository": {"full_name": "o/r"}}]}
        if path.endswith(f"commits/{SHA}/statuses?per_page=100&page=1"):
            return [_status(liveness.VERDICT_CONTEXT, 0.5)]
        return [_status(liveness.HEARTBEAT_CONTEXT, 0.1)]

    result = liveness.check("o/r", head_sha, api=api, now=NOW)
    assert result.ok and result.reason == "fresh_dev_verdict"
    assert any("actions/workflows/app-image-build.yml/runs" in path for path in seen)
    assert any(path.endswith(f"commits/{SHA}/statuses?per_page=100&page=1") for path in seen)
    assert any(path.endswith(f"commits/{head_sha}/statuses?per_page=100&page=1") for path in seen)


def test_checker_reads_verdict_from_later_status_page() -> None:
    build = _build(7)
    pages = {
        1: [_status(liveness.HEARTBEAT_CONTEXT, 0.1)] * 100,
        2: [_status(liveness.VERDICT_CONTEXT, 0.5)],
    }

    def api(path: str):
        if "actions/workflows" in path:
            return {"workflow_runs": [{"id": 123, "status": "completed", "conclusion": "success",
                                       "event": "push", "head_branch": "main", "head_sha": SHA,
                                       "path": liveness.BUILD_WORKFLOW,
                                       "completed_at": build.completed_at.isoformat(),
                                       "repository": {"full_name": "o/r"},
                                       "head_repository": {"full_name": "o/r"}}]}
        page = int(path.rsplit("page=", 1)[1])
        return pages[page]

    result = liveness.check("o/r", SHA, api=api, now=NOW)
    assert result.ok and result.reason == "fresh_dev_verdict"


def test_latest_admitted_build_uses_creation_order_and_paginates_failures() -> None:
    newer = {"id": 200, "status": "completed", "conclusion": "success", "event": "push",
             "head_branch": "main", "head_sha": "b" * 40, "path": liveness.BUILD_WORKFLOW,
             "created_at": "2026-10-19T10:00:00Z", "completed_at": "2026-10-19T10:05:00Z",
             "repository": {"full_name": "o/r"}, "head_repository": {"full_name": "o/r"}}
    rerun_old = {**newer, "id": 100, "head_sha": SHA, "created_at": "2026-10-19T09:00:00Z",
                 "completed_at": "2026-10-19T11:00:00Z"}
    failed = {**newer, "id": 300, "conclusion": "failure", "created_at": "2026-10-19T11:00:00Z"}

    def api(path: str):
        page = int(path.rsplit("page=", 1)[1])
        return {"workflow_runs": ([failed, newer, rerun_old] if page == 1 else [])}

    admitted = liveness.latest_admitted_build("o/r", api=api)
    assert admitted is not None
    assert admitted.sha == "b" * 40
    assert admitted.run_id == 200
