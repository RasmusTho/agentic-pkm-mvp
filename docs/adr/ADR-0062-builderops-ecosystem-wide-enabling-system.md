State: Proposed (owner drafting 2026-07-14 — core decision "ecosystem-wide now, general-purpose later" taken; composite pending owner ratification). Re-scopes the Builder System / BuilderOps from a Mimer-repo-bound enabling system to an ecosystem-wide enabling system serving all Yggdrasil constituents, with multi-repo operation first-class and physical code extraction deferred behind explicit triggers. Docs/governance decision only; no runtime/product behavior changes here.
Doc role: Decision record (ADR)
Authority: Authoritative for the scope, multi-repo posture, operating-plane state home, domain-neutral seam contract, and builder-specific split triggers of the Builder System. Layers on ADR-0010 (authority seam) without amending it. Does NOT define implementation internals — those follow in a specification directory and bounded issues.
Owner: BuilderOps governance / Architecture spine (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the ecosystem-wide scope, the multi-repo posture, or the layered relationship to ADR-0010 is reversed).
Source of truth: This ADR plus ADR-0010 (authority seam it layers on) and the forthcoming specification directory. The Fable + GPT/Codex model inquiry (inquiry_id `inq_20260714T164854Z_ba434186`, consensus) and the fact-checklist verification are advisory grounding, not authority.

# ADR-0062: BuilderOps as an ecosystem-wide enabling system

**Date:** 2026-07-14
**Status:** Proposed (owner drafting)

---

## Context

The Yggdrasil ecosystem is now multi-repo: Mimer (knowledge-and-cognition, `app/`), Heimdal (sensor), and a private-bindings proto are constituents, and Bifrost is a separate iPhone client repo (Swift). The Builder System / BuilderOps — the high-autonomy agentic development platform governed by the TCD (Total Cost of Development) capability-routing policy — is classified as an ISO/IEC/IEEE 15288 **enabling system** *around* the product, never an ecosystem constituent (ADR-0010; `docs/architecture/SBS_OPERATING_MODEL.md §3`).

Two separations were possible; only one was done. The **authority/classification** separation is settled: ADR-0010 fixes the seam ("BuilderOps governs the building system; the repo governs product/runtime truth; no silent authority transfer"). The **physical/operational** separation is not: the builder is de-facto Mimer's builder. Delivery skills are repo-implicit (`gh` without `--repo`); the SBS operating model is "repo-silent"; `.codex/skills` and `AGENTS.md` are self-admitted "bootstrap/executable copies pending a not-yet-designed export/promotion pipeline." Transition debt D18/D19 and audit RQ3 flag that the builder has no multi-repo awareness even though the ecosystem already is multi-repo.

This decision was grounded by (a) an independent two-reviewer model inquiry (Fable `claude-fable-5` + GPT/Codex `gpt-5.6-sol`) that reached consensus across a multi-round adversarial debate plus two additional independent Fable drafts, and (b) a fact-checklist verification of where builder state physically lives and how coupled it is to the Mimer repo. The models' single load-bearing correction was **"the state is the split"**: sequencing is right for builder *code* but the operating-plane *state* home must be decided now, not deferred with the code.

### Verified facts (fact-checklist, 2026-07-14)

- **Authoritative operating-plane state is a local SQLite DB** (`app/builderops/store.py`; default `runtime/builderops/builderops.sqlite3`). Leases, idempotency keys, worklogs, LearningSignals, PromotionIntents, receipts, and TCD/transition history are rows in that one file. The external Markdown "vault" (`BUILDEROPS_VAULT_ROOT`, iCloud) is optional and **never authoritative** — it is artifacts/projections. The SQLite Confinement Invariant (`app/builderops/config.py::validate_db_path_outside_vault`) keeps the DB out of the sync vault.
- **State is highly movable (low relocation cost).** `app/builderops` has no dependency on product-runtime code in the store/lease engine; the only inbound product dependency is one LLM import inside CKM/Kvasir (`app/builderops/ckm/semantic.py`). Relocation is a data copy plus an env-var config change (`BUILDEROPS_DB_PATH` / `BUILDEROPS_STATE_DIR`, already first-class inputs). No product refactor is required.
- **The real coupling is path, not code.** With the store-path env vars unset (the live state on the runtime host), the CWD-relative default binds each store to whatever checkout/worktree it runs in, fragmenting the single-host store into N uncoordinated SQLite files whose lease tables do not see each other. This is a live correctness defect tracked separately as issue #3686 (a prerequisite for consolidating the state home).
- **Writer topology is single-host, multi-agent.** SQLite transactions (`BEGIN IMMEDIATE`, fencing `lease_id`, TTL) serialize many concurrent agents on one host; cross-host is explicitly out of scope and advisory-only. The mac mini is the sole runtime host.

