from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.routes import standing_questions as routes


def test_list_shows_open_excludes_resolved_by_default(monkeypatch, tmp_path: Path) -> None:
    rows = [
        {
            "question_id": f"sq-00000000-0000-0000-0000-00000000000{index}",
            "scope": "work",
            "text": f"Question {index}",
            "status": status,
            "created_at": datetime(2026, 10, index + 1, tzinfo=UTC),
            "registered_via": "explicit",
            "standing_answer_ref": None,
            "candidate_answer_ref": None,
            "evidence": [],
        }
        for index, status in enumerate(("open", "answered", "closed"), start=1)
    ]
    monkeypatch.setattr(routes, "_vault_and_binding", lambda: (tmp_path, "binding-1"))
    monkeypatch.setattr(routes, "_current_projection_rows", lambda _root, _binding: rows)

    default = routes.list_standing_questions(include_resolved=False)
    resolved = routes.list_standing_questions(include_resolved=True)

    assert [question.status for question in default.questions] == ["open"]
    assert default.include_resolved is False
    assert [question.status for question in resolved.questions] == [
        "open",
        "answered",
        "closed",
    ]
    assert resolved.include_resolved is True
    assert default.read_only is True


@pytest.mark.parametrize(
    "created_at",
    [
        "0001-02-29 00:00:00.000000 BC",
        "10000-01-01 23:58:59+00",
    ],
    ids=("year-zero", "utc-overflow"),
)
def test_list_preserves_postgres_timestamps_outside_python_range(
    monkeypatch, tmp_path: Path, created_at: str
) -> None:
    row = {
        "question_id": "sq-00000000-0000-0000-0000-000000000001",
        "scope": "work",
        "text": "Can the question keep its full timestamp?",
        "status": "open",
        "created_at": created_at,
        "registered_via": "explicit",
        "standing_answer_ref": None,
        "candidate_answer_ref": None,
        "evidence": [],
    }
    monkeypatch.setattr(routes, "_vault_and_binding", lambda: (tmp_path, "binding-1"))
    monkeypatch.setattr(routes, "_current_projection_rows", lambda _root, _binding: [row])

    result = routes.list_standing_questions(include_resolved=False)

    assert len(result.questions) == 1
    assert result.questions[0].created_at == created_at


def test_projection_read_is_read_only_and_matches_canonical_notes(
    monkeypatch, tmp_path: Path
) -> None:
    note = {
        "question_id": "sq-00000000-0000-0000-0000-000000000001",
        "scope": "work",
        "text": "Will the projection stay current?",
        "status": "open",
        "created_at": "2026-10-25T10:15:00Z",
        "registered_via": "explicit",
        "standing_answer_ref": None,
        "candidate_answer_ref": None,
        "evidence": [],
    }
    row = {
        **note,
        "created_at": datetime(2026, 10, 25, 10, 15, tzinfo=UTC),
        "source_path": "questions/sq-1.md",
    }
    monkeypatch.setattr(routes, "iter_question_notes", lambda _root: [("questions/sq-1.md", note)])
    monkeypatch.setattr(routes, "_read_projection_rows", lambda _binding: [row])

    def forbidden_rebuild(*_args, **_kwargs):
        raise AssertionError("GET attempted to write the projection")

    monkeypatch.setattr(routes, "rebuild_standing_questions_projection", forbidden_rebuild)

    assert routes._current_projection_rows(tmp_path, "binding-1") == [row]


def test_projection_read_fails_closed_when_canonical_note_differs(
    monkeypatch, tmp_path: Path
) -> None:
    note = {
        "question_id": "sq-00000000-0000-0000-0000-000000000001",
        "scope": "work",
        "text": "Canonical question",
        "status": "open",
        "created_at": "2026-10-25T10:15:00Z",
        "registered_via": "explicit",
        "standing_answer_ref": None,
        "candidate_answer_ref": None,
        "evidence": [],
    }
    stale_row = {
        **note,
        "text": "Stale projected question",
        "created_at": datetime(2026, 10, 25, 10, 15, tzinfo=UTC),
        "source_path": "questions/sq-1.md",
    }
    monkeypatch.setattr(routes, "iter_question_notes", lambda _root: [("questions/sq-1.md", note)])
    monkeypatch.setattr(routes, "_read_projection_rows", lambda _binding: [stale_row])

    with pytest.raises(HTTPException) as stale:
        routes._current_projection_rows(tmp_path, "binding-1")

    assert stale.value.status_code == 503
    assert stale.value.detail["error"] == "question_projection_stale"


def test_projection_freshness_normalizes_extreme_timestamp_fraction_text() -> None:
    note = {
        "question_id": "sq-00000000-0000-0000-0000-000000000001",
        "scope": "work",
        "text": "Does freshness compare legal extreme timestamps?",
        "status": "open",
        "created_at": "0000-02-29T00:00:00.120000Z",
        "registered_via": "explicit",
        "standing_answer_ref": None,
        "candidate_answer_ref": None,
        "evidence": [],
        "last_matched_at": "9999-12-31T23:59:59.120000-23:59",
        "last_refreshed_at": None,
    }
    row = {
        **note,
        # PostgreSQL emits astronomical year and BC notation, and removes
        # insignificant fractional zeros from its timestamp text output.
        "created_at": "0001-02-29 00:00:00.12 BC",
        "last_matched_at": "10000-01-01 23:58:59.12",
        "source_path": "questions/sq-00000000-0000-0000-0000-000000000001.md",
    }

    assert routes._projection_row_matches_note(
        row,
        note,
        source_path="questions/sq-00000000-0000-0000-0000-000000000001.md",
    )
