import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.observability import status_service


def test_status_endpoint_returns_snapshot():
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "timestamp" in body
    assert body.get("sot_version")
    assert body.get("sot_baseline_version")
    assert body.get("sot_forward_line_version")
    assert isinstance(body.get("stores"), list)
    assert body.get("feature_line_version") == body.get("sot_forward_line_version")
    assert isinstance(body.get("active_features"), list)
    intents = body.get("intents") or {}
    assert "promote_created_total" in intents
    events = body.get("events") or {}
    assert "panel_runs_total" in events
    assert "watcher_runs_total" in events
    assert "promotion_executed_total" in events
    assert isinstance(events.get("ingest_runs_by_plane", {}), dict)

    events_log = body.get("events_log") or {}
    assert "path" in events_log
    assert "total_lines" in events_log

    worker_queue = body.get("worker_queue") or {}
    assert "mode" in worker_queue

    panel_diag = body.get("panel_diagnostics") or {}
    assert "resolved_panel_actions_root" in panel_diag
    assert "panel_actions_mappings_count" in panel_diag
    assert "panel_actions_ids_sample" in panel_diag
    assert "has_promote_evergreen_mapping" in panel_diag
    assert "last_panel_mapping_load_error" in panel_diag
    assert "source_paths" in panel_diag
    assert "source_mtimes" in panel_diag
    assert "combined_sha256" in panel_diag


def test_status_counts_watcher_runs(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "outbox.jsonl"
    watcher_event = {"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z"}
    outbox.write_text(json.dumps(watcher_event) + "\n", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    status_service.INDEX_OUTBOX_PATH = str(outbox)

    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    events = data.get("events") or {}
    assert events.get("watcher_runs_total", 0) >= 1

    events_log = data.get("events_log") or {}
    assert events_log.get("total_lines") == 1


def test_status_counts_align_with_events(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "outbox.jsonl"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    events = [
        {"event": "watcher.run", "timestamp": now},
        {"event": "panel.intent.executed", "timestamp": now},
        {"event": "promote.intent.created", "timestamp": now},
        {"event": "promote.done", "timestamp": now},
    ]
    outbox.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    status_service.INDEX_OUTBOX_PATH = str(outbox)

    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()

    event_counts = data.get("events") or {}
    assert event_counts.get("watcher_runs_total") == 1
    assert event_counts.get("panel_runs_total") == 1
    assert event_counts.get("promote_created_total") == 1
    assert event_counts.get("promotion_executed_total") == 1

    intents = data.get("intents") or {}
    assert intents.get("promote_created_total") == 1

    events_log = data.get("events_log") or {}
    assert events_log.get("total_lines") == len(events)


def test_status_exposes_panel_provenance():
    """Verify status snapshot exposes panel actions compiler provenance."""
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()

    panel_diag = body.get("panel_diagnostics") or {}
    # Provenance fields should always be present in the response
    assert isinstance(panel_diag.get("source_paths"), list)
    assert isinstance(panel_diag.get("source_mtimes"), list)
    # combined_sha256 may be None if panel actions settings cannot be loaded
    # but the field should exist in the response
    assert "combined_sha256" in panel_diag

    # If source_paths is not empty, source_mtimes should have the same length
    source_paths = panel_diag.get("source_paths", [])
    source_mtimes = panel_diag.get("source_mtimes", [])
    if source_paths:
        assert len(source_mtimes) == len(source_paths)
