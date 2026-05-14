"""Vault Action Layer — bounded, governed note mutations.

This module is the first Tier-2 write surface for panel-driven vault actions.
Every mutation passes through:
  1. Zone validation (only inbox → workbench is permitted in this slice)
  2. Source zone check (note must be in the expected source zone)
  3. Idempotency check (already-moved notes return skipped=True)
  4. Write guard (system health contract)
  5. Collision-safe rename if the destination already has a note of the same name
  6. Atomic move (shutil.move)
  7. Durable receipt appended to the moved note

No hardcoded folder names are used — all paths resolve through VaultLayout.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.vault.layout import VaultLayout
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

logger = logging.getLogger(__name__)

# Only one source→destination pair is supported in this slice.
_ALLOWED_ZONES: dict[str, str] = {
    "inbox": "workbench",
}

_RECEIPT_ACTION = "move_note_to_zone"


@dataclass
class MoveResult:
    """Result of a move_note_to_zone call."""

    success: bool
    skipped: bool  # True when idempotency check short-circuited (already moved)
    source_path: Path
    destination_path: Path
    collision_resolved: bool
    receipt_path: Optional[Path]
    reason: str


def _zone_dir(zone: str, vault_root: Path, layout: VaultLayout) -> Path:
    """Resolve an abstract zone name to an absolute directory path."""
    if zone == "inbox":
        return vault_root / layout.inbox_folder
    if zone == "workbench":
        return vault_root / layout.desk_folder
    raise ValueError(f"Unknown zone: {zone!r}")


def _collision_safe_path(destination_dir: Path, name: str) -> tuple[Path, bool]:
    """Return a path that does not already exist in destination_dir.

    If *name* is free, returns (destination_dir / name, False).
    Otherwise appends _2, _3, … until a free slot is found.
    Returns (resolved_path, collision_resolved).
    """
    candidate = destination_dir / name
    if not candidate.exists():
        return candidate, False
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        candidate = destination_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate, True
        counter += 1


def _append_receipt(
    note_path: Path,
    *,
    action: str,
    actor: str,
    source_path: Path,
    destination_path: Path,
    zone: str,
    ts: str,
    intent_id: Optional[str],
) -> None:
    """Append a receipt HTML comment block to the moved note."""
    intent_part = f" | intent: {intent_id}" if intent_id else ""
    receipt = (
        f"\n<!-- vault-action-receipt: {action}"
        f" | actor: {actor}"
        f" | from: {source_path}"
        f" | to: {destination_path}"
        f" | zone: {zone}"
        f" | ts: {ts}"
        f"{intent_part} -->\n"
    )
    existing = note_path.read_text(encoding="utf-8")
    note_path.write_text(existing + receipt, encoding="utf-8")


def move_note_to_zone(
    note_path: Path,
    destination_zone: str,
    vault_root: Path,
    layout: VaultLayout,
    actor: str,
    intent_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    write_guard=None,
) -> MoveResult:
    """Move a note from one vault zone to another.

    Only inbox → workbench is supported in this slice.  All other
    source/destination pairs are rejected with success=False.

    Args:
        note_path: Absolute path to the note to move.
        destination_zone: Target zone name (only "workbench" is supported).
        vault_root: Absolute vault root directory.
        layout: VaultLayout instance for the vault.
        actor: String identifier for the caller (e.g. "panel_agent").
        intent_id: Optional intent correlation identifier for the receipt.
        trace_id: Optional distributed trace identifier.
        write_guard: Optional WriteGuard to use (defaults to DEFAULT_WRITE_GUARD).

    Returns:
        MoveResult with outcome details.
    """
    if write_guard is None:
        write_guard = DEFAULT_WRITE_GUARD

    source_path = note_path.resolve()

    # 1. Zone validation — determine source zone from the note's location.
    inbox_dir = (vault_root / layout.inbox_folder).resolve()
    workbench_dir = (vault_root / layout.desk_folder).resolve()

    try:
        source_path.relative_to(inbox_dir)
        source_zone = "inbox"
    except ValueError:
        source_zone = None

    if source_zone is None:
        reason = (
            f"Note is not in inbox zone (inbox_folder={layout.inbox_folder!r}); "
            f"note_path={source_path}"
        )
        logger.warning("move_note_to_zone rejected: %s", reason)
        return MoveResult(
            success=False,
            skipped=False,
            source_path=source_path,
            destination_path=source_path,
            collision_resolved=False,
            receipt_path=None,
            reason=reason,
        )

    allowed_destination = _ALLOWED_ZONES.get(source_zone)
    if destination_zone != allowed_destination:
        reason = (
            f"Zone transition not allowed: {source_zone!r} → {destination_zone!r}. "
            f"Only inbox → workbench is supported in this slice."
        )
        logger.warning("move_note_to_zone rejected: %s", reason)
        return MoveResult(
            success=False,
            skipped=False,
            source_path=source_path,
            destination_path=source_path,
            collision_resolved=False,
            receipt_path=None,
            reason=reason,
        )

    # 2. Idempotency check — if the note no longer exists at source, it was already moved.
    if not source_path.exists():
        reason = f"Note not found at source path (already moved or deleted): {source_path}"
        logger.info("move_note_to_zone skipped (idempotent): %s", reason)
        return MoveResult(
            success=True,
            skipped=True,
            source_path=source_path,
            destination_path=source_path,
            collision_resolved=False,
            receipt_path=None,
            reason=reason,
        )

    # 3. Write guard.
    try:
        write_guard.assert_writes_allowed(_RECEIPT_ACTION)
    except WritesBlockedError as exc:
        reason = f"Write guard denied: {exc}"
        logger.warning("move_note_to_zone blocked by write guard: %s", reason)
        return MoveResult(
            success=False,
            skipped=False,
            source_path=source_path,
            destination_path=source_path,
            collision_resolved=False,
            receipt_path=None,
            reason=reason,
        )

    # 4. Destination resolution.
    destination_dir = workbench_dir
    destination_dir.mkdir(parents=True, exist_ok=True)

    # 5. Collision handling.
    final_destination, collision_resolved = _collision_safe_path(destination_dir, source_path.name)

    # 6. Atomic move.
    shutil.move(str(source_path), str(final_destination))
    logger.info(
        "move_note_to_zone: moved note actor=%s from=%s to=%s collision_resolved=%s trace_id=%s",
        actor,
        source_path,
        final_destination,
        collision_resolved,
        trace_id or "-",
    )

    # 7. Durable receipt.
    ts = datetime.now(timezone.utc).isoformat()
    try:
        _append_receipt(
            final_destination,
            action=_RECEIPT_ACTION,
            actor=actor,
            source_path=source_path,
            destination_path=final_destination,
            zone=destination_zone,
            ts=ts,
            intent_id=intent_id,
        )
        receipt_path = final_destination
    except OSError:
        logger.warning(
            "move_note_to_zone: receipt write failed (note already moved) note=%s",
            final_destination,
        )
        receipt_path = None

    return MoveResult(
        success=True,
        skipped=False,
        source_path=source_path,
        destination_path=final_destination,
        collision_resolved=collision_resolved,
        receipt_path=receipt_path,
        reason="ok",
    )


__all__ = ["MoveResult", "move_note_to_zone"]
