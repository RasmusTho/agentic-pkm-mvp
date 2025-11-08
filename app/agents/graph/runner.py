from __future__ import annotations
from typing import Callable, Dict, List, Any

Node = Callable[[Dict[str, Any]], Dict[str, Any]]

def run_graph(state: Dict[str, Any], nodes: List[Node]) -> Dict[str, Any]:
    """Run a list of nodes sequentially, threading shared state through."""
    for fn in nodes:
        name = getattr(fn, "__name__", str(fn))
        try:
            state = fn(state) or state
        except Exception as e:
            state["error"] = f"{name}: {e}"
            break
    return state

def node(name: str):
    def decorator(fn: Node) -> Node:
        fn.__name__ = name
        return fn
    return decorator
