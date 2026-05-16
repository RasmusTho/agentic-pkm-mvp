"""Issue #984: PanelAgent LLM route and fallback observability.

These tests exercise the real PanelAgent LangGraph to confirm that the
cognition seam emits bounded route/provider/fallback metadata on:

- ``panel.intent.executed`` (via ``PanelIntentExecutedPayload.cognition_metadata``)
- ``panel.log.created`` (via ``PanelLogEntry.cognition_metadata``)
- ``panel.action.logged`` receipts (``proposal_offered``, ``no_actions_matched``)

Metadata fields covered:

- ``cognition_mode`` — ``"rule" | "llm"``
- ``route`` — ``"rule" | "checkbox" | "freeform"``
- ``provider`` / ``model`` — taken from the reasoning facade's telemetry
- ``fallback_used`` / ``fallback_reason``
- ``proposal_candidate_count`` / ``proposal_accepted_count`` /
  ``proposal_rejected_count``
- ``no_match``
"""

from __future__ import annotations

from dataclasses import dataclass

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
    PanelActionLoggedEvent,
    PanelInfo,
    PanelIntentEvent,
    PanelIntentExecutedEvent,
    PanelIntentPayload,
    PanelLogEvent,
)

TEST_NOTE_UUID = "panel-obs-00000000-0000-4000-8000-000000000001"
TEST_NOTE_PATH = "vault/Observability.md"


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


# ---------------------------------------------------------------------------
# Stub reasoning facade with telemetry shape used by `_facade_route_info`.
# ---------------------------------------------------------------------------


@dataclass
class _TelemetryRecord:
    provider: str
    model: str


class _StubReasoningFacade:
    """Reasoning facade stub that mimics provider/model telemetry."""

    def __init__(
        self,
        response: object,
        *,
        provider: str = "anthropic",
        model: str = "claude-stub",
        raise_exc: Exception | None = None,
    ) -> None:
        self._response = response
        self._provider = provider
        self._model = model
        self._raise = raise_exc
        self.telemetry: list[_TelemetryRecord] = []

    def structured(self, messages, schema, *, task_kind: str, trace_id: str | None = None):
        # Telemetry is appended in the real facade's `finally` block — emulate
        # the same contract here (record happens whether or not we raise).
        self.telemetry.append(_TelemetryRecord(provider=self._provider, model=self._model))
        if self._raise is not None:
            raise self._raise
        return self._response


def _catalog() -> PanelActionCatalog:
    return PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen"],
                description="Promote note to evergreen",
                llm_hint="Use for promotion to evergreen.",
                params={"maturity": "evergreen"},
            )
        ]
    )


def _freeform_state(instruction: str = "Make this note evergreen.") -> PanelAgentState:
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(panel_id="p1", instruction=instruction, raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-#984")
    return PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[],
        intent_event=intent,
        action_catalog=_catalog(),
    )


def _executed_payload(events: list[object]):
    for evt in events:
        if isinstance(evt, PanelIntentExecutedEvent):
            return evt.payload
    raise AssertionError("PanelIntentExecutedEvent not found in emitted events")


def _log_entry(events: list[object]):
    for evt in events:
        if isinstance(evt, PanelLogEvent):
            return evt.payload
    raise AssertionError("PanelLogEvent not found in emitted events")


def _logged_events_by_reason(events: list[object], reason: str) -> list[PanelActionLoggedEvent]:
    return [
        evt
        for evt in events
        if isinstance(evt, PanelActionLoggedEvent)
        and (evt.payload or {}).get("reason") == reason
    ]


# ---------------------------------------------------------------------------
# AC 1: cognition_mode metadata emitted on executed event and log entry.
# ---------------------------------------------------------------------------


