State: Advisory audit snapshot (2026-07-02). Subordinate to `docs/DOCS_INDEX.md` and owner contracts. Executable form of §7 lives in the specification directory `docs/RUNTIME_CORRECTNESS_KERNEL/`.
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis; file:line anchors reflect `main` at 2026-07-02. Where this audit and an owner doc disagree, the owner doc wins and the divergence should be raised via issue, not silently resolved.

# Agentic PKM System Redesign — Structural Leverage Artifacts

Date: 2026-07-02
Basis: full-code survey of `app/stores`, `app/services/{outbox,vault_sync,indexer}`, `app/workers/outbox_worker.py`, `app/ingest/chunk_policy.py`, `app/indexer/consumer.py`, `app/chat/intent_classifier.py`, `app/orchestrator/*`, `yggdrasil_runtime/*`, `tests/invariants/*`, `tests/evals/*`, `tests/eval/*`, `schemas/*`, `docs/CONCEPTS/*`, `AGENTS.md`.

Reconciliation notes (post-analysis, authoritative for the backlog conversion in `docs/RUNTIME_CORRECTNESS_KERNEL/`):
- **T5 extends #2314 W4-RET-01.** The epic's deferred stub already names "reconcile the in-memory/durable split"; T5 delivers that half. The lexical-mirror + fusion half of W4-RET-01 stays with the epic.
- **T10 reframed.** #2022/#2025 (admissibility-governed activation gate) are delivered and closed; the "Slice #2025 pending" reference in `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` is stale numbering. The remaining gap is promoting scope-prefilter + ContextEnvelope semantics from `yggdrasil_runtime` into the `app/` retrieval path.

---

## 1. Critical Weakness Analysis

Ranked by systemic impact (blast radius × silence of failure), not likelihood.

### CW-1 — Split-truth persistence: three retrieval/index substrates with best-effort coupling
- Durable index: `store_vector_index` via `PgVectorIndex` (`app/stores/pg.py`).
- In-memory retrieval store: `app/retrieval/hybrid.py`, fed by **best-effort, never-block** fan-in from JSONL append (`app/index/outbox.py:45-67`); failures silently swallowed.
- JSONL "index outbox" audit file (`app/outbox/events.py`) written in parallel with the DB outbox; if the DB insert fails the JSONL append still happens.
- Legacy generation coexists: `app/store/object_store.py` (silent memory fallback at line 72-75), `app/store/vector_store.py` (`embeddings` table), alongside `app/stores/*` (`store_vector_index`). The Alembic `embeddings` table and the `_ensure_tables()`-created `store_vector_index` are two schema authorities for the same concept.
- **Systemic effect:** what is retrieved ≠ what is durable ≠ what is audited. Every downstream capability (ASK, recall, relevance) inherits an unbounded, undetected divergence. This is the root of #2314's "live retrieval disconnected from durable PgVectorIndex" and of #2242-class "consumes nothing" incidents being invisible.

### CW-2 — LLM output crosses execution boundaries as free text with silent action-class defaults
- Intent classifier (`app/chat/intent_classifier.py:189-243`): LLM output parsed by regex + `json.loads`; unparseable/degraded output **defaults to `CO_AUTHORING` with `classified=False`**. CO_AUTHORING is a mutation-capable class — the failure default is not a refusal, it is a route.
- Planner (`app/planner/prompts.py`): JSON requested by prompt text; executor consumes payload without schema validation; invalid plans surface only at step execution.
- Reasoning engine (`app/reasoning/prompts.py`): "always respond with valid JSON" enforced only rhetorically.
- **Systemic effect:** the governance chain (intent → capability class → authority gate) is only as strong as a regex. Misclassification silently converts governance-bearing intent into body edits; plan-schema drift is detected at the most expensive point.

