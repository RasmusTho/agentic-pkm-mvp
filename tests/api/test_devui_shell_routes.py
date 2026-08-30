from __future__ import annotations

import asyncio

from app.api.routes import devui as devui_route


def test_real_now_subject_gets_only_verified_visual_focus_target(monkeypatch) -> None:
    subject = "github:RasmusTho/agentic-pkm-mvp#4836"
    candidate = {
        "subject_ref": {
            "source_type": "github_issue",
            "source_id": subject,
            "locator": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4836",
            "version": "2026-08-28T10:00:00+00:00",
        },
        "display_label": "Connected devUI shell",
        "reason": "Source-owned working placement.",
        "evidence": [],
        "navigation_refs": [],
        "limitations": [],
    }
    monkeypatch.setattr(
        devui_route,
        "compose_owner_snapshot",
        lambda **_kwargs: {"providers": {"work": {"status": "available"}}},
    )
    monkeypatch.setattr(
        devui_route,
        "derive_overview_inputs",
        lambda **_kwargs: {"now": [candidate]},
    )
    monkeypatch.setattr(
        devui_route,
        "compose_overview_view",
        lambda *, composition, candidates: candidates,
    )

    payload = asyncio.run(devui_route.overview())

    assert payload["now"][0]["navigation_refs"] == [
        {
            "kind": "focus",
            "navigation_ref": {
                "source_type": "devui_focus_route",
                "source_id": subject,
                "locator": "/devui/focus?subject=github%3ARasmusTho%2Fagentic-pkm-mvp%234836",
                "version": "focus-view.v1",
            },
            "status": "available",
            "limitation": None,
        }
    ]
