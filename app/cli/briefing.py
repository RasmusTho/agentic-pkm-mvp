"""Operator commands for scheduled and explicit Daily Briefing generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import click

from app.briefing.trigger import (
    BriefingTriggerResult,
    regenerate_briefing,
    scheduled_briefing_tick,
)
from app.briefing.config import BRIEFING_TIMEZONE
from app.vault.manager import get_vault_manager
from app.vault.manager import VaultContext


@click.group(name="briefing")
def briefing_group() -> None:
    """Generate the derived Daily Briefing artifact."""


@briefing_group.command(name="tick")
@click.option("--vault-root", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON result.")
def briefing_tick(vault_root: Path | None, as_json: bool) -> None:
    result = scheduled_briefing_tick(
        vault_context=_resolve_vault_context(vault_root),
        now=datetime.now(tz=timezone.utc),
    )
    _emit(result, as_json=as_json)


@briefing_group.command(name="regenerate")
@click.option("--vault-root", type=click.Path(path_type=Path), default=None)
@click.option("--date", "date_value", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON result.")
def briefing_regenerate(
    vault_root: Path | None,
    date_value: datetime | None,
    as_json: bool,
) -> None:
    target_date = (
        date_value.date()
        if date_value is not None
        else datetime.now(tz=ZoneInfo(BRIEFING_TIMEZONE)).date()
    )
    result = regenerate_briefing(
        vault_context=_resolve_vault_context(vault_root),
        for_date=target_date,
    )
    _emit(result, as_json=as_json)


def _emit(result: BriefingTriggerResult, *, as_json: bool) -> None:
    payload = {
        "triggered": result.triggered,
        "reason": result.reason,
        "date": result.briefing_date.isoformat(),
    }
    rendered = json.dumps(payload, ensure_ascii=False)
    click.echo(rendered if as_json else json.dumps(payload, ensure_ascii=False, indent=2))


def _resolve_vault_context(vault_root: Path | None) -> VaultContext:
    manager = get_vault_manager()
    if vault_root is not None:
        return manager.validate_vault(vault_root.expanduser())
    if manager.context.status == "selected" and manager.context.active_vault_path:
        return manager.context
    return manager.load_last_active()


__all__ = ["briefing_group"]
