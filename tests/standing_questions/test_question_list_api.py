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
