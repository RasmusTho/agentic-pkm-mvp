from __future__ import annotations

from pathlib import Path
from typing import Mapping

from pydantic import BaseModel

from app.agents.panel.integration import handle_panel_update
from app.orchestrator.handler import OrchestratorContext
from app.services.note_uuid import ensure_note_uuid
from scripts.yaml_roundtrip import load_frontmatter

DEFAULT_SNAPSHOT_DIR = Path("tmp/note_update_snapshots")


class NoteUpdateResult(BaseModel):
    uuid: str
    current_path: Path
    changed: bool
    stale: bool = False
    uuid_added: bool = False
    events_count: int = 0
    dispatch_count: int = 0


def process_note_update(
    note_path: Path,
    ctx: OrchestratorContext | Mapping[str, object] | None,
    *,
    expected_path: Path | None = None,
    snapshot_dir: Path | None = None,
) -> NoteUpdateResult:
    resolved_path = Path(note_path).resolve()
    original_markdown = resolved_path.read_text(encoding="utf-8")
    original_frontmatter, _ = load_frontmatter(original_markdown)
    had_uuid = bool(str(original_frontmatter.get("uuid") or "").strip())
    note_uuid = ensure_note_uuid(resolved_path)
    uuid_added = not had_uuid

    raw_markdown = resolved_path.read_text(encoding="utf-8")
    if not note_uuid:
        raise ValueError(f"Note {resolved_path} is missing 'uuid' in frontmatter")

    if expected_path is not None and Path(expected_path).resolve() != resolved_path:
        return NoteUpdateResult(
            uuid=note_uuid,
            current_path=resolved_path,
            changed=False,
            stale=True,
        )

    snapshot_path = _snapshot_path(snapshot_dir, note_uuid, ensure_parent=False)
    if snapshot_path and snapshot_path.exists():
        old_markdown = snapshot_path.read_text(encoding="utf-8")
    else:
        old_markdown = raw_markdown

    panel_result = handle_panel_update(
        note_id=note_uuid,
        old_markdown=old_markdown,
        new_markdown=raw_markdown,
        ctx=ctx,
    )

    changed = panel_result.panel.updated_markdown != raw_markdown
    if changed:
        resolved_path.write_text(panel_result.panel.updated_markdown, encoding="utf-8")

    snapshot_path = _snapshot_path(snapshot_dir, note_uuid, ensure_parent=True)
    if snapshot_path is not None:
        snapshot_path.write_text(panel_result.panel.updated_markdown, encoding="utf-8")

    return NoteUpdateResult(
        uuid=note_uuid,
        current_path=resolved_path,
        changed=changed,
        stale=False,
        uuid_added=uuid_added,
        events_count=len(panel_result.events),
        dispatch_count=panel_result.dispatch_count,
    )


def _snapshot_path(snapshot_dir: Path | None, note_uuid: str, *, ensure_parent: bool) -> Path | None:
    base = snapshot_dir or DEFAULT_SNAPSHOT_DIR
    if ensure_parent:
        base.mkdir(parents=True, exist_ok=True)
    elif not base.exists():
        return base / f"{note_uuid}.md"
    return base / f"{note_uuid}.md"


__all__ = ["NoteUpdateResult", "process_note_update", "DEFAULT_SNAPSHOT_DIR"]
