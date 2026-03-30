"""Test Orchestrator V2 state contract: plan, step, checkpoint schemas."""

from __future__ import annotations

import json
import time


from .conftest import (
    MockCheckpoint,
    MockPlanState,
    MockStepState,
)


class TestOrchestratorStateContract:
    """Define state contract for Orchestrator V2."""

    def test_step_state_has_required_fields(self) -> None:
        """Step state must include: step_id, node_name, input, output, status, latency_ms, error."""
        step = MockStepState(
            step_id="step-1",
            node_name="agent-call",
            input={"task": "analyze"},
        )

        assert step.step_id == "step-1"
        assert step.node_name == "agent-call"
        assert step.input == {"task": "analyze"}
        assert step.output is None
        assert step.status == "pending"
        assert step.latency_ms == 0
        assert step.error is None

    def test_step_state_with_output_and_status(self) -> None:
        """Step state may have output and status set after execution."""
        step = MockStepState(
            step_id="step-1",
            node_name="agent-call",
            input={"task": "analyze"},
            output={"result": "ok"},
            status="completed",
            latency_ms=150,
        )

        assert step.output == {"result": "ok"}
        assert step.status == "completed"
        assert step.latency_ms == 150

    def test_step_state_with_error(self) -> None:
        """Step state tracks error message when execution fails."""
        step = MockStepState(
            step_id="step-1",
            node_name="agent-call",
            input={"task": "analyze"},
            status="failed",
            error="Agent timeout",
        )

        assert step.status == "failed"
        assert step.error == "Agent timeout"

    def test_plan_state_has_required_fields(self) -> None:
        """Plan state must include: plan_id, steps[], current_step_idx, checkpoints[], status, error."""
        steps = [
            MockStepState("step-1", "agent-call", {"task": "analyze"}),
            MockStepState("step-2", "agent-call", {"task": "decide"}),
        ]
        plan = MockPlanState(
            plan_id="plan-1",
            steps=steps,
            current_step_idx=0,
            checkpoints=[],
            status="pending",
            error=None,
        )

        assert plan.plan_id == "plan-1"
        assert len(plan.steps) == 2
        assert plan.current_step_idx == 0
        assert plan.checkpoints == []
        assert plan.status == "pending"
        assert plan.error is None

    def test_plan_state_transitions(self) -> None:
        """Plan state status flows: pending -> running -> completed."""
        plan = MockPlanState(
            plan_id="plan-1",
            steps=[MockStepState("step-1", "agent-call", {})],
            status="pending",
        )

        plan.status = "running"
        assert plan.status == "running"

        plan.status = "completed"
        assert plan.status == "completed"

    def test_plan_state_error_transition(self) -> None:
        """Plan status can transition to failed with error message."""
        plan = MockPlanState(
            plan_id="plan-1",
            steps=[MockStepState("step-1", "agent-call", {})],
            status="running",
        )

        plan.status = "failed"
        plan.error = "Step execution timeout"

        assert plan.status == "failed"
        assert plan.error == "Step execution timeout"

    def test_checkpoint_state_has_required_fields(self) -> None:
        """Checkpoint must store: step_id, state_snapshot (Dict), timestamp."""
        checkpoint = MockCheckpoint(
            step_id="step-2",
            state_snapshot={"result": "ok", "data": [1, 2, 3]},
            timestamp=time.time(),
        )

        assert checkpoint.step_id == "step-2"
        assert checkpoint.state_snapshot == {"result": "ok", "data": [1, 2, 3]}
        assert isinstance(checkpoint.timestamp, float)

    def test_plan_state_serialization_json_roundtrip(self) -> None:
        """Plan state must serialize to JSON and deserialize without loss."""
        original_plan = MockPlanState(
            plan_id="plan-1",
            steps=[
                MockStepState(
                    "step-1",
                    "agent-call",
                    {"task": "analyze"},
                    output={"result": "ok"},
                    status="completed",
                    latency_ms=100,
                ),
            ],
            current_step_idx=1,
            checkpoints=[
                MockCheckpoint(
                    "step-1",
                    {"result": "ok"},
                    time.time(),
                ),
            ],
            status="completed",
        )

        # Serialize to dict (JSON-compatible)
        data = original_plan.to_dict()

        # Verify it's JSON-serializable
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

        # Deserialize back
        loaded_data = json.loads(json_str)
        restored_plan = MockPlanState.from_dict(loaded_data)

        assert restored_plan.plan_id == original_plan.plan_id
        assert len(restored_plan.steps) == len(original_plan.steps)
        assert restored_plan.status == original_plan.status

    def test_plan_state_validation_all_fields_present(self) -> None:
        """All required fields must be present in serialized plan state."""
        plan = MockPlanState(
            plan_id="plan-1",
            steps=[MockStepState("step-1", "agent-call", {})],
        )
        data = plan.to_dict()

        required_fields = {
            "plan_id",
            "steps",
            "current_step_idx",
            "checkpoints",
            "status",
            "error",
        }
        assert all(field in data for field in required_fields)

    def test_step_state_validation_all_fields_present(self) -> None:
        """All required step fields must be present in serialized state."""
        step = MockStepState(
            "step-1",
            "agent-call",
            {"task": "test"},
            output={"ok": True},
            status="completed",
        )
        data = step.to_dict()

        required_fields = {
            "step_id",
            "node_name",
            "input",
            "output",
            "status",
            "latency_ms",
            "error",
        }
        assert all(field in data for field in required_fields)

    def test_checkpoint_validation_all_fields_present(self) -> None:
        """All required checkpoint fields must be present."""
        checkpoint = MockCheckpoint(
            "step-1",
            {"data": "snapshot"},
            time.time(),
        )

        assert hasattr(checkpoint, "step_id")
        assert hasattr(checkpoint, "state_snapshot")
        assert hasattr(checkpoint, "timestamp")
        assert isinstance(checkpoint.state_snapshot, dict)
