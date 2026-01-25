from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentExecutedEvent,
    PanelIntentExecutedPayload,
    PanelIntentPayload,
    PanelRuntimeActionResult,
)
from app.events.schema import make_outbox_event
from app.outbox.events import emit_index_embedding_requested, emit_index_object_embedded
from app.watcher.events import build_watcher_run_event


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        raise AssertionError(f"timestamp is not ISO-8601: {ts}")


def _assert_envelope(record: dict) -> None:
    assert isinstance(record.get("event"), str) and record["event"], "event must be non-empty string"
    assert isinstance(record.get("event_id"), str) and record["event_id"], "event_id must be non-empty string"
    assert isinstance(record.get("trace_id"), str) and record["trace_id"], "trace_id must be non-empty string"
    source = record.get("source")
    if isinstance(source, dict):
        assert source.get("component"), "source.component must be set"
    else:
        assert isinstance(source, str) and source, "source must be non-empty string"
    assert isinstance(record.get("payload"), dict), "payload must be a dict"
    _parse_ts(record.get("timestamp", ""))


def _assert_no_embedding(record: dict) -> None:
    assert "embedding" not in record
    assert "embedding" not in record.get("payload", {})


def _assert_watcher_payload(payload: dict) -> None:
    required = [
        "vault_root",
        "snapshot_path",
        "changed",
        "ingest_attempted",
        "ingested",
        "panel_candidates",
        "panel_runs",
        "panel_promotions",
        "panel_skipped_policy",
        "panel_skipped_limit",
        "errors",
        "dry_run",
        "limit_exceeded",
    ]
    for key in required:
        assert key in payload


def _assert_panel_intent_created_payload(payload: dict) -> None:
    note = payload.get("note") or {}
    panel = payload.get("panel") or {}
    actions = payload.get("actions")
    assert note.get("uuid"), "note.uuid required"
    assert panel.get("panel_id"), "panel.panel_id required"
    assert panel.get("instruction"), "panel.instruction required"
    assert isinstance(actions, list) and actions, "actions must be a non-empty list"
    assert "id" in actions[0]
    assert "label" in actions[0]
    assert "checked" in actions[0]


def _assert_panel_intent_executed_payload(payload: dict) -> None:
    note = payload.get("note") or {}
    panel = payload.get("panel") or {}
    actions = payload.get("actions")
    assert note.get("uuid"), "note.uuid required"
    assert panel.get("panel_id"), "panel.panel_id required"
    assert panel.get("instruction"), "panel.instruction required"
    assert isinstance(actions, list) and actions, "actions must be a non-empty list"
    assert "id" in actions[0]
    assert "label" in actions[0]
    assert "checked" in actions[0]
    assert "status" in actions[0]
    assert isinstance(payload.get("executed_action_ids"), list)


def _assert_promote_intent_payload(payload: dict) -> None:
    assert payload.get("note"), "note required"
    assert payload.get("panel"), "panel required"
    assert payload.get("action"), "action required"
    assert payload.get("instruction"), "instruction required"


def test_outbox_event_envelope_has_required_fields(tmp_path: Path, monkeypatch) -> None:
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.outbox.events.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    emit_index_embedding_requested(
        {
            "object_id": "obj-1",
            "trace_id": "trace-123",
            "source": "test-ingest",
            "kind": "note",
            "source_ref": "fixtures/demo.md",
        }
    )

    lines = outbox_path.read_text(encoding="utf-8").splitlines()
    assert lines, "Expected an outbox line to be written"
    record = json.loads(lines[-1])

    assert record.get("event") == "index.embedding.requested"
    _assert_envelope(record)
    assert record["payload"].get("object_id") == "obj-1"
    _assert_no_embedding(record)


def test_outbox_event_type_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    watcher_event = build_watcher_run_event(
        {
            "changed": 1,
            "ingest_attempted": 1,
            "ingested": 1,
            "panel_candidates": 1,
            "panel_runs": 1,
            "panel_promotions": 1,
            "panel_skipped_policy": 0,
            "panel_skipped_limit": 0,
            "errors": 0,
            "dry_run": False,
            "limit_exceeded": False,
            "snapshot_path": "tmp/snapshot.json",
        },
        vault_root=tmp_path,
        snapshot_path="tmp/snapshot.json",
        trigger="test",
        trace_id="trace-watcher",
    ).model_dump(mode="json")

    panel_note = NoteRef(uuid="note-1", path="vault/Note.md", origin="vault")
    panel = PanelInfo(panel_id="panel-1", instruction="Do the thing.", raw_block=None)
    panel_action = PanelIntentAction(id="promote.evergreen", label="Promote", checked=True, mapping=None)
    panel_intent_event = PanelIntentEvent(
        payload=PanelIntentPayload(note=panel_note, panel=panel, actions=[panel_action]),
        trace_id="trace-panel-created",
    ).model_dump(mode="json")

    action_result = PanelRuntimeActionResult(
        id="promote.evergreen",
        label="Promote",
        checked=True,
        status="triggered",
        emitted_events=["promote.intent.created"],
    )
    executed_event = PanelIntentExecutedEvent(
        payload=PanelIntentExecutedPayload(
            note=panel_note,
            panel=panel,
            actions=[action_result],
            executed_action_ids=["promote.evergreen"],
        ),
        trace_id="trace-panel-executed",
    ).model_dump(mode="json")

    promote_intent_event = make_outbox_event(
        "promote.intent.created",
        source="panel_agent.runtime",
        trace_id="trace-promote-intent",
        payload={
            "note": {"uuid": "note-1", "path": "vault/Note.md"},
            "panel": {"panel_id": "panel-1", "instruction": "Do the thing."},
            "action": {"id": "promote.evergreen", "label": "Promote"},
            "instruction": "Do the thing.",
        },
    ).model_dump(mode="json")

    promote_done_event = make_outbox_event(
        "promote.done",
        source="promotion_consumer",
        trace_id="trace-promote-done",
        payload={},
    ).model_dump(mode="json")

    ingest_created_event = make_outbox_event(
        "ingest.object.created",
        source="ingest",
        trace_id="trace-ingest",
        payload={},
    ).model_dump(mode="json")

    outbox_path = tmp_path / "index-object-embedded.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.outbox.events.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    emit_index_object_embedded(object_id="obj-embedded", trace_id="trace-embed", source_ref="vault/Note.md")
    embedded_record = json.loads(outbox_path.read_text(encoding="utf-8").splitlines()[-1])

    records = [
        ("watcher.run", watcher_event, _assert_watcher_payload, []),
        ("panel.intent.created", panel_intent_event, _assert_panel_intent_created_payload, []),
        ("panel.intent.executed", executed_event, _assert_panel_intent_executed_payload, []),
        ("promote.intent.created", promote_intent_event, _assert_promote_intent_payload, []),
        ("promote.done", promote_done_event, lambda payload: None, []),
        ("ingest.object.created", ingest_created_event, lambda payload: None, []),
        ("index.object.embedded", embedded_record, lambda payload: None, ["uuid", "metrics", "provenance"]),
    ]

    for expected_event, record, payload_check, extra_fields in records:
        assert record.get("event") == expected_event
        _assert_envelope(record)
        for field in extra_fields:
            assert field in record
        payload_check(record.get("payload") or {})
        _assert_no_embedding(record)
