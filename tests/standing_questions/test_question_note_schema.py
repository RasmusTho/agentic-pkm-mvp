from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


def _valid_note() -> dict[str, object]:
    return {
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


def test_question_note_schema_validates_shape() -> None:
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/question-note.schema.json").read_text()
    )
    jsonschema.validate(_valid_note(), schema)

    invalid_status = _valid_note() | {"status": "proposed"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_status, schema)

    invalid_id = _valid_note() | {"question_id": "question-123"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_id, schema)
