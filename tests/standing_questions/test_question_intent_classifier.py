"""Capture-intent classification for Standing Questions registration (SQ-02).

Covers `docs/STANDING_QUESTIONS/REGISTER_QUESTIONS_FRICTION_FREE.md` AC1-AC3 and
AC8: the classifier is LLM-backed through the shared schema-constrained-completion
utility, degrades to an explicit `UNKNOWN` that registers nothing, validates on the
production entrypoint, and can never bypass the human checkbox-confirm step.
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

import jsonschema
import pytest

import app.components.llm.constrained as constrained_module
from app.components.llm.constrained import registered_schema
from app.components.llm.question_intent_classifier import (
    QUESTION_INTENT_SCHEMA_REF,
    QuestionIntentClass,
    QuestionIntentClassifierCognition,
)
from app.standing_questions.registration import propose_question_registration

from tests.standing_questions._registration_fixtures import (
    CAPTURE_BODY,
    EXTRACTED_QUESTION,
    NON_QUESTION_BODY,
    NON_QUESTION_REL_PATH,
    completion_returning,
    healthy_guard,
    make_vault,
    question_notes,
    registration_payload,
    write_capture,
)


def _classify(raw: str | dict, capture_text: str = CAPTURE_BODY):
    return QuestionIntentClassifierCognition(
        completion=completion_returning(raw)
    ).classify(capture_text=capture_text)


# ---------------------------------------------------------------------------
# AC1: explicit registration intent, verbatim extraction.
# ---------------------------------------------------------------------------


def test_capture_intent_classified_and_extracted() -> None:
    result = _classify(registration_payload())

    assert result.intent_class is QuestionIntentClass.QUESTION_REGISTRATION
    assert result.classified is True
    assert result.extracted_text == EXTRACTED_QUESTION
    # Verbatim, never a paraphrase: the extraction must occur in the capture
    # byte-for-byte, which is what makes the eventual Question note the human's
    # own words rather than the classifier's.
    assert result.extracted_text in CAPTURE_BODY


def test_paraphrased_extraction_is_refused_not_registered() -> None:
    """A schema-valid classification whose extraction is not verbatim in the capture
    is downgraded to UNKNOWN -- the classifier may never invent question text."""
    result = _classify(registration_payload("Should we adopt a different embedding model?"))

    assert result.intent_class is QuestionIntentClass.UNKNOWN
    assert result.classified is False
    assert result.extracted_text is None


# ---------------------------------------------------------------------------
# AC2: non-registration intent and degraded backend never register.
# ---------------------------------------------------------------------------


def test_unknown_never_silently_registers(tmp_path: Path) -> None:
    negative = _classify(
        registration_payload(None, intent_class="not_a_question_registration"),
        capture_text=NON_QUESTION_BODY,
    )
    assert negative.intent_class is QuestionIntentClass.NOT_A_QUESTION_REGISTRATION
    assert negative.classified is True
    assert negative.extracted_text is None

    garbage = _classify("not json at all, just prose about migrating to BGE-M3")
    assert garbage.intent_class is QuestionIntentClass.UNKNOWN
    assert garbage.classified is False
    assert garbage.extracted_text is None

    def _degraded_backend(**_: object) -> str:
        raise RuntimeError("classification backend unavailable")

    degraded = QuestionIntentClassifierCognition(completion=_degraded_backend).classify(
        capture_text=CAPTURE_BODY
    )
    assert degraded.intent_class is QuestionIntentClass.UNKNOWN
    assert degraded.classified is False

    # And neither non-admitting outcome may reach the store through path (a).
    vault = make_vault(tmp_path)
    capture = write_capture(vault, NON_QUESTION_REL_PATH, NON_QUESTION_BODY)
    before = capture.read_bytes()
    for completion in (
        completion_returning(
            registration_payload(None, intent_class="not_a_question_registration")
        ),
        completion_returning("garbage"),
        _degraded_backend,
    ):
        result = propose_question_registration(
            capture_note_path=capture,
            vault_root=vault,
            complete=completion,
            write_guard=healthy_guard(),
        )
        assert result.written is False
        assert result.proposal_id is None
    assert capture.read_bytes() == before
    assert question_notes(vault) == []


# ---------------------------------------------------------------------------
# AC3 (enforcement): validation runs on the production classify() entrypoint.
# ---------------------------------------------------------------------------


def test_validation_invoked_from_production_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    validated: list[tuple[str, object]] = []
    real_validate = constrained_module.validate_payload

    def _spy(schema_ref: str, payload: object):
        validated.append((schema_ref, payload))
        return real_validate(schema_ref, payload)

    monkeypatch.setattr(constrained_module, "validate_payload", _spy)

    result = QuestionIntentClassifierCognition(
        completion=completion_returning(registration_payload())
    ).classify(capture_text=CAPTURE_BODY)

    assert result.intent_class is QuestionIntentClass.QUESTION_REGISTRATION
    assert [ref for ref, _payload in validated] == [QUESTION_INTENT_SCHEMA_REF]


def test_schema_rejects_unknown_as_a_model_emittable_class() -> None:
    """`UNKNOWN` is a local failure result, never something the model may claim."""
    with pytest.raises(constrained_module.ConstrainedCompletionError):
        constrained_module.validate_payload(
            QUESTION_INTENT_SCHEMA_REF,
            {"intent_class": "unknown", "extracted_text": None},
        )


# ---------------------------------------------------------------------------
# AC8 (fuzz): garbage classifier output never bypasses the checkbox.
# ---------------------------------------------------------------------------


def _garbage_outputs(rng: random.Random, count: int) -> list[str]:
    """Adversarial garbage: noise, non-objects, near-miss enums, prose-wrapped JSON."""
    near_misses = [
        "QUESTION_REGISTRATION",
        "question-registration",
        "unknown",
        "question_registration ",
        "",
        None,
        1,
        True,
        ["question_registration"],
    ]
    outputs: list[str] = []
    for _ in range(count):
        pick = rng.randrange(7)
        if pick == 0:
            outputs.append("".join(rng.choices(string.printable, k=rng.randrange(0, 80))))
        elif pick == 1:
            outputs.append(json.dumps(rng.choice([None, True, 3.14, "question_registration", [1]])))
        elif pick == 2:
            outputs.append(
                json.dumps(
                    {
                        "".join(rng.choices(string.ascii_lowercase, k=5)): rng.random()
                        for _ in range(rng.randrange(0, 4))
                    }
                )
            )
        elif pick == 3:
            outputs.append(
                json.dumps(
                    {
                        "intent_class": rng.choice(near_misses),
                        "extracted_text": rng.choice(near_misses),
                    }
                )
            )
        elif pick == 4:
            outputs.append(
                'Sure: {"intent_class": "question_registration", '
                f'"extracted_text": "{EXTRACTED_QUESTION}"}} as requested.'
            )
        elif pick == 5:
            outputs.append('{"intent_class": "question_registration", "extracted_te')
        else:
            # Schema-valid but fabricated extraction: the model invents text the
            # capture never contained.
            outputs.append(
                json.dumps(
                    {
                        "intent_class": "question_registration",
                        "extracted_text": "".join(
                            rng.choices(string.ascii_letters + " ", k=rng.randrange(1, 40))
                        ),
                    }
                )
            )
    return outputs


def test_fuzz_classifier_never_bypasses_checkbox(tmp_path: Path) -> None:
    rng = random.Random(3328)
    schema = registered_schema(QUESTION_INTENT_SCHEMA_REF)
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    guard = healthy_guard()

    for raw in _garbage_outputs(rng, 300):
        result = propose_question_registration(
            capture_note_path=capture,
            vault_root=vault,
            complete=completion_returning(raw),
            write_guard=guard,
        )
        # A Question note is never created by path (a), whatever the model emits.
        assert question_notes(vault) == []
        text = capture.read_text(encoding="utf-8")
        # Every registration line this path can ever write is unchecked.
        assert "- [x]" not in text.lower()

        if result.classification.intent_class is QuestionIntentClass.UNKNOWN:
            assert result.classification.classified is False
            assert result.written is False
            continue
        # Anything that classified must be provably schema-validated output.
        payload = json.loads(raw)
        jsonschema.validate(payload, schema)
        assert result.classification.classified is True
        if result.proposal_id is not None:
            # A proposal is only ever a suggestion line on the capture note.
            assert result.extracted_text is not None
            assert result.extracted_text in CAPTURE_BODY
            assert f'- [ ] Registrera stående fråga: "{result.extracted_text}"' in text
