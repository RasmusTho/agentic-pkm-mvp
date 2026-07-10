"""Local Signboard API: a Markdown projection with dispatcher-backed mutations.

The board deliberately reads the generated Markdown projection for presentation,
while lifecycle changes always go through dispatcher services and are re-exported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_loopback_or_api_key
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.queue import block, complete
from app.dispatcher.services import move_task
from app.dispatcher.signboard import STATUS_COLUMNS, canonical_status, export_signboard
from app.dispatcher.store import SqliteStore

router = APIRouter(prefix="/signboard", tags=["signboard"])

COLUMNS = ("Backlog", "Ready", "In Progress", "Review", "Blocked", "Done")


@dataclass(frozen=True)
class ParsedCard:
    id: str
    issue_number: int | None
    title: str
    status: str
    column: str
    priority: str
    labels: list[str]
    blocked_reason: str | None
    claimed_by: str | None
    linked_pr: str | None
    github_url: str | None
    source_anchor_refs: list[str]
    updated_at: str | None
    body: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class MoveRequest(BaseModel):
    status: str
    actor: str = Field(default="signboard-ui", min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=4_000)
    blocked_reason: str | None = Field(default=None, max_length=4_000)


def signboard_root() -> Path:
    """Return the operator-configured, local-only projection root.

    No request controls this path. Resolving it once prevents a symlinked root
    from turning a card read into arbitrary traversal later on.
    """
    raw = os.getenv("SIGNBOARD_ROOT", "~/BuilderOpsVault/agent-delivery")
    return Path(raw).expanduser().resolve()


def _store() -> SqliteStore:
    paths = load_paths()
    if not paths.db_path.exists():
        raise HTTPException(status_code=503, detail="dispatcher is not initialised")
    return SqliteStore(paths.db_path, JsonlEventWriter(paths.events_path))


def parse_signboard_markdown(markdown: str, *, expected_column: str) -> ParsedCard | None:
    """Parse one generated Signboard card; non-cards and malformed cards return None."""
    if not markdown.startswith("---\n"):
        return None
    end = markdown.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        metadata = yaml.safe_load(markdown[4:end])
    except yaml.YAMLError:
        return None
    if not isinstance(metadata, dict) or metadata.get("generated_by") != "dispatcher.signboard":
        return None
    card_id = metadata.get("id")
    if not isinstance(card_id, str) or not card_id or card_id == "_meta":
        return None
    status = metadata.get("status")
    column = metadata.get("column")
    if not isinstance(status, str) or not isinstance(column, str) or column != expected_column:
        return None
    try:
        if STATUS_COLUMNS[canonical_status(status)] != expected_column:
            return None
    except ValueError:
        return None

    def text(key: str) -> str | None:
        value = metadata.get(key)
        return str(value) if value not in (None, "") else None

    def strings(key: str) -> list[str]:
        value = metadata.get(key)
        return [str(item) for item in value] if isinstance(value, list) else []

    issue = metadata.get("issue_number")
    return ParsedCard(
        id=card_id,
        issue_number=issue if isinstance(issue, int) else None,
        title=text("title") or card_id,
        status=canonical_status(status),
        column=column,
        priority=text("priority") or "unspecified",
        labels=strings("labels"),
        blocked_reason=text("blocked_reason"),
        claimed_by=text("claimed_by"),
        linked_pr=text("linked_pr"),
        github_url=text("github_url"),
        source_anchor_refs=strings("source_anchor_refs"),
        updated_at=text("updated_at"),
        body=markdown[end + 5 :].strip(),
    )


def read_signboard(root: Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Read generated cards only, never following entries outside the board root."""
    board: dict[str, list[dict[str, Any]]] = {column: [] for column in COLUMNS}
    errors: list[str] = []
    if not root.exists():
        return board, errors
    for column in COLUMNS:
        directory = root / column
        if not directory.exists():
            continue
        if not directory.is_dir():
            errors.append(f"{column} is not a directory")
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
                if resolved.parent != directory.resolve():
                    continue
                card = parse_signboard_markdown(resolved.read_text(encoding="utf-8"), expected_column=column)
            except (OSError, ValueError) as exc:
                errors.append(f"could not read {column}/{path.name}: {exc}")
                continue
            if card is not None:
                board[column].append(card.to_dict())
    return board, errors


def _board_payload(root: Path) -> dict[str, Any]:
    board, errors = read_signboard(root)
    return {
        "root": str(root),
        "columns": [{"name": column, "cards": board[column]} for column in COLUMNS],
        "errors": errors,
        "authority": "dispatcher_projection",
    }


@router.get("/board")
def get_board() -> dict[str, Any]:
    return _board_payload(signboard_root())


@router.post("/refresh", dependencies=[Depends(require_loopback_or_api_key)])
def refresh_board() -> dict[str, Any]:
    root = signboard_root()
    export_signboard(_store(), root)
    return _board_payload(root)


@router.post("/cards/{task_id}/move", dependencies=[Depends(require_loopback_or_api_key)])
def move_card(task_id: str, request: MoveRequest) -> dict[str, Any]:
    if task_id == "_meta" or "/" in task_id or "\\" in task_id or ".." in task_id:
        raise HTTPException(status_code=400, detail="invalid task id")
    try:
        next_status = canonical_status(request.status)
        store = _store()
        if next_status == "blocked":
            if not request.blocked_reason or not request.blocked_reason.strip():
                raise ValueError("blocked status requires blocked_reason")
            task = block(store, task_id, request.blocked_reason.strip(), request.actor)
        elif next_status == "completed":
            existing = store.get_task(task_id)
            if existing is None:
                raise ValueError(f"Task {task_id} not found")
            task = complete(store, task_id, request.actor) if existing.lease_id is not None else move_task(
                store, task_id, next_status, request.actor, request.note
            )
        else:
            task = move_task(store, task_id, next_status, request.actor, request.note)
        root = signboard_root()
        export_signboard(store, root)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    payload = _board_payload(root)
    payload["task"] = {"id": task.task_id, "status": task.status}
    return payload


__all__ = ["router", "parse_signboard_markdown", "read_signboard", "signboard_root"]
