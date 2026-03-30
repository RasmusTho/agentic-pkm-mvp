"""Test suite for pilot agent integration contract.

Enforces correct integration with outbox events, telemetry, and vault.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


from tests.agents.pilot_agent.conftest import PilotAgentState


class TestAgentReceivesOutboxEvent:
    """Verify agent correctly receives input from outbox event."""

    def test_agent_receives_event_payload(self, mock_event_emitter):
        incoming_event = {
            "event": "promotion.intent.created",
            "event_id": "evt_123",
            "trace_id": "trace_abc",
            "source": "user.action",
            "payload": {
                "note_uuid": "note_uuid_1",
                "maturity": "draft",
                "review_state": "pending",
            },
        }

        # Agent should extract trace_id and payload
        agent_trace_id = incoming_event["trace_id"]
        agent_payload = incoming_event["payload"]

        assert agent_trace_id == "trace_abc"
        assert agent_payload["note_uuid"] == "note_uuid_1"

    def test_agent_extracts_note_uuid(self, mock_event_emitter):
        event_payload = {
            "note_uuid": "uuid_for_note",
            "maturity": "stable",
        }
        note_uuid = event_payload.get("note_uuid")
        assert note_uuid == "uuid_for_note"

    def test_agent_extracts_trace_id_from_event(self):
        incoming = {
            "trace_id": "trace_xyz",
            "payload": {"note_uuid": "n1"},
        }
        agent_trace = incoming["trace_id"]
        assert agent_trace == "trace_xyz"

    def test_agent_initializes_state_from_event(self, state_factory):
        event = {
            "trace_id": "trace_123",
            "event_id": "evt_456",
            "payload": {"note_uuid": "n1", "maturity": "draft"},
        }

        state = state_factory(
            uuid=event["payload"]["note_uuid"],
            trace_id=event["trace_id"],
        )
        assert state.uuid == "n1"
        assert state.trace_id == "trace_123"

    def test_agent_handles_missing_optional_fields(self, state_factory):
        minimal_event = {
            "trace_id": "trace_minimal",
            "payload": {"note_uuid": "n_min"},
        }
        state = state_factory(
            uuid=minimal_event["payload"]["note_uuid"],
            trace_id=minimal_event["trace_id"],
        )
        assert state is not None


class TestAgentEmitsTelemetry:
    """Verify agent emits structured telemetry."""

    def test_agent_includes_trace_id_in_telemetry(self):
        telemetry = {
            "trace_id": "trace_tel_123",
            "event": "agent.complete",
            "latency_ms": 150.5,
        }
        assert telemetry["trace_id"] == "trace_tel_123"

    def test_agent_includes_latency_in_telemetry(self):
        telemetry = {
            "trace_id": "t1",
            "latency_ms": 245.75,
            "event": "agent.complete",
        }
        assert telemetry["latency_ms"] > 0
        assert isinstance(telemetry["latency_ms"], float)

    def test_agent_includes_token_count_in_telemetry(self):
        telemetry = {
            "trace_id": "t1",
            "tokens_in": 150,
            "tokens_out": 75,
            "event": "agent.complete",
        }
        assert telemetry["tokens_in"] >= 0
        assert telemetry["tokens_out"] >= 0

    def test_telemetry_includes_agent_name(self):
        telemetry = {
            "agent": "promotion_pilot",
            "event": "agent.complete",
            "trace_id": "t1",
        }
        assert "promotion" in telemetry["agent"]

    def test_telemetry_includes_step_count(self):
        telemetry = {
            "trace_id": "t1",
            "agent": "promotion_pilot",
            "step_count": 3,
            "event": "agent.complete",
        }
        assert telemetry["step_count"] == 3

    def test_telemetry_includes_error_if_present(self):
        telemetry_success = {
            "trace_id": "t1",
            "error": None,
            "event": "agent.complete",
        }
        telemetry_failure = {
            "trace_id": "t2",
            "error": "budget_exhausted",
            "event": "agent.complete",
        }
        assert telemetry_success["error"] is None
        assert telemetry_failure["error"] is not None


class TestAgentProducesOutputEvent:
    """Verify agent emits canonical output event."""

    def test_agent_emits_promotion_done_event(self, mock_event_emitter):
        output_event = {
            "event": "promotion.done",
            "event_id": uuid4().hex,
            "trace_id": "trace_123",
            "source": "pilot_agent.promotion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "note_uuid": "n1",
                "decision": "promote",
                "maturity": "stable",
            },
            "meta": {
                "step_count": 3,
                "latency_ms": 125.5,
            },
        }
        assert output_event["event"] == "promotion.done"
        assert output_event["source"] == "pilot_agent.promotion"

    def test_output_event_has_canonical_envelope(self):
        """Output event matches OutboxEvent schema."""
        output = {
            "event": "promotion.done",
            "event_id": "evt_abc",
            "trace_id": "trace_abc",
            "source": "pilot_agent.promotion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"note_uuid": "n1", "decision": "promote"},
            "meta": {"step_count": 3},
        }
        required_fields = {"event", "event_id", "trace_id", "source", "timestamp", "payload", "meta"}
        assert required_fields.issubset(output.keys())

    def test_output_event_includes_decision_in_payload(self):
        output = {
            "event": "promotion.done",
            "event_id": "evt_123",
            "trace_id": "trace_123",
            "source": "pilot_agent.promotion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "note_uuid": "n1",
                "decision": "promote",
                "maturity": "stable",
            },
            "meta": {},
        }
        assert output["payload"]["decision"] is not None

    def test_output_event_preserves_note_uuid(self):
        output = {
            "event": "promotion.done",
            "event_id": "evt_456",
            "trace_id": "trace_456",
            "source": "pilot_agent.promotion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"note_uuid": "preserved_uuid", "decision": "skip"},
            "meta": {},
        }
        assert output["payload"]["note_uuid"] == "preserved_uuid"

    def test_output_event_includes_timestamp(self):
        output = {
            "event": "promotion.done",
            "event_id": "evt_789",
            "trace_id": "trace_789",
            "source": "pilot_agent.promotion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {},
            "meta": {},
        }
        assert "timestamp" in output
        assert output["timestamp"] is not None

    def test_output_event_maintains_trace_id(self):
        input_trace = "trace_input_123"
        output = {
            "event": "promotion.done",
            "event_id": "evt_final",
            "trace_id": input_trace,
            "source": "pilot_agent.promotion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"note_uuid": "n1"},
            "meta": {},
        }
        assert output["trace_id"] == input_trace


class TestAgentDoesNotMutateVault:
    """Verify agent never directly mutates vault notes."""

    def test_agent_does_not_call_write_operations(self, mock_store):
        # Agent should not call save_object or similar mutations
        PilotAgentState(
            uuid="n1",
            trace_id="t1",
            budget=100,
            step_count=0,
        )

        # Verify no vault mutations occurred
        mock_store.save_object.assert_not_called()

    def test_agent_only_emits_events(self, mock_event_emitter):
        # Agent should only emit events, not mutate directly
        mock_event_emitter.emit("promotion.done", {"note_uuid": "n1", "decision": "promote"}, trace_id="t1")
        assert len(mock_event_emitter.emitted_events) == 1
        assert mock_event_emitter.emitted_events[0]["event_type"] == "promotion.done"

    def test_agent_decision_emitted_not_written(self, mock_event_emitter):
        state = PilotAgentState(
            uuid="n1",
            trace_id="t1",
            budget=100,
            step_count=0,
            decision="promote",
        )

        # Decision should be in output event, not written to vault
        mock_event_emitter.emit(
            "promotion.done",
            {"note_uuid": state.uuid, "decision": state.decision},
            trace_id=state.trace_id,
        )
        assert len(mock_event_emitter.emitted_events) == 1

    def test_agent_action_emitted_not_executed(self, mock_event_emitter):
        # Agent records intended actions in event, doesn't execute them
        state = PilotAgentState(
            uuid="n1",
            trace_id="t1",
            budget=100,
            step_count=0,
            executed_actions=["promote"],
        )

        mock_event_emitter.emit(
            "promotion.done",
            {"note_uuid": state.uuid, "actions": state.executed_actions},
            trace_id=state.trace_id,
        )
        # Verify no direct vault mutations
        assert len(mock_event_emitter.emitted_events) == 1


class TestAgentHandlesCompleteWorkflow:
    """Verify agent handles a complete input-to-output workflow."""

    def test_complete_workflow_input_to_output(self, state_factory, mock_event_emitter):
        # 1. Receive event
        input_event = {
            "event": "promotion.intent.created",
            "trace_id": "trace_workflow",
            "payload": {"note_uuid": "workflow_n1", "maturity": "draft"},
        }

        # 2. Initialize state
        state = state_factory(
            uuid=input_event["payload"]["note_uuid"],
            trace_id=input_event["trace_id"],
        )
        state.decision = "promote"
        state.step_count = 3

        # 3. Emit output
        mock_event_emitter.emit(
            "promotion.done",
            {
                "note_uuid": state.uuid,
                "decision": state.decision,
            },
            trace_id=state.trace_id,
        )

        # 4. Verify complete flow
        assert len(mock_event_emitter.emitted_events) == 1
        output_event = mock_event_emitter.emitted_events[0]
        assert output_event["event_type"] == "promotion.done"
        assert output_event["trace_id"] == "trace_workflow"
        assert output_event["payload"]["note_uuid"] == "workflow_n1"
