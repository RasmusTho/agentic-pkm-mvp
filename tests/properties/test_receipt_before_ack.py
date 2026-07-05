"""P-5 receipt-before-ack ordering property (#2912).

Purpose: generalize the T-capture shape (``app/api/routes/capture.py`` -- ACK
only after the event/receipt row persists, else
``authority_receipt_persistence_failed``) to the registered mutating
transition list. An effect whose accountability record can be lost was never
accountable.

Derivation: ``docs/testing/invariant-synthesis-2026-07.md :: P-5`` and
``docs/architecture/formal-model.md :: 2.1`` (T-capture reference shape).
Q3's durability residue: D-1 settings receipts fixed (#2787); the
D-7-adjacent residue this issue closes is
``app/agents/reviewer/agent.py`` and ``app/agents/set_evaluator/agent.py``
re-swallowing at the call site (``try: insert_decision(...) except
Exception: pass``) what #2788 made fail-loud in ``insert_decision`` itself
(``docs/architecture/runtime-semantics.md :: Divergences`` D-7).

Registered transition list (this issue's start list; extending it is a
follow-up per Out of Scope):

  1. **T-capture** (``app/api/routes/capture.py::capture_to_inbox``) -- the
     passing exemplar this property generalizes from. Already fail-loud:
     ``_emit_capture_event`` raises ``CaptureEventPersistenceError`` when
     neither the JSONL nor DB outbox sink persists, and the route converts
     that into a withheld-ack 500 (``authority_receipt_persistence_failed``).
  2. **T-review-decide** (``app/api/routes/companion.py::
     post_memory_review_decision``, reject branch) -- already fail-loud:
     ``decision_store.record_decision(...)`` is called with no try/except
     around it before the response is built, so a raising decision store
     propagates uncaught (FastAPI turns it into an unhandled 500) rather
     than acking a lost receipt.
  3. **Reviewer decide** (``app/agents/reviewer/agent.py::review``) -- fixed
     by this issue. Was ``try: insert_decision(...) except Exception: pass``;
     now logs and re-raises, matching the pre-existing propagate-uncaught
     contract of every caller (the LangGraph ``_act`` node in
     ``app/agents/reviewer/graph.py``, the CLI dispatcher in
     ``app/agents/runner.py``, and the backfill job loop in
     ``app/jobs/backfill.py`` -- none of which caught or tolerated the
     swallow, so no caller's contract changes).
  4. **Set-evaluator decide** (``app/agents/set_evaluator/agent.py::
     evaluate_object``) -- same fix, same shape, same caller set
     (``app/agents/set_evaluator/graph.py``, ``app/agents/runner.py``,
     ``app/jobs/backfill.py``).
  5. **T-promote** (``app/promotion/consumer.py::
     consume_promotion_intent_payload``, DB-outbox path) -- already
     fail-loud: ``_emit_db_event`` calls ``write_outbox_event``, which
     raises on a real write-time failure (no idempotency-key swallow path
     for a raising store); ``_handle_promotion_payload`` has no try/except
     around ``emit(...)``, so the exception propagates out of
     ``consume_promotion_intent_payload`` uncaught.
  6. **T-panel-confirm** (``app/panel/confirmation.py::
     PanelConfirmationService.confirm`` via ``_emit_projection_event``) --
     fixed by #2962 (follow-up of this module's #2912, which explicitly
     out-of-scoped it). Was ``try: append_jsonl_outbox_event(...) /
     write_outbox_event(...) except Exception: logger.debug(...)`` with an
     unconditional ``return evt.event_id`` -- so a lost ``panel.action.logged``
     / ``panel.action.blocked`` receipt was acked as ``status="logged"`` with a
     receipt_id. Now ``_emit_projection_event`` tracks an ``emitted`` flag
     across both sinks (JSONL required, DB mirrored when pg) and raises
     ``PanelReceiptPersistenceError`` when neither persists; the
     ``/api/panel/confirm`` route maps it to a withheld-ack 500
     (``authority_receipt_persistence_failed`` / ``state=not_acknowledged``),
     mirroring T-capture.

Each registered transition gets one test: inject a failing
event/receipt-store seam (raises on insert) -> invoke the transition's real
entry point -> assert the result is a failure (raised exception or
non-2xx/non-success HTTP response), never a success-with-lost-receipt.

Ordering assertion (second operation class per the spec): with a *recording*
(not raising) store, assert the receipt/decision insert happens-before the
ACK point -- i.e. the insert is observed at all once the transition
succeeds, pinning "insert then ack", not merely "insert xor ack".

Only ``STORE_BACKEND=memory``/JSONL-backed seams are exercised (``not pg``,
no Postgres dependency) -- consistent with every other ``tests/properties/*``
module's CI placement.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.capture as capture_module
import app.agents.reviewer.agent as reviewer_agent_module
import app.agents.set_evaluator.agent as set_evaluator_agent_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_queue import MemoryCandidateReviewQueue
from app.api.app import app
from app.objects import DomainObject, ObjectStore
from app.promotion.consumer import consume_promotion_intent_payload, reset_promotion_dedup_store
from tests.api._vault_test_helpers import bind_initialized_vault

import app.api.routes.companion as companion_module
import app.panel.confirmation as panel_confirm_module
from app.agents.panel.writeback import stable_action_id
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
    PanelRuntimeActionResult,
)
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmRequest,
    PanelConfirmationService,
    ProposalStore,
    StagedProposal,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _setup_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    outbox = tmp_path / "index-outbox.jsonl"
    bind_initialized_vault(monkeypatch, vault, store_dir=tmp_path)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.delenv("VAULT_CAPTURE_NOTE_REL", raising=False)
    return vault, outbox


def _outbox_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _make_object(store: ObjectStore, object_id: str, text: str = "some content") -> None:
    store.save_object(
        DomainObject(
            uuid=object_id,
            kind="note",
            payload={"text": text},
            source_ref=None,
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
    )


# ===========================================================================
# 1. T-capture -- passing exemplar (already fail-loud, pinned as the baseline)
# ===========================================================================


def test_failing_receipt_store_fails_the_transition_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-capture: a receipt store that cannot persist withholds the ack.

    The passing exemplar the rest of this module's transitions are pinned
    against -- ``_emit_capture_event`` raises when neither outbox sink
    persists, and the route converts that into ``authority_receipt_
    persistence_failed`` (500, ``state=not_acknowledged``), never a 2xx.
    """
    _setup_vault(tmp_path, monkeypatch)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(
        capture_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )

    def _fail_jsonl_append(*args: object, **kwargs: object) -> bool:
        raise OSError("disk full")

    def _fail_db_write(*args: object, **kwargs: object) -> str:
        raise OSError("db down")

    monkeypatch.setattr(capture_module, "append_jsonl_outbox_event", _fail_jsonl_append)
    monkeypatch.setattr(capture_module, "write_outbox_event", _fail_db_write)

    resp = TestClient(app).post(
        "/api/companion/capture", json={"text": "persist accountability before ack"}
    )

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["error"] == "authority_receipt_persistence_failed"
    assert detail["state"] == "not_acknowledged"


