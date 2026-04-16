from __future__ import annotations

import pytest
from uuid import UUID

from app.retrieval.hybrid import get_store, hybrid_search
from app.stores import get_relation_index, reset_store_backends


@pytest.fixture(autouse=True)
def _reset_store_backends() -> None:
    reset_store_backends()
    yield
    reset_store_backends()


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


def test_missing_payload_domain_is_excluded_from_domain_scope(monkeypatch) -> None:
    """A document with no payload domain must not be included in a domain-scoped search,
    even if its source_ref path starts with the active domain name."""
    store = get_store()
    store.set_documents([])

    store.add_document(
        doc_id="no-domain-1",
        text="Shared marker text",
        source_ref="work/note.md",
        payload={},
    )
    store.add_document(
        doc_id="work-explicit",
        text="Shared marker text",
        source_ref="work/other.md",
        payload={"domain": "work"},
    )

    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    results = hybrid_search("marker", k=5)
    ids = {res.get("doc_id") for res in results}
    assert "work-explicit" in ids
    assert "no-domain-1" not in ids, (
        "Document with no payload domain must not be included via path-derived inference"
    )


def test_path_change_does_not_invent_domain(monkeypatch) -> None:
    """Moving a note to a different folder must not silently assign a domain when
    the payload carries no domain field."""
    store = get_store()
    store.set_documents([])

    # Same document, different source_ref paths — neither should be scope-included
    store.add_document(
        doc_id="moved-1",
        text="Shared marker text",
        source_ref="work/subfolder/note.md",
        payload={},
    )
    store.add_document(
        doc_id="moved-2",
        text="Shared marker text",
        source_ref="personal/note.md",
        payload={},
    )

    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    results = hybrid_search("marker", k=5)
    ids = {res.get("doc_id") for res in results}
    assert "moved-1" not in ids, "Path-matching source_ref must not grant domain membership"
    assert "moved-2" not in ids


def test_sphere_membership_relation_does_not_change_scope_filter(monkeypatch) -> None:
    store = get_store()
    store.set_documents([])
    rel = get_relation_index()

    rel.add_membership(
        UUID("00000000-0000-0000-0000-000000000111"),
        rel="sphere_membership",
        value="work",
    )
    store.add_document(
        doc_id="rpg-shared",
        text="Shared marker text",
        source_ref="rpg/note.md",
        payload={"domain": "rpg"},
    )

    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    results = hybrid_search("marker", k=5)
    ids = {res.get("doc_id") for res in results}
    assert "rpg-shared" not in ids
