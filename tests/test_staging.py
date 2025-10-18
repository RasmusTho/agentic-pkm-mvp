from pathlib import Path

from app.ingest.chunker import ChunkConfig
from app.ingest.staging import PendingChunk, list_pending_documents, promote_document, stage_chunks
from app.settings import settings


def test_stage_and_list_pending(monkeypatch, tmp_path):
    db_path = tmp_path / "staging.duckdb"
    monkeypatch.setattr(settings, "staging_db_path", str(db_path), raising=False)

    chunks = [
        PendingChunk(id="c1", text="alpha beta", size=2, doc_path="Inbox/foo.md"),
        PendingChunk(id="c2", text="gamma delta", size=2, doc_path="Inbox/foo.md"),
    ]
    stage_chunks(chunks, ChunkConfig(size=4, overlap=1))

    docs = list_pending_documents()
    assert len(docs) == 1
    doc = docs[0]
    assert doc.doc_path == "Inbox/foo.md"
    assert doc.chunk_count == 2
    assert doc.trust == "provisional"

    updated = promote_document("Inbox/foo.md", "reviewed")
    assert updated == 2
    docs_after = list_pending_documents()
    assert all(d.trust != "provisional" for d in docs_after)
