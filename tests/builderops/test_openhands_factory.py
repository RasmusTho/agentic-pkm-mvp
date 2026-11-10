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


@pytest.mark.parametrize("watch_status,phase,conversation,allowed", [
    ("running", "watching", "running", False),
    ("pending", "ci_wait", "finished", False),
    ("finished", "published", "finished", False),
    ("finished", "published", "running", False),
    ("finished", "published", None, False),
    ("not_started", None, "finished", False),
    ("not_started", None, "running", False),
])
def test_serial_admission_requires_prior_delivery_to_be_terminal(
    tmp_path, monkeypatch, watch_status, phase, conversation, allowed
):
    from app.builderops import openhands_watcher as watcher

    prior = tmp_path / "issue-41"
    prior.mkdir()
    monkeypatch.setattr(delivery, "status", lambda path: {
        "state": {"full_publication": {"state": "draft_published", "pr_number": 42}},
        "conversation_status": conversation, "service_status": "running",
    })
    monkeypatch.setattr(watcher, "status", lambda path: {"status": watch_status, "phase": phase})
    if allowed:
        factory._check_serial_admission(tmp_path, 43)
    else:
        with pytest.raises(delivery.DeliveryError, match="active or unresolved"):
            factory._check_serial_admission(tmp_path, 43)


def test_serial_admission_ignores_a_confirmed_pre_state_refusal(tmp_path):
    prior = tmp_path / "issue-41"
    prior.mkdir()
    (prior / "service.lock").touch()
    factory._check_serial_admission(tmp_path, 43)


def test_serial_admission_accepts_a_verified_stopped_legacy_session(tmp_path, monkeypatch):
    from app.builderops import openhands_watcher as watcher

    prior = tmp_path / "issue-41"
    prior.mkdir()
    settings = prior / "settings.json"
    worktree = str(tmp_path / "worktree")
    state = {"worktree": worktree, "full_publication": {"state": "draft_published", "pr_number": 42}}
    monkeypatch.setattr(delivery, "status", lambda path: {"state": state, "service_status": "stopped"})
    monkeypatch.setattr(watcher, "status", lambda path: {"status": "not_started"})
    monkeypatch.setattr(service, "status", lambda path: {"state": {"settings_file": str(settings),
                                                                   "workspace": worktree}})
    monkeypatch.setattr(service, "_settings", lambda path: {})
    verified = []
    monkeypatch.setattr(factory, "_persisted_session", lambda config, observed, expected:
                        verified.append((observed, expected)) or "thread")
    factory._check_serial_admission(tmp_path, 43)
    assert verified == [(state, "finished")]


def test_published_worker_cannot_restart(tmp_path):
    directory = tmp_path / "issue-41"
    directory.mkdir(mode=0o700)
    service._write(directory, {"version": 1, "kind": "openhands_delivery_run.v1",
                               "full_publication": {"state": "draft_published"}})
    with pytest.raises(delivery.DeliveryError, match="Published worker sessions cannot be restarted"):
        factory._restart(tmp_path, directory, 41, tmp_path, tmp_path)


def test_owner_recovers_pre_state_settings_without_external_effects(tmp_path, monkeypatch):
    from app.builderops import openhands_owner

    root = tmp_path / "runs"
    root.mkdir(mode=0o700)
    directory = root / "owner"
    directory.mkdir(mode=0o700)
    (directory / "settings.json").write_text('{"incomplete": true}')
    monkeypatch.setattr(factory, "_executable", lambda name: Path("/executable"))
    monkeypatch.setattr(factory, "_settings", lambda *args: {"fixed": "settings"})
    monkeypatch.setattr(service, "status", lambda path: {"status": "stopped"})
    starts = []
    monkeypatch.setattr(service, "start", lambda *args, **kwargs: starts.append((args, kwargs)))
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "private")
    monkeypatch.setattr(delivery, "_http", lambda *args: (200, {}))
    monkeypatch.setattr(openhands_owner, "ensure_profile", lambda *args: None)
    monkeypatch.setattr(openhands_owner, "attach", lambda *args: {"conversation_id": "control"})
    monkeypatch.setattr(factory, "_canvas", lambda *args: {"ui": {"url": "http://127.0.0.1:3001"}})
    result = factory._owner_service(tmp_path, root, tmp_path, "start", 8766, 3001, False)
    assert json.loads((directory / "settings.json").read_text()) == {"fixed": "settings"}
    assert service._read(directory)["kind"] == "openhands_owner_service.v1"
    assert len(starts) == 1 and starts[0][1]["control_only"] is True
    assert result["conversation_id"] == "control"


@pytest.mark.parametrize("ui_port", [None, 8124])
def test_legacy_control_uses_existing_owner_without_touching_worker_record(tmp_path, monkeypatch, capsys, ui_port):
    install, runs, worktrees, repo = (tmp_path / name for name in ("install", "runs", "worktrees", "repo"))
    for path in (install, runs, worktrees, repo):
        path.mkdir()
    owner = runs / "owner"
    owner.mkdir(mode=0o700)
    service._write(owner, {"version": 1, "kind": "openhands_owner_service.v1", "ui_port": 8124})
    old_control = runs / "issue-123" / "owner-control"
    old_control.mkdir(parents=True)
    (old_control / "service.json").write_text('{"version": 1, "phase": "creating"}')
    calls = []
    monkeypatch.setattr(factory, "_owner_service", lambda *args: calls.append(args) or {"url": "owner-url"})
    args = ["control", "--issue", "123", "--install-root", str(install),
            "--state-root", str(runs), "--worktree-root", str(worktrees), "--repo-root", str(repo)]
    if ui_port is not None:
        args += ["--ui-port", str(ui_port)]
    result = factory.main(args)
    assert result == 0
    assert calls == [(install, runs, repo, "start", None, None, False)]
    assert "owner-url" in capsys.readouterr().out
    assert json.loads((old_control / "service.json").read_text()) == {"version": 1, "phase": "creating"}


