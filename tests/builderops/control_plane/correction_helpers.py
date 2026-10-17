"""Real transaction setup for the narrow terminal metadata regression."""

from dataclasses import replace

from app.builderops.control_plane.store import _hash

TASK = "github-rasmustho--agentic-pkm-mvp-issue-5495"


def correction_setup(store, envelope):
    original = replace(envelope, actor="original-source")
    payload = {
        "repo": envelope.repository,
        "task_id": TASK,
        "issue_number": 5495,
        "title": "Delivered task",
        "status": "ready",
        "state": "completed",
        "priority": "high",
        "sync_state": {"state": "open", "authority_epoch": 1},
    }
    store.commit_transition(
        envelope=original,
        task_id=TASK,
        to_state="ready",
        idempotency_key="seed-ready",
        request=payload,
    )
    _, task_lease = store.claim_task(
        envelope=original,
        task_id=TASK,
        holder=original.actor,
        idempotency_key="seed-claim",
        request=payload,
    )
    store.complete_task(
        envelope=original,
        lease=task_lease,
        idempotency_key="seed-complete",
        expected_version=2,
        request=payload,
    )
    row = store.get_task(envelope.repository, TASK)
    _, lease = store.claim_lease(
        envelope=envelope,
        resource_id=f"payload-status-correction:{TASK}",
        holder=envelope.actor,
        idempotency_key="maintenance-claim",
        request={},
    )
    args = {
        "envelope": envelope,
        "task_id": TASK,
        "lease": lease,
        "idempotency_key": "correction-6175",
        "expected_state": "completed",
        "expected_version": 3,
        "expected_updated_at": row["updated_at"],
        "expected_payload_sha256": "sha256:" + _hash(row["payload"]),
        "proposal_sha256": "sha256:" + "a" * 64,
        "proposal_ref": "github:issue:5181:comment:6240522962",
    }
    return args, row
