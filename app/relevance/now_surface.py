"""Collect materialized moments for the companion-UI "now" / glance surface.

This is a read-only projection of vault-native moment artifacts. It reads
``<system_folder>/moments/*.md`` and returns view-models the glance surface
renders. If the governed attention loop has recorded an in-app reach-out
decision for a moment, the projection includes an in-app nudge marker. It
performs no write, reads no external source, and emits no OS notification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.relevance.attention_loop import query_reachout_receipts
from app.relevance.schema import URGENCY_ORDER, Moment, moment_from_frontmatter
from app.vault.manager import VaultContext
from app.vault.paths import get_vault_system_dir_rel


def collect_now_moments(
    vault_context: VaultContext,
    *,
    reachout_outbox_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return view-models for materialized moments, most urgent first."""

    if not vault_context.active_vault_path:
        return []
    vault_root = Path(vault_context.active_vault_path).expanduser().resolve()
    moments_dir = vault_root / get_vault_system_dir_rel(vault_root) / "moments"
    if not moments_dir.is_dir():
        return []

    nudges = _in_app_nudges_by_moment(reachout_outbox_path=reachout_outbox_path)
    views: list[dict[str, Any]] = []
    for path in sorted(moments_dir.glob("*.md")):
        moment = _load_moment(path)
        if moment is None:
            continue
        views.append(_to_view(moment, in_app_nudge=nudges.get(moment.uuid)))

    views.sort(
        key=lambda v: (URGENCY_ORDER.index(v["urgency_band"]), v["created"]),
        reverse=True,
    )
    return views


def _to_view(moment: Moment, *, in_app_nudge: dict[str, Any] | None = None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "moment_id": moment.uuid,
        "title": moment.need.summary,
        "need_basis": moment.need.basis,
        "urgency_band": moment.urgency.band,
        "lifecycle": moment.lifecycle,
        "created": moment.created,
        "authority": moment.authority,
        "surfaced_refs": [
            {"ref": ref.ref, "why": ref.why, "uuid": ref.uuid}
            for ref in moment.surfaced_refs
        ],
    }
    if in_app_nudge is not None:
        view["in_app_nudge"] = in_app_nudge
    return view


def _in_app_nudges_by_moment(*, reachout_outbox_path: Path | None) -> dict[str, dict[str, Any]]:
    nudges: dict[str, dict[str, Any]] = {}
    for record in query_reachout_receipts(outbox_path=reachout_outbox_path):
        payload = record.get("payload") or {}
        moment_uuid = payload.get("moment_uuid")
        reachout = payload.get("reachout") or {}
        if not isinstance(moment_uuid, str) or not isinstance(reachout, dict):
            continue
        if reachout.get("outcome") != "in_app":
            nudges.pop(moment_uuid, None)
            continue
        nudges[moment_uuid] = {
            "active": True,
            "receipt_id": payload.get("receipt_id"),
            "rung": reachout.get("rung"),
            "interruptibility_state": reachout.get("interruptibility_state"),
            "effective_band": reachout.get("effective_band"),
            "reason": reachout.get("reason"),
        }
    return nudges


def _load_moment(path: Path) -> Moment | None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) != 3:
        return None
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict) or frontmatter.get("type") != "moment":
        return None
    try:
        return moment_from_frontmatter(frontmatter)
    except Exception:
        return None


__all__ = ["collect_now_moments"]
