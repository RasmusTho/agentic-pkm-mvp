"""Real HTTP, Companion gateway and external SDK stdio-client test boundaries."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from queue import Queue
import sys
from threading import Thread

import httpx
from starlette.requests import Request

from app.api.operation_runtime import build_production_operation_runtime
from app.operations.contracts import OperationContext, OperationRequest
from tests.companion_ui.test_operations_workspace import gateway

SIDECAR = Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"
META_SESSION = "mimer/active-context-session"
META_OVERRIDE = "mimer/active-context-override"


def direct(host, command):
    """Invoke the production application boundary with real host composition."""
    request = Request({"type": "http", "method": "POST", "path": "/api/operations",
        "headers": [(key.lower().encode(), value.encode()) for key, value in host.headers.items()],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000), "scheme": "http", "query_string": b""})
    operation = OperationRequest(command["operation_id"], command["request_id"],
        OperationContext(command["active_context_ref"], command["vault_generation"]),
        targets=tuple(command.get("targets", ())), arguments=command.get("arguments", {}),
        expected_version=command.get("expected_version"))
    runtime = build_production_operation_runtime(request, api_key=None,
        session_bearer=host.headers.get("X-Active-Context-Session"), override_bearer=None,
        operation=operation, target_binding_id=command.get("target_binding_id"))
    # Compare the complete native JSON value across transport surfaces, not
    # Python-only tuple/list representation in opaque dataclass receipts.
    return json.loads(json.dumps(runtime.invoke(operation).to_dict(), allow_nan=False))


@contextmanager
def runtime_http(host):
    """Only the socket transport is bridged; all request owners remain real."""
    class RecordedCalls(list):
        def __init__(self):
            super().__init__()
            self.header_names = []

    calls = RecordedCalls()
    disconnect = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _forward(self, method):
            body = self.rfile.read(int(self.headers.get("content-length", "0"))) if method in {"POST", "PUT", "DELETE"} else None
            headers = {key: value for key, value in self.headers.items() if key.lower() in {
                "content-type", "x-active-context-session", "x-active-context-override", "x-trace-id"}}
            # Observe the actual socket boundary before the test bridge's
            # native-header allowlist, retaining names only, never bearers.
            calls.header_names.append(frozenset(key.lower() for key in self.headers.keys()))
            calls.append((method, self.path))
            response = host.client.request(method, self.path, content=body, headers=headers)
            if disconnect and self.path == disconnect[0]:
                disconnect.pop(0)
                self.close_connection = True
                return
            self.send_response(response.status_code)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(response.content)

        def do_GET(self):
            self._forward("GET")

        def do_POST(self):
            self._forward("POST")

        def do_PUT(self):
            self._forward("PUT")

        def do_DELETE(self):
            self._forward("DELETE")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, disconnect
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


class ExternalMcpClient:
    """Official external MCP SDK, with its stdio lifetime owned by one task."""
    def __init__(self, url, headers, *, profile="v2"):
        self.url, self.profile = url, profile
        self.meta = {META_SESSION: headers["X-Active-Context-Session"]} if headers else {}
        self.queue = Queue()
        self.ready = Future()

    async def _run(self):
        try:
            from mcp import ClientSession, types
            from mcp.client.stdio import StdioServerParameters, stdio_client

            parameters = StdioServerParameters(command=sys.executable,
                args=["-m", "mimer_mcp_sidecar", "--base-url", self.url, "--profile", self.profile],
                env={**os.environ, "PYTHONPATH": str(SIDECAR)})
            async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as session:
                initialized = await session.initialize()
                self.ready.set_result(initialized)
                while True:
                    item = await asyncio.to_thread(self.queue.get)
                    if item is None:
                        break
                    method, name, arguments, result = item
                    try:
                        if method == "list":
                            response = await session.list_tools(params=types.PaginatedRequestParams(_meta=self.meta))
                        elif method == "resources":
                            response = await session.list_resources(params=types.PaginatedRequestParams(_meta=self.meta))
                        else:
                            response = await session.call_tool(name, arguments, meta=self.meta)
                        result.set_result(response)
                    except Exception as exc:
                        result.set_exception(exc)
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            else:
                self.failure = exc

    def __enter__(self):
        self.thread = Thread(target=lambda: asyncio.run(self._run()), daemon=True)
        self.thread.start()
        self.initialized = self.ready.result(20)
        return self

    def _request(self, method, name=None, arguments=None):
        result = Future()
        self.queue.put((method, name, arguments, result))
        return result.result(30)

    def tools(self):
        return self._request("list").tools

    def call(self, name, arguments=None):
        return self._request("call", name, arguments or {})

    def payload(self, name, arguments=None):
        response = self.call(name, arguments)
        assert not response.isError, response
        return response.structuredContent

    def __exit__(self, *_):
        self.queue.put(None)
        self.thread.join(10)
        assert not self.thread.is_alive(), "external MCP client did not release its child"
        if hasattr(self, "failure"):
            raise self.failure


@contextmanager
def companion_http(host):
    with gateway(host) as (url, forwarded), httpx.Client(base_url=url) as client:
        client.cookies.set("companion_context_session", host.selection["context_selection_id"])
        yield client, forwarded


def _native_request(host):
    return Request({'type': 'http', 'method': 'POST', 'path': '/api/operations',
        'headers': [(key.lower().encode(), value.encode()) for key, value in host.headers.items()],
        'client': ('127.0.0.1', 12345), 'server': ('127.0.0.1', 8000), 'scheme': 'http', 'query_string': b''})


def direct_batch(host, action, command):
    from app.api.batch_operation_runtime import build_production_batch_runtime
    runtime = build_production_batch_runtime(_native_request(host), api_key=None,
        session_bearer=host.headers['X-Active-Context-Session'], override_bearer=None)
    if action == 'preview':
        context = OperationContext(command['active_context_ref'], command['vault_generation'])
        items = tuple(OperationRequest(command['operation_id'], item['request_id'], context,
            targets=({'artifact_id': item['artifact_id']},), arguments=item['arguments'],
            expected_version=item['expected_version']) for item in command['items'])
        return runtime.preview(command['batch_id'], items, target_binding_id=command['target_binding_id'],
            limit=command.get('limit', 100), partial_success_policy=command.get('partial_success_policy', 'independent'))
    return getattr(runtime, action)(command['batch_id'], expected_digest=command['expected_digest'])


class SurfaceCalls:
    def __init__(self, host, companion, mcp, initiator):
        self.host, self.companion, self.mcp, self.initiator = host, companion, mcp, initiator

    def operation(self, command):
        if self.initiator == 'direct':
            return direct(self.host, command)
        if self.initiator == 'mcp':
            return self.mcp.payload('mimer.v2.' + command['operation_id'], command)
        response = (self.host.client.post('/api/operations', headers=self.host.headers, json=command)
                    if self.initiator == 'http' else self.companion.post('/api/operations', json=command))
        assert response.status_code == 200, response.text
        return response.json()

    def batch(self, action, command):
        if self.initiator == 'direct':
            return direct_batch(self.host, action, command)
        if self.initiator == 'mcp':
            return self.mcp.payload('mimer.v2.batch.' + action, command)
        path = '/api/operations/batches/' + ('preview' if action == 'preview' else command['batch_id'])
        body = command if action == 'preview' else {'expected_digest': command['expected_digest']}
        if action not in {'preview', 'inspect'}:
            path += '/' + action
        client = self.host.client if self.initiator == 'http' else self.companion
        headers = self.host.headers if self.initiator == 'http' else {}
        response = client.get(path, params=body, headers=headers) if action == 'inspect' else client.post(path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()
