"""Memory candidate review-queue API tests (#1792, SEP-09a).

The READ surface is bounded and provenance-bearing; accept/reject/revise are
governed, receipt-bearing review outcomes whose receipts come from the
runtime's existing machinery (``app.agent_memory.promotion``); defer is
non-terminal queue bookkeeping with no semantic transition and no receipt.

Source authority:
- docs/SYSTEM_ENTRY_POINT/MEMORY_REVIEW_DRAWER.md (issue a, runtime half)
- docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md
- docs/adr/ADR-0009-orientation-memory-candidate-intent.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_queue import (
    MemoryCandidateReviewQueue,
    ReviewDecision,
    ReviewStatus,
)
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from tests.api._vault_test_helpers import bind_initialized_vault, bind_selected_vault

SENSITIVE_CONTENT = "Sensitive raw candidate body that must stay behind the review boundary."


@pytest.fixture(autouse=True)
def _runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bind_initialized_vault(monkeypatch, tmp_path, channel="test")
    monkeypatch.setenv("PKM_CHANNEL", "test")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def queue(monkeypatch: pytest.MonkeyPatch) -> MemoryCandidateReviewQueue:
    fresh = MemoryCandidateReviewQueue()
    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: fresh)
    return fresh


def _candidate(**overrides: Any) -> MemoryCandidate:
    fields: dict[str, Any] = dict(
        title="Observed terse-answer preference",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        content=SENSITIVE_CONTENT,
        source_refs=["session:2026-06-01T09:00:00Z"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
    )
    fields.update(overrides)
    return MemoryCandidate(**fields)


def _decision_url(candidate_id: str) -> str:
    return f"/api/companion/memory/review-queue/{candidate_id}/decision"


def test_review_queue_read_is_bounded_and_provenance_bearing(
    client: TestClient, queue: MemoryCandidateReviewQueue
) -> None:
    pending = _candidate()
    queue.enqueue(pending)
    decided = _candidate(title="Already decided candidate", source_refs=["session:decided"])
    queue.enqueue(decided)
    queue.decide(decided.candidate_id, ReviewDecision.REJECT, decided_by="reviewer:human")

    resp = client.get("/api/companion/memory/review-queue")

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "agent_memory.review_queue"
    assert data["source_ref"]["ref"] == "agent_memory.review_queue"
    assert "not semantic authority" in data["review_callout"].lower()

    # Only pending candidates are up for review.
    assert data["pending_count"] == 1
    assert len(data["candidates"]) == 1
    item = data["candidates"][0]
    assert item["candidate_id"] == pending.candidate_id

    # Why-now reason is explicit and human-legible.
    assert item["why_now"]
    assert "review" in item["why_now"].lower()

    # Provenance is first-class: source refs and derivation chain are present.
    assert item["source_refs"] == ["session:2026-06-01T09:00:00Z"]
    assert item["derived_from"] == "conversation:abc123"
    assert item["generated_by"] == "companion_agent"
    assert item["proposed_memory_type"] == "preference_memory"
    assert item["inferred"] is True

    # Authority posture: a candidate is a proposal, never semantic authority.
    posture = item["authority_posture"]
    assert posture["authority"] == "non_authoritative"
    assert posture["authority_role"] == "candidate"
    assert posture["review_posture"] == "inferred"
    assert posture["semantic_authority"] is False

    # Bounded read: no raw candidate body beyond what the review boundary
    # already admits (the posture projection admits no `content`).
    payload = json.dumps(data)
    assert SENSITIVE_CONTENT not in payload
    assert "content" not in item
    assert "Already decided candidate" not in payload


def test_accept_is_governed_decision(
    client: TestClient, queue: MemoryCandidateReviewQueue
) -> None:
    candidate = _candidate()
    queue.enqueue(candidate)

    resp = client.post(
        _decision_url(candidate.candidate_id),
        json={"action": "accept", "reviewed_by": "reviewer:human", "notes": "Confirmed."},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["candidate_pending"] is False

    # The promotion outcome and receipt come from the runtime's governed
    # machinery (a frozen PromotedMemory artifact), not from endpoint fiat.
    receipt = data["receipt"]
    assert receipt is not None
    assert receipt["kind"] == "agent_memory.review_decision"
    assert receipt["outcome"] == "accepted"
    assert receipt["candidate_id"] == candidate.candidate_id
    assert receipt["decided_by"] == "reviewer:human"
    assert receipt["decided_at"]
    assert receipt["receipt_id"]
    assert receipt["source"] == "agent_memory.promotion"

    entry = queue.get(candidate.candidate_id)
    assert entry.status is ReviewStatus.PROMOTED
    assert entry.decided_by == "reviewer:human"
    recallable = [e.candidate_id for e in queue.recallable_for_working_context()]
    assert recallable == [candidate.candidate_id]

    # Governed refusal: semantic promotion of an inferred single-source
    # candidate is refused by the runtime machinery. The endpoint surfaces the
    # runtime outcome; it must not invent a promotion or a receipt, and the
    # candidate must remain pending (not half-promoted).
    semantic = _candidate(
        title="Inferred semantic claim", memory_type=MemoryType.SEMANTIC_MEMORY
    )
    queue.enqueue(semantic)
    refused = client.post(
        _decision_url(semantic.candidate_id),
        json={"action": "accept", "reviewed_by": "reviewer:human"},
    )
    assert refused.status_code == 409
    assert queue.get(semantic.candidate_id).status is ReviewStatus.PENDING
    recallable = [e.candidate_id for e in queue.recallable_for_working_context()]
    assert recallable == [candidate.candidate_id]

    # Accountable review semantics come from the governed boundary: a blank
    # reviewer identity is refused and no transition is recorded.
    anonymous = _candidate(title="Anonymous decision attempt")
    queue.enqueue(anonymous)
    refused_anonymous = client.post(
        _decision_url(anonymous.candidate_id),
        json={"action": "accept", "reviewed_by": "   "},
    )
    assert refused_anonymous.status_code == 409
    assert queue.get(anonymous.candidate_id).status is ReviewStatus.PENDING


def test_reject_and_revise_are_receipted_review_outcomes_not_promotions(
    client: TestClient, queue: MemoryCandidateReviewQueue
) -> None:
    to_reject = _candidate(title="Candidate to reject")
    to_revise = _candidate(title="Candidate to revise")
    queue.enqueue(to_reject)
    queue.enqueue(to_revise)

    reject_resp = client.post(
        _decision_url(to_reject.candidate_id),
        json={"action": "reject", "reviewed_by": "reviewer:human", "notes": "Not durable."},
    )
    assert reject_resp.status_code == 200
    reject_data = reject_resp.json()
    assert reject_data["status"] == "rejected"
    reject_receipt = reject_data["receipt"]
    assert reject_receipt is not None
    assert reject_receipt["kind"] == "agent_memory.review_decision"
    assert reject_receipt["outcome"] == "rejected"
    assert reject_receipt["candidate_id"] == to_reject.candidate_id
    assert reject_receipt["decided_by"] == "reviewer:human"
    assert reject_receipt["decided_at"]
    assert reject_receipt["receipt_id"]
    # Rejection is a durable lifecycle outcome, retained and inspectable.
    assert queue.get(to_reject.candidate_id).status is ReviewStatus.REJECTED

    revise_resp = client.post(
        _decision_url(to_revise.candidate_id),
        json={
            "action": "revise",
            "reviewed_by": "reviewer:human",
            "notes": "Needs narrower wording.",
            "revision": {"title": "Narrowed candidate"},
        },
    )
    assert revise_resp.status_code == 200
    revise_data = revise_resp.json()
    assert revise_data["status"] == "revised"
    revise_receipt = revise_data["receipt"]
    assert revise_receipt is not None
    assert revise_receipt["outcome"] == "revised"
    assert revise_receipt["candidate_id"] == to_revise.candidate_id
    assert revise_receipt["decided_by"] == "reviewer:human"
    assert revise_receipt["receipt_id"]
    assert revise_receipt["receipt_id"] != reject_receipt["receipt_id"]
    assert queue.get(to_revise.candidate_id).status is ReviewStatus.REVISED

    # Revision goes back for review as a new pending entry referencing the
    # original; earlier evidence is preserved, nothing is promoted.
    revision_id = revise_data["revision_candidate_id"]
    assert revision_id
    revision_entry = queue.get(revision_id)
    assert revision_entry.status is ReviewStatus.PENDING
    assert revision_entry.revision_of == to_revise.candidate_id
    assert revision_entry.title == "Narrowed candidate"

    # Neither reject nor revise is a promotion: nothing became recallable
    # authoritative memory.
    assert queue.recallable_for_working_context() == []

    # The pending revision is back on the read surface for its own review.
    read = client.get("/api/companion/memory/review-queue").json()
    assert [c["candidate_id"] for c in read["candidates"]] == [revision_id]


def test_defer_is_non_terminal_and_unreceipted(
    client: TestClient, queue: MemoryCandidateReviewQueue
) -> None:
    candidate = _candidate(title="Deferred candidate")
    queue.enqueue(candidate)

    resp = client.post(_decision_url(candidate.candidate_id), json={"action": "defer"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deferred"
    assert data["candidate_pending"] is True
    # No receipt is produced or invented for a non-terminal action.
    assert data["receipt"] is None
    assert data.get("revision_candidate_id") is None

    # No semantic transition: the entry is untouched and still pending.
    entry = queue.get(candidate.candidate_id)
    assert entry.status is ReviewStatus.PENDING
    assert entry.decision is None
    assert entry.decided_by is None
    assert entry.decided_at is None
    assert queue.decided() == []
    assert queue.recallable_for_working_context() == []

    # Defer is repeatable bookkeeping and the candidate stays on the read surface.
    again = client.post(_decision_url(candidate.candidate_id), json={"action": "defer"})
    assert again.status_code == 200
    read = client.get("/api/companion/memory/review-queue").json()
    assert read["pending_count"] == 1
    assert read["candidates"][0]["candidate_id"] == candidate.candidate_id

    # Unknown candidates are a read miss, not an invented decision surface.
    missing = client.post(_decision_url("no-such-candidate"), json={"action": "defer"})
    assert missing.status_code == 404


def test_terminal_decision_without_selected_vault_returns_picker(
    client: TestClient,
    queue: MemoryCandidateReviewQueue,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_local_path = tmp_path / "app-local.md"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    candidate = _candidate(title="No-vault decision attempt")
    queue.enqueue(candidate)

    resp = client.post(
        _decision_url(candidate.candidate_id),
        json={"action": "reject", "reviewed_by": "reviewer:human"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "vault_selection_required"
    assert data["reason"] == "no_vault_bound"
    assert queue.get(candidate.candidate_id).status is ReviewStatus.PENDING


def test_terminal_decision_picker_uses_active_environment_configured_root(
    client: TestClient,
    queue: MemoryCandidateReviewQueue,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_local_path = tmp_path / "app-local.md"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    monkeypatch.setenv("PKM_ENVIRONMENT", "test")
    base_vault = tmp_path / "base-vault"
    test_vault = tmp_path / "test-vault"
    base_vault.mkdir()
    test_vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(base_vault))
    monkeypatch.setenv("VAULT_ROOT_TEST", str(test_vault))
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    candidate = _candidate(title="Channel-specific no-vault decision attempt")
    queue.enqueue(candidate)

    resp = client.post(
        _decision_url(candidate.candidate_id),
        json={"action": "reject", "reviewed_by": "reviewer:human"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "vault_selection_required"
    assert data["reason"] == "no_vault_bound"
    assert data["configured_vault_root"] == str(test_vault.resolve())
    assert queue.get(candidate.candidate_id).status is ReviewStatus.PENDING


def test_terminal_decision_with_uninitialized_vault_returns_picker(
    client: TestClient,
    queue: MemoryCandidateReviewQueue,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "uninitialized-vault"
    vault.mkdir()
    bind_selected_vault(monkeypatch, vault, store_dir=tmp_path)
    candidate = _candidate(title="Uninitialized-vault decision attempt")
    queue.enqueue(candidate)

    resp = client.post(
        _decision_url(candidate.candidate_id),
        json={"action": "reject", "reviewed_by": "reviewer:human"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "vault_selection_required"
    assert data["reason"] == "no_vault_bound"
    assert data["configured_vault_root"] == str(vault.resolve())
    assert queue.get(candidate.candidate_id).status is ReviewStatus.PENDING
