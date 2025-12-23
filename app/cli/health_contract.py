from __future__ import annotations

import json

import click

from app.health_contract import DEFAULT_CONTRACT


def emit_health_contract_status(as_json: bool) -> None:
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


__all__ = ["emit_health_contract_status"]
