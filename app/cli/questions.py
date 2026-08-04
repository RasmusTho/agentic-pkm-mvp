"""Standing Questions CLI (SQ-03, #4610).

`questions match-evidence` is the production invocation of the Heimdal
observation-log evidence tick -- the same operational shape as
`episodes tick` for the Episode Resolution Engine, which consumes the same
log through its own cursor. The vault-ingest and KAP completion paths need no
command here: the outbox worker's own topic handlers invoke the matcher
inline as events dispatch.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import click

from app.standing_questions.ingest_consumers import run_heimdal_evidence_matching_tick

_VAULT_ROOT_ENV_CANDIDATES = ("WATCHER_VAULT_PATH", "VAULT_ROOT")


def _default_vault_root() -> str:
    for env_name in _VAULT_ROOT_ENV_CANDIDATES:
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()
    return "vault"


@click.group(name="questions", help="Standing Questions controls (SQ-01+).")
def questions_group() -> None:
    ...


@questions_group.command(
    name="match-evidence",
    help="Run one standing-question evidence-matching tick over unread Heimdal observations.",
)
@click.option(
    "--vault-root",
    type=click.Path(),
    default=None,
    help=f"Vault root to run against. Defaults to the first set of {_VAULT_ROOT_ENV_CANDIDATES}, else 'vault'.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Maximum observations to consume this tick (default: all unread).",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit the tick summary as JSON.")
def match_evidence(vault_root: str | None, limit: int | None, as_json: bool) -> None:
    root = Path(vault_root) if vault_root else Path(_default_vault_root())
    summary = run_heimdal_evidence_matching_tick(vault_root=root, limit=limit)
    if as_json:
        click.echo(json.dumps(asdict(summary), ensure_ascii=False))
    else:
        click.echo(
            "questions match-evidence: "
            f"evaluated_pairs={summary.evaluated_pairs} attached={summary.attached} "
            f"below_threshold={summary.below_threshold} degraded={summary.degraded} "
            f"excluded_cross_scope={summary.excluded_cross_scope} "
            f"excluded_non_open={summary.excluded_non_open} "
            f"unresolved_artifact={summary.unresolved_artifact}"
        )
