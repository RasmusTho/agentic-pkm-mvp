"""Read-only composition of the immutable ``design_hub`` cockpit projection.

CDH-05 (issue #4312, `docs/CKM_DESIGN_AGENT_INTEGRATION/PROJECT_DESIGN_RUNS_IN_COCKPIT.md`)
extends the existing ``ckm overview --cockpit`` render context with sanitized
design-agent availability and validated BuilderOps design-run projections.

This module never admits, approves, starts, executes, or otherwise mutates a
design run. It only calls the two read-only :class:`DesignRunGovernance`
surfaces (`list_adapters`, `projection`) that already exist from CDH-02/
CDH-03, and only after independently discovering candidate run ids from
already-persisted receipt records. A run whose causal receipt chain does not
independently validate through ``DesignRunGovernance.projection`` is excluded
entirely rather than partially shown (INV-CDH-6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.builderops.ckm.contracts import canonical_digest
from app.builderops.design_run_contract import DesignAgentAvailabilityDescriptor
from app.builderops.design_run_governance import (
    DESIGN_RUN_RECEIPT_EVENT_TYPE,
    DesignRunGovernance,
    DesignRunGovernanceError,
)

# Fixed, safe operator identifier used only to enumerate cockpit-wide adapter
# availability. It never names, selects, or starts an actual run.
COCKPIT_DESIGN_HUB_RUN_ID = "ckm.cockpit.design_hub.availability"


@dataclass(frozen=True)
class DesignHubReceiptSummary:
    """One causal receipt from a validated design-run chain, in chain order."""

    receipt_id: str
    event_type: str
    occurred_at: str
    state: str | None
    previous_state: str | None
    previous_receipt_id: str | None


@dataclass(frozen=True)
class DesignHubHandoffSummary:
    """Unaccepted Builder material referenced by a completed run."""

    handoff_id: str
    content_hash: str
    acceptance_state: str
    produced_at: str
    limitations: tuple[str, ...]
    source_ref_ids: tuple[str, ...]


@dataclass(frozen=True)
class DesignHubRunSummary:
    """One validated design-run projection, captured once and never mutated."""

    run_id: str
    state: str
    latest_receipt_id: str
    admission_outcome: str | None
    approval_state: str | None
    refusal_code: str | None
    refusal_message: str | None
    handoff: DesignHubHandoffSummary | None
    receipts: tuple[DesignHubReceiptSummary, ...]


@dataclass(frozen=True)
class DesignHubProjection:
    """Immutable design-hub projection captured before cockpit rendering."""

    adapters: tuple[DesignAgentAvailabilityDescriptor, ...]
    runs: tuple[DesignHubRunSummary, ...]
    excluded_run_ids: tuple[str, ...]


def _decode_design_run_records(
    records: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    """Decode only well-formed design-run receipt records; skip the rest."""

    decoded: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for record in records:
        if record.get("event_type") != DESIGN_RUN_RECEIPT_EVENT_TYPE:
            continue
        raw_body = record.get("receipt_body")
        if not isinstance(raw_body, str):
            continue
        try:
            payload = json.loads(raw_body)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        decoded.append((record, payload))
    return decoded


def _ordered_receipts(
    decoded: Sequence[tuple[Mapping[str, Any], dict[str, Any]]],
    *,
    run_id: str,
    latest_receipt_id: str,
) -> tuple[DesignHubReceiptSummary, ...]:
    """Replay one already governance-validated chain in root-to-latest order.

    This only re-derives *display order* for a run whose full chain already
    passed ``DesignRunGovernance.projection`` (i.e. is proven non-tampered,
    acyclic, and singly rooted). It never independently trusts an unvalidated
    chain, and it is not a substitute for that validation.
    """

    selected = [
        (record, payload)
        for record, payload in decoded
        if payload.get("run_id") == run_id
    ]
    by_id = {
        record["id"]: (record, payload)
        for record, payload in selected
        if isinstance(record.get("id"), str)
    }
    children = {
        payload["previous_receipt_id"]: record["id"]
        for record, payload in selected
        if isinstance(payload.get("previous_receipt_id"), str)
        and isinstance(record.get("id"), str)
    }
    roots = [
        record["id"]
        for record, payload in selected
        if payload.get("previous_receipt_id") is None and isinstance(record.get("id"), str)
    ]
    if len(roots) != 1:
        return ()
    ordered: list[DesignHubReceiptSummary] = []
    seen: set[str] = set()
    current_id: str | None = roots[0]
    while current_id is not None and current_id not in seen:
        seen.add(current_id)
        entry = by_id.get(current_id)
        if entry is None:
            break
        record, payload = entry
        ordered.append(
            DesignHubReceiptSummary(
                receipt_id=str(record["id"]),
                event_type=str(payload.get("event_type")),
                occurred_at=str(payload.get("occurred_at")),
                state=payload.get("state"),
                previous_state=payload.get("previous_state"),
                previous_receipt_id=payload.get("previous_receipt_id"),
            )
        )
        if current_id == latest_receipt_id:
            break
        current_id = children.get(current_id)
    return tuple(ordered)


def build_design_hub_projection(
    *,
    governance: DesignRunGovernance,
) -> DesignHubProjection:
    """Capture one immutable, read-only design_hub projection for the cockpit.

    Never admits, approves, starts, executes, or otherwise mutates a run.
    Enumerates known design-run receipt evidence, keeps only runs whose full
    causal chain independently validates through
    :meth:`DesignRunGovernance.projection`, and excludes every other run
    rather than showing partial or unverified state.
    """

    adapters = tuple(
        sorted(
            governance.list_adapters(run_id=COCKPIT_DESIGN_HUB_RUN_ID),
            key=lambda item: item.design_agent_id,
        )
    )
    records = governance.store.list_records("BuilderOpsReceipt")
    decoded = _decode_design_run_records(records)
    known_run_ids = sorted(
        {
            payload["run_id"]
            for _, payload in decoded
            if isinstance(payload.get("run_id"), str)
        }
    )
    runs: list[DesignHubRunSummary] = []
    excluded: list[str] = []
    for known_run_id in known_run_ids:
        try:
            projection = governance.projection(known_run_id)
        except DesignRunGovernanceError:
            excluded.append(known_run_id)
            continue
        handoff: DesignHubHandoffSummary | None = None
        if projection.result is not None and projection.result.handoff is not None:
            ref = projection.result.handoff
            handoff = DesignHubHandoffSummary(
                handoff_id=ref.handoff_id,
                content_hash=ref.content_hash,
                acceptance_state=ref.acceptance_state,
                produced_at=ref.produced_at,
                limitations=tuple(sorted(ref.limitations)),
                source_ref_ids=tuple(sorted(item.source_id for item in ref.source_refs)),
            )
        refusal = projection.refusal
        runs.append(
            DesignHubRunSummary(
                run_id=projection.run_id,
                state=projection.state,
                latest_receipt_id=projection.latest_receipt_id,
                admission_outcome=(
                    projection.admission.outcome if projection.admission else None
                ),
                approval_state=(
                    projection.approval.state if projection.approval else None
                ),
                refusal_code=refusal.code if refusal else None,
                refusal_message=refusal.public_message if refusal else None,
                handoff=handoff,
                receipts=_ordered_receipts(
                    decoded,
                    run_id=known_run_id,
                    latest_receipt_id=projection.latest_receipt_id,
                ),
            )
        )
    return DesignHubProjection(
        adapters=adapters,
        runs=tuple(sorted(runs, key=lambda item: item.run_id)),
        excluded_run_ids=tuple(sorted(excluded)),
    )


def design_hub_digest(design_hub: DesignHubProjection) -> str:
    """Deterministic digest kept separate from, and visible alongside, the CKM digest."""

    return canonical_digest(
        {
            "adapters": [
                item.model_dump(mode="json") for item in design_hub.adapters
            ],
            "runs": [
                {
                    "run_id": run.run_id,
                    "state": run.state,
                    "latest_receipt_id": run.latest_receipt_id,
                    "admission_outcome": run.admission_outcome,
                    "approval_state": run.approval_state,
                    "refusal_code": run.refusal_code,
                    "refusal_message": run.refusal_message,
                    "handoff": (
                        {
                            "handoff_id": run.handoff.handoff_id,
                            "content_hash": run.handoff.content_hash,
                            "acceptance_state": run.handoff.acceptance_state,
                            "produced_at": run.handoff.produced_at,
                            "limitations": list(run.handoff.limitations),
                            "source_ref_ids": list(run.handoff.source_ref_ids),
                        }
                        if run.handoff is not None
                        else None
                    ),
                    "receipts": [
                        {
                            "receipt_id": receipt.receipt_id,
                            "event_type": receipt.event_type,
                            "occurred_at": receipt.occurred_at,
                            "state": receipt.state,
                            "previous_state": receipt.previous_state,
                            "previous_receipt_id": receipt.previous_receipt_id,
                        }
                        for receipt in run.receipts
                    ],
                }
                for run in design_hub.runs
            ],
            "excluded_run_ids": list(design_hub.excluded_run_ids),
        }
    )
