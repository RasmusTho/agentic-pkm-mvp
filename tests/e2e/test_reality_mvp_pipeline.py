from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_route
from app.ingest.vault_root import ingest_vault_root
from app.observability.ingest_meta import reset_ingest_meta
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.stores import get_object_store, reset_store_backends

SCENARIO_DOC = Path("docs/scenarios/REALITY_MVP.md")
FIXTURE_NOTE = Path("tests/fixtures/reality_mvp/demo_note.md")


@pytest.mark.e2e
def test_reality_mvp_note_ingest_and_ask(tmp_path: Path, monkeypatch) -> None:
    """
    See docs/scenarios/REALITY_MVP.md for the end-to-end Reality-MVP flow description.
    """
    assert SCENARIO_DOC.exists()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    monkeypatch.setenv("INGEST_STATUS_PATH", str(tmp_path / "ingest_status.json"))

    reset_store_backends()
    reset_ingest_meta()
    get_hybrid_store().set_documents([])
    monkeypatch.setattr(ask_route, "_HYBRID_WARMED", False, raising=False)

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_path = vault_root / "demo_note.md"
    note_path.write_text(FIXTURE_NOTE.read_text(encoding="utf-8"), encoding="utf-8")

    ingested = ingest_vault_root(vault_root, limit=1)
    assert ingested == 1

    store = get_object_store()
    objects = getattr(store, "_objects", {})
    assert len(objects) >= 1
    stored = next(iter(objects.values()))
    assert str(note_path) == str(stored.get("source_ref"))

    client = TestClient(app)
    question = "Which store backend do the Reality-MVP tests rely on?"
    resp = client.post("/api/ask", json={"question": question})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    answer = str(data.get("answer") or "")
    assert answer
    assert "memory" in answer.lower()

    sources = data.get("sources") or []
    assert sources
    source_paths = [src.get("path") for src in sources if src]
    assert any(path and Path(path).name == note_path.name for path in source_paths)
    assert any(path and path == str(note_path) for path in source_paths)
