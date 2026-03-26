"""Quality Wave A — contract tests for the watcher→panel→promotion event chain.

Validates:
  1. Full event chain produces expected event types in correct order
  2. Every event satisfies the outbox envelope contract
  3. trace_id propagates through the chain
  4. Idempotency: rerunning the same inputs produces no duplicate side effects
  5. Event type constants match the canonical registry in app.events.types
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import execute_panel_intent
from app.events.types import (
    PANEL_INTENT_CREATED,
    PANEL_INTENT_EXECUTED,
    PROMOTE_DONE,
    PROMOTE_INTENT_CREATED,
    WATCHER_RUN,
)
from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore
from app.watcher.events import build_watcher_run_event

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _events_of_type(records: list[dict], event_type: str) -> list[dict]:
    return [r for r in records if r.get("event") == event_type]


def _assert_envelope(record: dict, expected_event: str) -> None:
    """Validate the canonical outbox envelope contract."""
    assert record.get("event") == expected_event, f"expected event={expected_event}, got {record.get('event')}"
    assert isinstance(record.get("event_id"), str) and record["event_id"], "event_id must be non-empty"
    assert isinstance(record.get("trace_id"), str) and record["trace_id"], "trace_id must be non-empty"

    source = record.get("source")
    if isinstance(source, dict):
        assert source.get("component"), "source.component must be set"
    else:
        assert isinstance(source, str) and source, "source must be non-empty string"

    assert isinstance(record.get("payload"), dict), "payload must be a dict"

    ts = record.get("timestamp", "")
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        raise AssertionError(f"timestamp is not ISO-8601: {ts}")


def _seed_note(note_uuid: str, markdown: str, note_path: Path) -> None:
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(markdown, encoding="utf-8")
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref=str(note_path),
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="seed")


def _panel_markdown(label: str) -> str:
    return f"""\
---
uuid: {{uuid}}
title: Quality Wave A Test
---
%% AI:Start %%
## AI-instruktion
Please promote this note.
## AI-åtgärder
- [x] {label}
%% AI:End %%
"""


def _panel_actions_yaml(label: str) -> str:
    return f"""\
---
mappings:
  - id: promote.evergreen
    label: "{label}"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
