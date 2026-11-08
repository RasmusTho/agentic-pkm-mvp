import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops import openhands_service as service


@pytest.fixture
def settings_file(tmp_path):
    data = {
        "guard_executable": os.sys.executable,
        "codex_binary": os.sys.executable,
        "codex_config_args": ["--model", "gpt-6.1-terra"],
        "sandbox_read_roots": [str(tmp_path)],
        "conversations_path": str(tmp_path / "stored-conversations"),
        "bash_events_dir": str(tmp_path / "stored-events"),
        "conversation_worktree_root": str(tmp_path / "stored-worktrees"),
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    return path


def test_start_assembles_loopback_server_and_sanitizes_environment(
    tmp_path, monkeypatch, settings_file, capsys
):
    state_dir = tmp_path / "host"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    python = tmp_path / "python"
    python.symlink_to(Path(os.sys.executable))
    monkeypatch.setenv("PROVIDER_API_KEY", "should-not-pass")
    monkeypatch.setenv("RANDOM_SECRET", "should-not-pass")
    monkeypatch.setenv("OH_SESSION_API_KEYS_0", "should-not-pass")
    monkeypatch.setenv("OH_WORKSPACE_PATH", "/untrusted")
    settings = json.loads(settings_file.read_text())
    settings["resume_thread_id"] = "01a1bcfd-b399-7e32-8834-4e34bd9bfbac"
    settings_file.write_text(json.dumps(settings))
    captured = {}

    def launch(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(service.subprocess, "Popen", launch)
    monkeypatch.setattr(service, "_identity", lambda pid: ("start time", captured["command"][2]))
    result = service.start(state_dir, python, workspace, 8123, settings_file)
    assert result["status"] == "running"
    assert captured["command"][0] == str(python)  # preserve venv symlink
    assert captured["command"][3:] == ["--host", "127.0.0.1", "--port", "8123"]
    assert captured["cwd"] == state_dir
    assert captured["env"]["OH_WORKSPACE_PATH"] == str(workspace)
    env = captured["env"]
    assert env["OH_PERSISTENCE_DIR"] == str(state_dir / "openhands")
    assert env["CODEX_PATH"] == os.sys.executable
    assert env["OPENHANDS_FACTORY_PYTHON"] == str(python)
    assert env["OPENHANDS_FACTORY_RESUME_THREAD"] == settings["resume_thread_id"]
    assert env["PYTHONPATH"] == str(Path(service.__file__).resolve().parents[2])
    assert env["OPENHANDS_FACTORY_WORKSPACE"] == str(workspace)
    assert env["OPENHANDS_CODEX_BINARY"] == os.sys.executable
    assert json.loads(env["OPENHANDS_CODEX_CONFIG_ARGS"]) == ["--model", "gpt-6.1-terra"]
    assert json.loads(env["OPENHANDS_FACTORY_READ_ROOTS"]) == [str(tmp_path)]
    assert env["OH_CONVERSATIONS_PATH"] == str(tmp_path / "stored-conversations")
    assert env["OH_BASH_EVENTS_DIR"] == str(tmp_path / "stored-events")
    assert env["OH_CONVERSATION_WORKTREE_ROOT"] == str(tmp_path / "stored-worktrees")
    assert env["OH_TELEMETRY_CONSENT"] == "denied"
    key = (state_dir / "session-api-key").read_text().strip()
    assert env["OH_SESSION_API_KEYS_0"] == key
    assert key != "should-not-pass"
    assert (state_dir / "session-api-key").stat().st_mode & 0o777 == 0o600
    assert key not in json.dumps(result)
    assert key not in (state_dir / "service.json").read_text()
    assert key not in capsys.readouterr().out
    assert "PROVIDER_API_KEY" not in captured["env"]
    assert "RANDOM_SECRET" not in captured["env"]
    assert service.status(state_dir)["status"] == "running"
    assert json.loads((state_dir / "service.json").read_text())["pid"] == 12345
    with pytest.raises(service.ServiceError, match="running"):
        service.start(state_dir, python, workspace, 8123, settings_file)


def test_status_and_stop_refuse_stale_or_reused_pid(tmp_path, monkeypatch, settings_file):
    service._write(tmp_path, {"version": 1, "state": "running", "pid": 123, "marker": "unique", "started": "old"})
    monkeypatch.setattr(service, "_identity", lambda pid: ("new", "unrelated process"))
    monkeypatch.setattr(service.os, "kill", lambda *args: pytest.fail("must not signal"))
    assert service.status(tmp_path)["status"] == "stale"
    with pytest.raises(service.ServiceError, match="stale"):
        service.stop(tmp_path)
    with pytest.raises(service.ServiceError, match="stale"):
        service.start(tmp_path, Path(os.sys.executable), tmp_path, 9000, settings_file)


def test_stop_checks_identity_and_persists_stopped(tmp_path, monkeypatch):
    state = {"version": 1, "state": "running", "pid": 123, "marker": "unique", "started": "old"}
    service._write(tmp_path, state)
    identities = iter([("old", "unique"), ("old", "unique"), None])
    monkeypatch.setattr(service, "_identity", lambda pid: next(identities))
    monkeypatch.delattr(service.os, "pidfd_open", raising=False)
    sent = []
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert service.stop(tmp_path)["status"] == "stopped"
    assert sent == [(123, service.signal.SIGTERM)]
    assert service.status(tmp_path)["status"] == "stopped"


def test_launch_failure_is_stopped_but_ambiguous_identity_is_stale(
    tmp_path, monkeypatch, settings_file
):
    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(OSError("failed")))
    with pytest.raises(service.ServiceError, match="Could not launch"):
        service.start(tmp_path, Path(os.sys.executable), tmp_path, 9000, settings_file)
    assert service.status(tmp_path)["status"] == "stopped"
    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=123))
    monkeypatch.setattr(service, "_identity", lambda pid: None)
    with pytest.raises(service.ServiceError, match="identity"):
        service.start(tmp_path, Path(os.sys.executable), tmp_path, 9000, settings_file)
    assert service.status(tmp_path)["status"] == "stale"


