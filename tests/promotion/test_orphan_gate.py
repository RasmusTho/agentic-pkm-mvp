from __future__ import annotations

from uuid import UUID

import pytest

from app.promotion.gates import OrphanPromotionError, ensure_object_has_relations


class _FakeRelationIndex:
    def __init__(self, has_relation: bool) -> None:
        self._has_relation = has_relation

    def has_any(self, src: UUID) -> bool:  # pragma: no cover - simple shim
        return self._has_relation


def test_orphan_gate_allows_when_relations_exist() -> None:
    ensure_object_has_relations(
        UUID(int=1),
        relation_index=_FakeRelationIndex(True),
    )


def test_orphan_gate_blocks_without_relations() -> None:
    with pytest.raises(OrphanPromotionError):
        ensure_object_has_relations(
            UUID(int=1),
            relation_index=_FakeRelationIndex(False),
            allow_orphans=False,
        )


def test_orphan_gate_respects_override() -> None:
    ensure_object_has_relations(
        UUID(int=1),
        relation_index=_FakeRelationIndex(False),
        allow_orphans=True,
    )
