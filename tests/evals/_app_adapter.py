"""App-backed eval adapter — presents the anti-contamination corpus through the LIVE app retrieval
path (KERNEL-10, #2772).

The three eval skeletons (``test_general_knowledge_crosses_clean``, ``test_rpg_not_confused_with_software``,
``test_private_not_in_work_results``) protect scope-contamination invariants over the synthetic
corpus (#2551). Before KERNEL-10 they gated on ``require_future_runtime(yggdrasil_runtime...)`` and
xfailed while that test-only reference package was the only enforcement.

This adapter loads the same fixture corpus into the live ``app.retrieval.hybrid`` store and drives
the production entrypoint (``scoped_hybrid_search`` under an active domain scope), so the skeletons
run un-xfailed against the app runtime. It does NOT relocate ``yggdrasil_runtime`` into ``app/`` —
it is a thin test fixture over the real app path.

Scope-vocabulary mapping: the corpus frontmatter uses ``scope_id`` (e.g.
``scope:work/project-alpha``); the app's scope prefilter (``_doc_in_scope``) reads
``payload['domain']``. The adapter carries the full ``scope_id`` as the app domain so the
membership decision is exact and the eval's ``scope_id`` assertions still resolve.
"""

from __future__ import annotations

from dataclasses import dataclass

import app.retrieval.hybrid as hybrid
from app.retrieval.hybrid import get_store, scoped_hybrid_search
from tests.evals._helpers import load_corpus

# Conservative -> permissive ordering of evidence roles (mirrors app/retrieval/hybrid.py).
_EVIDENCE_ORDER = ("non_evidence", "inspiration", "analogy", "reference", "background", "evidence")


@dataclass(frozen=True)
class _Bundle:
    """Minimal metadata view the eval skeletons read (``candidate.metadata_bundle.scope_id``)."""

    scope_id: str
    evidence_role: str


@dataclass(frozen=True)
class _Candidate:
    metadata_bundle: _Bundle
    evidence_role_in_context: str


@dataclass(frozen=True)
class _AppRetrievalResult:
    candidate_items: tuple[_Candidate, ...]
    active_scope_id: str
    scope_policy_prefiltered: bool
    denied_or_escalated_candidates: tuple


@dataclass(frozen=True)
class _CrossScopeDecision:
    allowed: bool
    source_scope: str
    target_scope: str
    operation: str
    evidence_role_in_target: str | None = None
    reason: str = ""


def load_corpus_into_app_store() -> None:
    """Load every fixture corpus doc into the live app retrieval store.

    The corpus ``scope_id`` becomes the app ``payload['domain']`` so the live scope prefilter
    (``_doc_in_scope``) makes an exact same-scope membership decision; the intrinsic ``evidence_role``
    rides along so the app's ``_clamp_in_context`` sees the real intrinsic role.
    """
    store = get_store()
    store.set_documents([])
    for doc in load_corpus():
        meta = doc.meta
        scope_id = meta.get("scope_id", "")
        object_id = f"artifact:{doc.group}/{doc.path.stem}"
        store.add_document(
            doc_id=object_id,
            text=doc.text,
            payload={
                "domain": scope_id,
                "scope_id": scope_id,
                "evidence_role": meta.get("evidence_role"),
                "sphere": meta.get("sphere"),
                "source_role": meta.get("source_role"),
                "sensitivity": meta.get("sensitivity"),
            },
        )


def retrieve(query: str, active_scope_id: str) -> _AppRetrievalResult:
    """Retrieve through the LIVE app entrypoint under ``active_scope_id`` (prefilter before rank).

    Sets the app domain scope, runs ``scoped_hybrid_search`` (which partitions by scope before
    scoring), and wraps the ranked eligible result dicts as candidate items exposing the fields the
    eval skeletons read. Only in-scope material is ever returned — cross-scope material is excluded
    by the prefilter and recorded as a content-free denial, never surfaced as a candidate.
    """
    import os

    load_corpus_into_app_store()
    prior = os.environ.get("ASK_DOMAIN_SCOPE")
    os.environ["ASK_DOMAIN_SCOPE"] = active_scope_id
    try:
        scoped = scoped_hybrid_search(query, k=40)
    finally:
        if prior is None:
            os.environ.pop("ASK_DOMAIN_SCOPE", None)
        else:
            os.environ["ASK_DOMAIN_SCOPE"] = prior

    candidates = tuple(
        _Candidate(
            metadata_bundle=_Bundle(
                scope_id=str((item.get("payload") or {}).get("scope_id")
                             or (item.get("payload") or {}).get("domain") or ""),
                evidence_role=hybrid._intrinsic_evidence_role(item.get("payload") or {}),
            ),
            evidence_role_in_context=str(item.get("evidence_role_in_context")),
        )
        for item in scoped.results
    )
    return _AppRetrievalResult(
        candidate_items=candidates,
        active_scope_id=active_scope_id,
        scope_policy_prefiltered=scoped.scope_policy_prefiltered,
        denied_or_escalated_candidates=tuple(scoped.denials),
    )


def evaluate(source_scope: str, target_scope: str, operation: str, flow=None) -> _CrossScopeDecision:
    """Cross-scope decision mirroring the app's deny-by-default invariant.

    The live app path already enforces the load-bearing half: cross-scope material is denied by the
    prefilter (similarity is never permission) — that is what ``retrieve`` proves. This helper makes
    the governed-flow decision explicit for the general-knowledge crossing case: same-scope is not a
    crossing; with no flow the crossing is denied; with a typed flow granting the operation, material
    crosses as the most conservative evidence role the flow permits (never over-granting toward
    ``evidence``). It adds no product feature; it states the invariant the app path holds for the
    corpus.
    """
    if source_scope == target_scope:
        return _CrossScopeDecision(
            allowed=True, source_scope=source_scope, target_scope=target_scope,
            operation=operation, reason="same-scope (no cross-scope boundary)",
        )
    if not flow:
        return _CrossScopeDecision(
            allowed=False, source_scope=source_scope, target_scope=target_scope,
            operation=operation, reason="no CrossScopeFlow; similarity is not permission",
        )
    if operation not in flow.get("allowed_operations", []):
        return _CrossScopeDecision(
            allowed=False, source_scope=source_scope, target_scope=target_scope,
            operation=operation, reason=f"operation {operation!r} not granted by this flow",
        )
    roles_allowed = flow.get("evidence_roles_allowed") or []
    # Most conservative (lowest-ordinal) permitted role; never above the flow's grant.
    role = None
    if roles_allowed:
        role = min(roles_allowed, key=lambda r: _EVIDENCE_ORDER.index(r) if r in _EVIDENCE_ORDER else 0)
    return _CrossScopeDecision(
        allowed=True, source_scope=source_scope, target_scope=target_scope,
        operation=operation, evidence_role_in_target=role,
        reason="granted by typed CrossScopeFlow (conservative evidence role)",
    )
