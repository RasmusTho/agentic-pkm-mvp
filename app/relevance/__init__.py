"""Contextual Relevance Engine — runtime package.

First runtime slice (CRE-03): compute moments from vault-native data, materialize
them as governed artifacts with receipts, and project them to the companion-UI
glance surface, pull-only. No proactivity, no external sources, no notifications.
"""

from __future__ import annotations

from app.relevance.evaluator import DeterministicRelevanceEvaluator
from app.relevance.materialization import (
    MomentMaterializationResult,
    materialize_moment,
    query_moment_receipts,
)
from app.relevance.now_surface import collect_now_moments
from app.relevance.schema import Moment

__all__ = [
    "DeterministicRelevanceEvaluator",
    "Moment",
    "MomentMaterializationResult",
    "collect_now_moments",
    "materialize_moment",
    "query_moment_receipts",
]
