"""The proactive attention loop — the genuinely new dimension: proactivity.

On a context tick, the loop evaluates candidate moments and decides whether to
reach out, applying the deterministic reach-out/scarcity gate of
``docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md``: a moment climbs the
intrusiveness ladder only as far as its urgency clears the current
context-dependent interruption threshold; at the zero-tolerance floor (sleep /
declared DND) nothing pushes; below threshold a moment **defers** down to the
glance surface and re-attempts (it is never dropped). User-declared patterns are
soft guidance. Every reach-out and every deliberate suppression emits a receipt;
there are no external side-effects in this slice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence
from uuid import uuid4

from app.relevance.interruptibility import InterruptibilityThreshold, coerce_threshold
from app.relevance.patterns import DeclaredPattern, apply_patterns
from app.relevance.schema import Moment, UrgencyBand, urgency_rank
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

REACHOUT_ACTION = "moment.reachout"
REACHOUT_SOURCE = "relevance.attention_loop"
REACHOUT_EVENT = "moment.reachout"
DEFAULT_REACHOUT_RECEIPTS_PATH = Path("runtime/relevance/reachout_receipts.jsonl")

ReachOutcome = Literal["push", "in_app", "defer"]
# Ladder rung the moment ended up on. "glance" is the always-available pull floor
# a deferred moment waits on; it is never an interruption.
ReachRung = Literal["os_push", "in_app_nudge", "glance"]


@dataclass(frozen=True)
class ReachOutDecision:
    moment_uuid: str
    outcome: ReachOutcome
    rung: ReachRung
    urgency_band: UrgencyBand
    effective_band: UrgencyBand
    interruptibility_state: str
    applied_patterns: tuple[str, ...]
    reason: str
    receipt_id: str

    @property
    def reached_out(self) -> bool:
        return self.outcome in ("push", "in_app")


def decide_reachout(
    effective_band: UrgencyBand,
    threshold: InterruptibilityThreshold,
    *,
    suppressed: bool = False,
    writes_blocked: bool = False,
) -> tuple[ReachOutcome, ReachRung, str]:
    """Deterministically decide the reach-out outcome for a moment."""

    if threshold.zero_tolerance:
        return "defer", "glance", "zero-tolerance floor (sleep / declared DND) — never push"
    if writes_blocked:
        return "defer", "glance", "writes blocked by the health gate — deferred to glance"
    if suppressed:
        return "defer", "glance", "suppressed by a declared pattern — deferred to glance"
    rank = urgency_rank(effective_band)
    if threshold.push_min is not None and rank >= urgency_rank(threshold.push_min):
        return "push", "os_push", "urgency cleared the OS-push threshold"
    if threshold.in_app_min is not None and rank >= urgency_rank(threshold.in_app_min):
        return "in_app", "in_app_nudge", "urgency cleared the in-app threshold"
    return (
        "defer",
        "glance",
        "below the interruption threshold — deferred to the glance surface (not dropped)",
    )


class AttentionLoop:
    """Evaluate candidate moments for proactive surfacing on a context tick."""

    def __init__(
        self,
        vault_context: VaultContext,
        *,
        write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
        outbox_path: Path | None = None,
    ) -> None:
        self.vault_context = vault_context
        self.write_guard = write_guard
        self.outbox_path = outbox_path

    def tick(
        self,
        *,
        moments: Sequence[Moment],
        interruptibility: str | InterruptibilityThreshold | None,
        patterns: Sequence[DeclaredPattern] = (),
    ) -> list[ReachOutDecision]:
        """Run one context tick: gate each moment, emit receipts, return decisions."""

        threshold = coerce_threshold(interruptibility)
        # Governed by construction: if durable writes are blocked, the loop reaches
        # out to no one and records the deliberate suppression for accountability.
        try:
            self.write_guard.assert_writes_allowed(REACHOUT_ACTION)
            writes_blocked = False
        except WritesBlockedError:
            writes_blocked = True

        pattern_tuple = tuple(patterns)
        latest_by_moment = _latest_reachout_by_moment(outbox_path=self.outbox_path)
        decisions: list[ReachOutDecision] = []
        for moment in moments:
            effect = apply_patterns(moment, pattern_tuple, threshold.state)
            outcome, rung, reason = decide_reachout(
                effect.effective_band,
                threshold,
                suppressed=effect.suppressed,
                writes_blocked=writes_blocked,
            )
            if _matches_latest_reachout(
                latest_by_moment.get(moment.uuid),
                outcome=outcome,
                rung=rung,
                threshold_state=threshold.state,
                effective_band=effect.effective_band,
                applied=effect.applied,
                reason=reason,
            ):
                continue
            receipt_id = self._emit_reachout_receipt(
                moment=moment,
                outcome=outcome,
                rung=rung,
                threshold=threshold,
                effective_band=effect.effective_band,
                applied=effect.applied,
                reason=reason,
            )
            latest_by_moment[moment.uuid] = {
                "outcome": outcome,
                "rung": rung,
                "interruptibility_state": threshold.state,
                "effective_band": effect.effective_band,
                "applied_patterns": list(effect.applied),
                "reason": reason,
            }
            decisions.append(
                ReachOutDecision(
                    moment_uuid=moment.uuid,
                    outcome=outcome,
                    rung=rung,
                    urgency_band=moment.urgency.band,
                    effective_band=effect.effective_band,
                    interruptibility_state=threshold.state,
                    applied_patterns=effect.applied,
                    reason=reason,
                    receipt_id=receipt_id,
                )
            )
        return decisions

    def _emit_reachout_receipt(
        self,
        *,
        moment: Moment,
        outcome: ReachOutcome,
        rung: ReachRung,
        threshold: InterruptibilityThreshold,
        effective_band: UrgencyBand,
        applied: tuple[str, ...],
        reason: str,
    ) -> str:
        receipt_id = uuid4().hex
        trace_id = uuid4().hex
        timestamp = _iso(datetime.now(timezone.utc))
        # Reach-out is Act-tier (reversible, vault-internal, no external effect)
        # per #1881; a deliberate suppression is equally accountable.
        receipt: dict[str, Any] = {
            "action_taken": REACHOUT_ACTION,
            "outcome": outcome,
            "timestamp": timestamp,
            "message": (
                f"moment '{moment.need.summary}' ({moment.urgency.band}"
                f"->{effective_band}) -> {rung}: {reason}"
            ),
            "inverse_action": None,
        }
        payload: dict[str, Any] = {
            "receipt_id": receipt_id,
            "trace_id": trace_id,
            "vault_id": self.vault_context.active_vault_id,
            "moment_uuid": moment.uuid,
            "governance_tier": "act",
            "external_side_effect": False,
            "reachout": {
                "outcome": outcome,
                "rung": rung,
                "interruptibility_state": threshold.state,
                "zero_tolerance": threshold.zero_tolerance,
                "urgency_band": moment.urgency.band,
                "effective_band": effective_band,
                "applied_patterns": list(applied),
                "reason": reason,
            },
            "receipt": receipt,
        }
        record: dict[str, Any] = {
            "event": REACHOUT_EVENT,
            "event_id": receipt_id,
            "trace_id": trace_id,
            "source": REACHOUT_SOURCE,
            "timestamp": timestamp,
            "payload": payload,
        }
        path = self.outbox_path or DEFAULT_REACHOUT_RECEIPTS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        return receipt_id


def query_reachout_receipts(
    *,
    outbox_path: Path | None = None,
    moment_uuid: str | None = None,
) -> list[dict]:
    """Read back the reach-out / suppression receipts (accountability projection)."""

    path = outbox_path or DEFAULT_REACHOUT_RECEIPTS_PATH
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") != REACHOUT_EVENT:
            continue
        if moment_uuid is not None and (record.get("payload") or {}).get("moment_uuid") != moment_uuid:
            continue
        rows.append(record)
    return rows


def _latest_reachout_by_moment(*, outbox_path: Path | None) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in query_reachout_receipts(outbox_path=outbox_path):
        payload = record.get("payload") or {}
        reachout = payload.get("reachout") or {}
        moment_uuid = payload.get("moment_uuid")
        if isinstance(moment_uuid, str) and isinstance(reachout, dict):
            latest[moment_uuid] = reachout
    return latest


def _matches_latest_reachout(
    latest: dict[str, Any] | None,
    *,
    outcome: ReachOutcome,
    rung: ReachRung,
    threshold_state: str,
    effective_band: UrgencyBand,
    applied: tuple[str, ...],
    reason: str,
) -> bool:
    if latest is None:
        return False
    return (
        latest.get("outcome") == outcome
        and latest.get("rung") == rung
        and latest.get("interruptibility_state") == threshold_state
        and latest.get("effective_band") == effective_band
        and tuple(latest.get("applied_patterns") or ()) == applied
        and latest.get("reason") == reason
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "AttentionLoop",
    "ReachOutDecision",
    "decide_reachout",
    "query_reachout_receipts",
    "REACHOUT_EVENT",
    "REACHOUT_ACTION",
]
