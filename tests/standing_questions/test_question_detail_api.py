from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import standing_questions as routes
from app.standing_questions.question_store import QuestionStore
from app.write_guard import WriteGuard


def test_evidence_trail_renders_provenance_read_only(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    (vault / "Notes").mkdir(parents=True)
    source = vault / "Notes" / "evidence.md"
    source.write_text("The index remains local.", encoding="utf-8")
    store = QuestionStore(
        vault,
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    question, _ = store.create_question(
        text="Will the index move?",
        scope="work",
        registered_via="explicit",
    )
    evidence = {
        "artifact_ref": "vault://Notes/evidence.md",
        "source_stream": "vault.activity",
        "matched_at": "2026-10-25T10:00:00Z",
        "confidence_class": "high",
        "provenance_ref": "receipt:match-1",
        "quoted_span": "The index remains local.",
        "content_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    question, version = store.read_question_with_version(question["question_id"])
    question, _receipt = store.update_system_fields_if_unchanged(
        question["question_id"],
        question,
        {"evidence": [evidence]},
        expected_version=version,
    )
    row = {
        **question,
        "created_at": datetime.fromisoformat(question["created_at"].replace("Z", "+00:00")),
        "source_path": f"questions/{question['question_id']}.md",
    }
    monkeypatch.setattr(routes, "_vault_and_binding", lambda: (vault, "binding-1"))
    monkeypatch.setattr(routes, "_current_projection_rows", lambda _root, _binding: [row])
    monkeypatch.setattr(routes, "current_scoped_route_read", lambda: None)

    detail = routes.read_standing_question(question["question_id"])

    assert detail.read_only is True
    assert len(detail.evidence) == 1
    rendered = detail.evidence[0]
    assert rendered.artifact_ref == "vault://Notes/evidence.md"
    assert rendered.source_stream == "vault.activity"
    assert rendered.matched_at == evidence["matched_at"]
    assert rendered.confidence_class == "high"
    assert rendered.provenance_ref == "receipt:match-1"
    assert rendered.quoted_span == evidence["quoted_span"]
    assert rendered.content_hash == evidence["content_hash"]
    assert rendered.source_note_path == "Notes/evidence.md"


def test_detail_rejects_projection_that_changed_during_question_read(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(
        vault,
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    question, _ = store.create_question(
        text="Original question",
        scope="work",
        registered_via="explicit",
    )
    row = {
        **question,
        "created_at": datetime.fromisoformat(question["created_at"].replace("Z", "+00:00")),
        "source_path": f"questions/{question['question_id']}.md",
    }
    monkeypatch.setattr(routes, "_vault_and_binding", lambda: (vault, "binding-1"))
    monkeypatch.setattr(routes, "_current_projection_rows", lambda _root, _binding: [row])
    monkeypatch.setattr(routes, "current_scoped_route_read", lambda: None)

    def changed_after_projection(_self, _question_id):
        return {**question, "text": "Question changed during this read"}, "new-version"

    monkeypatch.setattr(QuestionStore, "read_question_with_version", changed_after_projection)

    with pytest.raises(HTTPException) as stale:
        routes.read_standing_question(question["question_id"])

    assert stale.value.status_code == 503
    assert stale.value.detail["error"] == "question_projection_stale"


def test_scoped_detail_does_not_return_nested_child_candidate_body(
    monkeypatch, tmp_path: Path
) -> None:
    from app.standing_questions import answer_refresh

    child_candidate = tmp_path / "vault" / "nested-child" / "candidate.md"
    child_candidate.parent.mkdir(parents=True)
    child_candidate.write_text("private child-vault answer", encoding="utf-8")
    monkeypatch.setattr(answer_refresh, "_resolve_vault_ref", lambda _root, _ref: child_candidate)
    monkeypatch.setattr(routes, "scoped_note_path_owned_by_binding", lambda _scope, _path: False)

    candidate = routes._candidate_answer(
        {"candidate_answer_ref": "vault://nested-child/candidate.md"},
        question_id="sq-00000000-0000-0000-0000-000000000001",
        question_version="version-1",
        vault_root=tmp_path / "vault",
        scoped=SimpleNamespace(),
    )

    assert candidate is not None
    assert candidate.state == "unreadable"
    assert candidate.body is None