def test_legacy_control_without_owner_fails_before_touching_worker(tmp_path, monkeypatch, capsys):
    install, runs, worktrees, repo = (tmp_path / name for name in ("install", "runs", "worktrees", "repo"))
    for path in (install, runs, worktrees, repo):
        path.mkdir()
    monkeypatch.setattr(factory, "_owner_service", lambda *args: pytest.fail("started missing owner"))
    assert factory.main(["control", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(runs), "--worktree-root", str(worktrees),
                         "--repo-root", str(repo)]) != 0
    assert "retired" in capsys.readouterr().err
    assert not (runs / "issue-123").exists()


def test_legacy_control_rejects_a_different_owner_port(tmp_path, monkeypatch, capsys):
    install, runs, worktrees, repo = (tmp_path / name for name in ("install", "runs", "worktrees", "repo"))
    for path in (install, runs, worktrees, repo):
        path.mkdir()
    owner = runs / "owner"
    owner.mkdir(mode=0o700)
    service._write(owner, {"version": 1, "kind": "openhands_owner_service.v1", "ui_port": 8124})
    monkeypatch.setattr(factory, "_owner_service", lambda *args: pytest.fail("changed owner port"))
    assert factory.main(["control", "--issue", "123", "--ui-port", "8125", "--install-root", str(install),
                         "--state-root", str(runs), "--worktree-root", str(worktrees),
                         "--repo-root", str(repo)]) != 0
    assert "recorded owner UI port" in capsys.readouterr().err
    assert service._read(owner)["ui_port"] == 8124


