from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, List, Optional

import numpy as np
from rank_bm25 import BM25Okapi
try:
    from rapidfuzz import process
except ImportError:
    process = None

from app.components.retrieval import embed_docs, embed_query
from app.retrieval.hook_adapter import maybe_rerank
from app.retrieval.tuning import get_retrieval_tuning

_logger = logging.getLogger(__name__)

# Conservative -> permissive ordering of evidence roles (semantic-dimensions.md). Mirrors
# mimer_runtime/retrieval.py::_EVIDENCE_ORDER — the reference for the invariant SHAPE. The
# in-context role may only be downgraded from the intrinsic role, never upgraded toward `evidence`.
_EVIDENCE_ORDER = ("non_evidence", "inspiration", "analogy", "reference", "background", "evidence")

# Intrinsic default for vault-derived / index-projection material with no explicit evidence_role:
# retrieval produces candidate context, not authority (ADR-0039), so it defaults to `background`,
# never `evidence`. An item reaches in-context `evidence` ONLY when its payload explicitly carries
# intrinsic `evidence`.
_DEFAULT_INTRINSIC_EVIDENCE_ROLE = "background"


def _intrinsic_evidence_role(payload: dict[str, Any] | None) -> str:
    """Intrinsic evidence role for a doc: ``payload['evidence_role']`` when present and valid,
    otherwise the conservative ``background`` default. Never invented as ``evidence``."""
    raw = (payload or {}).get("evidence_role")
    if isinstance(raw, str) and raw in _EVIDENCE_ORDER:
        return raw
    return _DEFAULT_INTRINSIC_EVIDENCE_ROLE


def _clamp_in_context(intrinsic: str, proposed: str | None = None) -> str:
    """Return an in-context evidence role that never exceeds the intrinsic role (non-upgrading).

    Ported from ``mimer_runtime/retrieval.py::_clamp_in_context``: defaults to the intrinsic
    role; a proposed value is honored only when it is ordinally lower-or-equal. Retrieval may
    downgrade an evidence role for the current context but must never upgrade it toward ``evidence``.
    """
    if intrinsic not in _EVIDENCE_ORDER:
        intrinsic = _DEFAULT_INTRINSIC_EVIDENCE_ROLE
    if proposed is None or proposed not in _EVIDENCE_ORDER:
        return intrinsic
    return proposed if _EVIDENCE_ORDER.index(proposed) <= _EVIDENCE_ORDER.index(intrinsic) else intrinsic


