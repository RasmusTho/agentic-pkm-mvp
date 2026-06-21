from __future__ import annotations

from pathlib import Path
from typing import Any

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)

from app.agents.panel.parser import parse_panel
from app.api.routes.vault_resolution import active_vault_root_or_selection_required
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
def debug_panel(note_rel: str = Query(..., description="Vault-relative path to note")) -> dict[str, Any] | JSONResponse:
    vault_root = active_vault_root_or_selection_required(
        requested_note_path=note_rel,
    )
    if isinstance(vault_root, JSONResponse):
        return vault_root
    note_path = _resolve_note_path(vault_root, note_rel)
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
        "panel_diagnostics": get_panel_actions_diagnostics(),
    }


__all__ = ["router"]
