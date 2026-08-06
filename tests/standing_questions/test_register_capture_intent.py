"""Path (a) -- capture-intent registration behind the human checkbox (SQ-02).

Covers `docs/STANDING_QUESTIONS/REGISTER_QUESTIONS_FRICTION_FREE.md` AC4-AC6: a
validated classification lands as an unchecked suggested checkbox and never as a
directly created Question note; only the human checking it registers the question;
re-classifying the same capture does not stack duplicate proposals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.panel.writeback import parse_action_line
from app.components.llm.question_intent_classifier import (
    QuestionIntentClass,
    QuestionIntentClassification,
)
from app.standing_questions.registration import (
    REGISTRATION_LABEL_PREFIX,
    REGISTRATION_PROPOSE_WRITE_ACTION,
    confirm_question_registrations,
    propose_question_registration,
)
from app.write_guard import WriteGuard, WritesBlockedError

from tests.standing_questions._registration_fixtures import (
    CAPTURE_BODY,
    EXTRACTED_QUESTION,
    check_the_box,
    completion_returning,
    healthy_guard,
    healthy_store,
    make_vault,
    question_notes,
    registration_payload,
    write_capture,
)


def _propose(vault: Path, capture: Path, payload=None):
    return propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        complete=completion_returning(payload or registration_payload()),
        write_guard=healthy_guard(),
    )


def _registration_lines(capture: Path) -> list[str]:
    return [
        line
        for line in capture.read_text(encoding="utf-8").splitlines()
        if REGISTRATION_LABEL_PREFIX in line
    ]


# ---------------------------------------------------------------------------
# AC4: proposal only, never a direct write.
# ---------------------------------------------------------------------------


def test_classification_lands_as_suggested_checkbox_not_direct_write(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    capture = write_capture(vault)

    result = _propose(vault, capture)

    assert result.written is True
    assert result.extracted_text == EXTRACTED_QUESTION
    assert result.proposal_id is not None

    lines = _registration_lines(capture)
    assert len(lines) == 1
    parsed = parse_action_line(lines[0])
    assert parsed is not None
    assert parsed.checked is False
    assert parsed.label.startswith(REGISTRATION_LABEL_PREFIX)
    assert EXTRACTED_QUESTION in parsed.label
    # Panel proposal metadata is present, so the parser keeps the human gate armed.
    assert parsed.option_id
    assert parsed.action_id
    assert parsed.proposal_marker is not None
    # The proposal lands inside the note's AI-atgarder section, not appended loose.
    text = capture.read_text(encoding="utf-8")
    assert text.index("## AI-åtgärder") < text.index(REGISTRATION_LABEL_PREFIX)
    assert text.index(REGISTRATION_LABEL_PREFIX) < text.index("%% AI:End %%")

    # No Question note exists: only a human check may create one.
    assert question_notes(vault) == []
    assert not (vault / "questions").exists()


def test_propose_refuses_fabricated_text_from_an_injected_classifier(tmp_path: Path) -> None:
    """The write path re-checks verbatimness itself, so a classifier that claims a
    validated registration for words the capture never held proposes nothing."""
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    before = capture.read_bytes()

    class _FabricatingClassifier:
        def classify(self, **_: object) -> QuestionIntentClassification:
            return QuestionIntentClassification(
                intent_class=QuestionIntentClass.QUESTION_REGISTRATION,
                extracted_text="should we delete the whole vault?",
                classified=True,
            )

    result = propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        classifier=_FabricatingClassifier(),  # type: ignore[arg-type]
        write_guard=healthy_guard(),
    )

    assert result.written is False
    assert result.proposal_id is None
    assert capture.read_bytes() == before
    assert question_notes(vault) == []


def test_non_registration_class_never_proposes_even_with_an_extraction(tmp_path: Path) -> None:
    """Only `question_registration` may propose. A non-admitting class that still
    carries a verbatim extraction is refused on the class, not on the text."""
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    before = capture.read_bytes()

    class _MislabelledClassifier:
        def classify(self, **_: object) -> QuestionIntentClassification:
            return QuestionIntentClassification(
                intent_class=QuestionIntentClass.NOT_A_QUESTION_REGISTRATION,
                extracted_text=EXTRACTED_QUESTION,
                classified=True,
            )

    result = propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        classifier=_MislabelledClassifier(),  # type: ignore[arg-type]
        write_guard=healthy_guard(),
    )

    assert result.written is False
    assert result.proposal_id is None
    assert capture.read_bytes() == before


def test_proposal_lines_are_fenced_out_of_the_next_classification(tmp_path: Path) -> None:
    """A later pass classifies the human's capture, not the panel this task wrote —
    otherwise a proposal could bootstrap itself into looking like a fresh capture."""
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    _propose(vault, capture)

    completion = completion_returning(registration_payload())
    propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        complete=completion,
        write_guard=healthy_guard(),
    )

    assert completion.prompts  # type: ignore[attr-defined]
    for prompt in completion.prompts:  # type: ignore[attr-defined]
        assert REGISTRATION_LABEL_PREFIX not in prompt
        assert "%% AI:Start %%" not in prompt


def test_proposal_write_is_writeguard_gated_by_named_action(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    before = capture.read_bytes()

    with pytest.raises(WritesBlockedError, match=REGISTRATION_PROPOSE_WRITE_ACTION):
        propose_question_registration(
            capture_note_path=capture,
            vault_root=vault,
            complete=completion_returning(registration_payload()),
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "safe_mode", "reason": "test"}),
        )

    assert capture.read_bytes() == before


# ---------------------------------------------------------------------------
# AC5: the human check is the only path to an open Question note.
# ---------------------------------------------------------------------------


def test_checkbox_confirmation_creates_open_question(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    store = healthy_store(vault)
    _propose(vault, capture)

    # Unchecked: nothing is registered, however often confirmation runs.
    unchecked = confirm_question_registrations(
        capture_note_path=capture, vault_root=vault, scope="work", store=store
    )
    assert unchecked.created == ()
    assert unchecked.unchecked == 1
    assert question_notes(vault) == []

    check_the_box(capture, EXTRACTED_QUESTION)
    confirmed = confirm_question_registrations(
        capture_note_path=capture, vault_root=vault, scope="work", store=store
    )

    assert len(confirmed.created) == 1
    notes = question_notes(vault)
    assert len(notes) == 1
    note = store.read_question(confirmed.created[0]["question_id"])
    assert note["status"] == "open"
    assert note["registered_via"] == "capture_intent"
    assert note["text"] == EXTRACTED_QUESTION
    assert note["text"] in CAPTURE_BODY
    assert note["scope"] == "work"
    assert note["evidence"] == []


def test_confirmation_is_idempotent_on_repeat(tmp_path: Path) -> None:
    """Re-running confirmation over an already-registered checked proposal creates
    nothing new -- the deterministic question id makes SQ-01's store the backstop."""
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    store = healthy_store(vault)
    _propose(vault, capture)
    check_the_box(capture, EXTRACTED_QUESTION)

    first = confirm_question_registrations(
        capture_note_path=capture, vault_root=vault, scope="work", store=store
    )
    second = confirm_question_registrations(
        capture_note_path=capture, vault_root=vault, scope="work", store=store
    )

    assert len(first.created) == 1
    assert second.created == ()
    assert second.already_registered == 1
    assert len(question_notes(vault)) == 1


