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


def emit_health_contract_explain() -> None:
    payload = DEFAULT_CONTRACT.evaluate()
    writes_allowed = payload.get("writes_allowed", True)
    guard_reason = payload.get("write_guard_reason")
    click.echo(f"State: {payload['state']} (since {payload['since_ts']})")
    click.echo(f"Reason: {payload['reason']}")
    click.echo(f"Writes allowed: {'yes' if writes_allowed else 'no'}")
    click.echo(f"Write guard reason: {guard_reason if guard_reason else 'n/a'}")
    click.echo(f"Outbox count: {payload['outbox_count']}")
    click.echo(f"Outbox oldest age: {payload['outbox_oldest_age_s']:.1f}s")
    click.echo(f"Index doctor: {payload.get('index_doctor_status', 'unknown')}")
    click.echo(f"Events doctor: {payload.get('events_doctor_status', 'unknown')}")
    progress = payload.get("catch_up_progress")
    if progress:
        click.echo(
            "Catch-up progress: "
            f"mode={progress.get('processing_mode')} "
            f"entries={progress.get('outbox_count')} "
            f"age={progress.get('outbox_oldest_age_s'):.1f}s"
        )
    actions = payload.get("suggested_actions") or []
    click.echo("Suggested actions:")
    if actions:
        for action in actions:
            click.echo(f"  - {action}")
    else:
        click.echo("  - none")


__all__ = ["emit_health_contract_status", "emit_health_contract_explain"]
