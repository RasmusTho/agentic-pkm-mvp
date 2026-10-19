"""The post-merge dev controller liveness check stays fail-loud (#6222)."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import io
import json
import subprocess
from zipfile import ZipFile

import pytest

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
    return {"context": context, "state": state, "created_at": stamp, "updated_at": stamp,
            "description": "observed_at=" + stamp}


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

    recorded_verdict = liveness.evaluate(
        _build(7),
        heartbeat_statuses=[_status(liveness.HEARTBEAT_CONTEXT, 0.1)],
        verdict_statuses=[_status(liveness.VERDICT_CONTEXT, 3)],
        now=NOW,
    )
    assert recorded_verdict.ok
    assert recorded_verdict.reason == "dev_verdict_recorded"

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
    workflow = yaml.safe_load(WORKFLOW.read_text())
    job = workflow["jobs"]["record-signal"]
    assert job["permissions"] == {"contents": "read", "actions": "read", "statuses": "write"}
    for fence in ("github.ref == 'refs/heads/main'", "github.actor == github.repository_owner",
                  "github.triggering_actor == github.repository_owner"):
        assert fence in job["if"]
    assert job["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    assert "--record-signal" in job["steps"][-1]["run"]
    heavy = yaml.safe_load((ROOT / ".github/workflows/post-merge-heavy-tests.yml").read_text())
    assert "record-liveness-signal" not in heavy["jobs"]
    assert "liveness" not in heavy["concurrency"]["group"]


def _native_receipt(channel, candidate):
    from app.ops.pg_acceptance import MINIMUM_SELECTED, identity
    op = candidate.operation_id(channel)
    return {"channel": channel, "terminal_result": "committed", "operation_id": op,
            "pg_acceptance": {**identity(candidate.sha, candidate.digest, channel, op),
                "result": "passed", "selected": MINIMUM_SELECTED, "passed": MINIMUM_SELECTED,
                "resource_tree": "e" * 40, "app_image_id": "sha256:" + "f" * 64, "report_hash": "0" * 64}}


class _GitHubTransport:
    """API-boundary double: real admission, polling, persistence and writers run."""
    def __init__(self):
        self.candidate = controller.Candidate(SHA, "sha256:" + "b" * 64, 123, 1, 456)
        self.run = {"id": 123, "run_attempt": 1, "event": "push", "status": "completed",
                    "conclusion": "success", "head_branch": "main", "head_sha": SHA,
                    "path": controller.BUILD_WORKFLOW,
                    "repository": {"full_name": controller.REPOSITORY},
                    "head_repository": {"full_name": controller.REPOSITORY}}
        proof = {"contract": "app-image-tts-engine-proof.v1", "candidate_sha": SHA,
                 "image": controller.IMAGE_REPOSITORY + ":" + SHA,
                 "image_ref": controller.IMAGE_REPOSITORY + "@" + self.candidate.digest,
                 "image_index_digest": self.candidate.digest,
                 "probe_scope": "package_presence_cli_load_import_app_health",
                 "platforms": [{"platform": p, "platform_digest": self.candidate.digest, "probe_result": "pass"}
                               for p in ("linux/amd64", "linux/arm64")]}
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("app-image-tts-engine-proof.json", json.dumps(proof))
        self.archive = stream.getvalue()
        self.metadata = {"id": 456, "name": "app-image-tts-engine-proof-" + SHA, "expired": False,
                         "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest(),
                         "size_in_bytes": len(self.archive)}
        self.dispatches = []
        self.writes = []
        self.denied_writes = []
        self.reads = []
        self.actions = False
        self.compare = "identical"
        self.fail_dispatch = False
        self.failed_workflows = set()

    @property
    def liveness_dispatches(self):
        return [command for command in self.dispatches if command[3] == "dev-delivery-liveness.yml"]

    @property
    def channel_dispatches(self):
        return [command for command in self.dispatches if command[3] == "postmerge-channel-bug.yml"]

    def __call__(self, argv, **kwargs):
        if argv[:3] == ["gh", "workflow", "run"]:
            self.dispatches.append(argv)
            return SimpleNamespace(returncode=int(self.fail_dispatch or argv[3] in self.failed_workflows),
                                   stdout="", stderr="")
        assert argv[:2] == ["gh", "api"], argv
        path = argv[2]
        if "/statuses/" in path:
            if not self.actions:
                self.denied_writes.append(argv)
                raise subprocess.CalledProcessError(403, argv)
            self.writes.append(argv)
            data = {}
        else:
            self.reads.append(path)
            if path.endswith("commits/main"):
                data = {"sha": SHA}
            elif "/compare/" in path:
                data = {"status": self.compare}
            elif "/workflows/" in path:
                data = {"workflow_runs": [self.run]}
            elif path.endswith("actions/runs/123"):
                data = self.run
            elif "/jobs?" in path:
                data = {"total_count": 1, "jobs": [{"name": controller.BUILD_JOB, "run_id": 123,
                        "run_attempt": 1, "status": "completed", "conclusion": "success"}]}
            elif "/artifacts?" in path:
                data = {"total_count": 1, "artifacts": [self.metadata]}
            elif path.endswith("/zip"):
                return SimpleNamespace(returncode=0, stdout=self.archive, stderr=b"")
            else:
                raise AssertionError(path)
        out = json.dumps(data)
        return SimpleNamespace(returncode=0, stdout=out if kwargs.get("text") else out.encode(), stderr="")


def _writer_env(monkeypatch):
    for key, value in {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
                       "GITHUB_ACTOR": "RasmusTho", "GITHUB_TRIGGERING_ACTOR": "RasmusTho",
                       "RUN_URL": f"https://github.com/{controller.REPOSITORY}/actions/runs/999"}.items():
        monkeypatch.setenv(key, value)


def _writer_main(kind, payload):
    return liveness.main(["--repo", controller.REPOSITORY, "--github-sha", SHA,
                          "--record-signal", "--kind", kind, "--payload", json.dumps(payload)])


def _verdict_payload(candidate):
    return {"protocol": controller.LIVENESS_PROTOCOL, "sha": candidate.sha,
            "observed_at": datetime.now(timezone.utc).isoformat(), "candidate": asdict(candidate),
            "result": "passed", "operation_id": candidate.operation_id("dev")}


def test_controller_latest_entrypoint_publishes_heartbeat_and_wires_dev_verdict(monkeypatch, tmp_path):
    transport = _GitHubTransport()
    monkeypatch.setattr(controller.subprocess, "run", transport)
    channels = []

    def native(channel, candidate):
        channels.append(channel)
        return _native_receipt(channel, candidate)

    monkeypatch.setattr(controller, "native_deploy", native)
    tmp_path.chmod(0o700)
    # No production main/poll/deliver/admission/publisher helper is replaced.
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 0
    assert channels == ["dev", "test"]
    assert not transport.denied_writes and not transport.writes
    checkpoint = json.loads((tmp_path / "postmerge-dev-test.json").read_text())
    assert (checkpoint["phase"], checkpoint["channel"]) == ("passed", "test")
    assert len(transport.liveness_dispatches) == 2
    assert len(transport.channel_dispatches) == 2
    assert checkpoint["last_green"] == {"dev": SHA, "test": SHA}
    assert checkpoint["channel_bug"]["dispatch"] == "sent"
    for command, channel in zip(transport.channel_dispatches, ("dev", "test"), strict=True):
        fields = dict(item.split("=", 1) for item in command if "=" in item)
        evidence = json.loads(fields["evidence"])
        assert controller.validate_channel_evidence(evidence, channel) == transport.candidate
    transport.actions = True
    _writer_env(monkeypatch)
    for command in transport.liveness_dispatches:
        assert command[3] == "dev-delivery-liveness.yml"
        assert command[command.index("--ref") + 1] == "main"
        fields = dict(item.split("=", 1) for item in command if "=" in item)
        assert _writer_main(fields["kind"], json.loads(fields["payload"])) == 0
    contexts = [next(arg for arg in call if arg.startswith("context=")) for call in transport.writes]
    assert contexts[0].startswith("context=" + liveness.HEARTBEAT_CONTEXT + "/")
    assert contexts[1] == "context=" + liveness.VERDICT_CONTEXT
    assert any("/artifacts/456/zip" in path for path in transport.reads)


@pytest.mark.parametrize("fault", ["actor", "rerun_actor", "ref", "kind", "protocol", "context",
                                     "foreign_sha", "failed_build", "foreign_build", "candidate",
                                     "operation", "stale", "future", "artifact"])
def test_actions_writer_refuses_unqualified_signal_before_status_write(monkeypatch, fault):
    transport = _GitHubTransport()
    transport.actions = True
    monkeypatch.setattr(liveness.subprocess, "run", transport)
    _writer_env(monkeypatch)
    signal = _verdict_payload(transport.candidate)
    kind = "verdict"
    if fault == "actor":
        monkeypatch.setenv("GITHUB_ACTOR", "other-actions-client")
    elif fault == "rerun_actor":
        monkeypatch.setenv("GITHUB_TRIGGERING_ACTOR", "other-actions-client")
    elif fault == "ref":
        monkeypatch.setenv("GITHUB_REF", "refs/heads/unadmitted")
    elif fault == "kind":
        kind = "status"
    elif fault == "protocol":
        signal["protocol"] = "generic-status.v1"
    elif fault == "context":
        signal["context"] = "post-merge-heavy-tests/ygg"
    elif fault == "foreign_sha":
        transport.compare = "diverged"
    elif fault == "failed_build":
        transport.run["conclusion"] = "failure"
    elif fault == "foreign_build":
        transport.run["head_repository"] = {"full_name": "other/repo"}
    elif fault == "candidate":
        signal["candidate"]["digest"] = "sha256:" + "c" * 64
    elif fault == "operation":
        signal["operation_id"] = transport.candidate.operation_id("test")
    elif fault == "stale":
        signal["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    elif fault == "future":
        signal["observed_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    else:
        transport.metadata["digest"] = "sha256:" + "0" * 64
    assert _writer_main(kind, signal) == 1
    assert not transport.writes


@pytest.mark.parametrize("failed_workflows", [
    {"dev-delivery-liveness.yml"},
    {"postmerge-channel-bug.yml"},
    {"dev-delivery-liveness.yml", "postmerge-channel-bug.yml"},
])
def test_controller_signal_transport_failure_keeps_native_progress(monkeypatch, tmp_path, failed_workflows):
    transport = _GitHubTransport()
    transport.failed_workflows = failed_workflows
    monkeypatch.setattr(controller.subprocess, "run", transport)
    monkeypatch.setattr(controller.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(controller, "native_deploy", _native_receipt)
    tmp_path.chmod(0o700)
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 0
    expected_signals = 6 if "dev-delivery-liveness.yml" in failed_workflows else 2
    assert len(transport.liveness_dispatches) == expected_signals
    assert len(transport.channel_dispatches) == 2
    assert not transport.denied_writes and not transport.writes
    checkpoint = json.loads((tmp_path / "postmerge-dev-test.json").read_text())
    assert (checkpoint["phase"], checkpoint["channel"]) == ("passed", "test")
    assert checkpoint["last_green"] == {"dev": SHA, "test": SHA}
    expected_report = "failed" if "postmerge-channel-bug.yml" in failed_workflows else "sent"
    assert checkpoint["channel_bug"]["dispatch"] == expected_report


def test_heartbeat_queue_cannot_displace_terminal_signals():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    expression = workflow["concurrency"]["group"]
    assert expression == ("post-merge-dev-liveness-${{ github.event.inputs.kind == 'heartbeat' "
                          "&& 'heartbeat' || github.run_id }}")
    assert workflow["concurrency"]["cancel-in-progress"] is False

    def group(kind, run_id):
        return "post-merge-dev-liveness-" + ("heartbeat" if kind == "heartbeat" else str(run_id))

    # Documented GitHub single-pending replacement, using the actual expression.
    queues = {}
    cancelled = []
    for kind, run_id in [("heartbeat", 1), ("heartbeat", 2), ("verdict", 3),
                         ("heartbeat", 4), ("verdict", 5)]:
        queue = queues.setdefault(group(kind, run_id), [])
        if len(queue) == 2:
            cancelled.append(queue.pop())
        queue.append((kind, run_id))
    assert cancelled == [("heartbeat", 2)]
    assert queues[group("verdict", 3)] == [("verdict", 3)]
    assert queues[group("verdict", 5)] == [("verdict", 5)]
    heavy = yaml.safe_load((ROOT / ".github/workflows/post-merge-heavy-tests.yml").read_text())
    assert heavy["concurrency"]["group"].startswith("post-merge-heavy-tests-")


def test_status_transport_time_cannot_refresh_an_old_observation():
    replayed = _status(liveness.HEARTBEAT_CONTEXT, 3)
    replayed["updated_at"] = NOW.isoformat()
    replayed["created_at"] = NOW.isoformat()
    result = liveness.evaluate(None, heartbeat_statuses=[replayed], verdict_statuses=[], now=NOW)
    assert not result.ok and result.reason == "heartbeat_stale"


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


def test_latest_verdict_supersedes_older_unverdict_builds() -> None:
    newest_sha = "e" * 40
    older_sha = "f" * 40

    def run(sha: str, hours_ago: float, run_id: int) -> dict[str, object]:
        stamp = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
        return {
            "id": run_id,
            "status": "completed",
            "conclusion": "success",
            "event": "push",
            "head_branch": "main",
            "head_sha": sha,
            "path": liveness.BUILD_WORKFLOW,
            "created_at": stamp,
            "completed_at": stamp,
            "repository": {"full_name": "o/r"},
            "head_repository": {"full_name": "o/r"},
        }

    runs = [run(newest_sha, 1, 2), run(older_sha, 24, 1)]

    def api(path: str):
        if "actions/workflows" in path:
            return {"workflow_runs": runs}
        if f"commits/{newest_sha}/statuses" in path:
            return [
                _status(liveness.HEARTBEAT_CONTEXT, 0.1),
                _status(liveness.VERDICT_CONTEXT, 0.5),
            ]
        return []

    result = liveness.check("o/r", newest_sha, api=api, now=NOW)
    assert result.ok
    assert result.reason == "fresh_dev_verdict"


@pytest.mark.parametrize(("newest_age", "preceding_age", "verdict_age", "heartbeat_age", "state", "expected_ok"), [
    (.25, 1, .1, None, "success", True),
    (.25, 1, .1, 3, "success", True),
    (.25, 1, .1, None, "failure", True),
    (.25, 1, .1, 3, "failure", True),
    (.25, 4, 3, None, "success", False),
    (.25, 4, 3, 3, "success", False),
    (.25, 4, 3, .1, "success", True),
    (7, 8, .1, None, "success", False),
    (7, 8, .1, 3, "success", False),
    (7, 8, .1, .1, "success", False),
])
def test_preceding_terminal_activity_recovers_only_within_newer_build_grace(
    newest_age, preceding_age, verdict_age, heartbeat_age, state, expected_ok,
):
    newest, preceding, skipped = "b" * 40, "c" * 40, "d" * 40
    runs = []
    for sha, age, run_id in ((newest, newest_age, 3), (preceding, preceding_age, 2), (skipped, 24, 1)):
        stamp = (NOW - timedelta(hours=age)).isoformat()
        runs.append({"id": run_id, "status": "completed", "conclusion": "success", "event": "push",
                     "head_branch": "main", "head_sha": sha, "path": liveness.BUILD_WORKFLOW,
                     "created_at": stamp, "completed_at": stamp,
                     "repository": {"full_name": "o/r"}, "head_repository": {"full_name": "o/r"}})

    def api(path):
        if "actions/workflows" in path:
            return {"workflow_runs": runs}
        if f"commits/{preceding}/statuses" in path:
            return [_status(liveness.VERDICT_CONTEXT, verdict_age, state)]
        if f"commits/{newest}/statuses" in path and heartbeat_age is not None:
            return [_status(liveness.HEARTBEAT_CONTEXT, heartbeat_age)]
        return []

    result = liveness.check("o/r", newest, api=api, now=NOW)
    assert result.ok is expected_ok
    if expected_ok and verdict_age <= 2:
        assert result.reason == "fresh_dev_verdict"
        assert preceding[:12] in result.description


def test_checker_grace_does_not_reset_for_continuous_builds() -> None:
    head_sha = "b" * 40
    middle_sha = "c" * 40
    overdue_sha = "d" * 40

    def run(sha: str, hours_ago: float, run_id: int) -> dict[str, object]:
        stamp = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
        return {
            "id": run_id,
            "status": "completed",
            "conclusion": "success",
            "event": "push",
            "head_branch": "main",
            "head_sha": sha,
            "path": liveness.BUILD_WORKFLOW,
            "created_at": stamp,
            "completed_at": stamp,
            "repository": {"full_name": "o/r"},
            "head_repository": {"full_name": "o/r"},
        }

    runs = [run(head_sha, 0.5, 3), run(middle_sha, 3, 2), run(overdue_sha, 7, 1)]

    def api(path: str):
        if "actions/workflows" in path:
            return {"workflow_runs": runs}
        if f"commits/{head_sha}/statuses" in path:
            return [_status(liveness.HEARTBEAT_CONTEXT, 0.1)]
        return []

    result = liveness.check("o/r", head_sha, api=api, now=NOW)
    assert not result.ok
    assert result.reason == "missing_dev_verdict"


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


def test_late_older_verdict_cannot_retire_newer_overdue_builds():
    newest, overdue, old = "b" * 40, "c" * 40, "d" * 40
    runs = []
    for sha, age, run_id in ((newest, .5, 3), (overdue, 7, 2), (old, 8, 1)):
        stamp = (NOW - timedelta(hours=age)).isoformat()
        runs.append({"id": run_id, "status": "completed", "conclusion": "success", "event": "push",
                     "head_branch": "main", "head_sha": sha, "path": liveness.BUILD_WORKFLOW,
                     "created_at": stamp, "completed_at": stamp,
                     "repository": {"full_name": "o/r"}, "head_repository": {"full_name": "o/r"}})

    def api(path):
        if "actions/workflows" in path:
            return {"workflow_runs": runs}
        if f"commits/{old}/statuses" in path:
            return [_status(liveness.VERDICT_CONTEXT, .1)]
        if f"commits/{newest}/statuses" in path:
            return [_status(liveness.HEARTBEAT_CONTEXT, .1)]
        return []

    result = liveness.check("o/r", newest, api=api, now=NOW)
    assert not result.ok and result.reason == "missing_dev_verdict"


def test_pending_dev_restart_publishes_terminal_signal_without_new_operation(monkeypatch, tmp_path):
    transport = _GitHubTransport()
    monkeypatch.setattr(controller.subprocess, "run", transport)
    operations = []
    interrupted = True

    def native(channel, candidate):
        operations.append((channel, candidate.operation_id(channel)))
        if interrupted:
            raise controller.CandidateRefused("native_terminal_evidence_refused")
        return _native_receipt(channel, candidate)

    monkeypatch.setattr(controller, "native_deploy", native)
    tmp_path.chmod(0o700)
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 78
    checkpoint = json.loads((tmp_path / "postmerge-dev-test.json").read_text())
    assert (checkpoint["phase"], checkpoint["channel"]) == ("pending", "dev")
    interrupted = False
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 0
    assert operations[0] == operations[1]
    assert [next(arg for arg in command if arg.startswith("kind=")) for command in transport.liveness_dispatches] == [
        "kind=heartbeat", "kind=heartbeat", "kind=verdict"]
    signal = json.loads(next(arg.removeprefix("payload=") for arg in transport.liveness_dispatches[-1]
                             if arg.startswith("payload=")))
    assert signal["operation_id"] == operations[0][1]
    assert signal["result"] == "passed"


def test_failed_dev_verdict_is_recorded_as_activity_not_deployment_success(monkeypatch, tmp_path):
    transport = _GitHubTransport()
    monkeypatch.setattr(controller.subprocess, "run", transport)
    monkeypatch.setattr(controller, "native_deploy", lambda channel, candidate: {
        "channel": channel, "terminal_result": "failed", "operation_id": candidate.operation_id(channel)})
    tmp_path.chmod(0o700)
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 78
    signal = json.loads(next(arg.removeprefix("payload=") for arg in transport.liveness_dispatches[-1]
                             if arg.startswith("payload=")))
    assert signal["result"] == "failed"
    transport.actions = True
    _writer_env(monkeypatch)
    assert _writer_main("verdict", signal) == 0
    assert "state=failure" in transport.writes[-1]
    observed = liveness.evaluate(_build(1), heartbeat_statuses=[],
                                verdict_statuses=[_status(liveness.VERDICT_CONTEXT, .1, "failure")], now=NOW)
    assert observed.ok and observed.reason == "fresh_dev_verdict"
