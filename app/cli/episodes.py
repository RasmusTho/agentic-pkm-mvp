"""CLI entrypoint for the Episode Resolution Engine segmentation tick (ERE-04, #3179).

``python -m app.cli episodes tick`` runs one deterministic tick of
:func:`app.episodes.segmenter.run_segmentation_tick` -- consumes deltas from
every live registered stream, folds them into per-scope open segments, and
emits any newly-closed segment as a ``segmentation: proposed`` Episode note.
Not a daemon (spec: "runs as a deterministic tick ... not a daemon"); a
caller schedules repeated invocations the same way other watcher-tick-style
commands are scheduled.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from app.episodes.segmenter import run_segmentation_tick

_VAULT_ROOT_ENV_CANDIDATES = ("EPISODES_VAULT_ROOT", "WATCHER_VAULT_PATH", "VAULT_ROOT")


def _default_vault_root() -> str:
    for env_name in _VAULT_ROOT_ENV_CANDIDATES:
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()
    return "vault"


@click.group(name="episodes", help="Episode Resolution Engine controls (ERE-04+).")
def episodes_group() -> None:
    ...


@episodes_group.command(name="tick", help="Run one deterministic segmentation tick.")
@click.option(
    "--vault-root",
    type=click.Path(),
    default=None,
    help=f"Vault root to run against. Defaults to the first set of {_VAULT_ROOT_ENV_CANDIDATES}, else 'vault'.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit the tick summary as JSON.")
def tick(vault_root: str | None, as_json: bool) -> None:
    root = Path(vault_root) if vault_root else Path(_default_vault_root())
    summary = run_segmentation_tick(vault_root=root)
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False))
    else:
        click.echo(
            "episodes tick: consumed="
            f"{summary['consumed']} proposed={len(summary['proposed'])} open_segments={summary['open_segments']} "
            f"degraded={summary.get('degraded', [])}"
        )


__all__ = ["episodes_group"]
