from __future__ import annotations
"""
LangGraph POC: a minimal Plan→Execute→Reflect skeleton with mock tools.
Decoupled från WS runtime. Run locally: `python app/langgraph/ws_graph.py`
"""
from typing import Dict, Any
try:
    from langgraph.graph import StateGraph, START, END
except Exception as e:
    print("LangGraph not installed; install manually if you want to run this POC.")
    raise

def plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
    q = state.get("q","")
    state["plan"] = ["bm25_search", "compose_answer"]
    state["log"] = state.get("log",[]) + [f"plan for: {q}"]
    return state

def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    # mock: return first sentence från a pretend corpus
    state["results"] = [{"id":"golden:note_evergreen","text":"YAML frontmatter aligns with Obsidian..."}]
    state["log"] = state.get("log",[]) + ["executed mock bm25_search"]
    return state

def reflect_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state["answer"] = f"A: {state['results'][0]['text'][:80]}"
    state["log"] = state.get("log",[]) + ["reflected & composed answer"]
    return state

def build_graph():
    g = StateGraph(dict)
    g.add_node("plan", plan_node)
    g.add_node("execute", execute_node)
    g.add_node("reflect", reflect_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "reflect")
    g.add_edge("reflect", END)
    return g.compile()

if __name__ == "__main__":
    graph = build_graph()
    out = graph.invoke({"q":"hello"})
    print(out["answer"])
    print("LOG:", " | ".join(out["log"]))
