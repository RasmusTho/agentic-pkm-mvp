from __future__ import annotations

from app.events.schema import make_outbox_event


def test_receipt_includes_context_dimensions() -> None:
    event = make_outbox_event(
        "watcher.run.completed",
        source="watcher",
        payload={"changed": 1},
        context_dimensions={
            "scope": "work",
            "sphere_memberships": ["team"],
            "situated_identity": None,
        },
    )
    dumped = event.model_dump(exclude_none=True)
    assert dumped["context_dimensions"]["scope"] == "work"
    assert dumped["context_dimensions"]["sphere_memberships"] == ["team"]
    assert "situated_identity" in dumped["context_dimensions"]
    assert dumped["context_dimensions"]["situated_identity"] is None


def test_receipt_omits_context_dimensions_when_absent() -> None:
    event = make_outbox_event(
        "watcher.run.completed",
        source="watcher",
        payload={"changed": 1},
    )
    dumped = event.model_dump(exclude_none=True)
    assert "context_dimensions" not in dumped