def test_status_reads_checks_for_manually_published_draft_without_watcher(tmp_path, monkeypatch, capsys):
    from app.builderops import openhands_watcher

    install, runs, worktrees, repo = (tmp_path / name for name in ("install", "runs", "worktrees", "repo"))
    for path in (install, runs, worktrees, repo):
        path.mkdir()
    state = {"full_publication": {"pr_number": 77}}
    monkeypatch.setattr(delivery, "status", lambda directory: {"state": state})
    monkeypatch.setattr(openhands_watcher, "status", lambda directory: {"status": "not_started"})
    monkeypatch.setattr(openhands_watcher, "fresh_ci_status", lambda *args: {"status": "pending"})
    monkeypatch.setattr(factory, "_ui_route", lambda *args: {})
    assert factory.main(["status", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(runs), "--worktree-root", str(worktrees),
                         "--repo-root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)["live_ci"] == {"status": "pending"}


@pytest.mark.parametrize("port,ui_port", [(0, 3001), (65536, 3001), (8766, 8766)])
def test_owner_invalid_ports_leave_no_persisted_state(tmp_path, monkeypatch, port, ui_port):
    root = tmp_path / "runs"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(factory, "_settings", lambda *args: pytest.fail("configured invalid ports"))
    with pytest.raises(delivery.DeliveryError, match="valid and distinct"):
        factory._owner_service(tmp_path, root, tmp_path, "start", port, ui_port, False)
    assert service._read(root / "owner") is None


def test_worker_stop_reconciles_process_lost_after_signal(tmp_path, monkeypatch):
    directory = tmp_path / "issue-123"
    server = directory / "server"
    server.mkdir(mode=0o700, parents=True)
    directory.chmod(0o700)
    worktree = str(tmp_path / "worktree")
    service._write(directory, {"version": 1, "kind": "openhands_delivery_run.v1", "issue": 123,
                               "port": 8123, "worktree": worktree,
                               "factory_shutdown": {"state": "stopping", "conversation_status": "finished"}})
    service._write(server, {"version": 1, "state": "stopping", "pid": 123, "marker": "unique",
                            "started": "old", "port": 8123, "workspace": worktree})
    monkeypatch.setattr(service, "_identity", lambda pid: None)
    monkeypatch.setattr(service.os, "kill", lambda *args: pytest.fail("must not signal a missing process"))
    result = factory._stop(tmp_path, directory, 123)
    assert result["backend_status"] == "stopped"
    assert service._read(server)["state"] == "stopped"
    assert service._read(directory)["factory_shutdown"]["state"] == "stopped"


def test_owner_stop_reconciles_interrupted_backend_shutdown(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    directory = root / "owner"
    server = directory / "server"
    server.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    directory.chmod(0o700)
    workspace = str(directory / "workspace")
    service._write(directory, {"version": 1, "kind": "openhands_owner_service.v1", "worktree": workspace,
                               "port": 8123, "ui_port": 3001})
    service._write(server, {"version": 1, "state": "stopping", "pid": 123, "marker": "unique",
                            "started": "old", "port": 8123, "workspace": workspace, "control_only": True,
                            "python": str(tmp_path / "venv/bin/python"),
                            "settings_file": str(directory / "settings.json")})
    monkeypatch.setattr(service, "_identity", lambda pid: None)
    monkeypatch.setattr(service.os, "kill", lambda *args: pytest.fail("must not signal a missing process"))
    monkeypatch.setattr(factory, "_canvas", lambda *args: {"ui": {"status": "stopped"}})
    assert factory._owner_service(tmp_path, root, tmp_path, "stop", None, None, False)["status"] == "stopped"
    assert service._read(server)["state"] == "stopped"


def test_owner_restart_reuses_recorded_ports(tmp_path, monkeypatch):
    from app.builderops import openhands_owner

    root = tmp_path / "runs"
    directory = root / "owner"
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    directory.chmod(0o700)
    service._write(directory, {"version": 1, "kind": "openhands_owner_service.v1", "worktree": str(workspace),
                               "port": 8123, "ui_port": 8124})
    monkeypatch.setattr(service, "status", lambda *args: {"status": "stopped"})
    starts = []
    monkeypatch.setattr(service, "start", lambda *args, **kwargs: starts.append(args))
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "private")
    monkeypatch.setattr(delivery, "_http", lambda *args: (200, {}))
    monkeypatch.setattr(openhands_owner, "ensure_profile", lambda *args: None)
    monkeypatch.setattr(openhands_owner, "attach", lambda *args: {"conversation_id": "control"})
    canvas_ports = []
    monkeypatch.setattr(factory, "_canvas", lambda install, directory, state, action, port, opened:
                        canvas_ports.append(port) or {"ui": {"url": "http://127.0.0.1:8124"}})
    factory._owner_service(tmp_path, root, tmp_path, "start", None, None, False)
    assert starts[0][3] == 8123 and canvas_ports == [8124]


def test_owner_rejects_colliding_canvas_port_without_changing_saved_state(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    directory = root / "owner"
    directory.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    original = {"version": 1, "kind": "openhands_owner_service.v1", "worktree": str(directory / "workspace"),
                "port": 8123, "ui_port": 8124}
    service._write(directory, original)
    monkeypatch.setattr(service, "start", lambda *args, **kwargs: pytest.fail("started on invalid ports"))
    with pytest.raises(delivery.DeliveryError, match="valid and distinct"):
        factory._owner_service(tmp_path, root, tmp_path, "start", None, 8123, False)
    assert service._read(directory) == original


def test_failed_owner_canvas_port_change_preserves_existing_port(tmp_path, monkeypatch):
    from app.builderops import openhands_owner

    root = tmp_path / "runs"
    directory = root / "owner"
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    directory.chmod(0o700)
    original = {"version": 1, "kind": "openhands_owner_service.v1", "worktree": str(workspace),
                "port": 8123, "ui_port": 8124}
    service._write(directory, original)
    monkeypatch.setattr(service, "status", lambda *args: {"status": "stopped"})
    monkeypatch.setattr(service, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "private")
    monkeypatch.setattr(delivery, "_http", lambda *args: (200, {}))
    monkeypatch.setattr(openhands_owner, "ensure_profile", lambda *args: None)
    monkeypatch.setattr(openhands_owner, "attach", lambda *args: {"conversation_id": "control"})
    def fail_canvas(*args):
        raise delivery.DeliveryError("Canvas already running on another port")
    monkeypatch.setattr(factory, "_canvas", fail_canvas)
    with pytest.raises(delivery.DeliveryError, match="another port"):
        factory._owner_service(tmp_path, root, tmp_path, "start", None, 8125, False)
    assert service._read(directory) == original


def test_owner_can_inspect_and_stop_a_previously_colliding_port(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    directory = root / "owner"
    directory.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    service._write(directory, {"version": 1, "kind": "openhands_owner_service.v1",
                               "worktree": str(directory / "workspace"), "port": 8123, "ui_port": 8123})
    monkeypatch.setattr(service, "status", lambda *args: {"status": "stopped"})
    monkeypatch.setattr(factory, "_canvas", lambda *args: {"ui": {"status": "stopped", "url": None}})
    assert factory._owner_service(tmp_path, root, tmp_path, "status", None, None, False)["status"] == "stopped"
    assert factory._owner_service(tmp_path, root, tmp_path, "stop", None, None, False)["status"] == "stopped"


def test_owner_start_builds_real_settings_and_routes_to_delivery(tmp_path, monkeypatch, capsys):
    from app.builderops import openhands_watcher as watcher

    install, state, worktrees = _installation(tmp_path)
    monkeypatch.setattr(factory, "_test_environment_for_base", lambda *args: (install / "venv/bin/python", "a" * 64))
    (install / "canvas").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(factory, "_base_config", lambda repo: None)
    library_root = tmp_path / "linked-libraries"
    library_root.mkdir()
    monkeypatch.setattr(factory, "_python_library_roots", lambda *args: [str(library_root)])
    monkeypatch.setattr(factory, "python_binary_roots", lambda *args: [])
    package_root = tmp_path / "brew/Cellar/python@3.12/3.12.12"
    python_root = package_root / "Frameworks/Python.framework/Versions/3.12"
    python_root.mkdir(parents=True)
    opt_root = tmp_path / "brew/opt"
    opt_root.mkdir()
    traversal_roots = factory._python_framework_traversal_roots
    monkeypatch.setattr(factory, "_python_framework_traversal_roots",
                        lambda root: traversal_roots(root, platform="darwin"))
    refreshed = []
    monkeypatch.setattr(factory, "_refresh_base", lambda repo: refreshed.append(repo) or "b" * 40)
    node = Path(__import__("sys").executable)
    monkeypatch.setattr(factory, "_executable", lambda name: node)
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, factory.CODEX_VERSION + "\n" if a[0][-1] == "--version" else str(python_root), ""))
    monkeypatch.setattr(delivery, "_run", lambda command: subprocess.CompletedProcess(
        command, 0, delivery.SERVER_VERSION + "\n", ""))
    captured = {}

    def start(directory, repo, issue, authorized, branch, worktree, python, port, settings, node, acp,
              *, auto_finish, test_python, test_environment_lock_sha256, expected_base):
        assert refreshed == [repo]
        captured.update(directory=directory, repo=repo, issue=issue, authorized=authorized,
                        branch=branch, worktree=worktree, python=python, port=port,
                        settings=delivery._validate_executables(python, node, acp, settings),
                        settings_path=settings, auto_finish=auto_finish, test_python=test_python,
                        test_environment_lock_sha256=test_environment_lock_sha256, expected_base=expected_base)
        return {"state": {"port": port}, "conversation_status": "running"}

    monkeypatch.setattr(delivery, "start", start)
    monkeypatch.setattr(watcher, "launch", lambda *args: captured.update(watcher_started=True))
    assert factory.main(["start", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state), "--worktree-root", str(worktrees)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert captured["issue"] == captured["authorized"] == 123
    assert captured["auto_finish"] is True and captured["watcher_started"] is True
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
    assert profile["filesystem"][str(library_root)] == "read"
    assert profile["filesystem"][str(package_root)] == "read"
    assert profile["filesystem"][str(opt_root)] == "read"
    assert profile["filesystem"] == {
        ":minimal": "read", ":workspace_roots": "write",
        **{root: "read" for root in settings["sandbox_read_roots"]},
    }
    assert settings["conversations_path"] == str(state / "issue-123/conversations")
    verify_command = factory._verification_command(settings, worktrees, tmp_path, captured["python"],
                                                   "tests/test_feature.py::test_ok")
    verify_config = tomllib.loads("\n".join(verify_command[3:verify_command.index("-P"):2]))
    assert verify_config["permissions"]["builder_factory"]["filesystem"][str(library_root)] == "read"
    assert verify_config["permissions"]["builder_factory"]["filesystem"][str(package_root)] == "read"
    assert verify_config["permissions"]["builder_factory"]["filesystem"][str(opt_root)] == "read"
    review_config = tomllib.loads("\n".join(factory.review._read_only_args(settings)[1::2]))
    assert review_config["permissions"]["builder_factory"]["filesystem"][str(library_root)] == "read"
    assert review_config["permissions"]["builder_factory"]["filesystem"][str(package_root)] == "read"
    assert review_config["permissions"]["builder_factory"]["filesystem"][str(opt_root)] == "read"
    assert result["owner_ui"]["agent_server"] == "http://127.0.0.1:8765"
    assert result["owner_ui"]["session_key_file"].endswith("/server/session-api-key")


def test_homebrew_framework_traversal_roots_are_bounded_and_portable(tmp_path):
    prefix = tmp_path / "custom-prefix"
    package = prefix / "Cellar/python@3.12/3.12.12"
    root = package / "Frameworks/Python.framework/Versions/3.12"
    root.mkdir(parents=True)
    opt = prefix / "opt"
    opt.mkdir()
    assert factory._python_framework_traversal_roots(root, platform="darwin") == [str(package), str(opt)]
    assert factory._python_framework_traversal_roots(root, platform="linux") == []
    assert factory._python_framework_traversal_roots(tmp_path / "other/Python.framework/Versions/3.12",
                                                     platform="darwin") == []
    other = tmp_path / "separate/Cellar/python@3.12/3.12.12/Frameworks/Python.framework/Versions/3.12"
    other.mkdir(parents=True)
    assert factory._python_framework_traversal_roots(other, platform="darwin") == [str(other.parent.parent.parent.parent)]
    (tmp_path / "separate/opt").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(delivery.DeliveryError, match="not a directory"):
        factory._python_framework_traversal_roots(other, platform="darwin")


def test_owner_rejects_wrong_codex_version_before_delivery(tmp_path, monkeypatch, capsys):
    install, state, worktrees = _installation(tmp_path)
    monkeypatch.setattr(factory, "_test_environment_for_base", lambda *args: (install / "venv/bin/python", "a" * 64))
    monkeypatch.setattr(factory, "_refresh_base", lambda repo: None)
    monkeypatch.setattr(factory, "_executable", lambda name: Path(__import__("sys").executable))
    monkeypatch.setattr(factory.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, "codex-cli 1.0.0\n", ""))
    monkeypatch.setattr(delivery, "start", lambda *args: (_ for _ in ()).throw(AssertionError()))
    assert factory.main(["start", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state), "--worktree-root", str(worktrees)]) == 1
    assert "Native Codex" in capsys.readouterr().err
    assert service._read(state / "issue-123") is None


def test_occupied_worker_port_is_refused_before_claim(tmp_path, monkeypatch, capsys):
    import socket

    install, state, worktrees = _installation(tmp_path)
    monkeypatch.setattr(factory, "_refresh_base", lambda *args: pytest.fail("refreshed after port refusal"))
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        assert factory.main(["start", "--issue", "123", "--port", str(port), "--install-root", str(install),
                             "--state-root", str(state), "--worktree-root", str(worktrees)]) == 1
    assert "Worker port is unavailable" in capsys.readouterr().err
    assert service._read(state / "issue-123") is None


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_python_library_discovery_limits_access_to_linked_sqlite_and_ssl_dirs(tmp_path, monkeypatch, platform):
    python_root = tmp_path / "python"
    extension_dir = python_root / "lib-dynload"
    extension_dir.mkdir(parents=True)
    sqlite_extension = extension_dir / "_sqlite3.so"
    ssl_extension = extension_dir / "_ssl.so"
    sqlite_extension.touch()
    ssl_extension.touch()
    suffixes = (".dylib", ".3.dylib", ".3.dylib") if platform == "darwin" else (".so.0", ".so.3", ".so.3")
    real_sqlite = tmp_path / "cellar/sqlite/lib"
    real_ssl = tmp_path / "cellar/openssl/lib"
    real_sqlite.mkdir(parents=True)
    real_ssl.mkdir(parents=True)
    names = ["libsqlite3" + suffixes[0], "libssl" + suffixes[1], "libcrypto" + suffixes[2]]
    (real_sqlite / names[0]).touch()
    for name in names[1:]:
        (real_ssl / name).touch()
    alias_sqlite = tmp_path / "opt/sqlite/lib"
    alias_ssl = tmp_path / "opt/openssl/lib"
    alias_sqlite.parent.mkdir(parents=True)
    alias_ssl.parent.mkdir(parents=True)
    alias_sqlite.symlink_to(real_sqlite, target_is_directory=True)
    alias_ssl.symlink_to(real_ssl, target_is_directory=True)
    paths = [alias_sqlite / names[0], alias_ssl / names[1], alias_ssl / names[2]]
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-inherit")
    monkeypatch.setattr(factory.shutil, "which", lambda name: "/usr/bin/" + name)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "-I" in command:
            output = json.dumps({"machine": "arm64", "origins": {
                "_sqlite3": str(sqlite_extension), "_ssl": str(ssl_extension)}})
        else:
            dependencies = paths[:1] if command[-1] == str(sqlite_extension) else paths[1:]
            if platform == "darwin":
                header = command[-1] + (" (architecture arm64):\n" if dependencies == paths[:1] else ":\n")
                output = header + "".join(
                    f"\t{path} (compatibility version 1.0.0, current version 1.0.0)\n" for path in dependencies
                ) + "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n"
            else:
                output = "".join(f"\t{path.name} => {path} (0x123)\n" for path in dependencies)
                output += "\tlibunrelated.so.1 => /outside/lib/libunrelated.so.1 (0x123)\n"

        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(factory.subprocess, "run", run)
    roots = factory._python_library_roots(python_root / "bin/python", python_root, platform=platform)
    assert roots == [str(alias_sqlite), str(real_sqlite), str(alias_ssl), str(real_ssl)]
    if platform == "darwin":
        assert all(command[1:3] == ["-arch", "arm64"] for command, _ in calls[1:])
    assert all("OPENAI_API_KEY" not in kwargs["env"] for _, kwargs in calls)
    assert all("/outside/lib" != root for root in roots)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_python_library_discovery_refuses_unresolved_dependency(tmp_path, monkeypatch, platform):
    python_root = tmp_path / "python"
    python_root.mkdir()
    extension = python_root / "_ssl.so"
    extension.touch()
    monkeypatch.setattr(factory.shutil, "which", lambda name: "/usr/bin/otool")

    def run(command, **kwargs):
        if "-I" in command:
            output = json.dumps({"machine": "arm64", "origins": {"_sqlite3": None, "_ssl": str(extension)}})
        elif platform == "darwin":
            output = f"{extension}:\n\t@rpath/libssl.3.dylib (compatibility version 3.0.0, current version 3.0.0)\n"
        else:
            output = "libssl.so.3 => not found\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(factory.subprocess, "run", run)
    with pytest.raises(delivery.DeliveryError, match="safely inspect"):
        factory._python_library_roots(python_root / "bin/python", python_root, platform=platform)


def test_python_library_discovery_fails_closed_if_tool_or_extension_is_untrusted(tmp_path, monkeypatch):
    python_root = tmp_path / "python"
    python_root.mkdir()
    extension = python_root / "_ssl.so"
    extension.touch()
    monkeypatch.setattr(factory.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, json.dumps({"machine": "arm64", "origins": {"_sqlite3": None, "_ssl": str(extension)}}), ""))
    monkeypatch.setattr(factory.shutil, "which", lambda name: None)
    with pytest.raises(delivery.DeliveryError, match="otool is required"):
        factory._python_library_roots(python_root / "bin/python", python_root, platform="darwin")
    monkeypatch.setattr(factory.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, json.dumps({"machine": "arm64", "origins": {"_sqlite3": None, "_ssl": "built-in"}}), ""))
    assert factory._python_library_roots(python_root / "bin/python", python_root, platform="darwin") == []
    monkeypatch.setattr(factory.shutil, "which", lambda name: "/usr/bin/otool")
    external = tmp_path / "external.so"
    external.touch()
    monkeypatch.setattr(factory.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, json.dumps({"machine": "arm64", "origins": {"_sqlite3": None, "_ssl": str(external)}}), ""))
    with pytest.raises(delivery.DeliveryError, match="safely inspect"):
        factory._python_library_roots(python_root / "bin/python", python_root, platform="darwin")


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