### CW-3 — Non-atomic multi-step mutations + opt-in idempotency
- `sync_markdown()` (`app/services/vault_sync.py:334-512`): objects upsert → file_state update → outbox insert are separate statements on one connection, **no transaction**. Crash windows leave objects without file_state, or outbox without commit. The outbox pattern's entire purpose (atomic state+event) is not realized.
- `handle_rename()` (vault_sync.py:515-546): `objects.path` and `file_state.path` updated separately.
- UUID healing spans vault write → companion write → DB write with no saga/compensation (`app/workers/outbox_worker.py:443-515,862-909`).
- Outbox idempotency key is **optional** (`app/services/outbox.py:206`); event dedup is in-memory only (`_EventDedup`, worker line 1210-1225), lost on restart. Handler idempotency is asserted by convention, verified nowhere.
- **Systemic effect:** at-least-once delivery without enforced idempotency and without atomic state+event means replay is not sound — the event log cannot be trusted to reconstruct state, defeating event-sourcing's core guarantee.

### CW-4 — Invariant enforcement lives in a test-only package; the runtime speaks untyped dicts
- 36 named invariants (docs/testing/invariant-tests.md), closed JSON Schemas (`schemas/*.schema.json`), frozen fail-loud value types — all in `yggdrasil_runtime/` (excluded from the wheel) and `tests/`.
- The live pipeline persists permissive `dict` payloads (`store_objects.payload`, `OutboxEvent.payload: Dict[str, Any]`), with no `schema_version`, no closed validation, no MetadataBundle. `inspect_pg_metadata_completeness()` (pg.py:677-721) can *observe* missing W3-SPINE-01 fields but nothing *prevents* writing them.
- **Systemic effect:** the system has a correct formal model and an unconstrained implementation. Drift between them is structural, not accidental; every new producer widens it.

