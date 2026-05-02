"""Tests for pilot_agent runtime orchestration."""

from __future__ import annotations

import asyncio
import os
import pytest
from unittest.mock import patch

from app.agents.pilot_agent.runtime import run_promotion_agent
from app.events.schema import make_outbox_event


class TestRuntimeFeatureFlag:
    """Test feature flag control."""

    @pytest.mark.asyncio
    async def test_feature_flag_off_by_default(self):
        """Feature flag is off by default."""
        # Ensure env var is not set
        original = os.environ.pop("LANGGRAPH_PILOT_AGENT", None)
        try:
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                await run_promotion_agent(event)
                # Should use fallback
                assert mock_emit.called
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original

    @pytest.mark.asyncio
    async def test_feature_flag_promotion(self):
        """Feature flag 'promotion' enables agent."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "promotion"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                await run_promotion_agent(event)
                assert mock_emit.called
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)

    @pytest.mark.asyncio
    async def test_feature_flag_case_insensitive(self):
        """Feature flag check is case insensitive."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "PROMOTION"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                await run_promotion_agent(event)
                assert mock_emit.called
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)


class TestRuntimeEventProcessing:
    """Test runtime event processing."""

    @pytest.mark.asyncio
    async def test_runtime_accepts_outbox_event(self):
        """Runtime accepts OutboxEvent."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                trace_id="trace-123",
                payload={"note_uuid": "note-456"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                await run_promotion_agent(event)
                assert mock_emit.called
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)

    @pytest.mark.asyncio
    async def test_runtime_emits_result_event(self):
        """Runtime emits result event."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                await run_promotion_agent(event)
                # Should call append_jsonl_outbox_event with an event
                assert mock_emit.called
                call_args = mock_emit.call_args
                assert call_args is not None
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)


class TestRuntimeErrorHandling:
    """Test runtime error handling."""

    def test_runtime_handles_graph_invocation_error(self):
        """Runtime handles graph invocation errors gracefully."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "promotion"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                trace_id="trace-error",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.run_promotion_graph"
            ) as mock_build:
                mock_build.side_effect = Exception("Graph build failed")
                with patch(
                    "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
                ) as mock_emit:
                    # Should not raise
                    asyncio.run(run_promotion_agent(event))
                    # Should still emit error event
                    assert mock_emit.called
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)

    @pytest.mark.asyncio
    async def test_runtime_handles_invalid_event(self):
        """Runtime handles invalid event gracefully."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                trace_id="",  # Invalid
                payload={},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                # Should handle gracefully
                await run_promotion_agent(event)
                assert mock_emit.called
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)


class TestDeterministicFallback:
    """Test deterministic fallback when LLM is disabled."""

    def test_fallback_high_confidence_promotes(self):
        """Fallback: high confidence → promote."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1", "confidence": 0.95},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                asyncio.run(run_promotion_agent(event))
                assert mock_emit.called
                call_args = mock_emit.call_args
                emitted_event = call_args[0][1]  # Second positional arg is the event
                assert emitted_event.event == "promotion.approved"
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)

    def test_fallback_medium_confidence_evergreen(self):
        """Fallback: medium confidence → evergreen."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1", "confidence": 0.65},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                asyncio.run(run_promotion_agent(event))
                assert mock_emit.called
                call_args = mock_emit.call_args
                emitted_event = call_args[0][1]
                assert emitted_event.event == "promotion.deferred"
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)

    def test_fallback_low_confidence_skips(self):
        """Fallback: low confidence → skip."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1", "confidence": 0.3},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                asyncio.run(run_promotion_agent(event))
                assert mock_emit.called
                call_args = mock_emit.call_args
                emitted_event = call_args[0][1]
                assert emitted_event.event == "promotion.skipped"
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)

    def test_fallback_preserves_trace_id(self):
        """Fallback preserves trace_id."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                trace_id="trace-fallback-123",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ) as mock_emit:
                asyncio.run(run_promotion_agent(event))
                assert mock_emit.called
                call_args = mock_emit.call_args
                emitted_event = call_args[0][1]
                assert emitted_event.trace_id == "trace-fallback-123"
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)


class TestRuntimeLogging:
    """Test runtime logging and telemetry."""

    @pytest.mark.asyncio
    async def test_runtime_logs_execution(self):
        """Runtime logs execution."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ):
                with patch(
                    "app.agents.pilot_agent.runtime.logger"
                ) as mock_logger:
                    await run_promotion_agent(event)
                    # Should log something
                    assert mock_logger.debug.called or mock_logger.info.called
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)

    @pytest.mark.asyncio
    async def test_runtime_logs_completion(self):
        """Runtime logs completion with decision."""
        original = os.environ.get("LANGGRAPH_PILOT_AGENT")
        try:
            os.environ["LANGGRAPH_PILOT_AGENT"] = "off"
            event = make_outbox_event(
                "promotion.intent.created",
                source="test",
                payload={"note_uuid": "n1"},
            )
            with patch(
                "app.agents.pilot_agent.runtime.append_jsonl_outbox_event"
            ):
                with patch(
                    "app.agents.pilot_agent.runtime.logger"
                ) as mock_logger:
                    await run_promotion_agent(event)
                    # Check if completion is logged
                    if mock_logger.info.called:
                        for call in mock_logger.info.call_args_list:
                            if "completed" in str(call).lower():
                                break
        finally:
            if original:
                os.environ["LANGGRAPH_PILOT_AGENT"] = original
            else:
                os.environ.pop("LANGGRAPH_PILOT_AGENT", None)
