from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, List, Optional

from langgraph.graph import END, START, StateGraph

from app.activation.ask_synthesis import (
    emit_ask_synthesis_receipt,
    evaluate_ask_synthesis,
)
from app.retrieval.envelope import assemble_and_validate_ask_envelope
from app.retrieval.hybrid import ScopeDenial, ScopedRetrieval, _resolve_domain_scope
from app.agent_memory.recall_activation import activate_guarded_recall
from app.agent_memory.recall_explanation import (
    ActivationReason,
    RecallUseRight,
    render_recall_footer,
)
from app.agent_memory.recall_retrieval import RecallCandidate, retrieve_relevant_promoted
from app.agent_memory.provisional_recall import (
    activate_provisional_recall,
    retrieve_relevant_provisional,
)
from app.agent_memory.provisional_write import ProvisionalReceiptStore
from app.activation.gate import ConsumingAuthority
from app.agent_memory.ask_provenance_manifest import (
    AuthorizationSnapshot,
    schedule_ask_provenance_capture,
    shadow_capture_enabled,
)
from app.agents.ask.state import AgentState, RetrievedHit
from app.agents.ask.utils import build_ask_context, get_ask_settings, llm_answer, score_hit
from app.config.environment import active_environment
from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.components.rerankers import get_reranker
from app.retrieval.capability import RetrievalRequest, retrieve
from app.vault.manager import get_vault_manager

logger = logging.getLogger(__name__)

TOP_K_INITIAL = 40
RECALL_TOP_K = 3
DEFAULT_RECALL_RECEIPTS_PATH = Path("runtime/agent_memory/recall_receipts.jsonl")
DEFAULT_PROVISIONAL_RECALL_RECEIPTS_PATH = Path(
    "runtime/agent_memory/provisional_recall_receipts.jsonl"
)
_ASK_LAST_ACTIVE_LOADED_ATTR = "_ask_recall_last_active_loaded"


def _to_retrieved_hit(hit: dict[str, Any], ask_score: float | None = None) -> RetrievedHit:
    payload = hit.get("payload") or {}
    return RetrievedHit(
        object_id=str(hit.get("id") or hit.get("doc_id") or payload.get("uuid") or ""),
        score=float(hit.get("score") or 0.0),
        ask_score=ask_score,
        origin=payload.get("origin") or None,
        zone=None,  # Zone is derived, not read from stored payload
        trust=payload.get("trust") or None,
        title=payload.get("title") or hit.get("title"),
        path=hit.get("source_ref") or payload.get("source_ref"),
        snippet=hit.get("snippet") or hit.get("text"),
        # Carry the full note body for LLM grounding (build_ask_context bounds it
        # by max_context_chars). Without this the synthesis context only ever
        # sees the short display snippet.
        text=hit.get("text") or payload.get("text") or payload.get("raw_text"),
        payload=payload,
        evidence_role_in_context=hit.get("evidence_role_in_context"),
    )


def _retrieve_node(state: AgentState, *, k: int, ask_settings) -> AgentState:
    response = retrieve(RetrievalRequest(query=state.query, k=k, trace_id=state.trace_id))
    enriched: list[RetrievedHit] = []
    for retrieval_hit in response.hits:
        hit = retrieval_hit.to_hybrid_dict()
        ask_score = score_hit(hit)
        enriched.append(_to_retrieved_hit(hit, ask_score=ask_score))
    state.hits = enriched
    state.retrieval_metadata = dict(getattr(response, "metadata", {}) or {})
    # Content-free scope denials ride the state separately from hits (KERNEL-10): they are
    # scope-level, so later rerank/truncation of hits must never drop them. getattr keeps
    # compatibility with test fakes that return a hits-only response.
    state.denials = [d.to_dict() for d in (getattr(response, "denials", ()) or ())]
    return state


