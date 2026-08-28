"""Connected browser proof for the exact committed #4836 devUI candidate."""

from __future__ import annotations

import os
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Iterator

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set COMPANION_UI_BROWSER_TESTS=1 to run Playwright browser-runtime tests.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
except ImportError:
    pytest.skip("playwright package not installed", allow_module_level=True)

from companion_ui.workspace.serve_dev_page import make_handler
from tests.companion_ui._devui_overview_exact_ref_evidence import (
    ExactRefEvidenceRecorder,
)

pytestmark = pytest.mark.browser_runtime

SUBJECT = "github:RasmusTho/agentic-pkm-mvp#4836"
FOCUS_PATH = "/devui/focus?subject=github%3ARasmusTho%2Fagentic-pkm-mvp%234836"
RUNTIME_SHA = "a" * 40
_EVIDENCE = ExactRefEvidenceRecorder()


def _page_errors(page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    return errors


def _source(source_id: str) -> dict[str, str]:
    return {
        "source_type": "github_issue",
        "source_id": source_id,
        "locator": f"https://example.invalid/{source_id}",
        "version": "2026-08-28T10:00:00+00:00",
    }


def _overview() -> dict[str, Any]:
    candidate = {
        "subject_ref": _source(SUBJECT),
        "display_label": "<img src=x onerror=alert(1)> Connected shell",
        "reason": "Owner-visible now item",
        "evidence": [
            {
                "evidence_id": "working-4836",
                "claim": "Working projection contains this item.",
                "source_ref": _source("cockpit:working:4836"),
                "availability": "available",
                "freshness": "fresh",
                "completeness": "complete",
                "cardinality": "nonempty",
                "linkage": "linked",
                "captured_at": "2026-08-28T10:00:00+00:00",
                "read_watermark": "2026-08-28T10:00:00+00:00",
                "limitation": None,
            }
        ],
        "navigation_refs": [
            {
                "kind": "focus",
                "navigation_ref": {
                    "source_type": "devui_focus_route",
                    "source_id": SUBJECT,
                    "locator": FOCUS_PATH,
                    "version": "devui-focus-view.v1",
                },
                "status": "available",
                "limitation": None,
            }
        ],
        "limitations": ["No owner acceptance is inferred."],
    }
    return {
        "contract_version": "devui-overview-view.v1",
        "authority": "projection_only",
        "composed_at": "2026-08-28T10:00:00+00:00",
        "state": "degraded",
        "trust_frame": {
            "availability": "available",
            "freshness": "stale",
            "completeness": "partial",
            "cardinality": "nonempty",
            "linkage": "linked",
            "limitations": ["One provider is stale."],
        },
        "now": [candidate],
        "needs_you": [],
        "ready_to_try": [],
        "limitations": ["One provider is stale."],
    }


def _focus() -> dict[str, Any]:
    claim = {
        "claim_id": "governing-subject",
        "claim": "Selected subject is readable.",
        "source_ref": _source("RasmusTho/agentic-pkm-mvp#4836"),
        "availability": "available",
        "freshness": "fresh",
        "coverage": "complete",
        "cardinality": "nonempty",
        "linkage": "linked",
        "captured_at": "2026-08-28T10:00:00+00:00",
        "limitation": None,
    }
    return {
        "contract_version": "devui-focus-view.v1",
        "authority": "projection_only",
        "composed_at": "2026-08-28T10:00:00+00:00",
        "state": "ready",
        "subject": {
            "kind": "issue",
            "stable_id": SUBJECT,
            "authority_ref": _source("RasmusTho/agentic-pkm-mvp#4836"),
            "title": "Connected devUI shell",
        },
        "owner_intent": {
            "summary": "Read the governed Issue.",
            "source_ref": _source("RasmusTho/agentic-pkm-mvp#4836"),
        },
        "governing_sources": [claim],
        "evidence": [{**claim, "claim_id": "subject-read"}],
        "receipts": [],
        "risks": [],
        "next_legal_step": {
            "workflow_ref": None,
            "actor_class": "system",
            "legality": "unavailable",
            "reason": "No transition is inferred.",
        },
        "execution_observations": [],
        "conversation_port": {
            "availability": "unsupported",
            "reason": "Conversation is not delivered here.",
        },
        "limitations": [
            {
                "kind": "coverage",
                "linkage": "not_assessed",
                "reason": "No acceptance receipt is available.",
            }
        ],
    }


class _Client:
    def __init__(self, *, focus_status: int = 200) -> None:
        self.focus_status = focus_status
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_with_status(
        self, url: str, *, params: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append((url, params))
        if url == "/api/devui/overview":
            return 200, _overview()
        if self.focus_status != 200:
            return self.focus_status, {"detail": "unavailable"}
        return 200, _focus()


@contextmanager
def _serve(*, focus_status: int = 200) -> Iterator[tuple[str, _Client]]:
    client = _Client(focus_status=focus_status)
    handler = make_handler(
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
        devui_external_bind_host="127.0.0.1",
        runtime_git_sha=RUNTIME_SHA,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", client
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _browser(base_url: str):
    playwright = sync_playwright().start()
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    try:
        browser = playwright.chromium.launch(executable_path=executable or None)
    except Exception:
        playwright.stop()
        raise
    context = browser.new_context()
    external: list[str] = []

    def record(route) -> None:
        if not route.request.url.startswith(base_url):
            external.append(route.request.url)
            route.abort()
            return
        route.continue_()

    context.route("**/*", record)
    return playwright, browser, context, context.new_page(), external


def test_real_gateway_overview_focus_return_journey_preserves_subject_context_and_sha() -> None:
    with _serve() as (base_url, client):
        playwright, browser, context, page, external = _browser(base_url)
        page_errors = _page_errors(page)
        document_shas: list[str] = []
        page.on(
            "response",
            lambda response: document_shas.append(
                response.headers.get("x-pkm-runtime-git-sha", "")
            )
            if response.request.resource_type == "document"
            else None,
        )
        try:
            page.goto(base_url + "/devui/overview")
            page.wait_for_selector('[data-testid="overview-load-state"][data-state="loaded"]')
            link = page.locator('[data-testid="overview-focus-link"]')
            assert link.get_attribute("href") == FOCUS_PATH
            link.click()
            page.wait_for_selector('[data-testid="focus-load-state"][data-state="loaded"]')
            assert page.locator('[data-testid="focus-subject"]').get_attribute("data-subject") == SUBJECT
            page.locator('[data-testid="overview-return"]').click()
            page.wait_for_selector('[data-testid="overview-load-state"][data-state="loaded"]')
            assert document_shas == [RUNTIME_SHA, RUNTIME_SHA, RUNTIME_SHA]
            assert client.calls == [
                ("/api/devui/overview", {}),
                ("/api/devui/focus", {"subject": SUBJECT}),
                ("/api/devui/overview", {}),
            ]
            assert external == []
            _EVIDENCE.record_pass(
                "test_real_gateway_overview_focus_return_journey_preserves_subject_context_and_sha",
                page_errors=page_errors,
            )
        finally:
            context.close()
            browser.close()
            playwright.stop()


def test_focus_api_failure_renders_honest_visual_error_without_url_probing() -> None:
    with _serve(focus_status=404) as (base_url, client):
        playwright, browser, context, page, _external = _browser(base_url)
        page_errors = _page_errors(page)
        try:
            page.goto(base_url + FOCUS_PATH)
            page.wait_for_selector('[data-testid="focus-load-state"][data-state="error"]')
            assert SUBJECT in page.locator('[role="alert"]').inner_text()
            assert client.calls == [("/api/devui/focus", {"subject": SUBJECT})]
            _EVIDENCE.record_pass(
                "test_focus_api_failure_renders_honest_visual_error_without_url_probing",
                page_errors=page_errors,
            )
        finally:
            context.close()
            browser.close()
            playwright.stop()


def test_connected_shell_freezes_server_identity_selector_and_aria_contract() -> None:
    with _serve() as (base_url, _client):
        playwright, browser, context, page, _external = _browser(base_url)
        page_errors = _page_errors(page)
        try:
            page.goto(base_url + FOCUS_PATH)
            page.wait_for_selector('[data-testid="focus-load-state"][data-state="loaded"]')
            for testid in (
                "devui-focus",
                "focus-subject",
                "focus-owner-intent",
                "focus-governing-sources",
                "focus-evidence",
                "focus-limitations",
                "overview-return",
            ):
                assert page.locator(f'[data-testid="{testid}"]').count() == 1
            assert page.locator("main").get_attribute("aria-labelledby") == "focus-heading"
            _EVIDENCE.record_pass(
                "test_connected_shell_freezes_server_identity_selector_and_aria_contract",
                page_errors=page_errors,
            )
        finally:
            context.close()
            browser.close()
            playwright.stop()


def test_connected_shell_renders_full_server_state_matrix_without_reclassification() -> None:
    with _serve() as (base_url, _client):
        playwright, browser, context, page, _external = _browser(base_url)
        page_errors = _page_errors(page)
        try:
            page.goto(base_url + "/devui/overview")
            page.wait_for_selector('[data-testid="overview-load-state"][data-state="loaded"]')
            matrix = page.locator('[data-testid="overview-trust-frame"]')
            for axis, value in (
                ("availability", "available"),
                ("freshness", "stale"),
                ("completeness", "partial"),
                ("cardinality", "nonempty"),
                ("linkage", "linked"),
            ):
                assert matrix.locator(f'[data-axis="{axis}"]').get_attribute("data-value") == value
            assert page.locator('[data-testid="overview-shell"]').get_attribute("data-server-state") == "degraded"
            _EVIDENCE.record_pass(
                "test_connected_shell_renders_full_server_state_matrix_without_reclassification",
                page_errors=page_errors,
            )
        finally:
            context.close()
            browser.close()
            playwright.stop()


def test_gateway_shell_is_safe_accessible_no_egress_and_effect_free() -> None:
    with _serve() as (base_url, client):
        playwright, browser, context, page, external = _browser(base_url)
        requests: list[tuple[str, str]] = []
        page_errors = _page_errors(page)
        page.on("request", lambda request: requests.append((request.method, request.url)))
        trace_path: Path | None = None
        trace_dir = os.environ.get("DEVUI_OVERVIEW_TRACE_DIR")
        if trace_dir:
            trace_path = Path(trace_dir) / "connected-overview-focus.zip"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
        try:
            page.goto(base_url + "/devui/overview")
            page.wait_for_selector('[data-testid="overview-load-state"][data-state="loaded"]')
            assert page.locator("img").count() == 0
            assert "<img" in page.locator('[data-testid="overview-card-title"]').inner_text()
            assert page.locator("h1").count() == 1
            assert page.get_by_role("main").get_attribute("aria-labelledby") == "overview-heading"
            assert page.get_by_role("link", name="Open Focus").count() == 1
            page.keyboard.press("Tab")
            assert page.locator(":focus").get_attribute("data-testid") == "overview-focus-link"

            assert page.viewport_size == {"width": 1280, "height": 720}
            page.set_viewport_size({"width": 375, "height": 812})
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            page.set_viewport_size({"width": 1280, "height": 720})
            cdp_session = context.new_cdp_session(page)
            cdp_session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
            assert page.evaluate("window.visualViewport.scale") == 2
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
            cdp_session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
            cdp_session.detach()
            page.emulate_media(media="print")
            assert page.get_by_role("main").is_visible()
            page.emulate_media(media="screen")

            before_javascript_off = list(client.calls)
            javascript_off_context = browser.new_context(java_script_enabled=False)
            javascript_off_external: list[str] = []

            def record_javascript_off(route) -> None:
                if not route.request.url.startswith(base_url):
                    javascript_off_external.append(route.request.url)
                    route.abort()
                    return
                route.continue_()

            javascript_off_context.route("**/*", record_javascript_off)
            javascript_off_page = javascript_off_context.new_page()
            try:
                javascript_off_page.goto(base_url + "/devui/overview")
                assert javascript_off_page.get_by_role("main").count() == 1
                assert javascript_off_page.get_by_role("alert").is_visible()
                assert "needs JavaScript" in javascript_off_page.get_by_role("alert").inner_text()
                assert client.calls == before_javascript_off
                assert javascript_off_external == []
            finally:
                javascript_off_context.close()

            screenshot_dir = os.environ.get("DEVUI_OVERVIEW_SCREENSHOT_DIR")
            if screenshot_dir:
                screenshot_path = Path(screenshot_dir) / "overview.png"
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                page.set_viewport_size({"width": 1280, "height": 720})
                page.screenshot(path=str(screenshot_path), full_page=True)
            assert all(method == "GET" for method, _url in requests)
            assert external == []
            assert client.calls == [("/api/devui/overview", {})]
            _EVIDENCE.record_pass(
                "test_gateway_shell_is_safe_accessible_no_egress_and_effect_free",
                page_errors=page_errors,
            )
        finally:
            if trace_path is not None:
                context.tracing.stop(path=str(trace_path))
            context.close()
            browser.close()
            playwright.stop()
