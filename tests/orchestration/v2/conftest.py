"""Fixtures for Orchestrator V2 tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional

import pytest


@dataclass
class MockCheckpoint:
    """Checkpoint state: step_id + state_snapshot + timestamp."""
    step_id: str
    state_snapshot: Dict[str, Any]
    timestamp: float


@dataclass
class MockStepState:
    """Step execution state."""
    step_id: str
    node_name: str
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    status: str = "pending"  # pending, running, completed, failed, rolled_back
    latency_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MockPlanState:
    """Orchestrator plan state contract."""
    plan_id: str
    steps: List[MockStepState]
    current_step_idx: int = 0
    checkpoints: List[MockCheckpoint] = None
    status: str = "pending"  # pending, running, completed, failed, rolled_back
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if self.checkpoints is None:
            self.checkpoints = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_idx": self.current_step_idx,
            "checkpoints": [
                {
                    "step_id": c.step_id,
                    "state_snapshot": c.state_snapshot,
                    "timestamp": c.timestamp,
                }
                for c in self.checkpoints
            ],
            "status": self.status,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MockPlanState:
        """Deserialize from JSON-compatible dict."""
        steps = [
            MockStepState(
                step_id=s["step_id"],
                node_name=s["node_name"],
                input=s["input"],
                output=s.get("output"),
                status=s.get("status", "pending"),
                latency_ms=s.get("latency_ms", 0),
                error=s.get("error"),
            )
            for s in data.get("steps", [])
        ]
        checkpoints = [
            MockCheckpoint(
                step_id=c["step_id"],
                state_snapshot=c["state_snapshot"],
                timestamp=c["timestamp"],
            )
            for c in data.get("checkpoints", [])
        ]
        return cls(
            plan_id=data["plan_id"],
            steps=steps,
            current_step_idx=data.get("current_step_idx", 0),
            checkpoints=checkpoints,
            status=data.get("status", "pending"),
            error=data.get("error"),
        )


class MockObjectStore:
    """In-memory mock ObjectStore."""

    def __init__(self) -> None:
        self.store: Dict[str, Dict[str, Any]] = {}

    def put_object(self, key: str, obj: Dict[str, Any]) -> None:
        self.store[key] = obj

    def get_object(self, key: str) -> Optional[Dict[str, Any]]:
        return self.store.get(key)

    def delete_object(self, key: str) -> None:
        self.store.pop(key, None)


class MockOutbox:
    """In-memory mock Outbox for events."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(self, event: Dict[str, Any]) -> None:
        self.events.append(event)

    def list_events(self, event_type: str = None) -> List[Dict[str, Any]]:
        if event_type:
            return [e for e in self.events if e.get("event") == event_type]
        return self.events.copy()

    def clear(self) -> None:
        self.events.clear()


class MockAgentExecutor:
    """Mock agent for step execution."""

    def __init__(self, default_result: Dict[str, Any] = None) -> None:
        self.default_result = default_result or {"status": "ok"}
        self.executed_steps: List[str] = []
        self.step_results: Dict[str, Dict[str, Any]] = {}

    def execute(self, step_id: str, input_data: Dict[str, Any] = None) -> Dict[str, Any]:
        self.executed_steps.append(step_id)
        result = self.step_results.get(step_id, self.default_result)
        return result.copy()

    def set_step_result(self, step_id: str, result: Dict[str, Any]) -> None:
        self.step_results[step_id] = result

    def reset(self) -> None:
        self.executed_steps.clear()
        self.step_results.clear()


@pytest.fixture
def mock_object_store() -> MockObjectStore:
    """In-memory object store for checkpoints."""
    return MockObjectStore()


@pytest.fixture
def mock_outbox() -> MockOutbox:
    """In-memory outbox for events."""
    return MockOutbox()


@pytest.fixture
def mock_agent_executor() -> MockAgentExecutor:
    """Mock agent for deterministic step execution."""
    return MockAgentExecutor()


@pytest.fixture
def plan_factory() -> Callable:
    """Factory for creating test plans with configurable structure."""

    def _make_plan(
        plan_id: str = None,
        steps: List[Dict[str, Any]] = None,
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        if not plan_id:
            plan_id = f"plan-{uuid.uuid4()}"

        if not steps:
            steps = []

        return {
            "id": plan_id,
            "meta": {
                "goal": "Test plan",
                "source_object_uuid": str(uuid.uuid4()),
                "created_by": "test",
                "trace_id": str(uuid.uuid4()),
            },
            "steps": steps,
            "trigger": None,
            "context": context or {},
            "tags": [],
        }

    return _make_plan


@pytest.fixture
def step_factory() -> Callable:
    """Factory for creating test plan steps."""

    def _make_step(
        step_id: str = None,
        kind: str = "agent_call",
        description: str = "Test step",
        agent: str = None,
        tool: str = None,
        depends_on: List[str] = None,
        compensate_fn: str = None,
        retry_count: int = 0,
        timeout_ms: int = None,
    ) -> Dict[str, Any]:
        if not step_id:
            step_id = f"step-{uuid.uuid4()}"

        step = {
            "id": step_id,
            "kind": kind,
            "description": description,
            "agent": agent,
            "intent": "analyze" if kind == "agent_call" else None,
            "tool": tool,
            "tool_args": {},
            "depends_on": depends_on or [],
            "metadata": {},
        }

        # Add V2-specific fields
        if compensate_fn:
            step["metadata"]["compensate_fn"] = compensate_fn
        if retry_count:
            step["metadata"]["retry_count"] = retry_count
        if timeout_ms:
            step["metadata"]["timeout_ms"] = timeout_ms

        return step

    return _make_step


@pytest.fixture
def canonical_event_envelope() -> Dict[str, Any]:
    """Template for canonical event envelope."""
    return {
        "event": "",
        "event_id": str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "source": "orchestrator.v2",
        "timestamp": 0.0,
        "payload": {},
        "meta": {},
    }
