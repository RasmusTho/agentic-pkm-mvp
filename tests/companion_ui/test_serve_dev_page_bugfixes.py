"""Focused regressions for serve_dev_page render bugs (#2159, #2160, #2161, #2162)."""

from __future__ import annotations

import threading
from http.server import HTTPServer
from types import SimpleNamespace
from typing import Any

import httpx

from companion_ui.workspace.serve_dev_page import (
    _e,
    _is_remote_page_origin,
    make_handler,
    _render_orientation_resurface,
    _render_portrait_sheet,
    _render_workspace_breadcrumb,
)


class _RouteFallbackClient:
    def __init__(self) -> None:
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if url == "/api/companion/orientation":
            return {
                "scope": {"kind": "workspace", "artifact_ref": None, "vault_id": "dev"},
                "meta": {"freshness": "fresh", "degraded_reasons": []},
            }
        if url == "/api/companion/vault-browser":
            return {"notes": [], "total_notes": 0, "filtered_notes": 0, "read_only": True}
        return {}

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return {}


def _start_route_fallback_server() -> tuple[HTTPServer, int, _RouteFallbackClient]:
    client = _RouteFallbackClient()
    handler = make_handler(client=client, api_base_url="http://127.0.0.1:18001")
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, int(server.server_address[1]), client


def test_portrait_sheet_aria_hidden_lowercase() -> None:
    # #2159 — ARIA defines only lowercase true/false; a Python bool must not be
    # stringified to "True"/"False" (which assistive tech does not honor).
    hidden = _render_portrait_sheet({"is_visible": False})
    assert 'aria-hidden="true"' in hidden
    assert 'aria-hidden="True"' not in hidden
    assert 'aria-hidden="False"' not in hidden

    shown = _render_portrait_sheet({"is_visible": True})
    assert 'aria-hidden="false"' in shown
    assert 'aria-hidden="True"' not in shown
    assert 'aria-hidden="False"' not in shown


def test_breadcrumb_escapes_once() -> None:
    # #2160 — the incoming note_path is already HTML-escaped; the breadcrumb must
    # escape exactly once, not double-escape every non-ampersand metacharacter.
    note_path = _e("Today's plan.md")  # what the caller passes: "Today&#x27;s plan.md"
    html = _render_workspace_breadcrumb(
        note_path=note_path,
        artifact_id="",
        content_hash="",
        identity_state="",
        identity_source="",
        artifact_kind="",
        owns_identity=False,
        companion_html="",
        rendered_props=SimpleNamespace(fields=(), html=""),
    )
    assert "Today&#x27;s plan.md" in html
    # The bug rendered the literal "Today&amp;#x27;s plan.md" (double-escaped),
    # both in the visible breadcrumb and in data-note-path (read by JS as the
    # real path) — neither must double-escape.
    assert "Today&amp;#x27;s" not in html
    assert 'data-note-path="Today&#x27;s plan.md"' in html


def test_resurface_badge_counts_all_candidates() -> None:
    # #2161 — with more candidates than the display budget (3), the count badge
    # must show the full capped count, like the sibling sections, not just the
    # visible subset.
    resurface = {"candidates": [{"label": f"C{i}", "why_now": "x"} for i in range(5)]}
    html = _render_orientation_resurface(resurface)  # no caps -> no server cap

    assert '<span class="orientation-count">5</span>' in html
    assert '<span class="orientation-count">3</span>' not in html
    # The 2 beyond the budget are still offered as overflow.
    assert 'data-resurface-overflow-count="2"' in html


def test_bracketed_ipv6_loopback_with_port_is_local() -> None:
    # #2162 — a bracketed IPv6 loopback carrying a port must be recognized as
    # local, not misclassified as a remote origin.
    assert _is_remote_page_origin("[::1]:8111") is False
    assert _is_remote_page_origin("[::1]") is False
    assert _is_remote_page_origin("127.0.0.1:8111") is False
    assert _is_remote_page_origin("localhost:8111") is False
    assert _is_remote_page_origin("localhost") is False
    # Real remote hosts still classify as remote.
    assert _is_remote_page_origin("example.com") is True
    assert _is_remote_page_origin("example.com:443") is True
    assert _is_remote_page_origin("[2001:db8::1]:443") is True


def test_unknown_document_route_renders_controlled_fallback() -> None:
    server, port, client = _start_route_fallback_server()
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/definitely-not-a-route")
    finally:
        server.shutdown()

    assert response.status_code == 404
    assert "Unknown Companion UI route" in response.text
    assert 'data-testid="workspace-error-state"' in response.text
    assert 'data-error-kind="route-not-found"' in response.text
    assert 'data-entry-state="no_vault"' not in response.text
    assert 'data-testid="workspace-entry-retry"' not in response.text
    assert 'data-testid="vault-settings-panel"' not in response.text
    assert client.get_calls == []


def test_unknown_document_route_is_distinguishable_from_orientation() -> None:
    server, port, client = _start_route_fallback_server()
    try:
        unknown = httpx.get(f"http://127.0.0.1:{port}/definitely-not-a-route")
        root = httpx.get(f"http://127.0.0.1:{port}/")
        workspace = httpx.get(f"http://127.0.0.1:{port}/workspace?note_path=Some%2FNote.md")
    finally:
        server.shutdown()

    assert unknown.status_code == 404
    assert 'data-route-error="unknown-document-route"' in unknown.text
    assert root.status_code == 200
    assert "Unknown Companion UI route" not in root.text
    assert workspace.status_code == 200
    assert any(call == ("/api/companion/workspace", {"note_path": "Some/Note.md"}) for call in client.get_calls)
