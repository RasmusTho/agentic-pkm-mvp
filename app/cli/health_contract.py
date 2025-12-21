from __future__ import annotations

import json

import click

from app.health_contract import DEFAULT_CONTRACT


@click.group(help="Health contract tooling built atop existing doctor assets.")
def health() -> None:
    ...


@health.command("status", help="Emit the health contract snapshot (JSON or text).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON payload.")
def status(as_json: bool) -> None:
    payload = DEFAULT_CONTRACT.evaluate()
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"state: {payload['state']}")
    click.echo(f"reason: {payload['reason']}")
    click.echo(f"since: {payload['since_ts']}")
    click.echo(f"outbox_count: {payload['outbox_count']}")
    click.echo(f"outbox_oldest_age_s: {payload['outbox_oldest_age_s']:.1f}")
    click.echo(f"index_doctor_status: {payload['index_doctor_status']}")
    click.echo(f"events_doctor_status: {payload['events_doctor_status']}")
    errors = payload.get("errors_last_10m")
    click.echo(f"errors_last_10m: {errors if errors is not None else 'n/a'}")
