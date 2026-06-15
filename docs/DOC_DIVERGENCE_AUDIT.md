State: Documentation reality audit, point-in-time, non-canonical.
Doc role: Audit report
Authority: Advisory only. `docs/DOCS_INDEX.md` remains the canonical documentation role map.
Owner: Documentation governance / architecture review
Temporal class: snapshot
Review cadence: ad hoc
Source of truth: mixed
Last reviewed: 2026-06-15
Supersedes: the 2026-05-28 edition of this report (same path).

# Documentation Divergence Audit

## Purpose and framing

This is a point-in-time audit of documentation reality. It is advisory only and does not change any
authority boundary. `docs/DOCS_INDEX.md` remains the canonical documentation role map; this report is
subordinate to it and must not be read as a competing source of truth.

The framing from the 2026-05-28 edition still holds and is not repeated in full:

- The repo does **not** lack documentation governance. `DOCS_INDEX.md` is the canonical role map.
- The risk is **not** "too many docs." A large, well-mapped doc set is not a defect.
- The real risk is **role drift** between current-runtime truth, target-state design, implementation
  writebacks, roadmap/spec, operations, and historical/snapshot surfaces.
- The correct response is **authority-preserving normalization** — repair contradictions and make
  authority legible — **not** a broad rewrite that would itself create drift.

## Method (2026-06-15 run)

Five read-only audit agents swept the corpus in parallel (temporal control surfaces; capability/
concept owner docs; architecture/contract coherence; duplication/overlap; `DOCS_INDEX` integrity),
plus a mechanical broken-link scan. Findings were then **re-baselined against `origin/main`**.

**Methodology finding (load-bearing):** the run was launched from a recovery branch
(`recovery/companion-loopback-bind-wip`) that was **107 commits behind `origin/main`**. Roughly a
third of the raw findings were *branch-staleness artifacts* — docs already corrected on `main` — not
real defects. Every finding below was verified against `main` (`969316fb`) before inclusion. The
lesson: a doc audit must run against `origin/main`, never a stale local branch, or it will "rediscover"
already-fixed drift and risk re-introducing it.

## Section 0 — Already fixed on main (do not re-flag)

These were flagged by the sweep but verified resolved on `main`; the prior audit's headline item is
among them:

