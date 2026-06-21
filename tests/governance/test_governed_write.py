from __future__ import annotations

import pytest

from app.governance.governed_write import (
    GovernedWriteAdapter,
    InvalidDecisionTokenError,
    MissingAuthorityReceiptError,
    MissingDecisionTokenError,
)
from app.health_contract import WRITE_BLOCKED_STATES
from app.knowledge.contracts import NoteLocator, WriteReceipt
from app.write_guard import WriteGuard, WritesBlockedError


def _open_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "ok"})


def _receipt(path: str = "Inbox/inbox.md") -> WriteReceipt:
    return WriteReceipt(
        operation="append_note",
        locator=NoteLocator(vault="Vault", path=path),
        adapter="fs_vault",
        fallback_used=False,
    )


def test_governed_write_adapter_issues_token_and_maps_state_owner_receipt() -> None:
    adapter = GovernedWriteAdapter()

    grant = adapter.issue_decision_token(
        write_guard=_open_guard(),
        action="companion.capture.append",
        write_class="vault_capture_append",
        actor="companion.capture",
        resource="Inbox/inbox.md",
    )
    authority_receipt = adapter.record_authority_receipt(
        decision_token=grant.decision_token,
        mutation_receipt=_receipt(),
        state_owner="knowledge",
        trace_id="trace-1",
    )

    assert grant.policy_decision.status == "approved"
    assert grant.policy_decision.source == "WriteGuard"
    assert grant.decision_token.resource == "Inbox/inbox.md"
    assert authority_receipt.decision_token_id == grant.decision_token.token_id
    assert authority_receipt.outcome == "applied"
    assert authority_receipt.operation == "append_note"
    assert authority_receipt.adapter == "fs_vault"
    assert authority_receipt.state_owner == "knowledge"
    assert authority_receipt.trace_id == "trace-1"


def test_governed_write_adapter_normalizes_path_like_resources_before_matching() -> None:
    adapter = GovernedWriteAdapter()

    grant = adapter.issue_decision_token(
        write_guard=_open_guard(),
        action="companion.capture.append",
        write_class="vault_capture_append",
        actor="companion.capture",
        resource=r"Inbox\inbox.md",
    )
    authority_receipt = adapter.record_authority_receipt(
        decision_token=grant.decision_token,
        mutation_receipt=_receipt("Inbox/inbox.md"),
        state_owner="knowledge",
    )

    assert grant.decision_token.resource == "Inbox/inbox.md"
    assert authority_receipt.resource == "Inbox/inbox.md"


def test_governed_write_adapter_writeguard_denial_prevents_token() -> None:
    blocked_state = sorted(WRITE_BLOCKED_STATES)[0]
    guard = WriteGuard(snapshot_fn=lambda: {"state": blocked_state, "reason": "maintenance"})

    with pytest.raises(WritesBlockedError):
        GovernedWriteAdapter().issue_decision_token(
            write_guard=guard,
            action="companion.capture.append",
            write_class="vault_capture_append",
            actor="companion.capture",
            resource="Inbox/inbox.md",
        )


def test_governed_write_adapter_missing_token_or_receipt_fails_loudly() -> None:
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=_open_guard(),
        action="companion.capture.append",
        write_class="vault_capture_append",
        actor="companion.capture",
        resource="Inbox/inbox.md",
    )

    with pytest.raises(MissingDecisionTokenError):
        adapter.record_authority_receipt(
            decision_token=None,
            mutation_receipt=_receipt(),
            state_owner="knowledge",
        )

    with pytest.raises(MissingAuthorityReceiptError):
        adapter.record_authority_receipt(
            decision_token=grant.decision_token,
            mutation_receipt=None,
            state_owner="knowledge",
        )

    with pytest.raises(InvalidDecisionTokenError):
        adapter.record_authority_receipt(
            decision_token=grant.decision_token,
            mutation_receipt=_receipt("Other/inbox.md"),
            state_owner="knowledge",
        )