def _rerank_node(state: AgentState, *, ask_settings) -> AgentState:
    if not state.hits:
        return state
    reranker = get_reranker()
    # Order by ask_score first (if present); otherwise use reranker
    sorted_hits = sorted(
        state.hits, key=lambda h: h.ask_score if h.ask_score is not None else 0.0, reverse=True
    )

    class _RRItem:
        def __init__(self, id: str, text: str):
            self.id = id
            self.text = text

    if reranker:
        rr_items = [
            _RRItem(
                h.object_id,
                h.snippet or h.payload.get("text") or h.payload.get("raw_text") or "",
            )
            for h in sorted_hits
        ]
        try:
            results = reranker.rerank(state.query, rr_items, top_k=None)  # type: ignore[arg-type]
            order = {res.id: idx for idx, res in enumerate(results)}
            sorted_hits = sorted(sorted_hits, key=lambda h: order.get(h.object_id, len(order)))
        except Exception:
            pass

    top_k_llm = max(1, int(ask_settings.max_context_docs or 10))
    state.hits = sorted_hits[:top_k_llm]
    return state


def _recall_receipt_path() -> Path:
    configured = os.getenv("RECALL_RECEIPTS_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_RECALL_RECEIPTS_PATH


def _provisional_recall_receipt_path() -> Path:
    configured = os.getenv("PROVISIONAL_RECALL_RECEIPTS_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_PROVISIONAL_RECALL_RECEIPTS_PATH


def _active_recall_vault_root() -> Path | None:
    manager = get_vault_manager()
    context = manager.context
    try:
        env_root = resolve_optional_vault_root(environment=active_environment())
    except VaultRootMisconfiguredError:
        env_root = None
    if (
        context.status == "selected"
        and context.active_vault_path
        and env_root is not None
        and getattr(manager, _ASK_LAST_ACTIVE_LOADED_ATTR, False)
    ):
        return env_root.expanduser().resolve()
    if context.status == "selected" and context.active_vault_path:
        return Path(context.active_vault_path).expanduser().resolve()
    if env_root is not None:
        return env_root.expanduser().resolve()
    # After an API restart the manager boots with an empty no-vault context;
    # the persisted last-active vault is only materialized on demand. Lazily
    # load it only when no explicit channel vault binding is present.
    context = manager.load_last_active()
    setattr(manager, _ASK_LAST_ACTIVE_LOADED_ATTR, context.status == "selected")
    if context.status == "selected" and context.active_vault_path:
        return Path(context.active_vault_path).expanduser().resolve()
    return None


def _source_artifact_path(candidate: RecallCandidate, vault_root: Path | None) -> Path | None:
    if not candidate.artifact_path:
        return None
    if not vault_root:
        return None
    return vault_root / candidate.artifact_path


def _recall_node(state: AgentState, *, ask_settings) -> AgentState:
    vault_root = _active_recall_vault_root()
    candidates = retrieve_relevant_promoted(state.query, k=RECALL_TOP_K, vault_root=vault_root)
    active_scope = _resolve_domain_scope()
    provisional = (
        retrieve_relevant_provisional(
            state.query,
            k=RECALL_TOP_K,
            vault_root=vault_root,
            receipt_store=ProvisionalReceiptStore(),
            active_scope_id=active_scope,
        )
        if vault_root is not None and active_scope is not None
        else None
    )
    if not candidates and (provisional is None or not provisional.candidates):
        state.recalled = []
        state.recalled_content = {}
        state.recalled_context_items = []
        return state

    recalled = []
    recalled_content: dict[str, str] = {}
    recalled_context_items: list[dict[str, Any]] = []
    reasoning = list(state.reasoning or [])
    receipt_path = _recall_receipt_path()
    for candidate in candidates:
        guarded = activate_guarded_recall(
            candidate.promoted,
            use_right=RecallUseRight.ACTIVATABLE,
            activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
            why_now=candidate.reason,
            receipt_path=receipt_path,
            source_artifact_path=_source_artifact_path(candidate, vault_root),
        )
        if guarded.may_answer:
            recalled.append(guarded.explanation)
            content = (candidate.promoted.candidate.content or "").strip()
            if content:
                recalled_content[guarded.explanation.artifact_id] = content
            reasoning.append(
                f"recall:{guarded.memory_id}:{guarded.explanation.title}:{candidate.reason}"
            )

    for candidate in provisional.candidates if provisional is not None else ():
        guarded = activate_provisional_recall(
            candidate,
            consuming_authority=ConsumingAuthority.READ_ONLY,
            active_scope_id=active_scope or "",
            use_right=RecallUseRight.ACTIVATABLE,
            activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
            receipt_path=_provisional_recall_receipt_path(),
        )
        if guarded.may_answer and guarded.explanation is not None:
            recalled.append(guarded.explanation)
            recalled_content[guarded.explanation.artifact_id] = candidate.record.content
            reasoning.append(
                f"provisional_recall:{guarded.memory_id}:{candidate.reason_code}"
            )
            record = candidate.record
            recalled_context_items.append(
                {
                    "id": record.artifact_ref,
                    "doc_id": record.artifact_ref,
                    "_admitted_provisional_memory": True,
                    "payload": {
                        "uuid": record.artifact_ref,
                        "object_type": "memory_item",
                        "scope_id": record.scope_id,
                        "principal_id": record.principal_id,
                        "source_role": record.source_role,
                        "authority_state": record.authority_state,
                        "evidence_role": record.evidence_role.value,
                        "sensitivity": record.sensitivity.value,
                        "created_by": record.created_by,
                        "created_at": record.created_at.isoformat(),
                        "provenance_event_ids": list(record.provenance_event_ids),
                        "memory_state": record.review_state.value,
                    },
                    "evidence_role_in_context": record.evidence_role.value,
                }
            )

    state.recalled = recalled
    state.recalled_content = recalled_content
    state.recalled_context_items = recalled_context_items
    if reasoning:
        state.reasoning = reasoning
    return state


def _recall_only_fallback(state: AgentState) -> str:
    """Compose a minimal non-reasoning answer from recalled memory alone.

    Recalled memory stays supporting input only — this surfaces the recalled
    fact without claiming retrieval authority. Used when retrieval returned
    zero hits but guarded recall yielded a usable may_answer memory and
    reasoning is disabled.

    Prefer the recalled memory body (the actual fact); fall back to the title
    and, only if no content is available, the recall match reason.
    """
    top = state.recalled[0]
    title = (top.title or "").strip()
    content = (state.recalled_content.get(top.artifact_id) or "").strip()
    if content:
        return f"{title}: {content}" if title else content
    why = (top.why_now or "").strip()
    if title and why:
        return f"{title}: {why}"
    return title or why


def _hits_as_scoped_retrieval(state: AgentState) -> ScopedRetrieval:
    """Project the reranked retrieval hits back into a :class:`ScopedRetrieval`.

    The hits already passed the scope prefilter in ``hybrid_search`` (eligibility decided membership
    before ranking); this repackages them as the structured value the envelope assembler consumes.
    Denials are not re-derived here (the retrieval entrypoint owns them); the seam's contract is that
    the consumer receives a bounded envelope, never raw index rows.
    """
    results: list[dict[str, Any]] = []
    for hit in state.hits:
        if not hit.object_id:
            continue
        results.append(
            {
                "id": hit.object_id,
                "doc_id": hit.object_id,
                "text": hit.text or hit.snippet or "",
                "score": hit.score,
                "snippet": hit.snippet,
                "source_ref": hit.path,
                "payload": dict(hit.payload or {}),
                "evidence_role_in_context": hit.evidence_role_in_context,
            }
        )
    results.extend(dict(item) for item in (state.recalled_context_items or []))
    # Rehydrate the content-free denials captured at retrieval time (state carries them as plain
    # dicts). They are scope-level: hit reranking/truncation between retrieve and here must not —
    # and does not — affect them.
    denial_fields = {"reason", "denial_class", "escalation_recommended", "required_flow_class"}
    denials = tuple(
        ScopeDenial(**{k: v for k, v in d.items() if k in denial_fields})
        for d in (state.denials or [])
        if isinstance(d, dict) and d.get("reason") and d.get("denial_class")
    )
    return ScopedRetrieval(results=results, denials=denials, active_scope=_resolve_domain_scope())


def _envelope_source_ids(envelope: dict[str, Any]) -> list[str]:
    """Ordered ``object_id``s of the envelope's retrieved items (single source of identity).

    The envelope's embedded metadata bundles are the only identity source the gate consumes; the
    consumer never touches raw index rows. Order is preserved so grounded-source linkage on the ASK
    response matches retrieval order.
    """
    ids: list[str] = []
    for item in envelope.get("retrieved_items", []):
        bundle = item.get("metadata_bundle") or {}
        object_id = str(bundle.get("object_id") or "").strip()
        if object_id:
            ids.append(object_id)
    return ids


def build_ask_envelope(state: AgentState) -> dict[str, Any]:
    """Assemble and validate the bounded ContextEnvelope the ASK synthesis seam consumes (KERNEL-10).

    This is the production seam: ``app.api.routes.ask`` -> ASK graph -> here. The consumer of the
    retrieval context is handed a schema-valid ContextEnvelope (no raw vault/index access), never the
    raw ranked dicts. ``active_scope_id`` is the active domain scope or an explicit ``unscoped``
    token (an id_string is required and must be non-empty).
    """
    scoped = _hits_as_scoped_retrieval(state)
    active_scope = scoped.active_scope or "scope:unscoped"
    return assemble_and_validate_ask_envelope(
        scoped,
        active_workspace_id="workspace:ask",
        active_scope_id=active_scope,
        principal_id="principal:ask",
        user_intent=state.query or "ask",
    )


def _synthesis_source_paths(state: AgentState) -> dict[str, str]:
    paths: dict[str, str] = {}
    for hit in state.hits:
        if hit.object_id and hit.path:
            paths[hit.object_id] = str(hit.path)
    return paths


def _capture_provenance_shadow(
    state: AgentState,
    *,
    envelope: dict[str, Any],
    admitted_source_ids: Iterable[str],
) -> None:
    """Best-effort post-answer capture with no return path into ASK."""

    if not shadow_capture_enabled() or state.answer is None:
        return
    hits = {hit.object_id: hit for hit in state.hits}
    evidence: list[dict[str, Any]] = []
    for source_id in admitted_source_ids:
        hit = hits.get(source_id)
        provenance = hit.payload.get("provenance") if hit else None
        canonical_source_hash = (
            provenance.get("content_hash")
            if isinstance(provenance, dict)
            and provenance.get("chunk_policy_version")
            and provenance.get("pipeline_version")
            else None
        )
        evidence.append(
            {
                "source_id": source_id,
                "canonical_source_hash": canonical_source_hash,
            }
        )
    policy = {
        "citation_policy": envelope.get("citation_policy") or {},
        "mutation_policy": envelope.get("mutation_policy") or {},
        "execution_policy": envelope.get("execution_policy") or {},
    }
    authorization_context = {
        "access_mode": envelope.get("access_mode"),
        "allowed_capabilities": envelope.get("allowed_capabilities") or [],
    }
    schedule_ask_provenance_capture(
        answer=state.answer,
        query=state.query,
        evidence=evidence,
        authorization=AuthorizationSnapshot(
            scope_id=str(envelope.get("active_scope_id") or "scope:unscoped"),
            # The current ASK route has no authenticated caller principal seam.
            # Record that identity unavailable rather than hashing its historical
            # placeholder ("principal:ask") as if it were authorization truth.
            principal_id=None,
            authorization_context=authorization_context,
            policy=policy,
            authorized_source_ids=tuple(admitted_source_ids),
        ),
        retrieval_identity=state.retrieval_metadata.get("canonical_index_identity"),
        synthesis_identity=state.llm_route,
    )


def _answer_node(state: AgentState, *, ask_settings) -> AgentState:
    if not state.hits and not state.recalled:
        # Preserve the fallback only when neither retrieval nor recall produced context.
        state.answer = "No results found."
        return state

    if state.hits:
        # Default answer: snippet/text of top hit
        top = state.hits[0]
        fallback = (
            top.snippet or top.payload.get("text") or top.payload.get("raw_text") or ""
        ).strip()
    else:
        # Recall-only path: retrieval was empty but guarded recall found supporting memory.
        fallback = _recall_only_fallback(state)
    answer_text = fallback or "No results found."

    # Expansion Activation Gate (#2026): ASK answer synthesis is now activated
    # THROUGH the deterministic admissibility gate (#2025) over the retrieved
    # context, not the raw REASONING_ENABLE env flag. When the gate admits, run
    # the existing run_reasoning(ASK_ANSWER) generation path and emit a
    # provenance-bearing activation receipt. When it blocks (or generation
    # yields nothing), preserve the existing literal-snippet fallback.
    #
    # KERNEL-10: the retrieval context reaches the gate as a bounded, schema-valid
    # ContextEnvelope (no raw index rows). The gate's source ids come from the
    # envelope's embedded metadata bundles (its single source of identity), with
    # recalled memory ids appended as before. `evaluate_ask_synthesis` stays the
    # gate seam so the deterministic admissibility decision is unchanged.
    envelope = build_ask_envelope(state)
    source_ids = _envelope_source_ids(envelope)
    for recalled in state.recalled or []:
        if recalled.artifact_id and recalled.artifact_id not in source_ids:
            source_ids.append(recalled.artifact_id)
    decision = evaluate_ask_synthesis(source_ids)
    if decision.activatable:
        context = build_ask_context(
            state.query,
            [h.model_dump() for h in state.hits],
            ask_settings,
            recalled=state.recalled,
            recalled_content=state.recalled_content,
        )
        llm, route = llm_answer(state.query, context, ask_settings)
        if route:
            state.llm_route = route
        if llm:
            answer_text = llm
            receipt_id = emit_ask_synthesis_receipt(
                decision,
                answer_preview=llm,
                source_paths=_synthesis_source_paths(state),
                llm_route=route,
            )
            state.synthesis_receipt_id = receipt_id
            state.synthesis_source_ids = list(decision.admitted_artifact_ids)
        else:
            # Gate admitted but generation produced no answer: fall back to the
            # literal snippet with a logged reason. No receipt for a non-synthesis.
            logger.info(
                "ask.synthesis: gate admitted but generation returned no answer; "
                "falling back to literal snippet (capability=%s, admitted=%d)",
                decision.capability_id,
                len(decision.admitted_artifact_ids),
            )
    else:
        logger.info(
            "ask.synthesis: gate blocked synthesis; serving literal snippet "
            "(capability=%s, reasons=%s)",
            decision.capability_id,
            ",".join(decision.blocked_reasons) or "none",
        )

    # Treatment A (#1972): when recall fired, attribute it with a footer keyed to
    # the recall receipt — outside the answer prose, never shown when recall is empty.
    footer = render_recall_footer(state.recalled or [])
    state.answer = f"{answer_text}\n\n{footer}" if footer else answer_text
    _capture_provenance_shadow(
        state,
        envelope=envelope,
        admitted_source_ids=decision.admitted_artifact_ids,
    )
    return state


def build_ask_graph(ask_settings=None):
    ask_settings = ask_settings or get_ask_settings()
    graph = StateGraph(AgentState)
    graph.add_node(
        "retrieve", lambda s: _retrieve_node(s, k=TOP_K_INITIAL, ask_settings=ask_settings)
    )
    graph.add_node("rerank", lambda s: _rerank_node(s, ask_settings=ask_settings))
    graph.add_node("recall", lambda s: _recall_node(s, ask_settings=ask_settings))
    graph.add_node("answer", lambda s: _answer_node(s, ask_settings=ask_settings))

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "recall")
    graph.add_edge("recall", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


def run_ask_graph(query: str, trace_id: Optional[str] = None, ask_settings=None) -> AgentState:
    ask_settings = ask_settings or get_ask_settings()
    compiled = build_ask_graph(ask_settings)
    initial = AgentState(trace_id=trace_id, query=query, hits=[])
    result = compiled.invoke(initial)
    if isinstance(result, AgentState):
        return result
    try:
        return AgentState.model_validate(result)
    except Exception:
        # Best-effort fallback if graph returned a plain dict
        return AgentState(trace_id=trace_id, query=query, hits=[], answer=None)


__all__ = ["run_ask_graph", "build_ask_graph", "TOP_K_INITIAL"]
