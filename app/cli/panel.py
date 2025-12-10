from __future__ import annotations

import click

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note


@click.group(help="PanelAgent runtime commands.")
def panel() -> None:
    ...


@panel.command(name="run", help="Parse AI panels in a note and emit panel.intent.created events.")
@click.option("--uuid", "note_uuid", required=True, help="UUID for the note in ObjectStore.")
@click.option(
    "--emit-only/--run-runtime",
    "emit_only",
    default=False,
    show_default=True,
    help="Skip runtime execution and only emit panel.intent.created.",
)
def panel_run(note_uuid: str, emit_only: bool) -> None:
    try:
        events = run_panel_intent_for_note(note_uuid=note_uuid, trace_id=None)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    click.echo(f"Panels processed: {len(events)}")
    click.echo(f"Events written: {len(events)}")

    runtime_results = []
    if not emit_only:
        runtime_results = [execute_panel_intent(event) for event in events]
        click.echo(f"Runtime executed: {len(runtime_results)}")
    else:
        click.echo("Runtime execution skipped (--emit-only).")


__all__ = ["panel"]
