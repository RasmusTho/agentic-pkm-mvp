"""Issue #982: proposal-only outputs remain bounded and human-readable.

These tests run the real PanelAgent LangGraph and confirm that proposal-only
cognitive capabilities (capability_class in {proposal, retrieval,
clarification, orientation, synthesis_review}; authority_class in
{read-only, proposal}) produce bounded, human-readable receipts and do not
emit governance-bearing downstream events.
"""

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


def _proposal_only_catalog() -> PanelActionCatalog:
    return PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="proposal.next_actions",
                intent_type="proposal",
                downstream_event="panel.proposal.next_actions",
                labels=["Suggest next actions"],
                description="Propose bounded next-step suggestions.",
                llm_hint="Use for next-step suggestions.",
                capability_class="proposal",
                authority_class="proposal",
                requires_human_gate=False,
            ),
            PanelActionDescriptor(
                id="retrieval.related_notes",
                intent_type="retrieval",
                downstream_event="panel.retrieval.related_notes",
                labels=["Show related notes"],
                description="Return candidate related notes for orientation.",
                llm_hint="Use for related-material queries.",
                capability_class="retrieval",
                authority_class="read-only",
                requires_human_gate=False,
            ),
        ]
    )


def test_proposal_outputs_remain_bounded(monkeypatch) -> None:
    """#982 AC: Proposal outputs remain bounded and human-readable.

    A proposal-only capability surfaces its outcome as a bounded panel.action.logged
    receipt that contains only structured, human-readable fields (action id,
    label, checked-state, mapping, reason). No raw model output is leaked
    into the receipt; the receipt itself is the bounded surface the human
    reviews. No durable governance-bearing event is emitted.
    """
    catalog = _proposal_only_catalog()
    note = NoteRef(
        uuid="panel-bounded-00000000-0000-4000-8000-000000000001",
        path="vault/Bounded.md",
        origin="vault",
    )
    panel = PanelInfo(panel_id="p1", instruction="What should I do next?", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-#982-bounded")
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
        lambda: _StubReasoningFacade(
            {"actions": [{"id": "proposal.next_actions", "reason": "instruction asks for next steps"}]}
        ),
    )

    result = run_panel_graph(state, decider_mode="llm")

    action_results = {r.id: r for r in result.action_results}
    proposal_result = action_results["proposal.next_actions"]
    assert proposal_result.status == "logged"
    assert proposal_result.label == "Suggest next actions"
    assert proposal_result.intent_type == "proposal"
    assert isinstance(proposal_result.details, dict)

    event_names = [getattr(evt, "event", None) for evt in result.emitted_events]
    assert "panel.intent.executed" in event_names
    assert "panel.log.created" in event_names
    assert "panel.action.logged" in event_names
    assert "promote.intent.created" not in event_names
    assert "note.archive" not in event_names

    logged_events = [
        evt for evt in result.emitted_events
        if getattr(evt, "event", None) == "panel.action.logged"
        and getattr(evt, "payload", {}).get("action", {}).get("id") == "proposal.next_actions"
    ]
    assert logged_events, "expected a panel.action.logged receipt for the proposal"
    logged_payload = logged_events[0].payload
    payload_keys = set(logged_payload.keys())
    # `cognition_metadata` is a bounded scalar observability field (provider,
    # model, route, mode, counts, fallback flags) attached by #984. It is not
    # raw model output and is part of the bounded receipt contract.
    assert payload_keys <= {
        "note",
        "panel_id",
        "action",
        "reason",
        "mapping",
        "cognition_metadata",
    }
    cognition_metadata = logged_payload.get("cognition_metadata") or {}
    assert set(cognition_metadata).issubset(
        {
            "cognition_mode",
            "route",
            "provider",
            "model",
            "fallback_used",
            "fallback_reason",
            "proposal_candidate_count",
            "proposal_accepted_count",
            "proposal_rejected_count",
            "no_match",
        }
    ), f"cognition_metadata leaked unexpected keys: {sorted(cognition_metadata)}"
