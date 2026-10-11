"""Production-route coverage for Standing Questions registration (#4611)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.capture as capture_module
import app.api.routes.companion as companion_module
from app.api.app import app
from app.components.llm.question_intent_classifier import (
    QuestionIntentClass,
    QuestionIntentClassification,
    QuestionIntentClassifierCognition,
)
from app.model_access.catalog import CatalogError
from app.standing_questions.registration import RegistrationProposalResult
from tests.api._vault_test_helpers import bind_initialized_vault
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


def test_capture_catalog_failure_is_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    bind_initialized_vault(monkeypatch, vault, store_dir=tmp_path)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))

    classifier_calls: list[str] = []

    def _catalog_unavailable(
        self: QuestionIntentClassifierCognition,
        *,
        capture_text: str,
        trace_id: str | None = None,
    ) -> QuestionIntentClassification:
        del self, trace_id
        classifier_calls.append(capture_text)
        raise CatalogError("catalog_invalid")

    monkeypatch.setattr(
        QuestionIntentClassifierCognition, "classify", _catalog_unavailable
    )

    resp = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "question classification must not undo the capture"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["registration_state"] == "degraded"
    assert classifier_calls == [
        "- ["
        + resp.json()["captured_at"]
        + "] question classification must not undo the capture"
    ]
    assert (vault / "Inbox" / "inbox.md").read_text(encoding="utf-8").count(
        "question classification must not undo the capture"
    ) == 1


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
