State: Specification directory (program design + bounded slice breakdown). Advisory until child issues are created and delivered; nothing here claims shipped runtime behavior. Grounded in the field audit `docs/research/yggdrasil-fable5-audit.md`, its binding owner rulings R1–R4 (§IX, 2026-07-05), and the **second-pass owner rulings of 2026-07-05**: (1) mechanical-hygiene auto-fix approved via draft ADR-0048 (propose-only until ratified), (2) cloud egress is an evolving graduated policy, not a fixed allowlist, (3) **Expansion (connect + create) is the program's north star and leads the ordering**.
Doc role: Specification (program architecture + decomposition umbrella)
Authority: Owns the capability-hardening program design that delivers the Expansion capability, closes audit gaps G1–G6, and enacts rulings R1–R4. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, the invariant registry `docs/testing/invariant-tests.md`, and the ADRs it cites. Where this program needs a FIXED constraint to move, it flags the move for an owner ADR/CES — it never enacts the move itself.
Owner: Architecture / product (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed — cites current code (`path:line`) and owner rulings; design content is proposal until ratified
Last reviewed: 2026-07-05 (second design pass)

# Mimer Capability Hardening — program spec

**Mandate (reordered 2026-07-05).** The north star is **Cognitive Expansion: Connect + Create** —
the charter's second class of value (`docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2.1), dormant until
now, activated as governed proposals through the existing admissibility gate. Hardening is no longer
the program's headline; it is the **enabling substrate**, and only the minimal enabling subset sits
on Expansion's critical path. The rest of the gap list (G4 proactivity, G5 tuning defaults, G6
hot-cache, the R4 paid tier) proceeds in parallel and never blocks the north star. Guardrail
unchanged: *reduce friction, not intelligence* — every slice hardens or composes existing modules;
Expansion itself activates built-but-dormant machinery (`app/reasoning/multi.py`,
`app/knowledge_compilation/*`) rather than building new cognition.

## Child specifications

| Doc | Covers | Depth |
|---|---|---|
| [EXPANSION_CONNECT_AND_CREATE.md](EXPANSION_CONNECT_AND_CREATE.md) | **The north star.** Connect (related-unlinked, thematic links, cluster emergence — candidate-only) + Create (overview/answer-note/digest as accepted drafts with source provenance); declined-proposal ledger; activation-gate records | deep |
| [GRADUATED_CURATION.md](GRADUATED_CURATION.md) | G2 + R1: mechanical-hygiene auto-fix (gated on ADR-0048), PanelAgent-in-markdown semantic proposals, contradiction callouts, vault-health lint, SV/EN safeguard. G2-1/G2-2 are on Expansion's critical path | deep |
| [RUNTIME_MODEL_POSTURE.md](RUNTIME_MODEL_POSTURE.md) | R4 + egress ruling: Anthropic chat provider, **graduated egress posture on a declared trajectory** (capability-first → balanced → local-first), budget guards, Fable-5 runtime exclusion | deep |
| [PROACTIVITY_TIERS_AND_QUIET_MODE.md](PROACTIVITY_TIERS_AND_QUIET_MODE.md) | G4: state-diff gate on the relevance tick, proactivity tiers bound to proportional governance + typed CrossScopeFlow, quiet-mode dial | deep |
| [RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md](RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md) | G1 residual, G3 BGE-M3 + re-index, G5 RRF/conditional rerank/tuned sizes, G6 session hot-cache. G1res-1 and G3-1 are on Expansion's critical path | mechanical |

## Why Expansion leads (the ruling, grounded)

