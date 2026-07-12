from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from app.retrieval.hybrid import ScopeDenial, scoped_hybrid_search

ViewFreshnessState = Literal["fresh", "stale", "partial", "unknown"]


@dataclass(frozen=True)
class RetrievalViewFreshness:
    state: ViewFreshnessState = "unknown"
    reason: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"state": self.state}
        if self.reason:
            payload["reason"] = self.reason
        if self.source:
            payload["source"] = self.source
        return payload


@dataclass(frozen=True)
class RetrievalSignalPayload:
    salience: dict[str, Any] = field(default_factory=dict)
    staleness: dict[str, Any] = field(default_factory=dict)
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.salience:
            payload["salience"] = dict(self.salience)
        if self.staleness:
            payload["staleness"] = dict(self.staleness)
        if self.source:
            payload["source"] = self.source
        return payload


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    k: int = 8
    language: str | None = None
    query_vector: list[float] | None = None
    scope: str | None = None
    domain: str | None = None
    trace_id: str | None = None
    relation_metadata: dict[str, Any] = field(default_factory=dict)
    provenance_metadata: dict[str, Any] = field(default_factory=dict)
    view_freshness: RetrievalViewFreshness | None = None
    include_signal_payload: bool = False
    signal_payload: RetrievalSignalPayload | None = None


@dataclass(frozen=True)
class RetrievalHit:
    object_id: str
    doc_id: str
    text: str
    score: float
    snippet: str | None
    source_ref: str | None
    payload: dict[str, Any]
    # ERE-06 (#3181): the closure-derived decay signal for THIS hit, computed fresh at retrieve()
    # time -- never persisted, never written back into `payload` (which stays whatever the durable
    # store actually holds; see app/episodes/closure_decay.py). Empty (default) when the hit
    # carries no episode binding or an open one.
    signal_payload: "RetrievalSignalPayload" = field(default_factory=lambda: RetrievalSignalPayload())

    @classmethod
    def from_hybrid(cls, hit: dict[str, Any]) -> "RetrievalHit":
        payload = dict(hit.get("payload") or {})
        doc_id = str(hit.get("doc_id") or hit.get("id") or payload.get("uuid") or "")
        return cls(
            object_id=str(hit.get("id") or doc_id),
            doc_id=doc_id,
            text=str(hit.get("text") or ""),
            score=float(hit.get("score") or 0.0),
            snippet=hit.get("snippet"),
            source_ref=hit.get("source_ref"),
            payload=payload,
        )

    def to_hybrid_dict(self) -> dict[str, Any]:
        return {
            "id": self.object_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "score": self.score,
            "snippet": self.snippet,
            "source_ref": self.source_ref,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class RetrievalResponse:
    query: str
    hits: list[RetrievalHit]
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    # Content-free scope denials from the prefilter (KERNEL-10): relevant-but-excluded material is
    # recorded, never silently dropped. Empty when no scope is active or nothing relevant was
    # excluded. Carried alongside hits so consumers (the ASK envelope seam) can surface them —
    # denials are scope-level, not per-hit, so downstream hit truncation must never drop them.
    denials: tuple[ScopeDenial, ...] = ()


def _apply_closure_decay(hits: list["RetrievalHit"]) -> list["RetrievalHit"]:
    """ERE-06 (#3181): derive (never persist) the closure-based salience drop for every hit, then
    re-sort the RETURNED set by the dampened score (ranking-only, AC4 -- this never changes
    `evidence_role_in_context`, `authority_state`, or scope).

    Lazily imported (avoids a retrieval -> episodes import at module load for callers that never
    touch episode-bound content) and batched: every hit's episode ids are collected into ONE
    closed-episode-id read instead of one query per hit. A hit set with no episode bindings at all
    (the common case today) short-circuits to zero DB round-trips.
    """
    from app.episodes.closure_decay import derive_closure_salience, read_closed_episode_ids, resolve_episode_ids

    all_ids: set[str] = set()
    for hit in hits:
        all_ids.update(resolve_episode_ids(hit.payload.get("episode_ref")))
    if not all_ids:
        return hits

    closed_ids = read_closed_episode_ids(all_ids)
    if not closed_ids:
        return hits

    dampened: list[RetrievalHit] = []
    for hit in hits:
        factor, salience = derive_closure_salience(hit.payload.get("episode_ref"), closed_ids)
        if salience:
            hit = replace(
                hit,
                score=hit.score * factor,
                signal_payload=RetrievalSignalPayload(salience=salience),
            )
        dampened.append(hit)
    # Stable, descending re-sort of the already-retrieved set only -- dampening can never pull in
    # a candidate excluded earlier by hybrid.py's own (undamped) top-k cut; it only reorders WITHIN
    # what was already returned (a documented v1 scope limit of enacting the decay at this call
    # site rather than inside hybrid.py's own fusion step).
    dampened.sort(key=lambda h: h.score, reverse=True)
    return dampened


def retrieve(request: RetrievalRequest) -> RetrievalResponse:
    scoped = scoped_hybrid_search(
        request.query,
        k=request.k,
        language=request.language,
        query_vector=request.query_vector,
    )
    raw_hits = scoped.results
    diagnostics: dict[str, Any] = {
        "query": request.query,
        "scope": request.scope,
        "domain": request.domain,
        "trace_id": request.trace_id,
    }
    if request.relation_metadata:
        diagnostics["relation_metadata"] = dict(request.relation_metadata)
    if request.provenance_metadata:
        diagnostics["provenance_metadata"] = dict(request.provenance_metadata)
    if request.view_freshness is not None:
        diagnostics["view_freshness"] = request.view_freshness.to_dict()
    if request.include_signal_payload and request.signal_payload is not None:
        diagnostics["signal_payload"] = request.signal_payload.to_dict()
    view_freshness_state = request.view_freshness.state if request.view_freshness is not None else "unknown"
    metadata: dict[str, Any] = {
        "provenance": {
            "capability": "retrieval",
            "adapter": "hybrid_search",
            "trace_id": request.trace_id,
            "request": {
                "scope": request.scope,
                "domain": request.domain,
            },
        },
        "temporal_validity": {
            "state": view_freshness_state,
            "is_fresh": view_freshness_state == "fresh",
            "is_stale": view_freshness_state == "stale",
            "is_partial": view_freshness_state == "partial",
            "is_unknown": view_freshness_state == "unknown",
        },
    }
    if request.provenance_metadata:
        metadata["provenance"]["hints"] = dict(request.provenance_metadata)
    hits = _apply_closure_decay([RetrievalHit.from_hybrid(hit) for hit in raw_hits])
    return RetrievalResponse(
        query=request.query,
        hits=hits,
        trace_id=request.trace_id,
        metadata=metadata,
        diagnostics=diagnostics,
        denials=tuple(scoped.denials),
    )


__all__ = [
    "RetrievalHit",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievalSignalPayload",
    "RetrievalViewFreshness",
    "ViewFreshnessState",
    "retrieve",
]
