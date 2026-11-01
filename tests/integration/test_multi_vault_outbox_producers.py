"""MVR-05D: every registered production vault-bound producer emits the versioned envelope.

Each recipe below invokes the registered producer's own production function
(the enclosing function the architecture registry names), against a real
provisioned instance whose live scalar binding is resolved, ownership-fenced,
and GOV-authorized by the production translator. Upstream collaborators that
only lead *to* the emission (note parsing, panel agents, store backends) are
stubbed; the outbox row itself is always written by the production choke
point and captured at the connection, never constructed by the test.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selections
from app.api.routes import capture as capture_routes
from app.events.schema import OutboxEvent
from app.services import outbox as outbox_service
from app.services.outbox_producers import OUTBOX_ENVELOPE_VERSION, vault_bound_producers
from app.write_guard import DEFAULT_WRITE_GUARD
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


class _Cursor:
    def __init__(self, one: Any = None, rowcount: int = 1) -> None:
        self._one = one
        self.rowcount = rowcount

    def fetchone(self) -> Any:
        return self._one

    def fetchall(self) -> list[Any]:
        return [] if self._one is None else [self._one]


class OutboxRecorder:
    """A connection that records the choke-point INSERT and answers its readback."""

    autocommit = False

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("insert into outbox"):
            self.rows.append(
                {
                    "id": params[0],
                    "topic": params[1],
                    "payload": json.loads(params[2]),
                    "legacy_key": params[5],
                    "vault_binding_id": params[6],
                }
            )
            return _Cursor((params[0],))
        if "from outbox" in normalized and normalized.startswith("select"):
            for row in reversed(self.rows):
                if row["id"] in params or row["legacy_key"] in params:
                    if normalized.startswith("select topic, payload"):
                        return _Cursor((row["topic"], row["payload"]))
                    return _Cursor((row["payload"],))
            return _Cursor(None)
        return _Cursor(None, rowcount=1)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class Harness(SimpleNamespace):
    root: Path
    binding: str
    tmp: Path
    mp: pytest.MonkeyPatch
    recorder: OutboxRecorder
    client: TestClient
    headers: dict[str, str]


@pytest.fixture()
def harness(tmp_path, monkeypatch) -> Harness:
    runtime, first, extra, _ = provisioned_instance(tmp_path, extra_roots=("other",))
    for registration in (first, *extra):
        initialize_test_vault(Path(registration.path))
        runtime.complete_initialization(
            registration.vault_binding_id,
            vault_id="vault-" + registration.vault_binding_id,
            local_instance_id=registration.local_instance_id,
        )
    root = Path(first.path).resolve()
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("VAULT_ROOT", str(root))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    selections.reset_selection_store_for_tests()
    client = TestClient(app)
    created = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [first.vault_binding_id]},
    )
    assert created.status_code == 201, created.text

    # Only now name a database: every self-owned producer reaches the real
    # choke point, whose connection is the recorder.
    recorder = OutboxRecorder()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://recorder.invalid:5432/mvr05d")
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: recorder)
    monkeypatch.setattr(outbox_service, "_self_owned_outbox_write_policy", lambda **_: "connect")
    monkeypatch.setattr(outbox_service, "self_owned_write_would_skip", lambda **_: False)
    # Payload schemas are not the subject here; the envelope is.
    monkeypatch.setattr(outbox_service, "is_registered_topic", lambda _topic: False)
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "ok"})
    return Harness(
        root=root,
        binding=first.vault_binding_id,
        tmp=tmp_path,
        mp=monkeypatch,
        recorder=recorder,
        client=client,
        headers={"X-Active-Context-Session": created.json()["context_selection_id"]},
    )


def _event(topic: str, payload: dict[str, Any] | None = None) -> OutboxEvent:
    return OutboxEvent(event=topic, source="test", trace_id="trace", payload=payload or {})


# --- recipes: one per registered vault-bound producer -------------------------


def _watcher_panel_note_events(h: Harness) -> None:
    from app.watcher import registry as watcher_registry
    from app.watcher.state import WatcherState

    (h.root / "n.md").write_text("# Note\n", encoding="utf-8")
    h.mp.setattr(watcher_registry, "watcher_panel_writeback_allowed", lambda *_a, **_k: True)
    h.mp.setattr(watcher_registry, "_ensure_panel_note_uuid_with_retry", lambda *_a, **_k: "note-uuid")
    h.mp.setattr(watcher_registry, "_read_panel_note_with_retry", lambda _p: ("# Note\n", "v1"))
    h.mp.setattr(watcher_registry, "resolve_canonical_object_id", lambda value: value)
    event = _event("panel.intent.created", {"note": {"uuid": "note-uuid"}})
    h.mp.setattr(
        watcher_registry,
        "handle_note_update",
        lambda **_k: SimpleNamespace(updated_markdown="# Note\n", executed_action_ids=[], events=[event]),
    )
    watcher_registry._process_panel_note(
        vault_root=h.root,
        rel_path=Path("n.md"),
        outbox_path=h.tmp / "panel.jsonl",
        state=WatcherState(),
        action_mappings={},
    )


def _watcher_emit(h: Harness, emit_event: str) -> None:
    from app.watcher import registry as watcher_registry
    from app.watcher.state import WatcherState

    (h.root / "w.md").write_text("# W\n", encoding="utf-8")
    watcher_registry._emit_watch_event(
        spec=SimpleNamespace(name="vault", emit_event=emit_event),
        cfg=SimpleNamespace(),
        outbox_path=h.tmp / "watch.jsonl",
        vault_root=h.root,
        rel_path=Path("w.md"),
        mtime=1.0,
        content_hash="hash",
        state=WatcherState(),
        required_db=True,
    )


def _watcher_delete_tombstone(h: Harness) -> None:
    from app.watcher import vault_watcher

    h.mp.setattr(vault_watcher, "find_companion_by_source_ref", lambda *_a, **_k: None)
    h.mp.setattr(vault_watcher, "read_companion", lambda *_a, **_k: None)
    h.mp.setattr(vault_watcher, "resolve_canonical_object_id", lambda value: value)
    vault_watcher._emit_watcher_delete_event(
        h.root / "gone.md", rel_deleted=Path("gone.md"), vault_root=h.root, observed_mtime=1.0
    )


def _api_ingest(h: Harness) -> None:
    response = h.client.post(
        "/ingest",
        json={"uuid": str(uuid4()), "title": "t", "review_state": "draft", "content": "c"},
    )
    assert response.status_code == 200, response.text


def _ingest_cli_pipe(h: Harness) -> None:
    import app.cli as cli_module

    source = h.root / "piped.md"
    source.write_text("# Pipe\n", encoding="utf-8")
    h.mp.setattr(cli_module, "_materialize_source", lambda value: Path(value))
    h.mp.setattr(cli_module, "normalize_run", lambda *_a, **_k: {"object_id": str(uuid4())})
    h.mp.setattr(cli_module, "classify_run", lambda *_a, **_k: {})
    h.mp.setattr(cli_module, "_should_transcribe", lambda _s: False)
    h.mp.setattr(cli_module, "append_jsonl", lambda *_a, **_k: None)
    h.mp.setattr(cli_module, "_dump", lambda *_a, **_k: None)
    cli_module.pipe.callback(str(source), False, None)


def _ingest_object_store(h: Harness) -> None:
    from app.objects import DomainObject, ObjectStore

    store = ObjectStore()
    h.mp.setattr(
        store,
        "_binding",
        lambda: SimpleNamespace(backend="pg", store=SimpleNamespace(put=lambda *_a, **_k: None)),
    )
    store.save_object(
        DomainObject(
            uuid=str(uuid4()),
            kind="note",
            payload={"text": "x"},
            source_ref="note.md",
            created_at=datetime.now(timezone.utc),
        )
    )


def _ingest_vault_sync(h: Harness) -> None:
    from app.services import vault_sync

    vault_sync._enqueue(
        "ingest.object.created", {"uuid": str(uuid4()), "path": "a.md"}, observation="m1"
    )


def _ka_request(h: Harness) -> None:
    from app.knowledge_acquisition.acquisition_requests import AcquisitionRequests

    AcquisitionRequests._emit(
        SimpleNamespace(),  # type: ignore[arg-type]
        "knowledge_acquisition.request.created",
        {"request_id": "r1"},
        key=outbox_service.derive_idempotency_key("ka", "r1", "f"),
        trace_id=None,
        conn=None,
    )


def _ka_rss_sync(h: Harness) -> None:
    from app.knowledge_acquisition import channel_rss_discovery

    channel_rss_discovery._write_sync_event(
        "knowledge_acquisition.source_sync.completed",
        {"binding_id": "source-1"},
        run_id="run-1",
        binding_id="source-1",
        conn=None,
    )


def _ka_stage_completed(h: Harness) -> None:
    from app.knowledge_acquisition.stage_events import emit_stage_completed

    emit_stage_completed(stage="extract", stage_version=1, content_identity="c1")


def _ka_stage_dead_letter(h: Harness) -> None:
    from app.knowledge_acquisition.stage_events import emit_stage_dead_letter

    emit_stage_dead_letter(
        stage="extract", stage_version=1, content_identity="c1", reason="r", error="e"
    )


def _capture(h: Harness) -> None:
    h.mp.setattr(capture_routes, "_offer_question_registration_proposal", lambda **_: None)
    response = h.client.post(
        "/api/companion/capture/scoped",
        json={"text": "Keep me", "target_binding_id": h.binding},
        headers=h.headers,
    )
    assert response.status_code == 200, response.text


def _heimdal_user_note(h: Harness) -> None:
    from app.api.routes import heimdal_meeting

    assert heimdal_meeting._emit_user_note_event(
        {"note_block_id": "b1", "revision": 1, "content_sha256": "c" * 64}, trace_id="t1"
    )


def _heimdal_entity_register(h: Harness) -> None:
    from app.heimdal.entity_register import EntityRegister

    EntityRegister._emit(
        SimpleNamespace(_conn=None),  # type: ignore[arg-type]
        "heimdal.register.entity.minted",
        entity_id="ent-1",
        fingerprint_scope="mint",
        payload={"entity_id": "ent-1"},
    )


def _heimdal_entity_merge(h: Harness) -> None:
    from app.heimdal import entity_review_operation_journal as journal_module

    h.mp.setattr(journal_module, "ensure_journal_schema", lambda _conn: None)
    journal = journal_module.EntityReviewOperationJournal(connection_factory=lambda: h.recorder)
    operation = journal_module.OperationRecord(
        operation_id="op-1",
        vault_identity="vault",
        queue_entry_id="q-1",
        decision_position=0,
        decision_digest="d",
        from_id="ent-a",
        into_id="ent-b",
        state=journal_module.STATE_CLAIMED,
        outbox_event_id=outbox_service.derive_idempotency_key("merge", "op-1", "f"),
    )
    journal.commit_merge_event(operation)


def _heimdal_entity_split(h: Harness) -> None:
    from app.heimdal import entity_review_operation_journal as journal_module

    h.mp.setattr(journal_module, "ensure_split_schema", lambda _conn: None)
    plan = {"events": [{"new_entity_id": "ent-new"}], "effects": [{"key": "e1"}], "complement_ids": []}
    record = journal_module.SplitRecord(
        "vault", "op-split", plan, journal_module.split_checkpoint_keys(plan)
    )
    journal = journal_module.EntityRegisterSplitJournal(connection_factory=lambda: h.recorder)
    h.mp.setattr(journal, "_load_split", lambda *_a, **_k: record)
    h.mp.setattr(journal, "load_split", lambda *_a, **_k: replace(record, completed=True))
    journal.finish_split(record)


def _heimdal_meeting_finalized(h: Harness) -> None:
    from app.heimdal import meeting_finalization

    assert meeting_finalization._emit_finalized_event(
        {"session_id": "s1", "finalization_state": "final"},
        trace_id="t1",
        vault_binding_id=h.binding,
    )


def _heimdal_late_admitted(h: Harness) -> None:
    from app.heimdal import meeting_ledger

    meeting_ledger._emit_late_admitted_event(
        {"session_id": "s1", "session_seq": 2, "content_sha256": "c" * 64}, trace_id="t1"
    )


def _panel_agent_execution(h: Harness) -> None:
    from app.agents.panel_agent import execution

    event = _event("panel.intent.created", {"note": {"uuid": "u"}, "panel": {"panel_id": "p"}})
    h.mp.setattr(execution, "run_panel_intent_for_note", lambda *_a, **_k: [event])
    h.mp.setattr(execution, "execute_panel_intent", lambda *_a, **_k: None)
    execution.run_panel_note_execution("u", persist_created_to_db=True, vault_root=h.root)


def _panel_agent_runtime(h: Harness) -> None:
    from app.agents.panel_agent import runtime

    runtime._write_db_outbox_events([_event("panel.action.executed", {"id": "a"})])


def _panel_confirmation(h: Harness) -> None:
    from app.panel import confirmation

    confirmation._emit_projection_event(
        "panel.action.confirmed", {"id": "a"}, "t1", outbox_path=h.tmp / "panel.jsonl"
    )


def _promotion_consumer(h: Harness) -> None:
    from app.promotion import consumer

    consumer._emit_db_event("promote.applied", {"source_event": "evt-1"}, "t1")


def _settings_write_receipt(h: Harness) -> None:
    from app.receipts.settings_write import SettingsWriteReceipt, emit_settings_write_receipt

    emit_settings_write_receipt(
        SettingsWriteReceipt(key="k", value="v", surface="test", actor="tester")
    )


def _index_embedding_requested(h: Harness) -> None:
    from app.outbox.events import emit_index_embedding_requested

    emit_index_embedding_requested({"object_id": str(uuid4())})


def _episode_closed(h: Harness) -> None:
    from app.episodes import closure

    (h.root / "episode.md").write_text("---\nx: 1\n---\n", encoding="utf-8")
    h.mp.setattr(
        closure, "parse_episode_note", lambda _t: {"time": {"closed": True}, "scope": "core"}
    )
    h.mp.setattr(closure, "_count_active_bound_artifacts", lambda _e: 0)
    h.mp.setattr(closure, "_sync_projection_closed", lambda _e: None)
    candidate = SimpleNamespace(episode_id="ep-1", note_path="episode.md", scope="core")
    closure.close_episode(
        candidate,  # type: ignore[arg-type]
        vault_root=h.root,
        write_guard=SimpleNamespace(assert_writes_allowed=lambda _a: None),  # type: ignore[arg-type]
    )


def _episode_debrief_trigger(h: Harness) -> None:
    from app.episode_debrief import trigger

    h.mp.setattr(trigger.store, "read_closures", lambda **_k: [])
    h.mp.setattr(
        trigger,
        "_closed_episodes",
        lambda _ids: [SimpleNamespace(episode_id="ep-1", bound_artifact_count=10_000)],
    )
    h.mp.setattr(trigger, "_episode_fields", lambda *_a: {"time": {"closed": True}, "scope": "core"})
    h.mp.setattr(trigger, "_already_debriefed", lambda *_a: False)
    trigger._reconcile(h.root, h.binding, (h.binding,), 10)


def _eval_disposition_receipt(h: Harness) -> None:
    from app.eval import failure_capture

    h.mp.setattr(failure_capture, "_governed_disposition_payload", lambda **_k: {"decision": "promote"})
    failure_capture._persist_disposition_authority_receipt(
        disposition_id=str(uuid4()),
        draft_id="d1",
        decision="promote",
        grant=None,  # type: ignore[arg-type]
        mutation_receipt=None,  # type: ignore[arg-type]
        authority_receipt=SimpleNamespace(  # type: ignore[arg-type]
            recorded_at=datetime.now(timezone.utc).isoformat()
        ),
        trace_id="t1",
    )


RECIPES: dict[str, Callable[[Harness], None]] = {
    "watcher.registry.panel_note_events": _watcher_panel_note_events,
    "watcher.registry.panel_scan_requested": lambda h: _watcher_emit(h, "panel.scan.requested"),
    "watcher.registry.watch_event": lambda h: _watcher_emit(h, "ingest.vault.changed"),
    "watcher.vault.delete_tombstone": _watcher_delete_tombstone,
    "api.ingest.object_created": _api_ingest,
    "ingest.cli.pipe": _ingest_cli_pipe,
    "ingest.object_store.save": _ingest_object_store,
    "ingest.vault_sync": _ingest_vault_sync,
    "ingest.knowledge_acquisition.request": _ka_request,
    "ingest.knowledge_acquisition.rss_sync": _ka_rss_sync,
    "ingest.knowledge_acquisition.stage_completed": _ka_stage_completed,
    "ingest.knowledge_acquisition.stage_dead_letter": _ka_stage_dead_letter,
    "capture.appended": _capture,
    "heimdal.meeting.user_note": _heimdal_user_note,
    "heimdal.entity_register": _heimdal_entity_register,
    "heimdal.entity_review.merge": _heimdal_entity_merge,
    "heimdal.entity_review.split": _heimdal_entity_split,
    "heimdal.meeting.finalized": _heimdal_meeting_finalized,
    "heimdal.meeting.late_admitted": _heimdal_late_admitted,
    "shared.panel_agent.execution": _panel_agent_execution,
    "shared.panel_agent.runtime": _panel_agent_runtime,
    "shared.panel.confirmation": _panel_confirmation,
    "shared.promotion.consumer": _promotion_consumer,
    "shared.settings.write_receipt": _settings_write_receipt,
    "shared.index.embedding_requested": _index_embedding_requested,
    "shared.episodes.closed": _episode_closed,
    "shared.episode_debrief.trigger": _episode_debrief_trigger,
    "shared.eval.disposition_receipt": _eval_disposition_receipt,
}


def test_production_call_sites_emit_binding_context_envelopes(harness: Harness) -> None:
    registered = {producer.producer_id for producer in vault_bound_producers()}
    # Every registered vault-bound producer is exercised; no recipe is stale.
    assert set(RECIPES) == registered

    expected_stamp = None
    failures: list[str] = []
    for producer_id in sorted(RECIPES):
        before = len(harness.recorder.rows)
        try:
            RECIPES[producer_id](harness)
        except Exception as exc:  # pragma: no cover - reported below with context
            failures.append(f"{producer_id}: {type(exc).__name__}: {exc}")
            continue
        emitted = [
            row
            for row in harness.recorder.rows[before:]
            if row["payload"].get("meta", {}).get("outbox_producer") == producer_id
        ]
        if not emitted:
            failures.append(f"{producer_id}: no outbox row reached the choke point")
            continue
        for row in emitted:
            meta = row["payload"]["meta"]
            stamp = {
                key: meta.get(key)
                for key in (
                    "vault_binding_id",
                    "binding_authority",
                    "binding_authorization_epoch",
                    "binding_revision",
                    "vault_root",
                )
            }
            expected_stamp = expected_stamp or stamp
            problems = []
            if meta.get("outbox_envelope") != OUTBOX_ENVELOPE_VERSION:
                problems.append("envelope version")
            if meta.get("routing_class") != "vault_bound":
                problems.append("routing class")
            if row["vault_binding_id"] != harness.binding or stamp != expected_stamp:
                problems.append(f"stable binding {row['vault_binding_id']} {stamp}")
            if meta.get("idempotency") != {
                "legacy_key": row["legacy_key"],
                "binding_scoped_key": row["id"],
            } or row["id"] != outbox_service.derive_binding_scoped_idempotency_key(
                row["topic"], harness.binding, row["legacy_key"]
            ):
                problems.append("idempotency")
            context = meta.get("producer_context") or {}
            expected_kind = "active_context" if producer_id == "capture.appended" else "binding_runtime"
            if context.get("kind") != expected_kind:
                problems.append(f"context kind {context.get('kind')}")
            if expected_kind == "active_context" and not (
                context.get("context_id") and context.get("context_generation", 0) >= 1
            ):
                problems.append("captured request context")
            if problems:
                failures.append(f"{producer_id}: {', '.join(problems)}")
    assert failures == []
    assert expected_stamp is not None
    assert expected_stamp["vault_binding_id"] == harness.binding
    assert expected_stamp["binding_authority"] == "allow"
    assert expected_stamp["vault_root"] == str(harness.root)
