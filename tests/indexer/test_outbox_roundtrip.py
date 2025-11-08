from __future__ import annotations

from uuid import uuid4

import importlib

from app.outbox import events
from app.stores import get_vector_index, reset_store_backends


def _vec(axis: int, dim: int = 8) -> list[float]:
    vec = [0.0] * dim
    vec[axis % dim] = 1.0
    return vec


def test_indexer_runner_consumes_outbox(tmp_path, monkeypatch) -> None:
    reset_store_backends()
    fake_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr(events, "INDEX_OUTBOX_PATH", fake_path, raising=False)
    import app.indexer.runner as runner
    importlib.reload(runner)

    for idx in range(2):
        events.emit_index_object_embedded(
            {
                "object_id": uuid4(),
                "kind": "note",
                "source_ref": f"unit-test:{idx}",
                "payload": {
                    "text": f"payload-{idx}",
                    "content": f"payload-{idx}",
                    "object_type": "note",
                    "system_intent": "learn",
                    "emergent_tags": [],
                },
                "embedding": _vec(idx),
                "model": "openai/text-embedding-3-large",
            }
        )

    runner.main()

    idx = get_vector_index()
    results = idx.search(_vec(0), k=2)
    assert results
    assert results[0].payload["text"] == "payload-0"

    reset_store_backends()
