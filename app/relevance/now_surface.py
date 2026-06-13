"""Collect materialized moments for the companion-UI "now" / glance surface.

This is a read-only projection of vault-native moment artifacts — pull-only. It
reads ``<system_folder>/moments/*.md`` and returns view-models the glance surface
renders. It performs no write, reads no external source, and emits no
notification: the human pulls the surface; the system does not reach out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.relevance.schema import URGENCY_ORDER, Moment, moment_from_frontmatter
from app.vault.manager import VaultContext
from app.vault.paths import get_vault_system_dir_rel


def collect_now_moments(vault_context: VaultContext) -> list[dict[str, Any]]:
    """Return view-models for materialized moments, most urgent first (pull-only)."""

    if not vault_context.active_vault_path:
        return []
    vault_root = Path(vault_context.active_vault_path).expanduser().resolve()
    moments_dir = vault_root / get_vault_system_dir_rel(vault_root) / "moments"
    if not moments_dir.is_dir():
        return []

    views: list[dict[str, Any]] = []
    for path in sorted(moments_dir.glob("*.md")):
        moment = _load_moment(path)
        if moment is None:
            continue
        views.append(_to_view(moment))

    views.sort(
        key=lambda v: (URGENCY_ORDER.index(v["urgency_band"]), v["created"]),
        reverse=True,
    )
    return views


def _to_view(moment: Moment) -> dict[str, Any]:
    return {
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
