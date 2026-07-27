"""#3510 identity threading for the note_update/note_scan panel seam.

The frontmatter uuid names the vault file; ObjectStore-facing panel state is
keyed by the canonical store id. For a retained legacy note the two differ, so
the seam must resolve the canonical id exactly like its sibling call sites
(watcher registry, vault watcher, outbox worker, checkbox projection).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services import note_update


def test_panel_seam_receives_canonical_identity(tmp_path: Path, monkeypatch) -> None:
    vault_uuid = str(uuid4())
    canonical_id = str(uuid4())
    note = tmp_path / "retained.md"
    note.write_text(
        f"---\nuuid: {vault_uuid}\n---\n\nbody\n",
        encoding="utf-8",
    )

    seen: dict[str, str] = {}

    def fake_resolve(value: str) -> str:
        seen["resolved_from"] = value
        return canonical_id

    def fake_prepare_panel_update(*, note_id, old_markdown, new_markdown, ctx, note_path):
        seen["panel_note_id"] = note_id
        panel = SimpleNamespace(
            updated_markdown=new_markdown,
            executed_action_ids=[],
        )
        return SimpleNamespace(
            note_id=note_id,
            panel=panel,
            events=[],
            dispatch_count=0,
        )

    monkeypatch.setattr(note_update, "resolve_canonical_object_id", fake_resolve)
    monkeypatch.setattr(
        note_update, "prepare_panel_update", fake_prepare_panel_update
    )
    monkeypatch.setattr(
        note_update,
        "commit_panel_update",
        lambda prepared, *, ctx: prepared,
    )
    monkeypatch.setattr(
        note_update.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )

    result = note_update.process_note_update(str(note), None, vault_root=tmp_path)

    assert seen["resolved_from"] == vault_uuid
    assert seen["panel_note_id"] == canonical_id
    assert result.uuid == vault_uuid, "the vault-facing result keeps the frontmatter uuid"
