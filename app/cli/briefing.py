"""Operator commands for scheduled and explicit Daily Briefing generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import click

from app.briefing.trigger import (
    BriefingTriggerResult,
    regenerate_briefing,
    scheduled_briefing_tick,
)
from app.briefing.config import BRIEFING_TIMEZONE
from app.vault.manager import get_vault_manager


@click.group(name="briefing")
def briefing_group() -> None:
    """Generate the derived Daily Briefing artifact."""


@briefing_group.command(name="tick")
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON result.")
def briefing_tick(as_json: bool) -> None:
    result = scheduled_briefing_tick(
        vault_context=get_vault_manager().context,
        now=datetime.now(tz=timezone.utc),
    )
    _emit(result, as_json=as_json)


@briefing_group.command(name="regenerate")
@click.option("--date", "date_value", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON result.")
def briefing_regenerate(date_value: datetime | None, as_json: bool) -> None:
    target_date = (
        date_value.date()
        if date_value is not None
        else datetime.now(tz=ZoneInfo(BRIEFING_TIMEZONE)).date()
    )
    result = regenerate_briefing(
        vault_context=get_vault_manager().context,
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


__all__ = ["briefing_group"]