### CW-5 — Silent fallback and false-green observability
- Store backend resolution probes Postgres and caches (`app/stores/provider.py:51-66`); legacy `ObjectStore` falls back to memory **silently on error**. A prod process can run healthy-looking on volatile state.
- Dead-letters are audit-logged but not alertable (observability audit 2026-06-27: ~1.4/5, zero alerting). `processed_total=0` for weeks (#2242) was the canonical symptom.
- **Systemic effect:** the failure mode of the whole pipeline is "quietly does nothing" — the most expensive failure class for a memory system, because absence of recall is indistinguishable from absence of content.

### CW-6 — Missing transformation provenance blocks replayability
- Vectors carry embedding identity (provider/model/dim/normalize) but **not** `content_hash` of the embedded text, **not** `chunk_policy_version`, **not** a pipeline version. Chunk metadata v1 is computed on demand, never persisted; what-was-embedded is a function of current code, not recorded state.
- Event `meta.version` is a static "1.0"; no per-topic payload schema registry.
- **Systemic effect:** "re-embed what changed", "was this vector produced from this text", and any deterministic replay/backfill require provenance that does not exist. Reconcile (#2752) works only for identity drift, not content/transform drift.

### CW-7 — Evaluation ground truth is thin and does not cover the highest-risk LLM decision
- Deterministic runner is sound (offline, thresholded, `eval_scorecard.v1`) but: 11 cases, precision@k floor 0.15, no eval at all for **intent classification** (the LLM decision that gates mutations), no model-comparison workflow beyond embryonic `benchmark.py`, LLM-judge suites opt-in and never gating.
- **Systemic effect:** model/prompt upgrades to the governance-critical classifier are unverifiable; retrieval regressions below a very low floor pass silently.

Failure-mode ranking for the four requested system classes:
1. **LLM-mediated ingestion:** unrecorded transform provenance (CW-6) > silent fan-in divergence (CW-1) > embed identity drift (mitigated: #2752/#2753).
2. **Orchestration over Store abstraction:** untyped boundary crossings (CW-2) > dual store generations (CW-1) > missing plan-level timeout (orchestrator v2 has per-step only).
3. **Event-sourced memory:** non-atomic state+event (CW-3) > opt-in idempotency (CW-3) > unbounded queue with no depth signal (CW-5).
4. **Evaluation frameworks:** no eval on the mutation-gating classifier (CW-7) > threshold floors below usefulness > judge suites decorative.

---

## 2. Invariant Set Proposal

Minimal set for correctness. `MUST` = fail-loud at runtime; `GATE` = CI/PR-blocking test; `DOCTOR` = detectable by read-only reconciliation. Existing partial enforcement noted.

### Data integrity
- **I-D1 (Derivation provenance).** Every persisted derived artifact `d` MUST carry `{source_id, source_content_hash, transform_id, transform_version, produced_at, trace_id}`. For vectors: `store_vector_index.payload.provenance ⊇ {source_ref, content_hash, chunk_policy_version, embedding_identity}`. *(New; extends W3-SPINE-01 fields.)*
- **I-D2 (Index identity).** At most one primary `EmbeddingIdentity` per index; rows diverging from it MUST be flagged `reconcilable_fallback` with matching `dim`, else write fails. *(Exists: CTI-1, pg.py:361-438 — keep.)*
- **I-D3 (Rebuildability).** `state_derived = replay(event_log, vault)` MUST hold: no serving substrate may hold state that is not reconstructible from durable stores. Corollary: the in-memory retrieval store is a cache of `store_vector_index`, never an independent truth. *(Violated today: app/index/outbox.py:45-67.)*
- **I-D4 (Continuity set).** vault note + companion note are the portable truth; every DB object row MUST be traceable to a vault uuid or carry `origin != vault`. UUID absence is advisory, never a gate. *(Exists as posture; keep — feedback: uuid-not-a-render-gate.)*

### Store mutation rules
- **I-S1 (Single writer).** Each durable table has exactly one writing module, and it is a `app/stores` protocol implementation. Legacy `app/store/*` writers are removed. GATE: import-boundary test enumerating writers per table.
- **I-S2 (Transactional outbox).** A state mutation and its outbox event MUST commit in one transaction: `BEGIN; upsert objects; upsert file_state; insert outbox; COMMIT`. Multi-store mutations that cannot share a transaction (vault + DB) MUST be sagas: ordered steps, each idempotent, with a recorded resume point. *(Violated: vault_sync.py:334-512.)*
- **I-S3 (Schema authority).** All DDL through Alembic; `_ensure_tables()` becomes assert-only (fail if missing), never create in non-test env. *(Violated: pg.py:37-110.)*
- **I-S4 (No silent fallback).** Backend resolution to memory MUST require explicit `STORE_BACKEND=memory`; probe failure with Postgres configured is fatal, not a fallback. *(Violated: app/store/object_store.py:72-75.)*

### Event/outbox rules
- **I-E1 (Mandatory idempotency key).** `write_outbox_event` requires `idempotency_key`; producers derive it deterministically: `key = sha256(topic ‖ source_id ‖ content_hash)` (or event-natural equivalent). No caller-optional path. *(Violated: outbox.py:206.)*
- **I-E2 (Idempotent handlers).** For every topic T: `handle_T(e); handle_T(e)` ≡ `handle_T(e)` observed on durable state. GATE: harness that dispatches every registered topic twice against a fixture payload and diffs state.
- **I-E3 (Ack-after-effect).** `ack_outbox` MUST be the last durable action of a dispatch; handlers assume at-least-once. *(Exists in worker loop — codify as GATE.)*
- **I-E4 (Dead-letter is loud).** `count(dead_lettered) > 0` and `age(oldest undelivered) > threshold` MUST surface in the health contract (WriteGuard's snapshot source), not only in audit JSONL. *(Violated: observability audit.)*
- **I-E5 (Typed topics).** Every topic has a versioned payload schema in a registry; validation at write AND at dispatch; invalid payload → immediate dead-letter with reason `schema_violation`, never partial processing. `OutboxEvent.meta.version` becomes `payload_schema: "<topic>.v<N>"`.

### Agent behavior constraints
- **I-A1 (Structured boundary).** LLM output that any code branches on MUST be produced under schema-constrained decoding (Ollama `format=json`/response schema; tool-call for API providers) and validated against a registered schema before use. Regex extraction on control paths is forbidden. Free-form prose is legal only as terminal user-facing output.
- **I-A2 (No default routes).** Classification failure yields explicit `UNKNOWN` surfaced to the caller (re-ask, degrade to read-only, or ask the user) — never a silent mapping to an action-capable class. *(Violated: intent_classifier.py `_defaulted` → CO_AUTHORING.)*
- **I-A3 (Governed effects).** Side effects only through a declared capability with `authority_class`; every governed effect emits a receipt keyed to trace_id. *(Exists: WriteGuard + SettingsWriteReceipt + panel descriptors — extend to all executors.)*
- **I-A4 (Bounded execution).** depth ≤ 2, per-step retries ≤ budget, AND a per-plan wall-clock timeout (missing today: orchestrator v2 has per-step only).
- **I-A5 (Bounded context).** Agents consume `ContextEnvelope` only; no raw vault/index access; denied scopes are content-free. *(Exists in yggdrasil_runtime + invariant 18/19 — promote to `app/` runtime; aligns with #2025 admissibility slice.)*

### Schema compliance rules
- **I-C1 (Versioned payloads).** Every persisted JSON payload carries `schema_version`; schemas are closed (`additionalProperties: false`) with an `extensions` object as the only open point. *(Exists in schemas/ contracts; absent in app/ persistence.)*
- **I-C2 (Evolution protocol).** Within a major version: additive-optional only. Semantic change ⇒ new version + backfill job + dual-read window + doctor check for stragglers. Never in-place meaning change of an existing field.
- **I-C3 (One authority per schema).** JSON Schema files under `schemas/` are canonical; pydantic models are checked against them by a GATE drift test (generate-or-compare). Prompt contracts (`docs/settings/prompts/*.v1.md`) stay descriptive mirrors of code constants — but each prompt version pins the output schema version it produces.

### RQ6 — minimal invariant kernel
Traceability = **I-D1 + I-E5** (every artifact names its origin and transform; every event is typed).
Replayability = **I-S2 + I-E1 + I-E2 + I-E3** (atomic state+event, deterministic dedup, idempotent handlers, ack-last).
State-transition correctness = **I-A2 + I-A3 + I-C1** (no default routes, gated effects with receipts, versioned payloads).
Everything else is defense in depth; these nine are the kernel.

---

## 3. Decomposition Model Redesign

One task model for both planes (runtime plans and builder issue-sets). This generalizes the repo's existing `Verify:` marker discipline into a graph contract.

### 3.1 Graph structure

```
Plan := DAG<TaskNode>          # cycle check at admission, not execution
TaskNode :=
  task_id:            str            # stable, deterministic within plan
  parent_id:          str | null
  kind:               deterministic | llm_transform | governed_effect | verification | human_gate
  input_contract:     schema_ref     # registered schema the node consumes
  output_contract:    schema_ref     # registered schema the node produces
  verify:             executable_ref # test path, doctor check, receipt query — never prose
  idempotency_key:    str            # derived: sha256(task_id ‖ input_hash)
  budget:             {retries: int, timeout_s: int, tokens: int | null}
  failure_policy:     retry | dead_letter | compensate(ref) | escalate(tier)
  provenance:         {trace_id, derived_from: [task_id], created_by}
```

### 3.2 Structural rules (checked at plan admission — deterministic, no LLM)

- **R1:** every `llm_transform` node has ≥1 successor `verification` node validating its `output_contract` before any consumer runs. (LLM proposes; code disposes.)
- **R2:** every `governed_effect` node is preceded by an authority check (capability + tier from the panel-action register) and succeeded by a receipt-emission check.
- **R3:** a plan is admissible iff all leaf nodes have resolvable `verify` targets — the runtime analogue of "ACs without `Verify:` are not `agent:ready`".
- **R4:** `Σ budgets ≤ plan budget`; plan carries its own wall-clock timeout (fixes the per-step-only gap).
- **R5:** `output_contract` of an edge's source = `input_contract` of its target — schema drift becomes a plan-admission error, not a runtime surprise.

### 3.3 Failure handling model

| Failure | Action |
|---|---|
| Transient (I/O, 5xx, DB connect) | retry within `budget.retries`, exponential backoff; row/task stays pending (at-least-once) |
| Contract violation (output fails `verification`) | one bounded re-ask with the validation error appended; second failure → `dead_letter` with `schema_violation` |
| Budget exhausted | `failure_policy` fires: dead-letter (audit + health signal per I-E4), compensate (registered inverse), or escalate (tier per proportional-governance: Act / agent-review / ask-you) |
| Upstream node dead-lettered | dependent subtree cancelled with reason; plan result = `partial` with explicit residue, never silent success |

### 3.4 Why this reduces drift
Schema drift is caught at three progressively cheaper points: plan admission (R5), post-LLM verification (R1), persistence validation (I-E5/I-C1). Traceability is free: `trace_id` + `derived_from` chains reconstruct execution without log archaeology. Decomposition quality becomes measurable (see §5 rubric).

---

## 4. Agent Role Architecture (runtime plane)

Roles aligned 1:1 with SBS L2 boundaries so responsibility overlap is structurally impossible. All inter-agent traffic uses the existing `AgentRequest/AgentResponse/AgentError` envelope (`app/a2a/schema.py`) with `payload` validated against the intent's registered schema (I-E5 applied to A2A).

| Agent | SBS home | Input contract | Output contract | LLM? | Allowed effects |
|---|---|---|---|---|---|
| **Ingestor** | PDM | filesystem events | `ingest.object.*` events (typed) + `store_objects` rows | no | DB write (objects/file_state/outbox, one tx); vault write only uuid-heal via WriteGuard |
| **Transformer** | DRI | `index.embedding.requested` (typed) | `store_vector_index` rows + `index.embedding.created/failed` | embed only | vector index upsert; nothing else |
| **Retriever** | RCA | typed query + active scope | `RetrievalResult` (schema-validated, prefiltered) | no | none (read-only) |
| **Router** | CAO | raw user utterance | `IntentClassification` schema incl. `UNKNOWN` | yes (constrained decoding) | none — classification is never an effect |
| **Synthesizer** | CAO | `ContextEnvelope` only | prose (terminal) + typed `ChangeProposal`s | yes | none directly; proposals only |
| **Executor** | EXE | typed `ChangeProposal` + authority token | receipts + mutation events | no | vault/DB writes via WriteGuard + capability register; the ONLY agent with governed-effect rights |
| **Doctor/Verifier** | OEF | none (scheduled) / verify refs | typed diagnosis + health-contract inputs | no | none (read-only; repairs are proposals to Executor) |

Constraints:
- **Non-overlap:** exactly one agent per effect class. Today's `handle_ingest_object_created` doing embed inline (indexer.py:106-113) violates Ingestor/Transformer separation — route through the `INDEX_EMBEDDING_REQUESTED` event exclusively.
- **Typed communication:** free text exists on exactly two edges: user→Router (inbound) and Synthesizer→user (outbound). Every other edge is schema-validated.
- **Side-effect funnel:** WriteGuard + receipt emission live in Executor only; adding a capability = registering a descriptor (capability_class, authority_class, tier), never adding a write path.
- **RQ7 (granularity criterion):** split agents where **authority class changes** (read / propose / effect) or **failure isolation is needed** (LLM vs deterministic); merge everywhere else. Finer splits than authority boundaries add coordination cost with no correctness gain; coarser ones collapse the governance model. Seven roles is the fixed point for this system.

Builder plane: keep the existing four roles (coordinator / implementer / maintainer / closer, `docs/development/BUILDER_SUBAGENT_ROLES.md`) — they already satisfy the authority-boundary criterion. The one addition: handoff receipts adopt the TaskNode `verify` field so builder ACs and runtime plan nodes share one verification vocabulary.

---

## 5. Evaluation System Design

Three layers; each answers RQ4 differently because ground truth differs by layer.

### 5.1 L0 — Structural correctness (deterministic, free, PR-gating)
- Every recorded output (outbox payloads, stored payloads, LLM boundary outputs captured in receipts) validated against its registered schema. Ground truth = the schema itself.
- Runner: extend `python -m app.eval.run` with a `structural` mode: sample N recent rows per table/topic (or replay fixtures in CI), emit violations into the scorecard.
- Idempotency harness (I-E2) and dispatch-twice diff run here.

### 5.2 L1 — Behavioral golden sets (deterministic, PR-gating)
Dataset structure — one case schema per capability, all following `retrieval_eval_case.v1`'s shape:

```yaml
# classification_case.v1  (NEW — highest-value gap)
id: cls-0001
utterance: "markera den här som mogen"        # bilingual, like retrieval seed
context: {surface: canvas, note_state: draft}
expected_intent: governance_bearing
expected_action_type: maturity_transition
acceptable: [governance_bearing]               # UNKNOWN counts as safe-fail, scored separately
```

- **Scoring rubric:** per-class precision/recall + confusion matrix; hard gate: `P(action-capable class | expected UNKNOWN/exploratory) = 0` — mutation-side confusion is a blocking regression, read-side confusion is a threshold.
- Retrieval: grow the 11-case seed via the production-capture loop (below); raise floors stepwise (0.15 → 0.35 precision@5) as the corpus grows — thresholds live in `config/eval_thresholds.yaml` as today.
- **Decomposition quality score (for §3):** over a golden set of planning requests — plan admission rate (R1–R5 pass), verify-executability rate, replan rate, budget-overrun rate. Ground truth = the structural rules, not human labels.

### 5.3 L2 — Semantic quality (LLM-judge, nightly, non-blocking → trend-tracked)
- Keep DeepEval/Ragas opt-in suites; make them *useful* by pinning judge model + prompt version in the scorecard so trends are comparable.
- **Model comparison:** formalize `app/eval/benchmark.py` into `eval compare --baseline <scorecard.json> --candidate <scorecard.json>` → per-slice deltas + verdict. Any model/prompt swap for Router or Synthesizer requires a compare artifact attached to the PR. Ground truth = the frozen baseline scorecard.

### 5.4 Production-capture loop (ground truth generation)
Every dead-letter with `schema_violation`, every `UNKNOWN` classification, and every operator correction is automatically drafted as an eval case (companion-note artifact, human-confirmed via review queue). This converts failures into permanent regression tests — the only sustainable answer to RQ4 in a probabilistic system: *ground truth is accumulated adjudicated history, not a priori labels.*

### 5.5 Automation
- L0 + L1 in the `not pg` PR gate (both are offline/deterministic — same class as the existing runner).
- L2 nightly via dispatch (like ir-v1-uat).
- Harness self-verification: extend `harness-selfverify.yml` with an intentional schema-violation fixture that MUST fail L0 — the verify-the-verifier rule applied to this framework.

---

## 6. Highest-Leverage Intervention Points

### Replace LLM with deterministic logic (currently none misplaced — keep it that way)
- Chunking, dedup, routing-on-typed-data, ranking arithmetic, state transitions, admissibility gates: already/must-stay deterministic. The standing decision (LLM-classification-over-heuristics, gate stays deterministic) is correct — do not regress into keyword heuristics, and do not let LLMs into gates.

### Keep LLM but strengthen (RQ5 boundary rule)
**Criterion: an LLM is justified iff the function is semantic interpretation over unbounded natural language; everything downstream of a typed value is code.** "LLM decides meaning; code decides consequences."
1. **Router/intent classifier** — constrained decoding + `UNKNOWN` + classification_case.v1 gate. Single highest-leverage LLM fix in the system: it gates mutations.
2. **Planner** — schema-validated plan output + admission rules R1–R5.
3. **Embeddings** — already well-governed (identity, gate, reconcile); add content_hash provenance (I-D1) to make re-embedding incremental and auditable.

### Pipeline redesign for maximum entropy reduction (ordered)
1. **Collapse to one retrieval truth** (CW-1): retrieval serves from `store_vector_index` (cache-through allowed, truth single); JSONL demoted to pure audit; delete `app/store/*` legacy generation and the Alembic `embeddings` table. Removes an entire class of divergence permanently.
2. **Transactional outbox** (CW-3): makes the event log trustworthy; unlocks replay, backfill, and honest metrics.
3. **Typed boundaries everywhere** (CW-2/CW-4): schema registry + constrained decoding moves the yggdrasil formal model into the live runtime — closing the two-type-systems split.

---

## 7. Minimal Implementation Backlog

Grouped by dependency order. Each converts to one Issue via feature-breakdown; ACs shown are the `Verify:`-able kernel. Existing-issue overlaps flagged so the backlog reconciles instead of duplicating (#2314 epic, #2025, #2324).

### Phase 0 — Truth substrate (no new features until these land)
- **T1. Transactional outbox in vault sync.** `sync_markdown` and `handle_rename` wrap objects+file_state+outbox in one transaction.
  AC: crash-injection test between steps shows all-or-nothing; `Verify:` tests/integration/test_vault_sync_atomicity.py.
- **T2. Mandatory deterministic idempotency keys.** `write_outbox_event` signature requires key; producers derive `sha256(topic‖source_id‖content_hash)`.
  AC: duplicate-emit test shows single row; no callsite passes None. `Verify:` grep-gate + tests/services/test_outbox_idempotency.py.
- **T3. Single store generation, fail-loud resolution.** Delete `app/store/object_store.py` + `app/store/vector_store.py` writers; memory backend only via explicit env; probe failure with PG configured is fatal.
  AC: import-boundary test lists exactly one writer per table (I-S1); startup test with unreachable PG + no override exits non-zero.
- **T4. Store DDL into Alembic.** `store_*` + `vector_index_meta` migrated; `_ensure_tables` becomes assert-only outside tests.
  AC: fresh-DB migration produces identical schema (pg_dump diff = ∅); `Verify:` tests/migrations/test_store_schema_parity.py.

### Phase 1 — Single retrieval truth (extends #2314; supersedes its W5 framing where conflicting)
- **T5. Retrieval reads durable index.** In-memory hybrid store becomes cache-through of `store_vector_index`; JSONL fan-in (`app/index/outbox.py:45-67`) removed as a truth path.
  AC: kill-and-restart test — retrieval results identical before/after restart; doctor reports 0 retrieval-vs-index divergence.
- **T6. Transform provenance stamp (I-D1).** Every vector row gains `{content_hash, chunk_policy_version, pipeline_version}`; index doctor gains staleness check (`content_hash ≠ current` ⇒ re-embed candidate). Extends #2324 completeness work.
  AC: doctor `--coverage` lists stale rows; reconcile re-embeds only stale rows (incremental proof on fixture vault).

### Phase 2 — Typed boundaries
- **T7. Structured-output enforcement + UNKNOWN route.** Shared `constrained_completion(schema_ref)` util (Ollama format/json-schema; provider tool-call); intent classifier migrated; `UNKNOWN` surfaced (read-only degrade + user re-ask), CO_AUTHORING default removed.
  AC: fuzz test with garbage LLM stub yields UNKNOWN never a route; `Verify:` tests/chat/test_intent_unknown_route.py.
- **T8. Topic schema registry (I-E5).** `schemas/events/<topic>.v1.schema.json` per registered topic; validation at write + dispatch; violation → immediate dead-letter with reason.
  AC: registry covers 100% of dispatch table topics (worker line 253-301); malformed-payload test dead-letters without handler invocation.
- **T9. Plan admission validation (R1–R5).** Planner output schema-validated; DAG/budget/verify-executability checks; plan-level timeout added.
  AC: invalid-plan fixtures rejected at admission with typed reasons; long-plan fixture killed by plan timeout not step timeout.

### Phase 3 — Invariants into the runtime
- **T10. Admissibility + envelope enforcement in `app/`** (delivers #2025): agents consume ContextEnvelope; four-axis predicate enforced; converts invariants 5/6/18/19/21 from xfail/static to runtime.
  AC: the three tests/evals runtime skeletons (general-knowledge / rpg / private) pass un-xfailed against app runtime.
- **T11. Idempotency harness (I-E2).** Dispatch-every-topic-twice diff harness in `not pg` gate.
  AC: harness enumerates dispatch table dynamically (new topic without fixture = failure — no silent cap).
- **T12. Dead-letter + queue-depth in health contract (I-E4).** `dead_lettered_count`, `oldest_undelivered_age` feed `DEFAULT_CONTRACT.evaluate()`; threshold breach visible on health surface.
  AC: injected dead-letter flips health within one worker tick; UAT asserts surfacing.

### Phase 4 — Evaluation hardening
- **T13. classification_case.v1 golden set + gate.** ≥40 bilingual cases incl. adversarial (governance phrased as chat); mutation-side-confusion = blocking.
  AC: runner emits confusion matrix into scorecard; PR gate wired.
- **T14. Scorecard compare runner.** `eval compare` baseline-vs-candidate with per-slice deltas; required artifact for Router/Synthesizer model or prompt-version changes.
  AC: fixture pair produces deterministic verdict; prompt-contract docs reference the pinned output schema version (I-C3).
- **T15. Production-capture loop.** Dead-letters + UNKNOWNs drafted as eval-case candidates into a review queue (companion-note artifact, human-confirmed).
  AC: injected schema-violation dead-letter appears as draft case with full provenance.

Dependency spine: T1–T4 → T5–T6 → T7–T9 → T10–T12 → T13–T15. T7 and T13 pair (build + measure). Nothing in Phase ≥1 is safe to verify without Phase 0's honest substrate — evals over a silently-diverging store measure noise.

---

## Research Question Resolutions (summary)

- **RQ1 (correctness conditions):** consistency over time = single truth per concept (I-S1/I-D3) + atomic state+event (I-S2) + deterministic replay (I-E1/2/3) + recorded transform provenance (I-D1). LLM mediation is safe iff its outputs are validated artifacts with provenance, never in-band control text.
- **RQ2 (scaling failure):** multi-agent systems fail at *untyped handoffs* and *silent defaults* — exactly CW-2. Coordination overhead is secondary to the fact that one agent's unparsed prose becomes another agent's action. Fix the edges, not the agents.
- **RQ3 (schema stability):** producers pin `schema_version` per output (prompt version ↔ schema version bound, I-C3); consumers validate closed schemas; evolution is additive-within-major + backfill + doctor (I-C2). LLMs never see or emit unversioned structures.
- **RQ4 (ground truth):** layered — schemas (structural), adjudicated golden sets (behavioral), frozen baseline scorecards (comparative), and accumulated production adjudications (T15). In a probabilistic system, ground truth is *curated history*, not oracle labels.
- **RQ5 (determinism boundary):** LLM iff the function's domain is unbounded natural language and the output is meaning; deterministic iff the domain is closed/typed. Gates, routes-on-typed-data, arithmetic, and state transitions are always code.
- **RQ6 (invariant minimality):** the nine-invariant kernel in §2 (I-D1, I-E5 / I-S2, I-E1, I-E2, I-E3 / I-A2, I-A3, I-C1).
- **RQ7 (agent granularity):** split on authority-class change and LLM/deterministic failure isolation; merge otherwise. Seven runtime roles + four builder roles is the fixed point.
