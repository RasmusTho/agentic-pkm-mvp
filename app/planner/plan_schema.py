"""Registered JSON schemas for planner plan output (KERNEL-09, #2771).

The planner's JSON is a control-path artifact: the orchestrator schedules and
executes whatever it admits. This module registers two projections of the
``Plan`` shape (``app/planner/schema.py``) in the KERNEL-07 schema registry
(``app/components/llm/constrained.py``):

- ``PLAN_SCHEMA_REF`` (``planner.plan.v1``) — the **admission** artifact.
  ``step_class`` stays nullable so legacy/code-built plans remain
  schema-admissible; plan admission (``app/orchestrator/admission.py``)
  validates every plan against this before scheduling.
- ``PLANNER_OUTPUT_SCHEMA_REF`` (``planner.plan.output.v1``) — the
  **planner-facing** artifact used by ``LLMPlanner`` through
  ``constrained_completion``. It additionally **requires** a non-null
  ``step_class`` on every step, so constrained decoding cannot emit a plan
  whose steps are unclassified — R1/R2 admission rules are therefore never
  vacuous for LLM-produced plans.

Both schemas are derived from the pydantic model so they cannot drift from the
code shape: the model is the single authority, the registry entries are its
projections.
"""

from __future__ import annotations

from typing import Any, get_args

from app.components.llm.constrained import register_schema

from .schema import Plan, StepClass

#: Registry ref for the admission-side plan schema (KERNEL-07 registry).
PLAN_SCHEMA_REF = "planner.plan.v1"

#: Registry ref for the planner-facing output schema: identical to
#: ``PLAN_SCHEMA_REF`` except ``step_class`` is required and non-null on every
#: step.
PLANNER_OUTPUT_SCHEMA_REF = "planner.plan.output.v1"


def _plan_json_schema() -> dict[str, Any]:
    return Plan.model_json_schema()


def _planner_output_schema() -> dict[str, Any]:
    schema = Plan.model_json_schema()
    step_def = schema["$defs"]["PlanStep"]
    step_def["properties"]["step_class"] = {
        "type": "string",
        "enum": list(get_args(StepClass)),
        "description": (
            "Admission class for this step; use 'plain' when no admission-"
            "relevant role applies."
        ),
    }
    required = list(step_def.get("required") or [])
    if "step_class" not in required:
        required.append("step_class")
    step_def["required"] = required
    return schema


# Registered at import so any consumer of the refs sees the same artifacts.
# ``register_schema`` is idempotent for an identical schema and refuses a
# conflicting re-registration (one authority per ref).
register_schema(PLAN_SCHEMA_REF, _plan_json_schema())
register_schema(PLANNER_OUTPUT_SCHEMA_REF, _planner_output_schema())

__all__ = ["PLAN_SCHEMA_REF", "PLANNER_OUTPUT_SCHEMA_REF"]
