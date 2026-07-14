"""Explicit CLI entrypoint for the evening reflection conversation."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import select
import sys

import click

from app.journaling.day_context import assemble_day_context
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


__all__ = ["journaling_group"]
