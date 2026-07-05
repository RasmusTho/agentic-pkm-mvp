"""#2998 (EXP-6) -- activation-gate records for `connection_proposal` and
`synthesis_note_proposal`.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §4, §5.

Covers the issue's third Acceptance Criterion:

- Activation-gate records exist for both `connection_proposal` and
  `synthesis_note_proposal`, and a regressed precondition yields a
  blocked-with-reason record, not a silent run.

Mirrors ``tests/activation/test_activation_gate.py``'s explicit,
never-closed-on-green style: every green path and every regressed-input path
is asserted directly against the real
:mod:`app.activation.expansion_records` module, not a stub.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.activation.expansion_records import (
    CONNECTION_PROPOSAL_CAPABILITY_ID,
    EXPANSION_GATE_RECEIPT_EVENT,
    SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID,
    build_connection_proposal_posture,
    build_synthesis_note_proposal_posture,
    emit_expansion_gate_receipt,
    evaluate_connection_proposal_activation,
    evaluate_synthesis_note_proposal_activation,
)
from app.activation.gate import (
    REASON_ADMISSIBILITY_UNDECLARED,
    REASON_LOOP_PRECONDITION_NOT_GREEN,
    REASON_NOT_OBSERVABLE,
)


def _outbox_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Records exist for both capabilities, green path
# ---------------------------------------------------------------------------


def test_connection_proposal_record_exists_and_is_activatable_green() -> None:
    decision = evaluate_connection_proposal_activation(["note-a", "note-b"])
    assert decision.capability_id == CONNECTION_PROPOSAL_CAPABILITY_ID
    assert decision.activatable is True
    assert decision.blocked_reasons == []
    assert decision.receipt.outcome == "activatable"


def test_synthesis_note_proposal_record_exists_and_is_activatable_green() -> None:
    decision = evaluate_synthesis_note_proposal_activation(["note-a", "note-b"])
    assert decision.capability_id == SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID
    assert decision.activatable is True
    assert decision.blocked_reasons == []
    assert decision.receipt.outcome == "activatable"


def test_both_capability_ids_match_the_spec_names() -> None:
    """The capability ids are exactly the spec's declared names (§1.3, §2.6)
    -- the `docs/STATUS.md` ladder rows key on these exact strings."""
    assert CONNECTION_PROPOSAL_CAPABILITY_ID == "connection_proposal"
    assert SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID == "synthesis_note_proposal"


# ---------------------------------------------------------------------------
# Regressed precondition -> blocked-with-reason, never a silent run
# ---------------------------------------------------------------------------


def test_connection_proposal_blocked_when_admissibility_regresses() -> None:
    regressed = build_connection_proposal_posture(admissibility_declared=False)
    decision = evaluate_connection_proposal_activation(["note-a"], posture=regressed)
    assert decision.activatable is False
    assert REASON_ADMISSIBILITY_UNDECLARED in decision.blocked_reasons
    assert decision.receipt.outcome == "blocked"


def test_connection_proposal_blocked_when_loop_precondition_regresses() -> None:
    regressed = build_connection_proposal_posture(loop_precondition_green=False)
    decision = evaluate_connection_proposal_activation(["note-a"], posture=regressed)
    assert decision.activatable is False
    assert REASON_LOOP_PRECONDITION_NOT_GREEN in decision.blocked_reasons


def test_connection_proposal_blocked_when_not_observable() -> None:
    regressed = build_connection_proposal_posture(observable=False)
    decision = evaluate_connection_proposal_activation(["note-a"], posture=regressed)
    assert decision.activatable is False
    assert REASON_NOT_OBSERVABLE in decision.blocked_reasons


def test_synthesis_note_proposal_blocked_when_admissibility_regresses() -> None:
    regressed = build_synthesis_note_proposal_posture(admissibility_declared=False)
    decision = evaluate_synthesis_note_proposal_activation(["obj-a"], posture=regressed)
    assert decision.activatable is False
    assert REASON_ADMISSIBILITY_UNDECLARED in decision.blocked_reasons


def test_synthesis_note_proposal_blocked_when_loop_precondition_regresses() -> None:
    regressed = build_synthesis_note_proposal_posture(loop_precondition_green=False)
    decision = evaluate_synthesis_note_proposal_activation(["obj-a"], posture=regressed)
    assert decision.activatable is False
    assert REASON_LOOP_PRECONDITION_NOT_GREEN in decision.blocked_reasons


def test_no_activate_anyway_path_exists_for_either_capability() -> None:
    """There is no third outcome: a regressed posture is never activatable
    regardless of how many admissible candidates are supplied."""
    regressed_connect = build_connection_proposal_posture(loop_precondition_green=False)
    decision = evaluate_connection_proposal_activation(
        ["note-a", "note-b", "note-c"], posture=regressed_connect
    )
    assert decision.activatable is False

    regressed_create = build_synthesis_note_proposal_posture(admissibility_declared=False)
    decision2 = evaluate_synthesis_note_proposal_activation(
        ["obj-a", "obj-b", "obj-c"], posture=regressed_create
    )
    assert decision2.activatable is False


# ---------------------------------------------------------------------------
# Durable, inspectable receipts
# ---------------------------------------------------------------------------


def test_emit_expansion_gate_receipt_writes_a_durable_record(tmp_path: Path) -> None:
    receipt_path = tmp_path / "expansion_gate_receipts.jsonl"

    green = evaluate_connection_proposal_activation(["note-a"])
    receipt_id = emit_expansion_gate_receipt(green, receipt_path=receipt_path)
    assert receipt_id == green.receipt.receipt_id

    regressed = build_synthesis_note_proposal_posture(loop_precondition_green=False)
    blocked = evaluate_synthesis_note_proposal_activation(["obj-a"], posture=regressed)
    emit_expansion_gate_receipt(blocked, receipt_path=receipt_path)

    records = _outbox_records(receipt_path)
    assert len(records) == 2
    events = {r["event"] for r in records}
    assert events == {EXPANSION_GATE_RECEIPT_EVENT}

    outcomes = {r["payload"]["capability_id"]: r["payload"]["outcome"] for r in records}
    assert outcomes[CONNECTION_PROPOSAL_CAPABILITY_ID] == "activatable"
    assert outcomes[SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID] == "blocked"

    blocked_record = next(r for r in records if r["payload"]["capability_id"] == SYNTHESIS_NOTE_PROPOSAL_CAPABILITY_ID)
    assert REASON_LOOP_PRECONDITION_NOT_GREEN in blocked_record["payload"]["blocked_reasons"]


def test_receipt_never_carries_note_content_or_span_text(tmp_path: Path) -> None:
    """Governance metadata only -- activation receipts must never carry raw
    note content, spans, or excerpts (the same content-free discipline the
    declined-proposal ledger and cross-scope denials already hold)."""
    receipt_path = tmp_path / "receipts.jsonl"
    decision = evaluate_connection_proposal_activation(["note-with-secret-content-marker"])
    emit_expansion_gate_receipt(decision, receipt_path=receipt_path)

    raw_text = receipt_path.read_text(encoding="utf-8")
    # The artifact id itself is fine (it's an opaque id, not content), but no
    # additional free-text content field should appear.
    payload = json.loads(raw_text.splitlines()[0])["payload"]
    assert set(payload.keys()) == {
        "capability_id",
        "consuming_authority",
        "outcome",
        "activatable",
        "blocked_reasons",
        "admitted_artifact_ids",
    }
