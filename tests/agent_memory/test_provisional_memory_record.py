from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.agent_memory.candidate import MemoryType
from app.agent_memory.provisional_memory import (
    ProvisionalLifecycleReceipt,
    ProvisionalLifecycleTransition,
    ProvisionalMarkdownArtifact,
    ProvisionalMemoryRecord,
    ProvisionalReconciliationState,
    ProvisionalSensitivity,
    rebuild_provisional_memory,
)

NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def _artifact(content: str = "The user prefers explicit verification.") -> ProvisionalMarkdownArtifact:
    return ProvisionalMarkdownArtifact(
        memory_id="memory-1",
        artifact_ref="vault://Memory/Provisional/memory-1.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content=content,
        created_by="agent://mimer",
        created_at=NOW,
        provenance_event_ids=("event-1",),
    )


def _created_receipt(artifact: ProvisionalMarkdownArtifact) -> ProvisionalLifecycleReceipt:
    return ProvisionalLifecycleReceipt(
        receipt_id="receipt-created",
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        transition=ProvisionalLifecycleTransition.CREATED,
        actor_ref="agent://mimer",
        occurred_at=NOW,
        artifact_digest=artifact.content_digest,
    )


def test_record_pins_noncanonical_low_trust_roles() -> None:
    artifact = _artifact()
    result = rebuild_provisional_memory(
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        artifact=artifact,
        receipts=(_created_receipt(artifact),),
    )

    assert result.state is ProvisionalReconciliationState.READY
    assert result.record is not None
    assert result.record.source_role == "agent_memory"
    assert result.record.authority_state == "noncanonical"
    assert result.record.review_state == "unreviewed"
    assert result.record.evidence_role.value == "background"
    assert result.record.scope_id == "scope-personal"
    assert result.record.provenance_event_ids == ("event-1",)
    assert result.record.may_read is True
    assert result.record.may_support_cited_proposal is True
    assert result.record.may_apply is False
    assert result.record.may_write is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_role", "human_knowledge"),
        ("authority_state", "canonical"),
        ("evidence_role", "evidence"),
        ("review_state", "accepted"),
    ],
)
def test_record_rejects_authority_escalation(field: str, value: str) -> None:
    payload = _artifact().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        ProvisionalMarkdownArtifact.model_validate(payload)

    with pytest.raises(ValidationError):
        ProvisionalMarkdownArtifact.model_validate(
            {**_artifact().model_dump(), "provenance_event_ids": ("",)}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope_id", ""),
        ("principal_id", ""),
        ("content", ""),
        ("provenance_event_ids", ()),
        ("lifecycle_receipt_refs", ()),
        ("created_at", datetime(2026, 7, 15)),
        ("may_apply", True),
    ],
)
def test_direct_record_construction_cannot_bypass_invariants(
    field: str, value: object
) -> None:
    artifact = _artifact()
    result = rebuild_provisional_memory(
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        artifact=artifact,
        receipts=(_created_receipt(artifact),),
    )
    assert result.record is not None
    payload = result.record.model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        ProvisionalMemoryRecord.model_validate(payload)


def test_lifecycle_receipts_are_content_free_and_distinguish_retryable_state() -> None:
    artifact = _artifact()
    failed = ProvisionalLifecycleReceipt(
        receipt_id="receipt-failed",
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        transition=ProvisionalLifecycleTransition.WRITE_FAILED,
        actor_ref="agent://mimer",
        occurred_at=NOW,
        error_code="vault_write_failed",
    )
    deleted = ProvisionalLifecycleReceipt(
        receipt_id="receipt-deleted",
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        transition=ProvisionalLifecycleTransition.DELETED,
        actor_ref="human://owner",
        occurred_at=NOW,
    )

    assert failed.retryable is True
    assert failed.terminal is False
    assert deleted.retryable is False
    assert deleted.terminal is True
    assert "content" not in failed.content_free_payload()
    with pytest.raises(ValidationError):
        ProvisionalLifecycleReceipt.model_validate(
            {**failed.model_dump(), "content": "must not persist"}
        )
    with pytest.raises(ValidationError):
        ProvisionalLifecycleReceipt.model_validate(
            {
                **failed.model_dump(),
                "error_code": "The user prefers explicit verification.",
            }
        )
    partial = rebuild_provisional_memory(
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        artifact=artifact,
        receipts=(failed,),
    )
    terminal = rebuild_provisional_memory(
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        artifact=None,
        receipts=(deleted,),
    )
    assert partial.state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
    assert partial.record is None
    assert terminal.state is ProvisionalReconciliationState.TERMINAL_DELETED
    assert terminal.record is None


def test_terminal_delete_cannot_be_reversed_by_later_created_receipt() -> None:
    artifact = _artifact()
    deleted = ProvisionalLifecycleReceipt(
        receipt_id="receipt-deleted",
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        transition=ProvisionalLifecycleTransition.DELETED,
        actor_ref="human://owner",
        occurred_at=NOW,
    )
    later_created = _created_receipt(artifact).model_copy(
        update={
            "receipt_id": "receipt-created-later",
            "occurred_at": NOW + timedelta(seconds=1),
        }
    )

    result = rebuild_provisional_memory(
        memory_id=artifact.memory_id,
        artifact_ref=artifact.artifact_ref,
        artifact=artifact,
        receipts=(deleted, later_created),
    )

    assert result.state is ProvisionalReconciliationState.TERMINAL_DELETED
    assert result.record is None


def test_record_rebuild_follows_markdown_and_never_resurrects_missing_content() -> None:
    original = _artifact("Original Markdown claim")
    receipt = _created_receipt(original)
    edited = _artifact("Human-edited Markdown claim")

    rebuilt = rebuild_provisional_memory(
        memory_id=edited.memory_id,
        artifact_ref=edited.artifact_ref,
        artifact=edited,
        receipts=(receipt,),
    )
    missing = rebuild_provisional_memory(
        memory_id=edited.memory_id,
        artifact_ref=edited.artifact_ref,
        artifact=None,
        receipts=(receipt,),
    )

    assert rebuilt.state is ProvisionalReconciliationState.EDITED
    assert rebuilt.record is not None
    assert rebuilt.record.content == "Human-edited Markdown claim"
    assert missing.state is ProvisionalReconciliationState.MISSING
    assert missing.record is None
    assert "Original Markdown claim" not in str(missing.model_dump())