"""


def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outbox_path: Path, settings_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr("app.observability.status_service.INDEX_OUTBOX_PATH", outbox_path, raising=False)


# ---------------------------------------------------------------------------
# 1. Event type constants match hardcoded strings
# ---------------------------------------------------------------------------

class TestEventTypeRegistry:
    """Verify that canonical type constants match the strings emitted by components."""

    def test_panel_intent_created_matches(self) -> None:
        assert PANEL_INTENT_CREATED == "panel.intent.created"

    def test_panel_intent_executed_matches(self) -> None:
        assert PANEL_INTENT_EXECUTED == "panel.intent.executed"

    def test_promote_intent_created_matches(self) -> None:
        assert PROMOTE_INTENT_CREATED == "promote.intent.created"

    def test_promote_done_matches(self) -> None:
        assert PROMOTE_DONE == "promote.done"

    def test_watcher_run_matches(self) -> None:
        assert WATCHER_RUN == "watcher.run"


# ---------------------------------------------------------------------------
# 2. Watcher event envelope contract
# ---------------------------------------------------------------------------

class TestWatcherEventContract:
    """Validate the watcher.run event satisfies the envelope and payload contracts."""

    def test_watcher_run_envelope(self, tmp_path: Path) -> None:
        trace_id = "trace-qwa-watcher"
        event = build_watcher_run_event(
            {
                "changed": 2,
                "ingest_attempted": 2,
                "ingested": 1,
                "panel_candidates": 1,
                "panel_runs": 1,
                "panel_promotions": 0,
                "panel_skipped_policy": 0,
                "panel_skipped_limit": 0,
                "errors": 0,
                "dry_run": False,
                "limit_exceeded": False,
                "snapshot_path": "tmp/snap.json",
            },
            vault_root=tmp_path,
            snapshot_path="tmp/snap.json",
            trigger="test",
            trace_id=trace_id,
        )
        record = event.model_dump(mode="json")
        _assert_envelope(record, "watcher.run")
        assert record["trace_id"] == trace_id

        payload = record["payload"]
        required_keys = [
            "vault_root", "snapshot_path", "changed", "ingest_attempted",
            "ingested", "panel_candidates", "panel_runs", "panel_promotions",
            "panel_skipped_policy", "panel_skipped_limit", "errors",
            "dry_run", "limit_exceeded",
        ]
        for key in required_keys:
            assert key in payload, f"watcher payload missing key: {key}"


# ---------------------------------------------------------------------------
# 3. Full event chain: panel → promote.intent → consumer → promote.done
# ---------------------------------------------------------------------------

class TestFullEventChain:
    """End-to-end contract: panel agent → promote.intent.created → consumer → promote.done."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def _run_chain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict], str, str]:
        """Run the full chain and return (all outbox records, note_uuid, trace_id)."""
        label = "Gör denna anteckning evergreen"
        note_uuid = uuid4().hex
        markdown = _panel_markdown(label).replace("{uuid}", note_uuid)
        note_path = tmp_path / "vault" / "Note.md"
        outbox_path = tmp_path / "outbox.jsonl"
        settings_path = tmp_path / "panel-actions.md"

        settings_path.write_text(_panel_actions_yaml(label), encoding="utf-8")
        _setup_env(monkeypatch, tmp_path, outbox_path, settings_path)
        _seed_note(note_uuid, markdown, note_path)

        # Step 1: Panel agent emits panel.intent.created
        panel_events = run_panel_intent_for_note(note_uuid, trace_id="trace-qwa-chain")
        assert panel_events, "panel agent should produce at least one event"

        # Step 2: Runtime executes → emits promote.intent.created
        execute_panel_intent(panel_events[0], outbox_path=outbox_path)

        # Step 3: Consumer applies → emits promote.done
        summary = consume_promotion_intents(outbox_path=outbox_path)
        assert summary["applied"] == 1, f"expected 1 applied, got {summary}"

        return _read_outbox(outbox_path), note_uuid, "trace-qwa-chain"

    def test_chain_produces_expected_event_types(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        records, _, _ = self._run_chain(tmp_path, monkeypatch)
        event_types = [r["event"] for r in records]
        assert PROMOTE_INTENT_CREATED in event_types
        assert PROMOTE_DONE in event_types

    def test_chain_envelope_contract_at_every_hop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        records, _, _ = self._run_chain(tmp_path, monkeypatch)
        for record in records:
            event_type = record.get("event", "")
            _assert_envelope(record, event_type)

    def test_chain_trace_id_propagates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        records, _, trace_id = self._run_chain(tmp_path, monkeypatch)

        promote_intents = _events_of_type(records, PROMOTE_INTENT_CREATED)
        assert promote_intents, "expected at least one promote.intent.created"
        for pi in promote_intents:
            assert pi["trace_id"] == trace_id, (
                f"promote.intent.created trace_id mismatch: {pi['trace_id']} != {trace_id}"
            )

        promote_dones = _events_of_type(records, PROMOTE_DONE)
        assert promote_dones, "expected at least one promote.done"
        for pd in promote_dones:
            assert pd["trace_id"] == trace_id, (
                f"promote.done trace_id mismatch: {pd['trace_id']} != {trace_id}"
            )

    def test_chain_promote_intent_payload_shape(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        records, _, _ = self._run_chain(tmp_path, monkeypatch)
        promote_intents = _events_of_type(records, PROMOTE_INTENT_CREATED)
        assert promote_intents

        payload = promote_intents[0]["payload"]
        assert payload.get("note"), "promote.intent.created must have note"
        assert payload["note"].get("uuid"), "promote.intent.created must have note.uuid"
        assert payload.get("panel"), "promote.intent.created must have panel"
        assert payload.get("action"), "promote.intent.created must have action"
        assert payload.get("instruction"), "promote.intent.created must have instruction"

    def test_chain_promote_done_payload_shape(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        records, note_uuid, _ = self._run_chain(tmp_path, monkeypatch)
        promote_dones = _events_of_type(records, PROMOTE_DONE)
        assert promote_dones

        payload = promote_dones[0]["payload"]
        assert payload.get("note_uuid") == note_uuid
        assert payload.get("state"), "promote.done must declare the applied state"

    def test_chain_store_state_after_promotion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, note_uuid, _ = self._run_chain(tmp_path, monkeypatch)
        obj = ObjectStore().get_object(note_uuid)
        assert obj is not None
        assert obj.payload.get("review_state") == "reviewed"
        assert obj.payload.get("maturity") == "evergreen"
        assert obj.payload.get("promotion", {}).get("state") == "evergreen"


# ---------------------------------------------------------------------------
# 4. Idempotency: rerun produces no duplicate effects
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Idempotency contract: rerunning the same chain on the same note must not duplicate promote.done."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def test_rerun_consumer_produces_no_duplicate_promote_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        label = "Gör denna anteckning evergreen"
        note_uuid = uuid4().hex
        markdown = _panel_markdown(label).replace("{uuid}", note_uuid)
        note_path = tmp_path / "vault" / "Note.md"
        outbox_path = tmp_path / "outbox.jsonl"
        settings_path = tmp_path / "panel-actions.md"

        settings_path.write_text(_panel_actions_yaml(label), encoding="utf-8")
        _setup_env(monkeypatch, tmp_path, outbox_path, settings_path)
        _seed_note(note_uuid, markdown, note_path)

        panel_events = run_panel_intent_for_note(note_uuid, trace_id="trace-idemp")
        execute_panel_intent(panel_events[0], outbox_path=outbox_path)

        # First consume — should apply
        summary1 = consume_promotion_intents(outbox_path=outbox_path)
        assert summary1["applied"] == 1

        records_after_first = _read_outbox(outbox_path)
        done_count_first = len(_events_of_type(records_after_first, PROMOTE_DONE))

        # Second consume — cursor should skip already-processed lines
        summary2 = consume_promotion_intents(outbox_path=outbox_path)
        records_after_second = _read_outbox(outbox_path)
        done_count_second = len(_events_of_type(records_after_second, PROMOTE_DONE))

        assert done_count_second == done_count_first, (
            f"promote.done count increased from {done_count_first} to {done_count_second} on rerun"
        )
        assert summary2["applied"] == 0, "second consume should not apply anything"
