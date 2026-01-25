from __future__ import annotations

import json
from pathlib import Path

from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store


def _write_note(path: Path, uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---\nuuid: {uuid}\nreview_state: inbox\n---\nContent""", encoding="utf-8")


def _event_payload(note_path: Path, note_uuid: str, event_id: str) -> dict:
    return {
        "event": "promote.intent.created",
        "trace_id": "trace-0",
        "event_id": event_id,
        "source": "panel_agent",
        "payload": {
            "note": {"uuid": note_uuid, "path": str(note_path)},
            "maturity": "evergreen",
        },
    }


def test_consume_promotion_intents_skips_duplicates(tmp_path: Path) -> None:
    reset_promotion_dedup_store()
    vault = tmp_path / "vault"
    note_path = vault / "Notes" / "A.md"
    note_uuid = "00000000-0000-0000-0000-000000000001"
    _write_note(note_path, note_uuid)

    outbox = tmp_path / "outbox.jsonl"
    event_data = _event_payload(note_path, note_uuid, event_id="dup-event")
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with outbox.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(event_data, ensure_ascii=False) + "\n")
        handle.write(json.dumps(event_data, ensure_ascii=False) + "\n")

    summary = consume_promotion_intents(outbox_path=outbox)
    assert summary.get("applied") == 1
    assert summary.get("skipped_duplicates") == 1

    content = note_path.read_text(encoding="utf-8")
    assert "review_state: evergreen" in content
