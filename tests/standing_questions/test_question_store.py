from __future__ import annotations

import json
from datetime import date
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

    for invalid_created_at in ("not-a-timestamp", "", False, 0):
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


@pytest.mark.parametrize(
    "created_at",
    [
        "0000-02-29T00:00:00Z",
        "1937-01-01T12:00:27.87+00:20",
        "1985-04-12T23:20:50.52Z",
        "1990-12-31T15:59:60-08:00",
        "2016-12-31T23:59:60Z",
        "2016-12-31t23:59:60.123z",
        "2017-01-01T00:59:60+01:00",
        "2026-07-11T10:00:00-00:00",
        "2026-07-11T10:00:00+23:59",
        "2026-07-11T10:00:00-23:59",
    ],
)
def test_validate_question_note_accepts_rfc3339_edge_cases(created_at: str) -> None:
    assert validate_question_note(_minimal_valid_note(created_at=created_at))["created_at"] == created_at


@pytest.mark.parametrize(
    "created_at",
    [
        "0000-02-30T00:00:00Z",
        "1900-02-29T00:00:00Z",
        "1990-02-31T15:59:59.123-08:00",
        "2013-350T01:01:01Z",
        "2016-12-31 23:59:60Z",
        "2016-12-31T22:59:60Z",
        "2016-12-31T23:58:60Z",
        "2016-12-31T23:59:60+01:00",
        "2016-12-31T23:59:61Z",
        "2017-01-01T00:59:60Z",
        "2026-07-11T10:00:00.Z",
        "2026-07-11T10:00:00+23:60",
        "2026-07-11T10:00:00+24:00",
        "2026-07-11T24:00:00Z",
        "+11963-06-19T08:30:06.283185Z",
        "1963-06-1৪T00:00:00Z",
    ],
)
def test_validate_question_note_rejects_non_rfc3339_edge_cases(created_at: str) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_question_note(_minimal_valid_note(created_at=created_at))


def test_datetime_schema_type_and_nullable_field_semantics() -> None:
    assert validate_question_note(_minimal_valid_note(last_matched_at=None))["last_matched_at"] is None

    for invalid_created_at in (None, False, 0):
        with pytest.raises(jsonschema.ValidationError) as exc_info:
            validate_question_note(_minimal_valid_note(created_at=invalid_created_at))
        assert exc_info.value.validator == "type"

    evidence = [
        {
            "artifact_ref": "note:abc",
            "source_stream": "vault.activity",
            "matched_at": None,
            "confidence_class": "high",
            "provenance_ref": "receipt:abc",
            "quoted_span": "evidence",
        }
    ]
    with pytest.raises(jsonschema.ValidationError) as exc_info:
        validate_question_note(_minimal_valid_note(evidence=evidence))
    assert exc_info.value.validator == "type"


@pytest.mark.parametrize(
    "field_name",
    ["created_at", "evidence.matched_at", "last_matched_at", "last_refreshed_at"],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        # ":60" outside the UTC leap-second minute is never a leap second.
        "2016-12-31T23:58:60Z",
        # Month-end 23:59:60 UTC, but no leap second was ever announced there.
        "1973-06-30T23:59:60Z",
        "1999-06-30T23:59:60Z",
        "2026-06-30T23:59:60Z",
        "2026-12-31T23:59:60Z",
        # Offset-adjusted to an unannounced month-end UTC leap-second position.
        "1999-06-30T15:59:60-08:00",
        "not-a-timestamp",
    ],
)
def test_all_schema_datetime_fields_use_the_same_rfc3339_boundary(
    field_name: str, invalid_value: str
) -> None:
    valid_note = _minimal_valid_note()
    invalid_note = _minimal_valid_note()
    if field_name == "evidence.matched_at":
        evidence = {
            "artifact_ref": "note:abc",
            "source_stream": "vault.activity",
            "confidence_class": "high",
            "provenance_ref": "receipt:abc",
            "quoted_span": "evidence",
        }
        valid_note["evidence"] = [{**evidence, "matched_at": "2016-12-31T23:59:60Z"}]
        invalid_note["evidence"] = [{**evidence, "matched_at": invalid_value}]
    else:
        valid_note[field_name] = "2016-12-31T23:59:60Z"
        invalid_note[field_name] = invalid_value

    assert validate_question_note(valid_note)
    with pytest.raises(jsonschema.ValidationError):
        validate_question_note(invalid_note)


# --- Announced-leap-second policy (#4204) -------------------------------------------


@pytest.mark.parametrize(
    "created_at",
    [
        # First and last announced leap seconds, at UTC and via a legal offset.
        "1972-06-30T23:59:60Z",
        "1972-12-31T23:59:60Z",
        "2016-12-31T23:59:60Z",
        "2016-12-31t23:59:60.123z",
        "1990-12-31T15:59:60-08:00",
        "2017-01-01T00:59:60+01:00",
        "2015-06-30T23:59:60Z",
        "2012-07-01T07:59:60+08:00",
    ],
)
def test_leap_second_policy_accepts_announced_leap_seconds(created_at: str) -> None:
    assert validate_question_note(_minimal_valid_note(created_at=created_at))["created_at"] == created_at


