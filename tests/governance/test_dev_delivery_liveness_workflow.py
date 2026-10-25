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
        self.heavy_calls = []
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
        if argv[0] == "/usr/bin/ssh":
            assert "ygg-dev" in argv
            assert argv[-3:] == ["qualify-heavy", "dev", self.candidate.operation_id("dev")]
            self.heavy_calls.append(argv)
            from app.ops.heavy_acceptance import identity
            receipt = {**identity(self.candidate.sha, self.candidate.digest, "dev", self.candidate.operation_id("dev")),
                       "result": "passed", "targets": ["tests/deploy"], "report_hash": "0" * 64,
                       "selected": 1, "passed": 1, "failed": 0, "skipped": 0, "docker_skipped": 0, "failures": []}
            return SimpleNamespace(returncode=0, stdout=json.dumps(receipt), stderr="")
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
    assert channels == ["dev"] and not transport.heavy_calls
    assert len(transport.liveness_dispatches) == 1 and not transport.channel_dispatches
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 0
    assert channels == ["dev", "test"] and len(transport.heavy_calls) == 1
    assert not transport.denied_writes and not transport.writes
    checkpoint = json.loads((tmp_path / "postmerge-dev-test.json").read_text())
    assert (checkpoint["phase"], checkpoint["channel"]) == ("passed", "test")
    assert len(transport.liveness_dispatches) == 3
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
    assert all(value.startswith("context=" + liveness.HEARTBEAT_CONTEXT + "/") for value in contexts[:-1])
    assert contexts[-1] == "context=" + liveness.VERDICT_CONTEXT
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
    assert controller.main(["--latest", "--state-directory", str(tmp_path)]) == 0
    expected_signals = 9 if "dev-delivery-liveness.yml" in failed_workflows else 3
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
        parents = {newest: preceding, preceding: skipped, skipped: None}
        for sha, parent in parents.items():
            if path == f"repos/o/r/git/commits/{sha}":
                return {"sha": sha, "parents": [{"sha": parent}] if parent else []}
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


@pytest.mark.parametrize('fault', ['missing_issue', 'missing_expiry', 'naive_expiry', 'backward_expiry',
                                   'future_engagement', 'expired_observation', 'extra_field'])
def test_pause_signal_refuses_malformed_authority_before_status_write(monkeypatch, fault):
    transport = _GitHubTransport()
    transport.actions = True
    monkeypatch.setattr(liveness.subprocess, 'run', transport)
    _writer_env(monkeypatch)
    now = datetime.now(timezone.utc)
    pause = {'issue': 6224, 'engaged_at': (now - timedelta(minutes=1)).isoformat(),
             'expires_at': (now + timedelta(minutes=5)).isoformat()}
    if fault == 'missing_issue':
        pause.pop('issue')
    elif fault == 'missing_expiry':
        pause.pop('expires_at')
    elif fault == 'naive_expiry':
        pause['expires_at'] = (now + timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    elif fault == 'backward_expiry':
        pause['expires_at'] = (now - timedelta(minutes=2)).isoformat()
    elif fault == 'future_engagement':
        pause['engaged_at'] = (now + timedelta(minutes=1)).isoformat()
    elif fault == 'expired_observation':
        pause['expires_at'] = now.isoformat()
    else:
        pause['authority'] = 'unapproved'
    signal = {'protocol': controller.LIVENESS_PROTOCOL, 'sha': SHA,
              'observed_at': now.isoformat(), 'sequence': 1, 'pause': pause}
    assert _writer_main('heartbeat', signal) == 1
    assert not transport.writes


def test_pause_controller_entrypoint_has_no_extra_host_permissions(monkeypatch, tmp_path):
    transport = _GitHubTransport()
    monkeypatch.setattr(controller.subprocess, 'run', transport)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(controller, '_utc_now', lambda: now)
    tmp_path.chmod(0o700)
    assert controller.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                            '--until', (now + timedelta(minutes=5)).isoformat()]) == 0
    assert not transport.reads and not transport.dispatches
    monkeypatch.setattr(controller, 'native_deploy', lambda *_: pytest.fail('paused native deployment'))
    assert controller.main(['--latest', '--state-directory', str(tmp_path)]) == 0
    assert transport.reads == [f'repos/{controller.REPOSITORY}/commits/main']
    assert len(transport.liveness_dispatches) == 1
    assert not transport.channel_dispatches and not transport.denied_writes and not transport.writes
    fields = dict(arg.split('=', 1) for arg in transport.liveness_dispatches[0] if '=' in arg)
    assert fields['kind'] == 'heartbeat'
    assert json.loads(fields['payload'])['pause']['issue'] == 6224
    transport.actions = True
    _writer_env(monkeypatch)
    assert _writer_main(fields['kind'], json.loads(fields['payload'])) == 0
    assert len(transport.writes) == 1
    assert 'state=failure' in transport.writes[0]



