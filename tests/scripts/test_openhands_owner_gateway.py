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

    def call(path, method="GET", body=None, **override):
        headers = {"Host": "owner.example:9443", "Tailscale-User-Login": "owner@example.test"}
        headers.update(override)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers)
            reply = conn.getresponse()
            return reply.status, reply.read()
        finally:
            conn.close()

    try:
        for _ in range(100):
            try:
                call("/")
                break
            except OSError:
                time.sleep(.02)
        else:
            pytest.fail("gateway failed to start")
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
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
    assert b"synthetic-private-key" not in stdout + stderr


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
def test_endpoint_holder_generation_and_loss(tmp_path, state):
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
@contextlib.contextmanager
def _endpoint_session(l,*args):
 (l.root/'holder.pid').write_text(str(os.getpid()))
 yield 18840,'synthetic-private-key'
''')
    (tmp_path / "state.json").write_text(json.dumps({"issue_mappings": {"6630": {
        "worker": "owner-sandbox", "conversation": {"id": "12345678-1234-1234-1234-123456789abc",
        "engine": "codex", "model": "gpt-6.1-terra", "status": state}}}}))
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
