import json
import os
import subprocess
import tomllib
import uuid
from pathlib import Path

import pytest

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_factory as factory
from app.builderops import openhands_service as service


def _installation(tmp_path):
    install = tmp_path / "install"
    python = install / "venv/bin/python"
    acp = install / "acp/node_modules/.bin/codex-acp"
    for path in (python, acp):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    (acp.parent / "package.json").write_text(json.dumps({
        "name": "@agentclientprotocol/codex-acp", "version": delivery.ACP_VERSION,
    }))
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    return install, state, worktrees


def _recorded_run(install, state_root, worktrees, *, conversation="finished"):
    directory = state_root / "issue-123"
    directory.mkdir(mode=0o700)
    worktree = worktrees / "issue-123-openhands"
    worktree.mkdir()
    conversation_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "issue": 123,
             "phase": "interrupted" if conversation == "paused" else "active", "port": 8765,
             "root": str(factory.FACTORY_ROOT), "worktree": str(worktree),
             "conversation_id": conversation_id}
    service._write(directory, state)
    settings = {"guard_executable": str(factory.FACTORY_ROOT / "scripts/openhands_guarded_codex"),
                "codex_binary": str(Path(__import__("sys").executable)), "codex_config_args": [],
                "sandbox_read_roots": [str(worktrees)], "conversations_path": str(directory / "conversations"),
                "bash_events_dir": str(directory / "bash-events"),
                "conversation_worktree_root": str(directory / "conversation-worktrees")}
    settings_path = directory / "settings.json"
    settings_path.write_text(json.dumps(settings))
    settings_path.chmod(0o600)
    server_dir = directory / "server"
    server_dir.mkdir(mode=0o700)
    key = server_dir / "session-api-key"
    key.write_text("K" * 43 + "\n")
    key.chmod(0o600)
    saved = {"id": conversation_id, "execution_status": conversation,
             "workspace": {"working_dir": str(worktree)},
             "agent_state": {"acp_session_id": thread_id, "acp_session_cwd": str(worktree)}}
    saved_path = Path(settings["conversations_path"]) / uuid.UUID(conversation_id).hex / "base_state.json"
    saved_path.parent.mkdir(parents=True)
    saved_path.write_text(json.dumps(saved))
    server = {"port": 8765, "workspace": str(worktree), "python": str(install / "venv/bin/python"),
              "settings_file": str(settings_path)}
    return directory, state, server, saved, thread_id