# ===========================================================================
# 2. T-review-decide -- already fail-loud (no try/except around record_decision)
# ===========================================================================


def _candidate(**overrides: object) -> MemoryCandidate:
    fields: dict[str, object] = dict(
        title="Property-test candidate",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        content="Some candidate content for the receipt-before-ack property.",
        source_refs=["session:property-test"],
        derived_from="conversation:property-test",
        generated_by="companion_agent",
    )
    fields.update(overrides)
    return MemoryCandidate(**fields)


def test_failing_receipt_store_fails_the_transition_review_decide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-review-decide: a raising decision store fails the reject transition.

    ``post_memory_review_decision``'s reject branch calls
    ``decision_store.record_decision(...)`` with no surrounding try/except
    before building the response -- a raising store propagates uncaught
    (FastAPI turns it into an unhandled 500), never a 200 ``"rejected"``.
    """
    bind_initialized_vault(monkeypatch, tmp_path / "vault", store_dir=tmp_path)
    monkeypatch.setenv("PKM_CHANNEL", "test")

    queue = MemoryCandidateReviewQueue()
    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: queue)

    candidate = _candidate()
    queue.enqueue(candidate)

    def _raising_record_decision(*args: object, **kwargs: object) -> None:
        raise RuntimeError("decision store unreachable")

    monkeypatch.setattr(
        companion_module.ReviewDecisionStore, "record_decision", _raising_record_decision
    )

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/companion/memory/review-queue/{candidate.candidate_id}/decision",
        json={"action": "reject", "reviewed_by": "reviewer:human"},
    )

    assert resp.status_code == 500
    # No success-with-lost-receipt: the response body must not report the
    # governed "rejected" outcome the endpoint would otherwise have returned.
    if resp.headers.get("content-type", "").startswith("application/json"):
        body = resp.json()
        assert body.get("status") != "rejected"


# ===========================================================================
# 3 & 4. Reviewer / set_evaluator decide -- fixed by this issue
# ===========================================================================


@pytest.fixture(autouse=True)
def _memory_backend_for_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reviewer/set_evaluator drive ``insert_decision`` -- pin them to the
    explicit memory backend like the rest of ``tests/properties/*`` (``not
    pg``), and clear the in-process store between tests."""
    import app.services.decisions as decisions_module

    monkeypatch.setenv("STORE_BACKEND", "memory")
    decisions_module._MEM_DECISIONS.clear()
    yield
    decisions_module._MEM_DECISIONS.clear()


