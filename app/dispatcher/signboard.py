"""Signboard Markdown projection for dispatcher tasks.

The dispatcher remains the operational source of truth. This module writes a
one-way Markdown projection that lightweight kanban tools can render from disk.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore
from app.vault.manager import get_vault_manager


# The Signboard export nests under the human's actively-selected vault so no
# CLI/automation caller ever has to type a manual path (dyslexia-friendly,
# no-manual-path-typing posture). This reuses the shipped Option 2
# active-vault-selection mechanism (``VaultManager`` / ``AppLocalSettingsStore``)
# rather than inventing a parallel "BuilderOps vault root" concept.
DEFAULT_SIGNBOARD_SUBPATH = Path("BuilderOpsVault") / "agent-delivery"

_NOTES_HEADING = "## Notes"
_RECEIPTS_HEADING = "## Receipts"
_GENERATED_FILENAME_RE = re.compile(r".+--.+\.md$")


class NoActiveVaultError(RuntimeError):
    """Raised when a default Signboard export path is requested but no vault
    is currently selected via the active-vault-selection mechanism."""


def default_signboard_root() -> Path:
    """Resolve the default Signboard export root from the active vault.

    Reuses the existing shipped active-vault-selection mechanism
    (``app.vault.manager.get_vault_manager``) so callers never need to type a
    manual vault path. Raises :class:`NoActiveVaultError` when no vault is
    currently selected; callers should fall back to an explicit path or
    instruct the human to select a vault first.
    """

    manager = get_vault_manager()
    context = manager.context
    if context.status == "none":
        context = manager.load_last_active()
    if context.active_vault_path and context.status in {"selected", "uninitialized"}:
        return Path(context.active_vault_path).expanduser().resolve() / DEFAULT_SIGNBOARD_SUBPATH
    raise NoActiveVaultError(
        "no active vault is selected; pass an explicit path or select a vault first"
    )


STATUS_COLUMNS: dict[str, str] = {
    "backlog": "Backlog",
    "ready": "Ready",
    "claimed": "In Progress",
    "in_progress": "In Progress",
    "review": "Review",
    "blocked": "Blocked",
    "completed": "Done",
    "done": "Done",
}

VALID_STATUSES = frozenset(STATUS_COLUMNS.keys()) - {"done"}


def canonical_status(status: str) -> str:
    normalized = status.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized == "done":
        return "completed"
    if normalized not in VALID_STATUSES:
        allowed = ", ".join(sorted(VALID_STATUSES | {"done"}))
        raise ValueError(f"Unknown dispatcher status {status!r}; expected one of: {allowed}")
    return normalized


def column_for_status(status: str) -> str:
    normalized = canonical_status(status)
    return STATUS_COLUMNS.get(normalized, "Backlog")


def export_signboard(store: SqliteStore, board_root: Path) -> dict[str, Any]:
    """Write dispatcher tasks as Markdown files grouped by kanban column.

    The exporter only removes prior generated files for task IDs that still
    exist in dispatcher. It leaves unrelated human notes alone.
    """

    root = Path(board_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    for column in sorted(set(STATUS_COLUMNS.values())):
        (root / column).mkdir(parents=True, exist_ok=True)

    # Synchronization metadata is stored alongside tasks for dispatcher
    # compatibility, but it is not a user-facing Signboard card.
    tasks = [task for task in store.list_tasks() if task.status != "_meta"]
    written: list[str] = []
    for task in tasks:
        filename = _task_filename(task)
        target_column = column_for_status(task.status)
        target = root / target_column / filename

        # Preserve any human-authored content in the "## Notes" section of a
        # previously generated card for this task, wherever it currently
        # lives (the card may have moved columns/filenames since the last
        # export because status or title changed). The target's own existing
        # card, if any, is the freshest source; stale cards elsewhere are a
        # fallback so a rename/status-move doesn't drop notes.
        preserved_notes: str | None = None
        target_text = _read_card_text(target)
        if target_text is not None and _is_generated_card_text(target_text):
            preserved_notes = _extract_notes_section(target_text)

        for column in sorted(set(STATUS_COLUMNS.values())):
            for candidate in (root / column).glob(f"{task.task_id}--*.md"):
                if candidate == target:
                    continue
                candidate_text = _read_card_text(candidate)
                if candidate_text is not None and _is_generated_card_text(candidate_text):
                    if preserved_notes is None:
                        preserved_notes = _extract_notes_section(candidate_text)
                    candidate.unlink()

        # No further cleanup pass here: the glob above already unlinks every
        # stale *generated* card for this task_id (including one at this
        # exact filename in another column). A second pass keyed on filename
        # alone — without the _is_generated_card_text check — would delete a
        # non-generated file that happens to share the filename by
        # coincidence; that used to be a real bug, not defense in depth.

        target.write_text(_render_task(task, notes=preserved_notes), encoding="utf-8")
        written.append(str(target))

    return {
        "root": str(root),
        "count": len(tasks),
        "columns": sorted(set(STATUS_COLUMNS.values())),
        "written": written,
    }


def validate_signboard(store: SqliteStore, board_root: Path) -> dict[str, Any]:
    """Return read-only findings for generated Signboard cards.

    Signboard is a derived projection. This intentionally never repairs cards
    or updates the dispatcher store; ``export-signboard`` remains the repair
    operation after a failing validation run.
    """
    root = Path(board_root).expanduser()
    tasks = {
        task.task_id: task
        for task in store.list_tasks()
        if task.status != "_meta"
    }
    findings: list[dict[str, str]] = []
    cards_by_task: dict[str, list[str]] = {}

    for path in sorted(root.rglob("*.md")) if root.is_dir() else []:
        relative_path = str(path.relative_to(root))
        text = _read_card_text(path)
        if text is None:
            if _GENERATED_FILENAME_RE.fullmatch(path.name):
                findings.append({
                    "kind": "unreadable_generated_card_candidate",
                    "path": relative_path,
                    "detail": "generated filename candidate could not be read",
                })
            continue
        if not _is_generated_card_text(text):
            continue

        frontmatter = _parse_generated_frontmatter(text)
        if frontmatter is None:
            findings.append({
                "kind": "malformed_generated_card",
                "path": relative_path,
                "detail": "generated card frontmatter is missing or invalid",
            })
            continue

        task_id = frontmatter["id"]
        status = frontmatter["status"]
        expected_column = column_for_status(status)
        actual_column = path.parent.name
        cards_by_task.setdefault(task_id, []).append(relative_path)
        if actual_column != expected_column or frontmatter["column"] != expected_column:
            findings.append({
                "kind": "column_status_mismatch",
                "path": relative_path,
                "detail": (
                    f"status {status!r} belongs in {expected_column!r}; "
                    f"card column is {actual_column!r} and frontmatter column is "
                    f"{frontmatter['column']!r}"
                ),
            })

        task = tasks.get(task_id)
        if task is None:
            findings.append({
                "kind": "stale_card",
                "path": relative_path,
                "detail": f"task {task_id!r} is absent from the dispatcher store",
            })
        elif actual_column != column_for_status(task.status):
            findings.append({
                "kind": "stale_card",
                "path": relative_path,
                "detail": (
                    f"task {task_id!r} now belongs in "
                    f"{column_for_status(task.status)!r}"
                ),
            })

    for task_id, paths in cards_by_task.items():
        if len(paths) > 1:
            findings.append({
                "kind": "duplicate_card",
                "path": ", ".join(paths),
                "detail": f"task {task_id!r} has {len(paths)} generated cards",
            })

    return {"root": str(root), "count": len(tasks), "findings": findings}


def _parse_generated_frontmatter(text: str) -> dict[str, str] | None:
    """Parse the minimal generated-card schema without accepting loose YAML."""
    if not text.startswith("---\n"):
        return None
    try:
        _, raw_frontmatter, _ = text.split("---\n", 2)
        data = yaml.safe_load(raw_frontmatter)
    except (ValueError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None

    task_id = data.get("id")
    issue_number = data.get("issue_number")
    status = data.get("status")
    column = data.get("column")
    if not isinstance(task_id, str) or not task_id.strip():
        return None
    if not isinstance(issue_number, int) or isinstance(issue_number, bool):
        return None
    if not isinstance(status, str) or not status.strip():
        return None
    if not isinstance(column, str) or not column.strip():
        return None
    try:
        canonical = canonical_status(status)
    except ValueError:
        return None
    return {"id": task_id, "status": canonical, "column": column}


def _task_filename(task: TaskRecord) -> str:
    title = re.sub(r"[^A-Za-z0-9._-]+", "-", task.title.strip()).strip("-")
    title = title[:72].strip("-") or "task"
    return f"{task.task_id}--{title}.md"


def _read_card_text(path: Path) -> str | None:
    """Read a card's text, tolerating a missing/unreadable file (returns None)."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _is_generated_card_text(text: str) -> bool:
    return "generated_by: dispatcher.signboard" in text