- `STATUS.md`, `ROADMAP.md`, `OPERATIONS.md` — current on `main` (reference CRE, durable memory, the
  v6.1 Wave-1 promotion, issues through #2026). The local-branch copies were stale.
- `ARCHITECTURE.md` — now documents the Contextual Relevance Engine seam (`app/relevance/*`,
  verified 2026-06-13). The "ARCHITECTURE never mentions CRE" finding was branch-staleness.
- `docs/AGENT_MEMORY/README.md` **index row** — relabeled `Draft specification` →
  `Delivered specification (parent #900 closed; all five slices shipped)`. The 2026-05-28 audit's
  finding #2 is **resolved**.
- `docs/EVENTS.md` — confirmed clean: no product action-verbs (Find/Reorient/Resurface/Act) have
  leaked in as emitted-event contracts. (Re-confirmed non-finding.)
- DB-as-mirror-not-authority invariant — consistent across ARCHITECTURE / DATA_MODEL / DB_SCHEMA /
  SEMANTIC_AUTHORITY_MATRIX / SYSTEM_OF_SYSTEMS. The authority layer is sound; only table *naming*
  drifts (see §2).

## Section 1 — Fixed in this run (applied to the docs PR)

Unambiguous, code-verified current-state corrections, real on `main`:

1. `docs/adr/INDEX.md` — removed two broken placeholder links
   (`ADR-00X-agent-memory-v1.md`, `ADR-00X-agent-memory-v42.md`); no such files exist.
2. `docs/COMPONENTS.md` — Companion Note maturity `Planned/forward-line contract` → `Active`
   (shipped: `app/services/companion_note.py`; the settled production replacement for VaultMirror).
3. `docs/CONCURRENCY.md` — deterministic-ID field `event_type` → `event` (canonical envelope field
   per `EVENTS.md`; `event_type` is not in the contract).
4. `docs/DEPENDENCIES.md` — prod config var `OLLAMA_MODEL` → `LLM_MODEL` (canonical chat-model var;
   `OLLAMA_MODEL` is a deprecated fallback only).
5. `docs/LANGGRAPH_AGENT_ARCHITECTURE.md` — example event `promotion.intent.created` →
   `promote.intent.created` (canonical name, `EVENTS.md` §`promote.intent.created`).
6. `docs/LANGGRAPH_AGENT_ARCHITECTURE.md` — removed dead `model="claude-3-sonnet"` arg from the
   `facade.chat()` example (stale model id + bypassed the routing fabric).

## Section 2 — Confirmed real on main, judgment required (proposed as issues, not auto-applied)

These are real defects, but the fix needs an architectural call or a verified rewrite. Auto-applying
them would risk exactly the broad-rewrite drift this audit warns against.

- **DB schema docs describe the wrong tables (high).** `docs/DATA_MODEL.md` and `docs/DB_SCHEMA.md`
  document the legacy AMG-core migration tables (`objects` / `chunks` / `embeddings` + a fabricated
  `search_vector` column) and even attribute them to Alembic. The **active runtime** uses
  `store_objects` + `store_vector_index`, created by runtime DDL in `app/stores/pg.py` (not Alembic).
  Two contract docs and the code give three different `embeddings` shapes. → Issue: reconcile both
  docs to the runtime store, demote the AMG tables to an explicit "historical lineage" subsection.
- **`COMPONENTS.md` ReasoningFacade / BaseLangGraphAgent still "Planned" (med).** Both exist and are
  imported (`app/reasoning/facade.py`, panel/canvas/chat paths), but are dormant-by-design (Cognitive
  Expansion is flag-gated). "Planned" understates; "Active" overstates. → Decision: relabel to
  `Experimental (opt-in, roadmap-gated off)` or add a one-line "code exists, gated off" note.
- **`ENVIRONMENTS.md` calls `prod` a "future target contract" (med-high).** Identical on `main`;
  last reviewed 2026-04-02. A real prod channel exists (promotion receipt
  `ops/promotions/2026-06-13-cc3ce65d.md`). **Caveat that makes this judgment, not mechanical:** the
  same receipt promoted CRE/recall code *inert* in Wave 1 ("'CRE in prod' ≠ 'CRE running'"). Any
  reframe must keep the promoted-but-dormant distinction and reconcile with `RELEASE_CHANNELS`.
- **`SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (med):** Human Surface still reads "Companion-UI is
  design-handoff … not production runtime" (last reviewed 2026-05-14); the System Entry Point shell
  shipped. → Current-state correction.
- **`INTERACTION_SURFACES_AND_AUTHORITY/README.md` + `CONTEXT_BUNDLES/README.md` (med):** owner-doc
  State/Status lag their own DOCS_INDEX rows and delivery records (canvas Chat shipped behind
  `CANVAS_ENABLED`; Context Bundles runtime "Satisfied 2026-06-04" yet the intro still says "upstream
  of any runtime implementation … does not claim the runtime already does it"). → Scope the
  historical wording; point forward to the satisfied wave.
- **`EMBEDDINGS.md` / `LLM.md` reconciliation (low):** `EMBED_DIM` example `768` vs code default
  `1536` (nomic-embed-text is natively 768 — state the authoritative runtime value); and the primary
  Ollama embedding endpoint (`/api/embed` native vs `/api/embeddings` compat) is described
  inconsistently. → Reconcile against `app/embedding_config.py` / `app/llm/embeddings.py`.

## Section 3 — `DOCS_INDEX` integrity

Verified against `main`. **Zero dangling rows** (everything the index rows point to exists). The gap
is *under-coverage* and *stale status labels*, not broken pointers:

- **~90 child-spec orphans:** the index uses a one-row-per-child convention for some capability dirs
  (CONTEXT_BUNDLES, AGENT_MEMORY) but stops at the README for others. On `main`:
  `SYSTEM_ENTRY_POINT/` has 3 index rows for 13 docs on disk; `CANVAS_CHAT_SURFACE/` has 2 for 12.
  Others: INTERACTION_SURFACES, COMMITMENT_AS_FIRST_CLASS, FINDING_AND_REORIENTING,
  SEPARATING_PERSISTENCE_SURFACES, RELEASE_CHANNELS, SCOPE_SPHERE, COGNITIVE_LOAD_RUNTIME_ADOPTION,
  DISPATCHER_AGENT_ADOPTION, 3 CONTEXTUALIZATION_LAYER children, 4 ADRs (0007/0009/0011/0012), a whole
  `docs/implementation/` dir, and `CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`.
- **Stale "pre-delivery" labels for shipped epics:** `SYSTEM_ENTRY_POINT/README.md` row still says
  "parent feature issue not yet filed" (epic #1782 filed; children #1783–#1795 merged);
  `CANVAS_CHAT_SURFACE` row predates PRs #605/#618/#619/#626.

→ Proposed as one bounded governance issue (mechanical backfill where the role label is uniform;
status text needs the per-slice issue/PR mapping).

## Section 4 — Consolidation proposal (authority-preserving)

The corpus is overwhelmingly single-owner; 8 evaluated clusters are cleanly delineated (architecture
trio, agents quartet, human-flows trio, context-bundles pair, inventory trio, ~28 contract docs,
ontology plans, dev-workflow stub). Real overlap is concentrated in ~9 docs / 6 clusters, mostly
restatement-that-risks-drift or temporal staleness — **not** authority contradiction.

Safe now (cross-link / scope-header only — can fold into the docs PR if approved):

- **cognitive-load** (`COGNITIVE_LOAD_PROJECTION_LAYER.md` ↔
  `COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md`): the contract owns the authority-class vocabulary
  and decision test; the operating-model should cite it rather than restate. Add cross-links + scope
  headers; do not merge (different audiences).
- **dispatcher adoption** (`DISPATCHER_AGENT_ADOPTION/README.md`): add a "delivered" banner — its
  premise "no agent workflow calls the dispatcher" is contradicted by the shipped owner contract.
- **same-filename hazards:** `ARTIFACT_MODEL_AND_LIFECYCLES.md` (CONCEPTS contract vs plans plan) —
  reciprocal cross-links + one-line scope headers.

Judgment required (→ issues):

- **Duplicate file:** `docs/plans/BENCHMARK_PROTOCOL.md` vs `docs/benchmarks/BENCHMARK_PROTOCOL.md`.
  The benchmarks/ copy is the canonical "Active" one; demote plans/ to a stub (the pattern
  `docs/DEV_WORKFLOW.md` already uses).
- **Contradictory plans:** `plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md` ("Delivered, Parts 1–8") vs
  `plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md` ("re-baselined … forward-line work"). Reconcile
  against `STATUS.md`, merge, demote one to a stub.
- **Largest unmapped surface:** `companion-ui/docs/` (55 files), including ~12
  cognition/attention/salience design-theory docs that are largely absent from `DOCS_INDEX.md` and
  overlap `CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`. Assign DOCS_INDEX roles *before*
  any merge. This is the most likely locus of unmapped role drift in the whole corpus.

## Section 5 — Recommended backlog issues

1. Reconcile DB schema docs (`DATA_MODEL.md` + `DB_SCHEMA.md`) to the runtime store tables. (§2)
2. `DOCS_INDEX` child-spec backfill + stale-label sweep (~90 rows). (§3)
3. `ENVIRONMENTS.md` prod-liveness reframe, preserving the promoted-but-dormant distinction. (§2)
4. Reclassify `COMPONENTS.md` ReasoningFacade / BaseLangGraphAgent maturity. (§2)
5. Consolidate the duplicate `BENCHMARK_PROTOCOL.md` and the contradictory companion-note plans. (§4)
6. Map the `companion-ui/docs/` cognition cluster into `DOCS_INDEX.md`. (§4)
7. Reconcile `EMBED_DIM` and the Ollama embedding endpoint across EMBEDDINGS / LLM / DB_SCHEMA. (§2)

## Non-goals

- This audit does not create a new canonical map.
- It does not rewrite architecture, change contracts, or alter shipped reality.
- It does not delete any document (the one deletion in §1 is two dead links inside an index, not a doc).
- The §1 fixes are current-state corrections only; everything requiring judgment is deferred to §2–§5.