def test_failing_receipt_store_fails_the_transition_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer decide: a raising ``insert_decision`` now fails ``review()``.

    Before this issue, ``review()`` wrapped the decision write in ``try:
    ... except Exception: pass`` -- a raising store was silently swallowed
    and ``review()`` still returned its normal success dict. Now the
    exception propagates: no silent success-with-lost-receipt.
    """
    store = ObjectStore()
    _make_object(store, "reviewer-prop-1")

    def _raise(*args: object, **kwargs: object) -> None:
        raise RuntimeError("decision store unreachable")

    monkeypatch.setattr(reviewer_agent_module, "insert_decision", _raise)

    with pytest.raises(RuntimeError, match="decision store unreachable"):
        reviewer_agent_module.review("reviewer-prop-1", trace_id="trace-reviewer-prop-1")


def test_failing_receipt_store_fails_the_transition_set_evaluator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set-evaluator decide: a raising ``insert_decision`` now fails
    ``evaluate_object()`` the same way as the reviewer fix above."""
    store = ObjectStore()
    _make_object(store, "set-evaluator-prop-1")
    reviewer_agent_module.review("set-evaluator-prop-1", trace_id="trace-set-evaluator-prop-1")

    def _raise(*args: object, **kwargs: object) -> None:
        raise RuntimeError("decision store unreachable")

    monkeypatch.setattr(set_evaluator_agent_module, "insert_decision", _raise)

    with pytest.raises(RuntimeError, match="decision store unreachable"):
        set_evaluator_agent_module.evaluate_object(
            "set-evaluator-prop-1", trace_id="trace-set-evaluator-prop-1"
        )


# ===========================================================================
# 5. T-promote -- already fail-loud (write_outbox_event raises, no swallow)
# ===========================================================================


