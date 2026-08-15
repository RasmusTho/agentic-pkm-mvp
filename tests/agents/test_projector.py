from app.events.types import (
    PROMOTION_PROJECT_DONE,
    PROMOTION_PROJECT_SKIP,
)

import uuid
from datetime import datetime, timezone

import pytest

from app.agents.projector.agent import _record_membership_db, run as project_run
from app.objects import ObjectStore, DomainObject


def _create_object() -> str:
    object_id = str(uuid.uuid4())
    payload = {"core6": {"id": object_id, "review_state": "reviewed"}}
    obj = DomainObject(
        uuid=object_id,
        kind="note",
        payload=payload,
        source_ref=None,
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="test-projector")
    return object_id


def test_projector_returns_structure() -> None:
    oid_a = _create_object()
    oid_b = _create_object()

    promoted = project_run(oid_a, trace_id="t-projector-1", set_name="published")
    skipped = project_run(oid_b, trace_id="t-projector-2", set_name="published")

    for result in (promoted, skipped):
        assert result["event"] in {PROMOTION_PROJECT_DONE, PROMOTION_PROJECT_SKIP}
        assert result.get("object_id")
        assert "set_name" in result
        assert "promote" in result


def test_projector_memory_backend_does_not_open_membership_database(monkeypatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(
        "app.agents.projector.agent.save_membership",
        lambda *_args, **_kwargs: pytest.fail("memory backend opened membership database"),
    )
    _record_membership_db("object", "published", "trace")
