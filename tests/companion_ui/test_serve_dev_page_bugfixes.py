"""Focused regressions for serve_dev_page render bugs (#2159, #2160, #2161, #2162, #2288)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Thread
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

from companion_ui.workspace.serve_dev_page import (
    CompanionThreadingHTTPServer,
    _e,
    _is_remote_page_origin,
    _render_orientation_resurface,
    _render_portrait_sheet,
    _render_workspace_breadcrumb,
    make_handler,
)


class _RouteTestClient:
    def get(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        if path == "/api/companion/orientation":
            return {
                "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
                "meta": {
                    "contract_version": "workspace_orientation.v1",
                    "as_of": "2026-06-20T12:00:00+00:00",
                    "trace_id": "route-regression-trace",
                    "freshness": "fresh",
                    "degraded_reasons": [],
                },
                "leave_point": {"status": "absent"},
                "open_loops": [],
                "notable_changes": [],
                "resurface": {"candidates": []},
                "governance": {
                    "pending_proposal_count": 0,
                    "pending_receipt_count": 0,
                    "latest_receipt_outcome": None,
                    "authority_role": "derived",
                    "source_ref": {
                        "kind": "runtime_signal",
                        "ref": "gov",
                        "label": "governance",
                    },
                },
                "guards": {
                    "read_only": True,
                    "runtime_posture": "healthy",
                    "degraded": False,
                    "reasons": [],
                    "authority_role": "derived",
                    "source_ref": {"kind": "status", "ref": "status", "label": "status"},
                },
                "mutation_intents": [],
            }
        if path == "/api/companion/workspace":
            note_path = params.get("note_path") or "Notes/deep-link.md"
            return {
                "artifact": {
                    "artifact_id": "route-regression-note",
                    "note_path": note_path,
                    "title": "Deep Link Note",
                    "body": "# Deep Link Note\n\nBody.",
                    "content_hash": "sha256-route-regression",
                },
                "canvas": {},
                "panel": {},
                "suggestions": {},
                "guards": {},
                "runtime": {},
            }
        raise AssertionError(f"unexpected route test client GET: {path} {params}")


@contextmanager
def _route_test_server() -> Iterator[str]:
    handler = make_handler(
        client=_RouteTestClient(),  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )
    server = CompanionThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _fetch(base_url: str, path: str) -> tuple[int, str, str]:
    try:
        with urlopen(f"{base_url}{path}", timeout=5.0) as response:
            body = response.read().decode("utf-8")
            return response.status, response.headers.get("Content-Type", ""), body
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, exc.headers.get("Content-Type", ""), body


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
    # #2288 — unknown document routes must not silently render the normal
    # orientation entry page.
    with _route_test_server() as base_url:
        status, content_type, body = _fetch(base_url, "/definitely-not-a-route")

    assert status == 404
    assert content_type.startswith("text/html")
    assert 'data-testid="workspace-route-not-found-state"' in body
    assert 'data-route-error="unknown_document_route"' in body
    assert "Companion UI route not found" in body


def test_unknown_document_route_is_distinguishable_from_orientation() -> None:
    # The invalid-route response must carry its own route-error marker and
    # status, while the real root entry route remains the orientation page.
    with _route_test_server() as base_url:
        unknown_status, _unknown_content_type, unknown_body = _fetch(
            base_url, "/definitely-not-a-route?note_path=Notes%2Fdeep-link.md"
        )
        root_status, _root_content_type, root_body = _fetch(base_url, "/")

    assert unknown_status == 404
    assert 'data-route-error="unknown_document_route"' in unknown_body
    assert "Workspace Orientation" not in unknown_body
    assert 'data-entry-state="' not in unknown_body

    assert root_status == 200
    assert "Workspace Orientation" in root_body
    assert 'data-entry-state="' in root_body
