from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.app import app
from app.observability.ingest_meta import record_ingest_run, reset_ingest_meta
from app.observability.status_service import reset_ask_metrics
from app.stores import get_object_store, reset_store_backends


def test_interim_gui_loads() -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "Reality-MVP Dashboard" in html
    assert "Status" in html
    assert "Health" in html
    assert "Settings" in html
    assert "Recent events" in html
    assert "/api/status" in html
    assert "/api/ask" in html
    assert "/api/health" in html
    assert "/api/settings/validate" in html
    assert "/api/events/tail" in html
    assert "Returned:" in html
    assert 'value="watcher."' in html


def test_interim_gui_refs_status_snapshot_data() -> None:
    reset_store_backends()
    reset_ingest_meta()
    reset_ask_metrics()
    store = get_object_store()
    store.put(
        uuid4(),
        kind="note",
        source_ref="vault/path",
        payload={"title": "Vault note", "origin": "vault"},
    )
    store.put(
        uuid4(),
        kind="note",
        source_ref="ext/path",
        payload={"title": "Ext", "origin": "external_raw", "plane": "external"},
    )
    record_ingest_run("vault", scanned=2, ingested=2, errors=0, malformed=0)

    client = TestClient(app)
    resp = client.get("/api/status")
    data = resp.json()
    planes = {s["name"]: s["object_count"] for s in data["stores"]}
    assert planes.get("vault") == 1
    assert planes.get("external") == 1

    page = client.get("/")
    assert page.status_code == 200
    html = page.text
    assert "Stores" in html
    assert "Ingestion" in html
    assert "ASK (24h)" in html
    assert "Health" in html
    assert "Settings validation" in html
    assert "Recent events" in html