def test_verify_distinguishes_identical_one_pass_outputs_for_full_evidence(tmp_path, monkeypatch):
    import sys

    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, _, _ = _recorded_run(install, state_root, worktrees)
    worktree = Path(state["worktree"])
    (worktree / "tests").mkdir()
    (worktree / "tests/test_feature.py").write_text("# selected targets\n")
    targets = ["tests/test_feature.py::test_one", "tests/test_feature.py::test_two"]
    issue_body = "## Acceptance Criteria\n" + "".join(
        f"- [ ] Behavior.\n  - Verify: `{target}`\n" for target in targets
    )
    head, base = "a" * 40, "b" * 40
    state.update(branch="codex/issue-123-openhands", issue_body_sha256=delivery._sha(issue_body))
    monkeypatch.setattr(delivery, "_finished_run", lambda path: state)
    monkeypatch.setattr(factory, "_candidate_head", lambda *args: head)
    monkeypatch.setattr(service, "status", lambda path: {"status": "running", "state": server})
    monkeypatch.setattr(service, "_settings", lambda path: {})
    monkeypatch.setattr(delivery, "_json_result", lambda command: {
        "number": 123, "state": "OPEN", "body": issue_body,
        "url": f"https://github.com/{delivery.REPOSITORY}/issues/123",
    })
    monkeypatch.setattr(factory, "_verification_command", lambda settings, tree, temp, python, target:
                        [sys.executable, "-c", "print('1 passed in 0.1s')", target])
    result = factory._verify(install, directory, 123, factory.FACTORY_ROOT, worktrees)
    assert result["status"] == "passed"
    entries = result["verification"]
    assert [entry["target"] for entry in entries] == targets
    assert entries[0]["evidence"]["sha256"] != entries[1]["evidence"]["sha256"]
    for target, entry in zip(targets, entries):
        assert Path(entry["evidence"]["path"]).read_text() == (
            f"[verification runner] Target: {target}\n1 passed in 0.1s\n"
        )
    review = directory / "review.txt"
    review.write_text(f"Reviewed {head}\n")
    receipt = directory / "combined.json"
    receipt.write_text(json.dumps({
        "version": 1, "repository": delivery.REPOSITORY, "issue": 123,
        "head_sha": head, "base_sha": base, "risk_surfaces": ["auth"],
        "review": {"reviewer": "independent", "verdict": "pass", "head_sha": head,
                   "blocking_findings": [], "evidence": {"path": str(review)}},
        "verification": entries,
    }))
    assert delivery._full_evidence(receipt, state, head, base, issue_body)[0]["verification"] == entries


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
    assert "actual acceptance criteria and examples and relevant regressions" in captured["prompt"]
    assert "pre-existing behavior as a blocker merely because it could be improved" in captured["prompt"]
    assert "new regressions and failed acceptance criteria as findings" in captured["prompt"]
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
            monkeypatch.setattr(factory, "_candidate_head", lambda path, branch: head)
            result = factory._review(install, directory, 123, factory.FACTORY_ROOT, worktrees,
                                     [], "Feature", {"summary": ["Implemented behavior"]})
            assert result["status"] == "pass"
            assert "declared risk surfaces none" in captured["prompt"]
            assert "unresolved if they omit any applicable risk" in captured["prompt"]
    else:
        assert output["review"] is None