def test_owner_start_builds_real_settings_and_routes_to_delivery(tmp_path, monkeypatch, capsys):
    install, state, worktrees = _installation(tmp_path)
    (install / "canvas").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(factory, "_base_config", lambda repo: None)
    refreshed = []
    monkeypatch.setattr(factory, "_refresh_base", lambda repo: refreshed.append(repo))
    node = Path(__import__("sys").executable)
    monkeypatch.setattr(factory, "_executable", lambda name: node)
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, factory.CODEX_VERSION + "\n" if a[0][-1] == "--version" else str(tmp_path), ""))
    monkeypatch.setattr(delivery, "_run", lambda command: subprocess.CompletedProcess(
        command, 0, delivery.SERVER_VERSION + "\n", ""))
    captured = {}

    def start(directory, repo, issue, authorized, branch, worktree, python, port, settings, node, acp):
        assert refreshed == [repo]
        captured.update(directory=directory, repo=repo, issue=issue, authorized=authorized,
                        branch=branch, worktree=worktree, python=python, port=port,
                        settings=delivery._validate_executables(python, node, acp, settings),
                        settings_path=settings)
        return {"state": {"port": port}, "conversation_status": "running"}

    monkeypatch.setattr(delivery, "start", start)
    assert factory.main(["start", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state), "--worktree-root", str(worktrees)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert captured["issue"] == captured["authorized"] == 123
    assert captured["branch"] == "codex/issue-123-openhands"
    assert captured["worktree"] == worktrees / "issue-123-openhands"
    assert captured["python"] == install / "venv/bin/python"
    assert not captured["settings_path"].exists()
    settings = captured["settings"]
    assert 'model="gpt-6.1-terra"' in settings["codex_config_args"]
    assert 'permissions.builder_factory.network.enabled=false' in settings["codex_config_args"]
    config = tomllib.loads("\n".join(settings["codex_config_args"][1::2]))
    assert config["model"] == "gpt-6.1-terra" and config["model_provider"] == "openai"
    profile = config["permissions"]["builder_factory"]
    assert profile["network"]["enabled"] is False
    assert str((install / "canvas").resolve()) in settings["sandbox_read_roots"]
    assert profile["filesystem"][str((install / "canvas").resolve())] == "read"
    assert profile["filesystem"] == {
        ":minimal": "read", ":workspace_roots": "write",
        **{root: "read" for root in settings["sandbox_read_roots"]},
    }
    assert settings["conversations_path"] == str(state / "issue-123/conversations")
    assert result["owner_ui"]["agent_server"] == "http://127.0.0.1:8765"
    assert result["owner_ui"]["session_key_file"].endswith("/server/session-api-key")


def test_owner_rejects_wrong_codex_version_before_delivery(tmp_path, monkeypatch, capsys):
    install, state, worktrees = _installation(tmp_path)
    monkeypatch.setattr(factory, "_refresh_base", lambda repo: None)
    monkeypatch.setattr(factory, "_executable", lambda name: Path(__import__("sys").executable))
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, "codex-cli 1.0.0\n", ""))
    monkeypatch.setattr(delivery, "start", lambda *args: (_ for _ in ()).throw(AssertionError()))
    assert factory.main(["start", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state), "--worktree-root", str(worktrees)]) == 1
    assert "Native Codex" in capsys.readouterr().err
    assert service._read(state / "issue-123") is None


def test_owner_status_and_cancel_use_recorded_run(tmp_path, monkeypatch, capsys):
    install, state, worktrees = _installation(tmp_path)
    seen = []
    for name in ("status", "cancel"):
        monkeypatch.setattr(delivery, name, lambda directory, n=name: (
            seen.append((n, directory)) or {"state": {"port": 8765}}
        ))
        assert factory.main([name, "--issue", "123", "--install-root", str(install),
                             "--state-root", str(state), "--worktree-root", str(worktrees)]) == 0
        assert json.loads(capsys.readouterr().out)["owner_ui"]["agent_server"].endswith(":8765")
    assert seen == [("status", state / "issue-123"), ("cancel", state / "issue-123")]


def test_ui_uses_recorded_loopback_backend_and_key_file(tmp_path, monkeypatch, capsys):
    install, state_root, worktrees = _installation(tmp_path)
    launcher = install / "bin/openhands_canvas.py"
    launcher.parent.mkdir()
    launcher.write_text("# installed launcher\n")
    directory = state_root / "issue-123"
    directory.mkdir(mode=0o700)
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "issue": 123,
             "port": 8765, "worktree": str(worktrees / "issue-123-openhands")}
    service._write(directory, state)
    monkeypatch.setattr(service, "status", lambda path: {
        "status": "running", "state": {"port": 8765, "workspace": state["worktree"]},
    })
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "http://127.0.0.1:3301\n", "")

    monkeypatch.setattr(factory.subprocess, "run", run)
    assert factory.main(["ui", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees),
                         "--ui-port", "3301", "--open"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ui"] == {"status": "running", "url": "http://127.0.0.1:3301"}
    command = calls[0]
    assert command[:3] == [str(install / "venv/bin/python"), str(launcher), "start"]
    assert command[command.index("--backend") + 1] == "http://127.0.0.1:8765"
    assert command[command.index("--key-file") + 1] == str(directory / "server/session-api-key")
    assert command[command.index("--state-dir") + 1] == str(directory / "canvas")
    assert "--open" in command


def test_ui_missing_launcher_has_install_guidance(tmp_path, capsys):
    install, state, worktrees = _installation(tmp_path)
    assert factory.main(["ui", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state), "--worktree-root", str(worktrees)]) == 1
    error = capsys.readouterr().err
    assert "#6602" in error and "<install-root>/bin/openhands_canvas.py" in error


