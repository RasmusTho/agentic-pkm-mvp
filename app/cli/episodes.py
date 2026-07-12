"""CLI entrypoint for the Episode Resolution Engine tick (ERE-04 #3179, ERE-05 #3180,
ERE-06 #3181, ERE-07 #3182).

``python -m app.cli episodes tick`` runs, in order, one deterministic tick of:

1. :func:`app.episodes.segmenter.run_segmentation_tick` -- consumes deltas from every live
   registered stream, folds them into per-scope open segments, emits any newly-closed segment
   as a ``segmentation: proposed`` Episode note, assigns pending episode_ref bindings to
   in-bounds artifacts (ERE-05), and closes any quiesced open episode -- flipping ``time.closed``
   and emitting ``episode.closed`` (ERE-06).
2. :func:`app.episodes.recut.run_recut_tick` -- detects operator edits to episode notes
   (``segmentation: re-cut``), applies acceptance-by-silence, and reconciles artifact bindings
   (ERE-07).

Running both in the same tick means a freshly-emitted proposal is picked up by the re-cut
tick's baseline tracking immediately, not on some later invocation. Not a daemon (spec: "runs
as a deterministic tick ... not a daemon"); a caller schedules repeated invocations the same
way other watcher-tick-style commands are scheduled.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from app.episodes.recut import run_recut_tick
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
    recut_summary = run_recut_tick(vault_root=root)
    summary.update(recut_summary)
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False))
    else:
        click.echo(
            "episodes tick: consumed="
            f"{summary['consumed']} proposed={len(summary['proposed'])} open_segments={summary['open_segments']} "
            f"closed={summary.get('closed', [])} events_emitted={summary.get('events_emitted', 0)} "
            f"degraded={summary.get('degraded', [])} "
            f"recut_detected={recut_summary['recut_detected']} accepted={recut_summary['accepted']} "
            f"bindings_corrected={recut_summary['bindings_corrected']}"
        )


__all__ = ["episodes_group"]