## Decision

### D1 — BuilderOps is re-scoped to an ecosystem-wide enabling system

The Builder System serves the whole Yggdrasil ecosystem (Mimer + Bifrost + Heimdal + future constituents), not one repo. Multi-repo operation is first-class. It remains an enabling system, not a constituent; ADR-0010's authority seam is untouched and reaffirmed per-repo.

### D2 — Sequencing: seam and state now; code extraction deferred behind triggers

Logical re-scope (schemas, contracts, docs, skill contracts) and the **operating-plane state home** are pulled forward now. Physical extraction of builder *code* into its own repo stays deferred until a builder-specific trigger (D6) fires. "General-purpose (non-Yggdrasil tenant) later" is not built now, only kept unblocked.

### D3 — State home: keep the transactional SQLite store; pin it host-stable; keep Markdown as projection

The authoritative store stays the existing local SQLite operating plane — it is already transactional, so we neither build a new transactional service (over-provisioned at single-host scale) nor promote the git/Markdown vault to authority (it is correctly a non-authoritative projection). The state home is decoupled from the Mimer checkout by pinning `BUILDEROPS_DB_PATH` / `BUILDEROPS_STATE_DIR` to **one host-stable location outside every checkout**, treated as a dedicated builder-state home (its own backup/lifecycle unit). This consolidates the per-worktree fragmentation (#3686 is the enabling correctness fix) and preserves the SQLite Confinement Invariant. Escalation to a networked transactional store is deferred until multi-host operation is real (trigger T2/T4 in D6).

### D4 — Domain-neutral seam to build now (no tenant abstraction)

- **Mandatory fully-qualified `RepoRef`** on every skill invocation, lease, worklog, receipt, LearningSignal, and PromotionIntent. A CI/lint gate fails repo-implicit operations (`gh` without an explicit target). This single item retires the D18/D19 repo-silent hazard.
- **Per-repo Delivery Target Manifest** declaring stack, build/test commands, review/merge policy, the per-repo definition of "accepted delivery," and receipt destination. Mimer-specific knowledge moves from code into data; onboarding a constituent = adding a manifest, not code.
- **Export/promotion as a contract, not a platform:** versioned, one-way (builder → repo via PromotionIntent + explicit repo-side acceptance; repo → builder only via read-only projections). Retires the `.codex/skills` / `AGENTS.md` bootstrap-copy drift by construction. Implementation may remain a script.
- **Versioned record schemas with a `scope` field** held constant at `yggdrasil` today — a field, not an abstraction layer.
- **Hybrid receipts:** authority stays in the host-stable store; **read-only BuilderOpsReceipt projections are committed into each consumer repo** as in-repo evidence, preserving "each repo governs its own truth."
- **Excluded now (the premature-generality traps):** tenant auth, per-tenant isolation, plugin/extension frameworks, config-driven policy engines, capability-negotiation frameworks. Unsupported operations fail loudly and never fall back to Mimer-default behavior.

### D5 — TCD stratified across heterogeneous repos

TCD routing keys on `(repo, stack, task-class)` with hierarchical priors (global → stack → repo) and an explicit cold-start policy for new constituents. Unstratified pooling of Python (Mimer) and Swift (Bifrost) learning signals would systematically mis-route (Simpson's-paradox effect). The per-repo "accepted delivery" definition (D4 manifest) is a TCD prerequisite, since it is the metric's denominator. **The one near-irreversible risk:** onboarding a second repo before LearningSignals carry `repo`/`stack` provenance silently poisons the learning plane; provenance tagging must land before Bifrost onboards.

### D6 — Builder-specific split triggers (T1–T5); any one forces physical code extraction

Distinct from, and deliberately cheaper to trip than, the product-constituent split triggers:

- **T1 Distribution:** a consumer repo needs to run builder tooling without cloning the Mimer monorepo.
- **T2 Cadence/credential divergence:** a builder change must ship independently of a product release, or builder needs multi-repo credentials/scopes that must not live in a product repo's trust zone.
- **T3 Blast-radius incident:** any concrete incident where product-repo operations damage or block builder operation across repos (or vice versa).
- **T4 Realized multi-host need:** builder must run authoritative state across more than one host.
- **T5 First external tenant:** the general-purpose moment; subsumes all others.

Until a trigger fires, the builder stays in the monorepo behind the hard internal seam.

### D7 — Layer a new ADR over ADR-0010; do not amend it

ADR-0010 is not reopened. This ADR layers on it and adds:
- **Pluralization:** "the repo governs product/runtime truth" → **each** consumer repo is sovereign over its own product truth.
- **A non-transitivity clause:** the builder may not use its standing in repo A to alter truth in repo B; PromotionIntents are per-repo-addressed and per-repo-accepted.
- **A named single-tenant invariant:** the assumptions permitted to be baked in now are enumerated — single store namespace, single identity/secrets domain, single owner, single runtime host — so later generalization is a search target, not archaeology.

## Owner decisions recorded

1. **Scope (D1):** ecosystem-wide enabling system. — taken.
2. **Sequencing (D2):** seam + state now, code extraction trigger-gated. — taken.
3. **State home (D3):** host-stable pinned SQLite + Markdown projection; networked store deferred. — **pending ratification** (recommended by fact-grounded analysis).
4. **Onboarding gate:** whether onboarding Bifrost/Heimdal requires repo-explicit operations + promotion-pipeline v1 *before* delivery (recommended), or a docs-level seam suffices. — **pending ratification**.
5. **Schema authorization (D4/D5):** mandatory `RepoRef` + `scope`/`stack` provenance on all records, and backfill policy for existing records. — **pending ratification**.
6. **Split triggers (D6):** adopt T1–T5 as normative. — **pending ratification**.
7. **ADR-0010 handling (D7):** untouched, new layered ADR (recommended) vs. clarifying errata. — recommended as stated.
8. **Governance:** the grounding inquiry accepted a Fable-authored artifact for three consecutive review rounds (self-review bias); the reviewers ask whether the owner requires independent non-Fable ratification before this ADR is accepted. Mitigated by three independently-converging Fable drafts plus GPT/Codex convergence and the independent fact-checklist, but recorded.

## Constraints honored

- BuilderOps plane only (ADR-0010): no product/runtime behavior, schema, or authority change in this ADR.
- SQLite Confinement Invariant preserved (`app/builderops/config.py::validate_db_path_outside_vault`).
- Single-host writer topology retained; no cross-host distributed locking introduced.
- No tenant abstraction, isolation, or plugin framework built now (D4 exclusions).
- Existing per-worktree store data must not be silently discarded when the state home is consolidated (#3686 constraint).

## Consequences

- **Enacts as docs + backlog, not runtime:** this ADR changes no product or builder runtime behavior on its own. Enactment follows as bounded issues from a specification directory.
- **Follow-on doc edits:** `docs/architecture/SBS_OPERATING_MODEL.md §3` (Builder System boundary) and `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md` gain the ecosystem-wide scope, the multi-repo posture, the state-home contract, and the T1–T5 trigger list. The ADR-0043 name register is unaffected (no new codename).
- **Prerequisite:** issue #3686 (host-stable store path) is the correctness fix that makes the D3 state-home consolidation safe; it should land before Bifrost onboards.
- **Retires debt:** D18/D19 (repo-silent operations, bootstrap-copy drift) are retired by the D4 seam (RepoRef gate + promotion contract).
- **Reversibility:** logical re-scope and state relocation are low-cost and reversible (data move + config). Physical code extraction remains deferred and trigger-gated (D6), so no expensive, hard-to-reverse step is committed by this ADR.

## Source Docs

- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md` (authority seam this ADR layers on)
- `docs/architecture/SBS_OPERATING_MODEL.md` (Builder System boundary)
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md` (builder architecture)
- `docs/builderops/BUILDEROPS_VAULT_STORE.md` (store mechanics, confinement invariant)
- `AGENTS.md :: Total Cost of Development` (TCD routing policy)
- Related issue: #3686 (host-stable BuilderOps store path — D3 prerequisite)
