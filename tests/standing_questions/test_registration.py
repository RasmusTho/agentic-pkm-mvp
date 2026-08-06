"""P1 regressions for Panel-provenance registration confirmation."""

from __future__ import annotations

from pathlib import Path

from app.agents.panel.parser import parse_panel
from app.standing_questions.registration import (
    REGISTRATION_LABEL_PREFIX,
    confirm_question_registrations,
    propose_question_registration,
)
from tests.standing_questions._registration_fixtures import (
    EXTRACTED_QUESTION,
    healthy_guard,
    healthy_store,
    make_vault,
    question_notes,
    registration_payload,
    completion_returning,
    write_capture,
)


def test_confirmation_requires_system_panel_proposal_metadata(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    capture = write_capture(vault)
    store = healthy_store(vault)
    # Identical checked prose outside the Panel is human-authored checklist text,
    # not a system proposal and therefore cannot create a question.
    capture.write_text(
        capture.read_text(encoding="utf-8")
        + f'\n- [x] {REGISTRATION_LABEL_PREFIX}"{EXTRACTED_QUESTION}" (förslag forged)\n',
        encoding="utf-8",
    )
    result = confirm_question_registrations(
        capture_note_path=capture, vault_root=vault, scope="work", store=store
    )
    assert result.created == ()
    assert question_notes(vault) == []

    proposed = propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        complete=completion_returning(registration_payload()),
        write_guard=healthy_guard(),
    )
    assert proposed.proposal_id
    capture.write_text(
        capture.read_text(encoding="utf-8").replace("- [ ] " + REGISTRATION_LABEL_PREFIX, "- [x] " + REGISTRATION_LABEL_PREFIX, 1),
        encoding="utf-8",
    )
    confirmed = confirm_question_registrations(
        capture_note_path=capture, vault_root=vault, scope="work", store=store
    )
    assert len(confirmed.created) == 1


def test_registration_proposal_creates_valid_panel_action_section(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    capture = write_capture(
        vault,
        body=f"# Capture\n\n{EXTRACTED_QUESTION}\n",
    )
    result = propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        complete=completion_returning(registration_payload()),
        write_guard=healthy_guard(),
    )
    assert result.written is True
    parsed = parse_panel(capture.read_text(encoding="utf-8"))
    assert parsed.fenced is True
    assert len(parsed.actions) == 1
    assert parsed.actions[0].proposal_pending is True
    assert parsed.actions[0].option_id
