"""Playwright browser tests: the unreachable-runtime entry states render and
*behave* in a real browser (#2123/#2124).

These are the interactive companion to the pure-render contract in
``tests/companion_ui/test_workspace_vault_unreachable_banner.py``. The unit tests
assert the HTML string; these assert the live behaviour the string cannot prove:

  * the three purpose-built states render and stay legible — the generic
    transport card, the remote-origin "wrong device" state (the shape the
    2026-06-19 incident hit at ``10.42.42.10``), and the 503 "vault unreachable"
    state;
  * the false vault-setup form is gone in every one of them;
  * the System map overlay actually *mounts* on click;
  * Retry is a real navigation back to ``/`` (not just a plausible href);
  * the page's module scripts load clean offline — no uncaught exceptions, no
    failed imports.

Guard: Playwright + Chromium must be available, else the module is skipped (not
failed). Locally rendered pages + offline ESM stubs — no live vault.
Set COMPANION_UI_BROWSER_TESTS=1 to enable.
"""

from __future__ import annotations

import os
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

from tests.companion_ui.browser_runtime_harness import (
    install_offline_esm_routes,
    serve_rendered_error_page,
)

pytestmark = pytest.mark.browser_runtime

# A transport refusal carries no JSON detail; from a local/unknown origin it is
# the generic runtime card, from a remote origin it is the "wrong device" state.
_TRANSPORT_ERROR = "[Errno 61] Connection refused"
# An application-level 503 runtime_unavailable contract error -> "Vault unreachable".
_HTTP_503 = "HTTP 503: runtime unavailable"
# Any non-localhost host the browser used to load the page (#2124).
_REMOTE_ORIGIN = "100.113.104.116"


def _attach(playwright, url):
    """Launch Chromium, route ESM offline, capture console/page errors, load url.

    Returns (browser, page, console_errors, page_errors, leaks). Listeners are
    registered before navigation so import-time failures are captured.
    """
    browser = playwright.chromium.launch()
    context = browser.new_context()
    leaks = install_offline_esm_routes(context)
    page = context.new_page()

    console_errors: list[str] = []
    page_errors: list[str] = []

    def _on_console(message: object) -> None:
        if getattr(message, "type", "") == "error":
            console_errors.append(getattr(message, "text", ""))

    page.on("console", _on_console)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.goto(url, wait_until="domcontentloaded")
    return browser, page, console_errors, page_errors, leaks


def _assert_system_map_mounts(page) -> None:
    """The System map affordance opens the pull-based overlay on click."""
    overlay = page.locator('[data-testid="system-map-overlay"]')
    host = page.locator('[data-testid="workspace-overlay-host"]')
    assert overlay.get_attribute("data-open") == "false"
    assert host.get_attribute("data-overlay-open") == "none"
    # Wait for the overlay controller to be wired before clicking so the
    # assertion is not racing inline-script execution.
    page.wait_for_function(
        "window.overlayHost && typeof window.overlayHost.mount === 'function'",
        timeout=5000,
    )
    page.locator('[data-testid="workspace-entry-map-affordance"]').click()
    page.wait_for_selector(
        '[data-testid="system-map-overlay"][data-open="true"]', timeout=5000
    )
    assert host.get_attribute("data-overlay-open") == "map"


def _assert_clean(page, console_errors, page_errors, leaks) -> None:
    """No uncaught exceptions, no console errors, no leaked external requests."""
    # A protocol round-trip flushes any in-flight console/error CDP events that
    # may not yet have been delivered, so the assertions below cannot race them.
    page.evaluate("1")
    assert page_errors == [], f"uncaught page errors: {page_errors}"
    assert console_errors == [], f"console errors: {console_errors}"
    assert leaks == [], f"unexpected external requests: {leaks}"