def test_cognition_mode_metadata_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM route stamps cognition_mode='llm' and route='freeform' onto the executed payload."""
    state = _freeform_state()
    facade = _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]})
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade", lambda: facade
    )

    result = run_panel_graph(state, decider_mode="llm")

    executed = _executed_payload(result.emitted_events)
    assert executed.cognition_mode == "llm"
    assert executed.cognition_metadata["cognition_mode"] == "llm"
    assert executed.cognition_metadata["route"] == "freeform"

    log_entry = _log_entry(result.emitted_events)
    assert log_entry.cognition_metadata["cognition_mode"] == "llm"

    # Rule mode: same fields populated with rule values.
    state2 = _freeform_state()
    result2 = run_panel_graph(state2, decider_mode="rule")
    executed2 = _executed_payload(result2.emitted_events)
    assert executed2.cognition_metadata.get("cognition_mode") == "rule"
    assert executed2.cognition_metadata.get("route") == "rule"


# ---------------------------------------------------------------------------
# AC 2: provider/model metadata for freeform proposal paths.
# ---------------------------------------------------------------------------


def test_provider_and_model_metadata_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider/model from the reasoning facade telemetry surface on the executed payload."""
    state = _freeform_state()
    facade = _StubReasoningFacade(
        {"actions": [{"id": "promote.evergreen"}]},
        provider="anthropic",
        model="claude-sonnet-test",
    )
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade", lambda: facade
    )

    result = run_panel_graph(state, decider_mode="llm")

    executed = _executed_payload(result.emitted_events)
    assert executed.cognition_metadata["provider"] == "anthropic"
    assert executed.cognition_metadata["model"] == "claude-sonnet-test"

    # proposal_offered receipt carries the same provider/model so receipt
    # consumers can correlate proposal surfacing with the cognition route.
    offered = _logged_events_by_reason(result.emitted_events, "proposal_offered")
    assert offered, "expected a proposal_offered receipt for the governance-bearing proposal"
    meta = offered[0].payload.get("cognition_metadata") or {}
    assert meta.get("provider") == "anthropic"
    assert meta.get("model") == "claude-sonnet-test"


# ---------------------------------------------------------------------------
# AC 3: fallback / no-match metadata.
# ---------------------------------------------------------------------------


def test_fallback_and_no_match_metadata_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM error -> rule fallback surfaces fallback_used/fallback_reason; empty LLM result -> no_match."""
    # (a) LLM raises -> fallback_used=True, fallback_reason starts with "llm_error:".
    state_err = _freeform_state()
    facade_err = _StubReasoningFacade(
        response={},
        provider="anthropic",
        model="claude-sonnet-test",
        raise_exc=RuntimeError("simulated provider outage"),
    )
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade", lambda: facade_err
    )
    result_err = run_panel_graph(state_err, decider_mode="llm")
    executed_err = _executed_payload(result_err.emitted_events)
    assert executed_err.cognition_metadata["fallback_used"] is True
    assert executed_err.cognition_metadata["fallback_reason"].startswith("llm_error:")
    assert executed_err.cognition_metadata["provider"] == "anthropic"

    # (b) LLM returns no candidates -> no_match True, no_actions_matched receipt
    #     carries the cognition metadata.
    state_empty = _freeform_state(instruction="Do something unrelated.")
    facade_empty = _StubReasoningFacade(
        response={"actions": []},
        provider="anthropic",
        model="claude-sonnet-test",
    )
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade", lambda: facade_empty
    )
    result_empty = run_panel_graph(state_empty, decider_mode="llm")
    executed_empty = _executed_payload(result_empty.emitted_events)
    assert executed_empty.cognition_metadata["no_match"] is True
    assert executed_empty.cognition_metadata["fallback_used"] is False

    no_match = _logged_events_by_reason(result_empty.emitted_events, "no_actions_matched")
    assert no_match, "expected a no_actions_matched receipt when LLM returned no candidates"
    meta = no_match[0].payload.get("cognition_metadata") or {}
    assert meta.get("no_match") is True
    assert meta.get("route") == "freeform"


# ---------------------------------------------------------------------------
# AC 4: bounded proposal accept/reject counts.
# ---------------------------------------------------------------------------


def test_proposal_acceptance_rejection_metadata_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Out-of-catalog IDs increment the rejected count; in-catalog IDs increment the accepted count."""
    state = _freeform_state()
    facade = _StubReasoningFacade(
        {
            "actions": [
                {"id": "promote.evergreen", "reason": "instruction asks for evergreen"},
                {"id": "not.in.catalog"},
                {"id": "also.unknown"},
            ]
        }
    )
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade", lambda: facade
    )

    result = run_panel_graph(state, decider_mode="llm")
    executed = _executed_payload(result.emitted_events)
    meta = executed.cognition_metadata
    assert meta["proposal_candidate_count"] == 3
    assert meta["proposal_accepted_count"] == 1
    assert meta["proposal_rejected_count"] == 2
    assert meta["no_match"] is False
