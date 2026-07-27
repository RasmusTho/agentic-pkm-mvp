State: Accepted (owner acceptance 2026-07-07 — "proceed until the design is broken down to ready issues"). **Amended 2026-07-27 (A1, owner decision):** a CKM-informed orchestrator role may drive delivery of epics and comparable work with exactly the authority Claude Code and Codex already hold. The amendment separates the acting role from the knowledge model — §6's candidate-until-confirmed lifecycle and the §7 authority posture are unchanged, §2's gap→issue writeback deferral is partially lifted, and automated orchestration carries a named entry condition tied to ADR-0064 §8. Marked inline at §1, §7, and `When to revisit`. Enacts the Capability Knowledge Model (CKM, codename Kvasir) as a Builder System subsystem and records the five owner decisions OD-K1..OD-K5 from the grounding research. Docs + backlog enactment only; no runtime/product behavior changes here.
Doc role: Decision record (ADR)
Authority: Authoritative for the existence, scope, authority posture, store choice, naming, and confirmation policy of the CKM subsystem. It does NOT define implementation internals (schema field lists, prompts, aggregation weights) — those live in the specification directory `docs/CAPABILITY_KNOWLEDGE_MODEL/` and are refined by delivery.
Owner: BuilderOps governance / Architecture spine (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the CKM's existence, authority posture, or plane placement is reversed).
Source of truth: This ADR plus `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md` (advisory grounding) and the specification directory `docs/CAPABILITY_KNOWLEDGE_MODEL/`.

# ADR-0057: The Capability Knowledge Model (Kvasir) — a projection-only Builder System subsystem

**Date:** 2026-07-07
**Status:** Accepted (owner acceptance, 2026-07-07)

---

## Context

Development knowledge about the Yggdrasil platform is fragmented across code, git history, PRs, Issues, ADRs, specs, tests, CI, and AI sessions; no artifact describes the system itself (which capabilities exist, how mature each is, where the gaps are). The static `docs/architecture/traceability-matrix.md` (#2535) is the hand-maintained precursor; it does not scale and does not assess maturity.

The research grounding `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md` (2026-07-07) verified the concept against five prior-art fields (developer portals, engineering intelligence, architecture KM, knowledge graphs/MBSE, AI-native memory) and found the composition — **capability nodes ← typed evidence edges → synthesized explainable maturity, continuously maintained** — to be genuine whitespace, with the assurance-case (GSN) claim←evidence pattern as the nearest conceptual precedent. It also established that this is a **digital shadow**, not a digital twin (no automated writeback), and surfaced five owner decisions.

## Decision (owner, locked 2026-07-07)

### 1. The CKM exists, as a Builder System subsystem

The Capability Knowledge Model enters the Builder System as the subsystem that continuously constructs and maintains an evidence-backed model of the platform's capabilities and their maturity. It lives entirely in the BuilderOps plane (ADR-0010): it reads product-plane and builder-plane artifacts as evidence; it writes only `analytical`/`projection`/`receipt` objects.

**Amended 2026-07-27 (A1):** this write-class restriction continues to bind the knowledge model itself. The CKM-informed orchestrator role admitted in §7 is a builder agent, not a CKM writer: its effects (issues, branches, PRs, dispatch claims) are produced through the ordinary builder surfaces under the ordinary gates, and never as CKM object writes.

### 2. OD-K1 — Build the MVP now; defer drift detection

Build: capability registry seed + artifact ingestion + evidence linking + maturity assessment + gap/missing-evidence detection + projections/query + a static-HTML development overview (the MVP scope in `docs/CAPABILITY_KNOWLEDGE_MODEL/`).

Defer: prescriptive-vs-descriptive **drift detection** (FR-8 of the SRS) until the Correctness Kernel's schema/writer registry substrate lands, at which point drift becomes a cheap diff over declared state — the same rationale as the Builder Capability Portfolio's "architectural regression detection = defer until KERNEL-08" ruling. Also deferred: closed-loop writeback (gap→issue automation), predictive maturity, cross-repo federation.

### 3. OD-K2 — Codename Kvasir; descriptive name primary

The subsystem's Norse codename is **Kvasir** (born from the synthesis of all knowledge). The ADR-0043 name register gains the row `Kvasir → Capability Knowledge Model (builder-plane subsystem), taken (ADR-0057)`. The descriptive term **Capability Knowledge Model (CKM)** remains primary in specs, code, and issues; Kvasir is the register/codename entry, consistent with how constituents are named.

### 4. OD-K3 — `evidence_kind` is builder-plane and orthogonal to runtime `evidence_role`

The CKM's evidence typing field is named `evidence_kind` and is a builder-plane **analytical** typing only. The orthogonality contract: an artifact being CKM evidence about a capability **never** changes that artifact's product-plane `evidence_role`, `authority_state`, or `source_role`; CKM code and schemas must never read or write the runtime `evidence_role` field, and no CKM output may be consumed as a runtime admissibility signal. A fitness check protecting this contract ships with the store slice.

### 5. OD-K4 — Extend the existing BuilderOps SQLite store; no graph database

The Capability Evidence Graph is stored relationally in the existing BuilderOps store substrate (`app/builderops/store.py` + `runtime/builderops/*.sqlite3` pattern), with graph shape expressed as tables + views/queries. Rationale: the substrate exists, is laptop-friendly (no heavy deps by design), tested, and the graph is small (hundreds of capabilities, low tens of thousands of evidence edges). The CEG is **derived and rebuildable**: dropping the CKM tables and re-running seed + ingestion must reconstruct it; no CKM-only fact is canonical.

### 6. OD-K5 — Inferred material is candidate until confirmed

Capabilities and evidence edges produced by inference (LLM association, capability-existence hypotheses) enter with lifecycle `candidate` and are visibly labeled as such in every projection. Promotion to `confirmed` requires an explicit human confirmation receipt. Deterministic-linker edges (test↔code, matrix rows, ADR references) enter as `confirmed` directly because their basis is mechanical and reproducible. (This is deliberately more conservative than the Episode opt-out precedent: CKM output feeds agent planning, so unconfirmed inference must not silently look like ground truth.)

### 7. Authority posture (load-bearing)

Every CKM output is a projection: self-identifying as derived, carrying provenance (inputs, method, model/provider where inferred) and an ingestion watermark, and never functioning as a source of truth. Maturity is always a visible, cited 7-dimension vector; any scalar aggregate is a labeled convenience computed by a published transparent function. Crossing from a CKM observation to action (filing an issue, editing a doc) is a human/agent decision outside the CKM, never a CKM effect.

**Amended 2026-07-27 (A1) — the acting role is admitted, the knowledge model is unchanged.** The owner ruled that CKM may orchestrate delivery of epics and comparable work "exactly as Claude Code and Codex may", as one step in raising the level of automation. That ruling is enacted by *separating the model from the role*, not by weakening the authority posture:

- **The Capability Knowledge Model remains projection-only.** Every clause above still holds for it: derived, provenance-bearing, never a source of truth, and never a runtime admissibility signal (§4). §6's candidate-until-confirmed lifecycle is **unchanged** — its rationale (unconfirmed inference must not silently look like ground truth) becomes *more* load-bearing once an orchestrator reads it, not less.
- **A CKM-informed orchestrator role is admitted as a builder agent.** It reads CKM projections and acts. Its authority is exactly the authority Claude Code and Codex already hold — no more: it is bound by the Issue task contract, the branch-truth and publication boundaries, CI, and the review gate. Automation level rises; the gate chain does not move.
- **The sentence "never a CKM effect" is therefore preserved in substance.** Action remains a decision by an agent operating outside the knowledge model, under the normal builder gates. What changes is only that the agent may now be the one that reads CKM most closely.
- **Candidate inference may propose, not select unreviewed.** An orchestrator may act directly on already-governed work (an epic, a strictly valid `agent:ready` issue). Work originating from `candidate` CKM inference enters through the normal Issue contract, which is where it is confirmed — at the task-contract boundary rather than per evidence edge. This satisfies §6's intent with a cheaper gate, not a weaker one.

Consequently §2's deferral of closed-loop writeback (gap→issue automation) is **partially lifted**: an orchestrator may file and drive issues. The deferral of prescriptive-vs-descriptive drift detection, predictive maturity, and cross-repo federation stands unchanged.

**Entry condition (safety, not ceremony).** Automated orchestration must not begin while the CKM's own model access still resolves through Product routing, because that path can silently return a mock route (`app/builderops/ckm/semantic.py`; recorded as transition debt in ADR-0063 and sequenced in ADR-0064 §8). An orchestrator that can unknowingly receive fabricated analysis cannot be trusted to gate delivery. ADR-0064's migration order swaps accordingly: the CKM model-path migration precedes the model-inquiry migration.

## Constraints honored

- BuilderOps plane only (ADR-0010): no product/runtime behavior, schema, or authority change.
- Reuses — does not fork — the capability definition (`docs/CAPABILITY_CONTRACT_MODEL.md`) and the SBS decomposition (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md`) as the seed taxonomy.
- Mirrors the doctrine invariants: projection is not evidence; derived views are candidate, not truth; provenance survives derivation.
- Non-goals stand: not an ALM/task tool, no sprint/story-point machinery, no automatic writeback.

## Consequences

- Specification directory `docs/CAPABILITY_KNOWLEDGE_MODEL/` (this enactment's companion) defines the MVP as ten bounded implementation tasks; GitHub issues are created from it.
- `app/builderops/ckm/` becomes the implementation home; `tests/builderops/ckm/` its test home.
- The static `traceability-matrix.md` remains the human-authored control document; the CKM emits a generated projection of the same shape, and divergence between them becomes a visible signal (not an auto-edit).
- The ADR-0043 name register gains the Kvasir row.
- When the Correctness Kernel registry substrate lands, a follow-up ADR/issue set may enact drift detection (deferred FR-8).

## When to revisit

**Amended 2026-07-27 (A1):** admitting the orchestrator role is *not* one of the reversals below — it grants no authority to the knowledge model. A future move that made CKM inference itself authoritative (dissolving §6's candidate lifecycle, or letting an orchestrator act on unconfirmed inference without passing the Issue contract) **would** require a new ADR.

Supersede only if the owner reverses the CKM's existence, moves it out of the BuilderOps plane, grants it authority, or replaces the store substrate. Tuning (weights, prompts, seed grain, projection formats) is delivery-level and needs no ADR revision.

## References

- Grounding: [DEVELOPMENT_KNOWLEDGE_MODEL](../research/DEVELOPMENT_KNOWLEDGE_MODEL.md)
- Specification: [docs/CAPABILITY_KNOWLEDGE_MODEL/](../CAPABILITY_KNOWLEDGE_MODEL/README.md)
- Related ADRs: ADR-0010 (BuilderOps authority boundary), ADR-0043/0050 (name register), ADR-0029 (orthogonal roles — the `evidence_role` the CKM must not touch), ADR-0016 (contract-first, module-lazy)
- Precursors: [traceability-matrix](../architecture/traceability-matrix.md) (#2535), [BUILDER_CAPABILITY_PORTFOLIO](../development/BUILDER_CAPABILITY_PORTFOLIO.md) (defer-drift rationale)
