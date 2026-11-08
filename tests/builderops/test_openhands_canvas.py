from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from scripts import openhands_canvas as canvas


@pytest.fixture
def setup(tmp_path, monkeypatch):
    package = tmp_path / "package"
    (package / "scripts").mkdir(parents=True)
    (package / "scripts" / "static-server.mjs").write_text("// fixture")
    (package / "build").mkdir()
    (package / "build" / "index.html").write_text("fixture")
    key_file = tmp_path / "key"
    key_file.write_text("test-only-session-key\n")
    key_file.chmod(0o600)
    state_dir = tmp_path / "state"
    running = {}
    launches = []

    class Process:
        pid = 12345

        def __init__(self, command, **kwargs):
            launches.append((command, kwargs))
            running[self.pid] = ("Mon Nov  9 01:02:03 2026", "S", " ".join(command))

        def poll(self):
            return None if self.pid in running else 0

        def terminate(self):
            running.pop(self.pid, None)

        def wait(self, timeout=None):
            return 0

    def send_signal(fd, sig):
        assert sig == signal.SIGTERM
        running.pop(Process.pid, None)

    monkeypatch.setattr(canvas.shutil, "which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(canvas.subprocess, "Popen", Process)
    monkeypatch.setattr(canvas, "process_info", lambda pid: running.get(pid))
    monkeypatch.setattr(canvas, "wait_ready", lambda process, port: None)
    monkeypatch.setattr(canvas, "ensure_port_free", lambda port: None)
    monkeypatch.setattr(canvas.os, "pidfd_open", lambda pid: os.open(os.devnull, os.O_RDONLY), raising=False)
    monkeypatch.setattr(canvas.signal, "pidfd_send_signal", send_signal, raising=False)
    args = ["--package-dir", str(package), "--backend", "http://127.0.0.1:8000",
            "--key-file", str(key_file), "--state-dir", str(state_dir)]
    return SimpleNamespace(args=args, state=state_dir, key=key_file, running=running, launches=launches)


def test_start_status_and_repeat(setup, capsys):
    assert canvas.main(["start", *setup.args]) == 0
    assert capsys.readouterr().out == "http://127.0.0.1:3001\n"
    assert canvas.main(["status", "--state-dir", str(setup.state)]) == 0
    assert capsys.readouterr().out == "running http://127.0.0.1:3001\n"
    assert canvas.main(["start", *setup.args]) == 0
    assert len(setup.launches) == 1
    assert canvas.main(["start", *setup.args, "--port", "3002"]) == 1
    assert len(setup.launches) == 1


def test_rotated_key_requires_restart(setup, capsys):
    assert canvas.main(["start", *setup.args]) == 0
    setup.key.write_text("rotated-test-session-key\n")
    assert canvas.main(["start", *setup.args]) == 1
    output = capsys.readouterr()
    assert "session key changed" in output.err
    assert "rotated-test-session-key" not in output.out + output.err
    assert "rotated-test-session-key" not in (setup.state / "server.json").read_text()
    assert len(setup.launches) == 1
    assert setup.running
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 0
    assert canvas.main(["start", *setup.args]) == 0
    assert setup.launches[-1][1]["env"]["SESSION_API_KEY"] == "rotated-test-session-key"
    assert len(setup.launches) == 2


def test_stop_owns_only_the_canvas_process(setup, capsys):
    assert canvas.main(["start", *setup.args]) == 0
    state = json.loads((setup.state / "server.json").read_text())
    # A reused PID, even one with the same command, must not be signalled.
    original = setup.running[state["pid"]]
    setup.running[state["pid"]] = ("different start time", original[1], original[2])
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert state["pid"] in setup.running
    assert (setup.state / "server.json").exists()
    setup.running[state["pid"]] = original
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 0
    assert not setup.running
    assert not (setup.state / "server.json").exists()
    assert "stopped" in capsys.readouterr().out


def test_key_and_loopback_configuration(setup, capsys):
    assert canvas.main(["start", *setup.args]) == 0
    command, kwargs = setup.launches[0]
    assert kwargs["env"]["SESSION_API_KEY"] == "test-only-session-key"
    assert kwargs["env"]["AGENT_CANVAS_DISABLE_TELEMETRY"] == "1"
    assert "test-only-session-key" not in " ".join(command)
    assert "test-only-session-key" not in (setup.state / "server.json").read_text()
    assert "--host" in command and command[command.index("--host") + 1] == "127.0.0.1"
    assert "/api=http://127.0.0.1:8000" in command
    assert "/sockets=http://127.0.0.1:8000" in command
    assert "test-only-session-key" not in capsys.readouterr().out
    for invalid in ("http://example.com:8000", "http://0.0.0.0:8000", "https://127.0.0.1:8000", "http://user@127.0.0.1:8000", "http://127.0.0.1:0"):
        with pytest.raises(canvas.CanvasError):
            canvas.endpoint_url(invalid)
    setup.key.chmod(0o644)
    with pytest.raises(canvas.CanvasError):
        canvas.private_file(setup.key)


def test_documented_cli_help():
    root = Path(__file__).resolve().parents[2]
    for args, expected in ((["--help"], ("start", "status", "stop")),
                           (["start", "--help"], ("--package-dir", "--backend", "--key-file", "--state-dir", "--open"))):
        result = subprocess.run([sys.executable, str(root / "scripts/openhands_canvas.py"), *args],
                                text=True, capture_output=True, check=True)
        assert all(item in result.stdout for item in expected)
    doc = (root / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md").read_text()
    assert "scripts/openhands_canvas.py" in doc
    assert "already-running" in doc


def test_invalid_state_refuses_stop(setup, capsys):
    setup.state.mkdir(mode=0o700)
    state = setup.state / "server.json"
    state.write_text('{"version": 1, "pid": 1}')
    state.chmod(0o600)
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert state.exists()
    assert "invalid server state" in capsys.readouterr().err


def test_failed_start_cleans_up_and_can_retry(setup, monkeypatch):
    def failed_ready(process, port):
        raise canvas.CanvasError("not ready")

    monkeypatch.setattr(canvas, "wait_ready", failed_ready)
    assert canvas.main(["start", *setup.args]) == 1
    assert not setup.running
    assert not (setup.state / "server.json").exists()
    monkeypatch.setattr(canvas, "wait_ready", lambda process, port: None)
    assert canvas.main(["start", *setup.args]) == 0
    assert len(setup.launches) == 2


def test_interrupted_start_retains_unknown_intent_and_prevents_duplicate(setup, monkeypatch, capsys):
    spawn = canvas.subprocess.Popen

    def spawn_after_intent(*args, **kwargs):
        intent = json.loads((setup.state / "server.json").read_text())
        assert intent["phase"] == "starting"
        assert intent["marker"].startswith("/__owner_canvas_")
        assert intent["backend"] == "http://127.0.0.1:8000"
        assert "test-only-session-key" not in (setup.state / "server.json").read_text()
        return spawn(*args, **kwargs)

    monkeypatch.setattr(canvas.subprocess, "Popen", spawn_after_intent)
    monkeypatch.setattr(canvas, "process_info", lambda pid: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        canvas.main(["start", *setup.args])
    assert setup.running
    assert canvas.main(["status", "--state-dir", str(setup.state)]) == 1
    assert "startup outcome unknown" in capsys.readouterr().err
    assert canvas.main(["start", *setup.args]) == 1
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert len(setup.launches) == 1
    assert setup.running
    assert (setup.state / "server.json").exists()


def test_macos_rechecks_identity_before_stop(setup, monkeypatch, capsys):
    monkeypatch.delattr(canvas.os, "pidfd_open")
    monkeypatch.setattr(canvas.sys, "platform", "darwin")
    calls = []

    def kill(pid, sig):
        calls.append((pid, sig))
        setup.running.pop(pid)

    monkeypatch.setattr(canvas.os, "kill", kill)
    assert canvas.main(["start", *setup.args]) == 0
    state = json.loads((setup.state / "server.json").read_text())
    original = setup.running[state["pid"]]
    observations = iter([original, ("different start", original[1], original[2])])
    monkeypatch.setattr(canvas, "process_info", lambda pid: next(observations))
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert not calls
    assert (setup.state / "server.json").exists()
    assert "refusing to stop" in capsys.readouterr().err
    monkeypatch.setattr(canvas, "process_info", lambda pid: setup.running.get(pid))
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 0
    assert calls == [(state["pid"], signal.SIGTERM)]


def test_unavailable_identity_preserves_state(setup, monkeypatch):
    assert canvas.main(["start", *setup.args]) == 0
    monkeypatch.setattr(canvas, "process_info", lambda pid: (_ for _ in ()).throw(canvas.CanvasError("inspection unavailable")))
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert (setup.state / "server.json").exists()
    assert setup.running


def test_disappearing_process_preserves_state(setup, monkeypatch):
    assert canvas.main(["start", *setup.args]) == 0
    state = json.loads((setup.state / "server.json").read_text())
    original = setup.running[state["pid"]]
    observations = iter([original, None])
    monkeypatch.setattr(canvas, "process_info", lambda pid: next(observations))
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert (setup.state / "server.json").exists()
    assert setup.running


def test_identity_change_after_signal_preserves_state(setup, monkeypatch):
    assert canvas.main(["start", *setup.args]) == 0
    state = json.loads((setup.state / "server.json").read_text())
    original = setup.running[state["pid"]]
    observations = iter([original, original, ("different start", original[1], original[2])])
    monkeypatch.setattr(canvas, "process_info", lambda pid: next(observations))
    monkeypatch.setattr(canvas.signal, "pidfd_send_signal", lambda fd, sig: None)
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert (setup.state / "server.json").exists()


def test_process_identity_parsing(monkeypatch):
    result = SimpleNamespace(returncode=0, stdout="Mon Nov  9 01:02:03 2026  S  node /tmp/static-server.mjs --host 127.0.0.1 --reject-prefix /__owner_canvas_" + "a" * 32 + " --route /api=http://127.0.0.1:8000")
    monkeypatch.setattr(canvas.subprocess, "run", lambda *args, **kwargs: result)
    state = {"pid": 123, "started": "Mon Nov 9 01:02:03 2026",
             "marker": "/__owner_canvas_" + "a" * 32, "server": "/tmp/static-server.mjs"}
    assert canvas.process_status(state) == "running"
    assert canvas.process_status({**state, "marker": "/__owner_canvas_" + "b" * 32}) == "mismatch"
    assert canvas.process_status({**state, "started": "different"}) == "mismatch"
    assert canvas.process_status({**state, "server": "/tmp/static-server"}) == "mismatch"


def test_real_process_identity_and_stop(tmp_path):
    marker = "/__owner_canvas_" + "a" * 32
    server = str(tmp_path / "static-server.mjs")
    # The test child is never a real Canvas or backend and has no network access.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", server,
                              "--host", "127.0.0.1", "--reject-prefix", marker, "--route", "/api=http://127.0.0.1:8000"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={})
    backend = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={})
    try:
        try:
            info = canvas.process_info(child.pid)
        except PermissionError:
            pytest.skip("process inspection is unavailable")
        assert info is not None
        state = {"pid": child.pid, "started": info[0], "marker": marker, "server": server}
        assert canvas.process_status(state) == "running"
        assert canvas.process_status({**state, "started": "not the start time"}) == "mismatch"
        canvas.stop_owned(state)
        child.wait(timeout=5)
        assert backend.poll() is None
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)
        backend.terminate()
        backend.wait(timeout=5)


