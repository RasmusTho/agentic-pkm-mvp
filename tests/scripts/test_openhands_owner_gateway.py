"""Exercise real HTTP admission and proxying without a tailnet or credentials."""
import http.client
import json
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_GATEWAY_STARTUP_DEADLINE_SECONDS = 15.0
_GATEWAY_PROBE_TIMEOUT_SECONDS = 3.0
_GATEWAY_DIAGNOSTIC_BYTES = 4096


def _wait_for_gateway_readiness(process, probe, *, deadline, clock=time.monotonic, sleep=time.sleep):
    """Wait for the exact synthetic upstream response without hiding child exits."""
    while True:
        returncode = process.poll()
        if returncode is not None:
            return False, f"gateway child exited before readiness (returncode={returncode})"
        remaining = deadline - clock()
        if remaining <= 0:
            return False, "gateway readiness deadline expired"
        try:
            response = probe(min(_GATEWAY_PROBE_TIMEOUT_SECONDS, remaining))
        except OSError:
            response = None
        if response == (200, b"upstream"):
            return True, ""
        remaining = deadline - clock()
        if remaining <= 0:
            return False, "gateway readiness deadline expired"
        sleep(min(0.02, remaining))


def _bounded_redacted_output(raw, secret: bytes) -> str:
    if not isinstance(raw, bytes):
        raw = str(raw).encode()
    return raw.replace(secret, b"[redacted]")[:_GATEWAY_DIAGNOSTIC_BYTES].decode(
        errors="replace"
    )


def _finish_gateway_process(process, secret: bytes) -> tuple[int | None, str, str, str | None]:
    cleanup_error = None
    try:
        if process.poll() is None:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
    except Exception as error:  # pragma: no cover - only cleanup failures
        cleanup_error = f"gateway cleanup failed ({type(error).__name__})"
        stdout = stderr = b""
    return (
        process.poll(),
        _bounded_redacted_output(stdout, secret),
        _bounded_redacted_output(stderr, secret),
        cleanup_error,
    )


