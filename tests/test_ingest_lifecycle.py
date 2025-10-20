from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.ingest import handle_post_ingest, normalize_payload
import app.ingest.lifecycle as lifecycle


@pytest.fixture()
def lifecycle_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logs_dir = tmp_path / "logs"
    reflect_dir = tmp_path / "reflect"
    monkeypatch.setattr(lifecycle, "LOGS_DIR", logs_dir, False)
    monkeypatch.setattr(lifecycle, "REFLECT_DIR", reflect_dir, False)
    monkeypatch.setattr(lifecycle, "REFLECTION_LOG", logs_dir / "reflection.json", False)
    monkeypatch.setattr(lifecycle, "ANALYTICS_LOG", logs_dir / "emergent_analytics.json", False)
    monkeypatch.setattr(lifecycle, "RELATIONS_LOG", logs_dir / "relations.jsonl", False)
    import app.ingest.reflection_consumer as reflector

    monkeypatch.setattr(reflector, "REFLECT_DIR", reflect_dir, False)


def test_normalize_payload_defaults() -> None:
    text = "Learning note content."
    payload = {}
    normalized = normalize_payload(payload, text)
    assert normalized["object_type"] == "note"
    assert normalized["system_intent"] == "learn"
    assert normalized["emergent_tags"] == []
    assert normalized["text"] == text
    assert normalized["content"] == text
    assert normalized["title"] == "Learning note content."


def test_reflection_queue_and_analytics(tmp_path: Path, lifecycle_paths: None) -> None:
    object_id = uuid4()
    payload = normalize_payload(
        {
            "object_type": "note",
            "system_intent": "reflect",
            "clarity_score": 0.4,
            "emergent_tags": ["serendipity", "invalid"],
        },
        "Need to clarify this idea.",
    )
    handle_post_ingest(object_id, payload, "Need to clarify this idea.")

    queue_file = lifecycle.REFLECT_DIR / f"{object_id}.json"
    assert queue_file.exists()
    queue_data = json.loads(queue_file.read_text(encoding="utf-8"))
    assert queue_data["source_object_id"] == str(object_id)

    reflection_log = lifecycle.REFLECTION_LOG
    log_entries = json.loads(reflection_log.read_text(encoding="utf-8"))
    assert log_entries[-1]["object_id"] == str(object_id)

    analytics = json.loads(lifecycle.ANALYTICS_LOG.read_text(encoding="utf-8"))
    assert analytics["system_intent"]["reflect"] == 1
    assert analytics["emergent_tags"]["serendipity"] == 1


def test_synthesis_note_relations(tmp_path: Path, lifecycle_paths: None) -> None:
    object_id = uuid4()
    payload = normalize_payload(
        {
            "object_type": "synthesis_note",
            "related_claim_ids": ["claim-1", "claim-2"],
        },
        "Synthesis content",
    )
    handle_post_ingest(object_id, payload, "Synthesis content")

    relations_path = lifecycle.RELATIONS_LOG
    assert relations_path.exists()
    last_line = relations_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    entry = json.loads(last_line)
    assert entry["type"] == "synthesizes"
    assert entry["synthesis_id"] == str(object_id)
    assert entry["related_claims"] == ["claim-1", "claim-2"]


def test_consume_reflection_queue(tmp_path: Path, lifecycle_paths: None, stub_index) -> None:
    from app.ingest.reflection_consumer import consume_reflection_queue

    _ = stub_index
    lifecycle.REFLECT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "source_object_id": str(uuid4()),
        "payload": {"title": "Reflection note"},
        "text": "Reflected insight",
    }
    entry_path = lifecycle.REFLECT_DIR / "entry.json"
    entry_path.write_text(json.dumps(entry), encoding="utf-8")

    processed = consume_reflection_queue()
    assert processed
    assert not entry_path.exists()