def test_pause_remains_red_without_heartbeat_and_expiry_restores_stale_alert():
    observed = NOW - timedelta(hours=3)
    until = NOW + timedelta(minutes=5)
    status = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'failure',
              'description': f'observed_at={observed.isoformat()};seq=2;paused_issue=6224;until={until.isoformat()}'}
    fresh_verdict = _status(liveness.VERDICT_CONTEXT, 0.1)
    result = liveness.evaluate(_build(1), heartbeat_statuses=[status],
                               verdict_statuses=[fresh_verdict], now=NOW)
    assert not result.ok and result.reason == 'paused'
    result = liveness.evaluate(_build(1), heartbeat_statuses=[status], verdict_statuses=[], now=until)
    assert not result.ok and result.reason == 'heartbeat_stale'


@pytest.mark.parametrize('pause_built', [True, False])
@pytest.mark.parametrize('heartbeat_age', [0.2, 3])
def test_pause_survives_main_advancement_without_another_heartbeat(pause_built, heartbeat_age):
    newer, paused, preceding = "b" * 40, "c" * 40, "d" * 40
    build_sha = paused if pause_built else preceding
    stamp = (NOW - timedelta(hours=1)).isoformat()
    run = {"id": 1, "status": "completed", "conclusion": "success", "event": "push",
           "head_branch": "main", "head_sha": build_sha, "path": liveness.BUILD_WORKFLOW,
           "created_at": stamp, "completed_at": stamp,
           "repository": {"full_name": "o/r"}, "head_repository": {"full_name": "o/r"}}
    expiry = NOW + timedelta(hours=1)
    pause = {"context": liveness.HEARTBEAT_CONTEXT, "state": "failure",
             "description": (f"observed_at={(NOW - timedelta(hours=heartbeat_age)).isoformat()};"
                             f"seq=2;paused_issue=6224;until={expiry.isoformat()}"),
             "updated_at": (expiry + timedelta(hours=4)).isoformat()}
    statuses = {newer: [], paused: [pause], preceding: []}
    statuses[build_sha].append(_status(liveness.VERDICT_CONTEXT, 0.5))
    parents = {newer: paused, paused: preceding, preceding: None}
    seen = []
    def api(path):
        seen.append(path)
        if "actions/workflows" in path:
            return {"workflow_runs": [run]}
        for sha in parents:
            if path == f"repos/o/r/git/commits/{sha}":
                return {"sha": sha, "parents": [{"sha": parents[sha]}] if parents[sha] else []}
            if path.startswith(f"repos/o/r/commits/{sha}/statuses?"):
                return statuses[sha]
        raise AssertionError(path)
    result = liveness.check("o/r", newer, api=api, now=NOW)
    assert not result.ok and result.reason == "paused"
    assert result.description == f"paused (#6224, until {expiry.isoformat()})"
    assert f"repos/o/r/git/commits/{newer}" in seen
    # Public update time cannot extend expiry; normal fresh-verdict recovery resumes.
    result = liveness.check("o/r", newer, api=api, now=expiry)
    assert result.ok and result.reason == "fresh_dev_verdict"
    # Without any further producer, the same history becomes stale after grace.
    result = liveness.check("o/r", newer, api=api, now=expiry + timedelta(hours=2))
    assert not result.ok and result.reason == "heartbeat_stale"
    # A later legitimate resumed tick on new main supersedes the expired old pause.
    resumed_at = expiry + timedelta(hours=2)
    statuses[newer] = [{"context": liveness.HEARTBEAT_CONTEXT, "state": "success",
                       "description": "observed_at=" + resumed_at.isoformat()}]
    result = liveness.check("o/r", newer, api=api, now=resumed_at)
    assert result.ok and result.reason == "dev_verdict_recorded"


