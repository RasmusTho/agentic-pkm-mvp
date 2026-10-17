from __future__ import annotations

from pathlib import Path
from typing import Any

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)

from app.agents.panel.parser import parse_panel
from app.api.request_active_context import (
    current_scoped_route_read,
    route_read_vault_root_or_selection_required,
    scoped_note_path_owned_by_binding,
    scoped_route_read,
)
from app.settings.panel_actions import get_panel_actions_diagnostics

router = APIRouter(prefix="/api/debug")


def _resolve_note_path(vault_root: Path, note_rel: str) -> Path:
    if note_rel.startswith("/"):
        raise HTTPException(status_code=400, detail="note_rel must be vault-relative")
    candidate = (vault_root / note_rel).expanduser().resolve()
    try:
        candidate.relative_to(vault_root)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="note_rel escapes vault root") from exc
    return candidate


@router.get("/panel", response_model=None)
@scoped_route_read
def debug_panel(note_rel: str = Query(..., description="Vault-relative path to note")) -> dict[str, Any] | JSONResponse:
    # MVR-05B3: a carrier-bearing request reads its own bound binding; only a
    # carrier-free request resolves the legacy process selection.
    vault_root = route_read_vault_root_or_selection_required(
        requested_note_path=note_rel,
    )
    if isinstance(vault_root, JSONResponse):
        return vault_root
    scoped = current_scoped_route_read()
    if scoped is not None:
        # Contain against the real bound root, so a symlinked registry path
        # cannot make an in-binding note look like an escape (or vice versa).
        vault_root = vault_root.resolve()
    note_path = _resolve_note_path(vault_root, note_rel)
    if scoped is not None and not scoped_note_path_owned_by_binding(scoped, note_path):
        # A note owned by an initialized nested child vault is not served
        # through the parent binding.
        raise HTTPException(status_code=404, detail="note not found")
    if not note_path.exists():
        raise HTTPException(status_code=404, detail="note not found")
    try:
        markdown = note_path.read_text(encoding="utf-8")
    except Exception as exc:
        _log.error("debug panel: failed to read note %s: %s", note_path, exc)
        raise HTTPException(status_code=500, detail="failed to read note")

    state = parse_panel(markdown)
    actions = [
        {"action_id": action.action_id, "action_text": action.text, "checked": action.checked}
        for action in state.actions
    ]

    return {
        "note_rel": note_rel,
        "note_path": str(note_path),
        "parsed_actions": actions,
        # Panel-actions mapping diagnostics are process-global (one mapping root
        # for the whole process plus a process-wide last-error slot the probe
        # rewrites). A scoped read neither reports them as the bound binding's
        # nor mutates that slot.
        "panel_diagnostics": get_panel_actions_diagnostics() if scoped is None else None,
    }


__all__ = ["router"]