def test_real_installed_canvas_with_isolated_backend(tmp_path):
    package = os.environ.get("OPENHANDS_CANVAS_PACKAGE")
    if not package:
        pytest.skip("set OPENHANDS_CANVAS_PACKAGE to an installed package for loopback integration")
    key = "synthetic-integration-key"

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.headers.get("X-Session-API-Key") == key else 401)
            self.end_headers()
            self.wfile.write(b"backend")

        def log_message(self, *args):
            pass

    try:
        backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
    except PermissionError:
        pytest.skip("loopback sockets are unavailable")
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    key_file = tmp_path / "key"
    key_file.write_text(key)
    key_file.chmod(0o600)
    state = tmp_path / "state"
    script = Path(__file__).resolve().parents[2] / "scripts/openhands_canvas.py"
    common = [sys.executable, str(script)]
    endpoint = f"http://127.0.0.1:{backend.server_port}"
    url = f"http://127.0.0.1:{port}"
    started = False
    try:
        result = subprocess.run([*common, "start", "--package-dir", package,
                                 "--backend", endpoint, "--key-file", str(key_file),
                                 "--state-dir", str(state), "--port", str(port)],
                                text=True, capture_output=True, check=True)
        started = True
        assert result.stdout.strip() == url
        assert key not in result.stdout + result.stderr + (state / "server.json").read_text()
        with urlopen(url, timeout=3) as response:
            assert key.encode() in response.read()
        request = Request(url + "/api/test", headers={"X-Session-API-Key": key})
        with urlopen(request, timeout=3) as response:
            assert response.read() == b"backend"
        subprocess.run([*common, "stop", "--state-dir", str(state)], check=True, capture_output=True)
        started = False
        request = Request(endpoint + "/api/test", headers={"X-Session-API-Key": key})
        with urlopen(request, timeout=3) as response:
            assert response.read() == b"backend"
    finally:
        if started:
            subprocess.run([*common, "stop", "--state-dir", str(state)], check=False, capture_output=True)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