@pytest.mark.parametrize('position', [99, 100])
def test_pause_history_has_an_exact_fail_closed_commit_bound(position):
    commits = [f"{i + 1:040x}" for i in range(102)]
    seen_statuses = []
    pause = {"context": liveness.HEARTBEAT_CONTEXT, "state": "failure",
             "description": f"observed_at={NOW.isoformat()};seq=2;paused_issue=6224;until={(NOW + timedelta(hours=1)).isoformat()}"}
    def api(path):
        if "actions/workflows" in path:
            return {"workflow_runs": []}
        if "/statuses?" in path:
            sha = path.split("/commits/")[1].split("/")[0]
            seen_statuses.append(sha)
            return [pause] if sha == commits[position] else []
        sha = path.rsplit("/", 1)[1]
        return {"sha": sha, "parents": [{"sha": commits[commits.index(sha) + 1]}]}
    assert liveness.MAX_HEARTBEAT_COMMITS == 100
    if position == 99:
        result = liveness.check("o/r", commits[0], api=api, now=NOW)
        assert not result.ok and result.reason == "paused"
    else:
        with pytest.raises(liveness.LivenessRefused, match="heartbeat_ancestry_incomplete"):
            liveness.check("o/r", commits[0], api=api, now=NOW)
    assert len(seen_statuses) == 100


@pytest.mark.parametrize('fault', ['wrong_sha', 'missing_parents', 'parent_shape', 'parent_sha',
                                  'cycle', 'auth', 'statuses_shape'])
def test_pause_history_refuses_ambiguous_ancestry(fault):
    def api(path):
        if "actions/workflows" in path:
            return {"workflow_runs": []}
        if "/statuses?" in path:
            return {} if fault == 'statuses_shape' else []
        commit = {"sha": SHA, "parents": []}
        if fault == 'wrong_sha':
            commit['sha'] = 'b' * 40
        elif fault == 'missing_parents':
            commit.pop('parents')
        elif fault == 'parent_shape':
            commit['parents'] = [False]
        elif fault == 'parent_sha':
            commit['parents'] = [{'sha': '../main'}]
        elif fault == 'cycle':
            commit['parents'] = [{'sha': SHA}]
        elif fault == 'auth':
            raise subprocess.CalledProcessError(403, ['gh', 'api', path])
        return commit
    with pytest.raises((liveness.LivenessRefused, subprocess.CalledProcessError)):
        liveness.check("o/r", SHA, api=api, now=NOW)


def test_pause_history_auth_failure_is_red_through_production_cli(monkeypatch, capsys):
    def transport(command, **kwargs):
        path = command[2]
        if "actions/workflows" in path:
            payload = {"workflow_runs": []}
        elif "/statuses?" in path:
            payload = []
        else:
            raise subprocess.CalledProcessError(403, command)
        return SimpleNamespace(stdout=json.dumps(payload))
    monkeypatch.setattr(liveness.subprocess, 'run', transport)
    assert liveness.main(['--repo', 'o/r', '--github-sha', SHA]) == 1
    result = json.loads(capsys.readouterr().out)
    assert not result['ok'] and result['reason'] == 'evidence_refused'


