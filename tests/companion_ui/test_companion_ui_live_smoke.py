"""Playwright LIVE smoke: a running Companion UI gateway is not stuck in an
error state (#2123/#2124 operational guard).

Unlike the offline render/interaction tests, this loads a REAL running gateway
(dev 8111 / test 8112 / prod 8113) in a browser and asserts:

  (a) the health proxy reports ok — the gateway can reach its backend hop; and
  (b) the entry surface is NOT rendering any runtime-unavailable / wrong-device
      / vault-unreachable error state.

This is the check that catches an *operational* outage a unit test cannot: a
down backend hop, or a stale gateway process rendering an error screen — the
2026-06-19 dev incident, where the page showed "RUNTIME UNAVAILABLE [Errno 61]"
while the API container itself was healthy.

Opt-in only. Set COMPANION_UI_SMOKE_URL to the gateway root, e.g.

    COMPANION_UI_SMOKE_URL=http://10.42.42.10:8111/ \
        pytest tests/companion_ui/test_companion_ui_live_smoke.py

With the env var unset (CI / default suite) the module skips cleanly, so this
never becomes a PR gate that would fail whenever a runtime is legitimately down.

Run it on the deploy host against loopback (``http://127.0.0.1:<ui-port>/``) as a
post-deploy/UAT check — e.g. right after ``make dev-ui``. From a remote macOS
machine, point it at a LAN/Tailscale address only if the Chromium binary has
been granted Local Network access; otherwise loopback (an SSH tunnel) avoids the
macOS Local Network privacy control, which blocks un-permissioned binaries from
LAN addresses while loopback is exempt.
"""

from __future__ import annotations

import os
from urllib.parse import urljoin

import pytest

_SMOKE_URL = os.environ.get("COMPANION_UI_SMOKE_URL")
_EXPECTED_CHANNEL = os.environ.get("COMPANION_UI_EXPECTED_CHANNEL")
if not _SMOKE_URL:
    pytest.skip(
        "Set COMPANION_UI_SMOKE_URL=<gateway root URL> to run the live UI smoke.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
except ImportError:
    pytest.skip(
        "playwright package not installed — skipping live UI smoke.",
        allow_module_level=True,
    )

pytestmark = pytest.mark.browser_runtime

# Any of these testids in the rendered DOM means the gateway is serving an error
# entry state rather than a usable surface.
_ERROR_TESTIDS = (
    "workspace-error-state",
    "workspace-wrong-device-state",
    "workspace-vault-unreachable-state",
)


def test_live_gateway_is_healthy_and_not_in_error_state() -> None:
    base = _SMOKE_URL if _SMOKE_URL.endswith("/") else _SMOKE_URL + "/"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()

            # (a) the gateway can reach its backend: the health proxy is ok.
            health = page.request.get(urljoin(base, "api/operator/health"))
            assert health.ok, f"health proxy HTTP {health.status}"
            payload = health.json()
            assert payload.get("ok") is True, f"health not ok: {payload!r}"

            # (b) the rendered entry surface is not stuck in an error state.
            response = page.goto(base, wait_until="domcontentloaded")
            assert response is not None and response.ok, (
                f"gateway root HTTP {getattr(response, 'status', 'n/a')}"
            )
            for testid in _ERROR_TESTIDS:
                count = page.locator(f'[data-testid="{testid}"]').count()
                assert count == 0, f"gateway rendering error state: {testid}"

            # The other half of the 2026-06-19 symptom: a process serving the
            # unreachable entry-state affordances while the backend reports
            # healthy. workspace-entry-retry renders only in the no_vault error
            # path, so its presence on an otherwise-"healthy" page is the
            # stale-/wrong-render fingerprint.
            assert (
                page.locator('[data-testid="workspace-entry-retry"]').count() == 0
            ), "healthy gateway is rendering error-state affordances"

            # positive signal: a real Companion UI shell rendered (orientation on
            # the bare root; the note shell if a vault auto-opened a document).
            title = page.title() or ""
            assert ("Workspace Orientation" in title) or (
                "Real-Note Workspace" in title
            ), f"unexpected page title: {title!r}"

            if _EXPECTED_CHANNEL:
                marker = page.locator('[data-testid="workspace-vault-channel"]').first
                assert marker.count() == 1, "runtime channel marker missing"
                marker_text = (marker.text_content() or "").lower()
                assert _EXPECTED_CHANNEL.lower() in marker_text, (
                    f"runtime channel marker {marker_text!r} did not match "
                    f"{_EXPECTED_CHANNEL!r}"
                )
        finally:
            browser.close()
