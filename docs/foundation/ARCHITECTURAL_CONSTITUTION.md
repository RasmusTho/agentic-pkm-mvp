State: CANDIDATE (advisory research artifact, RESEARCH-07, issue #2785, epic #2778; 2026-07-04). Ratification is an explicit owner decision framed in `:: Ratification decision` — until then this document governs nothing and silently changes no owner doc's claims.
Doc role: Foundation candidate (architectural constitution)
Authority: Derived, not asserted: every principle traces to the formal model (`docs/architecture/formal-model.md`), the runtime semantics baseline (`docs/architecture/runtime-semantics.md`), the kernel audit (`docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md`), the doctrine (`docs/foundation/00-yggdrasil-doctrine.md`), and the delivered contract layer. Subordinate to the doctrine and all owner contracts. Where a principle and an owner doc disagree, the owner doc wins and the divergence routes through an issue.

# The Yggdrasil Architectural Constitution (candidate)

Premise: assume the frontier model that wrote this never sees the repository again. What follows is
the smallest set of enduring architectural principles that should govern every future design
decision — implementation-independent, surviving rewrites, valid across languages, databases,
frameworks, editors, and models. Eleven principles; each earns its place by derivation, carries its
violations honestly, and names an automatic evaluation hook. A principle that could not name a hook
did not get in (see `:: Rejected candidates`).

Relationship to the doctrine: `00-yggdrasil-doctrine.md` states *what Mimer is* and the
commitments that must not collapse — it remains the product north star and this constitution's
superior. The constitution states *how any implementation of it must behave*, distilled from one
full pass of formal modeling (RESEARCH-01/02), invariant synthesis (RESEARCH-03), and the kernel
rebuild (#2762). Where a doctrine commitment appears below, it is cited, not restated.

## The apex model (resolving the 2026-07-04 clash)

Two merged-or-in-flight framings collided on what "Yggdrasil" names:

- **ADR-0043** (file on `main` via PR #2886; owner-decided 2026-07-04; ADR status: Proposed,
  enactment deferred): **Yggdrasil is the whole** — the acknowledged
  System-of-Systems in which the constituents hang: **Munin** (knowledge/memory), **Hugin**
  (agent runtime), **Heimdal** (sensing/event capture). "Federation" stays reserved for the SFC
  boundary's node/replication concern and is not the word for the constituent relationship.
- `docs/architecture/ecosystem-federation.md` (RESEARCH-08 lineage, #2888/#2890/#2891): framed a
  "Personal Agentic Ecosystem" as apex with Yggdrasil as one constituent.

**This constitution adopts ADR-0043: Yggdrasil = the whole.** The owner resolved the clash on
2026-07-04; the reconciliation landed as ADR-0044–0047 via PR #2920. PR #2888 was closed
unmerged. The losing framing is flagged, not erased: `ecosystem-federation.md` is reconciled to
ADR-0044 on `main`; #2890 (model reconciliation) and #2891 (the GLOSSARY
"federation"-usage follow-up) are closed.
One nuance holds everything honest: the SoS *reshape itself* (ADR-0041's "modular single system" →
acknowledged SoS) is owner-decided but not yet enacted through CES — until that enactment,
`docs/ARCHITECTURE.md`/`docs/STATUS.md` describe shipped reality and this constitution's principles
bind **the whole and every constituent equally**: nothing below is Munin-only law.

The earlier reconciliation queue is complete: #2890 and #2891 are closed.

---

## The principles

Format per principle: **Derivation** (why fundamental, from the formal work, not taste) ·
**Embodied / violated** (file-level anchors, verified against `main` 2026-07-04) ·
**Operational failure** (what breaking it costs, tied to real incident classes) ·
**Evaluation hook** (automatic; existing or committed) · **Belongs in** (governance / runtime / CI /
architecture docs / all).

### C-1 · Standing is explicit and changes only through governed transition

No artifact's authority is ever implied by where it sits, who wrote it, how often it appears, or how
similar it is to something trusted. `source_role`, `authority_state`, and `evidence_role` are
orthogonal; movement between authority states is a governed transition with a token and a receipt.

- **Derivation:** the doctrine's commitments 1/4/5/6 made enforceable; the formal model shows *why*
  they are structural, not stylistic — every path by which machine output could become durable
  standing (T-panel-confirm, T-promote, T-review-decide) already routes through an explicit
  transition, and every incident of implied authority in the audit (CW-2's silent CO_AUTHORING
  default) was a defect. Authorship ≠ canonicality: a human note enters as origin, not standing.
- **Embodied:** `app/write_guard.py` (WG at seams), `app/agent_memory/materialization.py` (human
  decision precedes materialization), `schemas/memory-item.schema.json` (`authority_state` const
  `noncanonical`), `schemas/authority-transition.schema.json` (token+receipt conditionals).
  **Violated:** none structurally today; nearest miss was the intent classifier's mutation-capable
  default route, removed by KERNEL-07 (#2769).
- **Operational failure:** an agent suggestion silently becomes accepted knowledge; the human stops
  being the locus of authority — the product's core promise, not a feature, breaks. Incident class:
  pre-#2769 misclassification routed governance-bearing intent to a mutation-capable class.
- **Evaluation hook:** registry rows `memory_item_authority_is_noncanonical`,
  `authority_transition_requires_decision_token_and_receipt` (static, passing);
  `promote_requires_governance`, `authority_transition_required_for_durable_mutation` (runtime
  slices pending, registered xfail); intent golden set (#2775) gates the classifier.
- **Belongs in:** all (governance owns it; runtime enforces it; CI pins it; docs teach it).

### C-2 · Eligibility precedes relevance

Whether material may participate is a set-membership decision made *before* any scoring, ranking,
or similarity computation; ranking orders the eligible set and can never reintroduce the excluded.
Exclusions of relevant material are recorded content-free — a denial that leaks the denied thing's
identity is itself a disclosure. The use-time corollary: an admitted candidate's
`evidence_role_in_context` may be downgraded but never upgraded above its intrinsic evidence role —
eligibility bounds *participation*, the clamp bounds *standing during participation*.

- **Derivation:** doctrine commitment 1 ("similarity is not permission") given its operational
  form by the retrieval contract and the formal model's admissibility precondition on T-ask.
  Fundamental because it is the only ordering that composes: filter-then-rank is stable under any
  future ranker, reranker, or model; rank-then-mask must re-prove safety for each one (and today's
  live path even lets ineligible rows shift score normalization of eligible ones).
- **Embodied:** `mimer_runtime/retrieval.py::eligible_candidates` + `_denials_for_excluded`
  (reference); `schemas/retrieval-result.schema.json` (`scope_policy_prefiltered` pinned,
  content-free denial shape). **Violated (in remediation):** `app/retrieval/hybrid.py::hybrid_search`
  ranks over all docs and masks after ordering, with silent drops — the exact gap KERNEL-10 (#2772,
  in delivery) closes.
- **Operational failure:** cross-scope contamination on a high similarity score — Project Beta
  material surfacing in a Project Alpha answer; private notes in work context. The anti-contamination
  corpus (#2551) exists because this failure is *undetectable by the user* when it happens.
- **Evaluation hook:** registry rows `retrieve_scope_prefilter`, `similarity_not_permission`,
  `denied_scope_does_not_leak_identity`, and `retrieval_cannot_upgrade_intrinsic_non_evidence`
  (the clamp); the three eval-corpus suites; #2772's
  `tests/retrieval/test_scope_prefilter_before_rank.py` binds the live entrypoint, including its
  in-context role-clamp test.
- **Belongs in:** runtime + CI.

### C-3 · Meaning travels with the artifact

Identity, scope, roles, and provenance ride *on* the object through every store, index, projection,
and derivation — never reconstructed downstream from context, path, or convention. There is no
naked representation; a derived artifact names what it derives from and what transform produced it.

- **Derivation:** doctrine commitments 2/3; RESEARCH-01's classification table demonstrates the
  cost of its absence historically (class 4 `store_objects` as "the semantically fuzziest class in
  the system"); the audit's CW-6 shows replay/backfill is *impossible* without recorded transform
  provenance — meaning-loss is not aesthetic, it forecloses whole capability classes.
- **Embodied:** `schemas/metadata-bundle.schema.json` (closed, required envelope),
  KERNEL-06 (#2768) provenance stamps on every vector row, `app/ingest/chunk_policy.py`
  (deterministic chunk identity). **Violated:** the live object rows still carry permissive dict
  payloads without full bundles (CW-4's two-type-systems split — narrowing kernel-by-kernel, not
  closed).
- **Operational failure:** #2297 (mixed embedding identity — rows whose provenance couldn't say
  which model produced them); "re-embed what changed" impossible pre-#2768; any DB rebuild loses
  what a row *meant* as opposed to what it *contained*.
- **Evaluation hook:** registry rows `metadata_bundle_required`, `store_no_naked_vectors`,
  `provenance_survives_derivation` (schema+static+runtime); KERNEL-06 doctor staleness check;
  P-2's replay-completeness property extends this to the event dimension.
- **Belongs in:** runtime + architecture docs.

### C-4 · One truth per concept; every copy is a rebuildable cache with a named reconciler

For each concept there is exactly one authoritative substrate and one writer; every other
representation is a cache or projection that is (a) rebuildable from the truth and (b) covered by a
*named* reconciliation mechanism — or explicitly registered as UNRECONCILED and advisory.

- **Derivation:** the formal model's §4 is this principle as a table: nine dual-store seams, each
  forced to declare its reconciler or wear UNRECONCILED. CW-1 (three retrieval substrates with
  best-effort coupling) was the system's largest structural weakness; KERNEL-05 resolved it by
  *demoting* the in-memory store to cache-of-durable-index rather than synchronizing two truths —
  demotion, not synchronization, is the general fix.
- **Embodied:** `app/retrieval/hybrid.py::rebuild_from_durable_index` (cache-through, I-D3),
  single store generation (KERNEL-03/04), Alembic-only DDL. **Violated:** #2901 — `PgObjects`
  writes both `store_objects` and legacy `objects` (a second writer generation live *after* the
  kernel closed I-S1); seam C8's mirror writes remain a registered-exception gap (P-2).
- **Operational failure:** what is retrieved ≠ what is durable ≠ what is audited (CW-1); #2242's
  "consumes nothing for weeks" was invisible precisely because divergence between substrates had no
  reconciler to scream.
- **Evaluation hook:** kill-and-restart identity test (KERNEL-05); doctor divergence checks;
  P-6 single-writer static gate (committed via #2781's follow-ups, sequenced with #2901).
- **Belongs in:** runtime + CI + architecture docs.

### C-5 · The event log is the transition journal — complete, idempotent, receipt-before-ack

Every durable state mutation commits atomically with its event, carries a deterministic idempotency
key, is handled idempotently under at-least-once delivery, and acknowledges success only after its
accountability record is durable. Exceptions exist only on a registered mirror list. Replay of the
log against the canonical plane reconstructs the derived plane — or the registry says exactly where
it cannot.

- **Derivation:** the outbox pattern's entire purpose (audit CW-3: "at-least-once delivery without
  enforced idempotency and without atomic state+event means replay is not sound"); the formal
  model's plain statement — `replay(P.outbox, V) reconstructs P only up to C3/C4/C8` — is the
  honest form this principle drives toward. T-capture is the reference shape: receipt persisted
  before ACK, else the caller learns it failed.
- **Embodied:** KERNEL-01 (#2763 + #2864/#2896 one-transaction vault sync), KERNEL-02 (#2764
  mandatory keys), KERNEL-11 (#2773 dispatch-twice harness), KERNEL-12 (#2774 loud dead-letters),
  `app/api/routes/capture.py` (receipt-before-ack exemplar). **Violated:** the eleven
  `emit_outbox=False` mirror sites are journal-invisible until P-2's registered-mirror census;
  reviewer/set_evaluator still swallow decision-write failures caller-side (P-5 residue).
- **Operational failure:** #2863 (content changes emitted no event — downstream consumers starved
  silently); #2864's pre-fix crash windows (objects without file_state); #2242 as the canonical
  consumes-nothing symptom.
- **Evaluation hook:** `tests/integration/test_vault_sync_atomicity.py`; the #2773 harness (topic
  without fixture = failure); P-2 event-completeness and P-5 receipt-before-ack properties.
- **Belongs in:** runtime + CI.

### C-6 · Guards live at the seam and fail closed

Enforcement is asserted inside the seam that performs the effect — never delegated to caller
convention. A guard that cannot evaluate blocks the effect. Deliberate bypasses are named,
registered escapes (bootstrap provisioning), not conventions.

- **Derivation:** formal-model gaps 1 and 4, discovered by walking every mutation initiator: the
  same seam (`execute_panel_intent`) was guarded or unguarded depending on *which caller* reached
  it — proof that caller-side guarding is not a weaker version of seam-side guarding but a
  different (and false) claim. Four seam-local fixes in one week (#2808 panel, #2809 settings,
  #2810 note_hygiene, #2877 scaffolder) prove the class recurs and gets fixed retail; the
  constitutional form ends the retail cycle. The #2877 scaffolder set the pattern: WG asserted at
  the seam, a *named* bootstrap escape (`DEFAULT_WRITE_GUARD`/`DEFAULT_BOOTSTRAP_ACTIONS`), denying
  guard blocks atomically.
- **Embodied:** `app/agents/panel_agent/runtime.py` (seam asserts `"panel.writeback"`, #2808),
  `app/settings/mimer_scaffolder.py::scaffold` (#2877), `app/agents/note_hygiene/agent.py`
  (#2810), `app/chat/canvas_writer.py` (WG + structural checks), `app/services/companion_note.py`.
  **Violated (verified on `main` 2026-07-04):** the knowledge write port itself
  (`app/knowledge/write_ops.py::write_note_from_absolute` — the shared root cause every retail fix
  worked around), identity-heal (`app/vault/manager.py::_ensure_frontmatter_id`), the
  checkbox-rollback compensating write (`app/panel/checkbox_projection.py` exception handler), and
  F-C — `note/save`'s WG deliberately fails open (`app/api/routes/companion.py`), a **named owner
  decision pending** (availability vs integrity), which is the honest state for a violation of law:
  on the books, scheduled for judgment, not hidden.
- **Operational failure:** until #2808 (2026-07-04), a worker- or CLI-triggered panel writeback
  mutated the vault with WriteGuard in `safe_mode` — the governance surface reported "writes
  blocked" while writes proceeded. That window is now closed retail; the class stays open until the
  port-level gate exists (P-1 priority table, rank 2).
- **Evaluation hook:** P-1 static call-graph gate + denying-guard property; P-4 raising-guard
  property (committed via #2781 follow-ups).
- **Belongs in:** runtime + CI + governance.

### C-7 · Reads do not write; every write is a named transition

The mutation surface is enumerable: a finite catalog of named transitions, each with initiator,
precondition, guard, and event. Read paths mutate nothing durable; healing-on-read is legal only as
a registered, WG-gated transition that a read *triggers* — not a side effect a read *has*.

- **Derivation:** the formal model exists because this was almost true: RESEARCH-02 could enumerate
  every transition (§2) precisely because mutation initiators are few — and its Q4 findings (uuid
  heal from GET, lazy identity-heal) were the undocumented exceptions that made the catalog false.
  A system whose mutation surface cannot be enumerated cannot be modeled; a system that cannot be
  modeled cannot be verified. This principle is what keeps every other principle checkable.
- **Embodied:** the transition catalog itself (`formal-model.md` §2, verified by two mutation-surface
  sweeps + an adversarial pass that found no hidden initiator); the API lifespan's read-only
  preflight. **Violated:** T-uuid-heal reachable from `GET /companion/workspace`; identity-heal via
  `app/vault/manager.py::_ensure_frontmatter_id` on lazy vault load — real heals, undeclared class.
- **Operational failure:** GET-path writes on hot loops compound invisibly (the #2903/#2905 watcher
  class shows how per-item side effects on scan paths amplify); undocumented writes are where the
  next F-A hides.
- **Evaluation hook:** P-3 route-walk property (every GET route × spy stores; new route
  unclassified = failure).
- **Belongs in:** runtime + architecture docs (the catalog is a living doc obligation).

### C-8 · Nothing fails silently — absence of signal is a detectable state

No silent fallback, no silent drop, no default route on classification failure, no swallowed
receipt failure, no queue quietly at zero. For a memory system this is existential: the absence of
recall is indistinguishable from the absence of content *unless the system makes them
distinguishable*.

- **Derivation:** audit CW-5's verdict — "the failure mode of the whole pipeline is 'quietly does
  nothing' — the most expensive failure class for a memory system." Every major incident in this
  repo's history is in this class: #2242 (worker consumed nothing, weeks), #2863 (no events on
  content change), pre-#2788 decisions writer (silent memory fallback on DB failure), pre-#2765
  store fallback, false-green observability (2026-06-27 audit). Not one was a wrong answer; all
  were missing answers presented as health.
- **Embodied:** fail-loud store resolution (#2765/#2766, explicit `STORE_BACKEND=memory` opt-in),
  decisions writer (#2788), UNKNOWN intent route (#2769), loud dead-letters + queue-age health
  (#2774), content-free denials replacing silent drops (#2772, in delivery), no-vault fail-loud
  (`VAULT_ROOT` set-but-missing). **Violated:** the remaining caller-side `try/except: pass`
  swallows (P-5 residue); C3's dual best-effort JSONL write (registered UNRECONCILED, advisory by
  declaration — the *honest* form of the exception).
- **Operational failure:** see derivation — this principle is written in incident blood.
- **Evaluation hook:** startup fail-loud tests; UNKNOWN fuzz test; dead-letter health surfacing
  test; denial-emission tests; P-5's failing-receipt-store property; harness-selfverify's
  intentional-violation fixtures (the verifier itself must be able to fail).
- **Belongs in:** all.

### C-9 · LLMs decide meaning; code decides consequences

A language model is justified exactly where the domain is unbounded natural language and the output
is meaning. Everything downstream of a typed value is deterministic code. LLM output that anything
branches on is schema-constrained and validated before use; free text crosses exactly two edges:
user→system inbound, system→user outbound.

- **Derivation:** audit RQ5's boundary rule, proven by CW-2: the governance chain was "only as
  strong as a regex," and the classifier's failure default was a *route*, not a refusal. The
  deterministic gate + LLM cognition split is also settled owner posture (LLM-classification over
  keyword heuristics, gates stay deterministic) — this principle is its architecture-law form.
- **Embodied:** constrained decoding + UNKNOWN (#2769), topic schema registry validating at write
  and dispatch (#2770), plan admission rules (#2771), classification golden set with
  mutation-side-confusion as a blocking gate (#2775), failure→eval capture loop (#2777).
  **Violated:** none structurally after Phase 2; the standing risk is regression, which the golden
  set now gates.
- **Operational failure:** pre-#2769, unparseable LLM output silently became a mutation-capable
  CO_AUTHORING route — the single highest-leverage LLM fix in the system, per the audit.
- **Evaluation hook:** `classification_case.v1` golden set (blocking); topic-registry coverage
  test; plan-admission fixtures; scorecard compare (#2776) required for model/prompt swaps.
- **Belongs in:** runtime + CI + governance.

### C-10 · Boundaries follow invariant ownership; technology is an adapter

Component boundaries sit where invariant ownership changes (who may decide, who may write, who must
receipt) — never where a technology, framework, or vendor artifact happens to end. Vaults, editors,
storage engines, embedding providers, model providers, sync transports, and agent frameworks are
replaceable mechanisms behind adapters; external standards adapt to the ontology, not the reverse.

- **Derivation:** ADR-0032 (boundaries follow invariant ownership) + ADR-0036 (standards are
  adapters) + ADR-0042 (volatility isolation), stress-proven by the SBS's 2030 scenarios (Part 9:
  Obsidian removed, retrieval replaced, memory replaced, agent runtime replaced — each survivable
  *because* no boundary is a technology). The formal model's failure domains (§5) show the same
  from below: FD boundaries are semantic (canonical vs derived vs advisory), not technological.
- **Embodied:** store ports + provider resolution (`app/stores/provider.py`), embedding identity
  gate + reconcilable fallback (ADR-0023 posture), `docs/ENVIRONMENTS.md` (vault names mutable,
  never hardcoded), import-direction gate (ADR-0013). **Violated:** the `activeVault` scalar leak
  (SBS transition debt D1) — a file-root standing in for a context set; WSP seams are the remedy.
- **Operational failure:** replacing a provider forces a semantic migration (the CW-6/#2297 class);
  multi-vault built on `activeVault` would harden a technology accident into an architecture.
- **Evaluation hook:** import-boundary tests (ADR-0013 gate); the no-`activeVault`-in-target-contracts
  CI rail (SBS Phase 2); embedding-identity gate tests (CTI-1).
- **Belongs in:** architecture docs + CI.

### C-11 · A law without a probe is not a law

Every principle, invariant, and contract in this system carries an executable evaluation hook — a
test, gate, doctor check, or golden set — and the verification layer itself is verified (an
intentional violation must fail). A normative statement with no probe is filed as a gap, not
shipped as governance.

- **Derivation:** doctrine §4 ("a doctrine statement with no contract/test path is philosophy, not
  architecture") + the owner's verify-the-verifier rule, earned twice: the false-green CI incident
  (`PYTEST_DISABLE_PLUGIN_AUTOLOAD` silently dropping a plugin) and the 2026-06 observability audit
  (always-on signals false-green, ~1.4/5). This is the constitution's self-application clause: it
  is the reason every C-principle above names its hook, and the reason `Rejected candidates`
  exists — candidates that could not name a probe were rejected *by construction*.
- **Embodied:** the invariant registry's enforcement-category discipline; `harness-selfverify` CI
  gate; strict-xfail + `require_future_runtime`'s honesty rule (only true absence xfails; breakage
  fails); the `Verify:`-marker contract on every Acceptance Criterion.
- **Violated:** `standards_are_adapters` remains the registry's one `doc_only` row without a
  mechanical probe (review-time by declaration — acceptable only because it is *declared*); any
  future doc that states a MUST without a hook.
- **Operational failure:** closed-on-green rot — a green suite that verifies nothing is worse than
  a red one, because it spends trust it no longer earns.
- **Evaluation hook (self-referential, deliberately):** harness-selfverify's
  intentional-violation fixtures; a registry-coverage check (every registry row names a test path
  or an explicit TBD with owner) — proposed as a docs_guard extension in #2781's follow-ups.
- **Belongs in:** CI + governance + docs.

---

## Adversarial pass (letter-vs-intent attacks, recorded per the issue's validation contract)

For each principle, the strongest design found that satisfies the letter while violating the
intent, and the wording that now blocks it:

| # | Attack | Disposition |
|---|---|---|
| C-1 | "We never *change* authority_state — we just always read the memory item when answering." Laundering standing through *use* rather than mutation. | Blocked by C-2's use-time corollary (`evidence_role_in_context` may be downgraded, never upgraded above the intrinsic role) — use-time standing is bounded, not just storage-time. The corollary was added to C-2's statement and hooks as a result of this attack. |
| C-2 | Prefilter applied, but the *reranker* hook receives the full corpus "for context." | Wording says ranking "can never reintroduce the excluded"; #2772 brief adds the rerank-containment assertion. Hook, not just prose. |
| C-3 | Bundle present but fields populated with defaults ("scope: default") — meaning present syntactically, absent semantically. | Conceded as residual risk: schemas enforce shape, not truthfulness. Mitigation lives in C-1 (defaults cannot upgrade standing) and capture-time stamping (`capture_stamps_scope`). Recorded honestly rather than over-claimed. |
| C-4 | "The second store isn't a *truth*, it's a cache" — declared cache, but written directly by a second writer. | P-6 gates *writers*, not declarations: a cache with its own writer fails the gate regardless of what it is called. |
| C-5 | Mutation emits an event *eventually* (async fire-and-forget) — letter of "has an event," intent of atomicity lost. | Wording: "commits atomically with its event"; P-2 asserts per-step, not eventual, correspondence. |
| C-6 | Guard asserted at the seam but the seam grows a `force=True` kwarg for "internal" callers. | Named-escape rule: bypasses live on ONE registered list (bootstrap actions) that P-1's static gate reads; an unregistered kwarg bypass fails the gate. |
| C-7 | A "read" endpoint enqueues an event that *later* causes the write — read stays pure, mutation happens anyway. | Transition catalog counts *initiation*: the enqueue is the initiator. P-3's spy covers outbox inserts on GET paths. |
| C-8 | Failure surfaced as a DEBUG-level log line — technically not silent. | Hook definitions require surfacing in the *health contract* (the WriteGuard snapshot source) or a failing test, not any log line. |
| C-9 | Schema-validated LLM output where the schema is `{"answer": "string"}` — typed in name only. | Registry requires *closed* schemas + the golden-set gate scores decisions, not parses. A vacuous schema fails the golden set even when it validates. |
| C-10 | An "adapter" that leaks provider enums into a core contract field ("model: text-embedding-3"). | SBS failure mode "provider-specific concepts leak into core semantics" + CTI-1 identity gate; the embedding-identity fields live in DRI provenance, not core semantics. |
| C-11 | Every law has a probe; the probes run in a suite nobody gates on. | Placement is part of the hook definition: PR-gating (`not pg`) or dispatch lane, named per probe. A probe without a named lane is an unfilled hook. |

## Rejected candidates (near-principles that failed the bar, kept to prevent re-litigation)

- **"Local-only / no egress."** Contradicts ratified posture (ADR-0023: Ollama-primary,
  governed Gemini fallback, reconcilable identity). The real principle is C-3/C-10: egress is
  *governed and provenance-stamped*, not forbidden. Absolutism here would be taste, not derivation.
- **"Event-source everything."** The vault is canonical and not event-sourced; the log is the
  journal of the *derived* plane (C-5's scope is precise). Extending event-sourcing to V would
  fight iCloud/Obsidian reality for no correctness gain — the formal model survives without it.
- **"Zero-trust agents."** The doctrine's actual stance is *low-trust with governed promotion* —
  agents are guests whose contributions can earn standing. Zero-trust forecloses the product.
- **"Immutability everywhere."** Q1/Q3 already protect what must not be destroyed; human notes are
  *meant* to be edited. Immutability is a per-class property (receipts, decisions, events), not a law.
- **"Fail fast, always."** Receipt-on-failure appends from exception handlers are working as
  designed (formal model §2.3); T-capture's vault-write-then-500 is deliberate
  (receipt-before-*ack*, not before-write); F-C is a live owner decision weighing availability.
  C-8 (nothing *silent*) is the true invariant; "fast" is a tactic.
- **"Single-user by design."** Product posture (one human per instance), not architecture law —
  and explicitly NOT a cap on agents. Enshrining it would foreclose the dual-model direction.
- **"Human-first / TCD."** Governs the *builder system* (`AGENTS.md`), not the runtime
  architecture. Constitutionalizing it here would blur the builder/product boundary that
  `AGENTS.md` itself draws.
- **"One storage substrate."** Consolidating PG/SQLite/JSONL would erase failure-domain isolation
  (formal model §5) — the plurality is load-bearing, per-domain blast radius is a feature.
- **"Split the repo by constituent."** Monorepo-until-forcing-function is the ratified posture
  (ECOSYSTEM_SOS_MODEL §4); a repo topology is C-10 "technology," not architecture.
- **"GC by age/TTL."** The ratified direction is event-triggered relevance decay + cold storage,
  not deletion schedules (D-2/D-6). A TTL law would contradict two owner decisions.

## SBS reconciliation (binding)

- **Conforms:** C-1…C-9 restate, at constitutional altitude, invariants the SBS assigns to GOV
  (C-1, C-6), RCA (C-2), SIP/DRI (C-3), PDM (C-4, C-5), CAO/EXE (C-9), OEF (C-8, C-11); the
  principles never move ownership. C-10 *is* the SBS's decomposition principle restated.
- **Extends:** C-7's "enumerable mutation surface" makes the formal model's transition catalog a
  standing documentation obligation (a living artifact OEF probes against) — new, flagged to CES.
  C-11's registry-coverage check is a new OEF self-fitness rule — flagged to CES.
- **Proposes reshaping:** none. The apex-model section records the ADR-0043 lineage; the glossary
  enactment completed under closed issue #2891. This document performs no rename and changes no
  glossary entry.

## Ratification decision (owner)

**Problem:** this constitution is advisory. Unratified, it will be cited informally, drift, and
become a second half-authority — the exact failure C-11 warns about.

**Options:**
1. **Ratify as a subordinate foundation doc** — lives under `docs/foundation/` beside the doctrine;
   doctrine stays superior; each C-principle's *pending* hooks (P-1…P-7, registry adoption) become
   the enforcement backlog via `docs-to-issue`.
2. **Ratify principles individually** — accept a subset now (e.g. C-1…C-9, defer C-10/C-11),
   marking the rest candidate.
3. **Leave candidate indefinitely** — no authority, citable as analysis only.

**Consequences:** (1) one coherent law layer with an executable enforcement path; costs one review
pass now and makes future disagreements adjudicable ("which principle and which hook?").
(2) preserves optionality, fragments citation — half the value of a constitution is that it is
*whole*. (3) zero cost now; guarantees the next architecture pass re-derives this from scratch,
which is exactly the Fable-window value this epic existed to bank.

Recommendation: (1), with the explicit note that ratification adopts the *principles*, not the
violation inventory (which ages) — anchors and incident lists are evidence, re-verifiable, never
themselves law.

**Owner decision (2026-08-02, epic #2778 chat decision):** held — do **not** ratify. `State`
above stays `CANDIDATE`; this document continues to govern nothing and silently changes no owner
doc's claims, per its own opening line. None of options (1)/(2)/(3) above is selected; ratification
remains an open, unscheduled owner call for a future pass.

## Related docs

- `docs/foundation/00-yggdrasil-doctrine.md` (superior; commitments cited by C-1/C-2/C-3)
- `docs/architecture/runtime-semantics.md` · `docs/architecture/formal-model.md` (RESEARCH-01/02 — the derivation base)
- `docs/testing/invariant-synthesis-2026-07.md` (RESEARCH-03 — the P-1…P-7 hooks C-5/C-6/C-7 commit to)
- `docs/architecture/evolution-graph.md` (RESEARCH-04 — the sequencing this law layer serves)
- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` (CW/I/RQ derivations)
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` + `docs/architecture/SBS_*` (boundary ownership; Part 8 failure modes cited throughout)
- ADR-0043 + `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` (apex model); ADR-0013/0023/0032/0036/0042