def test_pause_history_follows_first_parent_and_stops_at_later_resume():
    resumed, other = 'b' * 40, 'c' * 40
    seen = []
    def api(path):
        seen.append(path)
        if 'actions/workflows' in path:
            return {'workflow_runs': []}
        if path == f'repos/o/r/git/commits/{SHA}':
            return {'sha': SHA, 'parents': [{'sha': resumed}, {'sha': other}]}
        if f'/commits/{resumed}/statuses?' in path:
            return [_status(liveness.HEARTBEAT_CONTEXT, 0.1)]
        if f'/commits/{SHA}/statuses?' in path:
            return []
        raise AssertionError(path)
    result = liveness.check('o/r', SHA, api=api, now=NOW)
    assert result.ok and result.reason == 'no_admitted_build'
    assert all(other not in path for path in seen)
    assert len(seen) == 4


def test_pause_history_paginates_past_replayed_normal_heartbeat():
    expiry = NOW + timedelta(hours=1)
    replayed = _status(liveness.HEARTBEAT_CONTEXT, 1)
    recent_writes = [{**replayed, 'created_at': (NOW - timedelta(seconds=i)).isoformat()} for i in range(100)]
    pause = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'failure',
             'description': f'observed_at={(NOW - timedelta(minutes=6)).isoformat()};seq=2;paused_issue=6224;until={expiry.isoformat()}',
             'created_at': (NOW - timedelta(minutes=5)).isoformat()}
    pages = {1: recent_writes, 2: [pause]}
    seen = []
    def api(path):
        seen.append(path)
        if 'actions/workflows' in path:
            return {'workflow_runs': []}
        return pages[int(path.rsplit('page=', 1)[1])]
    result = liveness.check('o/r', SHA, api=api, now=NOW)
    assert not result.ok and result.reason == 'paused'
    assert any(path.endswith('page=2') for path in seen)
    # Later genuine resume remains authoritative even with the older pause retained.
    resumed_at = expiry + timedelta(seconds=1)
    pages[1][0] = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'success',
                   'description': 'observed_at=' + resumed_at.isoformat() + ';seq=3', 'created_at': resumed_at.isoformat()}
    seen.clear()
    result = liveness.check('o/r', SHA, api=api, now=resumed_at)
    assert result.ok and result.reason == 'no_admitted_build'
    assert not any(path.endswith('page=2') for path in seen)


@pytest.mark.parametrize('replayed_match', [True, False])
def test_pause_history_refuses_incomplete_status_pagination(replayed_match):
    pages = []
    def api(path):
        if 'actions/workflows' in path:
            return {'workflow_runs': []}
        page = int(path.rsplit('page=', 1)[1]); pages.append(page)
        context = liveness.HEARTBEAT_CONTEXT if replayed_match else 'unrelated'
        return [{**_status(context, 3), 'created_at': (NOW - timedelta(seconds=page * 100 + i)).isoformat()}
                for i in range(100)]
    with pytest.raises(liveness.LivenessRefused, match='statuses_incomplete'):
        liveness.check('o/r', SHA, api=api, now=NOW)
    assert pages == list(range(1, liveness.MAX_HISTORY_PAGES + 1))


@pytest.mark.parametrize('fault', ['missing_created', 'reordered', 'wrong_shape'])
def test_pause_history_refuses_malformed_status_page(fault):
    rows = [{**_status(liveness.HEARTBEAT_CONTEXT, 3),
             'created_at': (NOW - timedelta(seconds=i)).isoformat()} for i in range(100)]
    if fault == 'missing_created':
        rows[0].pop('created_at')
    elif fault == 'reordered':
        rows.reverse()
    else:
        rows[0] = False
    def api(path):
        return {'workflow_runs': []} if 'actions/workflows' in path else rows
    with pytest.raises(liveness.LivenessRefused):
        liveness.check('o/r', SHA, api=api, now=NOW)


