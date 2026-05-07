from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from app.agents.panel.integration import handle_panel_update
from app.agents.panel.writeback import upsert_executed_ids
from app.components.concurrency import OptimisticWriteGuard
from app.domain.state_axes import resolve_promotion_axes
from app.knowledge.write_ops import default_vault_root_for_path, write_note_from_absolute
from app.orchestrator.handler import OrchestratorContext
from app.services.note_uuid import ensure_note_uuid
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

DEFAULT_SNAPSHOT_DIR = Path("tmp/note_update_snapshots")
_WRITE_GUARD = OptimisticWriteGuard()


class NoteUpdateResult(BaseModel):
    uuid: str
    current_path: Path
    changed: bool
    stale: bool = False
    uuid_added: bool = False
    events_count: int = 0
    dispatch_count: int = 0


def _write_note_via_knowledge_port(note_path: Path, content: str) -> None:
    resolved = note_path.resolve()
    root = default_vault_root_for_path(resolved)
    write_note_from_absolute(resolved, content, vault_root=root)


def apply_promotion_frontmatter(
    note_path: Path,
    note_uuid: str,
    new_review_state: str,
    optional_title: str | None = None,
    *,
    maturity: str | None = None,
) -> bool:
    # Current callers still pass `new_review_state`, including legacy `evergreen`.
    # During the first state-axis separation wave we normalize that input here so
    # standing is written to `maturity` while `review_state` keeps review posture.
    try:
        markdown = note_path.read_text(encoding="utf-8")
    except Exception:
        return False

    expected_version = _WRITE_GUARD.compute_version(markdown.encode("utf-8"))
    frontmatter, body = load_frontmatter(markdown)
    fm = dict(frontmatter or {})

    existing_uuid = fm.get("uuid")
    if isinstance(existing_uuid, list) and len(existing_uuid) == 1:
        inner = existing_uuid[0]
        if isinstance(inner, list) and len(inner) == 1:
            existing_uuid = str(inner[0])
        else:
            existing_uuid = str(inner)
    if isinstance(existing_uuid, str):
        cleaned = existing_uuid.strip()
        if cleaned.startswith("[[") and cleaned.endswith("]]"):
            cleaned = cleaned[2:-2].strip()
        if cleaned:
            fm["uuid"] = cleaned
    if not fm.get("uuid"):
        fm["uuid"] = note_uuid

    if optional_title and not fm.get("title"):
        fm["title"] = optional_title

    axes = resolve_promotion_axes(maturity=maturity, review_state=new_review_state)
    if axes.maturity:
        fm["maturity"] = axes.maturity
    fm["review_state"] = axes.review_state

    updated = dump_frontmatter(fm, body)
    if updated != markdown:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("promotion frontmatter")
        current_version = _WRITE_GUARD.read_version(note_path)
        if current_version != expected_version:
            return False
        _write_note_via_knowledge_port(note_path, updated)
    return True


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
    expected_version = _WRITE_GUARD.compute_version(raw_markdown.encode("utf-8"))
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

    DEFAULT_WRITE_GUARD.assert_writes_allowed("panel runtimes")

    panel_result = handle_panel_update(
        note_id=note_uuid,
        old_markdown=old_markdown,
        new_markdown=raw_markdown,
        ctx=ctx,
        note_path=resolved_path,
    )

    changed = panel_result.panel.updated_markdown != raw_markdown
    if changed:
        current_version = _WRITE_GUARD.read_version(resolved_path)
        if current_version != expected_version:
            return NoteUpdateResult(
                uuid=note_uuid,
                current_path=resolved_path,
                changed=False,
                stale=True,
                uuid_added=uuid_added,
                events_count=len(panel_result.events),
                dispatch_count=panel_result.dispatch_count,
            )
        _write_note_via_knowledge_port(resolved_path, panel_result.panel.updated_markdown)
        upsert_executed_ids(note_uuid, panel_result.panel.executed_action_ids)

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


def _snapshot_path(
    snapshot_dir: Path | None, note_uuid: str, *, ensure_parent: bool
) -> Path | None:
    base = snapshot_dir or DEFAULT_SNAPSHOT_DIR
    if ensure_parent:
        base.mkdir(parents=True, exist_ok=True)
    elif not base.exists():
        return base / f"{note_uuid}.md"
    return base / f"{note_uuid}.md"


__all__ = [
    "NoteUpdateResult",
    "process_note_update",
    "DEFAULT_SNAPSHOT_DIR",
    "apply_promotion_frontmatter",
]
