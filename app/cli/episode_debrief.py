"""Headless deterministic Episode Debrief closure reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

import click

from app.cli.vault_context import CliVaultContextError, resolve_cli_vault_context
from app.episode_debrief.trigger import run_debrief_tick


@click.group(name="episode-debrief", help="Episode Debrief trigger controls (DEBRIEF-01).")
def episode_debrief_group() -> None:
    pass


@episode_debrief_group.command(name="tick", help="Reconcile eligible closed episodes once.")
@click.option("--vault-root", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def tick(vault_root: Path | None, as_json: bool) -> None:
    try:
        carrier = resolve_cli_vault_context(vault_root, env_policy="channel")
    except CliVaultContextError as exc:
        raise click.ClickException(str(exc)) from exc
    if carrier.root is None:
        # A bound instance registry selected no vault; never guess a root.
        raise click.ClickException("no vault is selected: pass --vault-root or set an instance default vault")
    summary = run_debrief_tick(vault_root=carrier.root)
    if as_json:
        click.echo(json.dumps(summary))
    else:
        click.echo(f"episode-debrief tick: triggered={len(summary['triggered'])} pending={len(summary['pending_debrief'])}")


@episode_debrief_group.command(name="synthesize", help="Replay the durable trigger for one Episode.")
@click.option("--episode", required=True)
@click.option("--vault-root", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
def synthesize(episode: str, vault_root: Path | None, as_json: bool) -> None:
    from app.episode_debrief.synthesis import synthesize_episode
    try:
        carrier = resolve_cli_vault_context(vault_root, env_policy="channel")
        if carrier.root is None:
            raise click.ClickException("no vault is selected")
        report = synthesize_episode(episode, vault_root=carrier.root)
    except (CliVaultContextError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report) if as_json else f"episode-debrief synthesize: {report['status']}")
    if report["status"] == "blocked":
        raise click.ClickException("debrief activation blocked: " + ", ".join(report["reasons"]))
