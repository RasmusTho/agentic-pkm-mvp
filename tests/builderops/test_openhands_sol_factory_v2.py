"""Sol/high factory admission and guarded transport, with only external ports replaced."""
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_factory as factory
from app.builderops import openhands_owner_acp as owner
from app.builderops import openhands_policy as policy
from app.builderops import openhands_service as service
from app.builderops.openhands_proxy import GuardedProxy
from tests.builderops.test_openhands_delivery import BODY, HEAD, ROOT, orchestration  # noqa: F401

_REAL_VALIDATE = delivery._validate_executables
_REAL_PREVIEW = delivery.preview
_REAL_INCLUDE = delivery._include_git_metadata
_REAL_JSON_RESULT = delivery._json_result


def test_owner_model_free_delegates_one_explicit_selection(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(owner, "_port", lambda: 18999)
    monkeypatch.setattr(owner, "_invoke", lambda args, env: calls.append((args, env)) or
                        SimpleNamespace(returncode=0, stdout='{}'))
    owner.run_command(tmp_path / "entry", "start #42 gpt-6.1-sol high")
    assert calls[0][0][1:] == ["start", "--issue", "42", "--model", "gpt-6.1-sol", "--effort", "high", "--port", "18999"]
    for message in ("start #42 gpt-6.1-astra high", "start #42 gpt-6.1-sol low", "status #42 gpt-6.1-sol high"):
        owner.run_command(tmp_path / "entry", message)
    assert len(calls) == 1


def test_delivery_real_admission_records_selection_before_first_prompt(orchestration, tmp_path, monkeypatch):  # noqa: F811
    kwargs, events, _ = orchestration
    python = Path(sys.executable)
    acp = tmp_path / "acp" / "codex-acp"
    acp.parent.mkdir()
    acp.write_text("# fixture")
    (acp.parent / "package.json").write_text(json.dumps({"name": "@agentclientprotocol/codex-acp", "version": delivery.ACP_VERSION}))
    settings = {"guard_executable": str(Path(delivery.__file__).resolve().parents[2] / "scripts/openhands_guarded_codex"),
                "codex_binary": str(python), "codex_config_args": ["-c", 'permissions.builder_factory.filesystem={}'], "sandbox_read_roots": [str(tmp_path)],
                "conversations_path": str(tmp_path / "conversations"), "bash_events_dir": str(tmp_path / "events"),
                "conversation_worktree_root": str(tmp_path / "trees"), "acp_model": "gpt-6.1-sol", "acp_effort": "high"}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    monkeypatch.setattr(delivery, "_validate_executables", _REAL_VALIDATE)
    monkeypatch.setattr(delivery, "preview", _REAL_PREVIEW)
    monkeypatch.setattr(delivery, "_include_git_metadata", _REAL_INCLUDE)
    monkeypatch.setattr(delivery, "_json_result", _REAL_JSON_RESULT)
    git_dir = tmp_path / "git-common"
    git_dir.mkdir()
    issue = {"number": 123, "title": "Implement feature", "body": BODY, "state": "OPEN",
             "labels": [{"name": "agent:ready"}], "url": f"https://github.com/{delivery.REPOSITORY}/issues/123",
             "updatedAt": "2026-11-08T00:00:00Z"}
    def external(command, **kwargs):
        if command[0] == str(python):
            output = "acp-effort-supported" if "acp-effort-supported" in command[-1] else "1.62.0"
        elif command[0] == "gh":
            output = json.dumps(issue if command[1:3] == ["issue", "view"] else [])
        elif command[-2:] == ["rev-parse", "--show-toplevel"]:
            output = str(ROOT)
        elif command[-3:] == ["remote", "get-url", "origin"]:
            output = f"https://github.com/{delivery.REPOSITORY}.git"
        elif command[-3:] == ["rev-parse", "--verify", "refs/remotes/origin/main^{commit}"]:
            output = HEAD
        elif command[-2:] == ["--path-format=absolute", "--git-common-dir"]:
            output = str(git_dir)
        elif "show-ref" in command:
            return subprocess.CompletedProcess(command, 1, "", "")
        elif "check-ref-format" in command:
            output = ""
        elif "show" in command:
            output = (ROOT / command[-1].split(":", 1)[1]).read_text()
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, output, "")
    monkeypatch.setattr(delivery, "_run", external)
    kwargs.update(python=python, node=python, acp=acp, settings_file=path)
    result = delivery.start(**kwargs)
    assert result["state"]["acp_model"] == "gpt-6.1-sol" and result["state"]["acp_effort"] == "high"
    body = next(e[2] for e in events if e[0] == "POST" and e[1] == "/conversations")
    assert body["agent_settings"]["acp_model"] == "gpt-6.1-sol"
    assert body["agent_settings"]["acp_effort"] == "high" and body["initial_message"]
    count = len(events)
    with pytest.raises(delivery.DeliveryError, match="already recorded"):
        delivery.start(**kwargs)
    assert len(events) == count


