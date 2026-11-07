import json

import pytest

from app.builderops.claude_issue_delivery import ClaudeStreamObservation
from app.builderops.epic_dispatch import IssueSessionLaunchError


SESSION = "e0ff1709-7c2a-47ef-b8aa-4b10c05c9b1b"


def event(**kwargs):
    return json.dumps(kwargs)


def test_entry_and_terminal_require_matching_identity():
    entries = []
    observed = ClaudeStreamObservation(SESSION, entries.append)
    observed.observe(event(type="system", subtype="init", session_id=SESSION))
    observed.observe(event(type="result", subtype="success", session_id=SESSION, is_error=False, result='{"status":"completed"}'))
    assert entries == [SESSION]
    assert observed.terminal(0) == {"session_id": SESSION, "worker_receipt": {"status": "completed"}}


@pytest.mark.parametrize("terminal", [
    {"type": "result", "subtype": "success", "session_id": "other", "is_error": False, "result": "{}"},
    {"type": "result", "subtype": "success", "session_id": None, "is_error": False, "result": "{}"},
    {"type": "result", "subtype": "success", "session_id": SESSION, "is_error": True, "result": "{}"},
    {"type": "result", "subtype": "success", "session_id": SESSION, "is_error": False, "result": "bad"},
])
def test_bad_terminal_cannot_report_success(terminal):
    observed = ClaudeStreamObservation(SESSION)
    observed.observe(event(type="system", subtype="init", session_id=SESSION))
    observed.observe(json.dumps(terminal))
    with pytest.raises(IssueSessionLaunchError):
        observed.terminal(0)


def test_init_must_match_preallocated_session_identity():
    entries = []
    observed = ClaudeStreamObservation(SESSION, entries.append)
    observed.observe(event(type="system", subtype="init", session_id="a689fc1f-d5d8-49ed-a86f-034d31984acd"))
    assert entries == []
    with pytest.raises(IssueSessionLaunchError):
        observed.terminal(0)
    with pytest.raises(ValueError):
        ClaudeStreamObservation("session-1")


def test_host_qualification_refuses_absent_and_mismatched_evidence(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from app.builderops import issue_delivery_effect_executor as executor

    binding = {"carrier": "claude", "model": "model", "reasoning_effort": "high", "executable_sha256": "a" * 64, "isolation_profile_sha256": "b" * 64}
    approval = {"operation_key": "operation", "approval_id": "approval", "approval_manifest_hash": "c" * 64, "carrier_binding": binding}
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", None)
    with pytest.raises(ValueError):
        executor.verify_installed_carrier_qualification(approval, authority_epoch=1)
    def qualified(request):
        now = datetime.now(timezone.utc)
        return {"binding": request, "state": "qualified", "revocation": "current", "session_freshness": "verified-absent", "source": "test://qualification", "observed_at": now.isoformat(), "expires_at": (now + timedelta(minutes=1)).isoformat()}
    runtime = SimpleNamespace(isolation_profile_sha256="b" * 64, carrier_qualification_verifier=qualified)
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", runtime)
    executor.verify_installed_carrier_qualification(approval, authority_epoch=1)
    runtime.isolation_profile_sha256 = "d" * 64
    with pytest.raises(ValueError):
        executor.verify_installed_carrier_qualification(approval, authority_epoch=1)
    runtime.isolation_profile_sha256 = "b" * 64
    runtime.carrier_qualification_verifier = lambda request: True
    with pytest.raises(ValueError):
        executor.verify_installed_carrier_qualification(approval, authority_epoch=1)


def test_host_qualification_cannot_reuse_old_authority_epoch(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from app.builderops import issue_delivery_effect_executor as executor

    approval = {"operation_key": "operation", "approval_id": "approval", "approval_manifest_hash": "c" * 64,
                "carrier_binding": {"isolation_profile_sha256": "b" * 64}}
    now = datetime.now(timezone.utc)
    def stale_epoch(request):
        return {"binding": {**request, "authority_epoch": 1}, "state": "qualified", "revocation": "current", "session_freshness": "verified-absent",
                "source": "test://qualification", "observed_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=1)).isoformat()}
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME",
                        SimpleNamespace(isolation_profile_sha256="b" * 64, carrier_qualification_verifier=stale_epoch))
    with pytest.raises(ValueError):
        executor.verify_installed_carrier_qualification(approval, authority_epoch=2)


@pytest.mark.parametrize("event_type", ["assistant", "user", "system", "unknown"])
def test_missing_identity_on_nonterminal_event_keeps_outcome_unknown(event_type):
    observed = ClaudeStreamObservation(SESSION)
    observed.observe(event(type="system", subtype="init", session_id=SESSION))
    observed.observe(event(type=event_type, subtype="other"))
    observed.observe(event(type="result", subtype="success", session_id=SESSION, is_error=False, result="{}"))
    with pytest.raises(IssueSessionLaunchError):
        observed.terminal(0)


@pytest.mark.parametrize("bad_stage", ["init", "result", "nested"])
def test_duplicate_json_keys_never_produce_success(bad_stage):
    entries = []
    observed = ClaudeStreamObservation(SESSION, entries.append)
    if bad_stage == "init":
        observed.observe('{"type":"system","subtype":"init","session_id":"other","session_id":"' + SESSION + '"}')
        assert entries == []
    else:
        observed.observe(event(type="system", subtype="init", session_id=SESSION))
        if bad_stage == "result":
            observed.observe('{"type":"result","subtype":"success","is_error":false,"session_id":"other","session_id":"' + SESSION + '","result":"{}"}')
        else:
            observed.observe(event(type="result", subtype="success", session_id=SESSION, is_error=False, result='{"status":"failed","status":"completed"}'))
    with pytest.raises(IssueSessionLaunchError):
        observed.terminal(0)


def test_unsafe_model_is_rejected_by_planner_and_direct_command():
    from app.builderops.epic_dispatch import EpicDispatchError, build_dispatch_plan
    from app.builderops.issue_delivery_worker_isolation import IssueWorkerIsolationError, _validate_direct_claude_command
    from tests.builderops.test_epic_dispatch import _candidate

    with pytest.raises(EpicDispatchError, match="model"):
        build_dispatch_plan(independent_issue_numbers=[3001], run_id="invalid-model", candidates=[_candidate(3001, risk="high")],
                            runtime_targets=["claude"], carrier_target={"capability": "sol", "model": "vendor/claude-model", "reasoning_effort": "high"})
    command = ["claude", "--print", "--output-format", "stream-json", "--verbose", "--session-id", SESSION,
               "--model", "vendor/claude-model", "--effort", "high", "--permission-mode", "acceptEdits"]
    with pytest.raises(IssueWorkerIsolationError, match="model"):
        _validate_direct_claude_command(command)
