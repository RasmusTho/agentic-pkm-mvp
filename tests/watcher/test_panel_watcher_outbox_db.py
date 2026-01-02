from __future__ import annotations

import json
from pathlib import Path

from app.events.schema import OutboxEvent
from app.settings.panel_actions import PanelActionMapping
from app.watcher.registry import _process_panel_note
from app.watcher.state import WatcherState


def test_process_panel_note_enqueues_db_and_jsonl(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "@Inbox"
    note.mkdir()
    note_path = note / "note.md"
    note_path.write_text(
        """---
uuid: test-uuid
---
# Panel
- [x] Make this note evergreen <!--ai:id=promote.evergreen-->
""",
        encoding="utf-8",
    )

    events: list[OutboxEvent] = []

    def fake_write_outbox(ev):
        events.append(ev)
        return "ok"

    monkeypatch.setattr("app.watcher.registry.write_outbox_event", fake_write_outbox)

    outbox_jsonl = tmp_path / "outbox.jsonl"
    mappings = {"Make this note evergreen": PanelActionMapping(text="Make this note evergreen", event_type="promote.intent.created", payload_template={"maturity": "evergreen"}, action_id="promote.evergreen")}
    state = WatcherState()

    _process_panel_note(
        vault_root=vault,
        rel_path=note_path.relative_to(vault),
        outbox_path=outbox_jsonl,
        state=state,
        action_mappings=mappings,
    )

    assert events, "expected DB outbox event"
    assert outbox_jsonl.exists(), "expected JSONL telemetry"
    payloads = [json.loads(line) for line in outbox_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert payloads, "expected payloads in JSONL"
