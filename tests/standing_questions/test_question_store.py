from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from app.standing_questions import question_store as question_store_module
from app.standing_questions.question_store import (
    HumanOwnedFieldMutationError,
    QuestionStore,
    WRITE_ACTION,
    parse_question_note,
    serialize_question_note,
    validate_question_note,
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


def _minimal_valid_note(**overrides: object) -> dict[str, object]:
    note: dict[str, object] = {
        "question_id": "sq-123e4567-e89b-12d3-a456-426614174000",
        "scope": "work",
        "text": "Should the retrieval index move to BGE-M3?",
        "status": "open",
        "created_at": "2026-07-11T10:00:00Z",
        "registered_via": "explicit",
        "standing_answer_ref": None,
        "candidate_answer_ref": None,
        "evidence": [],
        "last_matched_at": None,
        "last_refreshed_at": None,
    }
    note.update(overrides)
    return note


def test_validate_question_note_rejects_bad_created_at_format(tmp_path: Path) -> None:
    """Review finding #3: format_checker must actually enforce "format": "date-time" at
    write time, not just parse. A bad timestamp string must never reach the projection
    INSERT (TIMESTAMPTZ) undetected."""
    guard_calls: list[str] = []

    def _healthy_snapshot() -> dict[str, str]:
        guard_calls.append("called")
        return {"state": "healthy"}

    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=_healthy_snapshot))

    for invalid_created_at in ("not-a-timestamp", ""):
        with pytest.raises(jsonschema.ValidationError):
            store.create_question(
                text="Will this invalid timestamp write?",
                scope="work",
                registered_via="explicit",
                created_at=invalid_created_at,
            )

    assert guard_calls == []
    assert not (vault / "questions").exists()


def test_validate_question_note_accepts_well_formed_created_at() -> None:
    note = _minimal_valid_note()
    assert validate_question_note(note)["created_at"] == "2026-07-11T10:00:00Z"
    lowercase = _minimal_valid_note(created_at="2026-07-11t10:00:00z")
    assert validate_question_note(lowercase)["created_at"] == "2026-07-11t10:00:00z"


def test_datetime_validation_does_not_depend_on_optional_global_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jsonschema.Draft202012Validator,
        "FORMAT_CHECKER",
        jsonschema.FormatChecker(formats=[]),
    )

    with pytest.raises(jsonschema.ValidationError):
        validate_question_note(_minimal_valid_note(created_at="not-a-timestamp"))
    assert validate_question_note(_minimal_valid_note())["created_at"] == "2026-07-11T10:00:00Z"


def test_serialize_parse_round_trips_non_ascii_text() -> None:
    """Review finding #5: switching to the shared scripts.yaml_roundtrip helper must
    keep parse(serialize(note)) == note, including for non-ASCII (Swedish) text."""
    note = _minimal_valid_note(text="Är detta en fråga med åäö?")
    content = serialize_question_note(note)
    assert parse_question_note(content) == note


def test_parse_question_note_rejects_malformed_frontmatter() -> None:
    with pytest.raises(jsonschema.ValidationError):
        parse_question_note("not a note at all, no frontmatter here")


def test_field_ownership_frozensets_cover_exactly_the_schema_properties() -> None:
    """Non-blocking finding: the three field-ownership frozensets must union to exactly
    the schema's property set, or a newly-added schema field silently falls outside every
    ownership bucket (neither human-writable, engine-writable, nor immutable)."""
    schema = json.loads(question_store_module._SCHEMA_PATH.read_text(encoding="utf-8"))
    owned = (
        question_store_module._HUMAN_OWNED_FIELDS
        | question_store_module._SYSTEM_OWNED_FIELDS
        | question_store_module._IMMUTABLE_FIELDS
    )
    assert owned == set(schema["properties"])