def _pause_transport(monkeypatch, tmp_path):
    transport = _GitHubTransport()
    monkeypatch.setattr(controller.subprocess, 'run', transport)
    monkeypatch.setattr(controller, 'native_deploy', _native_receipt)
    monkeypatch.setattr(controller, 'native_heavy', lambda _: {
        'result': 'passed', 'selected': 1, 'passed': 1, 'failed': 0, 'skipped': 0,
        'docker_skipped': 0, 'failures': []})
    monkeypatch.setattr(controller, 'dispatch_verdict', lambda *_: None)
    tmp_path.chmod(0o700)
    return transport


def _record_heartbeat(transport, command, now):
    fields = dict(arg.split('=', 1) for arg in command if '=' in arg)
    assert fields['kind'] == 'heartbeat'
    transport.actions = True
    try:
        liveness.record_signal('heartbeat', fields['payload'], repo=controller.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho',
                               run_url=f'https://github.com/{controller.REPOSITORY}/actions/runs/999',
                               api=lambda _: {'status': 'identical'}, now=now)
    finally:
        transport.actions = False
    return {**dict(arg.split('=', 1) for arg in transport.writes[-1] if '=' in arg),
            'created_at': now.replace(microsecond=0).isoformat()}


def _check_pause_history(statuses, now):
    def api(path):
        return {'workflow_runs': []} if 'actions/workflows' in path else statuses
    return liveness.check(controller.REPOSITORY, SHA, api=api, now=now)


def test_pause_clock_rewind_after_normal_tick_refuses_at_producer(monkeypatch, tmp_path):
    # 6224-pause-clock-rewind-silent-green: actual normal producer -> rewind -> pause.
    transport = _pause_transport(monkeypatch, tmp_path)
    normal_at = NOW - timedelta(seconds=30)
    monkeypatch.setattr(controller, '_utc_now', lambda: normal_at)
    assert controller.main(['--latest', '--state-directory', str(tmp_path)]) == 0
    path = tmp_path / 'postmerge-dev-test.json'
    before = path.read_bytes()
    dispatches = len(transport.dispatches)
    monkeypatch.setattr(controller, '_utc_now', lambda: NOW - timedelta(seconds=90))
    assert controller.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                            '--until', (NOW + timedelta(minutes=10)).isoformat()]) == 78
    assert controller.main(['--latest', '--state-directory', str(tmp_path)]) == 78
    assert path.read_bytes() == before
    assert len(transport.dispatches) == dispatches
    assert 'pause' not in json.loads(before)


def test_pause_equal_time_replay_replacement_expiry_and_restart_order(monkeypatch, tmp_path):
    transport = _pause_transport(monkeypatch, tmp_path)
    monkeypatch.setattr(controller, '_utc_now', lambda: NOW)
    options = ['--latest', '--state-directory', str(tmp_path)]
    assert controller.main(options) == 0
    normal = _record_heartbeat(transport, transport.liveness_dispatches[0], NOW)
    pause_options = ['--pause', '--state-directory', str(tmp_path), '--issue', '6224', '--until']
    assert controller.main([*pause_options, (NOW + timedelta(minutes=10)).isoformat()]) == 0
    assert controller.main(options) == 0
    paused = _record_heartbeat(transport, transport.liveness_dispatches[-1], NOW)
    assert _check_pause_history([normal, paused, normal], NOW).reason == 'paused'
    # The operator may shorten a pause; the later durable sequence owns expiry.
    expiry = NOW + timedelta(minutes=5)
    assert controller.main([*pause_options, expiry.isoformat()]) == 0
    assert controller.main(options) == 0
    replacement = _record_heartbeat(transport, transport.liveness_dispatches[-1], NOW)
    result = _check_pause_history([paused, replacement, normal], NOW)
    assert result.reason == 'paused' and expiry.isoformat() in result.description
    monkeypatch.setattr(controller, '_utc_now', lambda: expiry)
    assert controller.main(options) == 0
    resumed_command = next(command for command in reversed(transport.liveness_dispatches) if 'kind=heartbeat' in command)
    resumed = _record_heartbeat(transport, resumed_command, expiry)
    assert _check_pause_history([paused, normal, replacement, resumed], expiry).ok
    path = tmp_path / 'postmerge-dev-test.json'
    before = path.read_bytes()
    monkeypatch.setattr(controller, '_utc_now', lambda: expiry - timedelta(microseconds=1))
    dispatches = len(transport.dispatches)
    assert controller.main(options) == 78
    assert path.read_bytes() == before and len(transport.dispatches) == dispatches
    assert _check_pause_history([paused, resumed], expiry).ok


