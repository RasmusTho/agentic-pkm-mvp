from __future__ import annotations

from app.config.agent import AgentConfig

from .actions import PlannedAction


def build_plan(config: AgentConfig) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    for query in config.plan.seed_queries[: config.plan.max_actions]:
        actions.append(
            PlannedAction(
                tool="retriever",
                args={"query": query, "k": 5},
                description=f"Retrieve context for '{query}'",
            )
        )
    if len(actions) < config.plan.max_actions:
        actions.append(
            PlannedAction(
                tool="write_note",
                args={"text": "Recorded heartbeat note from autonomous agent run."},
                description="Persist run heartbeat note.",
            )
        )
    return actions[: config.plan.max_actions]
