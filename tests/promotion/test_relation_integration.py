from __future__ import annotations

from uuid import uuid4

import pytest

from app.promotion.gates import OrphanPromotionError, prepare_relations_for_promotion
from app.stores.memory import MemoryRelationIndex

pytestmark = pytest.mark.not_pg


def test_prepare_relations_registers_links(monkeypatch: pytest.MonkeyPatch) -> None:
    rel_index = MemoryRelationIndex()
    src = uuid4()
    dst = uuid4()
    audit_events: list[dict] = []

    def fake_audit(**payload):
        audit_events.append(payload)

    monkeypatch.setattr("app.promotion.gates.audit_log", fake_audit)
    monkeypatch.setattr("app.stores.relation_index.audit_log", fake_audit)
    added = prepare_relations_for_promotion(
        src,
        metadata={"supports": [str(dst)]},
        body=f"See also: {dst}",
        relation_index=rel_index,
        require_relations=True,
    )
    assert added == 1
    assert rel_index.neighbors(src, rel="supports") == [dst]
    assert any(event["action"] == "relation.added" for event in audit_events)


def test_prepare_relations_blocks_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    rel_index = MemoryRelationIndex()
    src = uuid4()
    audit_events: list[dict] = []

    def fake_audit(**payload):
        audit_events.append(payload)

    monkeypatch.setattr("app.promotion.gates.audit_log", fake_audit)
    monkeypatch.setattr("app.stores.relation_index.audit_log", fake_audit)
    with pytest.raises(OrphanPromotionError):
        prepare_relations_for_promotion(
            src,
            metadata={},
            body="",
            relation_index=rel_index,
            require_relations=True,
        )
    assert any(event["action"] == "relation.missing" for event in audit_events)
