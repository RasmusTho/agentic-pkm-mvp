from pathlib import Path

from app.settings import settings


def test_ingest_text_writes_markdown_and_stages(client, tmp_path, monkeypatch):
    staged = {}

    def fake_stage(chunks, config=None):
        staged["chunks"] = list(chunks)

    monkeypatch.setattr("app.api.ingest.stage_chunks", fake_stage)
    monkeypatch.setattr(settings, "vault_dir", str(tmp_path / "vault"), raising=False)
    monkeypatch.setattr(settings, "chunk_size", 5, raising=False)
    monkeypatch.setattr(settings, "chunk_overlap", 2, raising=False)

    payload = {
        "source": {"type": "text", "text": "one two three four five six seven"},
        "tags": ["topic/test"],
    }

    response = client.post("/ingest", json=payload)
    assert response.status_code == 202

    data = response.json()
    assert data["trust"] == "provisional"
    assert data["title"].lower().startswith("one")
    assert len(data["chunks"]) == len(staged["chunks"])

    vault_path = Path(settings.vault_dir) / data["path"]
    assert vault_path.exists()
    content = vault_path.read_text(encoding="utf-8")
    assert content.startswith("---")
    assert "one two three" in content

    first_chunk = data["chunks"][0]
    assert first_chunk["size"] == len(first_chunk["text"].split())
    assert staged["chunks"][0].doc_path == data["path"]
    assert staged["chunks"][0].trust == "provisional"
