from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.api.interesting import interesting_summary, list_interesting
from tests.stub_repositories import MemoryAgentRepository


def test_list_interesting_returns_items() -> None:
    repo = MemoryAgentRepository()
    object_id = uuid4()
    repo.interesting_items[object_id] = {
        "object_id": object_id,
        "run_id": uuid4(),
        "novelty": 0.7,
        "anomaly": 0.4,
        "uncertainty": 0.5,
        "value": 0.9,
        "score": 0.8,
        "reason": "Test object",
        "payload": {"title": "Test object", "system_intent": "learn", "emergent_tags": ["serendipity"]},
        "created_at": datetime.now(tz=timezone.utc),
    }

    response = list_interesting(limit=5, repo=repo)
    assert response.items
    assert response.items[0].reason == "Test object"


def test_interesting_filters_and_summary() -> None:
    repo = MemoryAgentRepository()
    for idx, intent in enumerate(["learn", "reflect"]):
        object_id = uuid4()
        repo.interesting_items[object_id] = {
            "object_id": object_id,
            "run_id": uuid4(),
            "novelty": 0.5,
            "anomaly": 0.3,
            "uncertainty": 0.4,
            "value": 0.6,
            "score": 0.5 + idx,
            "reason": f"{intent} item",
            "payload": {"system_intent": intent, "emergent_tags": ["collaboration" if idx else "serendipity"]},
            "created_at": datetime.now(tz=timezone.utc),
        }

    filtered = list_interesting(limit=10, system_intent="reflect", repo=repo)
    assert len(filtered.items) == 1
    assert filtered.items[0].reason == "reflect item"

    summary = interesting_summary(repo=repo)
    assert summary.total == 2
    assert summary.system_intent.get("learn") == 1
    assert summary.system_intent.get("reflect") == 1
    assert summary.emergent_tags.get("serendipity") == 1
