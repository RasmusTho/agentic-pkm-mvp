"""Retrieval — scope/policy eligibility PREFILTER before ranking, then full RetrievalResult semantics.

``retrieve(query, active_scope_id)`` (1) loads candidates from the fixture corpus, (2) **prefilters**
to the scope/policy-eligible set *before* any ranking, (3) ranks the eligible set by a trivial lexical
score, and (4) returns a RetrievalResult whose candidates each carry a metadata bundle, an
``admissibility_status`` from the surfaceable set, and an ``evidence_role_in_context`` that is ordinally
``<=`` the intrinsic role (never upgraded toward ``evidence``). Out-of-scope/suppressed material is
excluded before ranking and never reintroduced; relevant-but-excluded material is recorded in a
**content-free** ``denied_or_escalated_candidates`` list (a closed ``scope_denial`` shape) so a denial
is never silently dropped and never leaks object/scope identity, content, or provenance.

Retrieval produces *candidate evidence*, not truth: a top-ranked candidate is neither authority nor
admitted evidence. Candidate identity lives only in the embedded metadata bundle (single source of
truth — no sibling object_id). The emitted result validates against
``schemas/retrieval-result.schema.json``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from yggdrasil_runtime import corpus

_WORD = re.compile(r"[a-z0-9]+")
_EMPTY_SIGNALS: Mapping[str, Any] = MappingProxyType({})

# Conservative -> permissive ordering of evidence roles (semantic-dimensions.md).
_EVIDENCE_ORDER = ["non_evidence", "inspiration", "analogy", "reference", "background", "evidence"]

# Defaults for the WSP-supplied context the fixed retrieve() signature does not carry.
_DEFAULT_WORKSPACE_ID = "workspace:default"
_DEFAULT_PRINCIPAL_ID = "principal:system"


def _clamp_in_context(intrinsic: str, proposed: str | None = None) -> str:
    """Return an in-context evidence role that never exceeds the intrinsic role (non-upgrading).

    Defaults to the intrinsic role; if a proposed downgrade is given it is honored only when it is
    ordinally lower-or-equal. Retrieval may downgrade an evidence role for the current context but
    must never upgrade it toward ``evidence``.
    """
    if proposed is None:
        return intrinsic
    return proposed if _EVIDENCE_ORDER.index(proposed) <= _EVIDENCE_ORDER.index(intrinsic) else intrinsic


@dataclass(frozen=True)
class ScopeDenial:
    """An audit-safe, content-free record that some relevant material was denied/escalated.

    Records WHY and WHAT CLASS of flow would be needed, WITHOUT identifying the denied content,
    scope, object, or provenance (revealing that a specific scope/object exists is itself a
    cross-boundary disclosure).
    """

    reason: str
    denial_class: str
    escalation_recommended: bool = False
    required_flow_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "reason": self.reason,
            "denial_class": self.denial_class,
            "escalation_recommended": self.escalation_recommended,
        }
        if self.required_flow_class is not None:
            out["required_flow_class"] = self.required_flow_class
        return out


@dataclass(frozen=True)
class Candidate:
    """A surfaceable retrieval candidate. Identity lives only in its metadata bundle."""

    metadata_bundle: Any
    admissibility_status: str
    evidence_role_in_context: str
    ranking_signals: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_SIGNALS)

    def to_dict(self) -> dict[str, Any]:
        # Identity comes only from the embedded bundle — no sibling object_id at the candidate level.
        return {
            "metadata_bundle": self.metadata_bundle.to_dict(),
            "admissibility_status": self.admissibility_status,
            "evidence_role_in_context": self.evidence_role_in_context,
            "ranking_signals": dict(self.ranking_signals),
        }


@dataclass(frozen=True)
class RetrievalResult:
    candidate_items: tuple[Candidate, ...]
    scope_policy_prefiltered: bool
    active_scope_id: str
    query: str
    denied_or_escalated_candidates: tuple[ScopeDenial, ...] = ()
    active_workspace_id: str = _DEFAULT_WORKSPACE_ID
    principal_id: str = _DEFAULT_PRINCIPAL_ID
    retrieval_id: str = ""
    query_id: str = ""
    trace_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Schema-conformant dict (validates against schemas/retrieval-result.schema.json)."""
        return {
            "retrieval_id": self.retrieval_id,
            "query_id": self.query_id,
            "active_scope_id": self.active_scope_id,
            "active_workspace_id": self.active_workspace_id,
            "principal_id": self.principal_id,
            "scope_policy_prefiltered": self.scope_policy_prefiltered,
            "candidate_items": [c.to_dict() for c in self.candidate_items],
            "applicable_cross_scope_flows": [],
            "denied_or_escalated_candidates": [d.to_dict() for d in self.denied_or_escalated_candidates],
            "trace_id": self.trace_id,
            "created_at": self.created_at,
        }


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


def _denials_for_excluded(query: str, active_scope_id: str) -> tuple[ScopeDenial, ...]:
    """Content-free denial records for relevant material that was excluded by the prefilter.

    Aggregated by denial class so the result records that material WAS withheld (never a silent drop)
    without leaking object/scope identity, content, provenance, or even a per-document count.
    """
    out_of_scope_relevant = False
    suppressed_relevant = False
    for doc in corpus.load_corpus():
        bundle = doc.metadata_bundle
        if _lexical_score(query, doc.text) <= 0:
            continue
        if bundle.scope_id != active_scope_id:
            out_of_scope_relevant = True
        elif bundle.suppression_state != "visible":
            suppressed_relevant = True
    denials: list[ScopeDenial] = []
    if out_of_scope_relevant:
        denials.append(
            ScopeDenial(
                reason="relevant material in other scopes was excluded; no CrossScopeFlow admits it",
                denial_class="cross_scope_no_flow",
                escalation_recommended=False,
                required_flow_class="other-scope -> active-scope, governed flow required",
            )
        )
    if suppressed_relevant:
        denials.append(
            ScopeDenial(
                reason="relevant in-scope material is suppressed/withheld",
                denial_class="suppressed",
                escalation_recommended=False,
            )
        )
    return tuple(denials)


def retrieve(
    query: str,
    active_scope_id: str,
    *,
    active_workspace_id: str = _DEFAULT_WORKSPACE_ID,
    principal_id: str = _DEFAULT_PRINCIPAL_ID,
) -> RetrievalResult:
    """Retrieve candidate context for ``query`` within ``active_scope_id`` (prefilter before rank)."""
    # 1) PREFILTER before ranking — eligibility decides membership, not similarity.
    eligible = eligible_candidates(query, active_scope_id)
    # 2) RANK only the eligible set (trivial lexical similarity; signals never confer permission).
    ranked = sorted(eligible, key=lambda d: _lexical_score(query, d.text), reverse=True)
    # 3) Package candidates; evidence_role_in_context clamped so it never exceeds the intrinsic role.
    candidates = tuple(
        Candidate(
            metadata_bundle=d.metadata_bundle,
            admissibility_status="admitted",
            evidence_role_in_context=_clamp_in_context(d.metadata_bundle.evidence_role),
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
        denied_or_escalated_candidates=_denials_for_excluded(query, active_scope_id),
        active_workspace_id=active_workspace_id,
        principal_id=principal_id,
        retrieval_id=f"retrieval:{uuid4().hex[:12]}",
        query_id=f"query:{uuid4().hex[:12]}",
        trace_id=f"trace:{uuid4().hex[:12]}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
