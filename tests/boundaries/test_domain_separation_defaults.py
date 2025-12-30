from __future__ import annotations

from app.retrieval.hybrid import get_store, hybrid_search


def test_domain_separation_defaults_excludes_cross_domain(monkeypatch) -> None:
    store = get_store()
    store.set_documents([])

    store.add_document(
        doc_id="work-1",
        text="Shared marker text",
        source_ref="work/note.md",
        payload={"domain": "work"},
    )
    store.add_document(
        doc_id="rpg-1",
        text="Shared marker text",
        source_ref="rpg/note.md",
        payload={"domain": "rpg"},
    )

    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    results = hybrid_search("marker", k=5)
    ids = {res.get("doc_id") for res in results}
    assert "work-1" in ids
    assert "rpg-1" not in ids


def test_domain_bridge_allows_cross_domain(monkeypatch) -> None:
    store = get_store()
    store.set_documents([])

    store.add_document(
        doc_id="work-2",
        text="Shared marker text",
        source_ref="work/note.md",
        payload={"domain": "work"},
    )
    store.add_document(
        doc_id="rpg-bridge",
        text="Shared marker text",
        source_ref="rpg/note.md",
        payload={"domain": "rpg", "bridge_domains": ["work"]},
    )

    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    results = hybrid_search("marker", k=5)
    ids = {res.get("doc_id") for res in results}
    assert "work-2" in ids
    assert "rpg-bridge" in ids
