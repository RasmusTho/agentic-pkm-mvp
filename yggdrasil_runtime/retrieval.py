"""Retrieval — scope/policy eligibility PREFILTER before ranking. Similarity is not permission.

``retrieve(query, active_scope_id)`` (1) loads candidates from the fixture corpus, (2) **prefilters**
to the scope/policy-eligible set *before* any ranking, (3) ranks the eligible set by a trivial lexical
score, and (4) returns candidates each carrying a metadata bundle, an admissibility status, and a
NON-UPGRADING ``evidence_role_in_context`` (default = intrinsic). Out-of-scope/suppressed material is
excluded before ranking; ranking never reintroduces it.

Module import-gate: creating this module auto-enables every retrieval-backed skeleton, including the
nominally-#2583 monotonicity and RPG tests. The non-upgrading ``evidence_role_in_context`` and the
in-scope-only candidate set keep those green here; #2583 enriches (explicit downgrades, content-free
denied list, full RetrievalResult schema conformance) without widening the eligible set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from yggdrasil_runtime import corpus

_WORD = re.compile(r"[a-z0-9]+")
_EMPTY_SIGNALS: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class Candidate:
    """A surfaceable retrieval candidate. Identity lives only in its metadata bundle."""

    metadata_bundle: Any
    admissibility_status: str
    evidence_role_in_context: str
    ranking_signals: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_SIGNALS)


@dataclass(frozen=True)
class RetrievalResult:
    candidate_items: tuple[Candidate, ...]
    scope_policy_prefiltered: bool
    active_scope_id: str
    query: str
    denied_or_escalated_candidates: tuple[Any, ...] = ()


def _terms(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _lexical_score(query: str, text: str) -> float:
    q = _terms(query)
    if not q:
        return 0.0
    return len(q & _terms(text)) / len(q)


def _is_eligible(doc: corpus.CorpusDoc, active_scope_id: str) -> bool:
    # Scope/policy eligibility: same active scope and not suppressed. Cross-scope inclusion is a
    # governed CrossScopeFlow decision (yggdrasil_runtime.cross_scope), never an automatic similarity
    # result — so it is intentionally NOT part of the default prefilter here.
    bundle = doc.metadata_bundle
    return bundle.scope_id == active_scope_id and bundle.suppression_state == "visible"


def eligible_candidates(query: str, active_scope_id: str) -> list[corpus.CorpusDoc]:
    """The scope/policy-eligible docs — computed BEFORE ranking. Exposed for the prefilter test."""
    return [d for d in corpus.load_corpus() if _is_eligible(d, active_scope_id)]


def retrieve(query: str, active_scope_id: str) -> RetrievalResult:
    """Retrieve candidate context for ``query`` within ``active_scope_id`` (prefilter before rank)."""
    # 1) PREFILTER before ranking — eligibility decides membership, not similarity.
    eligible = eligible_candidates(query, active_scope_id)
    # 2) RANK only the eligible set (trivial lexical similarity; signals never confer permission).
    ranked = sorted(eligible, key=lambda d: _lexical_score(query, d.text), reverse=True)
    # 3) Package candidates; evidence_role_in_context defaults to intrinsic (never upgraded).
    candidates = tuple(
        Candidate(
            metadata_bundle=d.metadata_bundle,
            admissibility_status="admitted",
            evidence_role_in_context=d.metadata_bundle.evidence_role,
            ranking_signals=MappingProxyType(
                {"similarity": _lexical_score(query, d.text), "method": "lexical"}
            ),
        )
        for d in ranked
    )
    return RetrievalResult(
        candidate_items=candidates,
        scope_policy_prefiltered=True,
        active_scope_id=active_scope_id,
        query=query,
    )
