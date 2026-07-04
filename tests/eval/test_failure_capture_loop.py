"""Failure-to-eval capture loop (KERNEL-15, #2777).

Verifies that the two worst silent failures in the runtime — schema-violation
dead-letters and UNKNOWN classifications — are drafted as human-reviewable
eval-case candidates instead of vanishing into logs, exercised from their real
production call sites:

- a schema-violation dead-letter drafted from
  ``app.workers.outbox_worker._dead_letter_outbox_message`` (the real poison-row
  dead-letter emission site), and
- an UNKNOWN classification drafted from the real ``/coauthor`` UNKNOWN landing
  branch in ``app.api.routes.canvas``.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/FAILURE_TO_EVAL_CAPTURE_LOOP.md
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.workers.outbox_worker as outbox_worker
from app.api.app import app
from app.eval.failure_capture import (
    DRAFT_KIND_CLASSIFICATION_CASE,
    DRAFT_KIND_SCHEMA_VIOLATION,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_PROMOTED,
    promote_draft,
    read_draft,
)
from app.vault.paths import get_vault_system_dir_rel
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drafts_dir(vault_root: Path) -> Path:
    return vault_root / get_vault_system_dir_rel(vault_root) / "eval_drafts"


def _find_single_draft_id(vault_root: Path) -> str:
    drafts = list(_drafts_dir(vault_root).glob("*.md"))
    assert len(drafts) == 1, f"expected exactly one draft, found {drafts}"
    return drafts[0].stem


# ---------------------------------------------------------------------------
# AC1 — schema_violation dead-letter drafts a case with provenance
# ---------------------------------------------------------------------------


def test_dead_letter_drafts_case_with_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A schema_violation dead-letter, emitted through the real production
    dead-letter path, produces a draft eval-case companion-note artifact with
    full provenance (trace_id, source event, payload snapshot)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", lambda *a, **k: None)
    monkeypatch.setattr(outbox_worker, "_use_db_outbox", lambda: False)

    # Real production dead-letter emission entrypoint (the poison-row path).
    outbox_worker._dead_letter_outbox_message(
        "ingest.vault.changed",
        {"trace_id": "trace-schema-1", "event_id": "evt-schema-1"},
        message_id="row-schema-1",
        reason="schema_violation:missing_required_field",
        attempts=5,
        trace_id="trace-schema-1",
        error="payload failed schema validation",
    )

    draft_id = _find_single_draft_id(vault)
    draft = read_draft(vault, draft_id)
    assert draft is not None
    assert draft.kind == DRAFT_KIND_SCHEMA_VIOLATION
    assert draft.status == DRAFT_STATUS_PENDING
    assert draft.trace_id == "trace-schema-1"
    assert draft.source_event.topic == "ingest.vault.changed"
    assert draft.source_event.event_id == "evt-schema-1"
    assert draft.payload_snapshot["reason"] == "schema_violation:missing_required_field"
    assert draft.payload_snapshot["payload"]["event_id"] == "evt-schema-1"


def test_non_schema_violation_dead_letter_is_not_drafted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dead-letter for a different reason family (e.g. dispatch_failed) must
    not produce a draft — this task is bounded to schema_violation capture."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", lambda *a, **k: None)
    monkeypatch.setattr(outbox_worker, "_use_db_outbox", lambda: False)

    outbox_worker._dead_letter_outbox_message(
        "ingest.vault.changed",
        {"trace_id": "trace-other", "event_id": "evt-other"},
        message_id="row-other",
        reason="dispatch_failed:ValueError",
        attempts=5,
        trace_id="trace-other",
        error="boom",
    )

    assert not _drafts_dir(vault).exists() or not list(_drafts_dir(vault).glob("*.md"))


# ---------------------------------------------------------------------------
# AC2 — UNKNOWN classification drafts a classification_case.v1 candidate
# ---------------------------------------------------------------------------


def _degraded_completion(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
    # A completion that fails schema validation -> explicit UNKNOWN (KERNEL-07).
    return "MOCK_ASK_ANSWER: not valid json"


@pytest.fixture(autouse=True)
def _clear_canvas_sessions():
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    yield
    canvas_module._sessions.clear()


@pytest.fixture()
def _canvas_vault(tmp_path: Path) -> Path:
    note = tmp_path / "note.md"
    note.write_text(
        "---\nuuid: note-uuid-failure-capture\n---\n\n# Hello\n\nOriginal body.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_unknown_drafts_classification_case(
    monkeypatch: pytest.MonkeyPatch, _canvas_vault: Path
) -> None:
    """A real UNKNOWN classification landing (degraded classifier completion,
    real ``/coauthor`` route) produces a draft ``classification_case.v1``
    candidate with provenance."""
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: _canvas_vault)
    monkeypatch.setattr(canvas_module, "_get_vault_root_or_picker", lambda **_: _canvas_vault)
    monkeypatch.setattr(
        canvas_module, "_intent_classifier_completion", lambda: _degraded_completion
    )

    client = TestClient(app)
    resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "coauthor"}
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "expand the introduction with unclear vague nonsense"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "unknown_intent_reask"

    draft_id = _find_single_draft_id(_canvas_vault)
    draft = read_draft(_canvas_vault, draft_id)
    assert draft is not None
    assert draft.kind == DRAFT_KIND_CLASSIFICATION_CASE
    assert draft.status == DRAFT_STATUS_PENDING
    assert draft.source_event.topic == "chat.intent_classification"
    assert draft.payload_snapshot["utterance"] == "expand the introduction with unclear vague nonsense"
    assert draft.payload_snapshot["case_shape"] == DRAFT_KIND_CLASSIFICATION_CASE


# ---------------------------------------------------------------------------
# AC3 — draft writes are WriteGuard-gated
# ---------------------------------------------------------------------------


def test_draft_is_write_guard_gated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A blocked WriteGuard state prevents the dead-letter draft from being
    written at all, asserted through the production write path
    (``draft_dead_letter_case`` calls ``WriteGuard.assert_writes_allowed``
    before any file I/O — matching ``materialize_promoted_memory``)."""
    from app.eval.failure_capture import draft_dead_letter_case

    vault = tmp_path / "vault"
    vault.mkdir()
    blocked_guard = WriteGuard(lambda: {"state": "safe_mode", "reason": "operator hold"})

    with pytest.raises(WritesBlockedError):
        draft_dead_letter_case(
            vault_root=vault,
            topic="ingest.vault.changed",
            reason="schema_violation:missing_required_field",
            event_id="evt-blocked",
            payload={"event_id": "evt-blocked"},
            trace_id="trace-blocked",
            write_guard=blocked_guard,
        )

    assert not (vault / get_vault_system_dir_rel(vault) / "eval_drafts").exists()


