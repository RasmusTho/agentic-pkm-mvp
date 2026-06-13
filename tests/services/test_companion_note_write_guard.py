from __future__ import annotations

from pathlib import Path

import pytest

from app.services.companion_note import CompanionNote, companion_path, read_companion, write_companion
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError


def _make_companion() -> CompanionNote:
    return CompanionNote(
        uuid="guarded-companion-uuid",
        source_ref="Notes/Guarded.md",
        title="Guarded",
        content_hash="abc123",
        ingest_state="tracked",
        last_ingested="2026-06-13T00:00:00+00:00",
        created_by_instance="test-instance",
    )


def test_write_companion_blocked_when_writes_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    companion = _make_companion()
    target = tmp_path / companion_path(companion.uuid, tmp_path)

    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "maintenance"},
    )

    with pytest.raises(WritesBlockedError) as exc:
        write_companion(tmp_path, companion)

    assert exc.value.action == "companion_note.write"
    assert exc.value.state == "safe_mode"
    assert exc.value.reason == "maintenance"
    assert not target.exists()
    assert not target.parent.exists()


@pytest.mark.parametrize("state", ["running", "degraded"])
def test_write_companion_allows_in_non_blocked_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: str
) -> None:
    companion = _make_companion()

    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": state, "reason": "test"},
    )

    write_companion(tmp_path, companion)

    result = read_companion(tmp_path, companion.uuid)
    assert result is not None
    assert result.uuid == companion.uuid
    assert result.source_ref == companion.source_ref
    assert result.title == companion.title
    assert result.content_hash == companion.content_hash
    assert result.ingest_state == companion.ingest_state
    assert result.last_ingested == companion.last_ingested
    assert result.created_by_instance == companion.created_by_instance