def test_gateway_admission_and_secret_boundary(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the owner gateway integration test")
    seen = []

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("X-Session-API-Key")))
            self.send_response(200)
            if self.path == f"/api/conversations/{cid}":
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"partial")
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            self.end_headers()
            self.wfile.write(b"upstream")

        def log_message(self, *args):
            pass

        def do_PATCH(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))) )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    key = tmp_path / "key"
    key.write_text("synthetic-private-key")
    key.chmod(0o600)
    cid = "12345678-1234-1234-1234-123456789abc"
    config = tmp_path / "config.json"
    config.write_text(json.dumps(dict(port=port, backend=f"http://127.0.0.1:{backend.server_port}",
                                     canvas=f"http://127.0.0.1:{backend.server_port}", keyFile=str(key),
                                     publicOrigin="https://owner.example:9443", ownerLogin="owner@example.test",
                                     conversationId=cid)))
    script = Path(__file__).resolve().parents[2] / "scripts/openhands_owner_gateway.mjs"
    process = subprocess.Popen([node, str(script), str(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def call(path, method="GET", body=None, timeout=3, **override):
        headers = {"Host": "owner.example:9443", "Tailscale-User-Login": "owner@example.test"}
        headers.update(override)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers)
            reply = conn.getresponse()
            return reply.status, reply.read()
        finally:
            conn.close()

    ready = False
    readiness_reason = "gateway readiness was not attempted"
    cleanup_error = None
    try:
        ready, readiness_reason = _wait_for_gateway_readiness(
            process,
            lambda timeout: call("/", timeout=timeout),
            deadline=time.monotonic() + _GATEWAY_STARTUP_DEADLINE_SECONDS,
        )
        if ready:
            seen.clear()
            assert call("/", **{"Tailscale-User-Login": ""})[0] == 403
            assert call("/", **{"Tailscale-User-Login": "someone@example.test"})[0] == 403
            assert call("/", Origin="https://evil.example")[0] == 403
            assert call("/", Host="other.example")[0] == 403
            assert call("/api/conversations/search?session_api_key=leak")[0] == 403
            assert call("/api/bash/execute_bash_command", "POST", Origin="https://owner.example:9443")[0] == 403
            assert call("/api/conversations", "POST", Origin="https://owner.example:9443")[0] == 403
            assert call(f"/api/conversations?ids={cid}&ids=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")[0] == 403
            assert call("/api/conversations?ids=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")[0] == 403
            assert call("/api/settings/secrets/private")[0] == 403
            assert call("/api/agent-profiles/private/secrets")[0] == 403
            assert call(f"/api/conversations/{cid}/run", "POST")[0] == 403
            assert seen == []
            assert call("/") == (200, b"upstream")
            assert seen[-1] == ("/", None)
            assert call("/api/conversations/search", **{"X-Session-API-Key": "attacker"}) == (200, b"upstream")
            assert seen[-1] == ("/api/conversations/search", "synthetic-private-key")
            assert call(f"/api/conversations?ids={cid}")[0] == 200
            assert call("/api/settings") == (200, b"upstream")
            assert seen[-1] == ("/api/settings", "synthetic-private-key")
            with pytest.raises((http.client.IncompleteRead, http.client.RemoteDisconnected)):
                call(f"/api/conversations/{cid}")
            assert call("/")[0] == 200
            preference = {"misc_settings_diff": {"app_preferences": {"user_consents_to_analytics": False}}}
            assert call("/api/settings", "PATCH", body=json.dumps(preference), Origin="https://owner.example:9443")[0] == 200
            preference["misc_settings_diff"]["app_preferences"]["user_consents_to_analytics"] = True
            assert call("/api/settings", "PATCH", body=json.dumps(preference), Origin="https://owner.example:9443")[0] == 403
            key.chmod(0o644)
            assert call("/api/conversations/search")[0] == 503
    finally:
        returncode, stdout, stderr, process_cleanup_error = _finish_gateway_process(
            process, b"synthetic-private-key"
        )
        cleanup_errors = [process_cleanup_error] if process_cleanup_error else []
        for cleanup_name, cleanup_action in (
            ("backend shutdown", backend.shutdown),
            ("backend close", backend.server_close),
            ("backend thread join", lambda: thread.join(timeout=5)),
        ):
            try:
                cleanup_action()
            except Exception as error:  # pragma: no cover - only cleanup failures
                cleanup_errors.append(f"{cleanup_name} failed ({type(error).__name__})")
        cleanup_error = "; ".join(cleanup_errors) or None
    if not ready:
        assert "synthetic-private-key" not in stdout + stderr
        pytest.fail(
            f"{readiness_reason}; returncode={returncode}; stderr={stderr!r}"
            + (f"; {cleanup_error}" if cleanup_error else "")
        )
    if cleanup_error:
        pytest.fail(cleanup_error)
    assert b"synthetic-private-key" not in stdout.encode() + stderr.encode()


def test_gateway_readiness_wait_admits_delayed_exact_response():
    now = [0.0]
    timeouts = []

    class Process:
        def poll(self):
            return None

    def probe(timeout):
        timeouts.append(timeout)
        now[0] = 2.1
        return 200, b"upstream"

    ready, reason = _wait_for_gateway_readiness(
        Process(), probe, deadline=15.0, clock=lambda: now[0], sleep=lambda _: None
    )
    assert ready is True
    assert reason == ""
    assert timeouts == [3.0]


def test_gateway_readiness_wait_reports_early_child_exit():
    probes = []

    class Process:
        def poll(self):
            return 17

    ready, reason = _wait_for_gateway_readiness(
        Process(), lambda timeout: probes.append(timeout), deadline=15.0, clock=lambda: 0.0
    )
    assert ready is False
    assert reason == "gateway child exited before readiness (returncode=17)"
    assert probes == []


def test_gateway_readiness_wait_stops_at_deadline():
    now = [0.0]
    timeouts = []

    class Process:
        def poll(self):
            return None

    def probe(timeout):
        timeouts.append(timeout)
        raise OSError("not ready")

    def sleep(duration):
        now[0] += duration

    ready, reason = _wait_for_gateway_readiness(
        Process(), probe, deadline=0.05, clock=lambda: now[0], sleep=sleep
    )
    assert ready is False
    assert reason == "gateway readiness deadline expired"
    assert timeouts
    assert max(timeouts) <= 0.05


def test_missing_identity_configuration_refuses():
    script = Path(__file__).resolve().parents[2] / "scripts/openhands_owner_gateway.mjs"
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    code = ("import {admitted} from " + json.dumps(script.as_uri()) + ";"
            "const req={method:'GET',url:'/',socket:{remoteAddress:'127.0.0.1'},headers:{host:'owner.example'}};"
            "if(admitted(req,{publicOrigin:'https://owner.example'}))process.exit(1);")
    subprocess.run([node, "--input-type=module", "-e", code], check=True)


@pytest.mark.parametrize("state", ["ended_with_container", "creating", "unknown", "created"])
@pytest.mark.parametrize("model,effort", [("gpt-6.1-terra", None), ("gpt-6.1-sol", "high")])
def test_endpoint_holder_generation_and_loss(tmp_path, state, model, effort):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    # The existing controller guard is separately qualified. This fixture exercises the real
    # gateway's child/pipe/generation/loss boundary with only that guard's engine substituted.
    package = tmp_path / "app/builderops"
    package.mkdir(parents=True)
    (tmp_path / "app/__init__.py").touch()
    (package / "__init__.py").touch()
    (package / "epic_workspace.py").write_text('''import contextlib,json,os,subprocess
from pathlib import Path
class Layout:
 def __init__(self,root,epic):self.root=root
def _load_state(l):return json.loads((l.root/'state.json').read_text())
def resolve_engine(engine,model):
 if engine!='codex' or model not in ('gpt-6.1-terra','gpt-6.1-sol'):raise ValueError('model')
 return engine,model
def resolve_effort(engine,model,effort):
 if model=='gpt-6.1-sol' and effort!='high':raise ValueError('effort')
def _conversation_bound(info,*args):return True
def verify_codex_subscription(*args):pass
def _http(method,port,key,path,body,timeout):
 c=json.loads((Path(__file__).parents[2]/'state.json').read_text())['issue_mappings']['6630']['conversation']
 return 200,{'agent':{'kind':'ACPAgent','acp_server':'codex','acp_model':c['model'],'acp_effort':c.get('effort')},'current_model_id':c['model'],'current_effort':c.get('effort')}
@contextlib.contextmanager
def _endpoint_session(l,*args):
 (l.root/'holder.pid').write_text(str(os.getpid()))
 yield 18840,'synthetic-private-key'
''')
    (tmp_path / "state.json").write_text(json.dumps({"issue_mappings": {"6630": {
        "worker": "owner-sandbox", "conversation": {"id": "12345678-1234-1234-1234-123456789abc",
        "engine": "codex", "model": model, "effort": effort, "status": state}}}}))
    script = Path(__file__).resolve().parents[2] / "scripts/openhands_owner_gateway.mjs"
    config = {"sandbox": True, "runner": str(tmp_path), "root": str(tmp_path), "sandboxEpic": 6630}
    code = "import {endpoint} from " + json.dumps(script.as_uri()) + ";import {readFileSync} from 'node:fs';"
    code += "const config=" + json.dumps(config) + ";"
    if state != "created":
        code += "try{await endpoint(config);process.exit(1)}catch{}"
    else:
        code += ("const binding=await endpoint(config);"
                 "await new Promise(resolve=>{binding.onLost(resolve);"
                 "process.kill(Number(readFileSync(config.root+'/holder.pid','utf8')),'SIGTERM')});"
                 "binding.release();binding.release();")
    subprocess.run([node, "--input-type=module", "-e", code], check=True, timeout=15, capture_output=True)
