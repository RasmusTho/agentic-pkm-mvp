from __future__ import annotations

import click

from app.agents.panel_agent import run_panel_intent_for_note


@click.group(help="PanelAgent runtime commands.")
def panel() -> None:
    ...


@panel.command(name="run", help="Parse AI panels in a note and emit panel.intent.created events.")
@click.option("--uuid", "note_uuid", required=True, help="UUID for the note in ObjectStore.")
def panel_run(note_uuid: str) -> None:
    try:
        events = run_panel_intent_for_note(note_uuid=note_uuid, trace_id=None)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    click.echo(f"Panels processed: {len(events)}")
    click.echo(f"Events written: {len(events)}")


__all__ = ["panel"]
