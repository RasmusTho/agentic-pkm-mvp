"""
Canonical import boundary for object-store contract types.

All callers that need ``DomainObject``, ``ObjectStore``, ``RelationEdge``,
``GraphSlice``, ``RelationIndex``, ``ScoredNeighbor``, or ``VectorIndex``
should import from this package::

    from app.objects import DomainObject, ObjectStore
    from app.objects import RelationIndex, RelationEdge, GraphSlice
    from app.objects import VectorIndex, ScoredNeighbor

``app.store.object_store``, ``app.store.relation_index``, and
``app.store.vector_index`` remain as backward-compatibility shims for
existing callers and will be migrated per-area in follow-up issues.
See docs/CODE_INVENTORY.md :: Cleanup follow-ups.
"""

from app.store.object_store import DomainObject, ObjectStore
from app.store.relation_index import RelationEdge, GraphSlice, RelationIndex
from app.store.vector_index import ScoredNeighbor, VectorIndex

__all__ = [
    "DomainObject",
    "ObjectStore",
    "RelationEdge",
    "GraphSlice",
    "RelationIndex",
    "ScoredNeighbor",
    "VectorIndex",
]