def test_guard_binds_sol_high_and_refuses_auth_model_and_effort_mismatch(tmp_path):
    child = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO())
    output = io.BytesIO()
    guard = GuardedProxy(child, tmp_path, output, allowed_read_roots=(), model="gpt-6.1-sol", effort="high")
    cfg = {"model": "gpt-6.1-sol", "model_reasoning_effort": "high", "model_provider": "openai",
           "chatgpt_base_url": "https://chatgpt.com/backend-api/", "web_search": "disabled",
           "features": {k: False for k in ("apps", "multi_agent", "js_repl", "hooks", "skill_mcp_dependency_install")},
           "permissions": {policy.PROFILE: {"filesystem": {":minimal": "read", ":workspace_roots": "write"},
                                             "network": {"enabled": False}}}}
    for account, config in (({"type": "apiKey"}, cfg), ({"type": "chatgpt"}, {**cfg, "model_reasoning_effort": "low"}),
                            ({"type": "chatgpt"}, {**cfg, "model": "gpt-6.1-terra"})):
        with pytest.raises(policy.PolicyRefusal):
            policy.verify_effective_config(config, account, allowed_read_roots=(), model=guard.model, effort=guard.effort)
    policy.verify_effective_config(cfg, {"type": "chatgpt"}, allowed_read_roots=(), model=guard.model, effort=guard.effort)
    guard.receive_server({"id": "builder-factory:auth", "result": {"account": {"type": "chatgpt"}}})
    guard.receive_server({"id": "builder-factory:config", "result": {"config": cfg}})
    assert guard._preflight == "ok"
    guard._threads.add("thread")
    for ident, model, effort in ((1, "gpt-6.1-astra", "high"), (2, "gpt-6.1-sol", "low")):
        guard.receive_client({"id": ident, "method": "turn/start", "params": {"threadId": "thread", "model": model, "effort": effort}})
    assert not child.stdin.getvalue()
    guard.receive_client({"id": 3, "method": "turn/start", "params": {"threadId": "thread", "model": "gpt-6.1-sol", "effort": "high"}})
    assert json.loads(child.stdin.getvalue())["params"]["effort"] == "high"
    with pytest.raises((ValueError, RuntimeError)):
        GuardedProxy(child, tmp_path, output, allowed_read_roots=(), model="gpt-6.1-astra", effort="high")


def test_existing_unknown_terra_refuses_sol_restart(tmp_path, monkeypatch, capsys):
    roots = [tmp_path / name for name in ("install", "state", "trees", "repo")]
    for root in roots:
        root.mkdir(mode=0o700)
    run = roots[1] / "issue-42"
    run.mkdir(mode=0o700)
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "phase": "creating_conversation"}
    service._write(run, state)
    monkeypatch.setattr(factory, "_restart", lambda *a: pytest.fail("must preserve unknown Terra run"))
    result = factory.main(["start", "--issue", "42", "--install-root", str(roots[0]), "--state-root", str(roots[1]),
                           "--worktree-root", str(roots[2]), "--repo-root", str(roots[3]),
                           "--model", "gpt-6.1-sol", "--effort", "high"])
    assert result != 0 and "selection differs" in capsys.readouterr().err
    assert service._read(run) == state


def test_explicit_settings_validate_without_changing_codex_home(tmp_path):
    settings = {"guard_executable": sys.executable, "codex_binary": sys.executable,
                "codex_config_args": [], "sandbox_read_roots": [str(tmp_path)],
                "conversations_path": str(tmp_path / "c"), "bash_events_dir": str(tmp_path / "e"),
                "conversation_worktree_root": str(tmp_path / "w"), "acp_model": "gpt-6.1-sol", "acp_effort": "high"}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    assert service._settings(path)["acp_effort"] == "high"
    for model, effort in (("gpt-6.1-astra", "high"), ("gpt-6.1-sol", "low"), ("gpt-6.1-sol", None)):
        path.write_text(json.dumps({**settings, "acp_model": model, "acp_effort": effort}))
        with pytest.raises(service.ServiceError):
            service._settings(path)


def test_finished_selection_readback_refuses_wrong_model_and_effort(tmp_path, monkeypatch):
    state = {"port": 1234, "conversation_id": "synthetic", "worktree": "/work", "acp_model": "gpt-6.1-sol", "acp_effort": "high"}
    info = {"id": "synthetic", "workspace": {"working_dir": "/work"}, "execution_status": "finished",
            "agent": {"kind": "ACPAgent", "acp_server": "codex", "acp_model": "gpt-6.1-sol", "acp_effort": "high"},
            "current_model_id": "gpt-6.1-sol", "current_effort": "high"}
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "synthetic-key")
    monkeypatch.setattr(delivery, "_http", lambda *args, **kwargs: (200, info))
    assert delivery._conversation(tmp_path, state) == info
    for field, bad in (("current_model_id", "gpt-6.1-terra"), ("current_effort", "low")):
        original = info[field]
        info[field] = bad
        with pytest.raises(delivery.DeliveryError, match="not verified"):
            delivery._conversation(tmp_path, state)
        info[field] = original


def test_guard_refuses_wrong_observed_thread_model(tmp_path):
    result = {"thread": {"id": "review"}, "model": "gpt-6.1-terra", "modelProvider": "openai",
              "activePermissionProfile": {"id": policy.PROFILE}, "approvalPolicy": "never", "cwd": str(tmp_path)}
    with pytest.raises(policy.PolicyRefusal, match="mismatch"):
        policy.verify_thread_response(result, workspace=tmp_path, model="gpt-6.1-sol", effort="high")


def test_owner_status_distinguishes_selection_from_unavailable_observation():
    selection = {"acp_model": "gpt-6.1-sol", "acp_effort": "high"}
    summary = owner._summary("status", 42, {"state": selection})
    assert "Selected: gpt-6.1-sol / high" in summary and "unavailable" in summary
    summary = owner._summary("status", 42, {"state": selection,
                             "current_model_id": "gpt-6.1-sol", "current_effort": "high"})
    assert "ACP current: gpt-6.1-sol / high" in summary


def test_recovery_never_relabels_a_retained_terra_selection(tmp_path):
    state = {"conversation_id": "unknown-retained", "acp_model": "gpt-6.1-terra", "acp_effort": "high"}
    settings = {"conversations_path": str(tmp_path), "acp_model": "gpt-6.1-sol", "acp_effort": "high"}
    with pytest.raises(delivery.DeliveryError, match="mismatched"):
        factory._persisted_session(settings, state, "finished")
