"""Production-route coverage for Standing Questions registration (#4611)."""

from __future__ import annotations

from pathlib import Path

import app.api.routes.capture as capture_module
import app.api.routes.companion as companion_module
from app.components.llm.question_intent_classifier import QuestionIntentClass, QuestionIntentClassification
from app.standing_questions.registration import RegistrationProposalResult
from tests.standing_questions._registration_fixtures import make_vault, question_notes


def test_capture_flow_surfaces_registration_proposals(tmp_path: Path, monkeypatch) -> None:
    vault = make_vault(tmp_path)
    capture = vault / "Inbox" / "inbox.md"
    capture.parent.mkdir()
    capture.write_text("question", encoding="utf-8")
    proposal = RegistrationProposalResult(
        classification=QuestionIntentClassification(
            intent_class=QuestionIntentClass.QUESTION_REGISTRATION, classified=True
        ),
        proposal_id="proposal-1",
    )
    monkeypatch.setattr(capture_module, "propose_question_registration", lambda **_: proposal)
    result = capture_module._offer_question_registration_proposal(
        vault_root=vault, note_rel="Inbox/inbox.md", trace_id="trace"
    )
    assert result == proposal


def test_companion_explicit_registration_route_writes_question(tmp_path: Path, monkeypatch) -> None:
    vault = make_vault(tmp_path)
    monkeypatch.setattr(companion_module, "_active_companion_vault_root_or_picker", lambda **_: vault)
    response = companion_module.register_companion_question(
        companion_module.QuestionRegistrationRequest(
            text="Should we keep the architecture decision open?", scope="work"
        )
    )
    assert response.status == "open"
    assert response.registered_via == "explicit"
    assert len(question_notes(vault)) == 1
