from __future__ import annotations
from langgraph.graph import StateGraph, END
from typing import TypedDict, Any, Callable

class AgentState(TypedDict, total=False):
    input: dict
    plan: dict
    act_result: dict
    reflection: dict
    output: dict
    trace_id: str

def make_per_graph(
    *,
    agent_name: str,
    plan_fn: Callable[[AgentState], dict],
    act_fn: Callable[[AgentState], dict],
    reflect_fn: Callable[[AgentState], dict],
    emit_fn: Callable[[AgentState], dict],
):
    g = StateGraph(AgentState)

    def plan_node(s: AgentState) -> AgentState:
        s["plan"] = plan_fn(s)
        return s

    def act_node(s: AgentState) -> AgentState:
        s["act_result"] = act_fn(s)
        return s

    def reflect_node(s: AgentState) -> AgentState:
        s["reflection"] = reflect_fn(s)
        return s

    def emit_node(s: AgentState) -> AgentState:
        s["output"] = emit_fn(s)
        return s

    g.add_node("plan", plan_node)
    g.add_node("act", act_node)
    g.add_node("reflect", reflect_node)
    g.add_node("emit", emit_node)

    g.set_entry_point("plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "reflect")
    g.add_edge("reflect", "emit")
    g.add_edge("emit", END)

    return g.compile()
