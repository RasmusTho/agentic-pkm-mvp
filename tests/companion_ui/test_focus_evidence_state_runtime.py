"""Production managed Focus aggregation and shell with synthetic source inputs."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip("Set COMPANION_UI_BROWSER_TESTS=1 for Focus state regressions", allow_module_level=True)

from playwright.sync_api import expect

from tests.builderops.test_devui_runtime import managed_sources  # noqa: F401
from tests.companion_ui.focus_evidence_fixture import CASES, SUBJECT, expected, inputs
from tests.companion_ui.focus_state_jev_advisory import capture_observation
from tests.companion_ui.test_devui_managed_journeys import FOCUS, ORIGIN, _browser, _loaded, _no_persistence, _server

pytestmark = pytest.mark.browser_runtime


@pytest.mark.parametrize("case_id", CASES)
@pytest.mark.parametrize("width", [1366, 900], ids=["desktop", "narrow-pane"])
def test_focus_evidence_state_matrix(managed_sources, monkeypatch, case_id, width):  # noqa: F811
    raw = inputs(case_id)
    original_evidence = deepcopy(raw["evidence"])
    reads = []
    def reader(config, subject):
        assert config.repository == "example/fixture" and subject == SUBJECT
        reads.append(subject)
        return raw
    monkeypatch.setattr("app.builderops.devui_runtime.read_managed_focus", reader)
    with _server(managed_sources, monkeypatch), _browser() as (page, context, _instance, external, requests, errors, console):
        page.set_viewport_size({"width": width, "height": 900})
        context.tracing.start(screenshots=True, snapshots=True)
        try:
            with page.expect_response(lambda r: "/api/devui/focus?" in r.url) as read:
                response = page.goto(ORIGIN + FOCUS)
            assert response.status == read.value.status == 200
            _loaded(page, "focus")
            payload = read.value.json(); wanted = expected(case_id)
            assert payload["state"] == wanted["focus_state"]
            expect(page.get_by_test_id("focus-load-state")).to_have_text("Server state: " + wanted["focus_state"])
            assert payload["subject"]["stable_id"] == SUBJECT
            row = payload["evidence"][0]
            assert all(row[key] == value for key, value in original_evidence[0].items())
            assert raw["evidence"] == original_evidence
            warning = page.locator("[data-testid='focus-evidence'] .owner-warning, [data-testid='focus-governing-sources'] .owner-warning")
            if wanted["warning"]:
                expect(warning.first).to_be_visible()
            else:
                expect(warning).to_have_count(0)
            if wanted["zero_result"]:
                expect(page.get_by_test_id("focus-evidence")).to_contain_text("No receipts exist in the measured subject scope.")
                assert row["read_watermark"] == "fixture-scope:0"
            if case_id in {"stale-empty", "unknown-empty"}:
                expect(warning).to_contain_text("the source is stale" if case_id == "stale-empty" else "source timing is unknown")
            assert payload["next_legal_step"] == raw["next_legal_step"]
            expect(page.get_by_test_id("focus-next-step")).to_contain_text("No operation is authorized")
            assert payload["next_legal_step"]["legality"] == "unavailable" and page.get_by_role("button").count() == 0
            assert reads == [SUBJECT] and all(method == "GET" for method, _url in requests)
            assert errors == console == external == []
            _no_persistence(page, context)
            folder = os.environ.get("COMPANION_UI_JEV_OBSERVATIONS_DIR")
            if folder:
                capture_observation(page, case_id=case_id, width=width, source_sha=os.environ["COMPANION_UI_JEV_SOURCE_SHA"], output_dir=Path(folder))
        finally:
            folder = os.environ.get("DEVUI_MANAGED_EVIDENCE_DIR")
            if folder:
                path = Path(folder); path.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path / f"{case_id}-{width}.png"), full_page=True)
                context.tracing.stop(path=str(path / f"{case_id}-{width}.zip"))
            else:
                context.tracing.stop()
