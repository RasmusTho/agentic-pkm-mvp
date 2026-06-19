"""Regression for #2191: deferred lifecycle survives no-new-receipt (dedup) ticks.

The proactive attention loop re-materializes a moment on every context tick from a
*fresh* ``Moment`` object whose lifecycle defaults to ``proposed`` (see
``app/watcher/relevance_tick.py`` — ``materialize_moment`` runs before the loop).
On the first defer tick the loop persists a durable ``deferred`` lifecycle. On a
subsequent tick with identical inputs the reach-out receipt is *deduped* (the loop
``continue``s without emitting a new receipt), but the artifact has already been
re-materialized back to ``proposed`` by the pre-loop materialization step.

Before the fix, ``_persist_deferred_lifecycle`` ran only *after* the dedup
``continue``, so on dedup ticks the artifact regressed to ``proposed`` and stayed
there. This test drives the production tick shape (re-materialize a fresh moment,
then run the loop) across multiple ticks and asserts the materialized artifact
lifecycle stays ``deferred``.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.relevance.attention_loop import AttentionLoop, query_reachout_receipts
from app.relevance.materialization import materialize_moment
from app.relevance.now_surface import collect_now_moments
from app.relevance.schema import (
    Moment,
    MomentNeed,
    MomentProvenance,
    MomentTrigger,
    MomentUrgency,
    SurfacedRef,
)
from app.vault.manager import VaultContext

_STABLE_UUID = uuid4().hex
_REF = "Projects/Contextual Relevance Engine.md"


def _fresh_proposed_moment() -> Moment:
    """A fresh moment as the evaluator yields each tick: stable uuid, ``proposed``.

    Re-built every tick so its in-memory lifecycle defaults back to ``proposed`` —
    exactly what ``DeterministicRelevanceEvaluator.evaluate()`` produces and what
    ``materialize_moment`` would then overwrite the on-disk artifact with.
    """

    return Moment(
        uuid=_STABLE_UUID,
        created="2026-06-13T07:00:00Z",
        trigger=MomentTrigger(kind="deadline-approaching", source_ref=_REF),
        need=MomentNeed(basis="commitment-risk", summary="slipping deadline (timely)"),
        surfaced_refs=[SurfacedRef(ref=_REF, why="deadline in 1 day")],
        urgency=MomentUrgency(band="timely", basis="test", evaluator="test"),
        provenance=MomentProvenance(produced_by="test", inputs_digest="sha256:test"),
    )


def _ctx(vault: Path) -> VaultContext:
    return VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(vault))


def _run_tick(ctx: VaultContext, *, moment_outbox: Path, reachout_outbox: Path) -> None:
    """One production-shaped tick: materialize a fresh moment, then run the loop.

    Mirrors ``run_relevance_tick``: re-materialize the (freshly ``proposed``)
    moment first, then run ``AttentionLoop.tick`` over the materialized moment.
    """

    moment = _fresh_proposed_moment()
    materialize_moment(moment, vault_context=ctx, outbox_path=moment_outbox)
    AttentionLoop(
        ctx,
        outbox_path=reachout_outbox,
        moment_outbox_path=moment_outbox,
    ).tick(moments=[moment], interruptibility="focus")


def test_deferred_lifecycle_survives_dedup_ticks(tmp_path: Path) -> None:
    """Across repeated dedup ticks the artifact lifecycle stays ``deferred``."""

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    ctx = _ctx(vault)
    moment_outbox = tmp_path / "moment.jsonl"
    reachout_outbox = tmp_path / "reachout.jsonl"

    # Tick 1: deep focus -> a "timely" moment defers; lifecycle persisted as deferred.
    _run_tick(ctx, moment_outbox=moment_outbox, reachout_outbox=reachout_outbox)
    after_first = collect_now_moments(ctx)
    assert after_first and after_first[0]["moment_id"] == _STABLE_UUID
    assert after_first[0]["lifecycle"] == "deferred"
    receipts_after_first = len(query_reachout_receipts(outbox_path=reachout_outbox))
    assert receipts_after_first == 1

    # Ticks 2 and 3: identical inputs -> reach-out receipt is deduped (no new
    # receipt), but the artifact was just re-materialized to ``proposed`` by the
    # pre-loop materialization. The lifecycle must be re-applied so it stays
    # ``deferred`` instead of regressing.
    for _ in range(2):
        _run_tick(ctx, moment_outbox=moment_outbox, reachout_outbox=reachout_outbox)
        views = collect_now_moments(ctx)
        assert views and views[0]["moment_id"] == _STABLE_UUID
        assert views[0]["lifecycle"] == "deferred", "deferred lifecycle regressed on a dedup tick"

    # The receipt was genuinely deduped across the extra ticks (no churn): the
    # fix must not re-emit reach-out receipts, only re-apply the durable lifecycle.
    assert len(query_reachout_receipts(outbox_path=reachout_outbox)) == receipts_after_first
