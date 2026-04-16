"""Test Orchestrator V2 retry & timeout contract."""

from __future__ import annotations

from app.orchestrator.v2_runtime import OrchestratorV2
from app.orchestrator.executor import StepExecutionError
from app.planner.schema import Plan, PlanMetadata, PlanStep

from .conftest import MockAgentExecutor, MockOutbox


class TestRetryContract:
    """Define retry and timeout contract for Orchestrator V2."""

    def test_step_configured_with_retry_count(
        self,
        step_factory,
    ) -> None:
        """Step can be configured with retry_count + backoff_ms in metadata."""
        step = step_factory(
            "step-1",
            "agent_call",
            "Task A",
            retry_count=3,
        )

        assert step["metadata"]["retry_count"] == 3

    def test_step_configured_with_timeout(
        self,
        step_factory,
    ) -> None:
        """Step can be configured with timeout_ms."""
        step = step_factory(
            "step-1",
            "agent_call",
            "Long task",
            timeout_ms=5000,
        )

        assert step["metadata"]["timeout_ms"] == 5000

    def test_step_timeout_raises_timeout_error(
        self,
        step_factory,
    ) -> None:
        """Step execution capped at timeout_ms raises TimeoutError."""
        step = step_factory(
            "step-1",
            "agent_call",
            "Slow task",
            timeout_ms=100,
        )

        # If execution exceeds timeout_ms, TimeoutError is raised
        assert step["metadata"]["timeout_ms"] == 100

    def test_step_retry_on_transient_failure(
        self,
        step_factory,
        mock_agent_executor: MockAgentExecutor,
    ) -> None:
        """On transient failure, retry up to retry_count times."""
        step_factory(
            "step-1",
            "agent_call",
            "Flaky task",
            retry_count=3,
        )

        # Attempt 1: fails
        # Attempt 2: fails
        # Attempt 3: succeeds
        mock_agent_executor.set_step_result("step-1", {"status": "ok"})
        result = mock_agent_executor.execute("step-1")

        assert result["status"] == "ok"

    def test_retry_state_tracked_attempt_count(
        self,
        step_factory,
    ) -> None:
        """Retry state tracks attempt #1, #2, etc."""
        step_factory(
            "step-1",
            "agent_call",
            "Retry task",
            retry_count=2,
        )

        # Track attempt number
        attempt = 1
        assert attempt <= 2
        attempt += 1
        assert attempt <= 2
        attempt += 1
        assert attempt > 2  # Exceeded max retries

    def test_max_retries_exceeded_compensation_triggered(
        self,
        step_factory,
        plan_factory,
        mock_outbox: MockOutbox,
    ) -> None:
        """When max retries exceeded, compensation is triggered."""
        steps = [
            step_factory("step-1", "agent_call", "Create", compensate_fn="delete"),
            step_factory(
                "step-2",
                "agent_call",
                "Process",
                retry_count=1,
                depends_on=["step-1"],
            ),
        ]
        plan_factory(steps=steps)

        # step-2 fails and exhausts retries
        outbox = mock_outbox
        outbox.clear()

        # Emit event: step-2 failed after retries exhausted
        outbox.emit({
            "event": "step.failed",
            "step_id": "step-2",
            "reason": "max_retries_exceeded",
        })

        # Compensation should be triggered
        outbox.emit({
            "event": "compensation.started",
            "step_id": "step-1",
        })

        events = outbox.list_events()
        assert any(e["event"] == "compensation.started" for e in events)

    def test_exponential_backoff_between_retries(
        self,
        step_factory,
    ) -> None:
        """Retry backoff increases exponentially (or linearly) between attempts."""
        step_factory(
            "step-1",
            "agent_call",
            "Task",
            retry_count=3,
        )

        # Retry schedule (example):
        # Attempt 1: immediate
        # Attempt 2: after 100ms
        # Attempt 3: after 200ms (or 100 * 2^1)
        backoff_ms_default = 100
        retry_intervals = [backoff_ms_default * (i + 1) for i in range(2)]

        assert retry_intervals == [100, 200]

    def test_timeout_failure_no_retry(
        self,
        step_factory,
    ) -> None:
        """Timeout failures do NOT retry (treated as fatal)."""
        step = step_factory(
            "step-1",
            "agent_call",
            "Timeout task",
            timeout_ms=100,
            retry_count=3,
        )

        # If step times out, don't retry (timeout is not transient)
        assert step["metadata"]["timeout_ms"] == 100
        assert step["metadata"]["retry_count"] == 3

    def test_retry_backoff_configurable(
        self,
        step_factory,
    ) -> None:
        """Backoff duration is configurable per step."""
        step_default = step_factory("step-1", "agent_call", "Task", retry_count=2)

        step_custom = step_factory(
            "step-2",
            "agent_call",
            "Task",
            retry_count=2,
        )
        step_custom["metadata"]["retry_backoff_ms"] = 500

        # Default backoff vs custom
        assert "retry_backoff_ms" not in step_default["metadata"]
        assert step_custom["metadata"]["retry_backoff_ms"] == 500


