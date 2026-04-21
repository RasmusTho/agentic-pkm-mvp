from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.events.panel import NoteRef, PanelInfo, PanelIntentAction, PanelIntentEvent, PanelIntentPayload
from app.events.schema import make_outbox_event
from app.events.types import MCP_TOOL_CALL_STARTED, ORCHESTRATOR_STEP_STARTED, PROMOTE_INTENT_CREATED
from app.watcher.events import build_watcher_run_event


def _parse_ts(ts: str) -> None:
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception as exc:  # pragma: no cover - assertion message matters more than branch coverage
        raise AssertionError(f"timestamp is not ISO-8601: {ts}") from exc


def _assert_versioned_envelope(record: dict[str, object]) -> None:
    assert isinstance(record.get("event"), str) and record["event"], "event must be non-empty string"
    assert isinstance(record.get("version"), str) and record["version"] == "1.0", "version must be 1.0"
    assert isinstance(record.get("event_id"), str) and record["event_id"], "event_id must be non-empty string"
    assert isinstance(record.get("trace_id"), str) and record["trace_id"], "trace_id must be non-empty string"
    source = record.get("source")
    assert isinstance(source, dict), "source must be a dict for versioned events"
    assert isinstance(source.get("component"), str) and source["component"], "source.component must be set"
    assert isinstance(record.get("payload"), dict), "payload must be a dict"
    _parse_ts(str(record.get("timestamp") or ""))


def _assert_outbox_envelope(record: dict[str, object]) -> None:
    assert isinstance(record.get("event"), str) and record["event"], "event must be non-empty string"
    assert isinstance(record.get("event_id"), str) and record["event_id"], "event_id must be non-empty string"
    assert isinstance(record.get("trace_id"), str) and record["trace_id"], "trace_id must be non-empty string"
    source = record.get("source")
    if isinstance(source, dict):
        assert isinstance(source.get("component"), str) and source["component"], "source.component must be set"
    else:
        assert isinstance(source, str) and source, "source must be non-empty string"
    assert isinstance(record.get("payload"), dict), "payload must be a dict"
    meta = record.get("meta")
    assert isinstance(meta, dict), "meta must be a dict"
    assert meta.get("version") == "1.0", "meta.version must be 1.0"
    _parse_ts(str(record.get("timestamp") or ""))


def _watcher_record(tmp_path: Path) -> dict[str, object]:
    return build_watcher_run_event(
        {
            "changed": 1,
            "ingest_attempted": 1,
            "ingested": 1,
            "panel_candidates": 1,
            "panel_runs": 1,
            "panel_promotions": 1,
            "panel_skipped_policy": 0,
            "panel_skipped_limit": 0,
            "panel_skipped_auto_exec": 0,
            "panel_skipped_allowed_actions": 0,
            "skipped_dedup": 0,
            "skipped_idempotent": 0,
            "skipped_writes_blocked": 0,
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


def _panel_record() -> dict[str, object]:
    panel_note = NoteRef(uuid="note-1", path="vault/Note.md", origin="vault")
    panel = PanelInfo(panel_id="panel-1", instruction="Do the thing.", raw_block=None)
    panel_action = PanelIntentAction(id="promote.evergreen", label="Promote", checked=True, mapping=None)
    return PanelIntentEvent(
        payload=PanelIntentPayload(note=panel_note, panel=panel, actions=[panel_action]),
        trace_id="trace-panel",
    ).model_dump(mode="json")


def _outbox_record(event_name: str, *, source: str, trace_id: str, payload: dict[str, object]) -> dict[str, object]:
    return make_outbox_event(event_name, source=source, trace_id=trace_id, payload=payload).model_dump(mode="json")


def test_representative_events_include_version_trace_and_idempotency_fields(tmp_path: Path) -> None:
    watcher_record = _watcher_record(tmp_path)
    _assert_versioned_envelope(watcher_record)

    missing_version = dict(watcher_record)
    missing_version.pop("version", None)
    with pytest.raises(AssertionError, match="version"):
        _assert_versioned_envelope(missing_version)

    missing_event_id = dict(watcher_record)
    missing_event_id.pop("event_id", None)
    with pytest.raises(AssertionError, match="event_id"):
        _assert_versioned_envelope(missing_event_id)

    missing_trace_id = dict(watcher_record)
    missing_trace_id.pop("trace_id", None)
    with pytest.raises(AssertionError, match="trace_id"):
        _assert_versioned_envelope(missing_trace_id)

    outbox_record = _outbox_record(
        ORCHESTRATOR_STEP_STARTED,
        source="orchestrator.runtime",
        trace_id="trace-orchestrator",
        payload={"plan_id": "plan-1", "step_id": "step-1"},
    )
    _assert_outbox_envelope(outbox_record)

    missing_meta_version = dict(outbox_record)
    missing_meta_version["meta"] = {}
    with pytest.raises(AssertionError, match="meta.version"):
        _assert_outbox_envelope(missing_meta_version)


def test_existing_event_families_pass_envelope_lint(tmp_path: Path) -> None:
    records = [
        _watcher_record(tmp_path),
        _panel_record(),
        _outbox_record(
            PROMOTE_INTENT_CREATED,
            source="panel_agent.runtime",
            trace_id="trace-promote",
            payload={
                "note": {"uuid": "note-1", "path": "vault/Note.md"},
                "panel": {"panel_id": "panel-1", "instruction": "Do the thing."},
                "action": {"id": "promote.evergreen", "label": "Promote"},
                "instruction": "Do the thing.",
            },
        ),
        _outbox_record(
            ORCHESTRATOR_STEP_STARTED,
            source="orchestrator.runtime",
            trace_id="trace-orchestrator",
            payload={"plan_id": "plan-1", "step_id": "step-1"},
        ),
        _outbox_record(
            MCP_TOOL_CALL_STARTED,
            source="orchestrator.runtime",
            trace_id="trace-mcp-tool",
            payload={"plan_id": "plan-1", "step_id": "step-1", "tool": "mcp.vault.append_note"},
        ),
    ]

    for record in records:
        if "version" in record:
            _assert_versioned_envelope(record)
        else:
            _assert_outbox_envelope(record)
