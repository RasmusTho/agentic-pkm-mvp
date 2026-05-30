"""Thin Playwright harness helpers for Companion UI runtime tests."""

from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Iterator
from urllib.parse import urlparse

from companion_ui.workspace.serve_dev_page import render_index_html


_VENDOR_DIR = Path(__file__).resolve().parent / "fixtures" / "browser_vendor"
_ESM_STUBS = {
    "https://esm.sh/mermaid@10.9.1": _VENDOR_DIR / "mermaid_10_9_1.mjs",
    "https://esm.sh/codemirror@6.0.1": _VENDOR_DIR / "codemirror_6_0_1.mjs",
    "https://esm.sh/@codemirror/lang-markdown@6.2.5": _VENDOR_DIR
    / "codemirror_lang_markdown_6_2_5.mjs",
    "https://esm.sh/@codemirror/theme-one-dark@6.1.2": _VENDOR_DIR
    / "codemirror_theme_one_dark_6_1_2.mjs",
}


def companion_workspace_fields(*, body: str) -> dict:
    """Return the minimal workspace payload consumed by render_index_html."""

    return {
        "title": "Mermaid Browser Runtime",
        "note_path": "Notes/mermaid-browser-runtime.md",
        "artifact_id": "art-browser-runtime-001",
        "content_hash": "sha256-browser-runtime",
        "body": body,
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": False,
        "guard_update_flow_available": False,
        "runtime_vault_provenance": "resolved",
        "runtime_vault_name": "BrowserTestVault",
        "runtime_vault_channel": "test",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_proposals": [],
        "panel_message": "",
        "find_candidates": [],
        "reorient_sections": None,
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }


@contextmanager
def serve_rendered_workspace(body: str) -> Iterator[str]:
    """Serve render_index_html output on localhost for a browser test."""

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/mermaid-browser-runtime.md",
        fields=companion_workspace_fields(body=body),
    ).encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def install_offline_esm_routes(context: object) -> list[str]:
    """Route browser module imports to repo-local stubs and record leaks."""

    unexpected_external_requests: list[str] = []

    def route_request(route: object) -> None:
        request = route.request
        url = request.url
        parsed = urlparse(url)
        cache_key = url.split("?", 1)[0]
        if parsed.scheme == "http" and parsed.hostname == "127.0.0.1":
            route.continue_()
            return
        if cache_key in _ESM_STUBS:
            route.fulfill(
                status=200,
                content_type="text/javascript; charset=utf-8",
                body=_ESM_STUBS[cache_key].read_text(encoding="utf-8"),
            )
            return
        if parsed.scheme == "https" and parsed.hostname == "fonts.googleapis.com":
            route.fulfill(status=200, content_type="text/css; charset=utf-8", body="")
            return
        if parsed.scheme == "https" and parsed.hostname == "fonts.gstatic.com":
            route.fulfill(status=200, content_type="font/woff2", body=b"")
            return
        unexpected_external_requests.append(url)
        route.abort()

    context.route("**/*", route_request)
    return unexpected_external_requests
