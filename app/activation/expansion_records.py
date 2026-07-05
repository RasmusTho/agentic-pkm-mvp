"""Expansion Activation Gate records for Connect + Create (EXP-6, #2998).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §4;
``docs/EMERGENT_FEATURES_MODEL.md :: Expansion Activation Gate``. Parent:
#2980 (Capability Hardening / Cognitive Expansion).

This module owns the activation-gate RECORD for the two Expansion capability
contracts named in the spec (§1.3, §2.6): ``connection_proposal`` (Connect,
EXP-1..EXP-2/EXP-5's cluster handoff) and ``synthesis_note_proposal`` (Create,
EXP-3/EXP-4/EXP-5's digest kind). It does not re-implement the deterministic
gate function itself (:mod:`app.activation.gate`) or either capability's own
per-invocation posture declaration (:func:`app.expansion.create.build_create_activation_posture`
already declares Create's posture per-kind) -- it is the STATUS-LADDER-FACING
record layer: one canonical posture per capability, an evaluation entry
point, and a durable activation receipt, mirroring
:mod:`app.activation.ask_synthesis`'s shape (the first proof case through
this same gate).

Hard invariants held by this module (do not relax without an owner-ratified
ADR, mirroring ``app.activation.ask_synthesis``'s and ``app.activation.gate``'s
posture):

- **The gate stays deterministic.** :func:`evaluate_connection_proposal_activation`
  and :func:`evaluate_synthesis_note_proposal_activation` are pure calls into
  :func:`app.activation.gate.evaluate_activation` -- no model output, no
  heuristic, and no runtime signal other than the declared posture inputs
  decides the outcome (``expansion_requires_activation_record``).
- **A regressed precondition is blocked-with-reason, never a silent run.**
  Withdrawing ``admissibility_declared`` or ``loop_precondition_green`` on
  either capability's posture makes ``evaluate_activation`` return
  ``activatable=False`` with a structured reason -- there is no third
  "activate anyway" path anywhere in this module or in the gate it calls.
- **Receipts are durable and inspectable**, mirroring
  :func:`app.activation.ask_synthesis.emit_ask_synthesis_receipt`'s jsonl
  append-only shape: one line per evaluation, capability id, outcome, blocked
  reasons, and the admitted artifact ids -- never any note content or span
  text (activation records are governance metadata, not knowledge).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from app.activation.gate import (
    ActivationDecision,
    ActivationPosture,
    CandidateContext,
    ConsumingAuthority,
    evaluate_activation,
)

# Capability identifiers -- these are the exact names the spec's capability
# contracts declare (§1.3 "Name `connection_proposal`", §2.6 "Name
# `synthesis_note_proposal`") and the exact strings the `docs/STATUS.md`
# Expansion ladder rows key on.
CONNECTION_PROPOSAL_CAPABILITY_ID = "connection_proposal"
SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID = "synthesis_note_proposal"

# Scope tokens for the read-side admissibility evaluation -- same-scope vault
# material admits; both capabilities are `proposal` authority (spec §4: "one
# step above ASK's read-only proof, still below governed execution").
CONNECTION_PROPOSAL_SCOPE = "expansion.connect.candidates"
SYNTHESIS_NOTE_PROPOSAL_SCOPE = "expansion.create.staging"

EXPANSION_GATE_RECEIPT_EVENT = "activation.expansion.gate_record"
EXPANSION_GATE_RECEIPT_SOURCE = "app.activation.expansion_records"

DEFAULT_RECEIPTS_PATH = Path("runtime/activation/expansion_gate_receipts.jsonl")


def _receipt_path() -> Path:
    configured = os.getenv("EXPANSION_GATE_RECEIPTS_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_RECEIPTS_PATH


def build_connection_proposal_posture(
    *,
    admissibility_declared: bool = True,
    loop_precondition_green: bool = True,
    observable: bool = True,
) -> ActivationPosture:
    """Declare the ``proposal``-authority activation posture for Connect
    (``connection_proposal``, spec §1.3).

    Connect's own write side effect is a propose-track panel checkbox
    (``app.curation.proposal_writer``, Git-reversible, never a canonical
    write), so ``reversible_write_path`` is True. The keyword overrides exist
    ONLY so tests can exercise a regressed precondition against this exact
    posture (mirrors ``app.expansion.create.build_create_activation_posture``'s
    shape) -- production call sites use the defaults, which declare every
    gate input green.
    """

    return ActivationPosture(
        capability_id=CONNECTION_PROPOSAL_CAPABILITY_ID,
        declared_authority=ConsumingAuthority.PROPOSAL,
        admissibility_declared=admissibility_declared,
        loop_precondition_green=loop_precondition_green,
        reversible_write_path=True,
        observable=observable,
        scope=CONNECTION_PROPOSAL_SCOPE,
    )


def build_synthesis_note_proposal_posture(
    *,
    admissibility_declared: bool = True,
    loop_precondition_green: bool = True,
    observable: bool = True,
) -> ActivationPosture:
    """Declare the ``proposal``-authority activation posture for Create
    (``synthesis_note_proposal``, spec §2.6) at the STATUS-LADDER level.

    Mirrors ``app.expansion.create.build_create_activation_posture`` exactly
    (same authority, same reversible-write declaration, same scope family) --
    this is the capability-level record the ladder consults, not a
    per-kind/per-invocation duplicate of Create's own posture declaration.
    """

    return ActivationPosture(
        capability_id=SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID,
        declared_authority=ConsumingAuthority.PROPOSAL,
        admissibility_declared=admissibility_declared,
        loop_precondition_green=loop_precondition_green,
        reversible_write_path=True,
        observable=observable,
        scope=SYNTHESIS_NOTE_PROPOSAL_SCOPE,
    )


def _build_candidates(source_ids: Iterable[str], *, scope: str) -> list[CandidateContext]:
    """Build read-side candidate contexts for the gate's admissibility check.

    ``review_state=ReviewState.REVIEWED`` mirrors
    ``app.expansion.create.build_create_candidates``'s default exactly: each
    admitted vault source note is declared as the reviewed source itself
    (not an unreviewed/raw candidate), which is what admits at the
    ``CITED_PROPOSAL`` tier this module's ``PROPOSAL``-authority postures
    require -- an unset review state would fall through to the gate's
    "unverifiable provenance" floor (``READ`` only) and every evaluation
    would spuriously report ``no_admissible_context`` regardless of the
    posture's own inputs.
    """
    from app.agent_memory.candidate import ReviewState

    candidates: list[CandidateContext] = []
    for source_id in source_ids:
        artifact_id = str(source_id or "").strip()
        if not artifact_id:
            continue
        candidates.append(
            CandidateContext(
                artifact_id=artifact_id,
                sphere=scope,
                is_memory=False,
                has_provenance=True,
                review_state=ReviewState.REVIEWED,
            )
        )
    return candidates


def evaluate_connection_proposal_activation(
    source_ids: Iterable[str],
    *,
    posture: ActivationPosture | None = None,
    receipt_id: str | None = None,
    now: datetime | None = None,
) -> ActivationDecision:
    """Evaluate the gate decision for the Connect (``connection_proposal``)
    activation record. ``posture`` defaults to the green production posture;
    a caller may supply a regressed posture (e.g. via
    :func:`build_connection_proposal_posture` overrides) to prove
    blocked-with-reason behavior."""

    resolved_posture = posture or build_connection_proposal_posture()
    candidates = _build_candidates(source_ids, scope=resolved_posture.scope or CONNECTION_PROPOSAL_SCOPE)
    return evaluate_activation(resolved_posture, candidates, receipt_id=receipt_id, now=now)


def evaluate_synthesis_note_proposal_activation(
    source_ids: Iterable[str],
    *,
    posture: ActivationPosture | None = None,
    receipt_id: str | None = None,
    now: datetime | None = None,
) -> ActivationDecision:
    """Evaluate the gate decision for the Create (``synthesis_note_proposal``)
    activation record. ``posture`` defaults to the green production posture;
    a caller may supply a regressed posture to prove blocked-with-reason
    behavior."""

    resolved_posture = posture or build_synthesis_note_proposal_posture()
    candidates = _build_candidates(
        source_ids, scope=resolved_posture.scope or SYNTHESIS_NOTE_PROPOSAL_SCOPE
    )
    return evaluate_activation(resolved_posture, candidates, receipt_id=receipt_id, now=now)


def emit_expansion_gate_receipt(
    decision: ActivationDecision,
    *,
    receipt_path: Path | None = None,
) -> str:
    """Emit a durable, provenance-bearing activation-gate receipt.

    Mirrors :func:`app.activation.ask_synthesis.emit_ask_synthesis_receipt`'s
    append-only jsonl shape. Carries the capability id, outcome, blocked
    reasons, and admitted artifact ids -- never note content or span text
    (governance metadata only, never knowledge).
    """

    path = receipt_path or _receipt_path()
    receipt = decision.receipt
    record = {
        "event": EXPANSION_GATE_RECEIPT_EVENT,
        "event_id": receipt.receipt_id,
        "trace_id": uuid4().hex,
        "source": EXPANSION_GATE_RECEIPT_SOURCE,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": {
            "capability_id": decision.capability_id,
            "consuming_authority": receipt.consuming_authority.value,
            "outcome": receipt.outcome,
            "activatable": decision.activatable,
            "blocked_reasons": list(decision.blocked_reasons),
            "admitted_artifact_ids": list(decision.admitted_artifact_ids),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return receipt.receipt_id


__all__ = [
    "CONNECTION_PROPOSAL_CAPABILITY_ID",
    "CONNECTION_PROPOSAL_SCOPE",
    "EXPANSION_GATE_RECEIPT_EVENT",
    "SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID",
    "SYNTHESIS_NOTE_PROPOSAL_SCOPE",
    "build_connection_proposal_posture",
    "build_synthesis_note_proposal_posture",
    "emit_expansion_gate_receipt",
    "evaluate_connection_proposal_activation",
    "evaluate_synthesis_note_proposal_activation",
]
