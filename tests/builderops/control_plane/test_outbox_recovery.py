from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.builderops.control_plane import StaleFencingToken, UnknownEffectNeedsReconciliation

pytestmark = pytest.mark.pg


def test_unknown_external_effect_requires_readback_before_retry(
    control_plane_store, envelope
) -> None:
    result = control_plane_store.commit_transition(
        envelope=envelope,
        task_id="task-3792",
        to_state="claimed",
        idempotency_key="unknown-effect",
        request={"command": "claim"},
        outbox={"effect_type": "github.merge", "payload": {"pr": 4000}},
    )
    now = datetime.now(timezone.utc)
    first_claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="demerzel-1",
        recovered_through=result.recovery_lsn,
        claim_ttl_seconds=1,
        now=now,
    )
    restarted_store = type(control_plane_store)(control_plane_store.dsn)
    claim = restarted_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="demerzel-2",
        recovered_through=first_claim.claim_lsn,
        now=now + timedelta(seconds=2),
    )
    assert claim.fencing_token > first_claim.fencing_token
    with pytest.raises(StaleFencingToken):
        control_plane_store.mark_effect_unknown(first_claim, detail="late stale worker")
    restarted_store.mark_effect_unknown(claim, detail="network timeout after request")

    with pytest.raises(UnknownEffectNeedsReconciliation):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="demerzel-2",
            recovered_through=claim.claim_lsn,
        )

    restarted_store.reconcile_outbox(claim, observed_applied=True, evidence={"merge_sha": "a" * 40})
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "succeeded"
