"""Playwright browser test for Operator diagnostics overlay Ask roundtrip (#1758).

Verifies the Ask input round-trips through the /api/operator/ask proxy and
renders the runtime response in the overlay.

Guard: Playwright + system Chrome must be available. If not available in the
current environment, the test module is skipped (not failed). The test uses
fixture payloads and a local HTTP server — no live vault required.

Set COMPANION_UI_BROWSER_TESTS=1 to enable this test.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlparse

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set COMPANION_UI_BROWSER_TESTS=1 to run Playwright browser-runtime tests.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
except ImportError:
    pytest.skip(
        "playwright package not installed — skipping browser tests.",
        allow_module_level=True,
    )

from companion_ui.workspace.serve_dev_page import render_operator_overlay_html


pytestmark = pytest.mark.browser_runtime


# ---------------------------------------------------------------------------
# Fixture payloads
# ---------------------------------------------------------------------------

_STATUS_PAYLOAD: dict[str, Any] = {"sot_version": "v5.5", "stores": [], "ingestion": {}, "ask": {}}
_HEALTH_PAYLOAD: dict[str, Any] = {"ok": True, "checks": {}}
_SETTINGS_PAYLOAD: dict[str, Any] = {"ok": True, "issues": []}
_EVENTS_PAYLOAD: dict[str, Any] = {"events": []}

_ASK_RESPONSE: dict[str, Any] = {
    "answer": "The answer is 42.",
    "sources": [],
    "latency_ms": 120,
}


# ---------------------------------------------------------------------------
# Local HTTP server that serves the overlay + handles /api/operator/ask
# ---------------------------------------------------------------------------


def _make_server() -> tuple[HTTPServer, int]:
    """Create a local HTTP server serving the operator overlay and a mock ask endpoint."""

    overlay_html = render_operator_overlay_html(
        status_payload=_STATUS_PAYLOAD,
        health_payload=_HEALTH_PAYLOAD,
        settings_payload=_SETTINGS_PAYLOAD,
        events_payload=_EVENTS_PAYLOAD,
    ).encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return  # suppress server noise in test output

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = (
                    b"<!doctype html><html><head><meta charset='utf-8'>"
                    b"<style>:root{--bg-base:#070b12;--fg-1:#dce8f0;--bg-raised:#111a2e;"
                    b"--border:#152030;--amber:#f09030;--amber-muted:#1a0e02;"
                    b"--amber-dim:#805010;--vault:#39e87d;--border-focus:#00d4e8;"
                    b"--border-strong:#1e3050;--bg-surface:#0c1220;--cyan:#00d4e8;}"
                    b"body{background:var(--bg-base);color:var(--fg-1);padding:16px}</style></head>"
                    b"<body><div id='overlay-mount'></div>"
                    b"<script>"
                    b"fetch('/overlay').then(r=>r.text()).then(html=>{"
                    b"document.getElementById('overlay-mount').innerHTML=html;"
                    b"Array.from(document.querySelectorAll('#overlay-mount script')).forEach(s=>{"
                    b"var ns=document.createElement('script');"
                    b"ns.textContent=s.textContent;"
                    b"s.parentNode.replaceChild(ns,s);});"
                    b"});"
                    b"</script></body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/overlay":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(overlay_html)))
                self.end_headers()
                self.wfile.write(overlay_html)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/operator/ask":
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    length = 0
                self.rfile.read(length) if length else b"{}"
                # Echo back fixture answer regardless of question
                body = json.dumps(_ASK_RESPONSE).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    return server, server.server_address[1]


# ---------------------------------------------------------------------------
# test_ask_roundtrip_via_proxy
# ---------------------------------------------------------------------------


def test_ask_roundtrip_via_proxy() -> None:
    """The Ask input round-trips through /api/operator/ask and renders the
    runtime response in the overlay answer element.

    Uses Playwright + system Chrome, fixture payloads, no live vault.
    """
    server, port = _make_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="chrome")
            except Exception:
                # Fall back to bundled Chromium if system Chrome unavailable
                browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded")

                # Wait for overlay content to be loaded into the mount
                page.wait_for_selector('[data-testid="operator-ask-input"]', timeout=5000)

                # Fill in a question
                page.fill('[data-testid="operator-ask-input"]', "What is the answer?")

                # Click the Ask button
                page.click('[data-testid="operator-ask-btn"]')

                # Wait for the answer to appear (the button re-enables when done)
                page.wait_for_selector(
                    '[data-testid="operator-ask-btn"]:not([disabled])', timeout=5000
                )

                # Verify the answer text was rendered
                answer_text = page.text_content('[data-testid="operator-ask-answer"]')
                assert answer_text is not None
                assert "42" in answer_text, (
                    f"Expected fixture answer '42' in answer element, got: {answer_text!r}"
                )

            finally:
                browser.close()
    finally:
        server.shutdown()