@pytest.mark.parametrize("outcome", ["pass", "failed", "unresolved", "review_failed", "review_unresolved", "stale"])
def test_finish_assembles_exact_evidence_and_refuses_incomplete_results(tmp_path, monkeypatch, capsys, outcome):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, _, _, _ = _recorded_run(install, state_root, worktrees)
    body = "## Acceptance Criteria\n- [ ] Works.\n  - Verify: `tests/test_feature.py::test_ok`\n"
    head, base = "a" * 40, "b" * 40
    state.update(branch="codex/issue-123-openhands", repository=delivery.REPOSITORY,
                 issue_body_sha256=delivery._sha(body))
    service._write(directory, state)
    monkeypatch.setattr(delivery, "_finished_run", lambda path: state)
    monkeypatch.setattr(factory, "_candidate_head", lambda *args: head)
    test_log = directory / "test.log"
    test_log.write_text("1 passed in 0.1s\n")
    review_log = directory / "review.txt"
    review_log.write_text(f"Reviewed {head}\n")
    verification = {"status": outcome if outcome in {"failed", "unresolved"} else "passed",
                    "head_sha": head, "failed": [], "unresolved": [],
                    "verification": [{"target": "tests/test_feature.py::test_ok", "result": "pass",
                                      "head_sha": head, "evidence": {"path": str(test_log)}}]}
    review_entry = {"reviewer": "native-codex-gpt-6.1-terra-independent", "verdict": "pass",
                    "head_sha": head, "blocking_findings": [], "evidence": {"path": str(review_log)}}
    independent = {"status": {"review_failed": "findings", "review_unresolved": "unresolved"}.get(outcome, "pass"),
                   "head_sha": "c" * 40 if outcome == "stale" else head,
                   "base_sha": base, "review": review_entry}
    monkeypatch.setattr(factory, "_verify", lambda *args: verification)
    monkeypatch.setattr(factory, "_review", lambda *args: independent)
    monkeypatch.setattr(factory.publication, "_candidate_paths", lambda *args: {"feature.py"})
    calls = []

    def publish(directory_arg, paths, title, body_inputs, evidence_file):
        evidence, _ = delivery._full_evidence(evidence_file, state, head, base, body)
        calls.append((paths, title, body_inputs, evidence_file, evidence))
        return {"draft": True, "commit_sha": head}

    monkeypatch.setattr(delivery, "publish_full", publish)
    inputs = tmp_path / "body.json"
    inputs.write_text(json.dumps({"lane": "implementation", "final_review_rounds": 1}))
    args = ["finish", "--issue", "123", "--install-root", str(install), "--state-root", str(state_root),
            "--worktree-root", str(worktrees), "--authorize-publication", "--title", "Feature",
            "--body-input-json", str(inputs), "--risk-surface", "auth"]
    code = factory.main(args)
    output = capsys.readouterr()
    if outcome != "pass":
        assert code == 1 and not calls and "publication refused" in output.err
        return
    assert code == 0 and json.loads(output.out)["commit_sha"] == head
    paths, title, body_inputs, evidence_file, evidence = calls[0]
    assert paths == ["feature.py"] and title == "Feature" and body_inputs["final_review_rounds"] == 1
    assert evidence["review"] == review_entry and evidence["verification"] == verification["verification"]
    assert os.stat(evidence_file).st_mode & 0o777 == 0o600
    state["full_publication"] = {"candidate": {"head": head}, "evidence_file": str(evidence_file)}
    monkeypatch.setattr(factory, "_verify", lambda *args: pytest.fail("reran verification on retry"))
    monkeypatch.setattr(factory, "_review", lambda *args: pytest.fail("reran review on retry"))
    assert factory.main(args) == 0
    assert calls[1][3] == evidence_file
    assert factory.main(args[:-1] + ["security"]) == 1
    assert "inputs changed" in capsys.readouterr().err and len(calls) == 2


