from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.retrieval.hybrid import hybrid_search

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


def retrieve(request: RetrievalRequest) -> RetrievalResponse:
    raw_hits = hybrid_search(
        request.query,
        k=request.k,
        language=request.language,
        query_vector=request.query_vector,
    )
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
    return RetrievalResponse(
        query=request.query,
        hits=[RetrievalHit.from_hybrid(hit) for hit in raw_hits],
        trace_id=request.trace_id,
        metadata=metadata,
        diagnostics=diagnostics,
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
