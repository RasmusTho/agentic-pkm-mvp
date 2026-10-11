"""Actual managed Focus shell and listener with finite external source fixtures."""
from __future__ import annotations

import os
from pathlib import Path
import re
from urllib.parse import urlencode

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip("Set COMPANION_UI_BROWSER_TESTS=1 for Focus browser regressions", allow_module_level=True)

from playwright.sync_api import expect

from tests.builderops.focus_owner_facts_fixture import owner_source
from tests.builderops.test_devui_runtime import managed_sources  # noqa: F401
from tests.companion_ui.focus_jev_advisory import CASES, MIXED_SUBJECT, SUBJECT, capture_observation, expected
from tests.companion_ui.test_devui_managed_journeys import ORIGIN, _browser, _loaded, _no_persistence, _server

pytestmark = pytest.mark.browser_runtime


@pytest.mark.parametrize("case_id", CASES)
@pytest.mark.parametrize("width", [1366, 900], ids=["desktop", "narrow-pane"])
def test_focus_owner_fact_identity_matrix(managed_sources, monkeypatch, case_id, width):  # noqa: F811
    source = managed_sources
    subject = SUBJECT if case_id == "canonical-complete" else MIXED_SUBJECT
    wanted = expected(case_id)
    with (
        owner_source(monkeypatch, case_id) as (collection, source_calls),
        _server(source, monkeypatch),
        _browser() as (page, context, _instance, external, requests, errors, console),
    ):
        page.set_viewport_size({"width": width, "height": 900})
        context.tracing.start(screenshots=True, snapshots=True)
        try:
            with page.expect_response(lambda r: "/api/devui/focus?" in r.url) as read:
                response = page.goto(ORIGIN + "/devui/focus?" + urlencode({"subject": subject}))
            assert response.status == read.value.status == 200
            _loaded(page, "focus")
            payload = read.value.json()
            assert payload["subject"]["stable_id"] == subject
            assert payload["subject"]["authority_ref"]["locator"] == "https://github.com/Example/Fixture/issues/501"
            expect(page.get_by_test_id("focus-owner-intent")).to_contain_text("Fixture owner intent.")
            claims = {row["claim_id"].split(":", 1)[0]: row for row in payload["evidence"]}
            prefixes = {"ready_to_try": "Exact candidate is ready to try", "owner_trial": "Owner trial:",
                "owner_acceptance": "Owner decision:", "owner_ask": "Canonical owner ask:"}
            for flag, kind in (("readiness", "ready_to_try"), ("trial", "owner_trial"), ("acceptance", "owner_acceptance"), ("ask", "owner_ask")):
                assert (kind in claims) is wanted[flag], (case_id, kind)
                if kind in claims:
                    visible = page.get_by_test_id("focus-evidence").locator(".owner-summary span").get_by_text(claims[kind]["claim"], exact=True)
                    expect(visible).to_be_visible()
                else:
                    expect(page.get_by_test_id("focus-evidence")).not_to_contain_text(re.compile(re.escape(prefixes[kind])))
            for kind in ("owner_trial", "owner_acceptance"):
                if kind in claims:
                    receipt = collection["subjects"][0]["facts"][kind]
                    assert claims[kind]["source_ref"]["source_id"] == receipt["id"]
                    assert claims[kind]["source_ref"]["version"] == receipt["hash"]
                    linked = next(row for row in payload["receipts"] if row["receipt_ref"] == receipt["id"])
                    assert linked["correlation"]["authority_ref"] == payload["subject"]["authority_ref"]
            unavailable = [row for row in payload["limitations"] if row["kind"] == "owner_facts_unavailable"]
            assert bool(unavailable) is wanted["unavailable"]
            if unavailable:
                visible = page.get_by_test_id("focus-limitations").locator(".owner-summary span").get_by_text(unavailable[0]["reason"], exact=True)
                expect(visible).to_be_visible()
            assert payload["next_legal_step"]["legality"] == "unavailable"
            expect(page.get_by_test_id("focus-next-step")).to_contain_text("unavailable")
            assert page.get_by_role("button").count() == 0
            assert source_calls == [("GET", "/v1/receipts/owner-facts/current")]
            assert all(method == "GET" for method, _url in requests)
            assert errors == console == external == []
            _no_persistence(page, context)
            folder = os.environ.get("COMPANION_UI_JEV_OBSERVATIONS_DIR")
            if folder:
                capture_observation(page, case_id=case_id, width=width,
                    source_sha=os.environ["COMPANION_UI_JEV_SOURCE_SHA"], output_dir=Path(folder))
        finally:
            folder = os.environ.get("DEVUI_MANAGED_EVIDENCE_DIR")
            if folder:
                path = Path(folder); path.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path / f"{case_id}-{width}.png"), full_page=True)
                context.tracing.stop(path=str(path / f"{case_id}-{width}.zip"))
            else:
                context.tracing.stop()
