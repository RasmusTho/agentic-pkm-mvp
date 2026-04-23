from __future__ import annotations

import json
from pathlib import Path

from app.events.types import PROMOTE_INTENT_CREATED
from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store


def _write_note(path: Path, uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nuuid: {uuid}\nreview_state: draft\n---\nBody\n", encoding="utf-8")


def test_apply_receipt_contains_required_fields(tmp_path: Path) -> None:
    reset_promotion_dedup_store()
    note_path = tmp_path / "vault" / "N.md"
    note_uuid = "00000000-0000-0000-0000-000000000999"
    _write_note(note_path, note_uuid)

    outbox = tmp_path / "outbox.jsonl"
    event = {
        "event": PROMOTE_INTENT_CREATED,
        "trace_id": "trace-apply",
        "event_id": "evt-apply",
        "source": "panel_agent.runtime",
        "payload": {
            "note": {"uuid": note_uuid, "path": str(note_path)},
            "transition": {"family": "promotion", "target_maturity": "evergreen"},
            "trust_verb": "APPLY",
        },
    }
    outbox.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = consume_promotion_intents(outbox_path=outbox)
    assert summary["applied"] == 1

    records = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
    applied = [r for r in records if r.get("event") == "promotion.transition.applied"]
    assert len(applied) == 1

    payload = applied[0]["payload"]
    assert payload["verb"] == "APPLY"
    assert payload["authority"]
    assert payload["basis"]
    assert payload["outcome"]
    assert payload["artifact_linkage"]
    assert payload["instance_provenance"]
