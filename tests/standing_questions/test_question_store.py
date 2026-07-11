from __future__ import annotations

from pathlib import Path

import pytest

from app.standing_questions.question_store import (
    HumanOwnedFieldMutationError,
    QuestionStore,
    WRITE_ACTION,
)
from app.write_guard import WriteGuard, WritesBlockedError


def _store(vault: Path) -> QuestionStore:
    return QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))


def test_write_asserts_guard_at_seam(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(
        vault,
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "safe_mode", "reason": "test"}),
    )

    with pytest.raises(WritesBlockedError, match=WRITE_ACTION):
        store.create_question(text="Will this write?", scope="work", registered_via="explicit")

    assert not (vault / "questions").exists()


def test_engine_cannot_overwrite_human_owned_fields(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text="Original question", scope="work", registered_via="explicit")
    path = vault / "questions" / f"{note['question_id']}.md"
    before = path.read_bytes()

    with pytest.raises(HumanOwnedFieldMutationError):
        store.update_system_fields(note["question_id"], {"text": "Engine rewrite"})
    with pytest.raises(HumanOwnedFieldMutationError):
        store.update_system_fields(note["question_id"], {"status": "answered"})

    assert path.read_bytes() == before
    assert "Rejected Standing Questions engine write" in caplog.text


def test_engine_may_append_system_owned_fields_only(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text="Original question", scope="work", registered_via="explicit")

    updated, receipt = store.update_system_fields(
        note["question_id"],
        {
            "evidence": [
                {
                    "artifact_ref": "note:abc",
                    "source_stream": "vault.activity",
                    "matched_at": "2026-07-11T11:00:00Z",
                    "confidence_class": "high",
                    "provenance_ref": "receipt:abc",
                    "quoted_span": "evidence",
                }
            ],
            "candidate_answer_ref": "note:candidate",
            "last_matched_at": "2026-07-11T11:00:00Z",
        },
    )

    assert receipt.operation == WRITE_ACTION
    assert updated["text"] == "Original question"
    assert updated["status"] == "open"
    assert updated["created_at"] == note["created_at"]
    assert updated["evidence"][0]["artifact_ref"] == "note:abc"
