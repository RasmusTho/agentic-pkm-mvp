import pytest

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
            return {"conversation": {"id": "same-retained-id", "engine": "codex", "model": "gpt-6.1-terra", "status": "created" if len(reads) > 1 else "unknown"}, "reachable": len(reads) > 1}
        return {}

    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_profile", lambda config: None)
    monkeypatch.setattr(owner, "_sandbox_auth", lambda config, engine: None)
    result = owner.run_command({"sandbox_url": "https://sandbox.example"}, "sandbox start")
    assert "is running" in result
    assert calls == ["status", "conversation-status", "conversation-reconcile", "conversation-status"]


def test_historical_terra_still_reports_readiness_with_omitted_effort(monkeypatch):
    def controller(config, *args):
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "running"}]}
        assert args[0] == "conversation-status"
        return {"reachable": True, "conversation": {"id": "retained", "status": "created",
                                                      "engine": "codex", "model": "gpt-6.1-terra"}}

    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_auth", lambda config, engine: None)
    monkeypatch.setattr(owner, "_sandbox_profile", lambda *args: pytest.fail("historical profile was retained"))
    assert "is running" in owner.run_command({"sandbox_url": "https://sandbox.example"},
                                            "sandbox start codex gpt-6.1-terra")


def test_unreachable_creation_never_reports_readiness(monkeypatch):
    def controller(config, *args):
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "running"}]}
        return {"conversation": {"id": "retained-id", "status": "unknown"}, "reachable": False}

    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_profile", lambda config: None)
    monkeypatch.setattr(owner, "_sandbox_auth", lambda config: None)
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


def test_existing_sandbox_does_not_relabel_or_create_for_new_selection(monkeypatch):
    calls = []
    def controller(config, *args):
        calls.append(args[0])
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "running"}]}
        if args[0] == "conversation-status":
            return {"reachable": True, "conversation": {"id": "old", "status": "created",
                    "engine": "codex", "model": "gpt-6.1-terra"}}
        return {}
    monkeypatch.setattr(owner, "_controller", controller)
    assert "differs" in owner.run_command({}, "sandbox start gpt-6.1-sol high")
    assert calls == ["status", "conversation-status"]


def test_sol_selection_is_passed_before_prompt_and_requires_live_readback(monkeypatch):
    calls = []
    reads = 0
    def controller(config, *args):
        nonlocal reads
        calls.append(args)
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "running"}]}
        if args[0] == "conversation-status":
            reads += 1
            if reads == 1:
                return {"conversation": {"status": "ended_with_container"}}
            return {"reachable": True, "conversation": {"id": "new", "status": "created",
                    "engine": "codex", "model": "gpt-6.1-sol", "effort": "high"},
                    "agent_settings": {"agent_kind": "acp", "acp_server": "codex",
                    "acp_model": "gpt-6.1-sol", "current_model_id": "gpt-6.1-sol",
                    "acp_effort": "high", "current_effort": "high"}}
        return {}
    profiles = []
    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_profile", lambda config, engine, model, effort: profiles.append((engine, model, effort)))
    monkeypatch.setattr(owner, "_sandbox_auth", lambda config, engine: None)
    result = owner.run_command({"readiness_prompt": "/prompt", "sandbox_url": "https://sandbox.example"},
                               "sandbox start gpt-6.1-sol high")
    assert "is running" in result and profiles == [("codex", "gpt-6.1-sol", "high")]
    create = next(c for c in calls if c[0] == "conversation-start")
    assert create[create.index("--model") + 1] == "gpt-6.1-sol"
    assert create[create.index("--effort") + 1] == "high"


def test_sandbox_auth_failure_is_a_refusal(monkeypatch):
    from types import SimpleNamespace
    import pytest
    monkeypatch.setattr(owner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(owner.OwnerAccessError, match="authentication is not verified"):
        owner._sandbox_auth({"runner": "/fake", "root": "/fake", "sandbox_epic": 6630})


def test_sol_readiness_refuses_wrong_observed_effort(monkeypatch):
    def controller(config, *args):
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "running"}]}
        return {"reachable": True, "conversation": {"id": "same", "status": "created",
                "engine": "codex", "model": "gpt-6.1-sol", "effort": "high"},
                "agent_settings": {"agent_kind": "acp", "acp_server": "codex",
                    "acp_model": "gpt-6.1-sol", "current_model_id": "gpt-6.1-sol",
                "acp_effort": "high", "current_effort": "low"}}
    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_auth", lambda *args: (_ for _ in ()).throw(AssertionError("not ready")))
    assert "not verified" in owner.run_command({}, "sandbox start gpt-6.1-sol high")


@pytest.mark.parametrize("selector,verified,live", [
    (None, None, "claude-sonnet-6-2"), ("sonnet", True, "sonnet"),
    ("sonnet", False, "sonnet"), ("sonnet", True, "default"),
])
def test_sandbox_start_claude_uses_only_provisioned_route_and_exact_readback(monkeypatch, selector, verified, live):
    calls = []
    model = "claude-sonnet-6-2"

    def controller(config, *args):
        calls.append(args)
        if args[0] == "status":
            return {"workers": [{"worker": "owner-sandbox", "container": "stopped", "recorded_state": "stopped_verified"}]}
        if args[0] == "conversation-status" and any(c[0] == "conversation-start" for c in calls):
            record = {"id": "new", "status": "created", "engine": "claude-code", "model": model}
            if selector:
                record["acp_selector"] = selector
            return {"reachable": True, "conversation": record, "selection_verified": verified,
                    "agent_settings": {"agent_kind": "acp", "acp_server": "claude-code",
                                       "acp_model": selector or model, "current_model_id": live}}
        return {}

    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_profile", lambda config, *selection: calls.append(selection))
    monkeypatch.setattr(owner, "_sandbox_auth", lambda config, engine: calls.append(("auth", engine)))
    assert "no provisioned claude-code" in owner.run_command({}, "sandbox start claude-code")
    assert [c[0] for c in calls] == ["status"]
    calls.clear()
    info = owner.run_command({"claude_env_file": "/provisioned/claude.env", "codex_home": "/do-not-use",
                              "readiness_prompt": "/prompt", "sandbox_url": "https://sandbox.example"}, "sandbox start claude-code")
    if selector and (not verified or live != selector):
        assert "not verified" in info and ("auth", "claude-code") not in calls
        return
    assert model in info and "is running" in info
    if selector:
        assert f"ACP selector `{selector}`" in info
    launch = next(c for c in calls if c[0] == "openhands-start")
    assert launch[-2:] == ("--claude-env-file", "/provisioned/claude.env")
    start = next(c for c in calls if c[0] == "conversation-start")
    assert start[3:6] == ("--engine", "claude-code", "--qualify-selection") and "--model" not in start
    assert ("auth", "claude-code") in calls and ("claude-code", model, None) in calls