@dataclass(frozen=True)
class ScopeDenial:
    """Content-free record that some relevant material was excluded by the scope prefilter.

    Records WHY and WHAT CLASS of flow would be needed WITHOUT identifying the denied content,
    scope, object, provenance, or even a per-document count — mirrors
    ``mimer_runtime/retrieval.py::ScopeDenial`` and validates against
    ``schemas/_defs.schema.json :: scope_denial`` (via the retrieval-result / context-envelope
    contracts). A denial is never a silent drop and never leaks scope/object identity.
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
class ScopedRetrieval:
    """Structured retrieval result carrying the ranked eligible items plus the content-free denials.

    ``results`` are the same ``List[dict]`` items ``hybrid_search`` returns (each now carrying an
    ``evidence_role_in_context``); ``denials`` records excluded-but-relevant material by class only;
    ``scope_policy_prefiltered`` asserts the eligibility decision ran BEFORE ranking. The
    ContextEnvelope assembler (:mod:`app.retrieval.envelope`) consumes this — never raw dicts.
    """

    results: List[dict]
    denials: tuple[ScopeDenial, ...] = ()
    scope_policy_prefiltered: bool = True
    active_scope: str | None = None


def _normalize_embedding(raw: Any) -> list[float] | None:
    """Coerce a caller-supplied embedding into ``list[float] | None``.

    An empty/missing value normalizes to ``None`` — the store's signal that
    this document has no preloaded vector and is a candidate for the
    per-document lazy-embed fallback (ADR-0059 D1).
    """
    if not raw:
        return None
    return [float(v) for v in raw]


@dataclass
class Document:
    doc_id: str
    text: str
    language: Optional[str] = None
    source_ref: Optional[str] = None
    payload: dict[str, Any] | None = None
    # Preloaded vector from the durable index (ADR-0059 D1). ``None`` means no
    # stored vector was supplied and the document is embedded lazily, on
    # first score computation, via the explicit fallback in ``_ensure_indexes``.
    embedding: Optional[list[float]] = None


class MemoryHybridStore:
    """Warm cache-through of the durable vector index (KERNEL-05, I-D3).

    ADR-0059 D1: the store loads whatever vectors its documents were given
    (typically the durable index's stored ``embedding`` column, passed
    through by ``rebuild_from_durable_index``) and never re-embeds a document
    that already carries one. Documents without a preloaded vector — only
    test-seeded corpora via ``set_documents()``/``add_document()`` without an
    ``embedding`` — are embedded lazily and exactly once, per document, the
    first time scores are computed.
    """

    def __init__(self) -> None:
        self._docs: List[Document] = []
        self._bm25: Optional[BM25Okapi] = None
        self._tokenized: Optional[List[List[str]]] = None
        self._embeddings: Optional[np.ndarray] = None
        self._emb_norms: Optional[np.ndarray] = None

    def _invalidate(self) -> None:
        self._bm25 = None
        self._tokenized = None
        self._embeddings = None
        self._emb_norms = None

    def add_document(
        self,
        *,
        doc_id: str,
        text: str,
        language: Optional[str] = None,
        source_ref: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        embedding: Optional[list[float]] = None,
    ) -> None:
        self._docs.append(
            Document(
                doc_id=doc_id,
                text=text,
                language=language,
                source_ref=source_ref,
                payload=dict(payload or {}),
                embedding=_normalize_embedding(embedding),
            )
        )
        self._invalidate()

    def set_documents(self, docs: List[dict]) -> None:
        self._docs = [
            Document(
                doc_id=str(doc["doc_id"]),
                text=str(doc["text"]),
                language=doc.get("language"),
                source_ref=doc.get("source_ref"),
                payload=dict(doc.get("payload") or {}),
                embedding=_normalize_embedding(doc.get("embedding")),
            )
            for doc in docs
        ]
        self._invalidate()

    def all(self) -> List[Document]:
        return list(self._docs)

    def _fill_missing_embeddings_lazily(self) -> None:
        """Explicit lazy-embed fallback (ADR-0059 D1), scoped to only the
        documents that were seeded without a preloaded vector.

        Never reachable from ``rebuild_from_durable_index()`` once ingest
        always writes vectors (it does today) — this exists for test-seeded
        corpora built via ``set_documents()``/``add_document()`` without an
        ``embedding``, and for the fail-safe single-row fallback when a
        durable row's stored vector is unexpectedly empty/missing (rebuild
        never crashes on that; see ``rebuild_from_durable_index``).
        """
        missing_idx = [i for i, doc in enumerate(self._docs) if not doc.embedding]
        if not missing_idx:
            return
        texts = [self._docs[i].text for i in missing_idx]
        vectors, _ = embed_docs(texts)
        for i, vector in zip(missing_idx, vectors):
            self._docs[i].embedding = list(vector)

    def _ensure_indexes(self) -> None:
        if not self._docs:
            return
        if self._tokenized is None:
            self._tokenized = [
                _tokenize(doc.text, doc.language)
                for doc in self._docs
            ]
        if self._bm25 is None and self._tokenized:
            self._bm25 = BM25Okapi(self._tokenized)
        if self._embeddings is None:
            # ADR-0059 D1: use each document's preloaded vector where present;
            # embed only the documents that still lack one (explicit fallback,
            # never the whole corpus when vectors were already supplied).
            self._fill_missing_embeddings_lazily()
            vectors = [doc.embedding or [] for doc in self._docs]
            if not any(vectors):
                self._embeddings = np.zeros((0, 0), dtype=np.float32)
                self._emb_norms = np.zeros(0, dtype=np.float32)
            else:
                dim = next(len(v) for v in vectors if v)
                for doc, vector in zip(self._docs, vectors):
                    if vector and len(vector) != dim:
                        raise ValueError(
                            "hybrid store embedding dim mismatch for doc "
                            f"{doc.doc_id!r}: expected {dim}, got {len(vector)}"
                        )
                self._embeddings = np.array(
                    [vector if vector else [0.0] * dim for vector in vectors],
                    dtype=np.float32,
                )
                norms = np.linalg.norm(self._embeddings, axis=1)
                norms[norms == 0] = 1e-9
                self._emb_norms = norms

    def bm25_scores(self, tokens: List[str]) -> np.ndarray:
        self._ensure_indexes()
        if not self._docs or self._bm25 is None:
            return np.zeros(len(self._docs))
        return np.array(self._bm25.get_scores(tokens), dtype=np.float32)

    def embedding_scores(self, query_vector: np.ndarray) -> np.ndarray:
        self._ensure_indexes()
        if self._embeddings is None or self._emb_norms is None or not self._docs:
            return np.zeros(len(self._docs))
        if query_vector.ndim != 1:
            raise ValueError("query embedding must be 1D")
        expected_dim = self._embeddings.shape[1] if self._embeddings.ndim == 2 else 0
        if expected_dim and query_vector.shape[0] != expected_dim:
            raise ValueError(
                f"hybrid query embedding dim mismatch: expected {expected_dim}, got {query_vector.shape[0]}"
            )
        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            return np.zeros(len(self._docs))
        q = query_vector / q_norm
        sims = (self._embeddings @ q) / self._emb_norms
        sims = np.clip(sims, -1, 1)
        return (sims + 1) / 2


_STORE = MemoryHybridStore()
_REBUILT_FROM_DURABLE_INDEX = False

# G1res-1 (#2981): durable store-generation token captured at the last rebuild,
# plus the monotonic time of the last generation check. The serving path
# revalidates the cache against the durable generation signal at most once per
# min-check interval and forces a rebuild on mismatch, closing the
# once-per-process staleness gap without a per-query durable-store round-trip.
_REBUILD_GENERATION: str | None = None
_LAST_GENERATION_CHECK_MONOTONIC: float | None = None

_DEFAULT_GENERATION_MIN_CHECK_INTERVAL_S = 1.0


def _generation_check_min_interval() -> float:
    """Min seconds between durable generation checks.

    Configurable via ``RETRIEVAL_GENERATION_MIN_CHECK_INTERVAL_S`` but clamped
    to a mandatory >=1s floor (issue #2981 constraint: the serving path must
    never round-trip to the durable store on every query). Junk values fall
    back to the default rather than disabling the bound.
    """
    raw = os.getenv("RETRIEVAL_GENERATION_MIN_CHECK_INTERVAL_S", "").strip()
    if raw:
        try:
            return max(_DEFAULT_GENERATION_MIN_CHECK_INTERVAL_S, float(raw))
        except ValueError:
            pass
    return _DEFAULT_GENERATION_MIN_CHECK_INTERVAL_S


def _revalidate_cache_generation() -> None:
    """Serving-path freshness check (G1res-1, #2981).

    Only applies once the cache has been populated from the durable index
    (never touches test corpora seeded directly via ``set_documents``). At
    most once per min-check interval, reads the durable store-generation
    token; on mismatch with the token captured at the last rebuild, forces a
    full rebuild so committed upserts/purges become visible without a process
    restart. Changes only WHEN a rebuild happens — never eligibility, scope
    prefilter ordering, or evidence-role clamping.
    """
    global _LAST_GENERATION_CHECK_MONOTONIC
    if not _REBUILT_FROM_DURABLE_INDEX:
        return
    now = time.monotonic()
    if (
        _LAST_GENERATION_CHECK_MONOTONIC is not None
        and (now - _LAST_GENERATION_CHECK_MONOTONIC) < _generation_check_min_interval()
    ):
        return
    _LAST_GENERATION_CHECK_MONOTONIC = now

    from app.stores import get_vector_index

    if get_vector_index().generation() != _REBUILD_GENERATION:
        rebuild_from_durable_index(force=True)


def _row_text(payload: dict[str, Any]) -> str | None:
    text = payload.get("text") or payload.get("content")
    return str(text) if text else None


def rebuild_from_durable_index(*, force: bool = False) -> int:
    """Load every row from the durable ``store_vector_index`` into the in-process cache.

    This is the ONLY production path allowed to populate the retrieval store
    (KERNEL-05, audit invariant I-D3): ``MemoryHybridStore`` is a cache-through
    of ``store_vector_index``, never an independently written truth. Safe to
    call repeatedly; a completed rebuild is a no-op unless ``force=True`` (used
    after a kill-and-restart simulation or an explicit operator-triggered
    reindex).

    ADR-0059 D1: each row's stored ``embedding`` is passed through to the
    cache as-is (mixed-identity rows load as-is; they are dimension-matched
    and L2-renormalized by construction at write time — ADR-0023/ADR-0052) so
    the serving path never re-embeds a document that the durable index
    already has a vector for. A row whose stored vector is unexpectedly
    empty/missing does not fail the rebuild: it is loaded with ``embedding``
    unset and picked up by the store's per-document lazy-embed fallback the
    first time scores are computed (fail-safe, logged, never a crash).

    Returns the number of documents loaded into the cache.
    """
    global _REBUILT_FROM_DURABLE_INDEX, _REBUILD_GENERATION, _LAST_GENERATION_CHECK_MONOTONIC
    if _REBUILT_FROM_DURABLE_INDEX and not force:
        return len(_STORE.all())

    from app.stores import get_vector_index

    index = get_vector_index()
    # Capture the generation BEFORE reading rows: a write racing the rebuild
    # then triggers the next generation check instead of being missed.
    generation = index.generation()

    docs: list[dict] = []
    missing_embeddings = 0
    for row in index.all_rows():
        payload = row.get("payload") or {}
        text = _row_text(payload)
        if not text:
            continue
        embedding = row.get("embedding") or None
        if not embedding:
            missing_embeddings += 1
        docs.append(
            {
                "doc_id": str(row["object_id"]),
                "text": text,
                "language": payload.get("language"),
                "source_ref": row.get("source_ref"),
                "payload": payload,
                "embedding": embedding,
            }
        )
    if missing_embeddings:
        _logger.warning(
            "rebuild_from_durable_index: %d/%d durable rows have no stored "
            "embedding; falling back to per-document lazy embedding for "
            "those rows only",
            missing_embeddings,
            len(docs),
        )
    _STORE.set_documents(docs)
    _REBUILT_FROM_DURABLE_INDEX = True
    _REBUILD_GENERATION = generation
    _LAST_GENERATION_CHECK_MONOTONIC = time.monotonic()
    return len(docs)


def reset_durable_rebuild_state() -> None:
    """Test-only: force the next ``rebuild_from_durable_index()`` call to reload.

    Simulates a process restart discarding the in-memory cache without
    discarding the durable index.
    """
    global _REBUILT_FROM_DURABLE_INDEX, _REBUILD_GENERATION, _LAST_GENERATION_CHECK_MONOTONIC
    _REBUILT_FROM_DURABLE_INDEX = False
    _REBUILD_GENERATION = None
    _LAST_GENERATION_CHECK_MONOTONIC = None


def _resolve_domain_scope() -> str | None:
    raw = os.getenv("ASK_DOMAIN_SCOPE", "").strip()
    return raw or None


def _extract_domain(doc: Document) -> str | None:
    """Extract domain from document payload.

    Domain must be explicitly set at ingest/write boundary.
    Missing domain is treated as 'unscoped' (conservative default).
    Path-derived domain is NOT used per LAYERING_MODEL contract.
    """
    payload = doc.payload or {}
    raw = payload.get("domain")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _bridge_domains(doc: Document) -> set[str]:
    payload = doc.payload or {}
    raw = payload.get("bridge_domains")
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _doc_in_scope(doc: Document, scope: str) -> bool:
    domain = _extract_domain(doc)
    if not domain:
        return False
    if domain == scope:
        return True
    return scope in _bridge_domains(doc)


def embed_text(text: str, language: Optional[str] = None) -> list[float]:
    """Backwards-compatible embedding helper for tests that patch this symbol."""
    vector, _ = embed_query(text)
    return vector


def embed_batches(texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
    """Backwards-compatible batch embedding helper for tests that patch this symbol."""
    del batch_size
    vectors, _ = embed_docs(texts)
    yield vectors


def get_store() -> MemoryHybridStore:
    return _STORE


def _tokenize(text: str, language: Optional[str]) -> List[str]:
    return [tok for tok in text.lower().split() if tok]


def _normalize(scores: np.ndarray) -> np.ndarray:
    if not len(scores):
        return scores
    min_v = float(np.min(scores))
    max_v = float(np.max(scores))
    if math.isclose(max_v - min_v, 0.0):
        return np.zeros_like(scores)
    return (scores - min_v) / (max_v - min_v)


def _snippet(text: str, query: str, size: int = 300) -> str:
    if not text:
        return ""
    lowered = text.lower()
    target = query.lower().strip()
    idx = lowered.find(target) if target else -1
    if idx < 0 and target and process is not None:
        best = process.extractOne(target, [lowered])
        if best and best[1] > 60:
            idx = lowered.find(best[0])
    if idx < 0:
        for token in target.split():
            pos = lowered.find(token)
            if pos >= 0:
                idx = pos
                break
    if idx < 0:
        return text[:size].strip()
    start = max(0, idx - 60)
    end = min(len(text), idx + size)
    return text[start:end].strip()


def _denials_for_excluded(
    excluded: List[Document], scope: str, token_set: set[str]
) -> tuple[ScopeDenial, ...]:
    """Content-free denials for relevant material excluded by the scope prefilter.

    A doc is "relevant" if it shares at least one query token (a cheap lexical overlap check —
    ineligible content is NEVER embedded or run through the scoring machinery; that restraint is the
    invariant itself). Aggregated by denial class so the result records that material WAS withheld
    without leaking object/scope identity, content, provenance, or a per-document count.
    Mirrors ``mimer_runtime/retrieval.py::_denials_for_excluded``.

    The live ``app/`` path has no suppression_state today, so only the ``cross_scope_no_flow`` class
    can actually occur; ``suppressed`` is intentionally NOT emitted (do not invent a class that
    cannot occur), while the record shape stays compatible with the schema's denial enum.
    """
    if not token_set:
        return ()
    out_of_scope_relevant = False
    for doc in excluded:
        doc_tokens = set(_tokenize(doc.text, doc.language))
        if token_set & doc_tokens:
            out_of_scope_relevant = True
            break
    if not out_of_scope_relevant:
        return ()
    return (
        ScopeDenial(
            reason="relevant material outside the active scope was excluded; no CrossScopeFlow admits it",
            denial_class="cross_scope_no_flow",
            escalation_recommended=False,
            required_flow_class="other-scope -> active-scope, governed flow required",
        ),
    )


# Fixed multiplier for the token-overlap signal under weighted RRF fusion (ADR-0059 D3 step 5,
# #3407). `RRFSignalWeights` (app/settings/models.py) intentionally exposes only `lexical`/`dense`
# — overlap is the linear formula's smallest, non-primary term and is not part of the
# lexical>=dense trust-hierarchy knob those two fields guard (docs/MIMER_CAPABILITY_HARDENING/
# RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md's precedent: "overlap folds into the lexical rank ... under
# RRF"). 0.2 preserves the same 5:4:1 ratio the linear defaults encode (0.5:0.4:0.1) against the
# RRF defaults' 2x scaling (lexical=1.0, dense=0.8): 0.1 * (1.0/0.5) = 0.2. Fixed rather than
# read from config: overriding lexical/dense via env does not change this term.
_RRF_OVERLAP_WEIGHT = 0.2


def _rrf_ranks(raw_scores: np.ndarray) -> np.ndarray:
    """1-based ranks over ``raw_scores``, descending (rank 1 = highest raw score).

    Ties are broken deterministically by ascending original index — the same tie-break the linear
    branch gets from ``np.argsort`` for well-separated floats, made explicit here because RRF is
    rank-based by construction and a tie in a raw signal must still resolve to a stable rank.
    """
    n = len(raw_scores)
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    # Primary key -raw_scores (ascending -> highest score first); secondary key ascending index
    # breaks ties. np.lexsort sorts by the LAST key first.
    order = np.lexsort((np.arange(n), -np.asarray(raw_scores, dtype=np.float32)))
    ranks = np.empty(n, dtype=np.float32)
    ranks[order] = np.arange(1, n + 1, dtype=np.float32)
    return ranks


def _weighted_rrf_combined(
    bm25_raw: np.ndarray,
    emb_raw: np.ndarray,
    overlap_bonus: np.ndarray,
    tuning,
) -> np.ndarray:
    """Weighted RRF fusion (ADR-0059 D3 step 5, #3407), scoped to the ELIGIBLE partition only.

    Per-signal rank lists (BM25, embedding, overlap) combined as
    ``sum(w_s / (rrf_k + rank_s))``, then min-max normalized so the exposed score stays in
    ``[0, 1]`` — the same contract the linear branch already holds. Default ``rrf_signal_weights``
    keep ``lexical >= dense`` so ADR-0024's trust hierarchy (exact lexical match weighted above
    fuzzy semantic match) survives the strategy swap.
    """
    weights = tuning.rrf_signal_weights
    rrf_k = tuning.rrf_k
    bm25_rank = _rrf_ranks(bm25_raw)
    emb_rank = _rrf_ranks(emb_raw)
    overlap_rank = _rrf_ranks(overlap_bonus)
    rrf_scores = (
        weights.lexical / (rrf_k + bm25_rank)
        + weights.dense / (rrf_k + emb_rank)
        + _RRF_OVERLAP_WEIGHT / (rrf_k + overlap_rank)
    ).astype(np.float32)
    return _normalize(rrf_scores)


def _rank_eligible(
    query: str,
    docs: List[Document],
    eligible_idx: List[int],
    *,
    k: int,
    language: Optional[str],
    query_vector: list[float] | None,
) -> List[dict]:
    """Score, normalize, and rank ONLY the eligible docs, then package result dicts.

    Scores come from the store's cached BM25 + embedding indexes (the single source of vectors —
    a cache-through of the durable index, KERNEL-05), but the candidate set and min/max
    normalization are restricted to ``eligible_idx``, so ineligible rows can never enter the scored
    candidate set nor shift the normalization of eligible rows (the correctness bug the prefilter
    closes). Each result dict carries ``evidence_role_in_context`` clamped ordinally ``<=`` its
    intrinsic role.

    Fusion strategy (ADR-0059 D3, #3404/#3407) is selected by the process-resolved
    ``RetrievalTuning.fusion``: ``"linear"`` (default) reproduces today's literal formula exactly;
    ``"rrf"`` uses weighted Reciprocal Rank Fusion over the same eligible partition. Either way the
    exposed contract is identical: same candidate set, same result-dict shape, ``score in [0, 1]``.
    """
    if not eligible_idx:
        return []

    tokens = _tokenize(query, language)
    # Full-corpus raw scores from the store cache, then sliced to the eligible partition BEFORE
    # normalization — ineligible rows are excluded from the candidate set and the normalization base.
    bm25_full = _STORE.bm25_scores(tokens)
    emb_vector_raw = query_vector if query_vector is not None else embed_text(query)
    emb_vector = np.array(emb_vector_raw, dtype=np.float32)
    if emb_vector.ndim != 1 or not emb_vector.shape[0]:
        raise ValueError("embedding client returned invalid vector shape")
    emb_full = _STORE.embedding_scores(emb_vector)

    idx_arr = np.array(eligible_idx, dtype=np.intp)
    bm25_raw = np.asarray(bm25_full, dtype=np.float32)[idx_arr]
    emb_raw = np.asarray(emb_full, dtype=np.float32)[idx_arr]

    bm25_norm = _normalize(bm25_raw)
    emb_norm = _normalize(emb_raw)

    token_set = set(tokens)
    overlap_bonus = np.zeros(len(eligible_idx), dtype=np.float32)
    if token_set:
        for i, doc_idx in enumerate(eligible_idx):
            doc = docs[doc_idx]
            doc_tokens = set(_tokenize(doc.text, doc.language))
            overlap_bonus[i] = len(token_set & doc_tokens) / max(1, len(token_set))

    # ADR-0059 D3 (#3404/#3407): fusion strategy and weights come from the process-resolved
    # RetrievalTuning config instead of a literal. "linear" reproduces today's formula exactly
    # (parity-tested); "rrf" is the weighted-RRF alternative, dark by default.
    tuning = get_retrieval_tuning()
    if tuning.fusion == "rrf":
        combined = _weighted_rrf_combined(bm25_raw, emb_raw, overlap_bonus, tuning)
    else:
        weights = tuning.linear_weights
        combined = weights.bm25 * bm25_norm + weights.embedding * emb_norm + weights.overlap * overlap_bonus
    order = [int(i) for i in np.argsort(-combined)][:k]

    results: List[dict] = []
    for i in order:
        doc = docs[eligible_idx[i]]
        score = float(np.clip(combined[i], 0.0, 1.0))
        snippet = _snippet(doc.text, query)
        payload = dict(doc.payload or {})
        intrinsic = _intrinsic_evidence_role(payload)
        results.append(
            {
                "id": doc.doc_id,
                "doc_id": doc.doc_id,
                "text": doc.text,
                "score": score,
                "snippet": snippet,
                "source_ref": doc.source_ref,
                "payload": payload,
                # In-context evidence role, clamped so it never exceeds the intrinsic role.
                "evidence_role_in_context": _clamp_in_context(intrinsic),
            }
        )
    return results


def _partition_by_scope(
    docs: List[Document], scope: str | None
) -> tuple[List[int], List[Document]]:
    """Split docs into (eligible indices, excluded docs) by scope eligibility, BEFORE tokenize/score.

    Eligibility decides membership; similarity decides order. With no active scope every doc is
    eligible (unchanged behavior). With an active scope, membership is the same conservative domain
    decision as before (``_doc_in_scope``: explicit ``payload['domain']`` / ``bridge_domains``;
    missing domain is ineligible) — only its POSITION moves ahead of scoring. Eligible items are
    returned as store indices so scoring can reuse the store's cached vectors while excluding the
    ineligible rows from the candidate set.
    """
    if not scope:
        return list(range(len(docs))), []
    eligible_idx: List[int] = []
    excluded: List[Document] = []
    for idx, doc in enumerate(docs):
        if _doc_in_scope(doc, scope):
            eligible_idx.append(idx)
        else:
            excluded.append(doc)
    return eligible_idx, excluded


def _contain_rerank(query: str, admitted: List[dict]) -> List[dict]:
    """Apply the optional rerank hook, then enforce that it only reordered/dropped within the
    admitted set — reranking never reintroduces an excluded doc (spec AC1, second clause)."""
    admitted_ids = {item.get("doc_id") for item in admitted}
    reranked = maybe_rerank(query, admitted)
    intruders = {item.get("doc_id") for item in reranked} - admitted_ids
    if intruders:
        raise AssertionError(
            f"rerank introduced doc_ids absent from the admitted set: {sorted(map(str, intruders))}"
        )
    return reranked


def scoped_hybrid_search(
    query: str,
    *,
    k: int = 8,
    language: Optional[str] = None,
    query_vector: list[float] | None = None,
) -> ScopedRetrieval:
    """Scope-prefiltered retrieval with content-free denials — the structured entrypoint.

    Partitions the store into eligible/excluded BY SCOPE before ranking, ranks the eligible set
    only, records excluded-but-relevant material as content-free denials, and returns a
    :class:`ScopedRetrieval`. ``hybrid_search`` is the ``List[dict]`` projection of ``.results``.
    """
    # G1res-1 (#2981): revalidate the durable-index cache-through before serving.
    _revalidate_cache_generation()

    docs = _STORE.all()
    scope = _resolve_domain_scope()
    if not docs:
        return ScopedRetrieval(results=[], denials=(), scope_policy_prefiltered=True, active_scope=scope)

    # 1) PREFILTER before ranking — eligibility decides membership, not similarity.
    eligible_idx, excluded = _partition_by_scope(docs, scope)

    # Content-free denials for relevant-but-excluded material (never a silent drop). The empty
    # eligible set is likewise no longer a silent early-exit.
    token_set = set(_tokenize(query, language))
    denials = _denials_for_excluded(excluded, scope, token_set) if scope else ()

    # 2) RANK only the eligible set (candidate set + normalization restricted to eligible-only).
    results = _rank_eligible(
        query, docs, eligible_idx, k=k, language=language, query_vector=query_vector
    )

    # 3) Rerank within the admitted set only (never reintroduces an exclusion).
    results = _contain_rerank(query, results)
    return ScopedRetrieval(
        results=results,
        denials=denials,
        scope_policy_prefiltered=True,
        active_scope=scope,
    )


def hybrid_search(query: str, *, k: int = 8, language: Optional[str] = None, query_vector: list[float] | None = None) -> List[dict]:
    """Item-consumer entrypoint: the ranked, scope-eligible result dicts.

    The scope prefilter is now internal to this production entrypoint (it runs BEFORE scoring via
    :func:`scoped_hybrid_search`), so callers and the spec's ``test_prefilter_precedes_ranking``
    bind to the same path. Each result dict additionally carries ``evidence_role_in_context``.
    """
    return scoped_hybrid_search(query, k=k, language=language, query_vector=query_vector).results


__all__ = [
    "hybrid_search",
    "scoped_hybrid_search",
    "ScopedRetrieval",
    "ScopeDenial",
    "get_store",
    "MemoryHybridStore",
    "Document",
    "rebuild_from_durable_index",
    "reset_durable_rebuild_state",
]
