"""Playwright browser smoke for overlay↔browser-history (NAV-3a #2639, NAV-3b #2640).

The NAV-3 core contract is real browser behaviour a pure-Python render test
cannot exercise: ``overlayHost.mount`` pushes a same-document history entry,
and browser **Back** fires ``popstate`` which reconciles the overlay stack —
closing the TOPMOST overlay (popping one history entry) instead of navigating
the page away; **Forward** restores the marked overlay. The URL path and query
never change.

This smoke renders the real workspace shell (``render_index_html``) over a
local HTTP server and drives the shared overlay host through Playwright. It
asserts the host's authoritative bookkeeping (``data-overlay-open`` /
``data-overlay-stack`` on ``[data-region="overlay-host"]`` — the single source
of truth for which overlay is mounted) plus URL invariance:

  single: open overlay → browser Back closes it (URL unchanged);
  stacked: open 2 → Back closes the topmost → Forward restores it
           (``data-overlay-stack`` consistent, never the wrong overlay,
           no navigation);
  System Map route (NAV-3b): open the map → click a node that routes to another
           overlay → the destination is open and the map is closed → one
           browser Back closes the destination (no extra/dead press, no
           navigate-away), ``data-overlay-stack`` consistent throughout.

Scope: NAV-3a (#2639) is the CORE overlay↔history mechanism (single + stacked);
NAV-3b (#2640) adds the System Map route swap (``overlayHost.replace`` —
``dismiss→mount`` would race history and desync the stack). The ``?overlay=``
deep-link is #2641 (NAV-3c) and IS exercised here by the deep-link auto-mount
smoke at the bottom (a query-honoring server that threads ``boot_overlay``);
the NAV-3a/3b smokes above render the shell without any ``boot_overlay``
threading, so their only history entries are the ones the host itself creates.

Guard: Playwright + a Chromium/Chrome must be available; otherwise the module
is skipped (not failed). Enable via COMPANION_UI_BROWSER_TESTS=1. Deterministic
and fully offline (rendered HTML; no live vault). ``memory`` and ``cmd`` are
declared + shipped occupants whose registration ships with the rendered shell,
so the host has real mount targets without any test stub.
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


def _page_html() -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=dict(_FIELDS),
    )


def _make_server() -> tuple[HTTPServer, int]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/?"):
                body = _page_html().encode("utf-8")
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


def test_browser_back_closes_single_overlay_url_unchanged() -> None:
    """Single overlay: open → browser Back closes it (page stays, URL unchanged).

    Esc and the scrim still dismiss to the document anchor without navigating
    (the dismiss grammar is preserved alongside the new history mechanism).
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
            finally:
                browser.close()
    finally:
        server.shutdown()


