from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.api.routes.companion as companion_module
import app.memory.store as memory_store
import app.panel.confirmation as confirm_module
from app.api.app import app
from app.observability.status_model import EventCounters, IngestionStatus, WorkerQueueStatus
from app.observability.status_service import OrientationSignals
from app.orientation import leave_point_cursor as cursor_module
from app.orientation.leave_point_cursor import (
    ALLOWED_CURSOR_FIELDS,
    ALLOWED_SOURCE_REF_FIELDS,
    append_raw_leave_point_trace,
    capture_leave_point_cursor,
    clear_leave_point_trace,
    latest_leave_point_projection,
)
from app.services import outbox as outbox_service


@pytest.fixture(autouse=True)
def _runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("PKM_CHANNEL", "test")
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "runtime" / "leave-point.sqlite3"))
    monkeypatch.setattr(companion_module, "_configured_vault_name", lambda: "vault-test")
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    clear_leave_point_trace()
    yield
    clear_leave_point_trace()
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _signals() -> OrientationSignals:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    return OrientationSignals(
        events=EventCounters(
            watcher_runs_total=1,
            watcher_runs_24h=0,
            panel_runs_total=0,
            panel_runs_24h=0,
            promote_created_total=0,
            promote_created_24h=0,
            promotion_executed_total=0,
            promotion_executed_24h=0,
            source_path="/tmp/status-events",
        ),
        ingestion=IngestionStatus(
            last_run_at=now,
            last_run_ok=True,
            total_scanned=1,
            total_ingested=1,
        ),
        worker_queue=WorkerQueueStatus(
            mode="memory",
            pending=0,
            processed_total=0,
            source_path="/tmp/worker",
        ),
    )


def _note(vault_root: Path, rel: str, uuid: str, title: str = "Cursor Note") -> Path:
    path = vault_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nuuid: {uuid}\ntitle: {title}\n---\n# {title}\n\nBody text.\n",
        encoding="utf-8",
    )
    return path


def _capture(
    *,
    artifact_uuid: str = "artifact-1",
    vault_id: str = "vault-test",
    channel: str = "test",
    trace_id: str = "trace-1",
    captured_at: datetime | None = None,
    content_hash_at_capture: str | None = None,
) -> dict:
    return capture_leave_point_cursor(
        vault_id=vault_id,
        channel=channel,
        artifact_uuid=artifact_uuid,
        source_kind="artifact_activation",
        source_ref_id="notes/cursor.md",
        capture_reason="artifact_focus",
        last_session_id="session-1",
        trace_id=trace_id,
        captured_at=captured_at,
        content_hash_at_capture=content_hash_at_capture,
    )


def _orientation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())
    resp = client.get("/api/companion/orientation")
    assert resp.status_code == 200
    return resp.json()


def test_cursor_survives_restart_reference_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")

    event = _capture()
    projection = latest_leave_point_projection(vault_id="vault-test", channel="test", vault_root=vault_root)

    assert projection.status == "present"
    assert projection.artifact_ref.artifact_uuid == "artifact-1"
    assert projection.artifact_ref.logical_ref == "notes/cursor.md"
    assert event["last_session_id"] == "session-1"


def test_cursor_loss_degrades_to_fresh_orientation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "absent"
    assert data["leave_point"]["authority_role"] == "derived_runtime_projection"
    assert data["meta"]["freshness"] == "fresh"


def test_cursor_contains_references_only() -> None:
    event = _capture()
    forbidden = {
        "body",
        "summary",
        "diff",
        "embedding",
        "working_set",
        "open_tabs",
        "selection",
        "scroll_position",
        "raw_chat_history",
        "memory_candidate",
        "receipt",
        "writeguard",
        "absolute_path",
        "orientation_summary",
        "resurfacing_candidates",
    }

    assert set(event) == ALLOWED_CURSOR_FIELDS
    assert set(event["source_ref"]) == ALLOWED_SOURCE_REF_FIELDS
    assert not forbidden.intersection(event)
    assert all("/Users/" not in json.dumps(value) for value in event.values())


def test_cursor_is_reference_only() -> None:
    test_cursor_contains_references_only()


def test_orientation_uses_cursor_with_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")
    _capture(trace_id="trace-cursor")

    with_cursor = _orientation(client, monkeypatch)
    clear_leave_point_trace()
    without_cursor = _orientation(client, monkeypatch)

    assert with_cursor["leave_point"]["status"] == "present"
    assert with_cursor["leave_point"]["authority_role"] == "operational_trace_pointer"
    assert with_cursor["leave_point"]["source_ref"] == {
        "kind": "artifact_activation",
        "trace_id": "trace-cursor",
    }
    assert without_cursor["leave_point"]["status"] == "absent"
    assert without_cursor["leave_point"]["authority_role"] == "derived_runtime_projection"