def test_worker_dead_letter_draft_is_best_effort_on_write_guard_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """From the real worker dead-letter site: a blocked WriteGuard must not
    break the dead-letter audit itself — the draft attempt is swallowed and
    logged, never re-raised."""
    from app.write_guard import DEFAULT_WRITE_GUARD

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", lambda *a, **k: None)
    monkeypatch.setattr(outbox_worker, "_use_db_outbox", lambda: False)
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "operator hold"},
    )

    # Must not raise even though the draft write is blocked.
    outbox_worker._dead_letter_outbox_message(
        "ingest.vault.changed",
        {"trace_id": "trace-blocked-2", "event_id": "evt-blocked-2"},
        message_id="row-blocked-2",
        reason="schema_violation:missing_required_field",
        attempts=5,
        trace_id="trace-blocked-2",
        error="payload failed schema validation",
    )

    assert not (vault / get_vault_system_dir_rel(vault) / "eval_drafts").exists()


# ---------------------------------------------------------------------------
# AC4 — no auto-promotion
# ---------------------------------------------------------------------------


def test_no_auto_promotion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A drafted case is not in the golden dataset until a recorded human
    decision promotes it: on write it is PENDING; only an explicit
    ``promote_draft`` call (naming a reviewer) moves it to PROMOTED."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", lambda *a, **k: None)
    monkeypatch.setattr(outbox_worker, "_use_db_outbox", lambda: False)

    outbox_worker._dead_letter_outbox_message(
        "ingest.vault.changed",
        {"trace_id": "trace-promo", "event_id": "evt-promo"},
        message_id="row-promo",
        reason="schema_violation:missing_required_field",
        attempts=5,
        trace_id="trace-promo",
        error="payload failed schema validation",
    )

    draft_id = _find_single_draft_id(vault)
    draft = read_draft(vault, draft_id)
    assert draft is not None
    assert draft.status == DRAFT_STATUS_PENDING

    # No auto-promotion: nothing promotes the draft without an explicit call.
    still_pending = read_draft(vault, draft_id)
    assert still_pending is not None
    assert still_pending.status == DRAFT_STATUS_PENDING

    # An explicit, reviewer-named decision is the only path to PROMOTED.
    decision = promote_draft(vault, draft_id, decided_by="rasmus:reviewer", notes="confirmed")
    assert decision.decision == "promote"
    assert decision.decided_by == "rasmus:reviewer"

    promoted = read_draft(vault, draft_id)
    assert promoted is not None
    assert promoted.status == DRAFT_STATUS_PROMOTED

    # A second promotion attempt on an already-decided draft is refused.
    from app.eval.failure_capture import PromotionDecisionError

    with pytest.raises(PromotionDecisionError):
        promote_draft(vault, draft_id, decided_by="rasmus:reviewer")


def test_promote_requires_decided_by(tmp_path: Path) -> None:
    """An empty decided_by is refused — promotion must name a reviewer."""
    from app.eval.failure_capture import PromotionDecisionError

    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(PromotionDecisionError):
        promote_draft(vault, "nonexistent-draft", decided_by="   ")
