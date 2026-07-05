---
kind: research_audit
title: Mimer × Fable 5 — Field Scan, Inspiration & Gap Analysis
status: Draft (advisory research, 2026-07-05)
authority: Advisory. Surveys what others build with Fable 5 and coding agents in our space, and maps the ideas onto gaps in Mimer's system and roadmap. Claims no shipped reality of its own; every recommendation is a proposal for owner review. Owner docs, the SBS, and ADRs win on all matters of record.
owner: Architecture / product (Rasmus)
temporal_class: strategic
review_cadence: event-driven
source_of_truth: mixed — cites Mimer code (`path:line`) and external sources (URLs)
---

State: Draft (advisory research, 2026-07-05). Field scan + gap analysis; claims no shipped reality of its own; every recommendation is a proposal for owner review.

# Mimer × Fable 5 — Field Scan, Inspiration & Gap Analysis

**Date:** 2026-07-05
**Purpose:** Not a name-audit and not a rebuild plan. This surveys **what people are building with Claude Fable 5 and other coding agents for "second brain" / agentic-PKM systems**, then asks one question of each pattern: *do we have this, and if not, where is the gap in our system or roadmap?* The output is inspiration + a prioritised gap list, grounded on one side in real external sources and on the other in Mimer's real code.

**Guardrail:** *reduce friction, not intelligence.* Every recommendation is a **harden-or-compose** of existing architecture, never a rebuild; at most one targeted mechanical refactor. Nothing here adopts A2A/AGNTCY, a third-party memory vendor, or an external durable-execution engine (the standing don't-touch list). Where a compelling external pattern collides with an invariant, it is surfaced as a **Decision** (§IX), not silently taken.

> *Naming footnote (stated once, then dropped): the handover's "Mimer" ≈ our current knowledge-surface module (retrieval seam = `app/retrieval/`), and "Heimdal" ≈ the proactivity/orchestration concern owned by the agent-runtime layer + the Contextual Relevance Engine. The exact Norse register (Mimer→Munin, Heimdall=sensor) is settled in ADR-0043 and irrelevant to this document's purpose. I use the plain capability names below.*

---

## 0. Executive summary

**The field validates our direction and exposes our moat.** Across the whole "LLM-Wiki / second-brain" ecosystem that has grown up around Claude Code and Fable 5 in 2025–2026 (brain.md, claude-obsidian, NicholasSpisak/second-brain, the two repos in the handover, mem0, Letta), the shared design is *markdown canonical, index disposable* — exactly ours. But almost all of them **auto-write to the knowledge base with no human gate.** Mimer's WriteGuard + typed grants + decision-receipts are, against this field, a genuine differentiator, not overhead. The most rigorous external work (`memorywire`, SSGM, the "silent memory pollution" result) is *converging toward* the gate we already have.

So the honest finding is not "we're behind." It's: **we're ahead on governance and thin on three things the field does well.** In rough priority:

| # | Gap (what the field does, we don't) | Where it lands | Effort |
|---|---|---|---|
| **G1** | **Durable retrieval is built-but-dormant** — pgvector index exists, live path is an in-memory cache; the two are disconnected (`app/retrieval/hybrid.py:212`, ADR-0024, epic #2314) | Retrieval seam | 1 targeted refactor |
| **G2** | **Synthesis capabilities** — contradiction-callouts with sourced citations, a vault-health "lint" (orphans/dead-links/gaps), gap-fill research. The field's "connect" and "create" stages; we're strong at capture/curate | New builder/curation passes (Deep-Agent, read-only) | Medium, additive |
| **G3** | **Swedish embeddings** — we run `nomic-embed-text` (English-centric, `docs/EMBEDDINGS.md:56`); the field's self-hostable multilingual default is **BGE-M3** (Swedish + dense+sparse in one model) | Embedding config | Benchmark + re-index |
| **G4** | **Proactive loop wastes reasoning** — our relevance tick has no state-diff, so it reasons on unchanged state; the field's "heartbeat" only reasons on a delta | Relevance tick (`app/watcher/relevance_tick.py`) | Small, additive |
| **G5** | **Retrieval tuning is unset** — rerank off by default, no RRF, no published defaults; the field has concrete numbers (RRF k=60, retrieve ~500/rerank ~100, rerank *conditionally*) | Retrieval config | Small |
| **G6** | **No session hot-cache** — the field's cheap "hot.md" recent-context primitive; we assemble context fresh each time | Context assembly | Small, additive |

**Two things to *not* do**, learned from the field:
- **Don't chase "no embeddings."** The Karpathy "LLM-Wiki" maximalist claim ("LLMs don't need embeddings over well-organized markdown") is overstated — even its flagship implementation keeps BM25 + cosine rerank. It's a *cheap tier for tiny vaults*, not a replacement.
- **Don't adopt async memory writes.** mem0 and others default to async for throughput; the "silent memory pollution" result (arXiv 2603.23064) shows async writes are a contamination vector. Our synchronous, gated posture is *correct* — keep it.

**A cost reframing (§VIII):** runtime cognition in Mimer is **local** (router serves `ollama/openai/deepseek/mock`, default ollama — `app/components/llm/router.py:41`; no Anthropic chat provider is wired). So "Fable 5 vs Opus" is a **builder/curation-layer** question, not a runtime one. Fable 5's own profile (great at long-horizon investigation; *bad at* writing clarity, design, and multi-agent orchestration — Lenny's Newsletter) argues for using it sparingly and never by default — matching our standing model-routing policy.

---

## I. What the field is doing (the scan)

Patterns worth stealing or reacting to, grouped by theme. Each is tagged with our position: **✅ have · ◐ partial · ✗ gap**.

### Memory architecture
- **Compiled-truth + append-only timeline** (`brain.md`, mindmuxai). Each page has a rewritable `compiled_truth` *and* an append-only `timeline`; `update-truth` rewrites the truth and appends evidence in one atomic write — "the understanding can never change without a trace." One CLI is the exclusive writer. → **✅ have** (this independently validates our decision-receipt-log design: readable surface canonical + immutable evidence chain; slices #2970–#2973). Worth mining its `create-page / update-truth / append-timeline` CLI as a reference contract.
- **Tiered memory with explicit promotion** (Letta: core / archival / recall). The agent *decides* via function calls what stays in-context vs. archived. → **◐ partial** — maps onto our hot-cache / vault / pgvector layering, but promotion in ours is not an explicit agent decision surface. The insight: promotion is a natural human-in-the-loop gate point.
- **Five-operation memory: store / retrieve / update / compress / forget** (2026 consensus). Most systems build only store+retrieve; "that's where the failures accumulate." Append-only logs specifically rot: "the old version and the new version coexist and the agent has to guess which is current." → **caution for our receipt log:** the log needs a compaction/projection story (we have it via PG projection) or retrieval degrades. Backs keeping the readable surface canonical and the log as *evidence*, not the query path.
- **Event-/decay-based forgetting** (arXiv 2604.02280, 2605.10870). The literature is mostly TTL/age-based decay; the harder open problem is *staleness in high-relevance memories*. → **✅ ahead** — our **event-triggered relevance decay** (value lost at a triggering event, e.g. a grocery list after shopping) is genuinely less common than the field's TTL model and is defensible as differentiated. The "Remember the Decision, Not the Description" rate-distortion paper is on-theme for our compaction slice.

### Retrieval
- **Hybrid → RRF → cross-encoder rerank** as the 2026 minimum baseline, with cite-able defaults: **RRF k=60** (drop to 30–40 for top-1 precision), retrieve **~500/mode**, rerank **top ~100**; **reranking *hurts* on simple keyword queries** so apply it conditionally; instruction-following rerankers (Voyage rerank-2.5) are new. → **◐ partial** — we ship trust-weighted linear fusion (`0.5·BM25+0.4·emb+0.1·overlap`, `app/retrieval/hybrid.py:433`) but **no RRF and rerank is off by default** (`docs/RETRIEVAL.md:71`). We have knobs and no tuned values. **G5.**
- **Consent-gated retrieval egress** (claude-obsidian `wiki-retrieve`): BM25 always-on + optional contextual-prefix that phones an API **behind an `--allow-egress` flag** + local cosine rerank via Ollama by default; reports +32pp top-1, +41% error reduction on a 50-query benchmark. → **✅ aligns** — this *is* our low-trust posture (Ollama-primary, Gemini fallback is explicit — ADR-0023). claude-obsidian is the closest architectural neighbor to us; worth a deep read.
- **Hot-cache + index + log hierarchy** (claude-obsidian: `hot.md` ~500-word recent-context cache, `index.md` catalog, `log.md` append-only ops). Read in order to stay token-cheap before touching page bodies. → **✗ gap (G6)** — a cheap session-memory primitive we don't have.
- **"No embeddings" LLM-Wiki** (Karpathy, Apr 2026). Structure + long-context reading over well-organized markdown, instead of RAG. → **react, don't adopt** — overstated (the reference impl keeps BM25+cosine); useful only as a cheap tier for a small vault.

### Proactivity & cadence
- **Ambient / post-prompting assistants** surface drafts/flags *before* being asked, with a **user-controlled quiet mode** ("stays quietly in the background until needed"). → **◐ partial** — our Contextual Relevance Engine is already headed here (#1960/#1972); the framing to steal is *proactivity is a dial, not default-loud*. **HYPE flag:** most consumer products here (Qira, Poppy) are press-release vaporware — directional only.
- **Capture → Curate → Connect → Create** (MindStudio; this is the real "Four C's" — the brief's version was wrong). "Curate is where Claude earns its place"; "individual notes are low-value, the signal is in the connections"; "a second brain that never produces anything is just an archive." → **✗ gap (G2)** — we're solid on capture/curate; **connect** and **create** are thin. Their active/reference/archive tiers map onto our hot/vault/archive.

### Skills & progressive disclosure
- **Progressive disclosure** (coleam00/second-brain-skills): "metadata always in context, body when triggered, resources as needed; only add context Claude doesn't already have." → **✅ have** — this is our `.codex/skills/` contract. The crisp rule ("don't put in a skill what the model already knows") is a good trimming lens.
- **Skill-per-verb PKM decomposition** (claude-obsidian: 15 skills — `wiki-ingest/query/lint/retrieve/mode`, `autoresearch`, `canvas`, `think`; **per-file advisory locking** for multi-writer safety). → **✗ two gaps:** `wiki-lint` health auditor (**G2**) and **per-file advisory locking** — a concrete answer to our "concurrent agents thrash the worktree" problem.

### Integrations & safety
- **Structured-diff write gate** (`memorywire`, arXiv 2606.01138): compute a structured diff between the proposed write and current state, show it to a human, commit only on approval; gate **mutations only** (remember/forget/merge), leave reads/expiry ungated; HITL for *validation*, not blanket blocking. → **✅ have, can sharpen** — near-exact formalization of WriteGuard. Two refinements: (a) gate on a **reviewable diff**, not the raw write; (b) scope the gate to mutations. Canonical LangGraph `interrupt()`/approval-node patterns exist — adopt rather than invent.
- **Governed evolving memory & silent pollution** (SSGM arXiv 2603.11768; pollution arXiv 2603.23064). Async/background memory writes enable "silent memory pollution." → **✅ vindicates us** — argues *against* the field's async-by-default; keep writes synchronous-and-gated.
- **MCP as lazy tool-loading** (schemas load on demand). → **✅ aligns** with our deferred-tool posture; external MCP = egress, so directional only for a local vault.

### Knowledge graph & synthesis
- **Auto-generated wiki graph with sourced contradiction callouts** (claude-obsidian `/wiki-ingest`: creates 8–15 interlinked pages, cross-references against every existing page, flags contradictions with `[!contradiction]` callouts + citations). "The LLM is the librarian. You're the curator." → **✗ gap (G2)** — contradiction detection with sourced callouts fits our low-trust ethos perfectly (surface + cite + human adjudicates). **Positioning:** these systems *auto-write freely with no gate* — our differentiator over the entire ecosystem is write-gating + receipts.
- **Autonomous gap-fill research loop** (claude-obsidian `autoresearch`, 3 rounds). → **◐ partial** — this is the "Expansion" half of our maintenance-vs-expansion split (built-but-dormant, gated behind explicit invocation — a model we already chose).

### Multilingual (Swedish)
- **BGE-M3 as the self-hostable multilingual default** — 100+ languages incl. Swedish, **dense + sparse + multi-vector in one model**, 8192-token docs. multilingual-E5-large (1024-dim) and Qwen3-Embedding as alternatives. → **✗ gap (G3)** — **BGE-M3 is the standout for us**: Ollama-hostable, covers Swedish, and its built-in **sparse output pairs natively with our hybrid BM25+dense design** (lexical + dense from one model). **Honest caveat:** no source has *Swedish-specific* retrieval numbers — leaderboards won't answer the Swedish question, so we must run our own small eval.

---

## II. Gap-analysis matrix (system + roadmap)

Consolidated view: each field pattern → our status → the concrete gap → where it lands.

| Field pattern | Our status | Gap | System / roadmap location |
|---|---|---|---|
| Markdown canonical, index disposable | ✅ | — | vault is sole canonical store |
| Human write-gate on knowledge base | ✅ **(moat)** | field mostly lacks it | `app/write_guard.py`, `docs/PANEL_AGENT.md:178-189` |
| Compiled-truth + append-only evidence | ✅ | — (validated by brain.md) | decision-receipt log #2970–#2973 |
| Event-triggered decay | ✅ ahead | — | event-triggered relevance decay note |
| Durable vector serving | ◐ built, **dormant** | **G1** connect pgvector → serving | `app/stores/pg.py:447`; ADR-0024; **#2314** |
| Hybrid + RRF + conditional rerank | ◐ linear fusion only | **G5** add RRF, tune, gate rerank | `app/retrieval/hybrid.py:433`; `docs/RETRIEVAL.md:71` |
| Multilingual embeddings (Swedish) | ✗ English-centric model | **G3** benchmark → BGE-M3 | `docs/EMBEDDINGS.md:56`; ADR-0023 |
| Contradiction-callouts (sourced) | ✗ | **G2** curation pass → Panel proposals | Deep-Agent read-only (`ROADMAP.md:256-288`) |
| Vault-health "lint" (orphans/gaps) | ✗ | **G2** health auditor skill | builder skill; fitness-function culture |
| Connect/Create synthesis | ◐ thin | **G2** synthesis capability | maintenance-vs-expansion (Expansion) |
| Proactive state-diffing | ✗ | **G4** diff before reasoning | `app/watcher/relevance_tick.py` |
| Dialable proactivity + tiers | ◐ | **G4** tiers → proportional governance | reach-out/scarcity gate; #1881 |
| Session hot-cache | ✗ | **G6** recent-context primitive | context assembly seam |
| Per-file advisory locking | ✗ | concurrency safety | addresses worktree-thrash |
| Structured-diff HITL gate | ✅, sharpenable | gate on diff, mutations-only | WriteGuard + LangGraph `interrupt()` |
| Progressive-disclosure skills | ✅ | trim per "don't add what model knows" | `.codex/skills/` |
| Async memory writes | ✗ (deliberately) | **keep gated** — pollution risk | invariant posture |

---

## III. Retrieval — closing G1 + G5

**G1 (the one targeted refactor): connect durable pgvector to the serving path.** Live retrieval reads an in-memory store rebuilt once per process (`app/retrieval/hybrid.py:212`); the durable pgvector index is written at ingest but never read at query time (ADR-0024:17, epic #2314). This is "index is a disposable projection of markdown" done *incompletely*. Finish the cache-through so pgvector is authority and the in-memory store is a warm cache with explicit invalidation. No new backend, no qmd. *(Builder model: Sonnet — mechanical.)*

**G5: adopt the field's hybrid-retrieval defaults, as tunable config, not hard-coded.**
- Add **RRF fusion (k=60)** as an option alongside the current linear fusion; the field notes RRF needs no score normalization and beats either mode alone (WANDS: RRF 0.7068 vs BM25 0.6983 / KNN 0.6953). Keep our trust-weighting available — RRF and trust-weighting are both selectable, decided by the Swedish benchmark.
- **Make reranking conditional**, not just off/on: the field is explicit that rerank *hurts* simple keyword queries but adds +39.7% MRR@3 on hard ones. Gate rerank on query shape. Our rerank seam already exists (`maybe_rerank`, `docs/RETRIEVAL.md:71`).
- Retrieve **~500/mode, rerank ~100** as starting sizes.
**Invariant guard:** none of this may bypass the scope prefilter that runs *before* ranking (`app/retrieval/hybrid.py:459-480`) or upgrade evidence-role (`:39-50`). Fusion changes ordering, never eligibility.

---

## IV. Proactivity — closing G4

Our proactive loop already exists and is governed: a scheduled relevance tick materializes moments through WriteGuard, each with a receipt; `GET /api/companion/now` surfaces them read-only; OS-send is deferred (`app/relevance/`, `app/watcher/relevance_tick.py`, `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md:53`). Two additive improvements from the field:

1. **State-diff the tick (the real cost lever).** The field's "heartbeat" saving is not "poll cheaply" — it's *only reason on a delta* (`build_snapshot → diff → reason over delta only`). Add a snapshot-diff gate so the expensive relevance evaluation fires only when relevance-relevant state changed; persist snapshot state. Cuts reasoning frequency and receipt/attention churn without weakening scarcity. **G4.** *(Sonnet.)*
2. **Bind proactivity tiers to our proportional-governance ladder — don't add a parallel system.** The field's Observer/Advisor/Assistant/Partner is a re-derivation of our Act / agent-review / ask-you (#1881):

   | Field tier | Our binding |
   |---|---|
   | Observer (notify) | read-only moment at `/api/companion/now` |
   | Advisor (draft) | Panel proposal / unchecked checkbox — WriteGuard-gated |
   | Assistant (act on reversible, ask for external) | proportional-governance "Act" tier |
   | Partner (send low-risk, ask for irreversible) | **typed CrossScopeFlow grant** + `confirmation_required` + `audit_required`, never a boolean |

   The "Partner" tier is exactly where an external design smuggles in a global "just do it" flag. Bind it to a typed grant (`docs/architecture/cross-scope-flow.md:33-52`). **Decision (§IX).** Also adopt the consumer framing: **proactivity is a dial with a quiet mode**, not default-loud.

---

## V. Synthesis — closing G2 (the biggest capability gap)

This is where the field is genuinely richer than us, and where Fable 5's strength (dense multi-page reasoning in one chain) actually earns its cost — **as a read-only builder/curation pass, never in the runtime write path.** Three capabilities to add, all as *proposals into the Panel/WriteGuard loop* so the human adjudicates:

1. **Contradiction-callouts with sourced citations.** A curation pass cross-references a note against the vault and emits `[!contradiction]`-style candidates *with evidence links* into Panel; the human confirms via checkbox. Fits low-trust exactly: surface + cite, never auto-resolve. This is the readable-surface analogue of our receipt design. Maps to the Deep-Agent read-only phase (`docs/ROADMAP.md:256-288`, "Deep Agents cannot execute or mutate"). *(Fable 5 for the pass; proposals only.)*
2. **Vault-health "lint" auditor** — orphans, dead links, knowledge gaps, stale claims (claude-obsidian's 8-category check). A natural fit for our fitness-function culture; ship as a builder skill first. *(Sonnet.)*
3. **Connect/Create scaffolding** — the field's point that "connect" (surfacing non-obvious links) and "create" (producing synthesized outputs) are where PKMs die as archives. This is our dormant "Expansion" half; the field confirms the sequencing (gate behind explicit invocation). *(Design first; not a build yet.)*

**Positioning to hold onto:** the entire LLM-Wiki ecosystem does 1–3 by *auto-writing*. Our version does them by *proposing*. That is the differentiator — don't let a synthesis feature quietly acquire write authority.

---

## VI. Roadmap gaps

Mapping the above onto the real repo roadmap (`docs/ROADMAP.md`: Phase 0 Stabilisation → Phase 1 v6.0 structural separation → Phase 2 Deep Agents read-only → Phase 3 Panel integration → Phase 4–5 execution/governance):

- **Phase 0 / now:** G3 Swedish benchmark (eval only, no code change); G5 retrieval-tuning defaults (config); a one-time Fable-5 eval pass scoring proposal quality (offline).
- **Phase 1:** **G1 pgvector serving** (the targeted refactor, #2314); **G4 state-diff** the relevance tick; **G6 session hot-cache**; LangGraph checkpointing for PanelAgent (the safe half of "durable checkpoints" — no saver is documented, `docs/LANGGRAPH_AGENT_ARCHITECTURE.md:428-437`).
- **Phase 2 (Deep Agents, read-only):** **G2 contradiction-callouts + vault-lint** as read-only curation passes; formalize the **CLI-mediated integration contract** (LLM never holds credentials — the field's `query.py` pattern in our boundary language; the safe reading of "MCP-ify the vault," *not* an external memory vendor).
- **Phase 3 (Panel integration):** proactivity-tier binding to proportional governance + CrossScopeFlow (Opus — authority semantics); optional pre-flight guardrail-agent advisory check *before* the checkbox.
- **Cross-cutting, unscheduled:** **per-file advisory locking** for concurrent vault writes (answers the worktree-thrash learning); a **compaction/projection guarantee** for the receipt log so it doesn't rot (the "append-only rots" caution).

**Roadmap-level observation:** our roadmap is strong on *separation and governance* and light on *synthesis/expansion*. The field's clearest message is that capture+curate is solved and the value is in connect+create — which is precisely our dormant Expansion track. If there's a strategic gap, it's sequencing Expansion sooner, behind the gates we already designed.

---

## VII. Multilingual (Swedish) — closing G3

The multilingual risk is the *model*, not the architecture. We run `nomic-embed-text` (English-centric, `docs/EMBEDDINGS.md:56-57`), weighted 0.4 in fusion (`app/retrieval/hybrid.py:433`), so Swedish semantic recall trails. Swedish also stresses BM25 (compounding: *sjukvårdsförsäkring*; definite suffixes: *boken*) at the 0.5 lexical weight — needs Swedish-aware tokenization/stemming.

**Benchmark (eval, no code change), then decide:**

| Model | Dim | Fit | Migration cost |
|---|---|---|---|
| `nomic-embed-text` (current) | 768 | English-centric | — |
| **BGE-M3** | 1024 | **Swedish + dense+sparse in one; pairs with hybrid** | dim change → full re-index |
| `multilingual-e5-large` | 1024 | strong SV | dim change → full re-index |
| `EmbeddingGemma-300m` | 768 | dim-matched → **cheapest migration** | no dim change |

Metrics: SV-only, EN-only, and cross-lingual recall@k on a hand-labelled Niflheim query set, fusion held fixed. **BGE-M3 is the recommended target** (self-host, Swedish, and its native sparse output could *replace or complement* our separate BM25 stage — a structural simplification). **Guards:** (a) no public source has Swedish-specific numbers, so our eval is the decider; (b) any model change alters `EmbeddingIdentity` (`app/components/embeddings.py:30-35`) and forces a full re-index under the mixed-identity/reconcile discipline (ADR-0023) — a real cost to weigh against `EmbeddingGemma`'s cheaper dim-matched path. **Decision (§IX).**

---

## VIII. Cost & model economics

**Reframe first:** runtime cognition is local (`app/components/llm/router.py:41`, default ollama; no Anthropic chat provider). So the heartbeat "$0.05 vs $0.38" saving is a saving on cloud round-trips we don't pay — importing state-diffing (§IV) still helps (local compute + human attention + receipt churn), but the dollar headline is Repo B's, not ours. **The billed question is the builder/curation layer.**

**Fable 5 profile (durable numbers; Lenny's Newsletter + awesome-claude-fable-5):**
- **Pricing:** ~$10/M input, ~$50/M output; ~2× the token burn of other models; **90% discount with prompt caching.** *(Verify against current pricing before budgeting — these are reported figures.)*
- **Benchmark:** 80.3% SWE-Bench Pro (vs Opus 4.8 69.2%).
- **Good at:** long-horizon technical work, exhaustive investigation, vision/document parsing.
- **Bad at:** *writing clarity* ("technically complete but almost impossible to parse"), one-shot design, MVP scoping, and **multi-agent orchestration ("not yet reliable," frequent stalls).**

**When to invoke (decision tree, matches our TCD routing):**
```
Always-on runtime loop (tick, retrieval, panel exec)?  → local Ollama. Never a paid frontier model in the hot path.
Dev-time building Mimer?                                → Sonnet default; Opus for auth/migration; Fable only for hard architecture/adversarial.
Offline curation/eval pass over the vault?             → dense single-chain reasoning → Fable earns its premium; routine → Sonnet.
Drafting owner-facing docs?                             → NOT Fable (writing-clarity weakness bites our concise-docs preference).
```
At a ~100–500-note bilingual vault: runtime ≈ free (local); a *weekly* Fable-5 curation pass is a bounded, single-digit-dollar operation amortised over the week. Cheapest correct posture = **local runtime + occasional frontier curation** — already where we sit.

---

## IX. Decisions needed from Rasmus

### Owner rulings — 2026-07-05 (supersede the open questions below)

- **R1 — AI edits (G2): graduated.** *Mechanical hygiene* — misspellings, grammar, poor transcriptions, broken links — may be **auto-fixed** (reversible, non-semantic; maps to the proportional-governance "Act" tier). *Anything semantic* (contradictions, reorganization, meaning changes) is written by the **PanelAgent as suggestions/questions directly into the markdown note** (the `AI-åtgärder` checkbox surface, `docs/PANEL_AGENT.md:178-189`) — **no separate UI callout**; the human approves in the note. Implies a defined **auto-fix allowlist** vs **propose-in-Panel** everything else.
- **R2 — Swedish (G3): switch to BGE-M3 now** (no pre-benchmark). One-time full re-index under the mixed-identity/reconcile discipline (ADR-0023). Explore folding BM25 into BGE-M3's native sparse output as a follow-up simplification.
- **R3 — Fable 5 focus: design + one cleanup pass.** Fable's scarce, *closing* window is spent on (a) designing the gap-closing capabilities into specs and (b) one deep curation pass over the real vault (contradictions/gaps → Panel suggestions per R1). Implementation is cheaper-model work (Sonnet/Opus).
- **R4 — Live model posture (reverses the §VIII "runtime stays local" lean): the runtime SHOULD support paid models (OpenAI and/or Anthropic).** Fable 5 will **not** be a runtime option (unavailable going forward); wiring an **Anthropic chat provider** into the router is a new gap (`app/components/llm/router.py:41` today knows `mock/ollama/openai/deepseek` — `openai` present, `anthropic` absent). Local Ollama remains the default/free tier; paid models become an available, routable tier for hard cases.

### Original open questions (now answered by R1–R4; retained for context)

1. **G1 — pgvector serving (the one refactor).** Approve closing #2314 (connect durable index to the serving path; keep in-memory as warm cache). Recommendation: yes; do this first.
2. **G3 — Swedish embedding.** Approve the benchmark and pre-authorise the re-index. Preference: **BGE-M3** (best fit, forces dim-change re-index) vs `EmbeddingGemma-300m` (cheapest migration)? BGE-M3 additionally opens the option of *folding BM25 into the embedding model's sparse output* — do you want that structural simplification explored, or keep BM25 separate?
3. **G2 — synthesis passes as proposals.** Confirm the stance: contradiction-callouts, vault-lint, and gap-fill run as **read-only curation passes that propose into Panel/WriteGuard**; agents never auto-write. (The whole field auto-writes; this is our differentiator.) Any low-stakes cases you'd allow to auto-resolve?
4. **G4 — proactivity "Partner" tier.** Approve binding the top proactivity tier to a typed CrossScopeFlow grant (+confirmation +audit), never a boolean, and adding a user "quiet mode" dial. Or keep the top tier deferred with OS-send.
5. **Fable-5 boundary.** Confirm Fable 5 stays at the **builder/curation/eval** layer and never enters the runtime router (runtime stays local Ollama). This is a posture call with cost + egress implications if reversed.
6. **Sequencing Expansion.** The field's strongest signal is that connect/create is the real value and our Expansion track is dormant. Do you want to pull Expansion sequencing forward (behind existing gates), or hold it behind the maintenance-first posture?

---

## Appendix A — Evidence index

**Mimer (this repo):**
- Retrieval: `app/retrieval/capability.py:44-159` (typed contract), `app/retrieval/hybrid.py:27,39-50,212,433,459-480`, `docs/RETRIEVAL.md:58-71,119-132`, `docs/adr/ADR-0024-retrieval-topology.md:17`, epic #2314.
- Vector store / embeddings: `app/stores/pg.py:447,97-106,767-802`, `docs/EMBEDDINGS.md:50-67,160-174`, `app/components/embeddings.py:30-35`, ADR-0023.
- Write authority / agents: `app/write_guard.py:40-73`, `docs/PANEL_AGENT.md:178-189`, `docs/LANGGRAPH_AGENT_ARCHITECTURE.md:428-437`.
- Routing: `app/components/llm/router.py:41`, `docs/LLM.md:20-54`, `docs/LLM_ROUTING.md:16-49`.
- Proactivity / governance: `app/relevance/`, `app/watcher/relevance_tick.py`, `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md:53`, `docs/architecture/cross-scope-flow.md:22-87`, proportional governance #1881, 27-invariant registry `docs/testing/invariant-tests.md`.
- Roadmap: `docs/ROADMAP.md:146-180,256-322`.

**External field (URLs, accessed 2026-07-05):**
- brain.md — https://github.com/mindmuxai/brain.md
- claude-obsidian (closest neighbor: hot/index/log, wiki-lint, consent-gated egress, per-file locking) — https://github.com/AgriciDaniel/claude-obsidian
- NicholasSpisak/second-brain ("librarian/curator") — https://github.com/NicholasSpisak/second-brain
- coleam00/second-brain-skills (progressive disclosure) — https://github.com/coleam00/second-brain-skills
- Letta / agentic-memory tiers — https://thenuancedperspective.substack.com/p/designing-agentic-memory-in-2026
- mem0 state of agent memory (semantic+BM25+entity; async-write pollution risk) — https://mem0.ai/blog/state-of-ai-agent-memory-2026
- Forgetting/decay literature — arXiv 2604.02280, 2605.10870; https://tianpan.co/blog/2026-04-12-the-forgetting-problem-when-agent-memory-becomes-a-liability
- Hybrid+RRF+rerank defaults — https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026 ; https://techbytes.app/posts/hybrid-rag-search-bm25-embeddings-deep-dive-2026/
- memorywire structured-diff HITL — arXiv 2606.01138 ; LangGraph HITL — https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- SSGM / silent pollution — arXiv 2603.11768, 2603.23064
- MindStudio Four C's (capture/curate/connect/create) — https://www.mindstudio.ai/blog/build-ai-second-brain-claude-fable-5-claude-code
- Post-prompting / ambient — https://www.mindstudio.ai/blog/what-is-the-post-prompting-era-proactive-ai-agents
- BGE-M3 / multilingual embeddings — https://arxiv.org/html/2402.03216v3 ; https://github.com/flagopen/flagembedding ; https://app.ailog.fr/en/blog/news/embedding-models-2026
- Fable 5 economics/profile — https://www.lennysnewsletter.com/p/how-i-ai-claude-fable-5-review-and ; https://github.com/Anil-matcha/awesome-claude-fable-5
- Two handover repos (covered separately) — https://github.com/jessepinkman9900/claude-second-brain ; https://github.com/coleam00/second-brain-starter

**HYPE flags:** `github.com/topics/claude-fable-5` is mostly access-hack/router noise, low signal. Consumer proactive assistants (Qira, Poppy) are press-release-stage, no architecture. "No embeddings" is overstated. mem0's headline scores are self-reported. Fable-5 single-run cost anecdotes ($4.07/$12) are marketing, not benchmarks.

## Appendix B — Provenance
- The three prior-session research docs are uploaded to the session scratch (`scratchpad/uploaded/`), not under `docs/research/`; recommend committing them so cross-references resolve in-repo.
- Reference repos cloned at HEAD 2026-07-05 (session scratch, not committed). Fable-5 pricing figures are reported inputs, not independently verified.