def test_ui_surfaces_only_known_safe_launcher_diagnostic(tmp_path, monkeypatch, capsys):
    install, state_root, worktrees = _installation(tmp_path)
    launcher = install / "bin/openhands_canvas.py"
    launcher.parent.mkdir()
    launcher.write_text("# installed launcher\n")
    directory = state_root / "issue-123"
    directory.mkdir(mode=0o700)
    service._write(directory, {"version": 1, "kind": "openhands_delivery_run.v1", "issue": 123})
    diagnostic = ["Canvas: Canvas loopback port is unavailable\n"]
    monkeypatch.setattr(factory.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, "", diagnostic[0]))
    args = ["ui", "--ui-action", "status", "--issue", "123", "--install-root", str(install),
            "--state-root", str(state_root), "--worktree-root", str(worktrees)]
    assert factory.main(args) == 1
    assert "Canvas: Canvas loopback port is unavailable" in capsys.readouterr().err
    diagnostic[0] = "Canvas: private-key-content\n"
    assert factory.main(args) == 1
    error = capsys.readouterr().err
    assert "Canvas launcher failed" in error and "private-key-content" not in error


def test_ui_stop_uses_canvas_state_without_stopping_backend(tmp_path, monkeypatch, capsys):
    install, state_root, worktrees = _installation(tmp_path)
    launcher = install / "bin/openhands_canvas.py"
    launcher.parent.mkdir()
    launcher.write_text("# installed launcher\n")
    directory = state_root / "issue-123"
    directory.mkdir(mode=0o700)
    service._write(directory, {"version": 1, "kind": "openhands_delivery_run.v1", "issue": 123})
    monkeypatch.setattr(service, "status", lambda *a: pytest.fail("backend must not be stopped or inspected"))
    calls = []
    monkeypatch.setattr(factory.subprocess, "run", lambda command, **kwargs: (
        calls.append(command) or subprocess.CompletedProcess(command, 0, "stopped\n", "")
    ))
    assert factory.main(["ui", "--ui-action", "stop", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)]) == 0
    assert json.loads(capsys.readouterr().out)["ui"]["status"] == "stopped"
    assert calls[0] == [str(install / "venv/bin/python"), str(launcher), "stop",
                        "--state-dir", str(directory / "canvas")]


@pytest.mark.parametrize("conversation,phase", [("finished", "active"), ("paused", "interrupted")])
def test_stop_preserves_session_and_stops_recorded_services(tmp_path, monkeypatch, capsys, conversation, phase):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, saved, thread_id = _recorded_run(
        install, state_root, worktrees, conversation=conversation
    )
    (directory / "canvas").mkdir()
    (directory / "canvas/server.json").write_text("recorded")
    (directory / "session-data").write_text("retained")
    monkeypatch.setattr(service, "status", lambda path: {
        "status": "running", "state": server,
    })
    monkeypatch.setattr(delivery, "_conversation", lambda *args: saved)
    events = []
    monkeypatch.setattr(factory, "_ui", lambda *args: events.append("canvas") or {"ui": {"status": "stopped"}})
    monkeypatch.setattr(service, "stop", lambda path: events.append("backend"))
    assert factory.main(["stop", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert events == ["canvas", "backend"]
    assert result["conversation_status"] == conversation and "unverified" in result["note"]
    assert thread_id not in json.dumps(result)
    assert service._settings(directory / "recovery-settings.json")["resume_thread_id"] == thread_id
    assert os.stat(directory / "recovery-settings.json").st_mode & 0o777 == 0o600
    assert (directory / "session-data").read_text() == "retained"
    assert service._read(directory)["factory_shutdown"]["state"] == "stopped"


def test_stop_refuses_running_conversation_before_stopping_services(tmp_path, monkeypatch, capsys):
    install, state_root, worktrees = _installation(tmp_path)
    directory = state_root / "issue-123"
    directory.mkdir(mode=0o700)
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "issue": 123,
             "phase": "active", "port": 8765, "worktree": str(worktrees / "issue-123-openhands")}
    service._write(directory, state)
    monkeypatch.setattr(service, "status", lambda path: {
        "status": "running", "state": {"port": 8765, "workspace": state["worktree"]},
    })
    monkeypatch.setattr(delivery, "_conversation", lambda *args: {"execution_status": "running"})
    monkeypatch.setattr(service, "stop", lambda *args: pytest.fail("stopped a running conversation"))
    assert factory.main(["stop", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)]) == 1
    assert "not finished or confirmed interrupted" in capsys.readouterr().err
    assert "factory_shutdown" not in service._read(directory)


