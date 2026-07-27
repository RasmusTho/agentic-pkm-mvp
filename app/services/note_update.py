from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel

from app.agents.panel.integration import commit_panel_update, prepare_panel_update
from app.objects import resolve_canonical_object_id
from app.components.concurrency import OptimisticWriteGuard
from app.domain.state_axes import resolve_promotion_axes
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import (
    default_vault_root_for_path,
    read_note_text_with_version,
    write_note_from_absolute,
)
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


def _write_note_via_knowledge_port(
    note_path: Path,
    content: str,
    *,
    vault_root: Path | None = None,
    expected_version: str,
) -> None:
    resolved = note_path.resolve()
    root = Path(vault_root).resolve() if vault_root is not None else default_vault_root_for_path(resolved)
    write_note_from_absolute(resolved, content, vault_root=root, expected_version=expected_version)


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
        markdown, expected_version = read_note_text_with_version(note_path)
    except Exception:
        return False

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
        try:
            _write_note_via_knowledge_port(
                note_path,
                updated,
                expected_version=expected_version,
            )
        except KnowledgeWriteConflict:
            return False
    return True


def process_note_update(
    note_path: Path,
    ctx: OrchestratorContext | Mapping[str, object] | None,
    *,
    vault_root: Path | None = None,
    expected_path: Path | None = None,
    snapshot_dir: Path | None = None,
) -> NoteUpdateResult:
    resolved_path = Path(note_path).resolve()
    resolved_root = Path(vault_root).resolve() if vault_root is not None else default_vault_root_for_path(resolved_path)
    original_markdown, _ = read_note_text_with_version(resolved_path)
    original_frontmatter, _ = load_frontmatter(original_markdown)
    had_uuid = bool(str(original_frontmatter.get("uuid") or "").strip())
    note_uuid = ensure_note_uuid(resolved_path, vault_root=resolved_root)
    uuid_added = not had_uuid

    raw_markdown, expected_version = read_note_text_with_version(resolved_path)
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

    # ObjectStore-facing panel state is keyed by the canonical store id; a
    # retained legacy note's frontmatter uuid may map to a different
    # objects.id after #3510, and using it verbatim would split the note
    # across two parents (the defect class every sibling call site resolves).
    canonical_note_id = resolve_canonical_object_id(note_uuid)

    prepared_panel = prepare_panel_update(
        note_id=canonical_note_id,
        old_markdown=old_markdown,
        new_markdown=raw_markdown,
        ctx=ctx,
        note_path=resolved_path,
    )

    changed = prepared_panel.panel.updated_markdown != raw_markdown
    if changed:
        current_version = _WRITE_GUARD.read_version(resolved_path)
        if current_version != expected_version:
            return NoteUpdateResult(
                uuid=note_uuid,
                current_path=resolved_path,
                changed=False,
                stale=True,
                uuid_added=uuid_added,
                events_count=len(prepared_panel.events),
                dispatch_count=0,
            )
        try:
            _write_note_via_knowledge_port(
                resolved_path,
                prepared_panel.panel.updated_markdown,
                expected_version=expected_version,
            )
        except KnowledgeWriteConflict:
            return NoteUpdateResult(
                uuid=note_uuid,
                current_path=resolved_path,
                changed=False,
                stale=True,
                uuid_added=uuid_added,
                events_count=len(prepared_panel.events),
                dispatch_count=0,
            )

    panel_result = commit_panel_update(prepared_panel, ctx=ctx)

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
