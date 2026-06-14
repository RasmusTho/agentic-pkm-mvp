"""Governed relevance tick — runs the Contextual Relevance Engine on a context tick.

This is the runtime hook (slice 1 of #1958) that makes `app/relevance/` actually
run: on a watcher tick it computes moments from vault-native data and materializes
them through the WriteGuard with receipts, then runs the proactive attention loop
over the freshly materialized moments. It is isolated from the watcher core so the
watcher's main loop never depends on relevance internals, and it is gated behind a
flag (on by default — materialization and in-app reach-out decisions are Act-tier,
reversible, vault-internal). It performs no OS notification delivery and no
external side-effect.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.relevance.attention_loop import AttentionLoop
from app.relevance.evaluator import DeterministicRelevanceEvaluator
from app.relevance.interruptibility import InterruptibilityThreshold
from app.relevance.materialization import materialize_moment
from app.relevance.patterns import DeclaredPattern
from app.relevance.schema import Moment
from app.vault.manager import VaultContext, get_vault_manager

RELEVANCE_TICK_FLAG = "RELEVANCE_TICK_ENABLED"
RELEVANCE_INTERRUPTIBILITY_ENV = "RELEVANCE_INTERRUPTIBILITY"
RELEVANCE_DECLARED_PATTERNS_ENV = "RELEVANCE_DECLARED_PATTERNS_JSON"


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
    reachout_outbox_path: Path | None = None,
    interruptibility: str | InterruptibilityThreshold | None = None,
    patterns: Sequence[DeclaredPattern] | None = None,
) -> dict[str, object]:
    """Compute and materialize moments, then run governed reach-out decisions.

    Returns a summary dict. Never raises for a not-selected vault — it skips.
    """

    root = Path(vault_root).expanduser()
    context = vault_context or _resolve_context(root)
    if context is None or context.status != "selected" or not context.active_vault_path:
        return {"materialized": 0, "moment_ids": [], "skipped": "vault-not-selected"}

    moments = DeterministicRelevanceEvaluator(root).evaluate()
    materialized: list[str] = []
    materialized_moments: list[Moment] = []
    for moment in moments:
        result = materialize_moment(moment, vault_context=context, outbox_path=outbox_path)
        if result.status == "materialized":
            materialized.append(result.moment_uuid)
            materialized_moments.append(moment)

    current_interruptibility = (
        interruptibility if interruptibility is not None else os.getenv(RELEVANCE_INTERRUPTIBILITY_ENV)
    )
    declared_patterns = (
        tuple(patterns)
        if patterns is not None
        else _declared_patterns_from_env(os.getenv(RELEVANCE_DECLARED_PATTERNS_ENV))
    )
    decisions = AttentionLoop(context, outbox_path=reachout_outbox_path).tick(
        moments=materialized_moments,
        interruptibility=current_interruptibility,
        patterns=declared_patterns,
    )
    return {
        "materialized": len(materialized),
        "moment_ids": materialized,
        "reachout_decisions": len(decisions),
        "in_app_nudges": sum(1 for decision in decisions if decision.outcome == "in_app"),
        "push_candidates": sum(1 for decision in decisions if decision.outcome == "push"),
        "deferred": sum(1 for decision in decisions if decision.outcome == "defer"),
    }


def _resolve_context(root: Path) -> VaultContext | None:
    try:
        return get_vault_manager().validate_vault(root)
    except Exception:
        return None


def _declared_patterns_from_env(raw: str | None) -> tuple[DeclaredPattern, ...]:
    """Parse optional user-declared reach-out patterns from runtime config."""

    if not raw or not raw.strip():
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    items = [parsed] if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return ()

    patterns: list[DeclaredPattern] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            patterns.append(DeclaredPattern(**_declared_pattern_kwargs(item)))
        except (TypeError, ValueError):
            continue
    return tuple(patterns)


def _declared_pattern_kwargs(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "name",
        "when_state",
        "match_trigger_kind",
        "match_ref_prefix",
        "urgency_boost",
        "suppress",
    }
    return {key: value for key, value in item.items() if key in allowed}


__all__ = [
    "RELEVANCE_TICK_FLAG",
    "RELEVANCE_INTERRUPTIBILITY_ENV",
    "RELEVANCE_DECLARED_PATTERNS_ENV",
    "relevance_tick_enabled",
    "run_relevance_tick",
]
