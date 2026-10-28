"""Composed fixture acceptance for the Standing Questions lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.routes import panel as panel_route
from app.api.routes import standing_questions as standing_question_routes
from app.expansion.create import SourceInput
from app.panel import checkbox_projection as checkbox_projection_module
from app.panel.checkbox_projection import (
    CheckboxProjectionRequest,
    CheckboxProjectionService,
)
from app.standing_questions import review as review_module
from app.standing_questions.answer_refresh import EVIDENCE_DELTA_REFRESH_THRESHOLD
from app.standing_questions.evidence_matching import (
    CandidateArtifact,
    run_standing_questions_tick,
)
from app.standing_questions.registration import (
    confirm_question_registrations,
    propose_question_registration,
)
from scripts.yaml_roundtrip import load_frontmatter
from tests.standing_questions._registration_fixtures import (
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

pytestmark = pytest.mark.usefixtures("product_model_access_gateway")


def _panel_request(vault: Path) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(compatibility_write_root=vault))


def test_fixture_question_full_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    product_model_access_gateway,
) -> None:
    """A checked capture proposal can gather evidence, draft, and be accepted once."""
    vault = make_vault(tmp_path)
    store = healthy_store(vault)
    capture = write_capture(vault)
    classifier = completion_returning(registration_payload())

    proposal = propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        complete=classifier,
        write_guard=healthy_guard(),
    )
    assert proposal.written is True
    assert proposal.extracted_text == EXTRACTED_QUESTION
    assert question_notes(vault) == []

    proposed_capture = capture.read_bytes()
    proposal_replay = propose_question_registration(
        capture_note_path=capture,
        vault_root=vault,
        complete=classifier,
        write_guard=healthy_guard(),
    )
    assert proposal_replay.proposal_id == proposal.proposal_id
    assert proposal_replay.written is False
    assert capture.read_bytes() == proposed_capture

    check_the_box(capture, EXTRACTED_QUESTION)
    registered = confirm_question_registrations(
        capture_note_path=capture,
        vault_root=vault,
        scope="work",
        store=store,
    )
    assert len(registered.created) == 1
    question_id = registered.created[0]["question_id"]
    registered_note = store.read_question(question_id)
    assert registered_note["text"] == EXTRACTED_QUESTION
    assert registered_note["registered_via"] == "capture_intent"
    assert registered_note["status"] == "open"

    registration_replay = confirm_question_registrations(
        capture_note_path=capture,
        vault_root=vault,
        scope="work",
        store=store,
    )
    assert registration_replay.created == ()
    assert registration_replay.already_registered == 1
    assert len(question_notes(vault)) == 1

    evidence_path = vault / "notes" / "bge-m3-decision.md"
    evidence_path.parent.mkdir(parents=True)
    evidence_text = (
        "# Embedding decision\n\n"
        "We will fully migrate to BGE-M3 before the Q3 planning round.\n"
    )
    evidence_path.write_text(evidence_text, encoding="utf-8")
    evidence_bytes = evidence_path.read_bytes()
    evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    evidence_ref = "vault://notes/bge-m3-decision.md"
    provenance_ref = "outbox://ingest.vault.changed/bge-m3-decision"
    supporting_span = "We will fully migrate to BGE-M3 before the Q3 planning round."
    candidate = CandidateArtifact(
        artifact_ref=evidence_ref,
        source_stream="ingest.vault.changed",
        scope="work",
        provenance_ref=provenance_ref,
    )
    evidence_sources = {
        provenance_ref: SourceInput(
            object_id=provenance_ref,
            note_path="notes/bge-m3-decision.md",
            text=evidence_text,
            language="en",
            review_state="reviewed",
            raw_bytes=evidence_bytes,
        )
    }

    def associate_evidence(
        *,
        system: str,
        user: str,
        trace_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return json.dumps(
            {
                "related": True,
                "confidence_class": "high",
                "relation_label": "states the migration decision",
                "supporting_span": supporting_span,
            }
        )

    product_model_access_gateway.completion_content = (
        "The evidence supports completing the BGE-M3 migration before Q3 planning."
    )
    outbox_path = tmp_path / "outbox.jsonl"
    tick_time = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    first_tick = run_standing_questions_tick(
        vault_root=vault,
        candidates=[candidate],
        evidence_sources=evidence_sources,
        outbox_path=outbox_path,
        store=store,
        complete=associate_evidence,
        write_guard=healthy_guard(),
        now=tick_time,
    )

    assert first_tick.matching.attached == 1
    assert first_tick.refresh.refresh_candidates == (question_id,)
    assert len(store.read_question(question_id)["evidence"]) >= EVIDENCE_DELTA_REFRESH_THRESHOLD
    assert first_tick.refresh.drafted == (question_id,)
    candidate_note, candidate_version = store.read_question_with_version(question_id)
    candidate_ref = candidate_note["candidate_answer_ref"]
    assert candidate_ref and candidate_note["standing_answer_ref"] is None
    assert candidate_note["status"] == "open"
    evidence = candidate_note["evidence"][0]
    assert evidence["artifact_ref"] == evidence_ref
    assert evidence["provenance_ref"] == provenance_ref
    assert evidence["quoted_span"] == supporting_span
    assert evidence["content_hash"] == evidence_hash

    candidate_path = vault / candidate_ref.removeprefix("vault://")
    draft_frontmatter, draft_body = load_frontmatter(
        candidate_path.read_text(encoding="utf-8")
    )
    assert draft_frontmatter["authority_state"] == "proposal"
    assert draft_frontmatter["question_id"] == question_id
    assert provenance_ref in draft_frontmatter["provenance_refs"]
    assert supporting_span in draft_body
    assert "BGE-M3" in draft_body

    replay_tick = run_standing_questions_tick(
        vault_root=vault,
        candidates=[candidate],
        evidence_sources=evidence_sources,
        outbox_path=outbox_path,
        store=store,
        complete=associate_evidence,
        write_guard=healthy_guard(),
        now=tick_time,
    )
    assert replay_tick.matching.attached == 0
    assert replay_tick.matching.duplicate_basis == 1
    assert replay_tick.refresh.drafted == ()
    assert replay_tick.refresh.deferred_pending_review == (question_id,)
    replayed_note, replayed_version = store.read_question_with_version(question_id)
    assert replayed_note["candidate_answer_ref"] == candidate_ref
    assert replayed_note["status"] == "open"
    assert replayed_version == candidate_version

    candidate_view = standing_question_routes._candidate_answer(
        {"candidate_answer_ref": candidate_ref},
        question_id=question_id,
        question_version=candidate_version,
        vault_root=vault,
    )
    assert candidate_view is not None
    assert candidate_view.state == "pending"
    assert candidate_view.acceptance_control is not None
    request = CheckboxProjectionRequest.model_validate(candidate_view.acceptance_control)
    service = CheckboxProjectionService(write_guard=healthy_guard())
    monkeypatch.setattr(
        checkbox_projection_module, "resolve_optional_vault_root", lambda: vault
    )
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox_path)

    accepted = asyncio.run(
        panel_route.panel_checkbox_projection(request, _panel_request(vault))
    )
    answered_note, answered_version = store.read_question_with_version(question_id)
    assert accepted.status == "executed"
    assert accepted.receipt is not None
    accepted_receipt_id = accepted.receipt["authority_receipt_id"]
    assert answered_note["status"] == "answered"
    assert answered_note["candidate_answer_ref"] is None
    assert answered_note["standing_answer_ref"]
    answer_path = vault / answered_note["standing_answer_ref"].removeprefix("vault://")
    accepted_answer_bytes = answer_path.read_bytes()
    answer_frontmatter, answer_body = load_frontmatter(
        accepted_answer_bytes.decode("utf-8")
    )
    assert answer_frontmatter["authority_state"] == "accepted"
    assert answer_frontmatter["question_id"] == question_id
    assert answer_frontmatter["acceptance_receipt_id"] == accepted_receipt_id
    assert provenance_ref in answer_frontmatter["provenance_refs"]
    assert supporting_span in answer_body

    acceptance_replay = asyncio.run(
        panel_route.panel_checkbox_projection(request, _panel_request(vault))
    )
    assert acceptance_replay.status == "executed"
    assert acceptance_replay.receipt is not None
    assert acceptance_replay.receipt["idempotent_replay"] is True
    assert (
        acceptance_replay.receipt["authority_receipt_id"]
        == accepted_receipt_id
    )
    replayed_answered_note, replayed_answered_version = store.read_question_with_version(
        question_id
    )
    assert replayed_answered_version == answered_version
    assert replayed_answered_note["status"] == answered_note["status"] == "answered"
    assert (
        replayed_answered_note["standing_answer_ref"]
        == answered_note["standing_answer_ref"]
    )
    assert replayed_answered_note == answered_note
    assert answer_path.read_bytes() == accepted_answer_bytes
    assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == evidence_hash
