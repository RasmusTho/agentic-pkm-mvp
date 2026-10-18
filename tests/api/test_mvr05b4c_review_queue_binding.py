"""MVR-05B4c1 (#6211): the memory review queue is keyed by its producing vault binding.

``MemoryCandidateReviewQueue`` is one process-wide object. Every entry carries the
binding that produced it and is keyed by (binding, candidate id), so two bindings
that enqueue the same candidate id keep independent entries. Scoped
``/memory/review-queue``, ``/vault-browser`` agent-memory posture and the
``/orientation`` memory summary answer from the request binding's entries only;
an unstamped legacy entry is never shown to a scoped read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_queue import (
    MemoryCandidateReviewQueue,
    ReviewDecision,
    ReviewQueueError,
    ReviewStatus,
)
from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import companion as companion_routes
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg

SHARED_NOTE_UUID = "shared-note-uuid-6211"
SHARED_NOTE_PATH = "shared.md"


@pytest.fixture()
def two_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.vault.manager as vault_manager_module

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    for root in (Path(first.path), Path(second.path)):
        initialize_test_vault(root)
        (root / SHARED_NOTE_PATH).write_text(
            f"---\ntitle: Shared\nuuid: {SHARED_NOTE_UUID}\nkind: human_note\n"
            "review_state: reviewed\ntrust: assert\n---\n\nBody.\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "leave-point.sqlite3"))
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    queue = MemoryCandidateReviewQueue()
    monkeypatch.setattr(companion_routes, "_MEMORY_CANDIDATE_REVIEW_QUEUE", queue)
    return TestClient(app), first, second, queue


def _headers(client: TestClient, binding_id: str) -> dict[str, str]:
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding_id]}
    )
    assert created.status_code == 201, created.text
    return {"X-Active-Context-Session": created.json()["context_selection_id"]}


def _candidate(candidate_id: str, title: str) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title=title,
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=[f"artifact_uuid:{SHARED_NOTE_UUID}", f"note_path:{SHARED_NOTE_PATH}"],
        generated_by="agent_memory.test",
    )


def test_scoped_review_queue_reads_only_request_binding(two_bindings, monkeypatch) -> None:
    client, first, second, queue = two_bindings
    queue.enqueue(_candidate("cand-a", "From A"), binding=first.vault_binding_id)
    queue.enqueue(_candidate("cand-b", "From B"), binding=second.vault_binding_id)
    queue.enqueue(_candidate("cand-legacy", "Unstamped legacy"))
    headers_a = _headers(client, first.vault_binding_id)
    headers_b = _headers(client, second.vault_binding_id)

    def forbid(**_kwargs):
        raise AssertionError("a scoped read must not reconfigure the process queue")

    before = dict(queue._entries)
    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(queue, "configure_reconciliation", forbid)
        a = client.get("/api/companion/memory/review-queue", headers=headers_a)
        b = client.get("/api/companion/memory/review-queue", headers=headers_b)

    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    assert [c["candidate_id"] for c in a.json()["candidates"]] == ["cand-a"]
    assert [c["candidate_id"] for c in b.json()["candidates"]] == ["cand-b"]
    assert a.json()["pending_count"] == 1 and b.json()["pending_count"] == 1
    assert "cand-legacy" not in a.text + b.text
    assert queue._entries == before

    # Carrier-free behavior is unchanged: a direct call is the legacy view, which
    # shows the unstamped entry (and never another binding's).
    legacy = companion_routes.get_memory_review_queue(None, None)
    assert [c.candidate_id for c in legacy.candidates] == ["cand-legacy"]

    # A zero-binding selection owns no entries; a blank carrier is scoped and invalid.
    empty = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": []})
    assert empty.status_code == 201, empty.text
    zero = client.get(
        "/api/companion/memory/review-queue",
        headers={"X-Active-Context-Session": empty.json()["context_selection_id"]},
    )
    assert zero.status_code == 200 and zero.json()["candidates"] == []
    blank = client.get(
        "/api/companion/memory/review-queue", headers={"X-Active-Context-Session": ""}
    )
    assert blank.status_code >= 400
    assert "cand-" not in blank.text


def _posture(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get("/api/companion/vault-browser", headers=headers)
    assert response.status_code == 200, response.text
    note = next(n for n in response.json()["notes"] if n["note_path"].endswith(SHARED_NOTE_PATH))
    return note["agent_memory_posture"]


def test_scoped_vault_browser_memory_posture_is_binding_stamped(two_bindings) -> None:
    client, first, second, queue = two_bindings
    queue.enqueue(_candidate("cand-a", "From A"), binding=first.vault_binding_id)
    queue.enqueue(_candidate("cand-b", "From B"), binding=second.vault_binding_id)
    queue.enqueue(_candidate("cand-legacy", "Unstamped legacy"))

    posture_a = _posture(client, _headers(client, first.vault_binding_id))
    posture_b = _posture(client, _headers(client, second.vault_binding_id))

    assert [i["candidate_id"] for i in posture_a["items"]] == ["cand-a"]
    assert [i["candidate_id"] for i in posture_b["items"]] == ["cand-b"]
    assert posture_a["counts"]["pending"] == 1 and posture_a["state"] == "pending"


def test_scoped_orientation_memory_summary_counts_only_request_binding(two_bindings) -> None:
    client, first, second, queue = two_bindings
    queue.enqueue(_candidate("cand-a1", "A1"), binding=first.vault_binding_id)
    queue.enqueue(_candidate("cand-a2", "A2"), binding=first.vault_binding_id)
    queue.enqueue(_candidate("cand-b", "B"), binding=second.vault_binding_id)
    queue.enqueue(_candidate("cand-legacy", "Legacy"))

    def memory(binding_id: str) -> dict:
        response = client.get(
            "/api/companion/orientation", headers=_headers(client, binding_id)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "memory_source_unavailable" not in body.get("degraded_reasons", [])
        return body["memory"]

    assert memory(first.vault_binding_id)["pending_candidate_count"] == 2
    assert memory(second.vault_binding_id)["pending_candidate_count"] == 1


def test_same_candidate_id_in_two_bindings_stays_independent(two_bindings) -> None:
    client, first, second, queue = two_bindings
    a, b = first.vault_binding_id, second.vault_binding_id

    entry_a = queue.enqueue(_candidate("cand-same", "A's"), binding=a)
    entry_b = queue.enqueue(_candidate("cand-same", "B's"), binding=b)
    assert entry_a.binding_id == a and entry_b.binding_id == b
    with pytest.raises(ReviewQueueError):
        queue.enqueue(_candidate("cand-same", "A again"), binding=a)

    # Lookup and decision act on the binding's own entry only.
    assert queue.get("cand-same", binding=a).title == "A's"
    assert queue.get("cand-same", binding=b).title == "B's"
    decided = queue.decide("cand-same", ReviewDecision.REJECT, decided_by="reviewer", binding=a)
    assert decided.status is ReviewStatus.REJECTED
    assert queue.get("cand-same", binding=b).status is ReviewStatus.PENDING
    with pytest.raises(ReviewQueueError):
        queue.decide("cand-same", ReviewDecision.REJECT, decided_by="reviewer", binding=a)

    # Scoped route reads: A's decided entry is gone from pending, B's remains.
    pending_a = client.get(
        "/api/companion/memory/review-queue", headers=_headers(client, a)
    ).json()
    pending_b = client.get(
        "/api/companion/memory/review-queue", headers=_headers(client, b)
    ).json()
    assert pending_a["candidates"] == []
    assert [c["title"] for c in pending_b["candidates"]] == ["B's"]


def test_legacy_view_never_sees_foreign_binding_entries() -> None:
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(_candidate("cand-x", "foreign"), binding="other-binding")
    assert queue.pending() == []
    with pytest.raises(ReviewQueueError):
        queue.get("cand-x")
    assert queue.snapshot_for_binding("other-binding").get("cand-x", binding="other-binding")


def test_companion_discovery_producer_stamps_and_dedups_per_binding() -> None:
    from app.agent_memory.companion_aware import (
        SynthesisCompanion,
        discover_candidates_from_companions,
    )

    companion = SynthesisCompanion(
        companion_for=SHARED_NOTE_UUID,
        target_path=SHARED_NOTE_PATH,
        candidates={"cand-d": _candidate("cand-d", "Discovered")},
        generated_by="agent_memory.test",
    )
    queue = MemoryCandidateReviewQueue()

    discover_candidates_from_companions([companion], queue, binding="binding-1")
    discover_candidates_from_companions([companion], queue, binding="binding-2")
    discover_candidates_from_companions([companion], queue, binding="binding-1")

    assert [e.binding_id for e in queue.pending(binding="binding-1")] == ["binding-1"]
    assert [e.binding_id for e in queue.pending(binding="binding-2")] == ["binding-2"]
    assert queue.pending() == []