def _write_note(path: Path, uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nuuid: {uuid}\nreview_state: draft\n---\nBody\n", encoding="utf-8")


def test_failing_receipt_store_fails_the_transition_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-promote: a raising DB-outbox write fails the promotion transition.

    ``consume_promotion_intent_payload`` routes through ``_emit_db_event`` ->
    ``write_outbox_event`` with no try/except in ``_handle_promotion_payload``
    around ``emit(...)`` -- a raising store propagates uncaught, so the
    transition never reports ``applied`` while silently losing the
    ``promote.done``/``promotion.transition.applied`` receipt.
    """
    reset_promotion_dedup_store()
    note_path = tmp_path / "vault" / "N.md"
    note_uuid = "00000000-0000-0000-0000-000000000201"
    _write_note(note_path, note_uuid)

    def _raise(*args: object, **kwargs: object) -> str:
        raise RuntimeError("outbox db unreachable")

    monkeypatch.setattr("app.promotion.consumer.write_outbox_event", _raise)

    payload = {
        "note": {"uuid": note_uuid, "path": str(note_path)},
        "transition": {"family": "promotion", "target_maturity": "evergreen"},
    }

    with pytest.raises(RuntimeError, match="outbox db unreachable"):
        consume_promotion_intent_payload(payload, trace_id="trace-promote-prop-1", event_id="evt-promote-prop-1")


# ===========================================================================
# 6. T-panel-confirm -- fixed by this issue
# ===========================================================================


def _panel_intent(
    note_path: str | None,
    *,
    note_uuid: str = "panel-prop-uuid-1",
    action_label: str = "log this",
) -> PanelIntentEvent:
    aid = stable_action_id(action_label)
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=note_uuid, path=note_path),
            panel=PanelInfo(panel_id="panel-prop-1", instruction="do the thing"),
            actions=[PanelIntentAction(id=aid, label=action_label, checked=True)],
        )
    )


class _LoggedExecuteResult:
    """Minimal ``execute_panel_intent`` result: one checked action, all logged,
    no pre-emitted events -- so ``confirm()`` reaches ``_emit_projection_event``
    for ``panel.action.logged`` (the accountability receipt under test)."""

    def __init__(self, action_label: str = "log this") -> None:
        aid = stable_action_id(action_label)
        self.actions = [
            PanelRuntimeActionResult(
                id=aid, label=action_label, checked=True, status="logged", details={}
            )
        ]
        self.emitted_events: list[object] = []


def _panel_service_with_staged_proposal(
    *,
    proposal_id: str = "panel-prop-1",
    note_uuid: str = "panel-prop-uuid-1",
    note_path: str | None = None,
) -> PanelConfirmationService:
    """Fresh in-memory service with one proposal staged outside the same-turn
    window (``proposed_at=0.0``)."""
    ps = ProposalStore()
    ids = ConfirmIdempotencyStore()
    svc = PanelConfirmationService(ps, ids)
    ps.stage(
        proposal_id,
        StagedProposal(
            artifact_id=note_uuid,
            intent_event=_panel_intent(note_path, note_uuid=note_uuid),
            proposed_at=0.0,
        ),
    )
    return svc


def _panel_confirm_request(
    *,
    proposal_id: str = "panel-prop-1",
    artifact_id: str = "panel-prop-uuid-1",
    ikey: str = "panel-ikey-1",
) -> ConfirmRequest:
    return ConfirmRequest(
        proposal_id=proposal_id,
        artifact_id=artifact_id,
        action="confirm",
        idempotency_key=ikey,
    )


def test_failing_receipt_store_fails_panel_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-panel-confirm: when neither outbox sink persists the
    ``panel.action.logged`` receipt, the confirm transition withholds its ack.

    Before this issue, ``_emit_projection_event`` swallowed both the JSONL and
    DB outbox failures and unconditionally returned ``evt.event_id``, so
    ``confirm()`` returned ``status="logged"`` with a receipt for a receipt
    that never persisted. Now it raises ``PanelReceiptPersistenceError`` and the
    ``/api/panel/confirm`` route converts that into a withheld-ack 500
    (``authority_receipt_persistence_failed`` / ``state=not_acknowledged``),
    never a success-with-lost-receipt. The failed confirm must also leave no
    success cached and the proposal staged for retry.
    """
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    # Exercise both sinks failing: pg backend selected so the DB mirror path is
    # taken, and both the JSONL append and the DB write raise.
    monkeypatch.setenv("STORE_BACKEND", "pg")

    def _fail_jsonl(*args: object, **kwargs: object) -> bool:
        raise OSError("disk full")

    def _fail_db_write(*args: object, **kwargs: object) -> str:
        raise OSError("db down")

    monkeypatch.setattr(panel_confirm_module, "append_jsonl_outbox_event", _fail_jsonl)
    monkeypatch.setattr(panel_confirm_module, "write_outbox_event", _fail_db_write)
    monkeypatch.setattr(
        panel_confirm_module, "execute_panel_intent", lambda intent: _LoggedExecuteResult()
    )

    svc = _panel_service_with_staged_proposal()
    monkeypatch.setattr(panel_confirm_module, "_service", svc)

    resp = TestClient(app, raise_server_exceptions=False).post(
        "/api/panel/confirm",
        json={
            "proposal_id": "panel-prop-1",
            "artifact_id": "panel-prop-uuid-1",
            "action": "confirm",
            "idempotency_key": "panel-ikey-1",
        },
    )

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["error"] == "authority_receipt_persistence_failed"
    assert detail["state"] == "not_acknowledged"

    # No success-with-lost-receipt: nothing cached under the key, proposal still
    # staged so a post-recovery retry resolves instead of failing unknown.
    assert svc._idempotency.get("panel-ikey-1") is None
    assert svc._proposals.get("panel-prop-1") is not None


# ===========================================================================
# Ordering assertion: receipt insert happens-before the ack/success point
# ===========================================================================


def test_recording_receipt_store_ordering_reviewer_insert_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a recording (non-raising) store, the decision insert is observed
    to have happened by the time ``review()`` returns its success dict --
    ordering (insert-before-ack), not merely presence."""
    store = ObjectStore()
    _make_object(store, "reviewer-order-1")

    calls: list[str] = []
    original_insert = reviewer_agent_module.insert_decision

    def _recording_insert(*args: object, **kwargs: object) -> None:
        calls.append("insert_decision")
        return original_insert(*args, **kwargs)

    monkeypatch.setattr(reviewer_agent_module, "insert_decision", _recording_insert)

    assert calls == []
    out = reviewer_agent_module.review("reviewer-order-1", trace_id="trace-reviewer-order-1")

    # The insert happened, and it happened strictly before this observation
    # point (i.e. before/at the moment review() handed back its result) --
    # never a scenario where the success dict is returned with no insert
    # recorded at all.
    assert calls == ["insert_decision"]
    assert out["event"]


def test_recording_receipt_store_ordering_promote_insert_before_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a recording (non-raising) JSONL-outbox write, the receipt
    emission (``promote.done`` / ``promotion.transition.applied``) is
    observed before ``consume_promotion_intents`` reports ``applied=1`` --
    the mirror write happens, then the transition-accountability event is
    durable, before the caller can observe success.

    Drives the JSONL-outbox entry point (``not pg``-safe -- no
    DATABASE_URL/DB_DSN reached), matching
    ``tests/promotion/test_consumer_idempotency.py`` and
    ``tests/properties/test_event_completeness.py::_run_promote``'s
    established pattern; the DB-path failure test above already covers the
    ``write_outbox_event`` seam directly.
    """
    reset_promotion_dedup_store()
    note_path = tmp_path / "vault" / "N.md"
    note_uuid = "00000000-0000-0000-0000-000000000202"
    _write_note(note_path, note_uuid)

    calls: list[str] = []
    import app.promotion.consumer as consumer_module

    original_write_outbox = consumer_module._write_outbox

    def _recording_write_outbox(path: Path, events: object) -> None:
        events = list(events)
        calls.extend(getattr(event, "event", None) for event in events)
        return original_write_outbox(path, events)

    monkeypatch.setattr(consumer_module, "_write_outbox", _recording_write_outbox)

    outbox = tmp_path / "outbox.jsonl"
    event_data = {
        "event": "promote.intent.created",
        "trace_id": "trace-promote-order-1",
        "event_id": "evt-promote-order-1",
        "source": "property_test",
        "payload": {
            "note": {"uuid": note_uuid, "path": str(note_path)},
            "transition": {"family": "promotion", "target_maturity": "evergreen"},
        },
    }
    outbox.write_text(json.dumps(event_data, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = consumer_module.consume_promotion_intents(outbox_path=outbox)

    assert summary["applied"] == 1
    # The transition-accountability events were actually written through the
    # real outbox-write seam before/at the point "applied" is reported -- not
    # an empty call list with a claimed success.
    assert "promotion.transition.applied" in calls
    assert "promote.done" in calls


def test_panel_confirm_receipt_insert_happens_before_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a recording (non-raising) JSONL sink, the ``panel.action.logged``
    receipt insert is observed by the time ``confirm()`` returns its
    ``status="logged"`` ack -- pinning insert-then-ack, not insert-xor-ack.

    JSONL-only path (``not pg``-safe): the autouse memory backend plus explicit
    DSN clearing keep ``_emit_projection_event`` off the DB mirror, so the real
    ``append_jsonl_outbox_event`` seam is the observed write point.
    """
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    calls: list[str] = []
    original_append = panel_confirm_module.append_jsonl_outbox_event

    def _recording_append(path: Path, event: object, **kwargs: object) -> bool:
        calls.append(str(getattr(event, "event", None)))
        return original_append(path, event, **kwargs)

    monkeypatch.setattr(panel_confirm_module, "append_jsonl_outbox_event", _recording_append)
    monkeypatch.setattr(
        panel_confirm_module, "execute_panel_intent", lambda intent: _LoggedExecuteResult()
    )

    svc = _panel_service_with_staged_proposal()

    assert calls == []
    resp = svc.confirm(_panel_confirm_request())

    # The receipt insert happened, and it happened before this observation
    # point (confirm returning its logged ack) -- never a logged success with
    # no receipt recorded at all.
    assert resp.status == "logged"
    assert resp.receipt is not None and resp.receipt.receipt_id
    assert "panel.action.logged" in calls
