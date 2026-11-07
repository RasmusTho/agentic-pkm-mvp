"""Contract probes for the dormant Claude Issue-delivery carrier."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root
from app.builderops.claude_issue_delivery import ClaudeStreamObservation
from app.builderops.epic_dispatch import IssueSessionLaunchError, build_dispatch_plan
from app.builderops import issue_delivery_effect_executor as executor
from tests.builderops.test_epic_dispatch import _candidate


SESSION = "e0ff1709-7c2a-47ef-b8aa-4b10c05c9b1b"
TARGET = {"capability": "sol", "model": "claude-test", "reasoning_effort": "high"}


def test_carrier_is_approval_bound_and_dormant_by_default(monkeypatch):
    binding = {"carrier": "claude", "model": TARGET["model"], "reasoning_effort": "high",
               "executable_sha256": "a" * 64, "isolation_profile_sha256": "b" * 64, "session_id": SESSION}
    approval = {"operation_key": "operation", "approval_id": "approval",
                "approval_manifest_hash": "c" * 64, "carrier_binding": binding}
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", None)
    with pytest.raises(ValueError, match="unavailable"):
        executor.verify_installed_carrier_qualification(approval, authority_epoch=1)

    def qualified(request):
        now = datetime.now(timezone.utc)
        return {"binding": deepcopy(request), "state": "qualified", "revocation": "current", "session_freshness": "verified-absent",
                "source": "fixture-host", "observed_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=1)).isoformat()}

    runtime = SimpleNamespace(isolation_profile_sha256="b" * 64, carrier_qualification_verifier=qualified)
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", runtime)
    executor.verify_installed_carrier_qualification(approval, authority_epoch=1)
    for field in binding:
        changed = deepcopy(approval)
        changed["carrier_binding"][field] = "changed"
        runtime.carrier_qualification_verifier = lambda request: qualified({**request, "carrier_binding": binding})
        with pytest.raises(ValueError):
            executor.verify_installed_carrier_qualification(changed, authority_epoch=1)
    runtime.carrier_qualification_verifier = lambda request: qualified({**request, "authority_epoch": 2})
    with pytest.raises(ValueError):
        executor.verify_installed_carrier_qualification(approval, authority_epoch=1)
    for changes in ({"session_freshness": None}, {"session_freshness": "unknown"}, {"revocation": "revoked"}, {"state": "unknown"}, {"expires_at": "2000-01-01T00:00:00+00:00"}, {"source": ""}):
        runtime.carrier_qualification_verifier = lambda request, changes=changes: {**qualified(request), **changes}
        with pytest.raises(ValueError):
            executor.verify_installed_carrier_qualification(approval, authority_epoch=1)


@pytest.mark.pg
def test_real_admission_and_plan_producers_preserve_versioned_binding(tmp_path, issue_delivery_production_harness):
    candidate = _candidate(5001, risk="high")
    plan = build_dispatch_plan(independent_issue_numbers=[5001], run_id="carrier-plan", candidates=[candidate],
                               runtime_targets=["claude"], carrier_target=TARGET)
    runtime = plan["context_packs"][0]["runtime"]
    assert runtime["runtime"] == "claude"
    assert all(runtime[key] == value for key, value in TARGET.items())
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps({"candidates": [candidate], "carrier_target": TARGET}))
    result = CliRunner().invoke(_root, ["builderops", "epic-run-state", "dispatch-plan", "--independent-issue", "5001",
                                      "--run-id", "carrier-plan", "--root", str(tmp_path),
                                      "--candidates-file", str(path), "--runtime", "claude", "--json"])
    assert result.exit_code == 0, (result.output, result.exception)
    assert json.loads(result.output) == plan
    harness = issue_delivery_production_harness(claude=True)
    approval = harness.approval
    assert approval["contract_version"] == "fca-issue-delivery.v4"
    assert approval["carrier_binding"]["carrier"] == "claude"
    assert approval["carrier_binding"]["isolation_profile_sha256"] == harness.prepared_worker.launcher.expected_profile_sha256
    assert approval["carrier_binding"]["session_id"] == harness.prepared_worker.launcher._session_id


def test_claude_transport_maps_entry_and_terminal_without_authority():
    entries = []
    observation = ClaudeStreamObservation(SESSION, entries.append)
    observation.observe(json.dumps({"type": "system", "subtype": "init", "session_id": SESSION}))
    observation.observe(json.dumps({"type": "result", "subtype": "success", "session_id": SESSION,
                                    "is_error": False, "result": json.dumps({"status": "completed"})}))
    assert entries == [SESSION]
    assert observation.terminal(0) == {"session_id": SESSION, "worker_receipt": {"status": "completed"}}
    for bad in (None, "", "other"):
        observation = ClaudeStreamObservation(SESSION)
        observation.observe(json.dumps({"type": "system", "subtype": "init", "session_id": bad}))
        with pytest.raises(IssueSessionLaunchError):
            observation.terminal(0)


def test_unsupported_controls_are_not_claimed():
    from app.builderops.issue_delivery_operation import IssueDeliveryOperationAdapter

    assert IssueDeliveryOperationAdapter.stop(None) == {
        "stop_support": "unsupported", "stop_status": "unsupported"
    }


@pytest.mark.pg
def test_protected_composition_for_both_carriers(issue_delivery_production_harness, monkeypatch):
    from app.builderops.epic_dispatch import dispatch_issue_sessions
    from tests.builderops.test_issue_delivery_operation import _production_adapter

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/untrusted/ambient")
    monkeypatch.setenv("GH_TOKEN", "ambient-marker")
    for claude in (False, True):
        harness = issue_delivery_production_harness(host_candidate=True, claude=claude)
        approval = harness.approval
        adapter = _production_adapter(harness)
        launch = adapter.launch
        failures = []
        def traced(*args, **kwargs):
            try:
                return launch(*args, **kwargs)
            except Exception as exc:
                import traceback
                failures.append("".join(traceback.format_exception(exc)))
                raise
        monkeypatch.setattr(adapter, "launch", traced)
        result = dispatch_issue_sessions(approval["context"]["dispatch_plan"], adapter,
                                         expected_plan_hash=approval["context"]["expected_plan_hash"])
        assert harness.worker_transport.calls == 1, (claude, result, failures)
        assert "candidate_ready" in json.dumps(result), (claude, failures, result)
        command = harness.worker_transport.commands[0]
        assert "ambient-marker" not in " ".join(command)
        assert "/untrusted/ambient" not in " ".join(command)
        if claude:
            assert approval["carrier_binding"]["session_id"] in command
            profile = json.loads(launcher._isolation_runner._profile_file.read_text()) if (launcher := harness.prepared_worker.launcher) else {}
            assert f"CLAUDE_CONFIG_DIR={profile['model_auth']['home']}" in command
            assert "--continue" not in command and "--resume" not in command
        replay = dispatch_issue_sessions(approval["context"]["dispatch_plan"], adapter,
                                         expected_plan_hash=approval["context"]["expected_plan_hash"])
        assert harness.worker_transport.calls == 1
        assert "delivered" not in json.dumps(replay)


@pytest.mark.pg
def test_claude_unknown_attempt_never_relaunches(issue_delivery_production_harness, monkeypatch):
    from app.builderops.epic_dispatch import dispatch_issue_sessions
    from tests.builderops.test_issue_delivery_operation import _production_adapter

    from app.builderops.control_plane.client import ControlPlaneNotFoundError
    import httpx

    before = issue_delivery_production_harness(claude=True)
    before.worker_transport.lose_response_before_entry = True
    before_adapter = _production_adapter(before)
    before_plan = before.approval["context"]["dispatch_plan"]
    invoke_before = lambda: dispatch_issue_sessions(before_plan, before_adapter, expected_plan_hash=before.approval["context"]["expected_plan_hash"])
    assert invoke_before()["stopped_reason"] == "session-launch-failed"
    assert before.worker_transport.calls == 1
    with pytest.raises(ControlPlaneNotFoundError):
        before.owner.issue_delivery_operation_record_read(repository=before.approval["repository"], record_id=f"issue-delivery-entry:{before.approval['operation_key']}")
    assert before.owner.issue_delivery_operation_record_read(repository=before.approval["repository"], record_id=f"issue-delivery-terminal:{before.approval['operation_key']}")["state"] == "launch_unknown"
    invoke_before()
    assert before.worker_transport.calls == 1

    harness = issue_delivery_production_harness(claude=True, lose_response_after_entry=True)
    approval = harness.approval
    adapter = _production_adapter(harness)
    plan = approval["context"]["dispatch_plan"]
    first = dispatch_issue_sessions(plan, adapter, expected_plan_hash=approval["context"]["expected_plan_hash"])
    assert first["stopped_reason"] == "session-launch-failed"
    assert harness.worker_transport.calls == 1
    for kind, state in (("entry", "active"), ("terminal", "launch_unknown")):
        record = harness.owner.issue_delivery_operation_record_read(repository=approval["repository"], record_id=f"issue-delivery-{kind}:{approval['operation_key']}")
        assert record["state"] == state
    dispatch_issue_sessions(plan, adapter, expected_plan_hash=approval["context"]["expected_plan_hash"])
    assert harness.worker_transport.calls == 1

    # The service commits the terminal record, then its readback transport is
    # unavailable. Restore the transport and replay through the real adapter.
    terminal = issue_delivery_production_harness(claude=True)
    terminal_adapter = _production_adapter(terminal)
    terminal_plan = terminal.approval["context"]["dispatch_plan"]
    request = terminal.client._http.request
    lost = {"committed": False, "reads": 0}
    def unavailable_terminal_read(method, path, **kwargs):
        if method == "GET" and "issue-delivery-terminal:" in str(path) and lost["committed"]:
            lost["reads"] += 1
            raise httpx.ConnectError("simulated lost terminal readback")
        response = request(method, path, **kwargs)
        body = kwargs.get("json") or {}
        if method == "POST" and str(body.get("record_id", "")).startswith("issue-delivery-terminal:") and body.get("state") == "terminal":
            lost["committed"] = True
        return response
    monkeypatch.setattr(terminal.client._http, "request", unavailable_terminal_read)
    invoke_terminal = lambda: dispatch_issue_sessions(terminal_plan, terminal_adapter, expected_plan_hash=terminal.approval["context"]["expected_plan_hash"])
    assert invoke_terminal()["stopped_reason"] == "session-launch-failed"
    assert lost["committed"] and lost["reads"] > 0
    assert terminal.worker_transport.calls == 1
    persisted = terminal.owner.issue_delivery_operation_record_read(repository=terminal.approval["repository"], record_id=f"issue-delivery-terminal:{terminal.approval['operation_key']}")
    assert persisted["state"] == "terminal"
    monkeypatch.setattr(terminal.client._http, "request", request)
    recovered = invoke_terminal()
    assert terminal.worker_transport.calls == 1
    assert recovered["sessions"][0]["fresh_session"] is False
    assert recovered["sessions"][0]["session_id"] == terminal.approval["carrier_binding"]["session_id"]


@pytest.mark.pg
def test_claude_qualification_refuses_before_preparation_and_spawn(issue_delivery_production_harness, monkeypatch):
    from dataclasses import replace
    from app.builderops.epic_dispatch import dispatch_issue_sessions
    from tests.builderops.test_issue_delivery_operation import _production_adapter

    harness = issue_delivery_production_harness(claude=True)
    runtime = executor._HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME
    observed = runtime.carrier_qualification_verifier
    calls = []
    def mismatched(request):
        result = observed(request)
        result["binding"]["authority_epoch"] += 1
        return result
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", replace(runtime, carrier_qualification_verifier=mismatched))
    original_prepare = harness.destination.prepare
    monkeypatch.setattr(harness.destination, "prepare", lambda *_: calls.append("prepared"))
    launcher = harness.prepared_worker.launcher
    with pytest.raises(ValueError):
        executor.PreparedIssueDeliveryWorker.create(approval=harness.approval, destination=harness.destination,
            launcher_factory=lambda _: launcher, carrier_profile_file=launcher._isolation_runner._profile_file,
            authority_client=harness.host, carrier_launcher=launcher)
    assert calls == []
    assert harness.worker_transport.calls == 0

    # Fresh pre-entry observation refuses revoked qualification after admission.
    monkeypatch.setattr(harness.destination, "prepare", original_prepare)
    original = runtime.carrier_qualification_verifier
    def revoked(request):
        return {**original(request), "revocation": "revoked"}
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", replace(runtime, carrier_qualification_verifier=revoked))
    approval = harness.approval
    dispatch_issue_sessions(approval["context"]["dispatch_plan"], _production_adapter(harness),
                            expected_plan_hash=approval["context"]["expected_plan_hash"])
    assert harness.worker_transport.calls == 0
    assert harness.transport.apply_calls == 0


@pytest.mark.pg
def test_claude_cli_dispatch_reaches_protected_candidate(issue_delivery_production_harness, monkeypatch, tmp_path):
    from tests.builderops.issue_delivery_production_harness import _production_client
    from app.builderops import cli

    harness = issue_delivery_production_harness(claude=True)
    approval = harness.approval
    launcher = harness.prepared_worker.launcher
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(approval["context"]["dispatch_plan"]))
    monkeypatch.setattr(cli.ClientConfig, "from_env", lambda: object())
    monkeypatch.setattr(cli, "BuilderOpsControlPlaneClient", lambda *args, **kwargs: _production_client(harness.store, harness.registry, "executor-pg-token"))
    # Keep the actual CLI class, launcher constructor and runner. Inject only
    # host/OS observations and the outer process transport at the base init.
    from app.builderops import issue_delivery_worker_isolation as isolation
    actual_init = isolation.LinuxSystemdCodexIssueSessionLauncher.__init__
    template = launcher._isolation_runner
    created = []
    def init_with_external_ports(self, **kwargs):
        kwargs.update(principal_resolver=template._principal_resolver, current_identity=template._current_identity,
            credential_probe=template._credential_probe, worker_access_probe=template._worker_access_probe,
            worktree_head_resolver=template._worktree_head_resolver, worktree_git_topology_resolver=template._worktree_git_topology_resolver,
            systemd_preflight=template._systemd_preflight, executable_resolver=template._executable_resolver,
            path_lstat_resolver=template._path_lstat_resolver, runner=template._runner, unit_token=template._unit_token,
            clock=template._clock, platform_name="linux", completion_reader=launcher._completion_reader)
        actual_init(self, **kwargs)
        created.append(self)
    monkeypatch.setattr(isolation.LinuxSystemdCodexIssueSessionLauncher, "__init__", init_with_external_ports)
    result = CliRunner().invoke(_root, ["builderops", "epic-run-state", "dispatch-sessions", "--plan-file", str(plan_file),
        "--repo-root", str(harness.worktree), "--approval-file", str(launcher.effect_gate_approval_file),
        "--expected-plan-hash", approval["context"]["expected_plan_hash"], "--worker-isolation-profile-file",
        str(launcher._isolation_runner._profile_file), "--worker-isolation-profile-sha256", launcher.expected_profile_sha256, "--json"])
    assert result.exit_code == 0, (result.output, result.exception)
    assert "candidate_ready" in result.output
    assert len(created) == 1 and created[0] is not launcher
    assert type(created[0]) is executor.ClaudeContentOnlyIssueDeliverySessionLauncher
    assert harness.worker_transport.calls == 1
