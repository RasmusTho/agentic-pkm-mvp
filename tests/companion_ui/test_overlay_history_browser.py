"""Playwright browser smoke for overlay↔browser-history (NAV-3, #2611).

The NAV-3 contract is a real browser behaviour a pure-Python render test
cannot exercise: ``overlayHost.mount`` pushes a history entry, and browser
**Back** fires ``popstate`` which dismisses the TOPMOST overlay (popping one
history entry) instead of navigating the page away. Esc and the scrim must
still dismiss to the document anchor, and ``?overlay=`` deep-links auto-mount
on load.

This smoke renders the real workspace shell (``render_index_html``) over a
local HTTP server and drives the shared overlay host through Playwright. It
asserts the host's authoritative bookkeeping (``data-overlay-open`` /
``data-overlay-stack`` on ``[data-region="overlay-host"]``) — the single
source of truth for which overlay is mounted — plus URL invariance:

  open overlay → browser Back closes THAT overlay (URL unchanged) →
  Esc dismisses → scrim dismisses → ?overlay= deep-link auto-mounts.

Guard: Playwright + a Chromium/Chrome must be available; otherwise the module
is skipped (not failed). Enable via COMPANION_UI_BROWSER_TESTS=1. Deterministic
and fully offline (rendered HTML; no live vault). ``memory`` is a declared +
shipped occupant whose registration ships with the rendered shell, so the host
has a real mount target without any test stub.
"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

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

from companion_ui.workspace.serve_dev_page import render_index_html

pytestmark = pytest.mark.browser_runtime


# ---------------------------------------------------------------------------
# Minimal loaded-note fields (mirror test_overlay_host's _fields)
# ---------------------------------------------------------------------------

_FIELDS: dict[str, Any] = {
    "title": "Note Title",
    "note_path": "Notes/note.md",
    "artifact_id": "art-123",
    "artifact_kind": "human_note",
    "artifact_identity_source": "frontmatter.uuid",
    "artifact_identity_state": "resolved",
    "artifact_companion_of": None,
    "artifact_owns_identity": True,
    "content_hash": "sha256-aaa",
    "body": "# Note\n\nBody paragraph.",
    "panel_rail": "Panel / agent rail placeholder",
    "runtime_environment_label": "dev",
    "runtime_api_base_url_label": "local-dev",
    "runtime_trace_id": "trace-1",
    "runtime_vault_name": "vault/dev",
    "runtime_vault_channel": "local-dev",
    "runtime_vault_provenance": "resolved",
    "canvas_session_state": "idle",
    "canvas_session_persistence": "durable",
    "panel_state": "idle",
    "panel_proposal_count": 0,
    "panel_proposals": [],
    "panel_message": "",
    "guard_writeguard_status": "ok",
    "guard_canvas_enabled": True,
    "guard_degraded": False,
    "guard_workspace_update_available": True,
    "guard_update_flow_available": True,
    "find_candidates": [],
    "find_payload_available": False,
    "reorient_sections": {},
    "resurface_candidates": [],
    "governance_receipts": [],
    "suggestion_state": "idle",
    "suggestion_composer_enabled": True,
    "is_production_ui": False,
    "dev_page_label": "dev/staging",
    "workspace_loaded_at": None,
}

# Host bookkeeping read helpers (the host element is the single source of truth
# for which overlay is open / what the full stack is; the host element is
# display:none until something mounts).
_OPEN_JS = (
    "document.querySelector('[data-region=\\'overlay-host\\']')"
    ".getAttribute('data-overlay-open')"
)
_STACK_JS = (
    "document.querySelector('[data-region=\\'overlay-host\\']')"
    ".getAttribute('data-overlay-stack')"
)


def _page_html(boot_overlay: str = "") -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=dict(_FIELDS),
        boot_overlay=boot_overlay,
    )


def _make_server() -> tuple[HTTPServer, int]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                qs = parse_qs(parsed.query)
                boot = qs.get("overlay", [""])[0]
                body = _page_html(boot).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                # Calmly satisfy any same-origin asset/API probe the shell makes.
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    return server, server.server_address[1]


def _launch(pw: Any) -> Any:
    try:
        return pw.chromium.launch(channel="chrome")
    except Exception:
        return pw.chromium.launch()


def _wait_open(page: Any, value: str) -> None:
    page.wait_for_function(f"{_OPEN_JS} === '{value}'", timeout=5000)


def _wait_stack(page: Any, value: str) -> None:
    page.wait_for_function(f"{_STACK_JS} === '{value}'", timeout=5000)


def test_browser_back_closes_topmost_overlay_then_esc_and_scrim() -> None:
    """open overlay → browser Back closes it (page stays) → Esc & scrim dismiss."""
    server, port = _make_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}/"
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            try:
                page = browser.new_page()
                page.goto(base, wait_until="domcontentloaded")
                # The host element is display:none until an overlay mounts, so
                # wait for it to be ATTACHED (not visible).
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                start_url = page.url

                # Nothing mounted initially.
                assert page.evaluate(_OPEN_JS) == "none"

                # Open the overlay via the host API → pushes a history entry and
                # records the overlay as topmost in the host bookkeeping.
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")

                # Browser Back closes THAT overlay (popstate → dismiss topmost),
                # returning to the document anchor, and does NOT navigate away.
                page.go_back()
                _wait_open(page, "none")
                assert page.url == start_url, "Back must not navigate the page away"

                # Esc still dismisses: mount again, press Escape.
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")
                page.keyboard.press("Escape")
                _wait_open(page, "none")
                assert page.url == start_url, "Esc must not navigate the page away"

                # Scrim still dismisses: mount again, click the scrim.
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")
                page.evaluate(
                    "document.getElementById('workspace-overlay-scrim').click()"
                )
                _wait_open(page, "none")
                assert page.url == start_url, "scrim must not navigate the page away"

                # Stacked: two overlays, Back closes only the topmost (one entry
                # per mount). memory then cmd; Back leaves memory mounted and the
                # stack consistent.
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")
                page.evaluate("window.overlayHost.mount('cmd')")
                _wait_stack(page, "memory cmd")
                page.go_back()
                _wait_open(page, "memory")  # only the topmost (cmd) was popped
                _wait_stack(page, "memory")
                assert page.url == start_url
                # Clean up: Back again returns fully to the anchor.
                page.go_back()
                _wait_open(page, "none")
            finally:
                browser.close()
    finally:
        server.shutdown()


def test_browser_forward_restores_overlay_and_stack_stays_correct() -> None:
    """Codex P2 (popstate must reconcile to history position):

    - single overlay: Back closes it, Forward RESTORES it (not a blind pop);
    - 2-overlay stack: Back then Forward leaves the CORRECT overlay open and
      ``data-overlay-stack`` consistent — never closes/restores the wrong one.
    No page navigation throughout.
    """
    server, port = _make_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}/"
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            try:
                page = browser.new_page()
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                start_url = page.url
                assert page.evaluate(_OPEN_JS) == "none"

                # Single overlay: open → Back closes → Forward restores it.
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")
                page.go_back()
                _wait_open(page, "none")
                assert page.url == start_url
                page.go_forward()
                _wait_open(page, "memory")  # RESTORED, not a different overlay
                _wait_stack(page, "memory")
                assert page.url == start_url, "Forward must not navigate the page away"

                # Back to a clean anchor for the stacked case.
                page.go_back()
                _wait_open(page, "none")

                # 2-overlay stack: memory then cmd. Back drops cmd (memory left).
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")
                page.evaluate("window.overlayHost.mount('cmd')")
                _wait_stack(page, "memory cmd")
                page.go_back()
                _wait_open(page, "memory")  # only the topmost (cmd) closed
                _wait_stack(page, "memory")
                # Forward restores cmd ON TOP of memory — the correct overlay,
                # stack consistent (never restores the wrong one).
                page.go_forward()
                _wait_open(page, "cmd")
                _wait_stack(page, "memory cmd")
                assert page.url == start_url, "Forward must not navigate the page away"
            finally:
                browser.close()
    finally:
        server.shutdown()


def test_overlay_query_param_auto_mounts_on_load() -> None:
    """?overlay=memory auto-mounts the declared+shipped overlay on load."""
    server, port = _make_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}/?overlay=memory"
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            try:
                page = browser.new_page()
                page.goto(base, wait_until="domcontentloaded")
                _wait_open(page, "memory")
            finally:
                browser.close()
    finally:
        server.shutdown()
