"""Offline browser proof for independent Vault Browser failure axes (#5943).

The canonical pane is exercised at desktop and a narrow persistent-pane
width. Mobile overlay/live-channel acceptance belongs to separate journeys.
Only the recorded missing-identity notice may be an expected failure; browser
errors, unsafe requests and lost healthy rows remain ordinary failures.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Iterator
from urllib.parse import parse_qs, urlparse

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip("Set COMPANION_UI_BROWSER_TESTS=1 to run browser tests.", allow_module_level=True)

# An explicitly enabled run must fail if its browser dependency is missing.
from playwright.sync_api import Browser, BrowserContext, Page, Route, expect, sync_playwright

from tests.companion_ui.browser_runtime_harness import (
    install_offline_esm_routes,
    serve_rendered_workspace,
)

pytestmark = pytest.mark.browser_runtime

_NOTE_PATH = "Notes/Readable & café #1?.md"
_KNOWN_DEFECT = (
    "KD-87DEE784B97A: list degradation masks unresolved identity; "
    "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4172#issuecomment-6099201983"
)


class MissingIdentityNotice(AssertionError):
    """The exact deferred presentation defect, not an arbitrary test failure."""


_KNOWN_IDENTITY_OMISSION = pytest.mark.xfail(
    strict=True, raises=MissingIdentityNotice, reason=_KNOWN_DEFECT
)


@dataclass
class ObservedBrowser:
    context: BrowserContext
    page: Page
    page_errors: list[str]
    console_errors: list[str]
    external_requests: list[str]
    write_requests: list[tuple[str, str]]

    def assert_clean(self) -> None:
        # A protocol round trip delivers queued page/console/request events.
        self.page.evaluate("document.readyState")
        assert self.page_errors == []
        assert self.console_errors == []
        assert self.external_requests == []
        assert self.write_requests == []


@pytest.fixture(scope="module")
def chromium() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture(params=[(1366, 900), (900, 900)], ids=["desktop", "narrow-pane"])
def observed_browser(chromium: Browser, request: pytest.FixtureRequest) -> Iterator[ObservedBrowser]:
    width, height = request.param
    context = chromium.new_context(viewport={"width": width, "height": height})
    external_requests = install_offline_esm_routes(context)
    # The shell loads its separate settings drawer on entry. Stub only that
    # unrelated read; unexpected paths and missing real assets still fail.
    context.route(
        re.compile(r"http://127\.0\.0\.1:\d+/vault-settings\?scope=settings$"),
        lambda route: route.fulfill(status=200, content_type="text/html", body="")
        if route.request.method == "GET" else route.continue_(),
    )
    page = context.new_page()
    observed = ObservedBrowser(context, page, [], [], external_requests, [])
    page.on("pageerror", lambda error: observed.page_errors.append(str(error)))
    page.on("console", lambda message: (
        observed.console_errors.append(message.text) if message.type == "error" else None
    ))
    context.on("request", lambda req: (
        observed.write_requests.append((req.method, req.url))
        if req.method not in {"GET", "HEAD", "OPTIONS"} else None
    ))
    evidence_root = os.environ.get("COMPANION_UI_STATE_EVIDENCE_DIR")
    evidence_path = Path(evidence_root) if evidence_root else None
    evidence_name = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    if evidence_path:
        evidence_path.mkdir(parents=True, exist_ok=True)
        context.tracing.start(screenshots=True, snapshots=True)
    try:
        yield observed
    finally:
        try:
            if evidence_path:
                page.screenshot(path=str(evidence_path / f"{evidence_name}.png"), full_page=True)
                context.tracing.stop(path=str(evidence_path / f"{evidence_name}.zip"))
        finally:
            context.close()


def _fields(list_state: str, identity_available: bool) -> dict:
    has_notes = list_state in {"populated", "partial"}
    return {
        "guard_canvas_enabled": False,
        "suggestion_composer_enabled": False,
        "vault_browser_notes": ([{
            "note_path": _NOTE_PATH, "title": "Readable note", "kind": "human_note",
        }] if has_notes else []),
        "vault_browser_total_notes": 2 if list_state == "partial" else int(has_notes),
        "vault_browser_filtered_notes": int(has_notes),
        "vault_browser_read_only": True,
        "vault_browser_identity_available": identity_available,
        "vault_browser_vault_name": "FixtureVault" if identity_available else "unresolved",
        "vault_browser_vault_channel": "test" if identity_available else "unknown",
        "vault_browser_vault_provenance": "resolved" if identity_available else "unresolved",
        "vault_browser_state": "partial" if list_state == "partial" else "ready",
        "vault_browser_degraded_reason": "note_read_failed" if list_state == "partial" else None,
        "vault_browser_error": "private transport error" if list_state == "error" else None,
    }


def _open_browser(observed: ObservedBrowser, url: str) -> None:
    fixture_origin = urlparse(url).netloc

    def confine_requests(route: Route) -> None:
        target = urlparse(route.request.url)
        if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
            # Record via the request listener, but stop before any real effect.
            route.abort()
        elif target.hostname == "127.0.0.1" and target.netloc != fixture_origin:
            observed.external_requests.append(route.request.url)
            route.abort()
        else:
            route.fallback()

    # Even a future JS regression cannot reach a running localhost backend.
    observed.context.route("**/*", confine_requests)
    page = observed.page
    page.goto(url, wait_until="networkidle")
    page.get_by_test_id("workspace-vault-chip").click()
    expect(page.get_by_test_id("workspace-left-panel-mode-browse")).to_be_visible()
    expect(page.get_by_test_id("workspace-vault-browser")).to_be_visible()


@pytest.mark.parametrize("list_state,identity_available,primary", [
    pytest.param("populated", True, "ready", id="populated-bound"),
    pytest.param("populated", False, "identity-unavailable", id="populated-unbound"),
    pytest.param("empty", True, "empty", id="empty-bound"),
    pytest.param("empty", False, "identity-unavailable", id="empty-unbound"),
    pytest.param("partial", True, "partial", id="partial-bound"),
    pytest.param("error", True, "error", id="error-bound"),
])
def test_vault_browser_failure_state_matrix(
    observed_browser: ObservedBrowser, list_state: str, identity_available: bool, primary: str,
) -> None:
    _assert_browser_state(observed_browser, list_state, identity_available, primary)


@_KNOWN_IDENTITY_OMISSION
@pytest.mark.parametrize("list_state", ["partial", "error"])
def test_known_combined_identity_notice_omission(
    observed_browser: ObservedBrowser, list_state: str,
) -> None:
    _assert_browser_state(observed_browser, list_state, False, list_state)


def _assert_browser_state(
    observed_browser: ObservedBrowser, list_state: str, identity_available: bool, primary: str,
) -> None:
    observed = observed_browser
    with serve_rendered_workspace("# Current\n\nFixture.", fields=_fields(list_state, identity_available)) as url:
        _open_browser(observed, url)
        surface = observed.page.get_by_test_id("workspace-vault-browser")
        expect(surface.get_by_test_id(f"workspace-vault-browser-state-{primary}")).to_have_count(1)
        if primary != "ready":
            expect(surface.get_by_test_id(f"workspace-vault-browser-state-{primary}")).to_be_visible()
            expect(surface.get_by_test_id("workspace-vault-browser-state-ready")).to_have_count(0)
        if list_state in {"partial", "error"}:
            expect(surface.get_by_test_id("workspace-vault-browser-state-empty")).to_have_count(0)
        expect(surface.get_by_test_id("workspace-vault-browser-read-only")).to_have_text("read-only")
        expected_identity = "FixtureVault/test" if identity_available else "unresolved/unknown"
        expect(surface.get_by_test_id("workspace-vault-browser-active-identity")).to_have_text(expected_identity)
        links = surface.get_by_test_id("workspace-vault-browser-note-link")
        expect(links).to_have_count(int(list_state in {"populated", "partial"}))
        if list_state in {"populated", "partial"}:
            expect(links).to_be_visible()
        assert "private transport error" not in surface.inner_text()
        observed.assert_clean()
        if not identity_available:
            notice = surface.get_by_test_id("workspace-vault-browser-state-identity-unavailable")
            if notice.count() == 0:
                raise MissingIdentityNotice(_KNOWN_DEFECT)
            expect(notice).to_be_visible()


@pytest.mark.parametrize("list_state", ["populated", "partial"])
def test_read_only_note_link_navigates_with_exact_path(
    observed_browser: ObservedBrowser, list_state: str,
) -> None:
    observed = observed_browser
    with serve_rendered_workspace("# Current\n\nFixture.", fields=_fields(list_state, True)) as url:
        _open_browser(observed, url)
        link = observed.page.get_by_test_id("workspace-vault-browser-note-link")
        link.focus()
        with observed.page.expect_navigation(wait_until="networkidle"):
            link.press("Enter")
        destination = urlparse(observed.page.url)
        assert destination.netloc == urlparse(url).netloc
        assert parse_qs(destination.query)["note_path"] == [_NOTE_PATH]
        observed.assert_clean()
