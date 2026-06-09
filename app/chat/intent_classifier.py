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

It is the missing classifier behind the current ``/coauthor`` gap: today
governance-bearing is detected only by inspecting the *generated body* for a
frontmatter block, which the co-authoring prompt deliberately suppresses, so a
governance intent like "promote this note to evergreen" is silently applied as
an in-place body edit. This module classifies the intent instead.

It is LLM-backed via the shared ``ReasoningFacade`` (the provider is injectable
for tests), and it is **pure**: it reads the intent (and optionally the current
body for context) and returns a typed label. It never writes to disk, never
calls ``CanvasWriter``, and never stages a Panel intent. It does not loosen
``STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md``; it only labels intent.

Conservative degraded policy: when the reasoning backend is mock/degraded,
returns a failed/empty run, or returns an unparseable label, the cognition
returns ``classified=False`` and defaults to ``CO_AUTHORING`` with no governance
``action_type``. It never fabricates a governance routing from an untrusted
response; the route keeps the body-frontmatter check as its backstop.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from app.chat.governance_router import GovernanceActionType
from app.reasoning.facade import ReasoningFacade, get_reasoning_facade

# Sentinel prefixes emitted by the mock/degraded reasoning backend (mirrors
# ``coauthoring_cognition``). A diagnostic string is not a real classification.
_DEGRADED_LABEL_PREFIXES = ("MOCK_ASK_ANSWER:", "MOCK_")


class IntentClass(str, Enum):
    """The three intent classes from the Hybrid Chat Integration Schema."""

    CO_AUTHORING = "co_authoring"
    GOVERNANCE_BEARING = "governance_bearing"
    EXPLORATORY = "exploratory"


@dataclass(frozen=True)
class IntentClassification:
    """Result of classifying a co-authoring intent.

    ``action_type`` is set **iff** ``intent_class`` is ``GOVERNANCE_BEARING``.
    ``classified`` is ``False`` when the backend was degraded/unparseable and
    the result was defaulted conservatively to ``CO_AUTHORING`` — callers can
    use it to fall through to existing behavior rather than route on an
    untrusted signal.
    """

    intent_class: IntentClass
    action_type: GovernanceActionType | None = None
    classified: bool = True
    rationale: str | None = None
    trace_id: str | None = None


class IntentClassifierCognition:
    """Classify a co-authoring intent into one of the three intent classes.

    The reasoning provider is injectable via ``facade_factory`` so tests can
    supply a deterministic stub instead of a live LLM provider.
    """

    def __init__(
        self,
        *,
        facade_factory: Callable[[], ReasoningFacade] = get_reasoning_facade,
    ) -> None:
        self._facade_factory = facade_factory

    def classify(
        self,
        *,
        intent: str,
        current_body: str | None = None,
        trace_id: str | None = None,
    ) -> IntentClassification:
        """Return the intent class (and governance action, if any) for ``intent``.

        Never raises on a degraded backend: an untrusted/empty/unparseable
        response yields ``classified=False`` defaulting to ``CO_AUTHORING`` so
        the caller falls through to existing behavior instead of fabricating a
        governance routing.
        """
        facade = self._facade_factory()
        question = _build_classification_question(intent)
        context = _build_context(current_body)
        run = facade.answer(question, context=context, trace_id=trace_id)

        label = _extract_label(run)
        if label is None or _is_degraded_label(label):
            return _defaulted(trace_id, reason="degraded-or-empty-backend")
        return _parse_label(label, trace_id=trace_id)


# ---------------------------------------------------------------------------
# Prompt + context
# ---------------------------------------------------------------------------


def _build_classification_question(intent: str) -> str:
    return (
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
        "state. action_type = null.\n\n"
        f"User intent: {intent.strip()}"
    )


def _build_context(current_body: str | None) -> str | None:
    if current_body and current_body.strip():
        return "Current note (for reference only — do not edit):\n" + current_body
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _defaulted(trace_id: str | None, *, reason: str) -> IntentClassification:
    return IntentClassification(
        intent_class=IntentClass.CO_AUTHORING,
        action_type=None,
        classified=False,
        rationale=reason,
        trace_id=trace_id,
    )


def _is_degraded_label(label: str) -> bool:
    stripped = label.lstrip()
    return any(stripped.startswith(prefix) for prefix in _DEGRADED_LABEL_PREFIXES)


def _extract_label(run: Any) -> str | None:
    """Pull the classification label text from a ReasoningRun, or ``None``."""
    if getattr(run, "status", None) != "ok":
        return None
    result = getattr(run, "result", None)
    if isinstance(result, dict):
        for key in ("answer", "label", "text"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None
    if isinstance(result, str) and result.strip():
        return result
    return None


def _parse_label(label: str, *, trace_id: str | None) -> IntentClassification:
    """Parse a model label into a typed classification.

    Falls back to the conservative ``CO_AUTHORING`` default (``classified=False``)
    when the label is not a parseable JSON object or names an unknown class.
    """
    obj = _extract_json_object(label)
    if obj is None:
        return _defaulted(trace_id, reason="unparseable-label")

    raw_class = obj.get("intent_class")
    intent_class = _coerce_intent_class(raw_class)
    if intent_class is None:
        return _defaulted(trace_id, reason="unknown-intent-class")

    if intent_class is not IntentClass.GOVERNANCE_BEARING:
        # Co-authoring / exploratory never carry a governance action.
        return IntentClassification(
            intent_class=intent_class,
            action_type=None,
            classified=True,
            rationale=_str_or_none(obj.get("rationale")),
            trace_id=trace_id,
        )

    # Governance-bearing: resolve the action subtype. If the model omitted or
    # mis-named it, keep the governance classification (routing to the gated
    # pipeline is safe — the note is never mutated) and fall back to the generic
    # frontmatter bucket rather than discarding the governance signal.
    action_type = _coerce_action_type(obj.get("action_type")) or GovernanceActionType.FRONTMATTER_UPDATE
    return IntentClassification(
        intent_class=IntentClass.GOVERNANCE_BEARING,
        action_type=action_type,
        classified=True,
        rationale=_str_or_none(obj.get("rationale")),
        trace_id=trace_id,
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the first JSON object embedded in ``text``, or ``None``."""
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        pass
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_intent_class(value: Any) -> IntentClass | None:
    if not isinstance(value, str):
        return None
    try:
        return IntentClass(value.strip().lower())
    except ValueError:
        return None


def _coerce_action_type(value: Any) -> GovernanceActionType | None:
    if not isinstance(value, str):
        return None
    try:
        return GovernanceActionType(value.strip().lower())
    except ValueError:
        return None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


__all__ = [
    "IntentClass",
    "IntentClassification",
    "IntentClassifierCognition",
]
