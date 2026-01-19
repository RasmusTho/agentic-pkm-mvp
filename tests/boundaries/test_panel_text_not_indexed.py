from __future__ import annotations

from app.components.embeddings import get_embedding_identity
from app.search.service import ingest_object
from app.stores import get_vector_index, reset_store_backends


def _query_vector(dim: int = 1536) -> list[float]:
    return [1.0] + [0.0] * (dim - 1)


def test_panel_text_not_indexed(monkeypatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()

    marker_panel = "P0_PANEL_MARKER_DO_NOT_INDEX"
    marker_body = "P0_KNOWLEDGE_MARKER"
    markdown = (
        "# Note\n\n"
        f"Knowledge: {marker_body}\n\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        f"{marker_panel}\n"
        "%% AI:End %%\n"
    )

    ingest_object(
        kind="note",
        source_ref="work/note.md",
        payload={"title": "Boundary Test"},
        text=markdown,
    )

    idx = get_vector_index()
    identity = get_embedding_identity()
    hits = idx.search(_query_vector(identity.dim), k=5, identity=identity)
    assert hits, "expected indexed hits"

    texts = [str(getattr(hit, "payload", {}).get("text") or "") for hit in hits]
    assert any(marker_body in text for text in texts)
    assert all(marker_panel not in text for text in texts)
