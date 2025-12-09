from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.api.app import app
from app.api.routes import ask as ask_module
from app.cli import cli
from app.stores import get_object_store, reset_store_backends
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _force_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response [#1]")


def test_external_ingest_cli_creates_objects(tmp_path: Path) -> None:
    reset_store_backends()
    drop = tmp_path / "external"
    drop.mkdir(parents=True, exist_ok=True)
    f1 = drop / "news.txt"
    f1.write_text("External newsletter about LangGraph planning.", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(cli, ["ingest-external", "--root", str(drop)])
    assert result.exit_code == 0, result.output
    assert "External ingest" in result.output

    store = get_object_store()
    objs = list(store.list_by_kind("external"))
    assert len(objs) == 1
    payload = objs[0].get("payload") or {}
    assert payload.get("origin") == "external_raw"
    assert payload.get("plane") == "external"
    assert payload.get("title") == "news"


def test_external_ingest_objects_are_ask_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    # Reset hybrid store documents
    from app.retrieval.hybrid import get_store as get_hybrid_store

    get_hybrid_store().set_documents([])
    drop = tmp_path / "external"
    drop.mkdir(parents=True, exist_ok=True)
    f1 = drop / "post.txt"
    f1.write_text("This is an external corpus entry about serendipity.", encoding="utf-8")

    runner = CliRunner()
    runner.invoke(cli, ["ingest-external", "--root", str(drop)])

    # Warm hybrid store to pick up new objects
    ask_module._HYBRID_WARMED = False
    client = TestClient(app)
    resp = client.post("/api/ask", json={"question": "serendipity"})
    assert resp.status_code == 200
    data = resp.json()
    sources = data.get("sources") or []
    assert any(src.get("origin") == "external_raw" and src.get("plane") == "external" for src in sources)
