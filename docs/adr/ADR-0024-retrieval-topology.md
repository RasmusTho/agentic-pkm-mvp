State: Accepted (ratifies shipped reality; recorded by #2317). Records the retrieval topology that the system already ships: an in-memory hybrid serving path with weighted linear fusion, rerank off by default, and a durable-spine direction toward the Postgres/pgvector index. **Numbering note:** the governing issue #2317 originally named this "ADR-0016", but ADR-0015 through ADR-0022 were already taken on `origin/main` (the SBS series). This record uses the next free number, **ADR-0024**; its sibling embedding-egress ADR is **ADR-0023**, and **ADR-0025** is reserved for sibling issue #2318.
Doc role: Decision record (ADR)
Authority: Authoritative for the current retrieval topology decision (in-memory hybrid serving, weighted linear fusion shape, rerank-off default, durable-spine direction). Operational scoring/behavior detail remains in `docs/RETRIEVAL.md`; this ADR records the decision those mechanics implement.
Owner: Architecture / Retrieval posture
Temporal class: Durable decision (supersede via a new ADR, do not edit in place). Revisit when the durable spine becomes the serving path or when a fusion strategy (RRF/HyDE/low-trust-weights) is adopted — see "Future work / when to revisit".
Source of truth: This ADR for the topology decision; `docs/RETRIEVAL.md` for the live scoring/behavior contract; `app/retrieval/hybrid.py` for the executing code.

# ADR-0024: Retrieval topology — in-memory hybrid serving, weighted linear fusion, durable-spine direction

**Date:** 2026-06-20
**Status:** Accepted (ratifies shipped reality)

---

## Context

The retrieval path was built and shipped before it was captured as a decision record. The live serving path is an **in-process memory store** (`app/retrieval/hybrid.py`) that combines lexical (BM25), dense (embedding cosine), and a small token-overlap bonus, and exposes the same path through a typed capability wrapper (`app/retrieval/capability.py`). A durable Postgres/pgvector index (`PgVectorIndex`) exists as the intended durable spine, but the **active serving path is the in-memory store**, not the durable index — the two are currently disconnected (see the RAG/memory decomposition epic #2314).

The scoring is a **weighted linear fusion** with hardcoded weights, rerank is **off by default**, and several stronger retrieval strategies (RRF, HyDE/query expansion, provenance-aware / low-trust signal weights, an eval framework) are deliberately deferred behind a future `SearchPort` boundary (`docs/ROADMAP.md :: Abstraction Layer Hardening`). None of this was recorded as a decision; this ADR ratifies the shipped topology so the owner docs and the backlog reason against a captured baseline rather than implicit reality.

## Decision

**Ratify the shipped retrieval topology as the current accepted baseline. No behavior change.**

1. **In-memory hybrid serving is the active path.** The default retrieval path is the in-process memory store in `app/retrieval/hybrid.py` (`hybrid_search`), consumed through the typed `app/retrieval/capability.py::retrieve(RetrievalRequest)` wrapper. This is the serving path today; the durable `PgVectorIndex` is the intended spine but is not the serving path yet.

2. **Weighted linear fusion is the scoring shape.** Per document, the runtime normalizes each signal and combines them linearly:

   `combined = 0.5 * bm25_norm + 0.4 * emb_norm + 0.1 * overlap_bonus`

   The weights are an intentional first-pass **trust encoding** (exact lexical match weighted above fuzzy semantic match, with a small overlap bonus), not an arbitrary tuning artifact. The authoritative scoring detail lives in `docs/RETRIEVAL.md :: Scoring`.

3. **Rerank is off by default.** The optional rerank hook (`app/retrieval/rerank/` via `app/retrieval/hook_adapter.py`) is opt-in (`RERANK_ENABLE` unset/false by default) and does not run on the default path.

4. **Durable-spine direction.** The accepted forward direction is to make the durable Postgres/pgvector index (`PgVectorIndex`) the serving spine, replacing the in-memory store as the source of served results, behind a stable retrieval boundary (`SearchPort`). This is direction, not shipped state; the in-memory store remains the serving path until that migration lands (tracked under #2314).

5. **Default filtering and metadata posture (unchanged).** Optional operational-scope filtering and the metadata/diagnostic inputs (provenance, relation, view-freshness, opt-in salience/staleness) remain *metadata only* and do not affect ranking or filtering on the default path, exactly as `docs/RETRIEVAL.md` already describes.

## Future work / when to revisit

These are **named future work**, not part of the ratified baseline, and are deferred behind the `SearchPort` boundary (`docs/ROADMAP.md :: Abstraction Layer Hardening :: Retrieval quality improvements`). Adopting any of them is a new decision (new ADR):

- **RRF (Reciprocal Rank Fusion)** over the weighted linear sum — more robust to score-scale differences between lexical and dense signals; must be validated not to degrade the intentional trust hierarchy before replacing the weights.
- **HyDE / query expansion** — generate-then-embed or multi-query merge for abstract/retrospective PKM queries.
- **Provenance-aware / low-trust signal weights** — per-source-type weighting (e.g. lower semantic weight for AI-generated memory artifacts than for human-authored notes).
- **Eval framework** — an automated retrieval-quality regression signal (RAGAS or LLM-as-judge) in CI.

Revisit this ADR (a new ADR) when:

- the durable `PgVectorIndex` becomes the **serving** path (topology change), or
- any of the future-work fusion/expansion strategies above is **adopted as default** (scoring change), or
- the default filtering/metadata posture starts affecting ranking on the default path.

## Consequences

- The current retrieval topology now has a captured baseline: in-memory hybrid serving, `0.5/0.4/0.1` linear fusion, rerank-off, durable-spine as direction. Owner docs and the backlog reason against this record instead of implicit code reality.
- `docs/RETRIEVAL.md` is reconciled to state the live serving path (in-memory vs durable `PgVectorIndex`), the explicit fusion weights, the rerank-off default, and the future-work list — anchored to this ADR. No runtime behavior changes.
- The deferred retrieval-quality strategies (RRF/HyDE/low-trust-weights/eval) stay future work behind `SearchPort`; this ADR does not adopt them.
- This ADR is docs/decision-only: no `app/` or `tests/` change. It ratifies the topology the shipped code already implements.

## References

- #2314 — RAG/memory decomposition epic (durable-spine migration parent track)
- #2317 — this ratification (two ADRs, docs-only); records the ADR-0016→ADR-0024 renumber
- `docs/RETRIEVAL.md` :: Scoring, Hybrid Search, Optional Rerank, Delta / Known Limits (reconciled live-reality wording)
- `docs/ROADMAP.md` :: Abstraction Layer Hardening (SearchPort boundary + Retrieval quality improvements: RRF/HyDE/low-trust-weights/eval as future work)
- `app/retrieval/hybrid.py`, `app/retrieval/capability.py`, `app/retrieval/rerank/`, `app/retrieval/hook_adapter.py` — the executing serving path
- ADR-0023 — sibling embedding-egress ratification
