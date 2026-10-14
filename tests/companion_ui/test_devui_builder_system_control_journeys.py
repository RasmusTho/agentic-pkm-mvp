"""Real managed Overview/Focus/system-lens navigation and browser evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.builderops.test_devui_runtime import managed_sources  # noqa: F401
from tests.builderops.test_devui_builder_system_control_navigation import prepare_control_sources
from tests.companion_ui.test_devui_managed_journeys import ORIGIN, FOCUS, _server, _browser, _loaded

pytestmark = pytest.mark.browser_runtime
CONTROL = "/devui/builder-system-control"
PRIOR = "?return_subject=github%3Aexample%2Ffixture%23501"
HEADINGS = ["Governance", "Workflows", "Capabilities", "Assurance", "Routes", "Inspect and recovery", "Limitations"]


def test_system_lens_accessibility_and_no_egress(managed_sources, monkeypatch) -> None:  # noqa: F811
    source = managed_sources
    prepare_control_sources(source)
    source.environment.update(DEVUI_DIAGNOSTIC_ORIGIN="https://diagnostics.example.test",
                              DEVUI_CKM_OVERVIEW_URL="https://ckm.example.test/overview.html")
    evidence = {"evidence_class": "repository production-route browser proof with isolated synthetic sources; no live qualification",
                "modes": [], "source_states": [], "cross_origin_request_count": 0}
    with _server(source, monkeypatch), _browser() as (page, context, browser, external, requests, errors, console):
        page.goto(ORIGIN + "/devui/overview")
        _loaded(page, "overview")
        entry = page.locator('[data-testid="builder-system-control-entry"]')
        assert entry.get_attribute("href") == CONTROL
        entry.click()
        assert page.locator('main').get_attribute("data-primary-identity") == "builder_system"
        assert page.locator('[data-testid="focus-return"]').count() == 0
        page.locator('[data-testid="overview-return"]').click()
        _loaded(page, "overview")
        page.get_by_role("link", name="Open Focus").click()
        _loaded(page, "focus")
        assert page.locator('[data-testid="builder-system-control-entry"]').get_attribute("href") == CONTROL + PRIOR
        page.locator('[data-testid="builder-system-control-entry"]').click()
        assert page.locator('[data-testid="focus-return"]').get_attribute('href') == FOCUS
        assert "one governed subject" not in page.locator('main').inner_text()
        page.locator('[data-testid="focus-return"]').click()
        _loaded(page, "focus")
        assert page.locator('[data-testid="focus-subject"]').get_attribute('data-subject') == "github:example/fixture#501"
        for mode, viewport in [("desktop", {"width": 1280, "height": 900}), ("narrow", {"width": 390, "height": 844}),
                               ("zoom_200", {"width": 1280, "height": 900}), ("keyboard", {"width": 1280, "height": 900}),
                               ("screen_reader", {"width": 1280, "height": 900}), ("print", {"width": 1280, "height": 900})]:
            page.set_viewport_size(viewport)
            page.goto(ORIGIN + CONTROL + PRIOR)
            if mode == "zoom_200":
                page.evaluate("document.documentElement.style.zoom='2'")
            if mode == "print":
                page.emulate_media(media="print")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), mode
            for label in HEADINGS:
                assert page.get_by_role("heading", name=label, exact=True).is_visible(), (mode, label)
            assert page.get_by_role("heading", name="Builder System Control", exact=True).count() == 1
            assert "unsupported" in page.locator('main').inner_text()
            assert "Opening Signboard triggers a refresh POST" in page.locator('main').inner_text()
            assert page.locator('a[href^="https://"]').count() > 0
            for link in page.locator('a[href^="https://"]').all():
                assert link.get_attribute('target') == '_blank'
                assert link.get_attribute('rel') == 'noopener noreferrer'
            if mode == "keyboard":
                page.keyboard.press('Tab')
                assert page.locator(':focus').get_attribute('data-testid') == 'overview-return'
                page.keyboard.press('Tab')
                assert page.locator(':focus').get_attribute('data-testid') == 'focus-return'
                page.keyboard.press('Tab')
                assert page.locator(':focus').evaluate('e=>e.tagName') == 'SUMMARY'
                page.keyboard.press('Enter')
                assert page.locator('details').first.get_attribute('open') is not None
            if mode == "screen_reader":
                aria = page.locator('main').aria_snapshot()
                for name in [*HEADINGS, 'Return to prior Focus', 'Inspect source and technical details']:
                    assert name in aria
            evidence['modes'].append({"mode": mode, "passed": True})
            folder = os.environ.get('DEVUI_BSC_EVIDENCE_DIR')
            if folder and mode in {'desktop', 'narrow', 'print'}:
                Path(folder).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(folder) / (mode + '.png')), full_page=True)
                (Path(folder) / (mode + '.aria.txt')).write_text(page.locator('main').aria_snapshot())
            page.emulate_media(media='screen')
        disabled = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
        nojs = disabled.new_page()
        nojs.on('request', lambda r: requests.append((r.method, r.url)))
        nojs.goto(ORIGIN + CONTROL + PRIOR)
        for label in HEADINGS:
            assert nojs.get_by_role('heading', name=label, exact=True).is_visible()
        assert nojs.locator('[data-testid="focus-return"]').get_attribute('href') == FOCUS
        assert nojs.locator('script').count() == 0
        evidence['modes'].append({"mode": 'javascript_off', "passed": True})
        disabled.close()
        # Source-specific failures are induced on the actual candidate-backed route.
        file = source.root / 'docs/DEVUI.md'
        original = file.read_bytes()
        for state in ('fresh', 'refused', 'unavailable'):
            if state == 'refused':
                file.write_text('changed after candidate packaging')
            elif state == 'unavailable':
                file.unlink()
            response = context.request.get(ORIGIN + '/api/devui/builder-system-control' + PRIOR)
            assert response.ok
            payload = response.json()
            document = payload['control']['governing_documents'][0]
            expected = 'available' if state == 'fresh' else state
            assert document['source_state']['availability'] == expected
            page.goto(ORIGIN + CONTROL + PRIOR)
            assert expected in page.locator('section').filter(has=page.get_by_role('heading', name='Governance', exact=True)).inner_text()
            assert page.locator('[data-testid="focus-return"]').get_attribute('href') == FOCUS
            evidence['source_states'].append({"state": state, "source_state": document['source_state'], "text_preserved": True})
        file.write_bytes(original)
        from app.builderops import devui_runtime
        from copy import deepcopy
        original_reader = devui_runtime.read_managed_cockpit

        def stale_reader(config):
            result = deepcopy(original_reader(config))
            for plane in result["sources"]:
                if plane["name"] == "docs-frontmatter":
                    plane["state"] = "stale"
                    plane["detail"] = "Fixture source declares a stale read"
                    result["withdrawn_counts"] = [{"source": "docs-frontmatter", "counts": ["capability_lanes.lanes"]}]
            return result

        monkeypatch.setattr(devui_runtime, "read_managed_cockpit", stale_reader)
        page.goto(ORIGIN + CONTROL + PRIOR)
        for state, heading in [("stale", "Assurance"), ("unread", "Workflows"), ("missing", "Governance"), ("unlinked", "Routes")]:
            section = page.locator('section').filter(has=page.get_by_role('heading', name=heading, exact=True))
            assert state in section.inner_text(), (state, heading)
            evidence['source_states'].append({"state": state, "source_region": heading, "text_preserved": True})
        assert page.evaluate('localStorage.length + sessionStorage.length') == 0
        assert not external and not errors, (external, errors)
        assert all(method == 'GET' for method, _ in requests), requests
        assert all(method == 'GET' for method, _ in source.http_calls), source.http_calls
        evidence['cross_origin_request_count'] = sum(not url.startswith(ORIGIN + '/') for _, url in requests)
        assert evidence['cross_origin_request_count'] == 0, requests
        evidence['browser_request_count'] = len(requests)
    folder = os.environ.get('DEVUI_BSC_EVIDENCE_DIR')
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / 'browser-proof.json').write_text(json.dumps(evidence, sort_keys=True, indent=2) + '\n')
