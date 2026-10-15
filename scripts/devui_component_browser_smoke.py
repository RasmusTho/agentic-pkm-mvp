#!/usr/bin/env python3
"""Read-only browser proof for the fixed managed DevUI origin; never acceptance."""
from __future__ import annotations

import argparse
import json
from urllib.parse import parse_qs, urlencode, urlsplit


def smoke(source_sha: str, *, preflight: bool = False, baseline: bool = False) -> dict[str, object]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            if preflight:
                return {"browser_launch": True}
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            forbidden: list[str] = []

            def admit(route):  # type: ignore[no-untyped-def]
                request = route.request
                if request.method != "GET" or urlsplit(request.url).netloc != "127.0.0.1:8113":
                    forbidden.append(request.method + " " + request.url)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", admit)
            page = context.new_page()
            page.set_default_timeout(60000)
            origin = "http://127.0.0.1:8113"
            version = context.request.get(origin + "/version", max_redirects=0).json()
            if version.get("source_sha") != source_sha:
                raise RuntimeError("served candidate mismatch")
            response = page.goto(origin + "/devui/overview", wait_until="domcontentloaded")
            if response is None or response.status != 200:
                raise RuntimeError("Overview unavailable")
            page.locator('[data-testid="overview-load-state"][data-state="loaded"]').wait_for()
            if baseline:
                if forbidden:
                    raise RuntimeError("baseline browser effects or egress")
                return {"source_sha": source_sha, "baseline_overview": True,
                        "forbidden_request_count": 0, "owner_acceptance": False}
            page.locator('[data-testid="builder-system-control-entry"]').click()
            page.get_by_role("heading", name="Builder System Control", exact=True).wait_for()
            if page.locator("main").get_attribute("data-primary-identity") != "builder_system":
                raise RuntimeError("system identity missing")
            page.locator('[data-testid="overview-return"]').click()
            page.locator('[data-testid="overview-load-state"][data-state="loaded"]').wait_for()
            control = context.request.get(origin + "/api/devui/builder-system-control", max_redirects=0).json()
            repository = control.get("control", {}).get("scope", {}).get("repository_ref")
            if not isinstance(repository, str) or "/" not in repository:
                raise RuntimeError("repository binding unavailable")
            subject = "github:" + repository + "#6080"
            focus = page.get_by_role("link", name="Open Focus").first
            if focus.count():
                selected = parse_qs(urlsplit(focus.get_attribute("href") or "").query).get("subject", [])
                if len(selected) != 1 or not selected[0].lower().startswith("github:" + repository.lower() + "#"):
                    raise RuntimeError("server Focus binding mismatch")
                subject = selected[0]
            page.goto(origin + "/devui/focus?" + urlencode({"subject": subject}), wait_until="domcontentloaded")
            def require_focus():  # type: ignore[no-untyped-def]
                page.locator('[data-testid="focus-load-state"]:not([data-state="loading"])').wait_for()
                if (page.locator('[data-testid="focus-load-state"]').get_attribute("data-state") != "loaded" or
                        page.locator('[data-testid="focus-subject"]').get_attribute("data-subject") != subject):
                    raise RuntimeError("Focus read or subject mismatch")

            require_focus()
            page.locator('[data-testid="builder-system-control-entry"]').click()
            if page.locator('[data-testid="focus-return"]').get_attribute("href") != "/devui/focus?" + urlencode({"subject": subject}):
                raise RuntimeError("Focus return context mismatch")
            page.locator('[data-testid="focus-return"]').click()
            require_focus()
            if forbidden:
                raise RuntimeError("unexpected browser effects or egress")
            if page.evaluate("localStorage.length + sessionStorage.length"):
                raise RuntimeError("unexpected browser persistence")
            return {"source_sha": source_sha, "overview_system_focus_return": True,
                    "forbidden_request_count": 0, "browser_storage_entries": 0,
                    "owner_acceptance": False, "source_qualification": False}
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", default="")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    arguments = parser.parse_args()
    try:
        print(json.dumps(smoke(arguments.source_sha, preflight=arguments.preflight,
                               baseline=arguments.baseline), sort_keys=True))
    except Exception:
        raise SystemExit("DevUI browser smoke refused; no owner outcome asserted") from None
