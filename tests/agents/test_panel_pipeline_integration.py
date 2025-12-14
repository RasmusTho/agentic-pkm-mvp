from __future__ import annotations

import textwrap

import pytest

from app.agents.panel.integration import handle_panel_update
from app.events.types import ASK_QUERY_RECEIVED
from app.orchestrator.handler import OrchestratorContext
from app.settings.panel_actions import PanelActionMapping
from app.stores.plan_store import reset_plan_store


def setup_function() -> None:
    reset_plan_store()


def _markdown(action_prefix: str) -> str:
    return textwrap.dedent(
        f"""
        ## AI-instruktion
        Gör något fint.
        
        ## AI-åtgärder
        - [{action_prefix}] Gör denna anteckning evergreen
        """
    )


def test_handle_panel_update_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PANEL_EVENTS_ENABLE", raising=False)
    mappings = {
        "Gör denna anteckning evergreen": PanelActionMapping(
            text="Gör denna anteckning evergreen",
            event_type="ask.query.received",
        )
    }
    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    result = handle_panel_update(
        note_id="note-dry",
        old_markdown=_markdown(" "),
        new_markdown=_markdown("x"),
        ctx=ctx,
        action_mappings=mappings,
    )

    assert result.panel.events
    assert result.dispatch_count == 0
    assert result.plans == []
    assert "- [x] Gör denna anteckning evergreen" not in result.panel.updated_markdown
    assert "> [!info]- AI status" in result.panel.updated_markdown
    assert "- ✅ Gör denna anteckning evergreen" in result.panel.updated_markdown


def test_handle_panel_update_dispatches_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")
    mappings = {
        "Gör denna anteckning evergreen": PanelActionMapping(
            text="Gör denna anteckning evergreen",
            event_type=ASK_QUERY_RECEIVED,
            payload_template={"question": "What now?", "object_id": "note-dispatch"},
        )
    }
    ctx = OrchestratorContext(settings={"panel_events_enable": True})

    result = handle_panel_update(
        note_id="note-dispatch",
        old_markdown=_markdown(" "),
        new_markdown=_markdown("x"),
        ctx=ctx,
        action_mappings=mappings,
    )

    assert result.dispatch_count == 1
    assert len(result.plans) == 1
    assert result.plans[0].trigger is not None
    assert result.plans[0].trigger.event_type == ASK_QUERY_RECEIVED
    assert any(tag in {"qa", "flow:qa"} for tag in result.plans[0].tags)