def _is_generated_card(path: Path) -> bool:
    text = _read_card_text(path)
    return text is not None and _is_generated_card_text(text)


def _extract_notes_section(text: str) -> str | None:
    """Return the human-authored body of a card's "## Notes" section, if any.

    The section runs from just below the "## Notes" heading up to (but not
    including) the *last* "## Receipts" heading in the file — the only other
    heading ``_render_task`` ever generates, and always the final line of
    generated structure (nothing follows it but a trailing blank line). Using
    the last occurrence rather than the first means a human quoting the
    literal text "## Receipts" earlier in their own notes does not get
    mistaken for the real boundary; only the generator's actual trailing
    heading does. Returns ``None`` when there is no "## Notes" heading or the
    section is blank, so callers can fall back to the default stub.
    """

    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == _NOTES_HEADING)
    except StopIteration:
        return None

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == _RECEIPTS_HEADING:
            end = i

    section_lines = lines[start + 1 : end]
    while section_lines and section_lines[0] == "":
        section_lines.pop(0)
    while section_lines and section_lines[-1] == "":
        section_lines.pop()

    if not section_lines:
        return None
    return "\n".join(section_lines)


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(_yaml_scalar(v) for v in values) + "]"


def _render_task(task: TaskRecord, *, notes: str | None = None) -> str:
    source_refs = list(task.source_anchor_refs or [])
    github_url = ""
    labels: list[str] = []
    if task.sync_state:
        github_url = str(task.sync_state.get("url") or "")
        raw_labels = task.sync_state.get("labels") or []
        if isinstance(raw_labels, list):
            labels = [str(label) for label in raw_labels]

    frontmatter = [
        "---",
        "generated_by: dispatcher.signboard",
        f"id: {_yaml_scalar(task.task_id)}",
        f"issue_number: {task.issue_number}",
        f"title: {_yaml_scalar(task.title)}",
        f"status: {_yaml_scalar(canonical_status(task.status))}",
        f"column: {_yaml_scalar(column_for_status(task.status))}",
        f"priority: {_yaml_scalar(task.priority)}",
        f"repo: {_yaml_scalar(task.repo)}",
        f"claimed_by: {_yaml_scalar(task.claimed_by)}",
        f"linked_pr: {_yaml_scalar(task.linked_pr)}",
        f"blocked_reason: {_yaml_scalar(task.blocked_reason)}",
        f"github_url: {_yaml_scalar(github_url)}",
        f"labels: {_yaml_list(labels)}",
        f"source_anchor_refs: {_yaml_list(source_refs)}",
        f"updated_at: {_yaml_scalar(task.updated_at)}",
        "---",
        "",
    ]

    body = [
        f"# {task.title}",
        "",
        f"- Task: `{task.task_id}`",
        f"- Issue: `#{task.issue_number}`",
        f"- Status: `{canonical_status(task.status)}`",
        f"- Priority: `{task.priority}`",
    ]
    if task.repo:
        body.append(f"- Repo: `{task.repo}`")
    if task.claimed_by:
        body.append(f"- Claimed by: `{task.claimed_by}`")
    if task.linked_pr:
        body.append(f"- PR: `#{task.linked_pr}`")
    if task.blocked_reason:
        body.append(f"- Blocked: {task.blocked_reason}")
    if github_url:
        body.append(f"- GitHub: {github_url}")
    if source_refs:
        body.append(f"- Source anchors: {', '.join(source_refs)}")
    body.extend(["", _NOTES_HEADING, ""])
    if notes:
        body.extend([notes, ""])
    body.extend(["## Receipts", ""])
    return "\n".join(frontmatter + body)
