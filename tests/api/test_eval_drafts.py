"""API contract for persisting eval-draft promotion decision provenance."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
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
