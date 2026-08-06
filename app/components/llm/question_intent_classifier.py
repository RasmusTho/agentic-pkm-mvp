"""Capture-intent classification for Standing Questions registration (SQ-02).

Sibling of :mod:`app.components.llm.intent_classifier` — same pattern, different
intent taxonomy. This cognition labels an ordinary capture's text as either
``question_registration`` (the human said something like "find out whether X" /
"jag undrar om X") or ``not_a_question_registration``, and extracts the question
itself.

It is LLM-backed through the shared constrained-completion utility
(``app/components/llm/constrained.py``): the model is asked for schema-constrained
JSON and the completion is **validated against the registered schema before any
routing decision** (KERNEL-07, audit invariants I-A1/I-A2,
``docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md``). The
raw completion function is injectable for tests; validation always runs below the
injection point. Keyword heuristics are explicitly not the mechanism here — the
governing spec forbids replacing the classifier with one.

The cognition is **pure**: it reads the capture text and returns a typed label. It
never writes to disk, never creates a Question note, and never stages a proposal.
Registration is `app.standing_questions.registration`'s job, and even there a
validated classification only ever becomes an unchecked suggested checkbox.

Two explicit non-admitting outcomes, neither of which can register anything:

- ``UNKNOWN`` when the provider fails, the backend is degraded, or the completion
  does not validate. There is no silent action-capable default.
- ``UNKNOWN`` when a *schema-valid* ``question_registration`` carries an
  ``extracted_text`` that is not present verbatim in the capture. The Question
  note's text must always be the human's own words (``REGISTER_QUESTIONS_FRICTION_FREE.md``
  :: "never a paraphrase or summary the classifier invents"), so a fabricated or
  paraphrased extraction is refused rather than proposed.
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


class QuestionIntentClass(str, Enum):
    """Capture-intent classes, plus the explicit ``UNKNOWN`` failure class.

    ``UNKNOWN`` is deliberately absent from the model-facing schema enum: it is
    never a class the model may emit, only the local result of a refused or failed
    validation. It authorizes nothing.
    """

    QUESTION_REGISTRATION = "question_registration"
    NOT_A_QUESTION_REGISTRATION = "not_a_question_registration"
    UNKNOWN = "unknown"


#: Registered schema for the classification completion. The model must return
#: exactly one JSON object of this shape; anything else is a validation failure
#: and yields ``UNKNOWN``.
QUESTION_INTENT_SCHEMA_REF = "standing_questions.capture_intent_classification.v1"

_QUESTION_INTENT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "intent_class": {
            "enum": [
                QuestionIntentClass.QUESTION_REGISTRATION.value,
                QuestionIntentClass.NOT_A_QUESTION_REGISTRATION.value,
            ]
        },
        "extracted_text": {"type": ["string", "null"]},
        "rationale": {"type": ["string", "null"]},
    },
    "required": ["intent_class", "extracted_text"],
}

register_schema(QUESTION_INTENT_SCHEMA_REF, _QUESTION_INTENT_SCHEMA)


@dataclass(frozen=True)
class QuestionIntentClassification:
    """Result of classifying one capture for question-registration intent.

    ``extracted_text`` is set **iff** ``intent_class`` is ``QUESTION_REGISTRATION``,
    and is then guaranteed to occur verbatim in the capture that was classified.
    ``classified`` is ``False`` **iff** ``intent_class`` is ``UNKNOWN``.
    """

    intent_class: QuestionIntentClass
    extracted_text: str | None = None
    classified: bool = True
    rationale: str | None = None
    trace_id: str | None = None


class QuestionIntentClassifierCognition:
    """Classify a capture for question-registration intent.

    The raw LLM completion is injectable via ``completion`` so tests can supply a
    deterministic stub instead of a live provider. Schema validation runs inside
    :func:`constrained_completion` on this side of the injection seam, so the
    production ``classify()`` path always validates.
    """

    def __init__(self, *, completion: CompletionFn | None = None) -> None:
        self._completion = completion

    def classify(
        self,
        *,
        capture_text: str,
        trace_id: str | None = None,
    ) -> QuestionIntentClassification:
        """Return the capture-intent class (and verbatim question, if any).

        Never raises on a degraded backend or invalid output: anything that does
        not validate yields the explicit ``UNKNOWN`` classification
        (``classified=False``) instead of a silent registration.
        """
        try:
            payload = constrained_completion(
                QUESTION_INTENT_SCHEMA_REF,
                system=_SYSTEM_PROMPT,
                user=_build_user_prompt(capture_text),
                task_kind="decide",
                trace_id=trace_id,
                complete=self._completion,
            )
        except ConstrainedCompletionError as exc:
            # Fail-loud observability: without this line a provider outage is
            # indistinguishable from "the owner captured nothing worth registering".
            logger.warning(
                "capture-intent classification degraded to UNKNOWN (schema_ref=%s trace_id=%s): %s",
                QUESTION_INTENT_SCHEMA_REF,
                trace_id or "-",
                exc.reason,
            )
            return _unknown(trace_id, reason=exc.reason)
        return _from_validated(payload, capture_text=capture_text, trace_id=trace_id)


# ---------------------------------------------------------------------------
# Prompt + context
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "You are reading one capture the owner just made (a voice note, a clipping, a "
    "quick note to self). Decide whether it contains an intent to register a "
    "standing question — something the owner wants answered over time, phrased as "
    '"find out whether X", "jag undrar om X", "should we X?", and so on. Return '
    "ONLY a JSON object, no commentary:\n"
    '{"intent_class": "<question_registration|not_a_question_registration>", '
    '"extracted_text": "<the question, copied verbatim from the capture, or null>"}\n\n'
    "Rules:\n"
    "- extracted_text must be copied from the capture byte-for-byte. Never "
    "rephrase it, translate it, tidy it, or turn a statement into a question; a "
    "span that is not present verbatim in the capture is rejected and nothing is "
    "registered.\n"
    "- question_registration only when the owner is asking for something to be "
    "found out, not merely mentioning a topic. Otherwise "
    "not_a_question_registration with extracted_text null."
)


def _build_user_prompt(capture_text: str) -> str:
    return f"Capture:\n{capture_text.strip()}"


# ---------------------------------------------------------------------------
# Validated-payload mapping
# ---------------------------------------------------------------------------


def _unknown(trace_id: str | None, *, reason: str) -> QuestionIntentClassification:
    """Explicit UNKNOWN: the only failure result. Authorizes nothing."""
    return QuestionIntentClassification(
        intent_class=QuestionIntentClass.UNKNOWN,
        extracted_text=None,
        classified=False,
        rationale=reason,
        trace_id=trace_id,
    )


def _from_validated(
    payload: dict[str, Any], *, capture_text: str, trace_id: str | None
) -> QuestionIntentClassification:
    """Map a schema-validated payload to a typed classification.

    Only called with payloads that already validated against
    :data:`QUESTION_INTENT_SCHEMA_REF`, so the enum construction cannot fail. The
    verbatim check below is the second, non-schema gate: JSON Schema can prove the
    shape of ``extracted_text`` but not that the model copied it rather than
    invented it.
    """
    intent_class = QuestionIntentClass(payload["intent_class"])
    rationale = _str_or_none(payload.get("rationale"))

    if intent_class is not QuestionIntentClass.QUESTION_REGISTRATION:
        return QuestionIntentClassification(
            intent_class=intent_class,
            extracted_text=None,
            classified=True,
            rationale=rationale,
            trace_id=trace_id,
        )

    extracted = _str_or_none(payload.get("extracted_text"))
    if extracted is None or extracted not in capture_text:
        logger.warning(
            "capture-intent classification refused a non-verbatim extraction "
            "(schema_ref=%s trace_id=%s)",
            QUESTION_INTENT_SCHEMA_REF,
            trace_id or "-",
        )
        return _unknown(trace_id, reason="extracted_text is not verbatim in the capture")
    return QuestionIntentClassification(
        intent_class=QuestionIntentClass.QUESTION_REGISTRATION,
        extracted_text=extracted,
        classified=True,
        rationale=rationale,
        trace_id=trace_id,
    )


def _str_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "QUESTION_INTENT_SCHEMA_REF",
    "QuestionIntentClass",
    "QuestionIntentClassification",
    "QuestionIntentClassifierCognition",
]
