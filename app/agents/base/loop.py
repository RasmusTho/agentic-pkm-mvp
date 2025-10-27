from __future__ import annotations

from typing import Any, Dict, Tuple

from app.agent.events import Event, make_event, new_trace_id
from app.observability.tracer import start_span

class Agent:
    def plan(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"goal": "act"}

    def act(self, plan: Dict[str, Any], inputs: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return {"result": "ok"}, {}

    def reflect(self, outcome: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"reflection": "done"}

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = inputs.get("trace_id") or new_trace_id()
        agent_name = self.__class__.__name__
        with start_span(f"agent.{agent_name}.run", trace_id, {"agent": agent_name}):
            with start_span(f"agent.{agent_name}.plan", trace_id):
                plan = self.plan(inputs)
            with start_span(f"agent.{agent_name}.act", trace_id):
                outcome, context = self.act(plan, inputs)
            with start_span(f"agent.{agent_name}.reflect", trace_id):
                reflection = self.reflect(outcome, context)
        return {"trace_id": trace_id, "plan": plan, "outcome": outcome, "reflection": reflection}

def reflection_event(agent_name: str, output: Dict[str, Any]) -> Event:
    return make_event(name=f"agent.{agent_name}.reflected", payload=output, trace_id=output["trace_id"])
