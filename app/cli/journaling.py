"""Explicit CLI entrypoint for the evening reflection conversation."""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import select
import sys

import click

from app.journaling.day_context import assemble_day_context
from app.journaling.review import (
    process_journal_reviews_tick,
    project_journal_review,
)
from app.chat.reflection_conversation import ReflectionConversationService
from app.vault.manager import VaultContext


@click.group(name="journaling")
def journaling_group() -> None:
    """Conversational journaling controls."""


@journaling_group.command(name="reflect")
@click.option("--start", "start_requested", is_flag=True, required=True)
@click.option(
    "--note",
    "note_path",
    type=click.Path(path_type=Path),
    required=True,
    help="Existing vault note that anchors the chat-session artifact.",
)
@click.option("--vault-root", type=click.Path(path_type=Path), required=True)
@click.option("--date", "for_date", type=click.DateTime(formats=["%Y-%m-%d"]))
def reflect(
    *, start_requested: bool, note_path: Path, vault_root: Path, for_date: datetime | None
) -> None:
    """Start an owner-paced reflection; type /stop at any turn."""
    if not start_requested:
        raise click.UsageError("reflection starts only through explicit --start")
    root = vault_root.expanduser().resolve()
    note = note_path.expanduser()
    if not note.is_absolute():
        note = root / note
    context = VaultContext(status="selected", active_vault_path=str(root))
    target_date: date = for_date.date() if for_date is not None else date.today()
    service = ReflectionConversationService(vault_root=root)
    conversation = service.start(
        note_path=note,
        day_context=assemble_day_context(vault_context=context, for_date=target_date),
    )
    click.echo(f"Agent: {conversation.opening_turn}")

    while not conversation.closed:
        owner_text = _read_owner_turn(conversation.settings.idle_timeout_seconds)
        if owner_text is None:
            service.stop(conversation, reason="idle_timeout")
            break
        followup = service.submit_owner_turn(conversation, owner_text)
        if followup is not None:
            click.echo(f"Agent: {followup}")
    click.echo(f"Transcript: {conversation.session.log_path}")


@journaling_group.command(name="review-status")
@click.option("--vault-root", type=click.Path(path_type=Path), required=True)
@click.option("--date", "for_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON result.")
def review_status(
    *, vault_root: Path, for_date: datetime | None, as_json: bool
) -> None:
    """Project one journal candidate's durable review state without writing."""

    target_date = for_date.date() if for_date is not None else date.today()
    projection = project_journal_review(
        vault_context=_vault_context(vault_root), for_date=target_date
    )
    payload = {
        "state": projection.state.value,
        "date": target_date.isoformat(),
        "candidate_path": projection.candidate_path,
        "canonical_path": projection.canonical_path,
        "status_message": projection.status_message,
    }
    click.echo(
        json.dumps(payload, ensure_ascii=False)
        if as_json
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )


@journaling_group.command(name="review-tick")
@click.option("--vault-root", type=click.Path(path_type=Path), required=True)
@click.option("--date", "for_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--outbox-path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit one JSON result.")
def review_tick(
    *,
    vault_root: Path,
    for_date: datetime | None,
    outbox_path: Path | None,
    as_json: bool,
) -> None:
    """Observe checked journal actions and retry durable pending intent."""

    result = process_journal_reviews_tick(
        vault_context=_vault_context(vault_root),
        outbox_path=outbox_path,
        only_date=for_date.date() if for_date is not None else None,
    )
    payload = {
        "scanned_dates": list(result.scanned_dates),
        "materialized": result.materialized,
        "pending": result.pending,
        "results": [
            {
                "state": item.state.value,
                "action": item.action,
                "candidate_path": item.candidate_path,
                "canonical_path": item.canonical_path,
                "receipt_id": item.receipt_id,
                "status_message": item.status_message,
            }
            for item in result.results
        ],
    }
    click.echo(
        json.dumps(payload, ensure_ascii=False)
        if as_json
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _vault_context(vault_root: Path) -> VaultContext:
    root = vault_root.expanduser().resolve()
    if not root.is_dir():
        raise click.UsageError("--vault-root must name an existing directory")
    return VaultContext(status="selected", active_vault_path=str(root))


def _read_owner_turn(timeout_seconds: int) -> str | None:
    click.echo("Owner (/stop to finish): ", nl=False)
    ready, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
    if not ready:
        click.echo()
        return None
    line = sys.stdin.readline()
    if line == "":
        return "/stop"
    return line.rstrip("\n")


__all__ = ["journaling_group", "review_status", "review_tick"]
