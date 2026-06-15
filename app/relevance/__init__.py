"""Contextual Relevance Engine — runtime package.

Pull slice (CRE-03): compute moments from vault-native data, materialize them as
governed artifacts with receipts, and project them to the companion-UI glance
surface, pull-only. Proactive slice (CRE-04): the attention loop reaches out only
when a moment's urgency clears the current interruption threshold, never at the
zero-tolerance floor, and defers (not drops) when suppressed.
"""

from __future__ import annotations

from app.relevance.attention_loop import (
    AttentionLoop,
    ReachOutDecision,
    decide_reachout,
    query_reachout_receipts,
)
from app.relevance.evaluator import DeterministicRelevanceEvaluator
from app.relevance.interruptibility import InterruptibilityThreshold, threshold_for
from app.relevance.materialization import (
    MomentMaterializationResult,
    materialize_moment,
    query_moment_receipts,
)
from app.relevance.now_surface import collect_now_moments
from app.relevance.patterns import DeclaredPattern
from app.relevance.schema import Moment

__all__ = [
    "AttentionLoop",
    "DeclaredPattern",
    "DeterministicRelevanceEvaluator",
    "InterruptibilityThreshold",
    "Moment",
    "MomentMaterializationResult",
    "ReachOutDecision",
    "collect_now_moments",
    "decide_reachout",
    "materialize_moment",
    "query_moment_receipts",
    "query_reachout_receipts",
    "threshold_for",
]