def test_cli_status_and_input_validation(tmp_path, capsys, settings_file):
    assert service.main(["--state-dir", str(tmp_path / "state"), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stopped"
    assert service.main(["--state-dir", str(tmp_path), "start", "--python", os.sys.executable, "--workspace", str(tmp_path), "--port", "0", "--settings", str(settings_file)]) == 1
    assert "port" in capsys.readouterr().err
    result = subprocess.run([os.sys.executable, "-m", "app.builderops.openhands_service", "--help"], capture_output=True, text=True, check=True)
    assert "start" in result.stdout and "status" in result.stdout and "stop" in result.stdout


def test_process_identity_parses_ps_and_refuses_inspection_errors(monkeypatch):
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(
            returncode=0, stdout="S  Sun Nov  8 22:00:00 2026 python -c marker\n"
        )

    monkeypatch.setattr(service.subprocess, "run", run)
    assert service._identity(123) == ("Sun Nov 8 22:00:00 2026", "python -c marker")
    assert seen[0][:4] == ["ps", "-ww", "-p", "123"]
    monkeypatch.setattr(
        service.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=2, stdout="")
    )
    with pytest.raises(service.ServiceError, match="inspect"):
        service._identity(123)


def test_stop_timeout_preserves_running_state(tmp_path, monkeypatch):
    service._write(
        tmp_path,
        {"version": 1, "state": "running", "pid": 123, "marker": "unique", "started": "old"},
    )
    monkeypatch.setattr(service, "_identity", lambda pid: ("old", "unique"))
    monkeypatch.delattr(service.os, "pidfd_open", raising=False)
    monkeypatch.setattr(service.os, "kill", lambda *args: None)
    with pytest.raises(service.ServiceError, match="timeout"):
        service.stop(tmp_path, timeout=0)
    assert service.status(tmp_path)["status"] == "running"


def test_session_key_reused_and_never_printed_by_cli(tmp_path, monkeypatch, settings_file, capsys):
    state_dir = tmp_path / "state"
    launches = []

    def launch(command, **kwargs):
        launches.append((command, kwargs))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(service.subprocess, "Popen", launch)
    monkeypatch.setattr(service, "_identity", lambda pid: ("start", launches[-1][0][2]))
    argv = [
        "--state-dir", str(state_dir), "start", "--python", os.sys.executable,
        "--workspace", str(tmp_path), "--port", "8123", "--settings", str(settings_file),
    ]
    assert service.main(argv) == 0
    key = launches[0][1]["env"]["OH_SESSION_API_KEYS_0"]
    assert key not in capsys.readouterr().out
    data = service._read(state_dir)
    data["state"] = "stopped"
    service._write(state_dir, data)
    assert service.main(argv) == 0
    assert launches[1][1]["env"]["OH_SESSION_API_KEYS_0"] == key
    assert key not in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["public_key", "symlink_key", "public_directory"])
def test_insecure_key_or_directory_refuses_launch(tmp_path, monkeypatch, settings_file, kind):
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    key = state_dir / "session-api-key"
    if kind == "public_directory":
        state_dir.chmod(0o755)
    elif kind == "symlink_key":
        key.symlink_to(settings_file)
    else:
        key.write_text("x" * 43)
        key.chmod(0o644)
    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **kw: pytest.fail("launched"))
    with pytest.raises(service.ServiceError):
        service.start(state_dir, Path(os.sys.executable), tmp_path, 8123, settings_file)
    assert not (state_dir / "service.json").exists()


@pytest.mark.parametrize("invalid", ["unknown", "bad_args", "relative_root", "missing_guard"])
def test_invalid_settings_refuse_before_launch(tmp_path, monkeypatch, settings_file, invalid):
    settings = json.loads(settings_file.read_text())
    if invalid == "unknown":
        settings["api_key"] = "must-not-appear-in-errors"
    elif invalid == "bad_args":
        settings["codex_config_args"] = "not-an-array"
    elif invalid == "relative_root":
        settings["sandbox_read_roots"] = ["relative"]
    else:
        settings["guard_executable"] = str(tmp_path / "missing")
    settings_file.write_text(json.dumps(settings))
    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **kw: pytest.fail("launched"))
    with pytest.raises(service.ServiceError) as exc:
        service.start(tmp_path / "state", Path(os.sys.executable), tmp_path, 8123, settings_file)
    assert "must-not-appear-in-errors" not in str(exc.value)
    assert not (tmp_path / "state").exists()
