"""Standardised LangGraph graph builder for all agents.

Provides ``AgentStateBase`` (the minimum state every graph must carry) and
``build_agent_graph`` which enforces structural invariants — entry node,
terminal node, telemetry wrapper on every node.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Callable, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)


class AgentStateBase(TypedDict, total=False):
    """Minimum fields every agent graph state must include."""

    trace_id: str
    budget: int
    step_count: int
    messages: list[dict[str, Any]]


def _wrap_node(
    agent_name: str,
    node_name: str,
    fn: Callable[..., Any],
) -> Callable[..., Any]:
    """Return a wrapper that logs node entry/exit with timing."""

    def _trace_id_for_state(state: Any) -> str:
        trace_id = ""
        if isinstance(state, dict):
            trace_id = state.get("trace_id", "")
        elif hasattr(state, "trace_id"):
            trace_id = getattr(state, "trace_id", "") or ""
        return trace_id[:8] if trace_id else uuid4().hex[:8]

    def _log_enter(short_trace: str) -> float:
        logger.debug(
            "graph.node.enter agent=%s node=%s trace=%s",
            agent_name,
            node_name,
            short_trace,
        )
        return time.monotonic()

    def _log_exit(short_trace: str, t0: float) -> None:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug(
            "graph.node.exit agent=%s node=%s trace=%s elapsed=%.1fms",
            agent_name,
            node_name,
            short_trace,
            elapsed_ms,
        )

    if inspect.iscoroutinefunction(fn):
        async def _wrapped(state: Any) -> Any:
            short_trace = _trace_id_for_state(state)
            t0 = _log_enter(short_trace)
            try:
                return await fn(state)
            finally:
                _log_exit(short_trace, t0)
    else:
        def _wrapped(state: Any) -> Any:
            short_trace = _trace_id_for_state(state)
            t0 = _log_enter(short_trace)
            try:
                return fn(state)
            finally:
                _log_exit(short_trace, t0)

    _wrapped.__name__ = fn.__name__ if hasattr(fn, "__name__") else node_name
    _wrapped.__qualname__ = getattr(fn, "__qualname__", node_name)
    return _wrapped


class GraphTopologyError(ValueError):
    """Raised when the declared graph topology is invalid."""


def build_agent_graph(
    agent_name: str,
    *,
    nodes: dict[str, Callable[..., Any]],
    edges: list[tuple[str, str]],
    state_cls: type = AgentStateBase,
) -> StateGraph:
    """Build a validated, telemetry-wrapped LangGraph ``StateGraph``.

    Parameters
    ----------
    agent_name:
        Human-readable name used in telemetry logs.
    nodes:
        Mapping of node-name to handler function.
    edges:
        List of ``(from, to)`` pairs.  Use the string literals
        ``"__start__"`` and ``"__end__"`` to reference LangGraph's
        ``START`` / ``END`` sentinels.
    state_cls:
        The TypedDict (or Pydantic model) used as graph state.
        Must be a superset of ``AgentStateBase``.

    Returns
    -------
    An **uncompiled** ``StateGraph`` — callers can add conditional edges
    or compile as they see fit.
    """
    if not nodes:
        raise GraphTopologyError(f"[{agent_name}] graph must have at least one node")

    # -- validate entry / terminal edges ------------------------------------
    has_entry = any(src in ("__start__", START) for src, _ in edges)
    has_terminal = any(dst in ("__end__", END) for _, dst in edges)

    if not has_entry:
        raise GraphTopologyError(
            f"[{agent_name}] graph must have at least one edge from START"
        )
    if not has_terminal:
        raise GraphTopologyError(
            f"[{agent_name}] graph must have at least one edge to END"
        )

    # -- build graph --------------------------------------------------------
    graph = StateGraph(state_cls)

    for node_name, fn in nodes.items():
        wrapped = _wrap_node(agent_name, node_name, fn)
        graph.add_node(node_name, wrapped)

    for src, dst in edges:
        real_src = START if src in ("__start__", START) else src
        real_dst = END if dst in ("__end__", END) else dst
        graph.add_edge(real_src, real_dst)

    return graph


__all__ = [
    "AgentStateBase",
    "GraphTopologyError",
    "build_agent_graph",
]
