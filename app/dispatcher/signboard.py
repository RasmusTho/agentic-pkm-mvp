"""Signboard Markdown projection for dispatcher tasks.

The dispatcher remains the operational source of truth. This module writes a
one-way Markdown projection that lightweight kanban tools can render from disk.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore


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

    tasks = store.list_tasks()
    written: list[str] = []
    for task in tasks:
        filename = _task_filename(task)
        target_column = column_for_status(task.status)
        target = root / target_column / filename
        for column in sorted(set(STATUS_COLUMNS.values())):
            for candidate in (root / column).glob(f"{task.task_id}--*.md"):
                if candidate == target:
                    continue
                if _is_generated_card(candidate):
                    candidate.unlink()

        for column in sorted(set(STATUS_COLUMNS.values())):
            candidate = root / column / filename
            if candidate.exists() and column != target_column:
                candidate.unlink()

        target.write_text(_render_task(task), encoding="utf-8")
        written.append(str(target))

    return {
        "root": str(root),
        "count": len(tasks),
        "columns": sorted(set(STATUS_COLUMNS.values())),
        "written": written,
    }


def _task_filename(task: TaskRecord) -> str:
    title = re.sub(r"[^A-Za-z0-9._-]+", "-", task.title.strip()).strip("-")
    title = title[:72].strip("-") or "task"
    return f"{task.task_id}--{title}.md"


def _is_generated_card(path: Path) -> bool:
    try:
        return "generated_by: dispatcher.signboard" in path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return False


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(_yaml_scalar(v) for v in values) + "]"


def _render_task(task: TaskRecord) -> str:
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
    body.extend(["", "## Notes", "", "## Receipts", ""])
    return "\n".join(frontmatter + body)
