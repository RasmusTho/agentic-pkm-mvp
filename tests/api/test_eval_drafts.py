"""API contract for persisting eval-draft promotion decision provenance."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from threading import Barrier, Event, Lock
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
from app.receipts import outbox_sources as receipt_sources
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


@pytest.mark.parametrize("tamper", ["contract_version", "issued_at"])
def test_receipt_pending_retry_rejects_tampered_governed_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / f"tampered-token-{tamper}.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance=f"tampered token {tamper} case",
        trace_id=f"api-tampered-token-{tamper}",
    )
    assert draft is not None
    notes = "reviewed exact disposition"
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": notes,
    }

    issue_calls = 0
    adapter = failure_capture_module._GOVERNED_WRITE_ADAPTER
    real_issue = adapter.issue_human_decision_token

    def count_issue(**kwargs: Any) -> Any:
        nonlocal issue_calls
        issue_calls += 1
        return real_issue(**kwargs)

    monkeypatch.setattr(adapter, "issue_human_decision_token", count_issue)
    append_attempts = 0

    def fail_receipt_write(*_args: Any, **_kwargs: Any) -> bool:
        nonlocal append_attempts
        append_attempts += 1
        raise OSError("fault injection leaves an applied receipt pending")

    monkeypatch.setattr(
        failure_capture_module,
        "append_jsonl_outbox_event",
        fail_receipt_write,
    )
    real_write = failure_capture_module.write_note_relative
    status_mutations = 0

    def count_status_mutations(*args: Any, **kwargs: Any) -> Any:
        nonlocal status_mutations
        status_mutations += 1
        return real_write(*args, **kwargs)

    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_status_mutations)
    client = TestClient(app)
    first_response = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
    )
    assert first_response.status_code == 409, first_response.text
    assert issue_calls == 1
    assert status_mutations == 1
    assert append_attempts == 2

    terminal = read_draft(vault, draft.draft_id)
    assert (
        terminal is not None
        and terminal.decision_token is not None
        and terminal.draft_path is not None
    )
    if tamper == "contract_version":
        changed_token = replace(
            terminal.decision_token,
            contract_version="unsupported-governed-write-contract",
        )
    else:
        changed_token = replace(
            terminal.decision_token,
            issued_at=f"{terminal.decision_token.issued_at}-tampered",
        )
    tampered_terminal = replace(terminal, decision_token=changed_token)
    terminal_path = vault / terminal.draft_path
    terminal_path.write_text(
        failure_capture_module._render_draft_note(
            tampered_terminal,
            title="Promoted draft: tampered authorization",
        ),
        encoding="utf-8",
    )

    retry = client.post(f"/api/eval-drafts/{draft.draft_id}/decision", json=payload)

    assert retry.status_code == 409, retry.text
    assert issue_calls == 1
    assert status_mutations == 1
    assert append_attempts == 2
    persisted = read_draft(vault, draft.draft_id)
    assert persisted is not None and persisted.status == DRAFT_STATUS_PROMOTED
    assert persisted.decision_token == changed_token
    assert not outbox_path.exists()


def test_legacy_terminal_eval_draft_retry_fails_closed_without_minting_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "legacy-terminal-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="legacy terminal API case",
        trace_id="api-legacy-terminal",
    )
    assert draft is not None and draft.draft_path is not None
    notes = "legacy adjudication"
    legacy_terminal = replace(
        draft,
        status=DRAFT_STATUS_PROMOTED,
        decided_by=principal_record.local_operator_role_id,
        decided_at="2026-10-01T12:00:00+00:00",
        notes=notes,
    )
    legacy_path = vault / draft.draft_path
    legacy_path.write_text(
        failure_capture_module._render_draft_note(
            legacy_terminal,
            title="Promoted draft: legacy fixture",
        ),
        encoding="utf-8",
    )

    issue_calls = 0
    adapter = failure_capture_module._GOVERNED_WRITE_ADAPTER
    real_issue = adapter.issue_human_decision_token

    def count_issue(**kwargs: Any) -> Any:
        nonlocal issue_calls
        issue_calls += 1
        return real_issue(**kwargs)

    monkeypatch.setattr(adapter, "issue_human_decision_token", count_issue)

    outbox_reads = 0
    real_read_receipts = failure_capture_module.read_receipt_source_snapshot

    def count_outbox_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal outbox_reads
        outbox_reads += 1
        return real_read_receipts(*args, **kwargs)

    monkeypatch.setattr(
        failure_capture_module,
        "read_receipt_source_snapshot",
        count_outbox_read,
    )
    outbox_writes = 0

    def count_outbox_write(*_args: Any, **_kwargs: Any) -> bool:
        nonlocal outbox_writes
        outbox_writes += 1
        return True

    monkeypatch.setattr(
        failure_capture_module,
        "append_jsonl_outbox_event",
        count_outbox_write,
    )
    response = TestClient(app).post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={
            "action": "promote",
            "decided_by": principal_record.local_operator_role_id,
            "notes": notes,
        },
    )

    assert response.status_code == 409, response.text
    assert issue_calls == 0
    assert outbox_reads == 0
    assert outbox_writes == 0
    persisted = read_draft(vault, draft.draft_id)
    assert persisted is not None
    assert persisted.status == DRAFT_STATUS_PROMOTED
    assert persisted.decided_by == principal_record.local_operator_role_id
    assert persisted.decided_at == legacy_terminal.decided_at
    assert persisted.notes == notes
    assert persisted.policy_decision is None
    assert persisted.decision_token is None
    assert outbox_reads == 0
    assert outbox_writes == 0
    assert not outbox_path.exists()


def test_durable_receipt_with_lost_acknowledgement_returns_existing_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "lost-ack-receipt.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="durable receipt acknowledgement case",
        trace_id="api-lost-receipt-ack",
    )
    assert draft is not None
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": "reviewed exact disposition",
    }

    real_append = failure_capture_module.append_jsonl_outbox_event
    append_attempts = 0

    def append_then_lose_ack(*args: Any, **kwargs: Any) -> bool:
        nonlocal append_attempts
        append_attempts += 1
        real_append(*args, **kwargs)
        raise OSError("fault injected after the receipt became durable")

    monkeypatch.setattr(
        failure_capture_module,
        "append_jsonl_outbox_event",
        append_then_lose_ack,
    )
    real_write = failure_capture_module.write_note_relative
    status_writes = 0

    def count_status_write(*args: Any, **kwargs: Any) -> Any:
        nonlocal status_writes
        status_writes += 1
        return real_write(*args, **kwargs)

    monkeypatch.setattr(
        failure_capture_module, "write_note_relative", count_status_write
    )
    response = TestClient(app).post(
        f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
    )

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "promote"
    assert append_attempts == 1
    assert status_writes == 1
    persisted = read_draft(vault, draft.draft_id)
    assert persisted is not None and persisted.decision_token is not None
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
    assert (
        matching[0]["payload"]["decision_token"]["token_id"]
        == persisted.decision_token.token_id
    )


def test_exact_retry_returns_jsonl_receipt_when_configured_db_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "jsonl-receipt-db-unavailable.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setattr(
        failure_capture_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "healthy"},
    )
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="JSONL receipt with unavailable DB case",
        trace_id="api-jsonl-receipt-db-unavailable",
    )
    assert draft is not None
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": "replay the already durable JSONL receipt",
    }

    append_calls = 0
    real_append = failure_capture_module.append_jsonl_outbox_event

    def count_append(*args: Any, **kwargs: Any) -> bool:
        nonlocal append_calls
        append_calls += 1
        return real_append(*args, **kwargs)

    db_write_calls = 0

    def fail_db_write(*_args: Any, **_kwargs: Any) -> str:
        nonlocal db_write_calls
        db_write_calls += 1
        raise OSError("configured DB sink is unavailable")

    status_writes = 0
    real_write_note = failure_capture_module.write_note_relative

    def count_status_write(*args: Any, **kwargs: Any) -> Any:
        nonlocal status_writes
        status_writes += 1
        return real_write_note(*args, **kwargs)

    token_issues = 0
    adapter = failure_capture_module._GOVERNED_WRITE_ADAPTER
    real_issue_token = adapter.issue_human_decision_token

    def count_token_issue(**kwargs: Any) -> Any:
        nonlocal token_issues
        token_issues += 1
        return real_issue_token(**kwargs)

    monkeypatch.setattr(failure_capture_module, "append_jsonl_outbox_event", count_append)
    monkeypatch.setattr(failure_capture_module, "write_outbox_event", fail_db_write)
    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_status_write)
    monkeypatch.setattr(adapter, "issue_human_decision_token", count_token_issue)
    client = TestClient(app)

    first_response = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
    )

    assert first_response.status_code == 200, first_response.text
    terminal = read_draft(vault, draft.draft_id)
    assert terminal is not None and terminal.decision_token is not None
    original_token_id = terminal.decision_token.token_id
    original_decided_at = terminal.decided_at
    assert append_calls == 1
    assert db_write_calls == 1
    assert status_writes == 1
    assert token_issues == 1

    monkeypatch.setattr(receipt_sources, "_read_db_outbox_records", lambda: None)
    retry = client.post(f"/api/eval-drafts/{draft.draft_id}/decision", json=payload)

    assert retry.status_code == 200, retry.text
    assert retry.json()["decided_at"] == original_decided_at
    assert append_calls == 1
    assert db_write_calls == 1
    assert status_writes == 1
    assert token_issues == 1
    reread = read_draft(vault, draft.draft_id)
    assert reread is not None and reread.decision_token is not None
    assert reread.decision_token.token_id == original_token_id
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


def test_exact_retry_returns_db_receipt_when_jsonl_source_is_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "db-receipt-jsonl-corrupt.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setattr(
        failure_capture_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "healthy"},
    )
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="DB receipt with corrupt JSONL case",
        trace_id="api-db-receipt-jsonl-corrupt",
    )
    assert draft is not None
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": "replay the already durable DB receipt",
    }

    append_calls = 0
    real_append = failure_capture_module.append_jsonl_outbox_event

    def count_append(*args: Any, **kwargs: Any) -> bool:
        nonlocal append_calls
        append_calls += 1
        return real_append(*args, **kwargs)

    db_write_calls = 0

    def acknowledge_db_write(*_args: Any, **_kwargs: Any) -> str:
        nonlocal db_write_calls
        db_write_calls += 1
        return "db-receipt-event"

    status_writes = 0
    real_write_note = failure_capture_module.write_note_relative

    def count_status_write(*args: Any, **kwargs: Any) -> Any:
        nonlocal status_writes
        status_writes += 1
        return real_write_note(*args, **kwargs)

    token_issues = 0
    adapter = failure_capture_module._GOVERNED_WRITE_ADAPTER
    real_issue_token = adapter.issue_human_decision_token

    def count_token_issue(**kwargs: Any) -> Any:
        nonlocal token_issues
        token_issues += 1
        return real_issue_token(**kwargs)

    monkeypatch.setattr(failure_capture_module, "append_jsonl_outbox_event", count_append)
    monkeypatch.setattr(failure_capture_module, "write_outbox_event", acknowledge_db_write)
    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_status_write)
    monkeypatch.setattr(adapter, "issue_human_decision_token", count_token_issue)
    client = TestClient(app)

    first_response = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
    )

    assert first_response.status_code == 200, first_response.text
    terminal = read_draft(vault, draft.draft_id)
    assert terminal is not None and terminal.decision_token is not None
    original_token_id = terminal.decision_token.token_id
    original_decided_at = terminal.decided_at
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
    db_record = matching[0]
    assert append_calls == 1
    assert db_write_calls == 1
    assert status_writes == 1
    assert token_issues == 1

    outbox_path.write_text('{"event": malformed\n', encoding="utf-8")
    malformed_source = outbox_path.read_text(encoding="utf-8")
    monkeypatch.setattr(receipt_sources, "_read_db_outbox_records", lambda: [db_record])
    retry = client.post(f"/api/eval-drafts/{draft.draft_id}/decision", json=payload)

    assert retry.status_code == 200, retry.text
    assert retry.json()["decided_at"] == original_decided_at
    assert append_calls == 1
    assert db_write_calls == 1
    assert status_writes == 1
    assert token_issues == 1
    assert outbox_path.read_text(encoding="utf-8") == malformed_source
    reread = read_draft(vault, draft.draft_id)
    assert reread is not None and reread.decision_token is not None
    assert reread.decision_token.token_id == original_token_id


def test_malformed_receipt_jsonl_fails_closed_on_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "malformed-receipt-source.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="malformed receipt source case",
        trace_id="api-malformed-receipt-source",
    )
    assert draft is not None
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": "reviewed exact disposition",
    }

    issue_calls = 0
    adapter = failure_capture_module._GOVERNED_WRITE_ADAPTER
    real_issue = adapter.issue_human_decision_token

    def count_issue(**kwargs: Any) -> Any:
        nonlocal issue_calls
        issue_calls += 1
        return real_issue(**kwargs)

    monkeypatch.setattr(adapter, "issue_human_decision_token", count_issue)
    append_attempts = 0

    def fail_receipt_write(*_args: Any, **_kwargs: Any) -> bool:
        nonlocal append_attempts
        append_attempts += 1
        raise OSError("fault injection leaves an applied receipt pending")

    monkeypatch.setattr(
        failure_capture_module,
        "append_jsonl_outbox_event",
        fail_receipt_write,
    )
    real_write = failure_capture_module.write_note_relative
    status_writes = 0

    def count_status_write(*args: Any, **kwargs: Any) -> Any:
        nonlocal status_writes
        status_writes += 1
        return real_write(*args, **kwargs)

    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_status_write)
    client = TestClient(app)
    first_response = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
    )
    assert first_response.status_code == 409, first_response.text
    assert append_attempts == 2
    assert status_writes == 1
    outbox_path.write_text('{"event": malformed\n', encoding="utf-8")
    malformed_source = outbox_path.read_text(encoding="utf-8")

    retry = client.post(f"/api/eval-drafts/{draft.draft_id}/decision", json=payload)

    assert retry.status_code == 409, retry.text
    assert issue_calls == 1
    assert append_attempts == 2
    assert status_writes == 1
    assert outbox_path.read_text(encoding="utf-8") == malformed_source


def test_concurrent_same_decision_posts_reconcile_one_terminal_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "concurrent-eval-disposition.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="concurrent exact decision case",
        trace_id="api-concurrent-disposition",
    )
    assert draft is not None
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": "one exact concurrent decision",
    }

    real_write = failure_capture_module.write_note_relative
    before_write = Barrier(2)
    first_write_completed = Event()
    counter_lock = Lock()
    write_attempts = 0
    status_writes = 0
    write_errors: list[str] = []

    def synchronize_and_write(*args: Any, **kwargs: Any) -> Any:
        nonlocal write_attempts, status_writes
        with counter_lock:
            write_attempts += 1
            attempt = write_attempts
        before_write.wait(timeout=15)
        if attempt > 1 and not first_write_completed.wait(timeout=15):
            raise TimeoutError("first concurrent status write did not complete")
        try:
            result = real_write(*args, **kwargs)
        except Exception as exc:
            with counter_lock:
                write_errors.append(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if attempt == 1:
                first_write_completed.set()
        with counter_lock:
            status_writes += 1
        return result

    monkeypatch.setattr(
        failure_capture_module,
        "write_note_relative",
        synchronize_and_write,
    )

    def post_decision(_: int) -> Any:
        return TestClient(app).post(
            f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(post_decision, (1, 2)))

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert write_attempts == 2
    assert status_writes == 1, write_errors
    assert len(write_errors) == 1
    assert write_errors[0].startswith("KnowledgeWriteConflict:")
    terminal = read_draft(vault, draft.draft_id)
    assert terminal is not None
    assert terminal.status == DRAFT_STATUS_PROMOTED
    assert terminal.decision_token is not None
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
    assert (
        matching[0]["payload"]["decision_token"]["token_id"]
        == terminal.decision_token.token_id
    )


def test_concurrent_initial_and_retry_receipts_converge_before_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, first, _extra, principal_record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    outbox_path = tmp_path / "concurrent-initial-retry-eval-disposition.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    vault = Path(first.path)
    bind_initialized_vault(monkeypatch, vault)
    draft = draft_unknown_classification_case(
        vault_root=vault,
        utterance="initial disposition concurrent with exact retry",
        trace_id="api-concurrent-initial-retry-disposition",
    )
    assert draft is not None
    payload = {
        "action": "promote",
        "decided_by": principal_record.local_operator_role_id,
        "notes": "one exact concurrent decision",
    }

    counter_lock = Lock()
    persist_barrier = Barrier(2)
    first_persist_entered = Event()
    receipt_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    emitted_events: list[dict[str, Any]] = []
    status_writes = 0
    token_issues = 0
    real_persist = failure_capture_module._persist_disposition_authority_receipt
    real_append = failure_capture_module.append_jsonl_outbox_event
    real_write = failure_capture_module.write_note_relative
    adapter = failure_capture_module._GOVERNED_WRITE_ADAPTER
    real_issue_token = adapter.issue_human_decision_token

    def synchronize_receipt_persist(**kwargs: Any) -> None:
        with counter_lock:
            receipt_candidates.append(
                (
                    asdict(kwargs["mutation_receipt"]),
                    asdict(kwargs["authority_receipt"]),
                )
            )
            first_persist_entered.set()
        persist_barrier.wait(timeout=15)
        real_persist(**kwargs)

    def capture_event(*args: Any, **kwargs: Any) -> bool:
        event = args[1] if len(args) > 1 else kwargs["event"]
        with counter_lock:
            emitted_events.append(event.model_dump(mode="json"))
        return real_append(*args, **kwargs)

    def count_status_write(*args: Any, **kwargs: Any) -> Any:
        nonlocal status_writes
        with counter_lock:
            status_writes += 1
        return real_write(*args, **kwargs)

    def count_token_issue(**kwargs: Any) -> Any:
        nonlocal token_issues
        with counter_lock:
            token_issues += 1
        return real_issue_token(**kwargs)

    monkeypatch.setattr(
        failure_capture_module,
        "_persist_disposition_authority_receipt",
        synchronize_receipt_persist,
    )
    monkeypatch.setattr(
        failure_capture_module, "append_jsonl_outbox_event", capture_event
    )
    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_status_write)
    monkeypatch.setattr(adapter, "issue_human_decision_token", count_token_issue)

    def post_decision() -> Any:
        return TestClient(app).post(
            f"/api/eval-drafts/{draft.draft_id}/decision", json=payload
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        initial = pool.submit(post_decision)
        assert first_persist_entered.wait(timeout=15)
        retry = pool.submit(post_decision)
        initial_response = initial.result(timeout=30)
        retry_response = retry.result(timeout=30)

    assert initial_response.status_code == 200, initial_response.text
    assert retry_response.status_code == 200, retry_response.text
    assert initial_response.json() == retry_response.json()
    assert len(receipt_candidates) == 2
    assert receipt_candidates[0] == receipt_candidates[1]
    assert len(emitted_events) == 2
    assert emitted_events[0] == emitted_events[1]
    assert status_writes == 1
    assert token_issues == 1

    terminal = read_draft(vault, draft.draft_id)
    assert terminal is not None
    assert terminal.status == DRAFT_STATUS_PROMOTED
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
    assert matching[0]["payload"]["authority_receipt"] == receipt_candidates[0][1]
