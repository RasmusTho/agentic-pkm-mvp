"""MVR-05B4c4 (#6214): orientation runtime signals and the leave-point cursor scoped per binding.

A scoped ``/orientation`` or ``/workspace`` read computes its runtime signals (ingest runs,
status-outbox events, worker queue) from the request binding's stamped work only, so another
binding's backlog never changes them; a carrier-free read keeps the process-wide view. The
leave-point cursor is keyed by binding (two bindings sharing a display name keep separate
cursors) and a scoped read opens it read-only, never creating or migrating the DB.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.events.types import PROMOTE_INTENT_CREATED
from app.instance.settings_rebind import _install_dormant_settings_rebind
from app.observability import ingest_meta
from app.observability.ingest_meta import record_ingest_run
from app.orientation.leave_point_cursor import capture_leave_point_cursor
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def two_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.vault.manager as vault_manager_module

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    # Binding A is the compatibility binding the carrier-free producers stamp.
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=first.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    for root, uuid in ((Path(first.path), "note-a-uuid"), (Path(second.path), "note-b-uuid")):
        initialize_test_vault(root)
        (root / "shared.md").write_text(f"---\nuuid: {uuid}\n---\n\n# Shared\n", encoding="utf-8")
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    # Isolated process-global signal stores: ingest status, JSONL outbox, cursor DB.
    monkeypatch.setenv("INGEST_STATUS_PATH", str(tmp_path / "ingest_status.json"))
    monkeypatch.setattr(ingest_meta, "_last_ingest_run_at", None)
    monkeypatch.setattr(ingest_meta, "_last_ingest_run_ok", None)
    monkeypatch.setattr(ingest_meta, "_last_ingest_error_message", None)
    monkeypatch.setattr(ingest_meta, "_last_runs", {})
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("WORKER_ENABLE", "1")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    cursor_db = tmp_path / "cursor" / "leave_point.sqlite3"
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(cursor_db))
    return TestClient(app), first, second, outbox, cursor_db


def _headers(client: TestClient, binding_id: str) -> dict[str, str]:
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding_id]}
    )
    assert created.status_code == 201, created.text
    return {"X-Active-Context-Session": created.json()["context_selection_id"]}


def _select(client: TestClient, root: Path) -> None:
    selected = client.post(
        "/api/companion/vault/select", json={"path": str(root), "remember": False}
    )
    assert selected.status_code == 200, selected.text


def _orientation(client: TestClient, headers: dict[str, str] | None) -> dict:
    response = client.get("/api/companion/orientation", headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


def _runtime(client: TestClient, headers: dict[str, str] | None) -> dict:
    response = client.get(
        "/api/companion/workspace", params={"note_path": "shared.md"}, headers=headers or {}
    )
    assert response.status_code == 200, response.text
    return response.json()["runtime"]


def _append(outbox: Path, event: str, binding: str | None, count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    meta = {"vault_binding_id": binding} if binding else {}
    with outbox.open("a", encoding="utf-8") as handle:
        for _ in range(count):
            handle.write(json.dumps({"event": event, "timestamp": now, "meta": meta}) + "\n")


def _signal_view(body: dict) -> dict:
    return {
        "notable": [change["label"] for change in body["notable_changes"]],
        "changed_at": [change["changed_at"] for change in body["notable_changes"]],
        "open_loops": [loop["label"] for loop in body["open_loops"]],
        "resurface": [c["id"] for c in body["resurface"]["candidates"]],
        "leave_point_at": (body["leave_point"] or {}).get("captured_at"),
    }


def _reorient_view(runtime: dict) -> dict:
    reorient = runtime["reorient"]
    return {
        "facts": [item["label"] for item in reorient["facts"]],
        "deltas": [item["label"] for item in reorient["recent_deltas"]],
        "loops": [item["label"] for item in reorient["open_loops"]],
        "resurface": [c["candidate_id"] for c in runtime["resurface"]["candidates"]],
    }


def test_scoped_orientation_and_workspace_runtime_signals_are_binding_scoped(two_bindings) -> None:
    client, first, second, outbox, _cursor_db = two_bindings
    a, b = first.vault_binding_id, second.vault_binding_id

    # Production producer default: the carrier-free ingest run stamps the live binding (A).
    record_ingest_run("vault", scanned=2, ingested=2, errors=0)
    # Binding B's own work: an ingest run, watcher runs and a promotion backlog.
    record_ingest_run("external", scanned=9, ingested=9, errors=0, vault_binding_id=b)
    _append(outbox, "watcher.run", b, 3)
    _append(outbox, PROMOTE_INTENT_CREATED, b, 2)
    # Unstamped legacy history is never adopted into either binding.
    _append(outbox, "watcher.run", None, 5)

    headers_a, headers_b = _headers(client, a), _headers(client, b)
    orientation_a = _orientation(client, headers_a)
    orientation_b = _orientation(client, headers_b)
    assert "orientation_source_unavailable" not in json.dumps(orientation_a["meta"])
    [notable_a] = _signal_view(orientation_a)["notable"]
    [notable_b] = _signal_view(orientation_b)["notable"]
    assert "ingest_total=2" in notable_a and "watcher_runs_total=0" in notable_a
    assert "ingest_total=9" in notable_b and "watcher_runs_total=3" in notable_b
    assert "resurface-pending-promotions" not in _signal_view(orientation_a)["resurface"]
    assert "resurface-pending-promotions" in _signal_view(orientation_b)["resurface"]

    runtime_a, runtime_b = _runtime(client, headers_a), _runtime(client, headers_b)
    assert any("watcher_runs_24h=0" in fact for fact in _reorient_view(runtime_a)["facts"])
    assert any("watcher_runs_24h=3" in fact for fact in _reorient_view(runtime_b)["facts"])
    assert "resurface-pending-promotions" not in _reorient_view(runtime_a)["resurface"]
    assert "resurface-pending-promotions" in _reorient_view(runtime_b)["resurface"]

    # More of B's backlog never changes binding A's scoped signals.
    before_orientation, before_runtime = _signal_view(orientation_a), _reorient_view(runtime_a)
    record_ingest_run("vault", scanned=40, ingested=40, errors=3, vault_binding_id=b)
    _append(outbox, "watcher.run", b, 7)
    _append(outbox, PROMOTE_INTENT_CREATED, b, 4)
    assert _signal_view(_orientation(client, headers_a)) == before_orientation
    assert _reorient_view(_runtime(client, headers_a)) == before_runtime
    assert "watcher_runs_total=10" in _signal_view(_orientation(client, headers_b))["notable"][0]

    # A blank carrier is still scoped: it never falls back to the process-wide signals.
    blank = client.get("/api/companion/orientation", headers={"X-Active-Context-Session": ""})
    assert "watcher_runs_total=15" not in blank.text

    # The carrier-free view keeps the process-wide signals (stamped and unstamped).
    _select(client, Path(first.path))
    [notable_global] = _signal_view(_orientation(client, None))["notable"]
    assert "watcher_runs_total=15" in notable_global


def test_scoped_leave_point_cursor_is_binding_keyed_and_read_never_creates(
    two_bindings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, first, second, _outbox, cursor_db = two_bindings
    a, b = first.vault_binding_id, second.vault_binding_id
    headers_a, headers_b = _headers(client, a), _headers(client, b)

    # A scoped read with no cursor DB is an empty projection and never creates it.
    assert _orientation(client, headers_a)["leave_point"]["status"] == "absent"
    assert _orientation(client, headers_b)["leave_point"]["status"] == "absent"
    assert not cursor_db.exists() and not cursor_db.parent.exists()

    # A DB written before binding keying is legacy-only and never migrated by a read.
    cursor_db.parent.mkdir(parents=True)
    with sqlite3.connect(cursor_db) as legacy:
        legacy.execute(
            "CREATE TABLE leave_point_trace_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_type TEXT NOT NULL, vault_id TEXT NOT NULL, channel TEXT NOT NULL, "
            "artifact_uuid TEXT NOT NULL, captured_at TEXT NOT NULL, trace_id TEXT NOT NULL, "
            "payload TEXT NOT NULL)"
        )
    legacy_bytes = cursor_db.read_bytes()
    assert _orientation(client, headers_a)["leave_point"]["status"] == "absent"
    assert cursor_db.read_bytes() == legacy_bytes
    cursor_db.unlink()

    # Production producer: a carrier-free canvas session on vault A stamps binding A.
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    _select(client, Path(first.path))
    opened = client.post("/api/canvas/sessions", json={"note_path": "shared.md"})
    assert opened.status_code in (200, 201), opened.text
    with sqlite3.connect(cursor_db) as conn:
        [(display_name, channel, stamp)] = conn.execute(
            "SELECT vault_id, channel, vault_binding_id FROM leave_point_trace_events"
        ).fetchall()
    assert stamp == a

    # Binding B shares A's display name; an unstamped legacy row shares it too and is newer.
    capture_leave_point_cursor(
        vault_id=display_name,
        channel=channel,
        artifact_uuid="note-b-uuid",
        source_kind="artifact_activation",
        source_ref_id="shared.md",
        capture_reason="artifact_focus",
        vault_binding_id=b,
    )
    capture_leave_point_cursor(
        vault_id=display_name,
        channel=channel,
        artifact_uuid="legacy-uuid",
        source_kind="artifact_activation",
        source_ref_id="shared.md",
        capture_reason="artifact_focus",
    )
    before = cursor_db.read_bytes()
    point_a = _orientation(client, headers_a)["leave_point"]
    point_b = _orientation(client, headers_b)["leave_point"]
    assert point_a["status"] == "present"
    assert point_a["artifact_ref"]["artifact_uuid"] == "note-a-uuid"
    assert point_b["status"] == "present"
    assert point_b["artifact_ref"]["artifact_uuid"] == "note-b-uuid"
    # A scoped read never writes the cursor DB.
    assert cursor_db.read_bytes() == before


def test_unprovable_ingest_run_keeps_binding_history(two_bindings) -> None:
    """#6251 review: a run with no provable binding never erases other bindings' history."""

    client, first, second, _outbox, _cursor_db = two_bindings
    record_ingest_run(
        "vault", scanned=4, ingested=4, errors=0, vault_binding_id=second.vault_binding_id
    )
    record_ingest_run("vault", scanned=1, ingested=1, errors=0, vault_binding_id="")
    [notable_b] = _signal_view(_orientation(client, _headers(client, second.vault_binding_id)))[
        "notable"
    ]
    assert "ingest_total=4" in notable_b