def test_finish_requires_explicit_publication_authority(tmp_path, monkeypatch, capsys):
    install, state_root, worktrees = _installation(tmp_path)
    monkeypatch.setattr(factory, "_finish", lambda *args: pytest.fail("finish was called"))
    assert factory.main(["finish", "--issue", "123", "--install-root", str(install),
                         "--state-root", str(state_root), "--worktree-root", str(worktrees)]) == 1
    assert "--authorize-publication" in capsys.readouterr().err


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
    monkeypatch.setattr(factory, "_python_library_roots", lambda *args: [])
    monkeypatch.setattr(factory, "python_binary_roots", lambda *args: [])
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


def test_doc_writeback_requires_exact_review_and_candidate_change(tmp_path, monkeypatch):
    target = 'doc writeback at `docs/OWNER.md :: State`'
    body = f'## Acceptance Criteria\n- [ ] Updated state.\n  - Verify: {target}\n'
    head, base = 'a' * 40, 'b' * 40
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    state = {'worktree': str(worktree), 'issue': 123}
    review_file = tmp_path / 'review.json'
    result = {'head_sha': head, 'verdict': 'pass', 'summary': 'Reviewed the change.', 'findings': [],
              'doc_writebacks': [{'target': target, 'result': 'pass',
                                   'rationale': 'The state section describes the delivered behavior.'}]}
    receipt_file = tmp_path / 'receipt.json'
    receipt = {'version': 1, 'repository': delivery.REPOSITORY, 'issue': 123,
               'head_sha': head, 'base_sha': base, 'risk_surfaces': [], 'verification': [],
               'review': {'reviewer': 'independent', 'verdict': 'pass', 'head_sha': head,
                          'issue_body_sha256': delivery._sha(body), 'blocking_findings': [],
                          'evidence': {'path': str(review_file)}}}
    receipt_file.write_text(json.dumps(receipt))
    monkeypatch.setattr(delivery, '_run', lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 0, 'docs/OWNER.md\n', ''))
    monkeypatch.setattr(delivery, '_candidate_document_is_regular', lambda *args: True)
    review_file.write_text(json.dumps(result))
    delivery._full_evidence(receipt_file, state, head, base, body)
    monkeypatch.setattr(delivery, '_candidate_document_is_regular', lambda *args: False)
    with pytest.raises(delivery.DeliveryError, match='regular tracked candidate file'):
        delivery._full_evidence(receipt_file, state, head, base, body)
    monkeypatch.setattr(delivery, '_candidate_document_is_regular', lambda *args: True)
    for field, value in [('target', target.replace('State', 'Other')), ('result', 'fail'),
                         ('result', 'unresolved')]:
        broken = json.loads(json.dumps(result))
        broken['doc_writebacks'][0][field] = value
        review_file.write_text(json.dumps(broken))
        with pytest.raises(delivery.DeliveryError):
            delivery._full_evidence(receipt_file, state, head, base, body)
    review_file.write_text(json.dumps({**result, 'head_sha': 'c' * 40}))
    with pytest.raises(delivery.DeliveryError):
        delivery._full_evidence(receipt_file, state, head, base, body)
    review_file.write_text(json.dumps(result))
    receipt['review']['issue_body_sha256'] = '0' * 64
    receipt_file.write_text(json.dumps(receipt))
    with pytest.raises(delivery.DeliveryError):
        delivery._full_evidence(receipt_file, state, head, base, body)
    receipt['review']['issue_body_sha256'] = delivery._sha(body)
    receipt_file.write_text(json.dumps(receipt))
    monkeypatch.setattr(delivery, '_run', lambda *args, **kwargs: subprocess.CompletedProcess([], 0, '', ''))
    with pytest.raises(delivery.DeliveryError):
        delivery._full_evidence(receipt_file, state, head, base, body)


