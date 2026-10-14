"""Headless deterministic Episode Debrief closure reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

import click

from app.config.paths import resolve_vault_root
from app.episode_debrief.trigger import run_debrief_tick


@click.group(name="episode-debrief", help="Episode Debrief trigger controls (DEBRIEF-01).")
def episode_debrief_group() -> None:
    pass


@episode_debrief_group.command(name="tick", help="Reconcile eligible closed episodes once.")
@click.option("--vault-root", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def tick(vault_root: Path | None, as_json: bool) -> None:
    summary = run_debrief_tick(vault_root=resolve_vault_root(vault_root))
    if as_json:
        click.echo(json.dumps(summary))
    else:
        click.echo(f"episode-debrief tick: triggered={len(summary['triggered'])} pending={len(summary['pending_debrief'])}")
