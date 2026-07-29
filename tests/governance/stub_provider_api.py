"""Loopback provider API stub for end-to-end launcher tests.

The stub is reached exactly the way production reaches a provider: through the
declared `api_endpoint` in a census the test points `PROVIDER_CENSUS_PATH` at.
No test-only override exists in the resolver, the adapters, or the launcher.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Iterator

import yaml

RESPONSE_SCHEMA_VERSION = "builderops.model-turn-response.v1"


def _role_response(role: str, request: dict[str, Any]) -> dict[str, Any]:
    reviewed = request.get("reviewed_artifact_refs") or []
    if reviewed:
        return {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "stance": "accept",
            "content": f"{role} accepts the shared artifact",
            "claims": ["shared contract is coherent"],
            "risks": [],
            "blocking_questions": [],
            "reviewed_artifact_refs": list(reviewed),
            "accepted_artifact_hash": request["input_artifacts"][0]["artifact_hash"],
        }
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "stance": "draft",
        "content": f"{role} independent draft",
        "claims": [f"{role} claim"],
        "risks": [],
        "blocking_questions": [],
        "reviewed_artifact_refs": [],
        "accepted_artifact_hash": None,
    }


class _Handler(BaseHTTPRequestHandler):
    failing_paths: frozenset[str] = frozenset()

    def log_message(self, *_args: Any) -> None:
        return None

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path in self.failing_paths:
            payload = json.dumps({"error": "credential-sentinel"}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        anthropic = "x-api-key" in {key.lower() for key in self.headers}
        role = "fable" if anthropic else "gpt_codex"
        request = json.loads(body["messages"][-1]["content"])
        text = json.dumps(_role_response(role, request))
        if anthropic:
            payload_body: dict[str, Any] = {
                "id": "req_stub_anthropic",
                "content": [{"type": "text", "text": text}],
            }
        else:
            payload_body = {
                "id": "resp_stub_openai",
                "choices": [{"message": {"content": text}}],
            }
        payload = json.dumps(payload_body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def stub_provider_api(
    directory: Path,
    *,
    failing_roles: tuple[str, ...] = (),
) -> Iterator[Path]:
    """Serve both provider shapes on loopback and yield a census pointing at it."""
    handler = type(
        "_ScopedHandler",
        (_Handler,),
        {
            "failing_paths": frozenset(
                {"/anthropic"} if "fable" in failing_roles else set()
            )
            | frozenset({"/openai"} if "gpt_codex" in failing_roles else set())
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        base = f"http://{host}:{port}"
        census_path = census_with_stub_endpoints(directory, base)
        yield census_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def census_with_stub_endpoints(directory: Path, base_url: str) -> Path:
    """Write a census whose declared provider endpoints resolve to the stub."""
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / "docs" / "settings" / "models" / "providers.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    for provider in payload["providers"]:
        if provider["id"] == "anthropic":
            provider["api_endpoint"] = f"{base_url}/anthropic"
        elif provider["id"] == "openai":
            provider["api_endpoint"] = f"{base_url}/openai"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "providers.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path