def test_doc_writeback_verification_waits_for_independent_review(tmp_path, monkeypatch):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, _, _ = _recorded_run(install, state_root, worktrees)
    target = 'doc writeback at `docs/OWNER.md :: State`'
    body = f'## Acceptance Criteria\n- [ ] Updated state.\n  - Verify: {target}\n'
    head = 'a' * 40
    state.update(branch='codex/issue-123-openhands', issue_body_sha256=delivery._sha(body))
    monkeypatch.setattr(delivery, '_finished_run', lambda path: state)
    monkeypatch.setattr(factory, '_candidate_head', lambda *args: head)
    monkeypatch.setattr(service, 'status', lambda path: {'status': 'running', 'state': server})
    monkeypatch.setattr(service, '_settings', lambda path: {})
    monkeypatch.setattr(delivery, '_json_result', lambda command: {
        'number': 123, 'state': 'OPEN', 'body': body,
        'url': f'https://github.com/{delivery.REPOSITORY}/issues/123'})
    result = factory._verify(install, directory, 123, factory.FACTORY_ROOT, worktrees)
    assert result['status'] == 'pending_review'
    assert result['doc_targets'] == [target]
    assert result['verification'] == []


@pytest.mark.parametrize('doc_result', ['pass', 'fail', 'unresolved'])
def test_finish_document_review_to_publication(tmp_path, monkeypatch, doc_result):
    install, state_root, worktrees = _installation(tmp_path)
    directory, state, server, saved, worker_id = _recorded_run(install, state_root, worktrees)
    worktree = Path(state['worktree'])
    (worktree / 'AGENTS.md').write_text('Review repository instructions.\n')
    target = 'doc writeback at `docs/OWNER.md :: State`'
    body = f'## Acceptance Criteria\n- [ ] Updated state.\n  - Verify: {target}\n'
    head, base = 'a' * 40, 'b' * 40
    state.update(branch='codex/issue-123-openhands', issue_body_sha256=delivery._sha(body))
    monkeypatch.setattr(delivery, '_finished_run', lambda path: state)
    monkeypatch.setattr(delivery, '_conversation', lambda *args: saved)
    monkeypatch.setattr(factory, '_candidate_head', lambda *args: head)
    monkeypatch.setattr(service, 'status', lambda path: {'status': 'running', 'state': server})
    monkeypatch.setattr(delivery, '_json_result', lambda command: {
        'number': 123, 'state': 'OPEN', 'body': body,
        'url': f'https://github.com/{delivery.REPOSITORY}/issues/123'})

    def git(command, **kwargs):
        if 'rev-parse' in command:
            output = base
        elif '--name-only' in command:
            output = 'docs/OWNER.md\n'
        elif 'diff' in command:
            output = 'diff --git a/docs/OWNER.md b/docs/OWNER.md\n+Updated state\n'
        else:
            output = ''
        return subprocess.CompletedProcess(command, 0, output, '')

    monkeypatch.setattr(delivery, '_run', git)
    monkeypatch.setattr(delivery, '_candidate_document_is_regular', lambda *args: True)
    called = []

    def run_review(python, settings, workspace, candidate, prompt, worker, *, doc_targets):
        assert worker == worker_id and workspace == worktree and candidate == head
        assert doc_targets == [target] and target in prompt
        text = json.dumps({'head_sha': head, 'verdict': 'pass', 'summary': 'Reviewed candidate.',
                           'findings': [], 'doc_writebacks': [{'target': target, 'result': doc_result,
                           'rationale': 'The State section describes the delivered behavior.'}]})
        return factory.review._parse_result(text, candidate, doc_targets), text, 'independent-thread'

    monkeypatch.setattr(factory.review, 'run_review', run_review)
    monkeypatch.setattr(factory.publication, '_candidate_paths', lambda *args: {'docs/OWNER.md'})

    def publish(directory_arg, paths, title, inputs, evidence_file):
        receipt, _ = delivery._full_evidence(evidence_file, state, head, base, body)
        artifact = Path(receipt['review']['evidence']['path'])
        assert worktree not in artifact.resolve().parents
        assert artifact.stat().st_mode & 0o777 == 0o600
        called.append(receipt)
        return {'draft': True}

    monkeypatch.setattr(delivery, 'publish_full', publish)
    args = (install, directory, 123, factory.FACTORY_ROOT, worktrees, 'Update state', {}, [], None)
    if doc_result == 'pass':
        assert factory._finish(*args) == {'draft': True}
        assert len(called) == 1
    else:
        with pytest.raises(factory.FinishEvidenceError, match='Independent review'):
            factory._finish(*args)
        assert called == []