@pytest.mark.parametrize("conversation", ["paused", "finished"])
def test_start_restores_same_stopped_session_without_starting_a_turn(tmp_path, monkeypatch, capsys, conversation):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, saved, thread_id = _recorded_run(install, state_root, worktrees, conversation=conversation)
    status = {"value": "running"}
    monkeypatch.setattr(service, "status", lambda path: {"status": status["value"], "state": server})
    monkeypatch.setattr(delivery, "_conversation", lambda *args: saved)
    monkeypatch.setattr(service, "stop", lambda path: status.update(value="stopped"))
    assert factory._stop(install, directory, 123)["conversation_status"] == conversation
    calls = []

    def start(path, python, workspace, port, settings_path):
        calls.append((path, python, workspace, port))
        assert service._settings(settings_path)["resume_thread_id"] == thread_id
        server["settings_file"] = str(settings_path)
        status["value"] = "running"
        return {"status": "running"}

    monkeypatch.setattr(service, "start", start)
    monkeypatch.setattr(delivery, "start", lambda *args: pytest.fail("created a new delivery"))
    monkeypatch.setattr(factory, "_refresh_base", lambda *args: pytest.fail("contacted remote"))
    monkeypatch.setattr(delivery, "_http", lambda *args, **kwargs: pytest.fail("sent a conversation request"))
    assert factory.main(["start", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["backend_status"] == "running" and result["conversation_status"] == conversation
    assert "no agent turn was resumed" in result["note"]
    assert thread_id not in output and "K" * 43 not in output
    assert calls == [(directory / "server", install / "venv/bin/python", Path(state["worktree"]), 8765)]
    assert (directory / "server/session-api-key").read_text().strip() == "K" * 43


def test_restart_refuses_changed_session_key_before_launch(tmp_path, monkeypatch):
    install, state_root, worktrees = _installation(tmp_path)
    directory, _, server, saved, _ = _recorded_run(install, state_root, worktrees)
    status = {"value": "running"}
    monkeypatch.setattr(service, "status", lambda path: {"status": status["value"], "state": server})
    monkeypatch.setattr(delivery, "_conversation", lambda *args: saved)
    monkeypatch.setattr(service, "stop", lambda path: status.update(value="stopped"))
    factory._stop(install, directory, 123)
    (directory / "server/session-api-key").write_text("Z" * 43 + "\n")
    monkeypatch.setattr(service, "start", lambda *args: pytest.fail("started with changed key"))
    with pytest.raises(delivery.DeliveryError, match="session key changed"):
        factory._restart(install, directory, 123, factory.FACTORY_ROOT, worktrees)


def test_stop_refuses_mismatched_acp_session_before_stopping(tmp_path, monkeypatch):
    install, state_root, worktrees = _installation(tmp_path)
    directory, _, server, saved, _ = _recorded_run(install, state_root, worktrees)
    monkeypatch.setattr(service, "status", lambda path: {"status": "running", "state": server})
    live = dict(saved, agent_state={**saved["agent_state"], "acp_session_id": str(uuid.uuid4())})
    monkeypatch.setattr(delivery, "_conversation", lambda *args: live)
    monkeypatch.setattr(service, "stop", lambda *args: pytest.fail("stopped without an authorized session"))
    with pytest.raises(delivery.DeliveryError, match="session identities do not match"):
        factory._stop(install, directory, 123)


def test_restart_reconciles_running_backend_without_spawning_again(tmp_path, monkeypatch):
    install, state_root, worktrees = _installation(tmp_path)
    directory, _, server, saved, _ = _recorded_run(install, state_root, worktrees)
    status = {"value": "running"}
    monkeypatch.setattr(service, "status", lambda path: {"status": status["value"], "state": server})
    monkeypatch.setattr(delivery, "_conversation", lambda *args: saved)
    monkeypatch.setattr(service, "stop", lambda path: status.update(value="stopped"))
    factory._stop(install, directory, 123)
    state = service._read(directory)
    state["factory_shutdown"]["state"] = "starting"
    service._write(directory, state)
    status["value"] = "running"
    server["settings_file"] = str(directory / "recovery-settings.json")
    monkeypatch.setattr(service, "start", lambda *args: pytest.fail("duplicated running backend"))
    assert factory._restart(install, directory, 123, factory.FACTORY_ROOT, worktrees)["backend_status"] == "running"


def test_older_stopped_run_recovers_from_persisted_session(tmp_path, monkeypatch):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, saved, thread_id = _recorded_run(install, state_root, worktrees)
    state["factory_shutdown"] = {"state": "stopped", "conversation_status": "finished"}
    service._write(directory, state)
    status = {"value": "stopped"}
    monkeypatch.setattr(service, "status", lambda path: {"status": status["value"], "state": server})
    monkeypatch.setattr(delivery, "_conversation", lambda *args: saved)

    def start(path, python, workspace, port, settings):
        assert service._settings(settings)["resume_thread_id"] == thread_id
        status["value"] = "running"

    monkeypatch.setattr(service, "start", start)
    assert factory._restart(install, directory, 123, factory.FACTORY_ROOT, worktrees)["backend_status"] == "running"


def test_verify_records_real_results_and_unresolved_issue_targets(tmp_path, monkeypatch, capsys):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, _, _ = _recorded_run(install, state_root, worktrees)
    worktree = Path(state["worktree"])
    (worktree / "tests").mkdir()
    (worktree / "tests/test_feature.py").write_text("# candidate tests\n")
    body = ("## Acceptance Criteria\n"
            "- [ ] First behavior.\n  - Verify: `tests/test_feature.py::test_ok`\n"
            "- [ ] Second behavior.\n  - Verify: `tests/test_feature.py::test_bad`\n"
            "- [ ] Third behavior.\n  - Verify: `tests/test_feature.py::test_skipped`\n"
            "- [ ] Review a document.\n  - Verify: `docs/owner.md :: Review`\n")
    state.update(branch="codex/issue-123-openhands", issue_body_sha256=delivery._sha(body))
    service._write(directory, state)
    settings_path = directory / "settings.json"
    settings = json.loads(settings_path.read_text())
    settings["codex_config_args"] = ["-c", 'permissions.builder_factory.filesystem={":minimal"="read"}']
    settings_path.write_text(json.dumps(settings))
    monkeypatch.setattr(delivery, "_finished_run", lambda path: state)
    monkeypatch.setattr(factory, "_candidate_head", lambda path, branch: "a" * 40)
    monkeypatch.setattr(service, "status", lambda path: {"status": "running", "state": server})
    monkeypatch.setattr(delivery, "_json_result", lambda command: {
        "number": 123, "state": "OPEN", "body": body,
        "url": f"https://github.com/{delivery.REPOSITORY}/issues/123",
    })
    calls = []

    def run(command, cwd, temp, log):
        calls.append(command)
        is_pass = command[-1].endswith("test_ok")
        is_skipped = command[-1].endswith("test_skipped")
        log.write_text("test output\n1 passed in 0.1s\n" if is_pass else
                       "1 passed, 1 skipped in 0.1s\n" if is_skipped else "1 failed in 0.1s\n")
        return 0 if is_pass or is_skipped else 1

    monkeypatch.setattr(factory, "_run_verify_command", run)
    assert factory.main(["verify", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed" and output["head_sha"] == "a" * 40
    assert output["verification"][0]["target"] == "tests/test_feature.py::test_ok"
    assert output["verification"][0]["exit_code"] == 0
    assert output["failed"][0]["exit_code"] == 1
    assert {item["target"] for item in output["unresolved"]} == {
        "tests/test_feature.py::test_skipped", "`docs/owner.md :: Review`",
    }
    assert len(calls) == 3 and all(command[1] == "sandbox" for command in calls)
    assert all("builder_factory" in command and command[-1].startswith("tests/") for command in calls)
    evidence = output["verification"][0]["evidence"]
    assert delivery._sha(Path(evidence["path"]).read_text()) == evidence["sha256"]
    assert json.loads(Path(output["evidence_file"]).read_text())["verification"] == output["verification"]
    assert "test output" not in json.dumps(output)
    heads = iter(("a" * 40, "b" * 40))
    monkeypatch.setattr(factory, "_candidate_head", lambda path, branch: next(heads))
    calls.clear()
    assert factory.main(["verify", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)]) == 1
    drifted = json.loads(capsys.readouterr().out)
    assert drifted["status"] == "unresolved" and not drifted["verification"]
    assert len(calls) == 1 and len(drifted["unresolved"]) == 4


def test_verification_runner_captures_exit_and_drops_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-inherited")
    log = tmp_path / "result.log"
    command = [__import__("sys").executable, "-c",
               "import os,stat,sys; "
               "sys.exit(120) if stat.S_ISREG(os.fstat(1).st_mode) else None; "
               "os.write(1, b'x' * 200000); "
               "print('present' if 'OPENAI_API_KEY' in os.environ else 'absent'); "
               "print('stderr captured', file=sys.stderr)"]
    with (tmp_path / "direct.log").open("wb") as direct:
        assert subprocess.run(command, stdout=direct, stderr=subprocess.STDOUT, check=False).returncode == 120
    assert factory._run_verify_command(command, tmp_path, tmp_path, log) == 0
    contents = log.read_text()
    assert "x" * 200000 in contents and "absent" in contents and "stderr captured" in contents
    assert os.stat(log).st_mode & 0o777 == 0o600
    empty_log = tmp_path / "empty.log"
    assert factory._run_verify_command([command[0], "-c", "raise SystemExit(120)"],
                                       tmp_path, tmp_path, empty_log) == 120
    assert "exited 120 without output" in empty_log.read_text()


def test_verification_refuses_a_dirty_candidate(tmp_path, monkeypatch):
    def run(command):
        if "--show-toplevel" in command:
            output = str(tmp_path)
        elif "--show-current" in command:
            output = "branch"
        elif "--porcelain=v1" in command:
            output = " M feature.py\0"
        else:
            output = "a" * 40
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(delivery, "_run", run)
    with pytest.raises(delivery.DeliveryError, match="clean committed worktree"):
        factory._candidate_head(tmp_path, "branch")


@pytest.mark.parametrize("review_outcome", ["pass", "refused", "drift"])
def test_owner_review_records_independent_candidate_evidence(tmp_path, monkeypatch, capsys, review_outcome):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, saved, worker_thread = _recorded_run(install, state_root, worktrees)
    worktree = Path(state["worktree"])
    (worktree / "AGENTS.md").write_text("Review repository instructions.\n")
    body = "## Acceptance Criteria\n- [ ] Deliver feature.\n  - Verify: `tests/test_feature.py::test_ok`\n"
    state.update(branch="codex/issue-123-openhands", issue_body_sha256=delivery._sha(body))
    service._write(directory, state)
    head, base = "a" * 40, "b" * 40
    heads = iter((head, "c" * 40 if review_outcome == "drift" else head))
    monkeypatch.setattr(factory, "_candidate_head", lambda path, branch: next(heads))
    monkeypatch.setattr(delivery, "_finished_run", lambda path: state)
    monkeypatch.setattr(delivery, "_conversation", lambda *args: saved)
    monkeypatch.setattr(service, "status", lambda path: {"status": "running", "state": server})
    monkeypatch.setattr(delivery, "_json_result", lambda command: {
        "number": 123, "state": "OPEN", "body": body,
        "url": f"https://github.com/{delivery.REPOSITORY}/issues/123",
    })

    def git(command, **kwargs):
        output = base if "rev-parse" in command else "diff --git a/feature b/feature\n+change\n" if "diff" in command else ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(delivery, "_run", git)
    captured = {}

    def perform(python, settings, workspace, candidate, prompt, worker):
        captured.update(candidate=candidate, prompt=prompt, worker=worker, workspace=workspace)
        if review_outcome == "refused":
            raise factory.review.ReviewError("Reviewer request was refused or failed")
        result = {"head_sha": head, "verdict": "pass", "summary": "Reviewed candidate diff", "findings": []}
        return result, json.dumps(result), "independent-thread-id"

    monkeypatch.setattr(factory.review, "run_review", perform)
    code = factory.main(["review", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)])
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == ("pass" if review_outcome == "pass" else "unresolved")
    assert code == (0 if review_outcome == "pass" else 1)
    assert captured["worker"] == worker_thread and captured["candidate"] == head
    assert body in captured["prompt"] and "diff --git" in captured["prompt"]
    assert worker_thread not in json.dumps(output) and "independent-thread-id" not in json.dumps(output)
    assert os.stat(output["evidence_file"]).st_mode & 0o777 == 0o600
    if review_outcome != "refused":
        entry = output["review"]
        assert entry["reviewer"].startswith("native-codex-gpt-6.1-terra-")
        assert entry["head_sha"] == head and entry["verdict"] == output["status"]
        assert head in Path(entry["evidence"]["path"]).read_text()
        if review_outcome == "pass":
            test_log = directory / "verification.log"
            test_log.write_text("1 passed in 0.1s\n")
            publication_evidence = {"version": 1, "repository": delivery.REPOSITORY, "issue": 123,
                                    "head_sha": head, "base_sha": base, "risk_surfaces": ["auth"],
                                    "review": entry,
                                    "verification": [{"target": "tests/test_feature.py::test_ok",
                                                      "head_sha": head, "result": "pass",
                                                      "evidence": {"path": str(test_log)}}]}
            receipt = directory / "publication-evidence.json"
            receipt.write_text(json.dumps(publication_evidence))
            assert delivery._full_evidence(receipt, state, head, base, body)[0]["review"] == entry
    else:
        assert output["review"] is None


def test_inherited_tools_are_disabled_by_name_without_copying_values(tmp_path, monkeypatch):
    install, state, worktrees = _installation(tmp_path)
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex/config.toml").write_text(
        '[mcp_servers."service.with.dot"]\ncommand = "private-credential-value"\n'
        '[plugins."test@catalog"]\nenabled = true\n'
        '[profiles.alternate.plugins."profile@catalog"]\nenabled = true\n'
    )
    (worktrees / ".codex").mkdir()
    (worktrees / ".codex/config.toml").write_text('[mcp_servers.parent]\nurl = "private-url"\n')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(factory, "_base_config", lambda repo: b'[plugins."project@catalog"]\nenabled=true\n')
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, factory.CODEX_VERSION if a[0][-1] == "--version" else str(tmp_path), ""))
    executable = Path(__import__("sys").executable)
    settings = factory._settings(install, state / "issue-123", executable, executable,
                                 tmp_path, worktrees / "issue-123-openhands")
    assert str(install / "canvas") not in settings["sandbox_read_roots"]
    args = settings["codex_config_args"]
    overrides = args[1::2]
    assert [item for item in overrides if item.startswith("mcp_servers")] == [
        'mcp_servers={"parent"={enabled=false},"service.with.dot"={enabled=false}}',
    ]
    assert [item for item in overrides if item.startswith("plugins")] == [
        'plugins={"profile@catalog"={enabled=false},"project@catalog"={enabled=false},'
        '"test@catalog"={enabled=false}}',
    ]
    config = tomllib.loads("\n".join(args[1::2]))
    assert config["mcp_servers"] == {
        "service.with.dot": {"enabled": False}, "parent": {"enabled": False},
    }
    assert config["plugins"] == {
        "test@catalog": {"enabled": False}, "profile@catalog": {"enabled": False},
        "project@catalog": {"enabled": False},
    }
    assert "private-credential-value" not in json.dumps(settings)
    assert "private-url" not in json.dumps(settings)


