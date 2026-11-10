import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops.openhands_policy import (
    MODEL,
    PROFILE,
    PolicyRefusal,
    prepare_request,
    verify_effective_config,
    verify_thread_response,
)
from app.builderops.openhands_proxy import GuardedProxy
from app.builderops import openhands_service as service


def test_model_rejection_preserves_the_existing_proxy_session(tmp_path: Path) -> None:
    child = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO())
    output = io.BytesIO()
    proxy = GuardedProxy(child, tmp_path, output, allowed_read_roots=())
    proxy._preflight = "ok"
    proxy._threads.add("main")
    proxy.receive_client({"id": 1, "method": "turn/start",
                          "params": {"threadId": "main", "model": "other-model"}})
    proxy.receive_client({"id": 2, "method": "turn/start",
                          "params": {"threadId": "main", "input": []}})
    rejected = json.loads(output.getvalue())
    forwarded = json.loads(child.stdin.getvalue())
    assert rejected["id"] == 1 and rejected["error"]["message"] == "model_not_permitted"
    assert forwarded["id"] == 2 and forwarded["params"]["model"] == MODEL
    assert forwarded["params"]["threadId"] == "main"


def test_delivery_proxy_blocks_replay_after_interrupt(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": str(workspace), "phase": "active"}
    service._write(state_dir, state)
    child = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO())
    output = io.BytesIO()
    proxy = GuardedProxy(child, workspace, output, allowed_read_roots=(), delivery_state_dir=state_dir)
    proxy._preflight = "ok"
    proxy._threads.add("main")
    request = {"id": 1, "method": "turn/start", "params": {"threadId": "main", "input": []}}
    proxy.receive_client(request)
    before = child.stdin.getvalue()
    assert json.loads(before)["id"] == 1
    for index, update in enumerate(({"phase": "interrupting"}, {"phase": "interrupted"},
                                    {"phase": "resuming"}, {"worktree": str(tmp_path)}), 2):
        service._write(state_dir, {**state, **update})
        proxy.receive_client({**request, "id": index})
        assert child.stdin.getvalue() == before
    refusals = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(refusals) == 4
    assert all(item["error"]["message"] == "delivery_continuation_unverified" for item in refusals)


def test_cancel_fence_orders_a_waiting_turn_after_persisted_interrupt(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "worktree": str(workspace), "phase": "active"}
    service._write(state_dir, state)
    child = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO())
    output = io.BytesIO()
    proxy = GuardedProxy(child, workspace, output, allowed_read_roots=(), delivery_state_dir=state_dir)
    proxy._preflight = "ok"
    proxy._threads.add("main")
    with service._locked(state_dir / "execution-fence"):
        thread = threading.Thread(target=proxy.receive_client, args=({
            "id": 1, "method": "turn/start", "params": {"threadId": "main", "input": []}},))
        thread.start()
        service._write(state_dir, {**state, "phase": "interrupting"})
    thread.join(timeout=2)
    assert not thread.is_alive() and not child.stdin.getvalue()
    assert json.loads(output.getvalue())["error"]["message"] == "delivery_continuation_unverified"


def test_title_helper_is_refused_without_poisoning_the_next_turn(tmp_path: Path) -> None:
    threads = {"main"}
    with pytest.raises(PolicyRefusal, match="ephemeral_helper_disabled"):
        prepare_request(
            {"id": 1, "method": "thread/start", "params": {"ephemeral": True}},
            workspace=tmp_path,
            threads=threads,
        )
    turn = prepare_request(
        {"id": 2, "method": "turn/start", "params": {"threadId": "main", "input": []}},
        workspace=tmp_path,
        threads=threads,
    )
    assert turn["params"]["model"] == MODEL
    assert turn["params"]["permissions"] == PROFILE
    assert turn["params"]["approvalPolicy"] == "never"


def test_fresh_proxy_can_resume_only_the_authorized_thread(tmp_path: Path) -> None:
    thread_id = "01a1bcfd-b399-7e32-8834-4e34bd9bfbac"
    request = {"method": "thread/resume", "params": {"threadId": thread_id}}
    with pytest.raises(PolicyRefusal, match="unknown_thread"):
        prepare_request(request, workspace=tmp_path, threads=set())
    resumed = prepare_request(request, workspace=tmp_path, threads=set(), resume_thread_id=thread_id)
    assert resumed["params"]["cwd"] == str(tmp_path.resolve())
    with pytest.raises(PolicyRefusal, match="unknown_thread"):
        prepare_request({"method": "turn/start", "params": {"threadId": thread_id}},
                        workspace=tmp_path, threads=set(), resume_thread_id=thread_id)
    with pytest.raises(PolicyRefusal, match="unknown_thread"):
        prepare_request({"method": "thread/resume", "params": {}},
                        workspace=tmp_path, threads=set())