def test_review_refuses_evidence_directory_in_worker_workspace(tmp_path, monkeypatch):
    install, state_root, worktrees = _installation(tmp_path)
    _, state, _, _, _ = _recorded_run(install, state_root, worktrees)
    worktree = Path(state['worktree'])
    directory = worktree / 'worker-writable-evidence'
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(delivery, '_finished_run', lambda path: state)
    with pytest.raises(delivery.DeliveryError, match='outside the worker workspace'):
        factory._review(install, directory, 123, factory.FACTORY_ROOT, worktrees)


@pytest.mark.parametrize('kind', ['regular', 'deleted', 'missing', 'symlink'])
def test_candidate_document_must_be_regular_tracked_blob(tmp_path, kind):
    repo = tmp_path / 'repo'
    repo.mkdir()

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()

    git('init', '-q')
    (repo / 'docs').mkdir()
    target = repo / 'docs/OWNER.md'
    target.write_text('# State\nOld\n')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'base')
    if kind == 'regular':
        target.write_text('# State\nNew\n')
    elif kind == 'deleted':
        target.unlink()
    elif kind == 'missing':
        target.unlink()
        (repo / 'other').write_text('change')
    else:
        target.unlink()
        target.symlink_to('../other')
    git('add', '-A')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'candidate')
    head = git('rev-parse', 'HEAD')
    assert delivery._candidate_document_is_regular(repo, head, 'docs/OWNER.md') is (kind == 'regular')
