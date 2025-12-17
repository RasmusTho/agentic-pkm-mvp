from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.outbox.events import emit_index_embedding_requested


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        raise AssertionError(f"timestamp is not ISO-8601: {ts}")


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
    assert isinstance(record.get("trace_id"), str) and record["trace_id"], "trace_id must be non-empty string"
    assert isinstance(record.get("source"), str) and record["source"], "source must be non-empty string"
    assert isinstance(record.get("payload"), dict), "payload must be a dict"
    assert record["payload"].get("object_id") == "obj-1"
    assert "embedding" not in record
    assert "embedding" not in record.get("payload", {})
    _parse_ts(record.get("timestamp", ""))
