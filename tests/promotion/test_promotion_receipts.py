from __future__ import annotations

import json
from pathlib import Path

from app.events.types import PROMOTE_ERROR, PROMOTE_INTENT_CREATED
from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store


def _write_note(path: Path, uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nuuid: {uuid}\nreview_state: draft\n---\nBody\n", encoding="utf-8")


def _intent_event(note_path: Path, note_uuid: str, *, event_id: str = "evt-1", trace_id: str = "trace-1") -> dict:
    return {
        "event": PROMOTE_INTENT_CREATED,
        "trace_id": trace_id,
        "event_id": event_id,
        "source": "panel_agent",
        "payload": {
            "note": {"uuid": note_uuid, "path": str(note_path)},
            "transition": {"family": "promotion", "target_maturity": "evergreen"},
        },
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_applied_promotion_writes_transition_receipt(tmp_path: Path) -> None:
    reset_promotion_dedup_store()
    note_path = tmp_path / "vault" / "N.md"
    note_uuid = "00000000-0000-0000-0000-000000000101"
    _write_note(note_path, note_uuid)

    outbox = tmp_path / "outbox.jsonl"
    event = _intent_event(note_path, note_uuid, event_id="evt-applied", trace_id="trace-applied")
    outbox.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = consume_promotion_intents(outbox_path=outbox)
    assert summary["applied"] == 1

    records = _read_jsonl(outbox)
    receipts = [r for r in records if r.get("event") == "promotion.transition.applied"]
    assert len(receipts) == 1
    payload = receipts[0]["payload"]
    assert payload["intent_event_id"] == "evt-applied"
    assert payload["trace_id"] == "trace-applied"
    assert payload["note_uuid"] == note_uuid
    assert payload["transition_family"] == "promotion"
    assert payload["target_maturity"] == "evergreen"
    assert payload["executor"] == "promotion.consumer"
    assert payload["effect"] == "applied"


def test_replayed_promotion_intent_does_not_duplicate_receipt(tmp_path: Path) -> None:
    reset_promotion_dedup_store()
    note_path = tmp_path / "vault" / "N.md"
    note_uuid = "00000000-0000-0000-0000-000000000102"
    _write_note(note_path, note_uuid)

    outbox = tmp_path / "outbox.jsonl"
    event = _intent_event(note_path, note_uuid, event_id="evt-dup", trace_id="trace-dup")
    outbox.write_text(
        json.dumps(event, ensure_ascii=False) + "\n" + json.dumps(event, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = consume_promotion_intents(outbox_path=outbox)
    assert summary["applied"] == 1
    assert summary["skipped_duplicates"] == 1

    records = _read_jsonl(outbox)
    receipts = [r for r in records if r.get("event") == "promotion.transition.applied"]
    assert len(receipts) == 1


def test_failed_or_skipped_promotion_does_not_emit_applied_receipt(tmp_path: Path) -> None:
    reset_promotion_dedup_store()
    outbox = tmp_path / "outbox.jsonl"
    bad_event = {
        "event": PROMOTE_INTENT_CREATED,
        "trace_id": "trace-bad",
        "event_id": "evt-bad",
        "source": "panel_agent",
        "payload": {"note": {"uuid": "00000000-0000-0000-0000-000000000103"}},
    }
    outbox.write_text(json.dumps(bad_event, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = consume_promotion_intents(outbox_path=outbox)
    assert summary["errors"] == 1

    records = _read_jsonl(outbox)
    assert any(r.get("event") == PROMOTE_ERROR for r in records)
    assert all(r.get("event") != "promotion.transition.applied" for r in records)
