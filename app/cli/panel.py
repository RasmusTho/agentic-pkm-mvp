from __future__ import annotations

import click

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note


def run_panels_for_uuids(
    note_uuids: tuple[str, ...], *, emit_only: bool
) -> tuple[int, int, int, int, list[str]]:
    processed = 0
    promotions = 0
    with_panels = 0
    errors = 0
    error_messages: list[str] = []

    for note_uuid in note_uuids:
        try:
            events = run_panel_intent_for_note(note_uuid=note_uuid, trace_id=None)
        except FileNotFoundError:
            errors += 1
            error_messages.append(f"Note not found in ObjectStore: {note_uuid}")
            continue
        processed += 1
        if events:
            with_panels += 1

        if emit_only:
            continue

        runtime_results = [execute_panel_intent(event) for event in events]
        for res in runtime_results:
            for emitted in res.emitted_events:
                name = getattr(emitted, "event", None) or (emitted.get("event") if isinstance(emitted, dict) else None)
                if name == "promote.intent.created":
                    promotions += 1
    return processed, with_panels, promotions, errors, error_messages


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


@panel.command(name="run-many", help="Run PanelAgent parse/runtime for multiple notes (UUIDs).")
@click.option(
    "--emit-only/--run-runtime",
    "emit_only",
    default=False,
    show_default=True,
    help="Skip runtime execution and only emit panel.intent.created.",
)
@click.argument("note_uuids", nargs=-1, required=True)
def panel_run_many(note_uuids: tuple[str, ...], emit_only: bool) -> None:
    processed, with_panels, promotions, errors, messages = run_panels_for_uuids(note_uuids, emit_only=emit_only)
    for msg in messages:
        click.echo(msg, err=True)
    click.echo(
        f"Processed {processed} notes; panels_found={with_panels}; promotions={promotions}; errors={errors}"
    )
    if errors:
        raise SystemExit(1)


__all__ = ["panel", "run_panels_for_uuids"]
