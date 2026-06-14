"""CRE-04 proactive attention loop: deterministic reach-out/scarcity gate.

Verifies that a moment fires a reach-out only when its urgency clears the current
context-dependent interruption threshold (else it defers down to the glance
surface, not dropped); that the zero-tolerance floor never pushes; and that a
user-declared pattern changes which moments surface, with a receipt for every
decision and no external side-effects.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.relevance import AttentionLoop, DeclaredPattern, query_reachout_receipts
from app.relevance.schema import (
    Moment,
    MomentNeed,
    MomentProvenance,
    MomentTrigger,
    MomentUrgency,
    SurfacedRef,
    UrgencyBand,
)
from app.vault.manager import VaultContext


def _moment(band: UrgencyBand, *, ref: str = "Projects/Contextual Relevance Engine.md") -> Moment:
    return Moment(
        uuid=uuid4().hex,
        created="2026-06-13T07:00:00Z",
        trigger=MomentTrigger(kind="deadline-approaching", source_ref=ref),
        need=MomentNeed(basis="commitment-risk", summary=f"slipping deadline ({band})"),
        surfaced_refs=[SurfacedRef(ref=ref, why="deadline in 1 day")],
        urgency=MomentUrgency(band=band, basis="test", evaluator="test"),
        provenance=MomentProvenance(produced_by="test", inputs_digest="sha256:test"),
    )


def _ctx(tmp_path: Path) -> VaultContext:
    return VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(tmp_path))


def test_reachout_respects_context_threshold_and_defers(tmp_path: Path) -> None:
    receipts = tmp_path / "reachout.jsonl"
    loop = AttentionLoop(_ctx(tmp_path), outbox_path=receipts)
    moment = _moment("timely")

    # Low load (home) → lower bar → the same moment earns a reach-out.
    [home] = loop.tick(moments=[moment], interruptibility="home")
    assert home.reached_out
    assert home.outcome in ("in_app", "push")

    # High load (deep focus) → higher bar → the same moment defers to the glance
    # surface (re-attempts later), it is not dropped.
    [focus] = loop.tick(moments=[moment], interruptibility="focus")
    assert not focus.reached_out
    assert focus.outcome == "defer"
    assert focus.rung == "glance"

    # A clearly pressing moment at low load climbs to an OS push.
    [pushed] = loop.tick(moments=[_moment("pressing")], interruptibility="home")
    assert pushed.outcome == "push"

    # Every decision left a receipt (reach-out and deliberate deferral alike).
    assert len(query_reachout_receipts(outbox_path=receipts)) == 3


def test_zero_tolerance_floor_never_pushes(tmp_path: Path) -> None:
    receipts = tmp_path / "reachout.jsonl"
    loop = AttentionLoop(_ctx(tmp_path), outbox_path=receipts)
    moment = _moment("critical")  # maximum urgency

    for state in ("sleep", "dnd"):
        [decision] = loop.tick(moments=[moment], interruptibility=state)
        assert decision.outcome == "defer", f"{state} must never push"
        assert decision.rung == "glance"
        assert not decision.reached_out

    rows = query_reachout_receipts(outbox_path=receipts)
    assert len(rows) == 2
    assert all(row["payload"]["reachout"]["zero_tolerance"] is True for row in rows)
    assert all(row["payload"]["reachout"]["outcome"] == "defer" for row in rows)


def test_declared_pattern_changes_surfacing_with_receipts(tmp_path: Path) -> None:
    receipts = tmp_path / "reachout.jsonl"
    loop = AttentionLoop(_ctx(tmp_path), outbox_path=receipts)
    moment = _moment("timely")

    # In deep focus a 'timely' moment is below the bar and defers.
    [without] = loop.tick(moments=[moment], interruptibility="focus")
    assert without.outcome == "defer"

    # A declared pattern that boosts project moments in focus changes the outcome:
    # the same moment now clears the in-app threshold and surfaces.
    pattern = DeclaredPattern(
        name="boost-projects-in-focus",
        when_state="focus",
        match_ref_prefix="Projects/",
        urgency_boost=1,
    )
    [with_pattern] = loop.tick(
        moments=[moment], interruptibility="focus", patterns=[pattern]
    )
    assert with_pattern.reached_out
    assert with_pattern.outcome == "in_app"
    assert "boost-projects-in-focus" in with_pattern.applied_patterns
    assert without.outcome != with_pattern.outcome  # surfacing measurably changed

    # Every reach-out / deliberate suppression emitted a receipt; no external effect.
    rows = query_reachout_receipts(outbox_path=receipts)
    assert len(rows) == 2
    assert all(row["payload"]["external_side_effect"] is False for row in rows)
    assert all(row["payload"]["governance_tier"] == "act" for row in rows)


def test_no_reachout_when_writes_blocked(tmp_path: Path) -> None:
    """Governed by construction: blocked writes defer everything, still receipted."""

    class _BlockedGuard:
        def assert_writes_allowed(self, action: str) -> None:
            from app.write_guard import WritesBlockedError

            raise WritesBlockedError("degraded", "health gate", action)

    receipts = tmp_path / "reachout.jsonl"
    loop = AttentionLoop(_ctx(tmp_path), write_guard=_BlockedGuard(), outbox_path=receipts)
    [decision] = loop.tick(moments=[_moment("critical")], interruptibility="home")
    assert decision.outcome == "defer"
    assert query_reachout_receipts(outbox_path=receipts)