def test_unapproved_model_and_workspace_are_refused(tmp_path: Path) -> None:
    for params in (
        {"model": "another-model", "cwd": str(tmp_path)},
        {"modelProvider": "another-provider", "cwd": str(tmp_path)},
        {"cwd": str(tmp_path.parent)},
    ):
        with pytest.raises(PolicyRefusal):
            prepare_request({"method": "thread/start", "params": params}, workspace=tmp_path, threads=set())
    with pytest.raises(PolicyRefusal, match="unknown_thread"):
        prepare_request({"method": "turn/start", "params": {"threadId": "unobserved"}}, workspace=tmp_path, threads=set())
    with pytest.raises(PolicyRefusal, match="collaboration_not_permitted"):
        prepare_request(
            {"method": "turn/start", "params": {"threadId": "main", "collaborationMode": {}}},
            workspace=tmp_path,
            threads={"main"},
        )


def test_client_cannot_raise_sandbox_or_install_mcp(tmp_path: Path) -> None:
    request = {
        "method": "thread/start",
        "params": {"config": {"mcp_servers": {"untrusted": {}}}, "sandbox": "danger-full-access"},
    }
    prepared = prepare_request(request, workspace=tmp_path, threads=set())
    assert prepared["params"]["config"] == {}
    assert prepared["params"]["permissions"] == PROFILE
    assert prepared["params"]["cwd"] == str(tmp_path.resolve())
    assert "sandbox" not in prepared["params"]
    assert request["params"]["sandbox"] == "danger-full-access"
    for method in ("command/exec", "config/batchWrite", "review/start", "new/unknown-effect"):
        with pytest.raises(PolicyRefusal, match="method_not_permitted"):
            prepare_request({"method": method, "params": {}}, workspace=tmp_path, threads=set())


def test_a_turn_requires_observed_model_provider_and_profile(tmp_path: Path) -> None:
    observed = {
        "thread": {"id": "main"},
        "model": MODEL,
        "modelProvider": "openai",
        "activePermissionProfile": {"id": PROFILE},
        "approvalPolicy": "never",
        "cwd": str(tmp_path),
    }
    assert verify_thread_response(observed, workspace=tmp_path) == "main"
    for key in ("model", "modelProvider", "activePermissionProfile", "thread", "approvalPolicy", "cwd"):
        with pytest.raises(PolicyRefusal):
            verify_thread_response({**observed, key: None}, workspace=tmp_path)


def test_effective_configuration_refuses_hidden_external_tools_and_wrong_auth() -> None:
    config = {
        "model": MODEL,
        "model_provider": "openai",
        "chatgpt_base_url": "https://chatgpt.com/backend-api/",
        "features": {"apps": False, "multi_agent": False, "js_repl": False, "hooks": False, "skill_mcp_dependency_install": False},
        "web_search": "disabled",
        "plugins": {"known": {"enabled": False}},
        "mcp_servers": {"known": {"enabled": False}},
        "permissions": {PROFILE: {"filesystem": {":minimal": "read", ":workspace_roots": "write"}, "network": {"enabled": False}}},
    }
    verify_effective_config(config, {"type": "chatgpt"}, allowed_read_roots=())
    with pytest.raises(PolicyRefusal, match="uncontrolled_execution_features"):
        verify_effective_config({**config, "features": {**config["features"], "apps": True}}, {"type": "chatgpt"}, allowed_read_roots=())
    with pytest.raises(PolicyRefusal, match="subscription_auth_not_verified"):
        verify_effective_config(config, {"type": "apiKey"}, allowed_read_roots=())
    with pytest.raises(PolicyRefusal, match="uncontrolled_external_tools"):
        verify_effective_config({**config, "mcp_servers": {"unknown": {}}}, {"type": "chatgpt"}, allowed_read_roots=())
    with pytest.raises(PolicyRefusal, match="effective_permissions_mismatch"):
        verify_effective_config({**config, "permissions": {PROFILE: {"filesystem": {":workspace_roots": "write", "/": "read"}, "network": {"enabled": False}}}}, {"type": "chatgpt"}, allowed_read_roots=())


def test_owner_control_backend_refuses_native_codex(monkeypatch, capsys):
    from app.builderops import openhands_proxy

    monkeypatch.setenv("OPENHANDS_FACTORY_CONTROL_ONLY", "1")
    assert openhands_proxy.main() == 2
    assert "authorize an Issue" in capsys.readouterr().err