def test_runtime_unavailable_generic_card_renders_and_behaves() -> None:
    # Transport refusal from a local/unknown origin -> the generic runtime card.
    with serve_rendered_error_page(_TRANSPORT_ERROR) as url:
        with sync_playwright() as playwright:
            browser, page, console_errors, page_errors, leaks = _attach(playwright, url)
            try:
                page.wait_for_selector(
                    '[data-testid="workspace-error-state"]', timeout=5000
                )
                card = page.locator('[data-testid="workspace-error-state"]')
                assert card.is_visible()
                assert card.get_attribute("data-error-kind") == "runtime-unavailable"
                assert (
                    page.locator(
                        '[data-testid="workspace-runtime-unavailable-state"]'
                    ).count()
                    == 1
                )

                retry = page.locator('[data-testid="workspace-entry-retry"]')
                assert retry.count() == 1
                assert (retry.get_attribute("href") or "").endswith("/")

                # The vault-setup form is a false affordance while the runtime is
                # unreachable and must be suppressed (#2123 AC1).
                assert page.locator('[data-testid="vault-open-form"]').count() == 0

                _assert_system_map_mounts(page)
                _assert_clean(page, console_errors, page_errors, leaks)
            finally:
                browser.close()


def test_wrong_device_state_renders_and_suppresses_form() -> None:
    # Same unreachable runtime, but loaded from a REMOTE origin — the shape the
    # 2026-06-19 incident hit at 10.42.42.10. Current code renders the distinct
    # "wrong device" state, not the generic card, with the form suppressed (#2124).
    with serve_rendered_error_page(
        _TRANSPORT_ERROR, page_origin_hostname=_REMOTE_ORIGIN
    ) as url:
        with sync_playwright() as playwright:
            browser, page, console_errors, page_errors, leaks = _attach(playwright, url)
            try:
                page.wait_for_selector(
                    '[data-testid="workspace-wrong-device-state"]', timeout=5000
                )
                assert page.locator(
                    '[data-testid="workspace-wrong-device-state"]'
                ).is_visible()
                # It is the distinct remote-access state, not the generic card.
                assert page.locator('[data-testid="workspace-error-state"]').count() == 0
                # The false vault-setup form is suppressed here too.
                assert page.locator('[data-testid="vault-open-form"]').count() == 0

                _assert_system_map_mounts(page)
                _assert_clean(page, console_errors, page_errors, leaks)
            finally:
                browser.close()


def test_vault_unreachable_state_renders_and_suppresses_form() -> None:
    # An application-level HTTP 503 runtime_unavailable contract error from a
    # local origin -> the designed "Vault unreachable" state (#2123).
    with serve_rendered_error_page(_HTTP_503) as url:
        with sync_playwright() as playwright:
            browser, page, console_errors, page_errors, leaks = _attach(playwright, url)
            try:
                page.wait_for_selector(
                    '[data-testid="workspace-vault-unreachable-state"]', timeout=5000
                )
                assert page.locator(
                    '[data-testid="workspace-vault-unreachable-state"]'
                ).is_visible()
                assert page.locator('[data-testid="workspace-error-state"]').count() == 0
                assert page.locator('[data-testid="vault-open-form"]').count() == 0

                _assert_system_map_mounts(page)
                _assert_clean(page, console_errors, page_errors, leaks)
            finally:
                browser.close()


def test_runtime_unavailable_retry_navigates_home() -> None:
    # Retry is the user's only escape hatch from a stuck state — prove the click
    # really issues a navigation to "/", not just that the href looks right.
    with serve_rendered_error_page(_TRANSPORT_ERROR) as url:
        with sync_playwright() as playwright:
            browser, page, *_ = _attach(playwright, url)
            try:
                retry = page.locator('[data-testid="workspace-entry-retry"]')
                with page.expect_navigation(wait_until="domcontentloaded") as nav:
                    retry.click()
                assert urlparse(nav.value.url).path == "/"
                # The post-retry document re-renders the entry error state.
                page.wait_for_selector(
                    '[data-testid="workspace-error-state"]', timeout=5000
                )
            finally:
                browser.close()
