"""Local Signboard API served from the dispatcher store.

The dispatcher store is the board's only authority: every card is built from
``list_tasks`` on read, and lifecycle changes go through dispatcher services on
write. There is no Markdown projection in this path.

The board used to read back from disk what it had just written to the database,
and having a second copy to locate, reconcile, and prune is what #4279, #4293
and #4370 were each filed against. Serving from the store removes the root, the
drift, and the reconciliation together (#4401). ``export-signboard`` remains as
a legacy operator command for hosts that still keep a board directory.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_loopback_or_api_key
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import TaskRecord
from app.dispatcher.queue import block, complete
from app.dispatcher.services import move_task
from app.dispatcher.signboard import STATUS_COLUMNS, canonical_status, column_for_status
from app.dispatcher.store import SqliteStore

router = APIRouter(prefix="/signboard", tags=["signboard"])

# Column identity and order both derive from the dispatcher's status -> column
# table, so the board cannot disagree with the dispatcher about where a status
# belongs. Two spellings of one mapping is the class of drift this route is
# being taken out of.
COLUMNS: tuple[str, ...] = tuple(dict.fromkeys(STATUS_COLUMNS.values()))

# Synchronization metadata is stored as a task row for dispatcher
# compatibility, but it is not a board card.
_METADATA_STATUS = "_meta"


class MoveRequest(BaseModel):
    status: str
    actor: str = Field(default="signboard-ui", min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=4_000)
    blocked_reason: str | None = Field(default=None, max_length=4_000)


def _store() -> SqliteStore:
    paths = load_paths()
    if not paths.db_path.exists():
        raise HTTPException(status_code=503, detail="dispatcher is not initialised")
    return SqliteStore(paths.db_path, JsonlEventWriter(paths.events_path))


def _list_tasks(store: SqliteStore) -> list[TaskRecord]:
    """Read the store's tasks, turning an unusable store into a visible error.

    A store file that exists but carries no dispatcher schema would otherwise
    surface as an internal error. The board's standing invariant is that a board
    with no readable authority never renders as six healthy empty columns —
    "no work" and "misconfigured" must not look the same (#4279).
    """

    try:
        return store.list_tasks()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503, detail=f"dispatcher store is not readable: {exc}"
        ) from exc


def _card(task: TaskRecord) -> dict[str, Any]:
    """Render one dispatcher task as a board card.

    Raises :class:`ValueError` for a status the dispatcher's column table does
    not know, so the caller can report that task instead of dropping it.
    """

    sync_state = task.sync_state or {}
    raw_labels = sync_state.get("labels")
    github_url = str(sync_state.get("url") or "")
    return {
        "id": task.task_id,
        "issue_number": task.issue_number,
        "title": task.title or task.task_id,
        "status": canonical_status(task.status),
        "column": column_for_status(task.status),
        "priority": task.priority or "unspecified",
        "repo": task.repo or None,
        "labels": [str(label) for label in raw_labels] if isinstance(raw_labels, list) else [],
        "blocked_reason": task.blocked_reason or None,
        "claimed_by": task.claimed_by or None,
        "linked_pr": task.linked_pr or None,
        "github_url": github_url or None,
        "source_anchor_refs": [str(ref) for ref in (task.source_anchor_refs or [])],
        "updated_at": task.updated_at or None,
    }


def _board_payload(store: SqliteStore) -> dict[str, Any]:
    cards: dict[str, list[dict[str, Any]]] = {column: [] for column in COLUMNS}
    errors: list[str] = []
    for task in _list_tasks(store):
        if task.status == _METADATA_STATUS:
            continue
        try:
            card = _card(task)
        except ValueError as exc:
            errors.append(f"could not place task {task.task_id}: {exc}")
            continue
        cards[card["column"]].append(card)
    return {
        "columns": [{"name": column, "cards": cards[column]} for column in COLUMNS],
        "errors": errors,
        "status": "error" if errors else "ok",
        "authority": "dispatcher_store",
    }


@router.get("/board")
def get_board() -> dict[str, Any]:
    return _board_payload(_store())


@router.post("/refresh", dependencies=[Depends(require_loopback_or_api_key)])
def refresh_board() -> dict[str, Any]:
    """Re-read the board.

    Kept as the UI's explicit reload. Every read already comes from the store,
    so there is nothing left to re-materialize.
    """

    return _board_payload(_store())


@router.post("/cards/{task_id}/move", dependencies=[Depends(require_loopback_or_api_key)])
def move_card(task_id: str, request: MoveRequest) -> dict[str, Any]:
    if task_id == _METADATA_STATUS or "/" in task_id or "\\" in task_id or ".." in task_id:
        raise HTTPException(status_code=400, detail="invalid task id")
    store = _store()
    try:
        next_status = canonical_status(request.status)
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
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    payload = _board_payload(store)
    payload["task"] = {"id": task.task_id, "status": task.status}
    return payload


__all__ = ["COLUMNS", "router"]
