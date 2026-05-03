from __future__ import annotations

import json

from app.observability.status_service import get_system_status


def test_status_includes_context_dimensions_block(monkeypatch, tmp_path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(
        json.dumps(
            {
                "event": "watcher.run.completed",
                "context_dimensions": {
                    "scope": "work",
                    "sphere_memberships": ["team"],
                    "situated_identity": "maker",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr("app.observability.status_service.INDEX_OUTBOX_PATH", outbox)

    status = get_system_status()
    assert status.context_dimensions is not None
    assert status.context_dimensions.scope == "work"
    assert status.context_dimensions.sphere_memberships == ["team"]
    assert status.context_dimensions.situated_identity == "maker"


def test_status_omits_block_when_no_context(monkeypatch, tmp_path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps({"event": "watcher.run.completed"}) + "\n", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr("app.observability.status_service.INDEX_OUTBOX_PATH", outbox)

    status = get_system_status()
    dumped = status.model_dump(exclude_none=True)
    assert "context_dimensions" not in dumped


def test_null_situated_identity_explicit_not_omitted(monkeypatch, tmp_path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(
        json.dumps(
            {
                "event": "watcher.run.completed",
                "context_dimensions": {
                    "scope": "work",
                    "sphere_memberships": [],
                    "situated_identity": None,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr("app.observability.status_service.INDEX_OUTBOX_PATH", outbox)

    status = get_system_status()
    assert status.context_dimensions is not None
    dumped = status.context_dimensions.model_dump()
    assert "situated_identity" in dumped
    assert dumped["situated_identity"] is None


def test_no_all_null_context_dimensions_block(monkeypatch, tmp_path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(
        json.dumps(
            {
                "event": "watcher.run.completed",
                "context_dimensions": {
                    "scope": None,
                    "sphere_memberships": None,
                    "situated_identity": None,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr("app.observability.status_service.INDEX_OUTBOX_PATH", outbox)

    status = get_system_status()
    dumped = status.model_dump(exclude_none=True)
    assert "context_dimensions" not in dumped
