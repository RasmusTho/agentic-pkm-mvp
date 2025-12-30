from __future__ import annotations

from pathlib import Path

import pytest

from app.orchestrator.handler import OrchestratorContext
from app.services.note_update import process_note_update
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError


def _reviewed_note() -> str:
    return (
        "---\n"
        "uuid: reviewed-note-1\n"
        "review_state: reviewed\n"
        "---\n\n"
        "%% AI:Start %%\n"
        "## AI-åtgärder\n"
        "- [x] Apply change\n"
        "%% AI:End %%\n"
    )


def test_reviewed_note_blocks_mutation_without_apply(monkeypatch, tmp_path: Path) -> None:
    note_path = tmp_path / "reviewed.md"
    note_path.write_text(_reviewed_note(), encoding="utf-8")

    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "no-apply"},
    )

    ctx = OrchestratorContext(settings={"panel_events_enable": False})

    with pytest.raises(WritesBlockedError):
        process_note_update(note_path, ctx)

    assert "Apply change" in note_path.read_text(encoding="utf-8")
