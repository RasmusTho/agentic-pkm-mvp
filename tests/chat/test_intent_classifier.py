"""Intent classifier cognition — acceptance tests (no live LLM provider).

Covers the LLM-backed cognition that labels a canvas co-authoring *intent*
(not the generated body) as co-authoring / governance-bearing / exploratory,
and — when governance-bearing — into the correct ``GovernanceActionType``.

The cognition is pure: it consults the shared ``ReasoningFacade`` and returns a
typed label. It never mutates a note, calls ``CanvasWriter``, or stages a Panel
intent. A degraded/mock/unparseable backend must never fabricate a governance
routing; it defaults conservatively to co-authoring.

Implements CANVAS_CHAT_SURFACE/CLASSIFY_COAUTHORING_INTENT (issue #1743).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.chat.governance_router import GovernanceActionType
from app.chat.intent_classifier import (
    IntentClass,
    IntentClassification,
    IntentClassifierCognition,
)
from app.reasoning.models import ReasoningMode, ReasoningRun


class _LabelStub:
    """Deterministic facade stub returning a fixed classification label.

    Records calls so tests can assert the cognition consulted the facade with
    the intent, and nothing else.
    """

    def __init__(self, label: str, *, status: str = "ok") -> None:
        self._label = label
        self._status = status
        self.calls: list[dict[str, object]] = []

    def answer(
        self,
        question: str,
        *,
        context: str | None = None,
        object_ids: list[str] | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        self.calls.append(
            {"question": question, "context": context, "trace_id": trace_id}
        )
        return ReasoningRun(
            id="run-intent-1",
            mode=ReasoningMode.ASK_ANSWER,
            status=self._status,  # type: ignore[arg-type]
            result=None if self._status != "ok" else {"answer": self._label},
            object_uuids=[],
            trace_id=trace_id,
            error=None if self._status == "ok" else "provider failed",
        )


def _classify(label: str, intent: str, *, status: str = "ok") -> IntentClassification:
    facade = _LabelStub(label, status=status)
    cognition = IntentClassifierCognition(facade_factory=lambda: facade)
    return cognition.classify(intent=intent)


# ---------------------------------------------------------------------------
# Governance-bearing classes → correct GovernanceActionType
# ---------------------------------------------------------------------------


def test_maturity_intent_classified_governance_bearing() -> None:
    result = _classify(
        '{"intent_class": "governance_bearing", "action_type": "maturity_transition"}',
        intent="promote this note to evergreen",
    )
    assert result.intent_class is IntentClass.GOVERNANCE_BEARING
    assert result.action_type is GovernanceActionType.MATURITY_TRANSITION
    assert result.classified is True


def test_frontmatter_intent_classified() -> None:
    result = _classify(
        '{"intent_class": "governance_bearing", "action_type": "frontmatter_update"}',
        intent="add the tag #decision to this note's frontmatter",
    )
    assert result.intent_class is IntentClass.GOVERNANCE_BEARING
    assert result.action_type is GovernanceActionType.FRONTMATTER_UPDATE


def test_lifecycle_intent_classified() -> None:
    result = _classify(
        '{"intent_class": "governance_bearing", "action_type": "note_lifecycle"}',
        intent="archive this note and rename it",
    )
    assert result.intent_class is IntentClass.GOVERNANCE_BEARING
    assert result.action_type is GovernanceActionType.NOTE_LIFECYCLE


def test_cross_note_intent_classified() -> None:
    result = _classify(
        '{"intent_class": "governance_bearing", "action_type": "cross_note"}',
        intent="merge this note with my other planning note",
    )
    assert result.intent_class is IntentClass.GOVERNANCE_BEARING
    assert result.action_type is GovernanceActionType.CROSS_NOTE


# ---------------------------------------------------------------------------
# Co-authoring / exploratory → no governance action
# ---------------------------------------------------------------------------


def test_body_edit_intent_classified_coauthoring() -> None:
    result = _classify(
        '{"intent_class": "co_authoring", "action_type": null}',
        intent="expand the decision section with the trade-offs",
    )
    assert result.intent_class is IntentClass.CO_AUTHORING
    assert result.action_type is None
    assert result.classified is True


def test_exploratory_intent_classified() -> None:
    result = _classify(
        '{"intent_class": "exploratory", "action_type": null}',
        intent="what does this note argue?",
    )
    assert result.intent_class is IntentClass.EXPLORATORY
    assert result.action_type is None


# ---------------------------------------------------------------------------
# Conservative degraded policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,status",
    [
        ("MOCK_ASK_ANSWER: classify intent | context: ...", "ok"),  # mock backend
        ("this is not a parseable classification", "ok"),  # unparseable
        ("", "ok"),  # empty
        ("{\"intent_class\": \"governance_bearing\"}", "failed"),  # failed run
    ],
)
def test_degraded_backend_defaults_coauthoring(label: str, status: str) -> None:
    result = _classify(label, intent="promote this note to evergreen", status=status)
    # Never fabricate a governance routing from an untrusted/degraded response.
    assert result.classified is False
    assert result.intent_class is IntentClass.CO_AUTHORING
    assert result.action_type is None


# ---------------------------------------------------------------------------
# Purity: no mutation, no writer / Panel pipeline
# ---------------------------------------------------------------------------


def test_classifier_is_pure_no_writes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    original = "---\nuuid: u1\n---\n\n# Hello\n\nBody.\n"
    note.write_text(original, encoding="utf-8")

    facade = _LabelStub('{"intent_class": "co_authoring", "action_type": null}')
    cognition = IntentClassifierCognition(facade_factory=lambda: facade)
    result = cognition.classify(
        intent="tighten the intro",
        current_body=note.read_text(encoding="utf-8"),
        trace_id="trace-pure-1",
    )

    assert isinstance(result, IntentClassification)
    # The note on disk is untouched — the cognition performs no writes.
    assert note.read_text(encoding="utf-8") == original
    # Only the injected facade was consulted, exactly once, with the intent.
    assert len(facade.calls) == 1
    assert "tighten the intro" in str(facade.calls[0]["question"])
    assert facade.calls[0]["trace_id"] == "trace-pure-1"

    # Structurally pure: the module imports no writer / Panel-pipeline symbol
    # into its namespace (checked on bound names, not docstring prose).
    import app.chat.intent_classifier as mod

    for forbidden in ("CanvasWriter", "GovernanceRouter", "write_note_from_absolute"):
        assert forbidden not in vars(mod), f"{forbidden} must not be imported"