def test_cursor_loss_degrades_gracefully(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    test_cursor_loss_degrades_to_fresh_orientation(client, monkeypatch)


def test_stale_cursor_marked_stale_not_used_as_fact(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    note = _note(vault_root, "notes/cursor.md", "artifact-1")
    old_hash = companion_module._content_hash(note.read_text(encoding="utf-8"))
    _capture(content_hash_at_capture=old_hash)
    note.write_text(note.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "stale"
    assert data["leave_point"]["artifact_ref"]["artifact_uuid"] == "artifact-1"


def test_deleted_artifact_produces_degraded_leave_point(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    note = _note(vault_root, "notes/cursor.md", "artifact-1")
    _capture()
    note.unlink()

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "artifact_missing"
    assert data["leave_point"]["artifact_ref"]["artifact_uuid"] == "artifact-1"
    assert data["leave_point"]["artifact_ref"]["logical_ref"] is None


def test_cross_channel_cursor_ignored(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")
    _capture(channel="dev")

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "absent"


def test_cross_vault_cursor_ignored(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")
    _capture(vault_id="other-vault")

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "absent"


def test_cursor_hash_mismatch_degrades_not_overrides(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_stale_cursor_marked_stale_not_used_as_fact(client, monkeypatch)


def test_orientation_read_does_not_write_cursor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_cursor = MagicMock(side_effect=AssertionError("GET orientation must not write cursor"))
    monkeypatch.setattr(cursor_module, "capture_leave_point_cursor", write_cursor)

    data = _orientation(client, monkeypatch)

    assert data["mutation_intents"] == []
    assert write_cursor.call_count == 0


def test_no_vault_write_for_cursor_capture(tmp_path: Path) -> None:
    _capture()
    assert list(tmp_path.rglob("*.md")) == []


def test_no_receipt_write_for_cursor_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    write_outbox = MagicMock(side_effect=AssertionError("cursor capture must not write receipts/outbox"))
    monkeypatch.setattr(outbox_service, "write_outbox_event", write_outbox)

    _capture()

    assert write_outbox.call_count == 0


def test_no_memory_write_for_cursor_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    remember = MagicMock(side_effect=AssertionError("cursor capture must not write memory"))
    monkeypatch.setattr(memory_store, "remember", remember)

    _capture()

    assert remember.call_count == 0


def test_cursor_rejects_absolute_note_path() -> None:
    with pytest.raises(ValueError):
        capture_leave_point_cursor(
            vault_id="vault-test",
            channel="test",
            artifact_uuid="artifact-1",
            source_kind="artifact_activation",
            source_ref_id="/Users/rasmus/vault/notes/cursor.md",
            capture_reason="artifact_focus",
            trace_id="trace-1",
        )


def test_latest_valid_cursor_wins_concurrent_sessions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/one.md", "artifact-1", title="One")
    _note(vault_root, "notes/two.md", "artifact-2", title="Two")
    base = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    _capture(artifact_uuid="artifact-1", trace_id="trace-old", captured_at=base)
    _capture(artifact_uuid="artifact-2", trace_id="trace-new", captured_at=base + timedelta(seconds=1))

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "present"
    assert data["leave_point"]["artifact_ref"]["artifact_uuid"] == "artifact-2"
    assert data["leave_point"]["source_ref"]["trace_id"] == "trace-new"


def test_corrupt_cursor_ignored_and_next_valid_cursor_used(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")
    _capture(trace_id="trace-valid")
    append_raw_leave_point_trace("{not-json")

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "present"
    assert data["leave_point"]["source_ref"]["trace_id"] == "trace-valid"


def test_missing_trace_id_rejected_or_ignored(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")
    event = _capture(trace_id="trace-valid")
    bad = dict(event)
    bad.pop("trace_id")
    append_raw_leave_point_trace(json.dumps(bad))

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "present"
    assert data["leave_point"]["source_ref"]["trace_id"] == "trace-valid"


def test_missing_source_ref_rejected_or_ignored(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")
    event = _capture(trace_id="trace-valid")
    bad = dict(event)
    bad.pop("source_ref")
    append_raw_leave_point_trace(json.dumps(bad))

    data = _orientation(client, monkeypatch)

    assert data["leave_point"]["status"] == "present"
    assert data["leave_point"]["source_ref"]["trace_id"] == "trace-valid"


def test_cursor_does_not_emit_mutation_intents(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")
    _capture()

    data = _orientation(client, monkeypatch)

    assert data["mutation_intents"] == []


def test_scope_filtered_query_finds_valid_cursor_after_many_cross_scope_rows() -> None:
    # Regression: old code fetched LIMIT 100 globally then filtered in Python,
    # which hid a valid in-scope cursor when >100 cross-scope rows existed first.
    vault_root = Path(os.environ["VAULT_ROOT"])
    _note(vault_root, "notes/cursor.md", "artifact-1")

    base = datetime.now(timezone.utc) - timedelta(hours=1)
    # Insert 110 cross-scope rows (wrong channel) with timestamps newer than the valid row.
    for i in range(110):
        capture_leave_point_cursor(
            vault_id="vault-test",
            channel="other-channel",
            artifact_uuid=f"artifact-cross-{i}",
            source_kind="artifact_activation",
            source_ref_id="notes/cursor.md",
            capture_reason="artifact_focus",
            trace_id=f"trace-cross-{i}",
            captured_at=base + timedelta(seconds=i + 1),
        )

    # Insert the valid in-scope row with the oldest timestamp among all rows.
    _capture(
        artifact_uuid="artifact-1",
        vault_id="vault-test",
        channel="test",
        trace_id="trace-valid",
        captured_at=base,
    )

    projection = latest_leave_point_projection(
        vault_id="vault-test",
        channel="test",
        vault_root=vault_root,
    )

    assert projection.status == "present"
    assert projection.artifact_ref.artifact_uuid == "artifact-1"
    assert projection.source_ref.trace_id == "trace-valid"
