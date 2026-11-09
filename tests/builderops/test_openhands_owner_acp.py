import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import acp
import pytest

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_owner as owner_setup
from app.builderops import openhands_owner_acp as owner


@pytest.mark.parametrize("message", ["start 1; start 2", "start 1 and 2", "start 0", "start -1", "delete 3", "start 4\nstatus 5"])
def test_owner_requires_one_explicit_issue_command(tmp_path, monkeypatch, message):
    monkeypatch.setattr(owner.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected effect"))
    assert "one explicit Issue command" in owner.run_command(tmp_path / "entry", message)


def test_owner_calls_only_factory_and_does_not_forward_provider_keys(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "not-forwarded")
    monkeypatch.setattr(owner, "_port", lambda: 18650)

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"conversation_status": "running"}))

    monkeypatch.setattr(owner.subprocess, "run", execute)
    result = owner.run_command(tmp_path / "openhands", "/start #42")
    assert calls[0][0] == [str(tmp_path / "openhands"), "start", "--issue", "42", "--port", "18650"]
    assert "OPENAI_API_KEY" not in calls[0][1]["env"]
    assert "Conversation: running" in result


def test_uncertain_start_is_not_retried(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(owner, "_port", lambda: 18650)

    def timed_out(*args, **kwargs):
        calls.append(args)
        raise owner.subprocess.TimeoutExpired(args[0], 240)

    monkeypatch.setattr(owner.subprocess, "run", timed_out)
    assert "status #42" in owner.run_command(tmp_path / "openhands", "start 42")
    assert len(calls) == 1


def test_owner_explains_known_admission_failure_without_echoing_arbitrary_output(tmp_path, monkeypatch):
    monkeypatch.setattr(owner, "_port", lambda: 18650)
    monkeypatch.setattr(owner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stderr="OpenHands factory: Issue does not have exactly agent:ready as its agent state"))
    assert "not ready" in owner.run_command(tmp_path / "entry", "start #42")
    monkeypatch.setattr(owner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stderr="untrusted output must not be echoed"))
    assert "untrusted" not in owner.run_command(tmp_path / "entry", "start #42")


def test_status_shows_published_pr_and_ci_without_raw_state():
    result = owner._summary("status", 42, {"state": {"full_publication": {"pr_number": 123}},
        "watcher": {"status": "finished", "phase": "published", "ci": {"status": "passed"}}})
    assert "https://github.com/RasmusTho/agentic-pkm-mvp/pull/123" in result
    assert "CI: passed" in result
    assert "full_publication" not in result


def test_real_acp_process_accepts_a_status_command(tmp_path):
    entry = tmp_path / "factory"
    entry.write_text('#!/bin/sh\nprintf \'{"conversation_status":"finished"}\\n\'\n')
    entry.chmod(0o755)

    class Client:
        def __init__(self):
            self.messages = []

        def on_connect(self, connection):
            pass

        async def session_update(self, session_id, update, **kwargs):
            content = getattr(update, "content", None)
            if getattr(content, "type", None) == "text":
                self.messages.append(content.text)

    async def exercise():
        client = Client()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(owner.__file__).resolve().parents[2])
        async with acp.spawn_agent_process(client, sys.executable, "-m", "app.builderops.openhands_owner_acp",
                                           "--entry", str(entry), env=env) as (connection, _process):
            initialized = await connection.initialize(protocol_version=acp.PROTOCOL_VERSION)
            assert initialized.agent_capabilities.load_session
            session = await connection.new_session(cwd=str(tmp_path))
            result = await connection.prompt(session_id=session.session_id, prompt=[acp.text_block("status #42")])
            assert result.stop_reason == "end_turn"
            assert any("Conversation: finished" in text for text in client.messages)

    asyncio.run(exercise())


def test_attach_reuses_the_same_model_free_control_conversation(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "bin").mkdir(parents=True)
    (install / "bin/openhands").write_text("#!/bin/sh\n")
    directory = tmp_path / "issue"
    directory.mkdir(mode=0o700)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    host = {"issue": 42, "worktree": str(worktree), "port": 8123}
    monkeypatch.setattr(delivery, "_state", lambda *args: host)
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "test-key")
    calls = []
    stored = {}

    def request(port, key, method, path, payload=None, **kwargs):
        calls.append((method, path))
        if method == "POST":
            assert payload["autotitle"] is False
            assert payload["agent_settings"]["acp_server"] == "custom"
            assert "acp_model" not in payload["agent_settings"]
            stored.update(id=payload["conversation_id"], workspace=payload["workspace"], title=None,
                          agent={"kind": "ACPAgent", "acp_server": "custom", "acp_model": None,
                                 "acp_command": payload["agent_settings"]["acp_command"]})
            return 201, {}
        if method == "PATCH":
            stored["title"] = payload["title"]
            return 200, {}
        return 200, stored

    monkeypatch.setattr(delivery, "_http", request)
    first = owner_setup.attach(install, directory, 42)
    second = owner_setup.attach(install, directory, 42)
    assert first["conversation_id"] == second["conversation_id"]
    assert sum(method == "POST" for method, _ in calls) == 1
    assert stored["title"] == "Builder control"


def test_uncertain_control_creation_is_not_replayed(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "bin").mkdir(parents=True)
    (install / "bin/openhands").write_text("#!/bin/sh\n")
    directory = tmp_path / "issue"
    directory.mkdir(mode=0o700)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(delivery, "_state", lambda *args: {"issue": 42, "worktree": str(worktree), "port": 8123})
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "test-key")
    calls = []

    def request(port, key, method, path, payload=None, **kwargs):
        calls.append(method)
        return (500, {}) if method == "POST" else (404, {})

    monkeypatch.setattr(delivery, "_http", request)
    with pytest.raises(delivery.DeliveryError, match="uncertain"):
        owner_setup.attach(install, directory, 42)
    with pytest.raises(delivery.DeliveryError, match="could not be verified"):
        owner_setup.attach(install, directory, 42)
    assert calls.count("POST") == 1