def test_browser_back_then_forward_restores_topmost_on_stack() -> None:
    """Stacked overlays (2): Back closes the topmost → Forward restores it.

    The overlay stack reconciles to the landed history entry's depth, so a
    Back/Forward round-trip leaves the CORRECT overlay open with
    ``data-overlay-stack`` consistent — never the wrong one — and never
    navigates the page.
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

                # 2-overlay stack: memory then cmd (one history entry per mount).
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")
                page.evaluate("window.overlayHost.mount('cmd')")
                _wait_stack(page, "memory cmd")

                # Back closes only the topmost (cmd); memory stays open.
                page.go_back()
                _wait_open(page, "memory")
                _wait_stack(page, "memory")
                assert page.url == start_url, "Back must not navigate the page away"

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


def test_system_map_route_swaps_overlay_back_closes_in_one_press() -> None:
    """NAV-3b (#2640): System Map route stays in browser-history sync.

    Open the System Map, click a node that routes to another overlay (memory),
    and the destination overlay is open with the map closed — an ATOMIC swap of
    the single history entry (overlayHost.replace), NOT dismiss()->mount(). Then
    exactly ONE browser Back closes the destination overlay (no extra/dead
    press, no navigate-away), and ``data-overlay-stack`` is consistent
    throughout. Against the unrewired dismiss()->mount() route, the pending
    history.back() would be swallowed and Back would need a second press / land
    on the wrong overlay — this test pins the fix.
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

                # Open the System Map (its single history entry; depth 1).
                page.evaluate("window.overlayHost.mount('map')")
                _wait_open(page, "map")
                _wait_stack(page, "map")

                # Click the map's memory routing node — the real production path
                # systemMap.route('memory') -> overlayHost.replace('memory').
                # The destination overlay opens and the map closes in one atomic
                # swap: stack is exactly 'memory' (the map is gone, not stacked
                # under it), so depth stays 1 — one history entry SWAPPED.
                node = page.query_selector(
                    "[data-testid='system-map-node'][data-surface-id='memory']"
                )
                assert node is not None, "map must render a clickable memory route node"
                node.click()
                _wait_open(page, "memory")
                _wait_stack(page, "memory")
                assert page.url == start_url, "routing must not navigate the page away"

                # ONE browser Back closes the destination overlay and returns to
                # the document anchor — no dead/extra press, no navigate-away.
                # (With the old dismiss()->mount() race, history would still
                # point at the map entry and this single Back would land on the
                # wrong overlay or fail to close.)
                page.go_back()
                _wait_open(page, "none")
                _wait_stack(page, "")
                assert page.url == start_url, (
                    "one Back must close the destination without navigating away"
                )
            finally:
                browser.close()
    finally:
        server.shutdown()


def test_system_map_route_to_already_open_destination_does_not_duplicate() -> None:
    """NAV-3b (#2640) dedup: routing to a destination ALREADY in the stack must
    NOT create a duplicate stack entry, so host bookkeeping never desyncs from
    the DOM.

    Memory open -> Map opened over it (stack ``memory map``) -> click the map's
    Memory node -> overlayHost.replace('memory') closes the map and moves Memory
    to the single top: ``data-overlay-stack`` is exactly ``memory`` (one
    instance, NOT ``memory memory``). Without the dedup splice the stack would
    read ``memory memory`` while the DOM has one drawer — the bug Codex flagged:
    a later Back pops one phantom entry and hides the only drawer while the host
    still reports the overlay open. The single-Back-closes invariant is covered
    by ``test_system_map_route_swaps_overlay_back_closes_in_one_press`` (route
    over an empty stack); here the route reopens a destination that was already
    pushed below the map, so an extra lower history entry from that original
    push legitimately survives (history.replaceState swaps only the current
    entry, it cannot delete the one beneath). What this test pins is that Back
    unwinds the host->DOM relationship consistently — the host never reports an
    overlay open after the DOM drawer is gone — which the dedup guarantees and
    the duplicate would break.
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

                # Memory open, then the Map stacked OVER it (two history entries).
                page.evaluate("window.overlayHost.mount('memory')")
                _wait_open(page, "memory")
                page.evaluate("window.overlayHost.mount('map')")
                _wait_stack(page, "memory map")

                # Route to Memory from the map. replace('memory') closes the map
                # and de-dups: Memory moves to the single top, NOT appended again.
                # data-overlay-stack is exactly 'memory' (one instance) — the core
                # dedup assertion (no 'memory memory').
                node = page.query_selector(
                    "[data-testid='system-map-node'][data-surface-id='memory']"
                )
                assert node is not None, "map must render a clickable memory route node"
                node.click()
                _wait_open(page, "memory")
                _wait_stack(page, "memory")  # exactly one 'memory', never 'memory memory'
                assert page.evaluate(_STACK_JS) == "memory", (
                    "routing to an already-open destination must not duplicate the "
                    "stack entry (no 'memory memory')"
                )
                assert page.url == start_url, "routing must not navigate the page away"

                # Back unwinds host<->DOM consistently: each Back either keeps the
                # drawer open (host says 'memory') or closes it (host says 'none')
                # — the host never claims an overlay is open after the DOM drawer
                # is closed. The drawer's open state is its data-open attribute
                # (the memory occupant's open/close hooks toggle it); is_visible()
                # is unreliable here because the closed drawer is only slid off
                # via CSS transform. Walk Back until the host reports 'none'; the
                # stack must be empty at that point and never have carried a dup.
                drawer_open_js = (
                    "(function(){var d=document.querySelector("
                    "\"[data-overlay-id='memory']\");"
                    "return d ? d.getAttribute('data-open') : null;})()"
                )
                for _ in range(4):
                    open_now = page.evaluate(_OPEN_JS)
                    drawer_open = page.evaluate(drawer_open_js) == "true"
                    # Host/DOM agreement: host 'memory' <=> drawer data-open=true.
                    assert (open_now == "memory") == drawer_open, (
                        "host bookkeeping must match the DOM: open=='memory' iff the "
                        f"memory drawer data-open=true (open={open_now!r}, "
                        f"drawer_open={drawer_open})"
                    )
                    if open_now == "none":
                        break
                    page.go_back()
                    page.wait_for_timeout(150)
                _wait_open(page, "none")
                _wait_stack(page, "")
                # Final state agreement: drawer is closed when the host says none.
                assert page.evaluate(drawer_open_js) == "false", (
                    "the memory drawer must be closed (data-open=false) once the "
                    "host reports no overlay open"
                )
                assert page.url == start_url, "Back must not navigate the page away"
            finally:
                browser.close()
    finally:
        server.shutdown()


def test_system_map_vault_route_swaps_on_narrow_back_closes_in_one_press() -> None:
    """NAV-3b (#2640): the System Map Vault route stays in history sync on a
    NARROW viewport, where vault opens as the ``vault`` overlay.

    On a narrow viewport (< 860px) the inline left pane is unavailable, so
    vaultBrowser.focus() would fall through to open() -> mount('vault'). The
    route detects this via vaultBrowser.prefersOverlay() and goes through
    overlayHost.replace('vault') instead. Open the System Map, click the Vault
    node, and the vault overlay opens with the map closed (stack ``vault``);
    exactly ONE browser Back closes it (no extra/dead press, no navigate-away),
    ``data-overlay-stack`` consistent. Against the unfixed route (dismiss() then
    focus()->open()->mount('vault')), the pending history.back() would be
    swallowed and one Back would not close the vault overlay.
    """
    server, port = _make_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}/"
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            try:
                # NARROW viewport: the persistent inline left pane is suppressed,
                # so vault is an overlay (prefersOverlay() is true).
                page = browser.new_page(viewport={"width": 600, "height": 900})
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                start_url = page.url
                assert page.evaluate(_OPEN_JS) == "none"

                # Precondition: at this width vault prefers the overlay (so the
                # route must take the replace path, not dismiss()+focus()).
                assert (
                    page.evaluate(
                        "window.vaultBrowser && window.vaultBrowser.prefersOverlay"
                        " ? window.vaultBrowser.prefersOverlay() : false"
                    )
                    is True
                ), "narrow viewport must report vaultBrowser.prefersOverlay() == true"

                # Open the System Map, then click its Vault routing node.
                page.evaluate("window.overlayHost.mount('map')")
                _wait_open(page, "map")
                _wait_stack(page, "map")
                node = page.query_selector(
                    "[data-testid='system-map-node'][data-surface-id='vault']"
                )
                assert node is not None, "map must render a clickable vault route node"
                node.click()

                # The vault overlay opens and the map closes — one atomic swap,
                # stack is exactly 'vault' (depth stays 1).
                _wait_open(page, "vault")
                _wait_stack(page, "vault")
                assert page.url == start_url, "routing must not navigate the page away"

                # ONE browser Back closes the vault overlay (no extra/dead press).
                page.go_back()
                _wait_open(page, "none")
                _wait_stack(page, "")
                assert page.url == start_url, (
                    "one Back must close the vault route without navigating away"
                )
            finally:
                browser.close()
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# NAV-3c (#2641): ?overlay=<id> deep-link auto-mounts on load.
# ---------------------------------------------------------------------------


def _make_deep_link_server() -> tuple[HTTPServer, int]:
    """Server that honours ``?overlay=<id>`` like the real ``handle_get``.

    The query value is threaded verbatim into ``render_index_html`` as
    ``boot_overlay``; the renderer resolves it internally to a declared+shipped
    id (else a no-op), so an unknown id never auto-mounts a dead surface.
    """

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                boot_overlay = parse_qs(parsed.query).get("overlay", [""])[0].strip()
                body = render_index_html(
                    api_base_url="http://127.0.0.1:18001",
                    note_path="Notes/note.md",
                    fields=dict(_FIELDS),
                    boot_overlay=boot_overlay,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    return server, server.server_address[1]


def test_overlay_query_deep_link_auto_mounts_on_load() -> None:
    """``?overlay=memory`` and ``?overlay=settings`` auto-mount on page load.

    The deep-link boot script runs after the occupant scripts register, so the
    mount lands a real overlay (the host element records it as topmost). The
    ``settings`` case is the load-bearing one (closed-PR-#2637 ordering bug):
    its occupant script is emitted ~hundreds of lines after the others, and the
    boot must still run after it.
    """
    server, port = _make_deep_link_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            try:
                page = browser.new_page()
                # ?overlay=memory auto-mounts the memory drawer on load.
                page.goto(
                    f"http://127.0.0.1:{port}/?overlay=memory",
                    wait_until="domcontentloaded",
                )
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                _wait_open(page, "memory")

                # ?overlay=settings auto-mounts the settings drawer on load —
                # proving the boot script runs AFTER the late settings occupant
                # script (the regression that no-op'd in closed PR #2637).
                page.goto(
                    f"http://127.0.0.1:{port}/?overlay=settings",
                    wait_until="domcontentloaded",
                )
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                _wait_open(page, "settings")

                # Unknown id is a calm no-op: nothing mounts.
                page.goto(
                    f"http://127.0.0.1:{port}/?overlay=task-popup",
                    wait_until="domcontentloaded",
                )
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                assert page.evaluate(_OPEN_JS) == "none"
            finally:
                browser.close()
    finally:
        server.shutdown()


def test_vault_deep_link_honours_surface_duality_by_viewport() -> None:
    """``?overlay=vault`` routes through ``vaultBrowser.focus()`` per viewport.

    #2645 Codex P2: on a desktop viewport the canonical browse surface is the
    inline left pane (focus() focuses it; the modal stays closed — no duplicate
    surface). On a narrow viewport the inline pane is unavailable, so focus()
    falls through to open() and the modal becomes reachable.
    """
    server, port = _make_deep_link_server()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deep_link = f"http://127.0.0.1:{port}/?overlay=vault"
    modal_open_js = (
        "document.getElementById('vault-browser-overlay')"
        ".classList.contains('open')"
    )
    pane_focused_js = (
        "document.getElementById('vault-browser-left-pane')"
        ".getAttribute('data-browse-focused')"
    )
    try:
        with sync_playwright() as pw:
            browser = _launch(pw)
            try:
                # DESKTOP: focus() targets the inline pane; the modal stays shut.
                page = browser.new_page(viewport={"width": 1200, "height": 900})
                page.goto(deep_link, wait_until="domcontentloaded")
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                # The inline pane gets browse focus...
                page.wait_for_function(f"{pane_focused_js} === 'true'", timeout=5000)
                # ...and the responsive-fallback modal is NOT opened (no
                # duplicate browse surface, single-surface invariant holds).
                assert page.evaluate(modal_open_js) is False, (
                    "desktop ?overlay=vault must focus the inline pane, not open "
                    "the modal (duplicate-surface regression, #2645)"
                )
                # The overlay host did not mount 'vault' as an overlay either.
                assert page.evaluate(_OPEN_JS) == "none"
                page.close()

                # NARROW: no inline pane → focus() falls through to the modal.
                page = browser.new_page(viewport={"width": 600, "height": 900})
                page.goto(deep_link, wait_until="domcontentloaded")
                page.wait_for_selector(
                    '[data-region="overlay-host"]', state="attached", timeout=5000
                )
                page.wait_for_function(f"{modal_open_js} === true", timeout=5000)
            finally:
                browser.close()
    finally:
        server.shutdown()