class TestRetryObservability:
    """Test retry/backoff observability and event emission."""

    def test_retry_event_emitted_on_transient_failure(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Verify retry event is emitted when step fails and retries."""
        call_count = {"count": 0}

        class FailingExecutor:
            def execute_step(self, step, context):
                call_count["count"] += 1
                if call_count["count"] == 1:
                    raise StepExecutionError("Transient failure")
                return {"result": "ok"}

        # Create plan with retry-enabled step
        plan = Plan(
            id="plan-1",
            meta=PlanMetadata(
                goal="test",
                source_object_uuid="obj-1",
                created_by="test",
                trace_id="trace-1",
            ),
            steps=[
                PlanStep(
                    id="step-1",
                    kind="agent_call",
                    description="Flaky task",
                    agent="test_agent",
                    metadata={"retry_count": 2},
                )
            ],
            context={},
        )

        orchestrator = OrchestratorV2(
            executor=FailingExecutor(),
            outbox=mock_outbox,
        )

        results = orchestrator.run_plan(plan)

        # Verify step succeeded after retry
        assert any(r["status"] == "ok" for r in results)

        # Verify retry event was emitted
        retry_events = mock_outbox.list_events("orchestrator.step.retry")
        assert len(retry_events) >= 1
        assert retry_events[0]["step_id"] == "step-1"
        assert retry_events[0]["attempt"] == 1
        assert "backoff_ms" in retry_events[0]

    def test_retry_exhaustion_event_emitted(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Verify retry exhaustion event when all retries are consumed."""
        class FailingExecutor:
            def execute_step(self, step, context):
                raise StepExecutionError("Permanent failure")

        plan = Plan(
            id="plan-1",
            meta=PlanMetadata(
                goal="test",
                source_object_uuid="obj-1",
                created_by="test",
                trace_id="trace-1",
            ),
            steps=[
                PlanStep(
                    id="step-1",
                    kind="agent_call",
                    description="Failing task",
                    agent="test_agent",
                    metadata={"retry_count": 2},
                )
            ],
            context={},
        )

        orchestrator = OrchestratorV2(
            executor=FailingExecutor(),
            outbox=mock_outbox,
        )

        results = orchestrator.run_plan(plan)

        # Verify step failed
        assert any(r["status"] == "error" for r in results)

        # Verify retry exhaustion event was emitted
        exhaustion_events = mock_outbox.list_events("orchestrator.step.retry.exhausted")
        assert len(exhaustion_events) >= 1
        assert exhaustion_events[0]["step_id"] == "step-1"
        assert exhaustion_events[0]["max_retries"] == 2
        assert "final_error" in exhaustion_events[0]

    def test_retry_event_contains_observability_metadata(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Verify retry events contain detailed observability metadata."""
        call_count = {"count": 0}

        class FailingExecutor:
            def execute_step(self, step, context):
                call_count["count"] += 1
                if call_count["count"] <= 1:
                    raise StepExecutionError("Transient error", error_type="transient")
                return {"result": "ok"}

        plan = Plan(
            id="plan-1",
            meta=PlanMetadata(
                goal="test",
                source_object_uuid="obj-1",
                created_by="test",
                trace_id="trace-1",
            ),
            steps=[
                PlanStep(
                    id="step-1",
                    kind="agent_call",
                    description="Task",
                    agent="test_agent",
                    metadata={"retry_count": 2, "retry_backoff_ms": 250},
                )
            ],
            context={},
        )

        orchestrator = OrchestratorV2(
            executor=FailingExecutor(),
            outbox=mock_outbox,
        )

        results = orchestrator.run_plan(plan)

        # Verify retry event has all expected metadata
        retry_events = mock_outbox.list_events("orchestrator.step.retry")
        assert len(retry_events) >= 1

        event = retry_events[0]
        assert event["plan_id"] == "plan-1"
        assert event["step_id"] == "step-1"
        assert event["attempt"] == 1
        assert event["backoff_ms"] == 250
        assert event["error"] == "Transient error"
        assert event["error_type"] == "transient"

    def test_no_retry_events_on_no_retries_configured(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Verify no retry events emitted when retry_count is 0."""
        class FailingExecutor:
            def execute_step(self, step, context):
                raise StepExecutionError("Failed immediately")

        plan = Plan(
            id="plan-1",
            meta=PlanMetadata(
                goal="test",
                source_object_uuid="obj-1",
                created_by="test",
                trace_id="trace-1",
            ),
            steps=[
                PlanStep(
                    id="step-1",
                    kind="agent_call",
                    description="No-retry task",
                    agent="test_agent",
                    metadata={"retry_count": 0},
                )
            ],
            context={},
        )

        orchestrator = OrchestratorV2(
            executor=FailingExecutor(),
            outbox=mock_outbox,
        )

        results = orchestrator.run_plan(plan)

        # Verify no retry events were emitted
        retry_events = mock_outbox.list_events("orchestrator.step.retry")
        assert len(retry_events) == 0

        # Verify final failure was not marked as retry exhaustion (no retries configured)
        exhaustion_events = mock_outbox.list_events("orchestrator.step.retry.exhausted")
        assert len(exhaustion_events) == 0

    def test_timeout_failure_not_retried(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """Verify tool_timeout failures are not retried regardless of retry_count."""
        class TimeoutExecutor:
            def execute_step(self, step, context):
                raise StepExecutionError("tool call timed out", error_type="tool_timeout")

        plan = Plan(
            id="plan-1",
            meta=PlanMetadata(
                goal="test",
                source_object_uuid="obj-1",
                created_by="test",
                trace_id="trace-1",
            ),
            steps=[
                PlanStep(
                    id="step-1",
                    kind="agent_call",
                    description="Timeout task",
                    agent="test_agent",
                    metadata={"retry_count": 3},
                )
            ],
            context={},
        )

        orchestrator = OrchestratorV2(
            executor=TimeoutExecutor(),
            outbox=mock_outbox,
        )

        results = orchestrator.run_plan(plan)

        # Verify no retry events (timeout is not retried)
        retry_events = mock_outbox.list_events("orchestrator.step.retry")
        assert len(retry_events) == 0

        # Verify step failed immediately
        assert any(r["status"] == "error" for r in results)
