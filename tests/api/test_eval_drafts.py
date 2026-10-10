"""API contract for persisting eval-draft promotion decision provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.eval import failure_capture as failure_capture_module
from app.eval.failure_capture import (
    DRAFT_STATUS_PROMOTED,
    draft_unknown_classification_case,
    read_draft,
)
from tests._mvr03_principal_harness import provisioned_instance
from tests.api._vault_test_helpers import bind_initialized_vault

pytestmark = pytest.mark.not_pg


def test_promote_route_persists_decision_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="ambiguous API promotion case",
        trace_id="api-promotion-provenance",
    )
    client = TestClient(app)

    response = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={
            "action": "promote",
            "decided_by": principal_record.local_operator_role_id,
            "notes": "reviewed\nintegration_ref: golden-case:case-api-contract",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["draft_id"] == draft.draft_id
    assert body["decision"] == "promote"
    assert body["decided_by"] == principal_record.local_operator_role_id
    assert body["decided_at"]
    assert body["notes"] == "reviewed\nintegration_ref: golden-case:case-api-contract"

    persisted = read_draft(vault, draft.draft_id)
    assert persisted is not None
    assert persisted.status == DRAFT_STATUS_PROMOTED
    assert persisted.decided_by == body["decided_by"]
    assert persisted.decided_at == body["decided_at"]
    assert persisted.notes == body["notes"]


def test_decision_route_rejects_request_identity_not_bound_to_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="unbound API reviewer case",
        trace_id="api-unbound-reviewer",
    )
    assert draft is not None

    response = TestClient(app).post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={"action": "reject", "decided_by": "attacker-supplied-reviewer"},
    )

    assert response.status_code == 403, response.text
    persisted = read_draft(vault, draft.draft_id)
    assert persisted is not None
    assert persisted.status == "pending"
    assert principal_record.local_operator_role_id not in response.text


def test_receipt_pending_retry_reconciles_same_disposition_without_second_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "eval-disposition-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="retryable API promotion case",
        trace_id="api-disposition-retry",
    )
    assert draft is not None
    notes = "reviewed\nintegration_ref: golden-case:case-api-retry"
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": notes,
    }
    client = TestClient(app)

    real_append = failure_capture_module.append_jsonl_outbox_event
    append_attempts = 0

    def fail_first_two_receipt_writes(*args: Any, **kwargs: Any) -> bool:
        nonlocal append_attempts
        append_attempts += 1
        if append_attempts <= 2:
            raise OSError("fault injection for receipt persistence")
        return real_append(*args, **kwargs)

    real_write = failure_capture_module.write_note_relative
    status_mutations = 0

    def count_status_mutations(*args: Any, **kwargs: Any) -> Any:
        nonlocal status_mutations
        status_mutations += 1
        return real_write(*args, **kwargs)

    monkeypatch.setattr(
        failure_capture_module,
        "append_jsonl_outbox_event",
        fail_first_two_receipt_writes,
    )
    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_status_mutations)

    first_response = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
    )

    assert first_response.status_code == 409, first_response.text
    stranded = read_draft(vault, draft.draft_id)
    assert stranded is not None
    assert stranded.status == DRAFT_STATUS_PROMOTED
    assert stranded.decided_by == principal_record.local_operator_role_id
    assert stranded.decision_token is not None
    original_token_id = stranded.decision_token.token_id
    assert status_mutations == 1
    assert append_attempts == 2

    wrong_reviewer = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={**payload, "decided_by": "attacker-supplied-reviewer"},
    )
    assert wrong_reviewer.status_code == 403, wrong_reviewer.text
    assert status_mutations == 1
    assert append_attempts == 2

    wrong_action = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={**payload, "action": "reject"},
    )
    assert wrong_action.status_code == 409, wrong_action.text
    assert status_mutations == 1
    assert append_attempts == 2

    wrong_notes = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={**payload, "notes": "different decision notes"},
    )
    assert wrong_notes.status_code == 409, wrong_notes.text
    assert status_mutations == 1
    assert append_attempts == 2

    retry = client.post(f"/api/eval-drafts/{draft.draft_id}/decision", json=payload)

    assert retry.status_code == 200, retry.text
    body = retry.json()
    assert body["decision"] == "promote"
    assert body["decided_by"] == principal_record.local_operator_role_id
    assert body["decided_at"] == stranded.decided_at
    assert body["notes"] == notes
    assert status_mutations == 1
    assert append_attempts == 3

    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching = [
        record
        for record in records
        if record.get("event") == "governance.authority_receipt.recorded"
        and record.get("payload", {}).get("draft_id") == draft.draft_id
    ]
    assert len(matching) == 1
    assert matching[0]["payload"]["decision_token"]["token_id"] == original_token_id
    assert (
        matching[0]["payload"]["authority_receipt"]["decision_token_id"]
        == original_token_id
    )