def test_pause_fractional_pagination_uses_real_producer_and_writer(monkeypatch, tmp_path):
    # 6224-pause-fractional-pagination-cutoff: same server second, distinct source fractions.
    transport = _pause_transport(monkeypatch, tmp_path)
    normal_at = NOW.replace(microsecond=100000)
    pause_at = NOW.replace(microsecond=800000)
    monkeypatch.setattr(controller, '_utc_now', lambda: normal_at)
    options = ['--latest', '--state-directory', str(tmp_path)]
    assert controller.main(options) == 0
    normal = _record_heartbeat(transport, transport.liveness_dispatches[0], normal_at)
    monkeypatch.setattr(controller, '_utc_now', lambda: pause_at)
    assert controller.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                            '--until', (NOW + timedelta(hours=1)).isoformat()]) == 0
    assert controller.main(options) == 0
    paused = _record_heartbeat(transport, transport.liveness_dispatches[-1], pause_at)
    assert normal['created_at'] == paused['created_at']
    pages = {1: [{'context': 'unrelated', 'created_at': (NOW + timedelta(seconds=100-i)).isoformat()}
                 for i in range(99)] + [normal], 2: [paused]}
    reads = []
    def api(path):
        if 'actions/workflows' in path:
            return {'workflow_runs': []}
        page = int(path.rsplit('page=', 1)[1]); reads.append(page)
        return pages[page]
    result = liveness.check(controller.REPOSITORY, SHA, api=api, now=NOW + timedelta(minutes=5))
    assert not result.ok and result.reason == 'paused'
    assert reads == [1, 2]


def test_pause_adopts_legacy_pending_identity_despite_earlier_host_clock(monkeypatch, tmp_path):
    transport = _pause_transport(monkeypatch, tmp_path)
    candidate = transport.candidate
    # The shipped legacy checkpoint producer has no observation metadata.
    outcome = {'source_sha': SHA, 'image_digest': candidate.digest, 'source_run_id': candidate.run_id,
               'source_run_attempt': candidate.run_attempt, 'artifact_id': candidate.artifact_id,
               'result': 'pending', 'channel': 'dev', 'operation_id': candidate.operation_id('dev')}
    path = tmp_path / 'postmerge-dev-test.json'
    legacy = controller._save_outcome(path, candidate, outcome, last_green={'dev': 'b' * 40})
    host_now = NOW - timedelta(seconds=90)
    monkeypatch.setattr(controller, '_utc_now', lambda: host_now)
    assert controller.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                            '--until', (NOW + timedelta(minutes=10)).isoformat()]) == 0
    assert controller.main(['--latest', '--state-directory', str(tmp_path)]) == 0
    retained = json.loads(path.read_text())
    assert {k: v for k, v in retained.items() if k not in {'pause', 'observation'}} == legacy
    paused = _record_heartbeat(transport, transport.liveness_dispatches[-1], NOW)
    legacy_normal = _status(liveness.HEARTBEAT_CONTEXT, 30/3600)
    assert _check_pause_history([legacy_normal, paused], NOW).reason == 'paused'


@pytest.mark.parametrize('failure', ['before_replace', 'missing_after_bootstrap'])
def test_pause_state_loss_and_atomic_failure_refuse_before_external_effect(monkeypatch, tmp_path, failure):
    transport = _pause_transport(monkeypatch, tmp_path)
    monkeypatch.setattr(controller, '_utc_now', lambda: NOW)
    options = ['--latest', '--state-directory', str(tmp_path)]
    path = tmp_path / 'postmerge-dev-test.json'
    if failure == 'before_replace':
        monkeypatch.setattr(controller.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('crash')))
    else:
        assert controller.main(options) == 0
        path.unlink()
        transport.reads.clear(); transport.dispatches.clear()
    assert controller.main(options) == 78
    assert not transport.reads and not transport.dispatches and not path.exists()
    # The surviving existing lock is not authority to silently reset the counter.
    assert controller.main(options) == 78
    assert not transport.reads and not transport.dispatches


