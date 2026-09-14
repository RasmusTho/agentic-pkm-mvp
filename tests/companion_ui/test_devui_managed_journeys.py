"""Actual standalone listener journeys; only external source/transport faults are fixtures."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from tests.builderops.test_devui_runtime import (
    MANAGED_SUBJECT,
    _package_managed_shell,
    managed_sources,  # noqa: F401 - source-bound pytest fixture
)

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set COMPANION_UI_BROWSER_TESTS=1 for managed browser proof", allow_module_level=True
    )

from playwright.sync_api import sync_playwright
import uvicorn
from app.builderops.devui_runtime import production_app
from app.builderops.devui_sources import package_candidate

pytestmark = pytest.mark.browser_runtime
ORIGIN = "http://127.0.0.1:8113"
FOCUS = "/devui/focus?subject=github%3Aexample%2Ffixture%23501"


@contextmanager
def _server(source, monkeypatch):
    source.environment["DEVUI_REPOSITORY"] = "Example/Fixture"
    source.gh_mode.write_text("canonical_case")
    _package_managed_shell(source.root)
    manifest = json.loads((source.root / "manifest.json").read_text())
    package_candidate(
        source.root,
        repository=source.environment["DEVUI_REPOSITORY"],
        source_sha=source.environment["DEVUI_SOURCE_SHA"],
        capabilities=manifest["capabilities"],
        matrix=manifest["matrix"],
    )
    for key, value in source.environment.items():
        monkeypatch.setenv(key, value)
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 8113))
    server = uvicorn.Server(
        uvicorn.Config(
            production_app(), log_level="critical", proxy_headers=False, access_log=False
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.01)
        assert server.started
        yield
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


@contextmanager
def _browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
        )
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        external, requests, errors, console = [], [], [], []
        context.route(
            "**/*",
            lambda route: (external.append(route.request.url), route.abort())
            if not route.request.url.startswith(ORIGIN + "/")
            else route.continue_(),
        )
        page = context.new_page()
        page.set_default_timeout(5000)
        page.on("request", lambda r: requests.append((r.method, r.url)))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        try:
            yield page, context, browser, external, requests, errors, console
        finally:
            context.close()
            browser.close()


def _loaded(page, surface):
    page.locator(f'[data-testid="{surface}-load-state"][data-state="loaded"]').wait_for()


def _no_persistence(page, context):
    assert context.cookies() == []
    assert page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
    assert page.evaluate("indexedDB.databases()") == []
    assert page.evaluate("caches.keys()") == []
    assert page.evaluate("navigator.serviceWorker.getRegistrations().then(x => x.length)") == 0


def _capture(page, name):
    folder = os.environ.get("DEVUI_MANAGED_EVIDENCE_DIR")
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path / (name + ".png")), full_page=True)
        (path / (name + ".aria.txt")).write_text(page.locator("body").aria_snapshot())


def test_standalone_overview_focus_return_preserves_subject_and_candidate(
    managed_sources,  # noqa: F811 - imported pytest fixture
    monkeypatch
):
    source = managed_sources
    with (
        _server(source, monkeypatch),
        _browser() as (page, context, _browser_instance, external, requests, errors, console),
    ):
        first = page.goto(ORIGIN + "/devui/overview")
        _loaded(page, "overview")
        overview_reads = len(source.calls)
        link = page.get_by_role("link", name="Open Focus")
        assert link.get_attribute("href") == FOCUS
        with page.expect_response(lambda r: "/api/devui/focus?" in r.url) as read:
            link.click()
        _loaded(page, "focus")
        payload = read.value.json()
        assert payload["subject"]["stable_id"] == MANAGED_SUBJECT
        assert payload["subject"]["authority_ref"]["locator"] == "https://github.com/Example/Fixture/issues/501"
        assert (
            page.locator('[data-testid="focus-subject"]').get_attribute("data-subject")
            == MANAGED_SUBJECT
        )
        assert (
            page.locator('[data-testid="devui-focus"]').get_attribute("data-server-state")
            == payload["state"]
        )
        assert (
            source.calls and len(source.calls) == overview_reads
        ), "Focus must not read or join root providers"
        for key in (
            "x-pkm-runtime-git-sha",
            "x-devui-image-digest",
            "x-devui-config-fingerprint",
            "x-devui-asset-inventory",
        ):
            assert first.headers[key] == read.value.headers[key]
        assert payload["receipts"] == payload["execution_observations"] == []
        _capture(page, "managed-focus")
        page.get_by_role("link", name="Return to Overview").click()
        _loaded(page, "overview")
        assert len(source.calls) > overview_reads
        assert sum(url == ORIGIN + "/api/devui/overview" for _, url in requests) == 2
        assert all(method == "GET" for method, _ in requests)
        assert not external and not errors and not console
        _no_persistence(page, context)


def test_managed_journey_hostile_accessibility_and_no_effect_matrix(managed_sources, monkeypatch):  # noqa: F811 - imported pytest fixture
    source = managed_sources
    source.tasks[0]["payload"]["title"] = "<img src=x onerror=alert(1)> Managed work"
    with (
        _server(source, monkeypatch),
        _browser() as (page, context, browser, external, requests, errors, console),
    ):
        for surface, path in (("overview", "/devui/overview"), ("focus", FOCUS)):
            response = page.goto(ORIGIN + path)
            _loaded(page, surface)
            assert response.headers["cache-control"] == "no-store"
            assert "default-src 'none'" in response.headers["content-security-policy"]
            assert page.locator("img").count() == 0
            assert "<img" in page.locator("body").inner_text()
            assert page.get_by_role("main").get_attribute("aria-labelledby") == surface + "-heading"
            assert page.get_by_role("heading", level=1).count() == 1
            page.keyboard.press("Tab")
            assert page.locator(":focus").get_attribute("href") == (
                FOCUS if surface == "overview" else "/devui/overview"
            )
            page.keyboard.press("Tab")
            assert (
                page.locator(":focus").count() == 0
            ), "Only the admitted navigation is keyboard interactive"
            assert 'heading "' in page.locator("body").aria_snapshot()
            for name, width, height, scale in (
                ("desktop", 1280, 720, 1),
                ("narrow", 375, 812, 1),
                ("zoom_200", 640, 720, 2),
            ):
                page.set_viewport_size({"width": width, "height": height})
                cdp = context.new_cdp_session(page)
                cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": scale})
                assert page.evaluate("window.visualViewport.scale") == scale
                _capture(page, surface + "-" + name)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                ), page.evaluate(
                    "({width:innerWidth, client:document.documentElement.clientWidth, scroll:document.documentElement.scrollWidth, elements:Array.from(document.querySelectorAll('*')).filter(x => x.scrollWidth > x.clientWidth && !x.children.length).map(x => [x.tagName, x.className, x.textContent.slice(0, 70), x.getBoundingClientRect().right]).slice(0, 12)})"
                )
                cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
                cdp.detach()
            page.emulate_media(media="print")
            assert page.get_by_role("main").is_visible()
            _capture(page, surface + "-print")
            page.emulate_media(media="screen")
            _no_persistence(page, context)
            prior_calls = list(source.calls)
            prior_gh = source.gh_calls.read_text() if source.gh_calls.exists() else ""
            off = browser.new_context(java_script_enabled=False)
            try:
                off_page = off.new_page()
                off_page.goto(ORIGIN + path)
                assert "needs JavaScript" in off_page.get_by_role("alert").inner_text()
                _capture(off_page, surface + "-javascript-off")
                assert source.calls == prior_calls
                assert (source.gh_calls.read_text() if source.gh_calls.exists() else "") == prior_gh
            finally:
                off.close()
        assert all(method == "GET" for method, _ in requests)
        assert all(method == "GET" for method, _ in source.http_calls)
        assert not external and not errors and not console


def test_managed_journey_preserves_focus_failures_and_fresh_return(managed_sources, monkeypatch):  # noqa: F811 - imported pytest fixture
    source = managed_sources
    with (
        _server(source, monkeypatch),
        _browser() as (page, context, _browser_instance, external, requests, errors, console),
    ):
        for failure in (
            "refusal",
            "timeout",
            "404",
            "http_status",
            "malformed",
            "request_failure",
            "page_error",
            "console_error",
        ):
            before = len(source.calls)
            if failure == "refusal":
                source.gh_mode.write_text("unavailable")
            else:

                def fail(route):
                    mode = failure
                    if mode in {"timeout", "request_failure"}:
                        route.abort("timedout" if mode == "timeout" else "failed")
                    elif mode == "404":
                        route.fulfill(status=404, json={"detail": "missing"})
                    elif mode == "http_status":
                        route.fulfill(status=503, json={"detail": "unavailable"})
                    elif mode == "malformed":
                        route.fulfill(status=200, content_type="application/json", body="{broken")
                    else:
                        route.continue_()

                page.route("**/api/devui/focus?*", fail)
            page.goto(ORIGIN + FOCUS)
            if failure in {"page_error", "console_error"}:
                _loaded(page, "focus")
                if failure == "page_error":
                    page.evaluate(
                        "setTimeout(() => { throw new Error('fixture page failure'); }, 0)"
                    )
                    page.wait_for_timeout(50)
                    assert errors == ["fixture page failure"]
                else:
                    page.evaluate("console.error('fixture console failure')")
                    assert any("fixture console failure" in error for error in console)
            else:
                page.locator('[data-testid="focus-load-state"][data-state="error"]').wait_for()
                assert (
                    page.locator('[data-testid="devui-focus"]').get_attribute("data-server-state")
                    == "read_error"
                )
                assert page.get_by_role("alert").is_visible()
            assert len(source.calls) == before
            _capture(page, "focus-failure-" + failure)
            page.unroute("**/api/devui/focus?*")
            source.gh_mode.write_text("canonical_case")
            page.get_by_role("link", name="Return to Overview").click()
            _loaded(page, "overview")
            assert len(source.calls) > before
            _no_persistence(page, context)
        assert len([url for _, url in requests if "/api/devui/focus?" in url]) == 8
        assert all(method == "GET" for method, _ in requests)
        assert not external
        assert errors == ["fixture page failure"]
        assert set(url.split("?", 1)[0].removeprefix(ORIGIN) for _, url in requests) <= {
            "/devui/overview",
            "/devui/focus",
            "/devui/assets/devui.css",
            "/devui/assets/overview.js",
            "/devui/assets/focus.js",
            "/api/devui/overview",
            "/api/devui/focus",
        }
        source.mode = "unavailable"
        with page.expect_response(ORIGIN + "/api/devui/overview") as response:
            page.reload()
        _loaded(page, "overview")
        states = response.value.json()["trust_frame"]["provider_states"]
        assert "refused" in json.dumps(states)
        assert "refused" in page.locator('[data-testid="overview-trust-frame"]').inner_text()
def test_first_read_issue_journey_precedes_observation_without_effects(managed_sources, monkeypatch):  # noqa: F811 - imported pytest fixture
    from tests.builderops.test_devui_runtime import _install_first_read_observation

    source = managed_sources
    folder = Path(source.environment["DEVUI_VM102_RECEIPT_DIR"]) / "first-read"
    assert not folder.exists()
    with _server(source, monkeypatch), _browser() as (page, context, _, external, requests, errors, console):
        _install_first_read_observation(source, monkeypatch, retain=False)
        with page.expect_response(ORIGIN + "/api/devui/overview") as first:
            page.goto(ORIGIN + "/devui/overview")
        _loaded(page, "overview")
        assert first.value.headers["x-devui-first-read-observation"] == "refused"
        reads = len(source.calls)
        assert page.get_by_role("link", name="Open Focus").get_attribute("href") == FOCUS
        with page.expect_response(lambda r: "/api/devui/focus?" in r.url) as focus:
            page.get_by_role("link", name="Open Focus").click()
        _loaded(page, "focus")
        assert focus.value.json()["subject"]["stable_id"] == MANAGED_SUBJECT
        assert focus.value.headers["x-pkm-runtime-git-sha"] == first.value.headers["x-pkm-runtime-git-sha"]
        assert focus.value.headers["x-devui-first-read-observation"] == "refused"
        _capture(page, "first-read-before-observation")
        with page.expect_response(ORIGIN + "/api/devui/overview") as returned:
            page.get_by_role("link", name="Return to Overview").click()
        _loaded(page, "overview")
        assert len(source.calls) > reads
        providers = {item["role"]: item for item in returned.value.json()["trust_frame"]["provider_states"]}
        assert providers["first_read_observation"]["status"] == providers["vm102_evidence"]["status"] == "refused"
        assert not folder.exists()
        assert not external and not errors and not console
        assert all(method == "GET" for method, _ in requests + source.http_calls)
        assert sum(url == ORIGIN + "/api/devui/overview" for _, url in requests) == 2
        _no_persistence(page, context)
