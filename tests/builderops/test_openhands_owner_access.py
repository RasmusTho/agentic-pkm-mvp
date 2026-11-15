from app.builderops import openhands_owner_access as owner


def test_status_is_read_only_and_names_unknowns(monkeypatch):
    import json
    from types import SimpleNamespace

    calls = []
    state = {"issue_mappings": {"6618": {"worker": "w-6618", "state": "stopped_verified",
               "branch": "codex/existing", "conversation": {"id": "retained-id", "engine": "codex", "model": "gpt-6.1-terra"},
               "next_action": "existing owner repairs P1; see latest comment"}}}

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"state": state, "observations": {}}))

    monkeypatch.setattr(owner.subprocess, "run", run)
    text = owner.run_command({"runner": "/frozen", "root": "/workspaces"}, "status")
    assert len(calls) == 1
    code = calls[0][2]
    assert "_load_state" in code and "conversation_status" in code and "include_messages=False" in code
    assert not any(action in code for action in ("worker_stop", "conversation_start", "worker_start"))
    assert "retained-id" in text and "gpt-6.1-terra" in text and "unknown is not zero" in text
    assert "existing owner repairs P1" in text and "/pull/6628" in text and "not delivery" in text


def test_unknown_commands_never_execute_and_stop_is_owned(monkeypatch):
    calls = []
    monkeypatch.setattr(owner, "_controller", lambda config, *args: calls.append(args) or {})
    assert "model-free" in owner.run_command({}, "stop w-6618")
    assert calls == []
    assert "retained" in owner.run_command({}, "sandbox stop")
    assert calls == [("worker-stop", "--worker", "owner-sandbox", "--reason", "owner stopped disposable sandbox")]


def test_uncertain_creation_reconciles_without_another_create(monkeypatch):
    calls = []
    reads = []

    def controller(config, *args):
        calls.append(args[0])
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "running"}]}
        if args[0] == "conversation-status":
            reads.append(1)
            return {"conversation": {"id": "same-retained-id", "status": "created" if len(reads) > 1 else "unknown"}, "reachable": len(reads) > 1}
        return {}

    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_profile", lambda config: None)
    result = owner.run_command({"sandbox_url": "https://sandbox.example"}, "sandbox start")
    assert "is running" in result
    assert calls == ["status", "conversation-status", "conversation-reconcile", "conversation-status"]


def test_unreachable_creation_never_reports_readiness(monkeypatch):
    def controller(config, *args):
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "running"}]}
        return {"conversation": {"id": "retained-id", "status": "unknown"}, "reachable": False}

    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_profile", lambda config: None)
    result = owner.run_command({}, "sandbox start")
    assert "not verified reachable" in result and "is running" not in result


def test_start_producer_uses_the_qualified_native_configuration(monkeypatch):
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(owner.subprocess, "run", lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0, stdout="{}"))
    owner._controller({"runner": "/frozen", "root": "/workspaces", "sandbox_epic": 6630}, "openhands-start")
    assert "epic-worker@sha256:3c3c2472" in calls[0][2]
    assert "epicws-6615-egress-20261114" in calls[0][2]
    assert "range(18840,18848)" in calls[0][2]
