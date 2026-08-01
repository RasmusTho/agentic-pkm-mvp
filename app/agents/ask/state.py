from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.agent_memory.recall_explanation import RecallExplanation
from app.agents.runtime_state import RuntimeStateModel


class RetrievedHit(BaseModel):
    object_id: str
    score: float
    ask_score: Optional[float] = None
    origin: Optional[str] = None
    zone: Optional[str] = None
    trust: Optional[str] = None
    title: Optional[str] = None
    path: Optional[str] = None
    # `snippet` is the short, keyword-centered window used for display (the API
    # sources list). `text` is the full note body carried for LLM grounding so
    # the answer context is not starved by the display window. Keep them
    # distinct: collapsing the two truncates synthesis input to ~300 chars.
    snippet: Optional[str] = None
    text: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    # In-context evidence role resolved by the retrieval prefilter (KERNEL-10), clamped so it never
    # exceeds the item's intrinsic role. Carried through to the ContextEnvelope assembled at the
    # ASK synthesis seam.
    evidence_role_in_context: Optional[str] = None


class AgentState(RuntimeStateModel):
    trace_id: Optional[str] = None
    query: str
    # The active scope bound for THIS ASK turn (#2921). Resolved ONCE at graph entry — from the
    # caller's request binding, falling back to the ambient `ASK_DOMAIN_SCOPE` process default —
    # and then reused by retrieval, recall, and envelope assembly. Resolving it once is what keeps
    # the scope the prefilter used and the envelope's `active_scope_id` from diverging mid-turn.
    active_scope: Optional[str] = None
    hits: List[RetrievedHit] = Field(default_factory=list)
    # Authoritative metadata observed on the retrieval response. Shadow
    # experiments may inspect it, but it never feeds ranking or answer text.
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)
    # Content-free scope denials from the retrieval prefilter (KERNEL-10), as plain dicts
    # (ScopeDenial.to_dict()) so they survive the langgraph state round-trip. Scope-level, not
    # per-hit: reranking/truncating hits must never drop them. Carried to the ContextEnvelope
    # assembled at the ASK synthesis seam (denied_scopes + escalation_conditions).
    denials: List[dict[str, Any]] = Field(default_factory=list)
    recalled: List[RecallExplanation] = Field(default_factory=list)
    # Recalled memory bodies keyed by artifact/memory id. Supporting input only,
    # used to compose a recall-only answer when retrieval returns no hits.
    recalled_content: dict[str, str] = Field(default_factory=dict)
    # Content-free metadata projections for admitted provisional memory. These
    # are composed into the bounded ContextEnvelope; claim text remains only in
    # ``recalled_content`` for the already-admitted synthesis context.
    recalled_context_items: List[dict[str, Any]] = Field(default_factory=list)
    # Proposal-only provisional memory is deliberately separated from answer
    # recall state. ASK answer fallback, synthesis, and envelope assembly must
    # never consume these fields; a governed proposal consumer must opt in to
    # them with the citation-bound authority decision already attached.
    proposal_recalled: List[RecallExplanation] = Field(default_factory=list)
    proposal_recalled_content: dict[str, str] = Field(default_factory=dict)
    proposal_context_items: List[dict[str, Any]] = Field(default_factory=list)
    answer: Optional[str] = None
    reasoning: Optional[List[str]] = None
    llm_route: dict[str, Any] | None = None
    # Expansion Activation Gate (#2026): receipt id for an admitted ASK answer
    # synthesis, plus the grounded sources the gate admitted into it. None/empty
    # when the gate blocked or synthesis did not run (literal-snippet fallback).
    synthesis_receipt_id: Optional[str] = None
    synthesis_source_ids: List[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}