The audit's roadmap-level observation (§VI): we are strong on separation/governance and thin on
synthesis — "capture+curate is solved and the value is in connect+create." The charter already made
Expansion first-class purpose; the roadmap reset froze it behind two preconditions — a proven
vertical loop and a defined admissibility contract — **both now green** (Panel confirm→execute live;
`docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` + KERNEL-10 enforcement; first gate proof on ASK
synthesis #2022/#2026). Pulling Expansion forward is therefore not a governance relaxation: it is
using the gate we built, for the purpose we built it.

## Reality corrections to the audit (what changed under its feet)

The audit is dated 2026-07-05; the correctness-kernel wave merged the same day and moved the ground:

1. **G1 is substantially delivered, not dormant.** KERNEL-05 landed: `MemoryHybridStore` is now a
   cache-through of the durable `store_vector_index` — `rebuild_from_durable_index()` is the *only*
   production population path (`app/retrieval/hybrid.py:212-247`), wired at API startup
   (`app/api/app.py:190-193`) and consulted by the ASK route (`app/api/routes/ask.py:39`). What
   **remains** of G1 is live-process freshness (rows upserted after warm are invisible until
   restart) and doc truth (`docs/RETRIEVAL.md:66-71`, ADR-0024) — see
   RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md §1.
2. **G5's seam prerequisites partially exist.** Rerank containment is enforced in code
   (`_contain_rerank`, `app/retrieval/hybrid.py:483-493`) and the scope prefilter runs before
   ranking (`:459-480`, KERNEL-10). RRF can be added as a fusion *option* inside `_rank_eligible`
   without the full `SearchPort` abstraction — argued in the child doc; requires a small ADR
   superseding ADR-0024's "linear only" ratification.

## Ruling fold-in status (the three 2026-07-05 second-pass rulings)

1. **Amend-the-rule → drafted.** `docs/adr/ADR-0048-allowlisted-mechanical-hygiene-act-tier.md`
   (Proposed, NOT enacted) proposes the *allowlisted mechanical-hygiene body edit → `act`* row for
   the #1881 tier table — closed class allowlist, never semantic, deterministic transform, Swedish
   safeguard, one-fix-one-receipt-one-diff + revert, evidence gate for allowlist growth. The ADR
   proposes; the owner enacts (this program does not edit `docs/CAPABILITY_CONTRACT_MODEL.md`).
   Until ratification the hygiene engine is propose-only (GRADUATED_CURATION §1); after, slice
   G2-3 flips the allowlisted classes to `act`.
2. **Egress → graduated trajectory.** RUNTIME_MODEL_POSTURE §4 is redesigned from a fixed
   allowlist to a single owner-declared posture stage (`capability-first` now → `balanced` →
   `local-first`) with a stage-invariant floor (always-on loops never egress; every cloud call
   receipted; local-only always sufficient; budget breaker) and named tightening triggers.
   Tightening is one config edit, never a rebuild.
3. **Expansion forward → this README's ordering**, with the true dependency graph below.

## Collision resolved — BGE-M3 vs the dimension-matched fallback

- **BGE-M3 (1024-dim) vs ADR-0023's dimension-matched fallback (768) — RESOLVED by ADR-0052
  (Accepted, 2026-07-06).** R2's switch to BGE-M3 changes `EmbeddingIdentity`
  (`app/components/embeddings/legacy.py` — the live implementation reached via
  `app.components.embeddings`; the package `__init__.py` shadows the flat `app/components/embeddings.py`
  module of the same name, a pre-existing repo quirk unrelated to this decision) to 1024 dims. Option
  (a) was ratified: the Gemini fallback re-pins to `output_dimensionality=1024` — the adapter passes
  the caller's resolved `dim` straight through rather than a hardcoded literal, so the fallback stays
  dimension-matched automatically once the primary identity moves. The G3-1 implementation slice
  (#2984) shipped the `bge-m3` profile as a SELECTABLE mechanism (not the flipped default); see
  `docs/adr/ADR-0052-embedding-fallback-repin-1024-bge-m3.md` and
  `docs/runbooks/RUNBOOK_BGE_M3_CUTOVER.md` for the operator cutover procedure. *(The R1 tier-table
  collision is now covered by draft ADR-0048; the egress posture is covered by the reshaped decision
  3 below.)*

## Program architecture — how the pieces compose

```
                 ┌─────────────────────────────────────────────────────────┐
                 │  GOVERNANCE SUBSTRATE (shared, unchanged core)           │
                 │  WriteGuard · proportional tiers (#1881) · typed         │
                 │  CrossScopeFlow · receipts · Panel gate · admissibility  │
                 │  gate (app/activation/gate.py, proven by ASK #2026)      │
                 └────────────────────────┬────────────────────────────────┘
                                          │
              ╔═══════════════════════════▼════════════════════════════╗
              ║  NORTH STAR — EXPANSION: CONNECT + CREATE               ║
              ║  connect.* findings (candidate-only) ──► Panel checkbox ║
              ║  create drafts (staging + SourceRef provenance)         ║
              ║      ──► human accept ──► governed materialization      ║
              ║  contradiction pass (G2-4) as sibling Expansion pass    ║
              ╚══════╤═════════════════════════════════╤════════════════╝
                     │ reads through                    │ materializes via
   ┌─────────────────▼──────────────┐   ┌──────────────▼──────────────────┐
   │ RETRIEVAL SPINE (enabling)     │   │ CURATION PIPELINE (enabling)     │
   │ G1res-1 freshness  → critical  │   │ G2-1 finding pipeline → critical │
   │ G3-1 BGE-M3 (SV/EN)→ critical  │   │ G2-2 proposal writer  → critical │
   │ G5 tuning, G6 cache → parallel │   │ G2-3 auto-fix flip (ADR-0048)    │
   └────────────────────────────────┘   │        → independent track      │
                                        └─────────────────────────────────┘
   PARALLEL, NON-BLOCKING: G4 proactivity (state-diff, tier binding, quiet
   dial) · R4 cognition power (census, Anthropic provider, graduated egress
   posture, budget) — R4 raises Create quality but never gates it (local works)
```

- **Expansion** is the only track that delivers new *human-visible* capability; everything else
  exists to make it truthful (fresh index), work in Swedish (BGE-M3), and have a surface to land on
  (finding pipeline + Panel writer). It preserves the moat: the whole field auto-writes; we propose.
- **Curation** shares one finding pipeline with Connect and one declined-proposal ledger; its
  auto-fix track is governance-independent of Expansion and waits on ADR-0048.
- **Proactivity** and **cognition power** compose orthogonally: a G4 moment may *offer* a digest
  (never run one); a paid model may *execute* a synthesis route (never change what its output may
  do).

## The true dependency graph (what Expansion genuinely needs vs what can follow)

**Hard prerequisites for the first Expansion ship (EXP-1 connect pass):**

```
G2-1 finding pipeline ─┐
G2-2 proposal writer  ─┼──► EXP-1 connect (related-unlinked + thematic)
G1res-1 cache freshness┘         │
                                 ▼
                    EXP-2 declined ledger ──► EXP-3 create engine ──► EXP-4 acceptance
G3-1 BGE-M3 + re-index ──(before Expansion passes run on the REAL SV/EN vault;
                           EXP code lands in parallel against fixtures)
ADR: embedding fallback re-pin ──► G3-1
```

**Genuinely needed before ship:** G2-1, G2-2, G1res-1 (code), G3-1 (before real-vault operation —
connect quality on a majority-Swedish vault under an English-centric embedding would misrepresent
the capability on day one), and the embedding ADR that G3-1 needs.

**Explicitly NOT needed for Expansion (parallel/deferrable):** G5 fusion-default flip (tuning
improves ranking, doesn't gate correctness — invariants pin eligibility regardless), G6 hot-cache,
G4-1/2/3 (only the later digest-*offer* touches G4), all of R4 (local models run the passes; paid
routes are a quality upgrade under the declared posture), G2-3 auto-fix flip (independent
governance track), G2-5 grammar promotion.

## Sequencing — three tracks, Expansion leads

```
TRACK E — north star (serial spine)
  E1. G2-1 vault-health lint + finding pipeline core      (Sonnet)   [was Wave 0 D]
  E2. G2-2 proposal writer, propose-only                  (Sonnet)   [was Wave 1 J]
  E3. EXP-1 connect pass (related-unlinked + thematic)    (Sonnet)
  E4. EXP-2 declined-proposal ledger                      (Sonnet)
  E5. EXP-3 create engine (overview + answer_note)        (Sonnet)
  E6. EXP-4 governed acceptance/promotion                 (Opus — authority semantics)
  E7. EXP-5 cluster→overview + digest  ·  EXP-6 activation records + status ladder (Sonnet)
  E8. G2-4 contradiction pass harness (sibling pass; reuses EXP-1 shape + EXP-2 ledger) (Sonnet)
  E9. R3 one-time deep curation/connect pass over Niflheim (offline op, owner-scheduled;
      Fable 5 if the window is still open, else best available frontier model)

TRACK H — minimal enabling hardening (parallel; feeds E as marked)
  H1. G1res-1 cache freshness (generation check)          (Sonnet)   → needed by E3
  H2. G1res-2 retrieval doc truth                         (Sonnet, docs lane)
  H3. Embedding ADR (fallback re-pin)                     (owner + docs lane) → gates H4
  H4. G3-1 BGE-M3 identity migration + full re-index      (Sonnet impl / Opus runbook)
      → before E3+ run on the real vault
  H5. G3-2 SV/EN retrieval eval (validates + tunes; extended with an Expansion-quality
      section: connect precision on a hand-labelled SV/EN pair set)  (Sonnet)

TRACK P — parallel program (never blocks E)
  P1. R4-1 provider census → P2. R4-2 Anthropic provider (Opus) → P3. R4-3 graduated
      egress-posture compiler + budget breaker (Opus; posture ADR sets the declared stage)
  P4. G4-1 state-diff gate (Sonnet) → P5. G4-2 tier binding (Opus) → P6. G4-3 quiet dial (Sonnet)
  P7. G5-1 fusion option + conditional rerank code (Sonnet; default flip waits on H5)
  P8. G6-1 session hot-cache (Sonnet; after H1)
  P9. G2-3 auto-fix act-tier flip (Sonnet; after ADR-0048 ratified + soak) → G2-5 evidence review
  P10. Per-file advisory locking (Sonnet; before P9 or E-track gains a second body-writer — owner decision 8)
```

Orderings that changed from the first pass, with rationale:
- **Expansion slices moved from "Wave 3 capability activation" to the spine.** First pass treated
  the contradiction pass as the lone Expansion activation and put it last; the ruling inverts this —
  connect+create is the destination and hardening queues behind *its* needs.
- **G3 stays before real-vault Expansion but no longer before Expansion *code*.** Fixture-driven
  EXP slices proceed against SV/EN test corpora in parallel with the migration.
- **G5 default-flip and G6 dropped off the critical path entirely** (were Wave 2): ordering-quality
  tuning, not capability gates.
- **R3's deep pass keeps its late-but-bounded slot** — it needs the EXP/G2 harness to emit findings
  as governed proposals rather than a throwaway report; the harness, not the model, is the durable
  asset.

## Risk register (cross-cutting)

| Risk | Where it bites | Mitigation (designed into slices) |
|---|---|---|
| Staged drafts leak into retrieval and compound (machine text citing machine text) | EXP-3/EXP-4; provenance trust | Staging excluded from indexing; `staged_drafts_invisible_to_retrieval` invariant; accepted notes stay `derived_by: synthesis` and non-citable-as-authority until review-state advances (EXPANSION §2.3) |
| Proposal flood (connect findings + curation findings swamp the note surface) | EXP-1, G2 passes; user trust + dyslexia-friendly posture | Per-pass caps, decline ledger with visible suppression counts, idempotent finding ids, bounded panel trimming (existing PANEL contract) |
| Connect proposes cross-scope links | EXP-1; scope integrity | Same-scope by default; cross-scope only under existing `surface` flow; content-free denial (KERNEL-10) |
| Mixed-identity index window during BGE-M3 re-index | H4; every retrieval consumer | ADR-0023 reconcile discipline: doctor flags mixed state, query path pins one identity; prod re-index operator-ack-gated |
| Swedish text "corrected" into broken English by auto-fix | P9; user trust | ADR-0048 binding condition 4: lexicon veto, diacritic invariance, never cross-language, mixed ⇒ propose (GRADUATED_CURATION §3) |
| Paid-model cost runaway | Track P; always-on loops | Stage-invariant floor: always-on kinds structurally local; per-day budget breaker fails local + loud (RUNTIME_MODEL_POSTURE §4.2) |
| Vault-content egress outlives the owner's privacy comfort | Track P; trajectory | Every egress receipted from day one; declared-stage tightening is one config edit; named review triggers (RUNTIME_MODEL_POSTURE §4.3) |
| Receipt/attention churn from proactivity | P4; scarcity | State-diff gate: no evaluation and no receipts without a relevant delta |
| Fusion change silently altering *eligibility* | P7 | Invariant: fusion/rerank change ordering only; prefilter + role clamp + containment run independently |
| Concurrent writers thrash panel/receipt surfaces | E-track + P9 add machine writers | Per-file advisory locking as a bounded slice (P10, owner decision 8) |
| Append/propose surfaces rot (unbounded panels) | E/G2 passes | Proposal idempotency + bounded receipt trimming already contractual (`docs/PANEL_AGENT.md:172`); passes idempotent per (note, finding-hash) |

## Fitness invariants added by this program (registry candidates)

Full entries live in the child docs; on delivery each becomes a registry entry via the normal CES
flow (this spec does not edit the registry).

| Invariant | Child doc | One-line purpose |
|---|---|---|
| `create_never_autowrites_canonical` | EXPANSION_CONNECT_AND_CREATE | Synthesis output reaches canonical locations only through a human acceptance receipt; staging is the only machine destination |
| `synthesis_carries_source_provenance` | EXPANSION_CONNECT_AND_CREATE | Every draft + accepted note carries resolvable SourceRefs; citation failure blocks loudly; provenance survives acceptance |
| `connect_proposals_candidate_only` | EXPANSION_CONNECT_AND_CREATE | `connect.*` classes are propose-track by construction; connect evidence clamps to `background` |
| `staged_drafts_invisible_to_retrieval` | EXPANSION_CONNECT_AND_CREATE | Unaccepted drafts are never indexed or retrievable — no machine-text compounding |
| `expansion_requires_activation_record` | EXPANSION_CONNECT_AND_CREATE | Connect/Create run only under a green activation-gate record; regression ⇒ blocked-with-reason |
| `declined_findings_not_reproposed` | EXPANSION_CONNECT_AND_CREATE | A declined proposal is suppressed until its content basis changes; the ledger never enters context |
| `autofix_allowlist_closed` | GRADUATED_CURATION | Auto-applied edits' classes are on the closed mechanical allowlist; anything else fails loud |
| `autofix_reversible_receipted` | GRADUATED_CURATION | Every auto-fix = one Git-visible diff + one receipt + a revert marker |
| `autofix_sv_lexicon_guard` | GRADUATED_CURATION | No auto-edit of valid Swedish word-forms/diacritics; mixed-language demotes to propose |
| `semantic_curation_never_autowrites` | GRADUATED_CURATION | Semantic findings materialize only as unchecked `AI-åtgärder` checkboxes |
| `curation_citations_resolve` | GRADUATED_CURATION | Contradiction callouts carry ≥2 resolvable in-vault sources |
| `tick_reasons_only_on_delta` | PROACTIVITY_TIERS | No relevance evaluation without a declared-inputs delta or time-bucket crossing |
| `partner_tier_requires_typed_flow` | PROACTIVITY_TIERS | Outbound proactive delivery only under a typed CrossScopeFlow grant; no boolean |
| `quiet_mode_caps_surfacing_not_governance` | PROACTIVITY_TIERS | The dial silences rungs, never WriteGuard/receipts/the zero-tolerance floor |
| `paid_route_follows_declared_posture` | RUNTIME_MODEL_POSTURE | Paid routes exist only through compiled policy bounded by the single declared posture stage |
| `cloud_egress_always_receipted` | RUNTIME_MODEL_POSTURE | Every cloud call leaves an egress record — the pre-built privacy lever |
| `posture_tightening_is_config_only` | RUNTIME_MODEL_POSTURE | Tightening the egress stage is a config edit, never a code change |
| `local_only_remains_sufficient` | RUNTIME_MODEL_POSTURE | Zero paid eligibility still yields a fully functional system, degraded legibly |
| `paid_unreachable_from_always_on_tasks` | RUNTIME_MODEL_POSTURE | Tick/watcher/ingest kinds cannot resolve paid at any posture stage |
| `runtime_router_never_serves_fable` | RUNTIME_MODEL_POSTURE | No descriptor/policy/override resolves a runtime route to a Fable-class model |
| `provider_surface_census_single_source` | RUNTIME_MODEL_POSTURE | Every provider allowlist derives from / is asserted against one census |
| `retrieval_serves_durable_truth_fresh` | RETRIEVAL_EMBEDDINGS | Post-upsert retrieval reflects the durable index within the freshness bound, no restart |
| `fusion_changes_order_never_eligibility` | RETRIEVAL_EMBEDDINGS | Fusion/rerank selection permutes order, never membership or evidence role |
| `embedding_identity_converges_post_reindex` | RETRIEVAL_EMBEDDINGS | Post-migration doctor reports a single identity; mixed state is loud, never silent |
| `hot_cache_derived_never_authority` | RETRIEVAL_EMBEDDINGS | Hot-cache is rebuildable, scope-filtered, and never enters context as `evidence` |

## Consolidated owner decisions still needed

1. **Ratify ADR-0048** (allowlisted mechanical-hygiene → `act`). Drafted at
   `docs/adr/ADR-0048-allowlisted-mechanical-hygiene-act-tier.md` (Proposed). Until ratified,
   auto-fix is propose-only. *(Blocks P9 only; nothing on the Expansion spine.)*
2. **Embedding ADR superseding ADR-0023 (enacts R2).** BGE-M3 @1024 primary; fallback re-pinned to
   Gemini @`output_dimensionality=1024` (recommended) or fallback-less window. *(Blocks H4.)*
3. **Egress-posture ADR (reshaped by the graduated-policy ruling).** Ratify the trajectory model
   (RUNTIME_MODEL_POSTURE §4): stages + stage-invariant floor + tightening triggers, and declare
   the initial stage (recommended: `capability-first`). *(Blocks P3's declared stage; plumbing
   lands conservative-default first.)*
4. **Paid-tier budget ceiling** and trip behavior (recommended: degrade to local + loud signal).
   OpenAI-first, Anthropic-first, or both (spec wires both; enabling is config).
5. ~~Expansion sequencing~~ — **RESOLVED by the 2026-07-05 ruling:** Expansion leads; this README's
   Track E is the enactment. Residual Expansion decisions are E1–E4 in
   `EXPANSION_CONNECT_AND_CREATE.md` §7 (staging location; provenance frontmatter keys — owner-doc
   PR when EXP-3 lands; digest-by-moment; accepted-synthesis review-state semantics).
6. **BM25 folding into BGE-M3 sparse.** Explore-only; keep BM25 unless the H5 eval shows lexical
   weakness (new serving dependency otherwise — against the guardrail).
7. **Quiet-dial surface + default.** Recommended `@Settings/proactivity.md`, default `normal`.
8. **Per-file advisory locking.** Adopt as bounded slice P10 (recommended — the E-track and P9 add
   machine writers to note bodies) or defer.

## SBS reconciliation (per-claim posture)

- **Conforms:** Expansion activates through the ratified Expansion Activation Gate + admissibility
  contract at `proposal` authority (EMERGENT_FEATURES_MODEL, CONTEXT_ADMISSIBILITY_CONTRACT);
  Connect/Create materialization conforms to the Panel authority boundary, PA2-FREEFORM, and the
  #1881 tier table (acceptance of a body-modifying variant stays `ask-you`); retrieval spine work
  stays inside ADR-0023/0024 discipline and the KERNEL-05 cache-through contract; G4 conforms to
  the reach-out/scarcity contract; R4 conforms to the router/fabric contract and #2109.
- **Extends:** `connect.*` finding classes extend the closed curation enum (propose-track only);
  Create's staging area + proposal frontmatter extend the vault system-surface conventions
  (owner-doc PR for `docs/FRONTMATTER.md` keys — decision 5/E2); the declined-proposal ledger is a
  new derived store; the graduated egress posture extends the census; fusion option + rerank gate
  extend ADR-0024 via a superseding ADR; hot-cache extends the ActiveContextSet direction.
- **Reshapes (owner-routed, never enacted here):** the #1881 tier-table row (draft **ADR-0048** —
  proposed, awaiting ratification); the embedding identity/fallback re-pin (decision 2); the egress
  trajectory ratification (decision 3).

## TCD routing summary

Sonnet by default for every implementation slice. Opus for: EXP-4 acceptance/promotion (authority
semantics), the Anthropic provider + egress-posture compiler (auth/routing/authority), the G4
tier-binding slice, the G3 prod migration runbook, and any owner-doc-bundled cutover. Fable 5:
design (this spec set) and the one offline deep pass (E9) only — **never** an implementation slice,
never a runtime route.
