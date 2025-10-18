from __future__ import annotations

import sqlite3
from typing import Any, cast
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from .models import AgentState
from .nodes import feedback, guard, hydrate, log, reason

graph = StateGraph(AgentState)
graph.add_node("hydrate", hydrate)
graph.add_node("reason", reason)
graph.add_node("guard", guard)
graph.add_node("log", log)
graph.add_node("feedback", feedback)

graph.set_entry_point("hydrate")
graph.add_edge("hydrate", "reason")
graph.add_edge("reason", "guard")
graph.add_edge("guard", "log")
graph.add_edge("log", "feedback")
graph.add_edge("feedback", END)

checkpoint_conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
checkpointer = SqliteSaver(checkpoint_conn)
app = graph.compile(checkpointer=checkpointer)


def invoke(
    task: str,
    profile: str = "work",
    input_text: str | None = None,
    feedback_text: str | None = None,
) -> AgentState:
    state = AgentState(
        run_id=uuid4().hex,
        task=task,
        user_input=input_text,
        profile=profile,
        feedback=feedback_text,
    )
    config: dict[str, Any] = {"configurable": {"thread_id": state.run_id}}
    result = app.invoke(state, config=config)
    return AgentState.model_validate(cast(dict[str, Any], result))