def test_invalid_inherited_config_refuses_without_exposing_contents(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex/config.toml").write_text('credential = "secret-value"\n[broken\n')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(factory, "_base_config", lambda repo: None)
    with pytest.raises(delivery.DeliveryError, match="Cannot safely parse") as error:
        factory._tool_names(tmp_path, tmp_path / "worktree")
    assert "secret-value" not in str(error.value)


def test_project_config_comes_from_the_worktree_base(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        output = b"100644 blob hash\t.codex/config.toml\0" if "ls-tree" in command else b"[plugins]\n"
        return subprocess.CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(factory.subprocess, "run", run)
    assert factory._base_config(tmp_path) == b"[plugins]\n"
    assert "refs/remotes/origin/main" in calls[0]
    assert calls[1][-1] == "refs/remotes/origin/main:.codex/config.toml"


def test_refresh_verifies_live_default_branch_and_refuses_drift(tmp_path, monkeypatch):
    local_sha = ["a" * 40]
    fetched_sha = ["b" * 40]
    remote_sha = [fetched_sha[0]]
    ancestor_status = [0]
    calls = []
    monkeypatch.setattr(delivery, "_repository", lambda repo: (repo, local_sha[0]))

    def run(command, **kwargs):
        calls.append(command)
        if "ls-remote" in command:
            output = f"ref: refs/heads/main\tHEAD\n{remote_sha[0]}\tHEAD\n"
        elif "rev-parse" in command:
            output = fetched_sha[0]
        else:
            output = ""
        if "update-ref" in command:
            assert command[-1] == local_sha[0]
            local_sha[0] = command[-2]
        code = ancestor_status[0] if "merge-base" in command else 0
        return subprocess.CompletedProcess(command, code, output, "")

    monkeypatch.setattr(factory.subprocess, "run", run)
    assert factory._refresh_base(tmp_path) == fetched_sha[0]
    assert "fetch" in calls[0] and "--refmap=" in calls[0] and "refs/heads/main" in calls[0]
    assert not any(part.startswith("+") for part in calls[0])
    assert any("ls-remote" in call and "--symref" in call for call in calls)
    remote_sha[0] = "c" * 40
    with pytest.raises(delivery.DeliveryError, match="differs from the live default branch"):
        factory._refresh_base(tmp_path)
    fetched_sha[0] = remote_sha[0]
    ancestor_status[0] = 1
    before = sum("update-ref" in call for call in calls)
    with pytest.raises(delivery.DeliveryError, match="diverged"):
        factory._refresh_base(tmp_path)
    assert sum("update-ref" in call for call in calls) == before
    assert local_sha[0] == "b" * 40


def test_failed_refresh_stops_before_preparing_delivery(tmp_path, monkeypatch, capsys):
    install, state, worktrees = _installation(tmp_path)
    monkeypatch.setattr(delivery, "_repository", lambda repo: (repo, "a" * 40))
    monkeypatch.setattr(factory.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, "", "private network detail"))
    monkeypatch.setattr(factory, "_settings", lambda *args: pytest.fail("configured after failed fetch"))
    monkeypatch.setattr(delivery, "start", lambda *args: pytest.fail("started after failed fetch"))
    assert factory.main(["start", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state), "--worktree-root", str(worktrees)]) == 1
    error = capsys.readouterr().err
    assert "Cannot refresh origin/main" in error
    assert "private network detail" not in error
    assert service._read(state / "issue-123") is None
