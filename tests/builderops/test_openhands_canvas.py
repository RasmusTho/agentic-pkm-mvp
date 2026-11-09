from __future__ import annotations

import json
import io
import os
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts import openhands_canvas as canvas


def test_port_probe_allows_reuse_and_refuses_a_listener(monkeypatch):
    class Probe:
        reuse = False
        occupied = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, level, option, value):
            assert (level, option, value) == (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.reuse = True

        def bind(self, address):
            assert address == ("127.0.0.1", 3001)
            if not self.reuse:  # Simulate a recently closed connection.
                raise OSError("address in use")

        def listen(self, backlog):
            if self.occupied:  # Some platforms defer a listener conflict until listen().
                raise OSError("address in use")

    monkeypatch.setattr(canvas.socket, "socket", lambda *args: Probe())
    canvas.ensure_port_free(3001)
    Probe.occupied = True
    with pytest.raises(canvas.CanvasError, match="port is unavailable"):
        canvas.ensure_port_free(3001)


def test_port_probe_with_recent_connection_and_active_listener():
    listener = None
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
    except PermissionError:
        if listener is not None:
            listener.close()
        pytest.skip("loopback sockets are unavailable")
    with listener:
        port = listener.getsockname()[1]
        listener.listen(1)
        with pytest.raises(canvas.CanvasError, match="port is unavailable"):
            canvas.ensure_port_free(port)
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            accepted, _ = listener.accept()
            with accepted:
                accepted.shutdown(socket.SHUT_WR)
                assert client.recv(1) == b""
    canvas.ensure_port_free(port)


@pytest.mark.parametrize(
    ("marker_status", "marker_body", "ready"),
    [
        (200, b"unrelated listener", False),
        (503, b"different service", False),
        (503, b"Service Unavailable (no backend configured for this route) extra", False),
        (503, b"Service Unavailable (no backend configured for this route)", False),
        (503, b"Service Unavailable (no backend configured for this route)", True),
    ],
)
def test_readiness_requires_marker_response(monkeypatch, marker_status, marker_body, ready):
    marker = "/__owner_canvas_" + "a" * 32
    requests = []

    class Process:
        polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 or ready else 1

    class Response:
        def __init__(self, path):
            self.status = 200 if path == "/" else marker_status

        def read(self, size):
            return marker_body[:size]

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 3001, 0.2)

        def request(self, method, path):
            assert method == "GET"
            self.path = path
            requests.append(path)

        def getresponse(self):
            return Response(self.path)

        def close(self):
            pass

    # A failed marker probe is followed by the server child exiting.
    monkeypatch.setattr(canvas.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(canvas.time, "sleep", lambda _: None)
    if ready:
        canvas.wait_ready(Process(), 3001, marker)
    else:
        with pytest.raises(canvas.CanvasError, match="exited before becoming ready"):
            canvas.wait_ready(Process(), 3001, marker)
    assert requests == ["/", marker]


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
    requests = []
    auth = {"accept_key": True, "require_key": True}

    class BackendConnection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 8000, 5)

        def request(self, method, path, headers):
            requests.append((method, path, headers))
            self.has_key = "X-Session-API-Key" in headers

        def getresponse(self):
            accepted = auth["accept_key"] if self.has_key else not auth["require_key"]
            return SimpleNamespace(status=200 if accepted else 401)

        def close(self):
            pass

    class Process:
        pid = 54321

        def __init__(self, command, **kwargs):
            launches.append((command[5:], kwargs))
            running[12345] = command[4]
            self.stdout = io.BytesIO(b'{"pid":12345}\n')

        def poll(self):
            return None if running else 0

        def terminate(self):
            running.clear()

        def wait(self, timeout=None):
            return 0

    def request(state_path, state, action):
        if state.get("supervised") is not True:
            raise canvas.CanvasError("legacy Canvas is not supervised")
        if state["pid"] != 12345 or (running and state["marker"] != running[12345]):
            raise canvas.CanvasError("supervisor refused request; state retained")
        if action == "stop":
            running.clear()
            return "stopped"
        return "running" if running else "stopped"

    monkeypatch.setattr(canvas.shutil, "which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(canvas.http.client, "HTTPConnection", BackendConnection)
    monkeypatch.setattr(canvas.subprocess, "Popen", Process)
    monkeypatch.setattr(canvas, "supervisor_request", request)
    monkeypatch.setattr(canvas.select, "select", lambda r, w, x, timeout: (r, [], []))
    monkeypatch.setattr(canvas, "wait_ready", lambda process, port, marker: None)
    monkeypatch.setattr(canvas, "ensure_port_free", lambda port: None)
    args = ["--package-dir", str(package), "--backend", "http://127.0.0.1:8000",
            "--key-file", str(key_file), "--state-dir", str(state_dir)]
    return SimpleNamespace(args=args, state=state_dir, key=key_file, running=running,
                           launches=launches, requests=requests, auth=auth)


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
    state_file = setup.state / "server.json"
    state = json.loads(state_file.read_text())
    state_file.write_text(json.dumps({**state, "pid": state["pid"] + 1}))
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert state["pid"] in setup.running
    assert state_file.exists()
    state_file.write_text(json.dumps(state))
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 0
    assert not setup.running
    assert not (setup.state / "server.json").exists()
    assert "stopped" in capsys.readouterr().out


def test_key_and_loopback_configuration(setup, capsys):
    assert canvas.main(["start", *setup.args]) == 0
    assert setup.requests == [
        ("GET", "/api/conversations/search", {"X-Session-API-Key": "test-only-session-key"}),
        ("GET", "/api/conversations/search", {}),
    ]
    command, kwargs = setup.launches[0]
    assert kwargs["env"]["SESSION_API_KEY"] == "test-only-session-key"
    assert kwargs["env"]["AGENT_CANVAS_DISABLE_TELEMETRY"] == "1"
    assert "--auth-required" in command
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


def test_invalid_key_and_unprotected_backend_refuse_start(setup, capsys):
    setup.auth["accept_key"] = False
    assert canvas.main(["start", *setup.args]) == 1
    assert not setup.launches
    assert not (setup.state / "server.json").exists()
    assert "backend rejected" in capsys.readouterr().err
    setup.auth["accept_key"] = True
    setup.auth["require_key"] = False
    assert canvas.main(["start", *setup.args]) == 1
    assert not setup.launches
    assert "authentication could not be confirmed" in capsys.readouterr().err
    setup.auth["require_key"] = True
    assert canvas.main(["start", *setup.args]) == 0
    setup.auth["accept_key"] = False
    assert canvas.main(["start", *setup.args]) == 1
    output = capsys.readouterr()
    assert "backend rejected" in output.err
    assert "test-only-session-key" not in output.out + output.err
    assert len(setup.launches) == 1
    assert setup.running


def test_backend_verification_failure_does_not_expose_key(setup, monkeypatch, capsys):
    class FailedConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise OSError("test-only-session-key")

        def close(self):
            pass

    monkeypatch.setattr(canvas.http.client, "HTTPConnection", FailedConnection)
    assert canvas.main(["start", *setup.args]) == 1
    output = capsys.readouterr()
    assert "could not verify" in output.err
    assert "test-only-session-key" not in output.out + output.err
    assert not setup.launches
    assert not (setup.state / "server.json").exists()


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
    def failed_ready(process, port, marker):
        raise canvas.CanvasError("not ready")

    monkeypatch.setattr(canvas, "wait_ready", failed_ready)
    assert canvas.main(["start", *setup.args]) == 1
    assert not setup.running
    assert not (setup.state / "server.json").exists()
    monkeypatch.setattr(canvas, "wait_ready", lambda process, port, marker: None)
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
    monkeypatch.setattr(canvas.select, "select", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
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


def test_unavailable_supervisor_preserves_state(setup, monkeypatch):
    assert canvas.main(["start", *setup.args]) == 0
    monkeypatch.setattr(canvas, "supervisor_request", lambda *args: (_ for _ in ()).throw(canvas.CanvasError("supervisor unavailable")))
    assert canvas.main(["status", "--state-dir", str(setup.state)]) == 1
    assert canvas.main(["start", *setup.args]) == 1
    assert canvas.main(["stop", "--state-dir", str(setup.state)]) == 1
    assert (setup.state / "server.json").exists()
    assert setup.running
    assert len(setup.launches) == 1


def test_legacy_state_never_signals_a_process(tmp_path, monkeypatch):
    state = {"pid": 12345, "marker": "/__owner_canvas_" + "a" * 32}
    monkeypatch.setattr(canvas.os, "kill", lambda *args: pytest.fail("legacy PID must not be signalled"))
    with pytest.raises(canvas.CanvasError, match="legacy Canvas"):
        canvas.supervisor_request(tmp_path / "server.json", state, "stop")


def test_real_supervisor_controls_only_its_child(tmp_path):
    control = tmp_path / "control"
    os.mkfifo(control, 0o600)
    marker = "/__owner_canvas_" + "a" * 32
    script = Path(__file__).resolve().parents[2] / "scripts/openhands_canvas.py"
    helper = subprocess.Popen([sys.executable, str(script), "_supervise", str(control), marker,
                               sys.executable, "-c", "import time; time.sleep(30)"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={"PATH": os.defpath})
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={})
    state = None
    try:
        assert helper.stdout is not None
        assert canvas.select.select([helper.stdout], [], [], 5)[0]
        pid = json.loads(helper.stdout.readline())["pid"]
        state = {"supervised": True, "control": control.name, "marker": marker, "pid": pid}
        assert canvas.supervisor_request(tmp_path / "server.json", state, "status") == "running"
        with pytest.raises(canvas.CanvasError, match="refused"):
            canvas.supervisor_request(tmp_path / "server.json", {**state, "pid": unrelated.pid}, "stop")
        assert unrelated.poll() is None
        assert canvas.supervisor_request(tmp_path / "server.json", state, "status") == "running"
        assert canvas.supervisor_request(tmp_path / "server.json", state, "stop") == "stopped"
        assert helper.wait(timeout=5) == 0
        assert unrelated.poll() is None
        with pytest.raises(canvas.CanvasError, match="supervisor unavailable"):
            canvas.supervisor_request(tmp_path / "server.json", state, "stop")
    finally:
        if helper.poll() is None and state is not None:
            try:
                canvas.supervisor_request(tmp_path / "server.json", state, "stop")
            except canvas.CanvasError:
                pass
        if helper.poll() is None:
            helper.wait(timeout=35)
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_assembled_launcher_with_real_supervisor(tmp_path, monkeypatch, capsys):
    if not shutil.which("node"):
        pytest.skip("node is required")
    package = tmp_path / "package"
    (package / "scripts").mkdir(parents=True)
    (package / "scripts" / "static-server.mjs").write_text("setTimeout(() => {}, 30000);\n")
    (package / "build").mkdir()
    (package / "build" / "index.html").write_text("fixture")
    key = tmp_path / "key"
    key.write_text("synthetic-only-key\n")
    key.chmod(0o600)
    state_dir = tmp_path / "state"
    args = ["--package-dir", str(package), "--backend", "http://127.0.0.1:8000",
            "--key-file", str(key), "--state-dir", str(state_dir)]
    helpers = []
    spawn = subprocess.Popen

    def observe(*args, **kwargs):
        process = spawn(*args, **kwargs)
        helpers.append(process)
        return process

    monkeypatch.setattr(canvas.subprocess, "Popen", observe)
    # Only network effects are substituted; supervisor and CLI remain real.
    monkeypatch.setattr(canvas, "ensure_port_free", lambda port: None)
    monkeypatch.setattr(canvas, "wait_ready", lambda process, port, marker: None)
    monkeypatch.setattr(canvas, "verify_backend_key", lambda backend, key: None)
    try:
        assert canvas.main(["start", *args]) == 0
        assert canvas.main(["status", "--state-dir", str(state_dir)]) == 0
        assert canvas.main(["start", *args]) == 0
        assert len(helpers) == 1
        assert "synthetic-only-key" not in (state_dir / "server.json").read_text()
        assert "synthetic-only-key" not in capsys.readouterr().out
        assert canvas.main(["stop", "--state-dir", str(state_dir)]) == 0
        assert helpers[0].wait(timeout=5) == 0
    finally:
        if (state_dir / "server.json").exists():
            canvas.main(["stop", "--state-dir", str(state_dir)])
        for helper in helpers:
            if helper.poll() is None:
                helper.wait(timeout=35)


def test_installed_canvas_auth_mode_does_not_inject_key():
    package = os.environ.get("OPENHANDS_CANVAS_PACKAGE")
    node = shutil.which("node")
    if not package or not node:
        pytest.skip("installed Canvas package and node are required")
    server = (Path(package) / "scripts/static-server.mjs").as_uri()
    js = ("const m=await import(process.argv[1]);"
          "const c=m.parseArgs(['--auth-required'],process.env);"
          "if(!c.authRequired || c.sessionApiKey!==null)process.exit(1)")
    result = subprocess.run([node, "--input-type=module", "-e", js, server],
                            env={"PATH": os.defpath, "SESSION_API_KEY": "synthetic-key"},
                            capture_output=True, check=False)
    assert result.returncode == 0
    assert b"synthetic-key" not in result.stdout + result.stderr


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
            page = response.read()
            assert key.encode() not in page
            assert b"__AGENT_CANVAS_AUTH_REQUIRED__" in page
        with pytest.raises(HTTPError) as unauthenticated:
            urlopen(url + "/api/test", timeout=3)
        assert unauthenticated.value.code == 401
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
