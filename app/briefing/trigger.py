"""Durable, race-safe automatic and manual Daily Briefing triggers."""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from app.briefing.compose import briefing_note_path, compose_briefing
from app.briefing.config import (
    BRIEFING_ENABLED,
    BRIEFING_GENERATION_HOUR,
    BRIEFING_TIMEZONE,
)
from app.knowledge.contracts import WriteReceipt
from app.vault.manager import VaultContext, get_vault_manager
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

AutomaticTrigger = Literal["scheduled_window", "first_contact"]


@dataclass(frozen=True)
class BriefingTriggerResult:
    triggered: bool
    reason: str
    briefing_date: date
    receipt: WriteReceipt | None = None


def scheduled_briefing_tick(
    *,
    vault_context: VaultContext,
    now: datetime | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> BriefingTriggerResult:
    """Generate during the configured local-hour window when still absent."""

    local_now = _local_now(now)
    if not BRIEFING_ENABLED:
        return BriefingTriggerResult(False, "disabled", local_now.date())
    if local_now.hour != BRIEFING_GENERATION_HOUR:
        return BriefingTriggerResult(False, "outside_scheduled_window", local_now.date())
    return _automatic_trigger(
        vault_context=vault_context,
        for_date=local_now.date(),
        trigger="scheduled_window",
        write_guard=write_guard,
    )


def first_contact_briefing(
    *,
    vault_context: VaultContext,
    now: datetime | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> BriefingTriggerResult:
    """Generate on the first Companion entry of a local calendar day."""

    local_now = _local_now(now)
    if not BRIEFING_ENABLED:
        return BriefingTriggerResult(False, "disabled", local_now.date())
    return _automatic_trigger(
        vault_context=vault_context,
        for_date=local_now.date(),
        trigger="first_contact",
        write_guard=write_guard,
    )


def regenerate_briefing(
    *,
    vault_context: VaultContext,
    for_date: date,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> BriefingTriggerResult:
    """Explicitly replace a dated briefing, bypassing the automatic guard."""

    root = _selected_vault_root(vault_context)
    with _vault_generation_lock(root):
        receipt = compose_briefing(
            vault_context=vault_context,
            for_date=for_date,
            write_guard=write_guard,
        )
    return BriefingTriggerResult(True, "manual_regenerate", for_date, receipt)


def _automatic_trigger(
    *,
    vault_context: VaultContext,
    for_date: date,
    trigger: AutomaticTrigger,
    write_guard: WriteGuard,
) -> BriefingTriggerResult:
    root = _selected_vault_root(vault_context)
    if not _vault_local_writes_allowed(vault_context):
        return BriefingTriggerResult(False, "vault_local_writes_disabled", for_date)

    # Presence of the durable dated artifact is the idempotency truth. The
    # directory lock only serializes cooperating watcher/API processes long
    # enough to repeat that durable check and close the check-then-write race.
    if briefing_note_path(vault_context=vault_context, for_date=for_date).exists():
        return BriefingTriggerResult(False, "already_generated_today", for_date)
    with _vault_generation_lock(root):
        if briefing_note_path(vault_context=vault_context, for_date=for_date).exists():
            return BriefingTriggerResult(False, "already_generated_today", for_date)
        receipt = compose_briefing(
            vault_context=vault_context,
            for_date=for_date,
            write_guard=write_guard,
        )
    return BriefingTriggerResult(True, trigger, for_date, receipt)


class _vault_generation_lock:
    """Cross-process lock using the existing vault directory, with no marker write."""

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root
        self._fd: int | None = None

    def __enter__(self) -> None:
        self._fd = os.open(self._vault_root, os.O_RDONLY)
        fcntl.flock(self._fd, fcntl.LOCK_EX)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        assert self._fd is not None
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def _local_now(now: datetime | None) -> datetime:
    current = now or datetime.now(tz=timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("briefing trigger time must be timezone-aware")
    return current.astimezone(ZoneInfo(BRIEFING_TIMEZONE))


def _selected_vault_root(context: VaultContext) -> Path:
    if context.status != "selected" or not context.active_vault_path:
        raise ValueError("briefing trigger requires a selected vault context")
    root = Path(context.active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("briefing trigger requires an existing vault root")
    return root


def _vault_local_writes_allowed(context: VaultContext) -> bool:
    if not context.settings_path:
        return True
    return get_vault_manager().permissions_for_context(context).allow_writes_to_vault


__all__ = [
    "BriefingTriggerResult",
    "first_contact_briefing",
    "regenerate_briefing",
    "scheduled_briefing_tick",
]
