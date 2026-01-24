from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.llm import embeddings


class _RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.last_path = self.path
        self.server.last_body = body

        entry = self.server.responses.get(self.path)
        if entry is None:
            status, payload = 404, {"error": "not found"}
        else:
            status, payload = entry

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if isinstance(payload, dict):
            payload = json.dumps(payload).encode("utf-8")
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


def _start_server(responses: dict[str, tuple[int, dict]]) -> tuple[HTTPServer, threading.Thread]:
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.responses = responses
    server.last_path = None
    server.last_body = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server: HTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)


def test_ollama_embeddings_hits_native_path(monkeypatch) -> None:
    responses = {
        "/api/embeddings": (200, {"embeddings": [[1.0, 2.0, 3.0]]}),
    }
    server, thread = _start_server(responses)
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        monkeypatch.setattr(embeddings, "OLLAMA_URL", base_url)
        embeddings._embed_single.cache_clear()
        vector = embeddings.embed_text("server-path", provider="ollama", model="test", dim=3, normalize=False)

        assert vector == [1.0, 2.0, 3.0]
        assert server.last_path == "/api/embeddings"

        payload = json.loads(server.last_body.decode("utf-8"))
        assert payload["model"] == "test"
        assert payload["prompt"] == "server-path"
    finally:
        _stop_server(server, thread)


def test_ollama_embeddings_404_reports_actionable_error(monkeypatch) -> None:
    responses = {
        "/api/embeddings": (404, {"error": "model \"nomic-embed-text:latest\" not found, try pulling it first"}),
        "/v1/embeddings": (404, {"error": {"message": "model \"nomic-embed-text:latest\" not found, try pulling it first"}}),
    }
    server, thread = _start_server(responses)
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        monkeypatch.setattr(embeddings, "OLLAMA_URL", base_url)
        embeddings._embed_single.cache_clear()

        with pytest.raises(RuntimeError) as excinfo:
            embeddings.embed_text("server-missing", provider="ollama", model="test", dim=3, normalize=False)

        message = str(excinfo.value)
        assert "Ollama embedding requests failed" in message
        assert "HTTP 404" in message
        assert "try pulling it first" in message
    finally:
        _stop_server(server, thread)
