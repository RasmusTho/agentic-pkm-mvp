from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note
from app.stores import reset_store_backends

pytestmark = pytest.mark.panel_llm_e2e


def _skip_if_no_llm() -> None:
    if os.getenv("PANEL_AGENT_LLM_E2E") != "1":
        pytest.skip("PANEL_AGENT_LLM_E2E!=1; skipping panel LLM E2E.")
    provider = (os.getenv("LLM_PROVIDER") or "mock").lower()
    if provider in {"", "mock"}:
        pytest.skip("LLM_PROVIDER is mock/empty; skipping panel LLM E2E.")


def _panel_actions_file(tmp_path: Path) -> Path:
    path = tmp_path / "panel-actions.md"
    path.write_text(
        """---
mappings:
  - id: "promote.evergreen"
    kind: "promotion"
    labels:
      - "Make this note evergreen"
      - "Promote to evergreen"
    description: "Promote the note to evergreen maturity."
    intent_type: "promotion"
    downstream_event: "review.promote.evergreen"
    params:
      maturity: "evergreen"
  - id: "panel.reply"
    kind: "chat"
    labels:
      - "Reply in panel"
    description: "Leave a brief reply in the panel log."
    intent_type: "chat"
    downstream_event: "panel.reply.created"
---
""",
        encoding="utf-8",
    )
    return path


def _note_markdown(instruction: str, action_label: str) -> str:
    return f"""%% AI:Start %%
## AI-instruktion
{instruction}
## AI-åtgärder
- [x] {action_label}
%% AI:End %%
"""


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _seed_note(note_uuid: str, markdown: str) -> None:
    from datetime import datetime, timezone
    from app.store.object_store import DomainObject, ObjectStore

    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Test.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="panel-llm-e2e")


def _run_panel(note_uuid: str) -> list[dict]:
    events = run_panel_intent_for_note(note_uuid, trace_id="panel-llm-e2e")
    assert len(events) == 1
    res = execute_panel_intent(events[0])
    return res.emitted_events


def test_panel_llm_promotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_no_llm()
    reset_store_backends()

    note_uuid = str(uuid4())
    markdown = _note_markdown(
        instruction="Make this note evergreen. Do not summarize; just promote it.",
        action_label="Make this note evergreen",
    )
    _seed_note(note_uuid, markdown)

    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(_panel_actions_file(tmp_path)))

    emitted = _run_panel(note_uuid)
    topics = {getattr(e, "event", None) or e.get("event") for e in emitted}
    assert "panel.intent.created" in topics
    assert "panel.intent.executed" in topics
    assert "panel.log.created" in topics
    assert "promote.intent.created" in topics

    outbox_events = _read_outbox(outbox_path)
    assert any(ev.get("event") == "promote.intent.created" and ev.get("payload", {}).get("note", {}).get("uuid") == note_uuid for ev in outbox_events)


def test_panel_llm_no_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_no_llm()
    reset_store_backends()

    note_uuid = str(uuid4())
    markdown = _note_markdown(
        instruction="Give me a short reflection on this note but do not promote it.",
        action_label="Reflect only, no promotion",
    )
    _seed_note(note_uuid, markdown)

    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(_panel_actions_file(tmp_path)))

    emitted = _run_panel(note_uuid)
    topics = {getattr(e, "event", None) or e.get("event") for e in emitted}
    assert "panel.intent.created" in topics
    assert "panel.intent.executed" in topics
    assert "panel.log.created" in topics
    assert "promote.intent.created" not in topics

    outbox_events = _read_outbox(outbox_path)
    assert not any(ev.get("event") == "promote.intent.created" for ev in outbox_events)
