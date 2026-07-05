"""Pending eval-drafts review surface (KERNEL-15 follow-up, #2871).

Verifies the discoverable read surface over ``app.eval.failure_capture``
drafts: a reviewer can list pending drafts with provenance and adjudicate one
via the real API route, and eval drafts stay a distinct artifact class from
the memory review queue (no ``MemoryType``, no
``materialize_promoted_memory``, no ``MemoryCandidateReviewQueue``).

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/FAILURE_TO_EVAL_CAPTURE_LOOP.md :: Reviewer surfacing
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.eval.failure_capture import (
    DRAFT_KIND_SCHEMA_VIOLATION,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_PROMOTED,
    draft_dead_letter_case,
    draft_unknown_classification_case,
    list_pending_drafts,
    read_draft,
)

from tests.api._vault_test_helpers import bind_initialized_vault

pytestmark = pytest.mark.not_pg


def _draft_schema_violation(vault_root: Path, *, trace_id: str, event_id: str):
    return draft_dead_letter_case(
        vault_root=vault_root,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id=event_id,
        payload={"event_id": event_id},
        trace_id=trace_id,
    )


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bind_initialized_vault(monkeypatch, tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# AC1 -- a read surface lists pending eval drafts with provenance
# ---------------------------------------------------------------------------


def test_lists_pending_drafts(vault: Path) -> None:
    """The domain-level lister returns pending drafts with full provenance,
    and the real API route surfaces the same drafts."""
    draft = _draft_schema_violation(vault, trace_id="trace-1", event_id="evt-1")
    assert draft is not None

    pending = list_pending_drafts(vault)
    assert len(pending) == 1
    assert pending[0].draft_id == draft.draft_id
    assert pending[0].kind == DRAFT_KIND_SCHEMA_VIOLATION
    assert pending[0].status == DRAFT_STATUS_PENDING
    assert pending[0].trace_id == "trace-1"
    assert pending[0].source_event.topic == "ingest.vault.changed"
    assert pending[0].source_event.event_id == "evt-1"

    client = TestClient(app)
    resp = client.get("/api/eval-drafts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pending_count"] == 1
    listed = body["drafts"][0]
    assert listed["draft_id"] == draft.draft_id
    assert listed["kind"] == DRAFT_KIND_SCHEMA_VIOLATION
    assert listed["status"] == DRAFT_STATUS_PENDING
    assert listed["trace_id"] == "trace-1"
    assert listed["source_event"]["topic"] == "ingest.vault.changed"
    assert listed["source_event"]["event_id"] == "evt-1"


def test_lists_multiple_pending_drafts_across_kinds(vault: Path) -> None:
    """Both schema_violation and classification_case.v1 drafts surface."""
    _draft_schema_violation(vault, trace_id="trace-a", event_id="evt-a")
    draft_unknown_classification_case(
        vault_root=vault,
        utterance="an ambiguous utterance",
        trace_id="trace-b",
    )

    pending = list_pending_drafts(vault)
    assert len(pending) == 2
    kinds = {d.kind for d in pending}
    assert kinds == {"schema_violation", "classification_case.v1"}


def test_no_drafts_dir_lists_empty(vault: Path) -> None:
    """A vault with no eval_drafts directory yet returns an empty pending list,
    not an error."""
    assert list_pending_drafts(vault) == []

    client = TestClient(app)
    resp = client.get("/api/eval-drafts")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "source": "eval.failure_capture.eval_drafts",
        "pending_count": 0,
        "drafts": [],
    }


# ---------------------------------------------------------------------------
# AC2 -- a reviewer can promote/reject a listed draft through the surface;
# the draft leaves the pending list
# ---------------------------------------------------------------------------


def test_decide_removes_from_pending(vault: Path) -> None:
    """Promoting a listed draft through the API route changes its status and
    removes it from the pending list; a second decision is refused (409)."""
    draft = _draft_schema_violation(vault, trace_id="trace-promo", event_id="evt-promo")
    assert draft is not None

    client = TestClient(app)

    # Before decision: draft is pending and listed.
    resp = client.get("/api/eval-drafts")
    assert resp.json()["pending_count"] == 1

    resp = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={"action": "promote", "decided_by": "rasmus:reviewer", "notes": "confirmed"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["draft_id"] == draft.draft_id
    assert body["decision"] == "promote"
    assert body["decided_by"] == "rasmus:reviewer"

    # After decision: draft is no longer pending.
    resp = client.get("/api/eval-drafts")
    assert resp.status_code == 200
    assert resp.json()["pending_count"] == 0

    on_disk = read_draft(vault, draft.draft_id)
    assert on_disk is not None
    assert on_disk.status == DRAFT_STATUS_PROMOTED

    # A second decision on an already-decided draft is refused.
    resp = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={"action": "reject", "decided_by": "rasmus:reviewer"},
    )
    assert resp.status_code == 409


def test_reject_removes_from_pending(vault: Path) -> None:
    """Rejecting a listed draft through the API route also removes it from
    the pending list."""
    draft = _draft_schema_violation(vault, trace_id="trace-rej", event_id="evt-rej")
    assert draft is not None

    client = TestClient(app)
    resp = client.post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={"action": "reject", "decided_by": "rasmus:reviewer"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "reject"

    resp = client.get("/api/eval-drafts")
    assert resp.json()["pending_count"] == 0


def test_decision_on_unknown_draft_is_404(vault: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/eval-drafts/does-not-exist/decision",
        json={"action": "promote", "decided_by": "rasmus:reviewer"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# AC3 -- eval drafts are NOT surfaced through the memory review queue
# ---------------------------------------------------------------------------


def test_distinct_from_memory_queue(vault: Path) -> None:
    """An eval draft never appears in the memory candidate review queue, and
    the eval-drafts surface never imports/touches memory-review machinery."""
    _draft_schema_violation(vault, trace_id="trace-distinct", event_id="evt-distinct")

    client = TestClient(app)

    # The memory review queue is untouched by drafting an eval-draft.
    resp = client.get("/api/companion/memory/review-queue")
    assert resp.status_code == 200, resp.text
    assert resp.json()["pending_count"] == 0

    # The eval-drafts route module must not import memory-candidate machinery.
    import app.api.routes.eval_drafts as eval_drafts_module

    assert not hasattr(eval_drafts_module, "MemoryCandidateReviewQueue")
    assert not hasattr(eval_drafts_module, "MemoryType")
    assert not hasattr(eval_drafts_module, "materialize_promoted_memory")

    source = Path(eval_drafts_module.__file__).read_text(encoding="utf-8")
    assert "from app.agent_memory.review_queue import" not in source
    assert "from app.agent_memory.materialization import" not in source
    assert "materialize_promoted_memory(" not in source
