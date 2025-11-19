from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional

import yaml
from pydantic import BaseModel, Field

from app.agents.panel.integration import PanelPipelineResult, handle_panel_update
from app.orchestrator.handler import OrchestratorContext

DEFAULT_SNAPSHOT_DIR = Path("tmp/note_update_snapshots")


class NoteUpdateResult(BaseModel):
    uuid: str
    current_path: Path
    changed: bool
    stale: bool = False
    events_count: int = 0
    dispatch_count: int = 0
    panel_result: PanelPipelineResult | None = Field(default=None, exclude=True)


def process_note_update(
    note_path: Path,
    ctx: OrchestratorContext | Mapping[str, object] | None,
    *,
    expected_path: Path | None = None,
    snapshot_dir: Path | None = None,
) -> NoteUpdateResult:
    resolved_path = Path(note_path).resolve()
    raw_markdown = resolved_path.read_text(encoding="utf-8")
    frontmatter = _extract_frontmatter(raw_markdown)
    note_uuid = str(frontmatter.get("uuid") or "").strip()
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
        events_count=len(panel_result.events),
        dispatch_count=panel_result.dispatch_count,
        panel_result=panel_result,
    )


def _extract_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end_idx: Optional[int] = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}
    fm_text = "\n".join(lines[1:end_idx])
    try:
        data = yaml.safe_load(fm_text) or {}
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _snapshot_path(snapshot_dir: Path | None, note_uuid: str, *, ensure_parent: bool) -> Path | None:
    base = snapshot_dir or DEFAULT_SNAPSHOT_DIR
    if ensure_parent:
        base.mkdir(parents=True, exist_ok=True)
    elif not base.exists():
        return base / f"{note_uuid}.md"
    return base / f"{note_uuid}.md"


__all__ = ["NoteUpdateResult", "process_note_update", "DEFAULT_SNAPSHOT_DIR"]