def test_pause_dispatch_failure_keeps_durable_observation_for_retry_and_restart(monkeypatch, tmp_path):
    transport = _pause_transport(monkeypatch, tmp_path)
    monkeypatch.setattr(controller, '_utc_now', lambda: NOW)
    monkeypatch.setattr(controller.time, 'sleep', lambda _: None)
    options = ['--latest', '--state-directory', str(tmp_path)]
    assert controller.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                            '--until', (NOW + timedelta(minutes=10)).isoformat()]) == 0
    transport.fail_dispatch = True
    assert controller.main(options) == 0
    failed = [next(arg for arg in command if arg.startswith('payload='))
              for command in transport.liveness_dispatches]
    assert len(failed) == 3 and len(set(failed)) == 1
    path = tmp_path / 'postmerge-dev-test.json'
    persisted = json.loads(path.read_text())['observation']
    assert json.loads(failed[0].removeprefix('payload='))['sequence'] == persisted['sequence']
    transport.fail_dispatch = False
    assert controller.main(options) == 0
    restarted = json.loads(path.read_text())['observation']
    assert restarted['sequence'] == persisted['sequence'] + 1
    assert restarted['observed_at'] == persisted['observed_at']
    assert _record_heartbeat(transport, transport.liveness_dispatches[-1], NOW)['state'] == 'failure'


@pytest.mark.parametrize('observation', [
    {'sequence': True, 'observed_at': NOW.isoformat()},
    {'sequence': 0, 'observed_at': NOW.isoformat()},
    {'sequence': 10**18, 'observed_at': NOW.isoformat()},
    {'sequence': 1, 'observed_at': 'invalid'},
    {'sequence': 1, 'observed_at': NOW.replace(tzinfo=None).isoformat()},
    {'sequence': 1, 'observed_at': NOW.isoformat(), 'extra': 'unknown'},
])
def test_pause_malformed_observation_refuses_producer_and_trusted_writer(monkeypatch, tmp_path, observation):
    # Reach metadata validation independently of the machine's calendar date.
    class WriterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(liveness, 'datetime', WriterClock)
    transport = _pause_transport(monkeypatch, tmp_path)
    controller._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {'observation': observation})
    assert controller.main(['--latest', '--state-directory', str(tmp_path)]) == 78
    assert not transport.reads and not transport.dispatches
    transport.actions = True
    _writer_env(monkeypatch)
    signal = {'protocol': controller.LIVENESS_PROTOCOL, 'sha': SHA, **observation}
    assert _writer_main('heartbeat', signal) == 1
    assert not transport.writes


@pytest.mark.parametrize('fault', ['same_sequence_conflict', 'clock_regressed', 'unsequenced_pause'])
def test_pause_ambiguous_public_order_cannot_recover_to_green(fault):
    first = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'success',
             'description': f'observed_at={NOW.isoformat()};seq=1'}
    second = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'failure',
              'description': f'observed_at={NOW.isoformat()};seq=2;paused_issue=6224;until={(NOW + timedelta(hours=1)).isoformat()}'}
    if fault == 'same_sequence_conflict':
        second['description'] = second['description'].replace('seq=2', 'seq=1')
    elif fault == 'clock_regressed':
        second['description'] = second['description'].replace(NOW.isoformat(), (NOW - timedelta(seconds=1)).isoformat(), 1)
    else:
        second['description'] = second['description'].replace(';seq=2', '')
    with pytest.raises(liveness.LivenessRefused):
        _check_pause_history([first, second, _status(liveness.VERDICT_CONTEXT, 0)], NOW)
