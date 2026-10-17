"""Executable lost-ack/replay journeys for the CAL-03 card.

These tests intentionally run the rendered production card in Chromium.  The
local server drops the first POST response after recording the canonical
action, which proves that a transport failure cannot turn into a new choice or
an invented outcome.  They are opt-in with the repository's browser-runtime
switch because Chromium is not part of the ordinary unit-test environment.
"""

from __future__ import annotations

import json
import os
import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Iterator
from urllib.parse import urlparse

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set COMPANION_UI_BROWSER_TESTS=1 to run Companion browser-runtime tests.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    pytest.skip("playwright package not installed — skipping browser tests.", allow_module_level=True)

from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui.browser_runtime_harness import companion_workspace_fields


pytestmark = pytest.mark.browser_runtime


def _pending_surface() -> dict[str, Any]:
    return {
        "state": "pending",
        "decision_id": "decision-browser-1",
        "decision_object_id": "object-browser-1",
        "title": "Browser replay fixture",
        "decided_on": "2026-06-23",
        "rung_index": 0,
        "rung_days": 14,
        "degraded": False,
    }


@contextmanager
def _serve_card(*, canonical_intent: str) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    fields = companion_workspace_fields(body="# Browser replay fixture")
    fields.update(
        {
            "note_path": "Notes/browser-replay.md",
            "calibration_revisit": _pending_surface(),
        }
    )
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/browser-replay.md",
        fields=fields,
    ).encode("utf-8")
    posts: list[dict[str, Any]] = []
    dropped = False

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                payload = html
                content_type = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/companion/workspace":
                # Keep the browser in the terminal degraded branch after the
                # replay so the assertions observe the action response without
                # a navigation hiding it.
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                payload = b'{"error":"workspace_refresh_unavailable"}'
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            nonlocal dropped
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8") or "{}")
            posts.append(payload)
            if not dropped:
                dropped = True
                # The runtime has committed the action, but the browser sees
                # no acknowledgement.  The next request must be the exact
                # identity/payload replay, not a new choice.
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
            if canonical_intent == "answer":
                response = {
                    "status": "answered",
                    "decision_id": "decision-browser-1",
                    "rung_index": 0,
                    "receipt": {"outcome": "held"},
                }
            else:
                response = {
                    "status": "dismissed",
                    "decision_id": "decision-browser-1",
                    "rung_index": 0,
                    "receipt": None,
                }
            encoded = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/", posts
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _launch(playwright: Any, url: str) -> tuple[Any, Any]:
    try:
        browser = playwright.chromium.launch()
    except Exception as exc:  # pragma: no cover - host dependency
        if "Executable doesn't exist" in str(exc):
            pytest.skip("Playwright Chromium executable is not installed.")
        raise
    context = browser.new_context()
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    page.locator('[data-testid="calibration-revisit-card"]').wait_for()
    return browser, page


def test_answer_lost_ack_reconciles_same_payload_and_canonical_outcome() -> None:
    with _serve_card(canonical_intent="answer") as (url, posts), sync_playwright() as playwright:
        browser, page = _launch(playwright, url)
        try:
            page.locator('[data-outcome="held"]').click()
            page.locator('[data-calibration-reconcile]').wait_for(state="visible")
            assert page.locator('[data-calibration-feedback]').get_attribute("data-failure") == "uncertain"
            assert page.locator('[data-outcome="did_not_hold"]').is_disabled()

            # A stale/different answer event must be reconciled as the original
            # held action, never submitted as a fresh did_not_hold mutation.
            page.locator('form[data-intent="answer"]').evaluate(
                """form => {
                    const button = form.querySelector('[data-outcome="did_not_hold"]');
                    form.dispatchEvent(new SubmitEvent('submit', {bubbles: true, cancelable: true, submitter: button}));
                }"""
            )
            page.locator('[data-state="answered"]').wait_for()
            assert len(posts) == 2
            assert posts[0]["outcome"] == "held"
            assert posts[1]["outcome"] == "held"
            card = page.locator('[data-testid="calibration-revisit-card"]')
            assert card.get_attribute("data-outcome") == "held"
            assert "Nothing durable happened" not in (page.locator('[data-calibration-feedback]').text_content() or "")
        finally:
            browser.close()


def test_dismiss_lost_ack_reconciles_same_identity_without_outcome() -> None:
    with _serve_card(canonical_intent="dismiss") as (url, posts), sync_playwright() as playwright:
        browser, page = _launch(playwright, url)
        try:
            page.locator('[data-intent="dismiss"] button[type="submit"]').click()
            page.locator('[data-calibration-reconcile]').wait_for(state="visible")
            page.locator('[data-calibration-reconcile]').click()
            page.locator('[data-state="dismissed"]').wait_for()
            assert len(posts) == 2
            assert posts[0] == posts[1]
            assert "outcome" not in posts[0]
            card = page.locator('[data-testid="calibration-revisit-card"]')
            assert card.get_attribute("data-outcome") in (None, "")
            assert "Nothing durable happened" not in (page.locator('[data-calibration-feedback]').text_content() or "")
        finally:
            browser.close()
