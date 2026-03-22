from __future__ import annotations
from typing import TypedDict, Any, Callable, Optional
from dataclasses import dataclass
from langgraph.graph import StateGraph, START, END

class AgentState(TypedDict, total=False):
    trace_id: str
    input: dict
    plan: Any
    act_result: dict
    reflection: dict
    output: dict
    meta: dict
    current_plan_id: Optional[str]
    current_step_id: Optional[str]
    total_steps: Optional[int]
    max_total_steps: Optional[int]
    commitment_handles: list[Any]

@dataclass
class PERSpec:
    name: str
    plan: Callable[[AgentState], AgentState]
    act: Callable[[AgentState], AgentState]
    reflect: Callable[[AgentState], AgentState]
    emit: Callable[[AgentState], AgentState]

def build_graph(spec: PERSpec):
    g = StateGraph(AgentState)
    g.add_node("plan", spec.plan)
    g.add_node("act", spec.act)
    g.add_node("reflect", spec.reflect)
    g.add_node("emit", spec.emit)
    g.add_edge(START, "plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "reflect")
    g.add_edge("reflect", "emit")
    g.add_edge("emit", END)
    return g.compile()
