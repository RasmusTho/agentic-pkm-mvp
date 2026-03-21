from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

import app.agents.classifier.agent as classifier_agent
from app.agents.classifier.agent import run as classify_run
from app.store import object_store as legacy_object_store
from app.store.object_store import DomainObject, ObjectStore
from app.stores.provider import get_stores, reset_memory_stores

pytestmark = pytest.mark.not_pg


def test_classifier_falls_back_to_heuristic_and_persists_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _StubClient:
        def chat(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return '{"type":"idea","trust":"own","tags":["topic/ignore"],"confidence":0.2}'

    monkeypatch.setattr(classifier_agent, "get_chat_client", lambda intent: _StubClient())

    reset_memory_stores()
    legacy_object_store._MEMORY_STORE.clear()

    object_id = str(uuid4())
    ObjectStore().save_object(
        DomainObject(
            uuid=object_id,
            kind="note",
            payload={
                "text": "# Titel\n\nDetta ar en importerad text utan kallor.\nLank: http://example.com",
            },
            source_ref=str(tmp_path / "sample.md"),
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
    )

    result = classify_run(object_id, trace_id="t-classify-1")
    classification = result["classification"]

    assert classification["type"] == "note"
    assert classification["trust"] == "provisional"
    assert classification["confidence"] == 0.55
    assert sorted(classification["tags"]) == ["topic/has_title", "topic/links"]

    _, decisions = get_stores()
    latest = decisions.latest(object_id=object_id, key="classification")
    assert latest is not None
    assert latest["agent"] == "classifier"
    assert latest["kind"] == "classification"
    assert latest["value"] == classification
