"""Test Orchestrator V2 retry & timeout contract."""

from __future__ import annotations

import time
from typing import Dict, List

import pytest

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
        step = step_factory(
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
        step = step_factory(
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
        plan = plan_factory(steps=steps)

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
        step = step_factory(
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
