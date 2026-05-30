"""Real-browser Mermaid runtime coverage for the Companion UI workspace."""

from __future__ import annotations

import os

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set COMPANION_UI_BROWSER_TESTS=1 to run Playwright browser-runtime tests.",
        allow_module_level=True,
    )

from playwright.sync_api import sync_playwright

from tests.companion_ui.browser_runtime_harness import (
    install_offline_esm_routes,
    serve_rendered_workspace,
)


pytestmark = pytest.mark.browser_runtime


def test_valid_mermaid_renders_svg() -> None:
    body = "\n".join(
        [
            "Runtime Mermaid fixture.",
            "",
            "```mermaid",
            "graph TD",
            "    A --> B",
            "```",
        ]
    )

    with serve_rendered_workspace(body) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            unexpected_external_requests = install_offline_esm_routes(context)
            page = context.new_page()

            page.goto(url, wait_until="domcontentloaded")
            page.locator('[data-testid="vault-mermaid-rendered"] svg').wait_for()

            block = page.locator('[data-testid="vault-mermaid-block"]').first
            assert block.get_attribute("data-mermaid-state") == "rendered"
            assert page.locator('[data-testid="stub-mermaid-svg"]').count() == 1
            assert page.locator('[data-testid="failed-embed"][data-kind="mermaid"]').count() == 0
            assert unexpected_external_requests == []
        finally:
            browser.close()


def test_broken_mermaid_uses_failed_embed_partial() -> None:
    body = "\n".join(
        [
            "Runtime Mermaid failure fixture.",
            "",
            "```mermaid",
            "graph TD",
            "    BROKEN_CLIENT_RENDER",
            "```",
        ]
    )

    with serve_rendered_workspace(body) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            unexpected_external_requests = install_offline_esm_routes(context)
            page = context.new_page()

            page.goto(url, wait_until="domcontentloaded")
            page.locator('[data-testid="failed-embed"][data-kind="mermaid"]').wait_for()

            failed = page.locator('[data-testid="failed-embed"][data-kind="mermaid"]').first
            assert failed.get_attribute("data-mermaid-state") == "failed"
            assert failed.get_attribute("data-diagnostic-code") == "mermaid_render_error"
            assert page.locator('[data-testid="vault-mermaid-source"]').count() == 1
            assert page.locator('[data-testid="vault-mermaid-rendered"] svg').count() == 0
            assert unexpected_external_requests == []
        finally:
            browser.close()
