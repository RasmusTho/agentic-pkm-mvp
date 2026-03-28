"""Tests for the standardised LangGraph graph builder."""

from __future__ import annotations

from typing import Any

import pytest

from app.components.reasoning.graph_builder import (
    AgentStateBase,
    GraphTopologyError,
    build_agent_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identity(state: Any) -> Any:
    return state


def _increment_step(state: dict[str, Any]) -> dict[str, Any]:
    state["step_count"] = state.get("step_count", 0) + 1
    return state


# ---------------------------------------------------------------------------
# AgentStateBase
# ---------------------------------------------------------------------------


class TestAgentStateBase:
    def test_can_construct_with_defaults(self) -> None:
        state: AgentStateBase = {}
        assert "trace_id" not in state  # total=False

    def test_can_construct_with_values(self) -> None:
        state: AgentStateBase = {
            "trace_id": "abc",
            "budget": 10,
            "step_count": 0,
            "messages": [],
        }
        assert state["trace_id"] == "abc"
        assert state["budget"] == 10

    def test_serialises_to_dict(self) -> None:
        state: AgentStateBase = {"trace_id": "x", "budget": 5, "step_count": 1, "messages": []}
        assert isinstance(dict(state), dict)
        assert dict(state)["trace_id"] == "x"


# ---------------------------------------------------------------------------
# build_agent_graph — valid topologies
# ---------------------------------------------------------------------------


class TestBuildAgentGraphValid:
    def test_single_node_graph(self) -> None:
        graph = build_agent_graph(
            "test",
            nodes={"do_stuff": _identity},
            edges=[("__start__", "do_stuff"), ("do_stuff", "__end__")],
        )
        # Should compile without error
        compiled = graph.compile()
        assert compiled is not None

    def test_multi_node_graph(self) -> None:
        graph = build_agent_graph(
            "multi",
            nodes={"a": _identity, "b": _identity, "c": _identity},
            edges=[
                ("__start__", "a"),
                ("a", "b"),
                ("b", "c"),
                ("c", "__end__"),
            ],
        )
        compiled = graph.compile()
        assert compiled is not None

    def test_compiled_graph_runs(self) -> None:
        graph = build_agent_graph(
            "runner",
            nodes={"step": _increment_step},
            edges=[("__start__", "step"), ("step", "__end__")],
        )
        compiled = graph.compile()
        result = compiled.invoke({"trace_id": "t1", "step_count": 0, "messages": []})
        assert result["step_count"] == 1

    def test_custom_state_cls(self) -> None:
        from typing import TypedDict

        class MyState(TypedDict, total=False):
            trace_id: str
            budget: int
            step_count: int
            messages: list
            custom_field: str

        def _set_custom(state: dict) -> dict:
            state["custom_field"] = "hello"
            return state

        graph = build_agent_graph(
            "custom",
            nodes={"init": _set_custom},
            edges=[("__start__", "init"), ("init", "__end__")],
            state_cls=MyState,
        )
        compiled = graph.compile()
        result = compiled.invoke({"trace_id": "t", "messages": []})
        assert result["custom_field"] == "hello"


# ---------------------------------------------------------------------------
# build_agent_graph — invalid topologies
# ---------------------------------------------------------------------------


class TestBuildAgentGraphInvalid:
    def test_rejects_empty_nodes(self) -> None:
        with pytest.raises(GraphTopologyError, match="at least one node"):
            build_agent_graph(
                "empty",
                nodes={},
                edges=[("__start__", "__end__")],
            )

    def test_rejects_no_entry_edge(self) -> None:
        with pytest.raises(GraphTopologyError, match="edge from START"):
            build_agent_graph(
                "no_entry",
                nodes={"a": _identity},
                edges=[("a", "__end__")],
            )

    def test_rejects_no_terminal_edge(self) -> None:
        with pytest.raises(GraphTopologyError, match="edge to END"):
            build_agent_graph(
                "no_terminal",
                nodes={"a": _identity},
                edges=[("__start__", "a")],
            )


# ---------------------------------------------------------------------------
# Telemetry wrapping
# ---------------------------------------------------------------------------


class TestNodeTelemetry:
    def test_wrapper_preserves_function_result(self) -> None:
        """The telemetry wrapper must not swallow the node return value."""
        graph = build_agent_graph(
            "telemetry_test",
            nodes={"step": _increment_step},
            edges=[("__start__", "step"), ("step", "__end__")],
        )
        compiled = graph.compile()
        result = compiled.invoke({"trace_id": "tel", "step_count": 5, "messages": []})
        assert result["step_count"] == 6

    @pytest.mark.asyncio
    async def test_wrapper_awaits_async_nodes(self) -> None:
        """Async graph nodes should be awaited before their result is returned."""

        async def _async_increment(state: dict[str, Any]) -> dict[str, Any]:
            state["step_count"] = state.get("step_count", 0) + 1
            return state

        graph = build_agent_graph(
            "async_telemetry_test",
            nodes={"step": _async_increment},
            edges=[("__start__", "step"), ("step", "__end__")],
        )
        compiled = graph.compile()
        result = await compiled.ainvoke({"trace_id": "async", "step_count": 1, "messages": []})
        assert result["step_count"] == 2
