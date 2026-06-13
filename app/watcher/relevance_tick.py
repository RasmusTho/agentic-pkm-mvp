"""Governed relevance tick — runs the Contextual Relevance Engine on a context tick.

This is the runtime hook (slice 1 of #1958) that makes `app/relevance/` actually
run: on a watcher tick it computes moments from vault-native data and materializes
them through the WriteGuard with receipts. It is isolated from the watcher core so
the watcher's main loop never depends on relevance internals, and it is gated
behind a flag (on by default — materialization is Act-tier, reversible,
vault-internal). It performs no proactive reach-out (that is CRE-04 / #1881, a
separate slice); this only computes + materializes for the pull-only glance surface.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.relevance import DeterministicRelevanceEvaluator, materialize_moment
from app.vault.manager import VaultContext, get_vault_manager

RELEVANCE_TICK_FLAG = "RELEVANCE_TICK_ENABLED"


def relevance_tick_enabled() -> bool:
    """Whether the relevance tick runs. On by default; set the flag to 0 to disable."""

    raw = os.getenv(RELEVANCE_TICK_FLAG)
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def run_relevance_tick(
    vault_root: Path | str,
    *,
    vault_context: VaultContext | None = None,
    outbox_path: Path | None = None,
) -> dict[str, object]:
    """Compute moments from vault-native data and materialize them (governed).

    Returns a summary dict. Never raises for a not-selected vault — it skips.
    """

    root = Path(vault_root).expanduser()
    context = vault_context or _resolve_context(root)
    if context is None or context.status != "selected" or not context.active_vault_path:
        return {"materialized": 0, "moment_ids": [], "skipped": "vault-not-selected"}

    moments = DeterministicRelevanceEvaluator(root).evaluate()
    materialized: list[str] = []
    for moment in moments:
        result = materialize_moment(moment, vault_context=context, outbox_path=outbox_path)
        if result.status == "materialized":
            materialized.append(result.moment_uuid)
    return {"materialized": len(materialized), "moment_ids": materialized}


def _resolve_context(root: Path) -> VaultContext | None:
    try:
        return get_vault_manager().validate_vault(root)
    except Exception:
        return None


__all__ = ["RELEVANCE_TICK_FLAG", "relevance_tick_enabled", "run_relevance_tick"]