@pytest.mark.parametrize(
    "created_at",
    [
        # Month-end 23:59 UTC positions where no leap second was ever announced.
        "1971-12-31T23:59:60Z",
        "1973-06-30T23:59:60Z",
        "1999-06-30T23:59:60Z",
        "2016-06-30T23:59:60Z",
        "2020-12-31T23:59:60Z",
        "2026-06-30T23:59:60Z",
        "2026-12-31T23:59:60Z",
        # Offset-adjusted onto an unannounced month-end UTC leap-second position.
        "1999-06-30T15:59:60-08:00",
        "2000-01-01T00:59:60+01:00",
    ],
)
def test_leap_second_policy_rejects_unannounced_leap_seconds(created_at: str) -> None:
    with pytest.raises(jsonschema.ValidationError):
        validate_question_note(_minimal_valid_note(created_at=created_at))


def test_leap_second_policy_table_matches_the_iers_announcements() -> None:
    """The whole contract rests on this table's exactness, so pin every entry.

    A shape-only assertion (count, endpoints, month-end) would still accept a
    transposed year, which would silently admit or reject a real leap second.
    """
    assert sorted(question_store_module.ANNOUNCED_LEAP_SECOND_UTC_DATES) == [
        (1972, 6, 30),
        (1972, 12, 31),
        (1973, 12, 31),
        (1974, 12, 31),
        (1975, 12, 31),
        (1976, 12, 31),
        (1977, 12, 31),
        (1978, 12, 31),
        (1979, 12, 31),
        (1981, 6, 30),
        (1982, 6, 30),
        (1983, 6, 30),
        (1985, 6, 30),
        (1987, 12, 31),
        (1989, 12, 31),
        (1990, 12, 31),
        (1992, 6, 30),
        (1993, 6, 30),
        (1994, 6, 30),
        (1995, 12, 31),
        (1997, 6, 30),
        (1998, 12, 31),
        (2005, 12, 31),
        (2008, 12, 31),
        (2012, 6, 30),
        (2015, 6, 30),
        (2016, 12, 31),
    ]


def test_leap_second_policy_table_carries_a_usable_review_date() -> None:
    """The dated review marker keeps the manual-maintenance obligation checkable."""
    reviewed = question_store_module.ANNOUNCED_LEAP_SECOND_TABLE_REVIEWED
    reviewed_date = date.fromisoformat(reviewed)
    last_year, last_month, last_day = max(
        question_store_module.ANNOUNCED_LEAP_SECOND_UTC_DATES
    )
    # The table cannot claim a review older than the leap second it already lists.
    assert reviewed_date >= date(last_year, last_month, last_day)


def test_datetime_validation_does_not_depend_on_optional_global_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jsonschema.Draft202012Validator,
        "FORMAT_CHECKER",
        jsonschema.FormatChecker(formats=[]),
    )
    registered_check, _raises = question_store_module._QUESTION_NOTE_FORMAT_CHECKER.checkers[
        "date-time"
    ]
    assert registered_check is question_store_module._is_rfc3339_datetime

    with pytest.raises(jsonschema.ValidationError):
        validate_question_note(_minimal_valid_note(created_at="not-a-timestamp"))
    assert validate_question_note(_minimal_valid_note())["created_at"] == "2026-07-11T10:00:00Z"


def test_create_question_defaults_created_at_only_for_explicit_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(question_store_module, "_utc_now", lambda: "2026-07-27T12:34:56Z")
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)

    note, _receipt = store.create_question(
        text="Does explicit None select the producer default?",
        scope="work",
        registered_via="explicit",
        created_at=None,
    )

    assert note["created_at"] == "2026-07-27T12:34:56Z"


def test_store_round_trips_valid_leap_second_without_coercion(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)

    note, _receipt = store.create_question(
        text="Does the durable seam preserve an RFC 3339 leap second?",
        scope="work",
        registered_via="explicit",
        created_at="2016-12-31T23:59:60Z",
    )

    assert note["created_at"] == "2016-12-31T23:59:60Z"
    assert store.read_question(note["question_id"])["created_at"] == "2016-12-31T23:59:60Z"


def test_invalid_system_timestamp_is_rejected_before_guard_or_file_mutation(tmp_path: Path) -> None:
    guard_calls: list[str] = []

    def _healthy_snapshot() -> dict[str, str]:
        guard_calls.append("called")
        return {"state": "healthy"}

    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=_healthy_snapshot))
    note, _receipt = store.create_question(
        text="Will invalid engine metadata mutate this note?",
        scope="work",
        registered_via="explicit",
    )
    path = vault / "questions" / f"{note['question_id']}.md"
    before = path.read_bytes()
    guard_calls.clear()

    with pytest.raises(jsonschema.ValidationError):
        store.update_system_fields(note["question_id"], {"last_matched_at": ""})

    assert guard_calls == []
    assert path.read_bytes() == before


def test_parse_question_note_rejects_invalid_rfc3339_before_projection() -> None:
    content = serialize_question_note(_minimal_valid_note()).replace(
        "2026-07-11T10:00:00Z",
        "2016-12-31T23:58:60Z",
        1,
    )
    with pytest.raises(jsonschema.ValidationError):
        parse_question_note(content)


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
