from __future__ import annotations

from uuid import uuid4

import pytest

from app.stores.memory import MemoryRelationIndex
from app.stores.relation_candidates import (
    RelationCandidate,
    extract_semantic_relations,
    register_relation_candidates,
)

pytestmark = pytest.mark.not_pg


def test_extract_semantic_relations_parses_frontmatter_and_body() -> None:
    dst_supports = str(uuid4())
    dst_derivation = str(uuid4())
    dst_tag = str(uuid4())
    dst_body = str(uuid4())
    metadata = {
        "supports": [dst_supports],
        "relations": [{"target": dst_derivation, "type": "derived_from"}],
        "tags": [f"contradicts:{dst_tag}"],
    }
    body = f"See also: {dst_body}\nDerived from: {dst_derivation}"
    candidates = extract_semantic_relations(metadata, body)
    assert any(c.rel == "supports" and c.target == dst_supports for c in candidates)
    assert any(c.rel == "derived_from" and c.target == dst_derivation for c in candidates)
    assert any(c.rel == "contradicts" and c.target == dst_tag for c in candidates)
    assert any(c.source == "body.see_also" and c.target == dst_body for c in candidates)


def test_register_relation_candidates_audits_missing_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    rel_index = MemoryRelationIndex()
    src = uuid4()
    valid_dst = uuid4()
    events: list[dict] = []

    def fake_audit(**payload):
        events.append(payload)

    monkeypatch.setattr("app.stores.relation_candidates.audit_log", fake_audit)
    added, missing = register_relation_candidates(
        src,
        [
            RelationCandidate(target=str(valid_dst), rel="supports", source="frontmatter.supports"),
            RelationCandidate(target="not-a-uuid", rel="extends", source="frontmatter.supports"),
        ],
        relation_index=rel_index,
    )
    assert added == 1
    assert missing == 1
    assert rel_index.neighbors(src, rel="supports") == [valid_dst]
    assert any(event["action"] == "relation.added" for event in events)
    assert any(event["action"] == "relation.missing" for event in events)