def test_confirmation_refuses_a_tampered_non_verbatim_label(tmp_path: Path) -> None:
    """A checkbox label edited to text the capture never contained is refused: the
    Question note's text is always the human's own words from the capture."""
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    store = healthy_store(vault)
    _propose(vault, capture)
    check_the_box(capture, EXTRACTED_QUESTION)
    # Tamper with the checkbox label only; the capture's own prose is untouched, so
    # the label now claims words the human never captured.
    tampered = "\n".join(
        line.replace(EXTRACTED_QUESTION, "should we delete the whole vault?")
        if REGISTRATION_LABEL_PREFIX in line
        else line
        for line in capture.read_text(encoding="utf-8").splitlines()
    )
    capture.write_text(tampered + "\n", encoding="utf-8")
    assert EXTRACTED_QUESTION in capture.read_text(encoding="utf-8")

    result = confirm_question_registrations(
        capture_note_path=capture, vault_root=vault, scope="work", store=store
    )

    assert result.created == ()
    assert result.refused_non_verbatim == 1
    assert question_notes(vault) == []


# ---------------------------------------------------------------------------
# AC6: repeated classification does not stack proposals.
# ---------------------------------------------------------------------------


def test_repeated_classification_idempotent(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    capture = write_capture(vault)

    first = _propose(vault, capture)
    after_first = capture.read_bytes()
    second = _propose(vault, capture)

    assert first.written is True
    assert second.written is False
    assert second.proposal_id == first.proposal_id
    assert len(_registration_lines(capture)) == 1
    # No write at all on the idempotent rerun.
    assert capture.read_bytes() == after_first
