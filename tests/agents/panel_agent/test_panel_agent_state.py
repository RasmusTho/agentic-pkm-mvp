"""Issue #979: PanelAgentState separates proposed actions from executable actions."""

from __future__ import annotations

import pytest

from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.state import PanelAgentState
from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import (
    PanelActionCatalog,
    PanelActionDescriptor,
)
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentEvent,
    PanelIntentPayload,
)


@pytest.fixture(autouse=True)
def _avoid_wiring_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.graph.get_default_action_wiring", lambda: {}
    )


@pytest.fixture(autouse=True)
def _reset_idempotency_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.graph._IDEMPOTENCY_GUARD",
        IdempotencyGuard(ttl_seconds=86400.0),
    )


class _StubReasoningFacade:
    def __init__(self, response: object) -> None:
        self._response = response

    def structured(self, messages, schema, *, task_kind: str, trace_id: str | None = None):
        return self._response


def test_panel_state_separates_proposed_and_executable_actions(monkeypatch) -> None:
    """AC: Runtime state separates proposed actions from executable actions.

    Freeform LLM proposals for governance-bearing capabilities populate
    `proposed_action_ids` but NOT `executed_action_ids`. They are distinct
    state slots so downstream consumers can reason about "offered" vs
    "applied" without conflating them.
    """
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen"],
                description="Promote to evergreen",
                llm_hint="Use for promotion.",
                params={"maturity": "evergreen"},
            )
        ]
    )
    note = NoteRef(
        uuid="panel-split-00000000-0000-4000-8000-000000000001",
        path="vault/Split.md",
        origin="vault",
    )
    panel = PanelInfo(panel_id="p1", instruction="Make this note evergreen.", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-#979-split")
    state = PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[],
        intent_event=intent,
        action_catalog=catalog,
    )

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")

    # Distinct state slots:
    assert "promote.evergreen" in (result.proposed_action_ids or [])
    assert "promote.evergreen" not in (result.executed_action_ids or [])
    # The two collections do not overlap for the freeform-proposal case.
    assert not (
        set(result.proposed_action_ids or []) & set(result.executed_action_ids or [])
    )
