"""Registered JSON schema for planner plan output (KERNEL-09, #2771).

The planner's JSON is a control-path artifact: the orchestrator schedules and
executes whatever it admits. This module registers the ``Plan`` shape
(``app/planner/schema.py``) in the KERNEL-07 schema registry
(``app/components/llm/constrained.py``) so that:

- ``LLMPlanner`` routes raw completions through ``constrained_completion``
  against this ref instead of trusting ``PLANNER_SYSTEM_PROMPT`` text, and
- plan admission (``app/orchestrator/admission.py``) validates every plan as a
  named, checked schema artifact before scheduling.

The schema is derived from the pydantic model so the two cannot drift: the
model is the single authority, the registry entry is its projection.
"""

from __future__ import annotations

from typing import Any

from app.components.llm.constrained import register_schema

from .schema import Plan

#: Registry ref for the planner plan schema (KERNEL-07 registry).
PLAN_SCHEMA_REF = "planner.plan.v1"


def _plan_json_schema() -> dict[str, Any]:
    return Plan.model_json_schema()


# Registered at import so any consumer of the ref sees the same artifact.
# ``register_schema`` is idempotent for an identical schema and refuses a
# conflicting re-registration (one authority per ref).
register_schema(PLAN_SCHEMA_REF, _plan_json_schema())

__all__ = ["PLAN_SCHEMA_REF"]
