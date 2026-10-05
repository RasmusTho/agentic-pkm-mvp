"""Intent classifier cognition — acceptance tests (no live LLM provider).

Covers the LLM-backed cognition that labels a canvas co-authoring *intent*
(not the generated body) as co-authoring / governance-bearing / exploratory,
and — when governance-bearing — into the correct ``GovernanceActionType``.

The cognition is pure: it runs a typed Product judgment through the
existing Product MARR client and returns a typed
label. It never mutates a note, calls ``CanvasWriter``, or stages a Panel
intent. A degraded/mock/unvalidated completion must never fabricate a
routing; it yields the explicit ``UNKNOWN`` class (KERNEL-07, #2769 — the
former silent ``CO_AUTHORING`` default is gone).

Implements CANVAS_CHAT_SURFACE/CLASSIFY_COAUTHORING_INTENT (issue #1743);
UNKNOWN semantics per RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.eval.classification import ClassificationReplayClient

from app.components.llm.intent_classifier import (
    GovernanceActionType,
    IntentClass,
    IntentClassification,
    IntentClassifierCognition,
)


class _JudgmentStub(ClassificationReplayClient):
    def __init__(self, label: str, *, fail: bool = False) -> None:
        super().__init__(label)
        self.fail = fail
        self.calls: list[str] = []

    def judge_product_intent(self, intent_text):
        self.calls.append(intent_text)
        if self.fail:
            raise RuntimeError("provider failed")
        return super().judge_product_intent(intent_text)


def _classify(label: str, intent: str, *, fail: bool = False) -> IntentClassification:
    completion = _JudgmentStub(label, fail=fail)
    cognition = IntentClassifierCognition(judgment_client=completion)
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


def test_governance_without_action_remains_unknown() -> None:
    result = _classify(
        '{"intent_class": "governance_bearing", "action_type": null}', intent="promote this note",
    )
    assert result.intent_class is IntentClass.UNKNOWN
    assert result.action_type is None
    assert result.classified is False


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
# Explicit UNKNOWN on validation failure (no CO_AUTHORING default)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,fail",
    [
        ("MOCK_ASK_ANSWER: classify intent | context: ...", False),  # mock backend
        ("this is not a parseable classification", False),  # unparseable
        ("", False),  # empty
        ('{"intent_class": "governance_bearing"}', True),  # failed run
        ('{"intent_class": "co_authoring"}', False),  # missing required key
        ('{"intent_class": "unknown", "action_type": null}', False),  # not emittable
    ],
)
def test_degraded_backend_yields_explicit_unknown(label: str, fail: bool) -> None:
    result = _classify(label, intent="promote this note to evergreen", fail=fail)
    # Never fabricate any routing from an untrusted/degraded/invalid response —
    # and never default to a mutation-capable class (KERNEL-07).
    assert result.classified is False
    assert result.intent_class is IntentClass.UNKNOWN
    assert result.action_type is None
    assert result.rationale  # carries the failure reason for diagnostics


# ---------------------------------------------------------------------------
# Purity: no mutation, no writer / Panel pipeline
# ---------------------------------------------------------------------------


def test_classifier_is_pure_no_writes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    original = "---\nuuid: u1\n---\n\n# Hello\n\nBody.\n"
    note.write_text(original, encoding="utf-8")

    completion = _JudgmentStub('{"intent_class": "co_authoring", "action_type": null}')
    cognition = IntentClassifierCognition(judgment_client=completion)
    result = cognition.classify(
        intent="tighten the intro",
        trace_id="trace-pure-1",
    )

    assert isinstance(result, IntentClassification)
    # The note on disk is untouched — the cognition performs no writes.
    assert note.read_text(encoding="utf-8") == original
    # Only the injected judgment client was consulted, exactly once, with the intent.
    assert len(completion.calls) == 1
    assert completion.calls == ["tighten the intro"]
    assert result.trace_id == "trace-pure-1"

    # Structurally pure: the module imports no writer / Panel-pipeline symbol
    # into its namespace (checked on bound names, not docstring prose).
    import app.components.llm.intent_classifier as mod

    for forbidden in ("CanvasWriter", "GovernanceRouter", "write_note_from_absolute"):
        assert forbidden not in vars(mod), f"{forbidden} must not be imported"
