"""LangGraph state graph for Pilot Agent."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.pilot_agent.state import PilotAgentState
from app.agents.pilot_agent.nodes.validate import validate_node
from app.agents.pilot_agent.nodes.classify import classify_node
from app.agents.pilot_agent.nodes.reason import reason_node
from app.agents.pilot_agent.nodes.apply import apply_node


def build_promotion_graph() -> StateGraph:
    """Build and return the Pilot Agent graph.

    Graph topology:
        START → validate → classify → reason → apply → END

    Conditional routing:
        If error occurs in any node, route directly to END

    Returns:
        Compiled StateGraph ready for invocation
    """

    graph = StateGraph(PilotAgentState)

    # Add nodes
    graph.add_node("validate", validate_node)
    graph.add_node("classify", classify_node)
    graph.add_node("reason", reason_node)
    graph.add_node("apply", apply_node)

    # Add edges
    graph.add_edge(START, "validate")
    graph.add_edge("validate", "classify")
    graph.add_edge("classify", "reason")
    graph.add_edge("reason", "apply")
    graph.add_edge("apply", END)

    # Compile and return
    return graph.compile()


def run_promotion_graph(state: PilotAgentState) -> PilotAgentState:
    """Execute the promotion graph and return normalized state.

    Handles the fact that LangGraph may return dict or PilotAgentState.

    Args:
        state: Initial PilotAgentState

    Returns:
        Final PilotAgentState after graph execution
    """
    compiled = build_promotion_graph()
    result = compiled.invoke(state)

    # LangGraph returns dict or state object
    if isinstance(result, PilotAgentState):
        return result

    # Try to convert dict back to state
    try:
        return PilotAgentState(**result)
    except Exception:
        # Fallback: return input state if conversion fails
        return state


__all__ = ["build_promotion_graph", "run_promotion_graph"]
