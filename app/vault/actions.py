"""Vault Action Layer — governed artifact placement and lifecycle actions.

This module is the **first slice** of a broader Vault Action Layer for
Yggdrasil.  The current implementation supports only one bounded action:
Markdown note placement from the inbox zone to the workbench zone.

Long-term direction
-------------------
Agents should not receive raw filesystem powers.  Agents should request
governed artifact lifecycle actions.  The Vault Action Layer decides
whether, where, how, and with what receipt an artifact changes place,
state, relation, or derivative form.

Future artifact kinds this layer must eventually cover:

- Markdown notes (this slice)
- images / screenshots / whiteboards
- PDFs / receipts / invoices
- voice recordings and transcripts
- videos
- email exports / attachments
- generated companion / system artifacts
- source archives and retained raw material

Future action model:

- place / move / route
- attach / link
- derive / transcribe / OCR / summarize
- classify / enrich metadata
- archive / retain / expire
- promote / reject / quarantine

All future actions must pass through the same governed chain::

    policy gate → write guard → idempotency check
    → collision/placement handling → mutation
    → receipt → mirror/outbox event

``move_note_to_zone()`` is a narrow first-slice helper, not the full
long-term abstraction.  A future generalisation (e.g.
``place_artifact_in_zone()``) should supersede it once the artifact model
is defined and multiple kinds are supported.

Panel-writeback note
--------------------
The panel runtime writes a human-visible "✅ {label}" receipt to the note
as soon as the downstream ``note.move.workbench`` event is *queued* — not
after the worker successfully executes the move.  The Vault Action Layer
receipt (HTML comment appended to the moved note) is the authoritative
execution receipt.  A future slice should align panel-receipt semantics
with execution reality (e.g. "🔄 queued" vs "✅ done").
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
_RECEIPT_EVENT = "note.move.workbench"


@dataclass
class MoveResult:
    """Result of a move_note_to_zone call.

    ``success`` reflects whether the caller's intent was satisfied.
    ``mutation_applied`` indicates whether a filesystem move actually occurred.
    ``receipt_written`` indicates whether the durable receipt was persisted.
    Callers must not treat ``success=True`` as evidence that both mutation
    and receipt succeeded — inspect each field independently.
    """

    success: bool
    skipped: bool  # True when idempotency check short-circuited
    mutation_applied: bool
    receipt_written: bool
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
    event: str,
    actor: str,
    source_zone: str,
    destination_zone: str,
    source_path: Path,
    destination_path: Path,
    vault_root: Path,
    ts: str,
    write_guard_decision: str,
    intent_id: Optional[str],
    trace_id: Optional[str],
) -> None:
    """Append a receipt HTML comment block to the moved note.

    Paths are written as vault-relative strings to avoid encoding machine-
    specific absolute paths into durable Markdown artifacts.
    """
    try:
        from_rel = source_path.relative_to(vault_root).as_posix()
    except ValueError:
        from_rel = source_path.name
    try:
        to_rel = destination_path.relative_to(vault_root).as_posix()
    except ValueError:
        to_rel = destination_path.name

    parts = [
        f"vault-action-receipt: {action}",
        f"actor: {actor}",
        f"event: {event}",
        f"source_zone: {source_zone}",
        f"destination_zone: {destination_zone}",
        f"from: {from_rel}",
        f"to: {to_rel}",
        f"write_guard: {write_guard_decision}",
        f"ts: {ts}",
    ]
    if intent_id:
        parts.append(f"intent: {intent_id}")
    if trace_id:
        parts.append(f"trace: {trace_id}")

    receipt = f"\n<!-- {' | '.join(parts)} -->\n"
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
    """Move a Markdown note from one vault zone to another.

    Only inbox → workbench is supported in this slice.  All other
    source/destination pairs are rejected with success=False.

    This is a narrow first-slice implementation of the Vault Action Layer.
    See module docstring for the intended long-term abstraction.

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
        MoveResult with outcome details.  Inspect ``mutation_applied`` and
        ``receipt_written`` independently; ``success=True`` alone does not
        guarantee both succeeded.
    """
    if write_guard is None:
        write_guard = DEFAULT_WRITE_GUARD

    source_path = note_path.resolve()
    vault_root = vault_root.resolve()

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
            f"source_zone_invalid: note is not in inbox zone "
            f"(inbox_folder={layout.inbox_folder!r})"
        )
        logger.warning("move_note_to_zone rejected: %s", reason)
        return MoveResult(
            success=False,
            skipped=False,
            mutation_applied=False,
            receipt_written=False,
            source_path=source_path,
            destination_path=source_path,
            collision_resolved=False,
            receipt_path=None,
            reason=reason,
        )

    allowed_destination = _ALLOWED_ZONES.get(source_zone)
    if destination_zone != allowed_destination:
        reason = (
            f"destination_zone_invalid: transition {source_zone!r} → "
            f"{destination_zone!r} is not allowed; only inbox → workbench "
            f"is supported in this slice"
        )
        logger.warning("move_note_to_zone rejected: %s", reason)
        return MoveResult(
            success=False,
            skipped=False,
            mutation_applied=False,
            receipt_written=False,
            source_path=source_path,
            destination_path=source_path,
            collision_resolved=False,
            receipt_path=None,
            reason=reason,
        )

    # 2. Idempotency check (conservative).
    #    Source missing is NOT sufficient evidence of a prior successful move.
    #    The note may have been deleted, manually relocated, or the call may
    #    carry a stale path.  Filename presence in the workbench is also
    #    unreliable: a pre-existing file with the same name would produce a
    #    false positive after a collision-resolved move (which lands at
    #    my-note_2.md, not my-note.md).
    #
    #    Verified idempotency requires receipt-level evidence (intent_id,
    #    note uuid, or stored destination path).  That is deferred to a
    #    follow-up slice.  For now, any missing-source case is reported as
    #    source_missing_unverified so the caller can decide what to do.
    if not source_path.exists():
        reason = "source_missing_unverified"
        logger.warning(
            "move_note_to_zone: source_missing_unverified — note not found at "
            "source path; may have been already moved, deleted, manually relocated, "
            "or path is stale. Cannot verify without receipt/uuid evidence. source=%s",
            source_path,
        )
        return MoveResult(
            success=False,
            skipped=True,
            mutation_applied=False,
            receipt_written=False,
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
        reason = f"write_guard_denied: {exc}"
        logger.warning("move_note_to_zone blocked by write guard: %s", reason)
        return MoveResult(
            success=False,
            skipped=False,
            mutation_applied=False,
            receipt_written=False,
            source_path=source_path,
            destination_path=source_path,
            collision_resolved=False,
            receipt_path=None,
            reason=reason,
        )

    # 4. Destination resolution + collision handling.
    workbench_dir.mkdir(parents=True, exist_ok=True)
    final_destination, collision_resolved = _collision_safe_path(
        workbench_dir, source_path.name
    )

    # 5. Atomic move.
    shutil.move(str(source_path), str(final_destination))
    logger.info(
        "move_note_to_zone: actor=%s from=%s to=%s collision_resolved=%s trace_id=%s",
        actor,
        source_path,
        final_destination,
        collision_resolved,
        trace_id or "-",
    )

    # 6. Durable receipt.
    ts = datetime.now(timezone.utc).isoformat()
    receipt_written = False
    receipt_path: Optional[Path] = None
    try:
        _append_receipt(
            final_destination,
            action=_RECEIPT_ACTION,
            event=_RECEIPT_EVENT,
            actor=actor,
            source_zone=source_zone,
            destination_zone=destination_zone,
            source_path=source_path,
            destination_path=final_destination,
            vault_root=vault_root,
            ts=ts,
            write_guard_decision="allowed",
            intent_id=intent_id,
            trace_id=trace_id,
        )
        receipt_written = True
        receipt_path = final_destination
    except OSError as exc:
        logger.warning(
            "move_note_to_zone: receipt write failed note=%s error=%s",
            final_destination,
            exc,
        )

    reason = "ok" if receipt_written else "moved_without_receipt"
    return MoveResult(
        success=True,
        skipped=False,
        mutation_applied=True,
        receipt_written=receipt_written,
        source_path=source_path,
        destination_path=final_destination,
        collision_resolved=collision_resolved,
        receipt_path=receipt_path,
        reason=reason,
    )


__all__ = ["MoveResult", "move_note_to_zone"]
