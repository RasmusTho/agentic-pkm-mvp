"""Intent-level classification for the canvas co-authoring surface.

This cognition labels a user's natural-language *intent* — independent of any
generated body — as one of the three intent classes defined in
``docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md``
(:: Intent Classes):

- **co-authoring** — edit the body of the currently open note,
- **governance-bearing** — change classification, metadata with policy meaning,
  multiple notes, note lifecycle, or promotion/commitment state,
- **exploratory** — reason/compare/plan/orient without mutating durable state.

When the intent is governance-bearing the cognition also names *which*
``GovernanceActionType`` it maps to, so the ``/coauthor`` route can route it to
the gated Panel pipeline with the correct action — before and independent of
body generation (see ``ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR.md``).

It is LLM-backed through the shared constrained-completion utility
(``app/components/llm/constrained.py``): the model is asked for
schema-constrained JSON and the completion is **validated against the
registered classification schema before any routing decision** (KERNEL-07,
audit invariants I-A1/I-A2). The raw completion function is injectable for
tests; validation always runs below the injection point. The cognition is
**pure**: it reads the intent (and optionally the current body for context)
and returns a typed label. It never writes to disk, never calls
``CanvasWriter``, and never stages a Panel intent. It does not loosen
``STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md``; it only labels intent.

Explicit UNKNOWN policy: when the provider fails, the backend is
mock/degraded, or the completion does not validate against the schema, the
cognition returns ``IntentClass.UNKNOWN`` with ``classified=False``. There is
**no silent action-capable default** — the former ``CO_AUTHORING`` failure
default is gone. Callers must land ``UNKNOWN`` on read-only handling with a
re-ask affordance; only a schema-validated classification can route to a
mutation-capable class.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.components.llm.constrained import (
    CompletionFn,
    ConstrainedCompletionError,
    constrained_completion,
    register_schema,
)

logger = logging.getLogger(__name__)


class IntentClass(str, Enum):
    """The three intent classes from the Hybrid Chat Integration Schema,
    plus the explicit ``UNKNOWN`` failure class (KERNEL-07).

    ``UNKNOWN`` is deliberately absent from the model-facing schema enum: it is
    never a class the model may emit, only the local result of a failed
    validation. It authorizes nothing.
    """

    CO_AUTHORING = "co_authoring"
    GOVERNANCE_BEARING = "governance_bearing"
    EXPLORATORY = "exploratory"
    UNKNOWN = "unknown"


class GovernanceActionType(str, Enum):
    """Governance action types recognised by the canvas-to-Panel bridge.

    Defined here (cognition layer) rather than in ``app.chat.governance_router``
    (interaction layer) so the classifier — which must name the action type it
    maps a governance-bearing intent to — never has to import upward into the
    protected interaction layer (#2853). ``app.chat.governance_router``
    re-exports this symbol for its existing importers; it is authoritative
    here.
    """

    FRONTMATTER_UPDATE = "frontmatter_update"
    MATURITY_TRANSITION = "maturity_transition"
    NOTE_LIFECYCLE = "note_lifecycle"
    CROSS_NOTE = "cross_note"


#: Registered schema for the classification completion. The model must return
#: exactly one JSON object of this shape; anything else is a validation
#: failure and yields ``UNKNOWN``. ``UNKNOWN`` itself is not model-emittable.
INTENT_CLASSIFICATION_SCHEMA_REF = "chat.intent_classification.v1"

_INTENT_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "intent_class": {
            "enum": [
                IntentClass.CO_AUTHORING.value,
                IntentClass.GOVERNANCE_BEARING.value,
                IntentClass.EXPLORATORY.value,
            ]
        },
        "action_type": {
            "enum": [
                GovernanceActionType.MATURITY_TRANSITION.value,
                GovernanceActionType.FRONTMATTER_UPDATE.value,
                GovernanceActionType.NOTE_LIFECYCLE.value,
                GovernanceActionType.CROSS_NOTE.value,
                None,
            ]
        },
        "rationale": {"type": ["string", "null"]},
    },
    "required": ["intent_class", "action_type"],
}

register_schema(INTENT_CLASSIFICATION_SCHEMA_REF, _INTENT_CLASSIFICATION_SCHEMA)


@dataclass(frozen=True)
class IntentClassification:
    """Result of classifying a co-authoring intent.

    ``action_type`` is set **iff** ``intent_class`` is ``GOVERNANCE_BEARING``.
    ``classified`` is ``False`` **iff** ``intent_class`` is ``UNKNOWN``: the
    completion failed schema validation (or the provider failed/was degraded)
    and no routing signal exists. Callers land ``UNKNOWN`` on read-only
    handling with a re-ask affordance — never on a mutation-capable path.
    """

    intent_class: IntentClass
    action_type: GovernanceActionType | None = None
    classified: bool = True
    rationale: str | None = None
    trace_id: str | None = None


class IntentClassifierCognition:
    """Classify a co-authoring intent into one of the intent classes.

    The raw LLM completion is injectable via ``completion`` so tests can supply
    a deterministic stub instead of a live provider. Schema validation runs
    inside :func:`constrained_completion` on this side of the injection seam,
    so the production ``classify()`` path always validates.
    """

    def __init__(self, *, completion: CompletionFn | None = None) -> None:
        self._completion = completion

    def classify(
        self,
        *,
        intent: str,
        current_body: str | None = None,
        trace_id: str | None = None,
    ) -> IntentClassification:
        """Return the intent class (and governance action, if any) for ``intent``.

        Never raises on a degraded backend or invalid output: any completion
        that does not validate against the registered schema yields the
        explicit ``UNKNOWN`` classification (``classified=False``) instead of a
        silent action-capable default.
        """
        try:
            payload = constrained_completion(
                INTENT_CLASSIFICATION_SCHEMA_REF,
                system=_SYSTEM_PROMPT,
                user=_build_user_prompt(intent, current_body),
                task_kind="decide",
                trace_id=trace_id,
                complete=self._completion,
            )
        except ConstrainedCompletionError as exc:
            # Fail-loud observability: without this line a provider outage is
            # indistinguishable from "model was unsure" — the surface would
            # silently brick into a re-ask loop with no operator signal.
            logger.warning(
                "intent classification degraded to UNKNOWN (schema_ref=%s trace_id=%s): %s",
                INTENT_CLASSIFICATION_SCHEMA_REF,
                trace_id or "-",
                exc.reason,
            )
            return _unknown(trace_id, reason=exc.reason)
        return _from_validated(payload, trace_id=trace_id)


# ---------------------------------------------------------------------------
# Prompt + context
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are classifying a single user intent during an active canvas "
    "co-authoring session. Classify the intent into exactly one class and "
    "return ONLY a JSON object, no commentary:\n"
    '{"intent_class": "<co_authoring|governance_bearing|exploratory>", '
    '"action_type": "<maturity_transition|frontmatter_update|note_lifecycle'
    '|cross_note|null>"}\n\n'
    "Classes:\n"
    "- co_authoring: edit the body of the currently open note "
    "(rewrite/expand/tighten/restructure prose). action_type = null.\n"
    "- governance_bearing: change classification, frontmatter/metadata with "
    "policy meaning, maturity/promotion state, note lifecycle "
    "(create/delete/rename/archive), or cross-note state. Set action_type to "
    "the closest match: maturity_transition (promote/demote/evergreen/"
    "seedling), frontmatter_update (tags/classification/properties/metadata), "
    "note_lifecycle (create/delete/rename/archive/split), cross_note "
    "(link/move/merge across notes).\n"
    "- exploratory: reason/compare/plan/draft/orient without mutating durable "
    "state. action_type = null."
)


def _build_user_prompt(intent: str, current_body: str | None) -> str:
    prompt = f"User intent: {intent.strip()}"
    if current_body and current_body.strip():
        prompt += (
            "\n\nCurrent note (for reference only — do not edit):\n" + current_body
        )
    return prompt


# ---------------------------------------------------------------------------
# Validated-payload mapping
# ---------------------------------------------------------------------------


def _unknown(trace_id: str | None, *, reason: str) -> IntentClassification:
    """Explicit UNKNOWN: the only failure result. Authorizes nothing."""
    return IntentClassification(
        intent_class=IntentClass.UNKNOWN,
        action_type=None,
        classified=False,
        rationale=reason,
        trace_id=trace_id,
    )


def _from_validated(payload: dict[str, Any], *, trace_id: str | None) -> IntentClassification:
    """Map a schema-validated payload to a typed classification.

    Only called with payloads that already validated against
    ``INTENT_CLASSIFICATION_SCHEMA_REF`` — the enum constructions below cannot
    fail, so a mutation-capable class is reachable from validated parses only.
    """
    intent_class = IntentClass(payload["intent_class"])
    rationale = _str_or_none(payload.get("rationale"))

    if intent_class is not IntentClass.GOVERNANCE_BEARING:
        # Co-authoring / exploratory never carry a governance action.
        return IntentClassification(
            intent_class=intent_class,
            action_type=None,
            classified=True,
            rationale=rationale,
            trace_id=trace_id,
        )

    # Governance-bearing: resolve the action subtype. A validated payload may
    # still carry action_type=null; keep the governance classification (routing
    # to the gated pipeline is safe — the note is never mutated) and fall back
    # to the generic frontmatter bucket rather than discarding the signal.
    raw_action = payload.get("action_type")
    action_type = (
        GovernanceActionType(raw_action)
        if isinstance(raw_action, str)
        else GovernanceActionType.FRONTMATTER_UPDATE
    )
    return IntentClassification(
        intent_class=IntentClass.GOVERNANCE_BEARING,
        action_type=action_type,
        classified=True,
        rationale=rationale,
        trace_id=trace_id,
    )


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


__all__ = [
    "GovernanceActionType",
    "INTENT_CLASSIFICATION_SCHEMA_REF",
    "IntentClass",
    "IntentClassification",
    "IntentClassifierCognition",
]
