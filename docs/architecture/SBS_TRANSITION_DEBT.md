State: Transition debt register; entries are seeded from target SBS risk categories. Items marked `to verify` are architecturally plausible but not yet confirmed by code inspection.
Doc role: Transition debt register
Authority: Owns known and likely deviations from the target SBS while current runtime remains in transition.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-22
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/architecture/SBS_FITNESS_RULES.md, docs/architecture/SBS_OPERATING_MODEL.md

# SBS Transition Debt

This register names deviations and likely deviations from the target SBS. Its lifecycle is owned by `docs/architecture/SBS_OPERATING_MODEL.md` §10: every target-state slice either reduces a row, adds a bounded row, or states no debt effect.

**`to verify`** means the debt category is architecturally plausible but has not been confirmed by code/doc inspection. Do not assert a debt is confirmed in code unless it was inspected; record the unverified extent as `to verify` rather than overstating.

Each debt carries the full schema across two keyed tables (joined by debt ID): **triage** (boundary, current location, risk, severity, status) and **resolution & ownership** (containment, desired end state, owner, follow-up issue, fitness rule).

## Triage

| ID | Debt | Violated target boundary | Current location | Risk | Severity | Status |
|---|---|---|---|---|---|---|
| D1 | Active vault / vault path used as global architecture concept | WSP vs HKA/EBF/PDM | Broad runtime active-vault/path usage (extent `to verify`); first read-side seam at `ActiveContextResolver` (#2356). | Scope collapses into storage/source location. | High | Containing — first seam delivered; broad adoption open. |
| D2 | Direct durable writes without governed DecisionToken | GOV vs HKA/MEM/EXE | Representative capture path now via `GovernedWriteAdapter` (#2357/PR #2371); other durable write paths `to verify`. | Governance becomes advisory; accountability can be skipped. | High | Containing — first adapter delivered; broad enforcement open; owner-doc writeback #2375. |
| D3 | Persistence/store construction outside PDM ownership | PDM vs all state owners | First seam routes `app.store.object_store.ObjectStore` through `app.stores.resolve_object_store_port` (#2358); remaining direct store/DSN construction includes `app/stores/provider.py`, `app/stores/postgres.py`, `app/services/outbox.py`, `app/store/relation_index.py`, `app/store/vector_store.py`, and `app/store/membership_store.py`; broader extent `to verify`. | Storage technology leaks into semantics; migrations scatter. | High | Containing — first StorePort seam delivered; remaining direct construction open. |
| D4 | Retrieval result shape not formalized as ContextBundle | RCA vs HIX/CAO/MEM/HKA | Production retrieval bundle emission now runs a ContextBundle conformance check (#2359); broader retrieval/search outputs remain `to verify`. | Retrieval output treated as truth or prompt stuffing. | Medium | Containing — first conformance rail delivered; broader adoption open. |
| D5 | Memory records lacking explicit review/provenance lifecycle | MEM vs GOV/HKA/RCA | Current review-entry and promoted-recall outputs now have a MemoryRecord adapter (#2360); broader memory classes and archive/forget lifecycle remain `to verify`. | Memory becomes hidden instruction or shadow knowledge. | High | Containing — first MemoryRecord adapter delivered; broader lifecycle open. |
| D6 | Agent runtime performing side effects without EXE/GOV seam | CAO vs EXE/GOV | `to verify` — agent tool/side-effect call sites not yet inventoried. | Agents bypass authorization and receipts. | High | Open. |
| D7 | Watcher/sync event envelope lacking delivery semantics | EBF/SFC vs DRI/HKA/GOV/OEF | First seam wraps the `watcher.run` path (`app.watcher.events.WatcherRunEvent`) through `app.sfc.replication_envelope.wrap_as_replication_envelope` (#2362). `docs/contracts/REPLICATION_ENVELOPE.md` is the current owner contract for watcher/source-observation delivery semantics, naming idempotency, replay/backfill cursor, ordering/causal placeholder, delivery/failure visibility, and conflict-staging semantics; `SourceObservationEvent` is the observed-source payload inside that envelope, not a separate delivery contract today. Other watcher/sync event paths remain `to verify`. | Events drop, reorder, or fail replay/backfill invisibly. | Medium | Containing — first ReplicationEnvelope seam delivered (single-node/no-op per ADR-0020); broader adoption open. |
| D8 | Provider-specific assumptions leaking into core semantics | EBF/DRI/RCA vs HKA/SIP/GOV | `to verify` — provider/model/tool fields in core contracts not yet audited. | Vendor/model/tool choices become architecture. | Medium | Open. |
| D9 | OEF/fitness rules not yet enforcing SBS boundaries | OEF/CES vs all subsystems | Two CI rails shipped in `tests/architecture/test_sbs_fitness_rules.py`: active-vault identity (#2363/PR #2376) and non-HKA contracts disclaiming direct HKA mutation while routing through GOV (#2381); remaining P0/P1 rules manual-review-now (token-dependent P0 deferred until `DecisionToken`/`AuthorityReceipt` exist on enough paths). | Architecture remains documentation-only and drifts. | Medium | Containing — two CI rails shipped; further P0/P1 CI promotion open. |
| D10 | SIP projection / derived representation could become irreplaceable shadow store | SIP/DRI vs HKA/GOV | `to verify` — rebuildability of semantic projections/derived records from source anchors not yet verified. | Semantic projections carry unrecoverable meaning. | High | Open. |
| D11 | CES overloaded into the whole Builder System | CES vs Builder System / Product SBS | Historical and current docs may use CES as shorthand for architecture stewardship while builder agents, repo-local skills, issue delivery, BuilderOps records, release workflows, and TCD routing are broader Builder System concerns. | Builder workflows get misclassified as Product SBS runtime subsystems or CES silently becomes a development control plane. | Medium | Containing — Builder System boundary model resident in `SBS_OPERATING_MODEL.md`; #2422 reconciles CES wording and adds manual fitness coverage. |
| D12 | Builder learning and TCD signals not uniformly captured across all workflows | Builder System vs Product runtime memory / OEF | Builder Learning and TCD governance loop is defined in `SBS_OPERATING_MODEL.md`; current skills cover hot-path learning, issue intake, delivery, verification, and release/promotion routing, but uniform metric capture and mechanical completeness checks remain `to verify`. | High-cost or repeated builder failures may remain in chat context, disappear from receipts, or be over-promoted into runtime/user memory instead of governed Builder destinations. | Medium | Containing — loop and allowed destinations defined; mechanical capture coverage open. |

## Resolution & ownership

| ID | Containment | Desired end state | Owner | Follow-up issue | Fitness rule |
|---|---|---|---|---|---|
| D1 | Route new work through ActiveContextSet; treat vault/source binding as implementation detail. | All context binding flows through `ActiveContextSet`; no public contract outside WSP carries active-vault/path identity. | WSP | #2356 (first seam, closed); broad adoption unfiled — file when widened | "No global `activeVault` … outside WSP/EBF/HIX adapters" |
| D2 | Use GovernedWriteProtocol for authority-bearing durable mutations. | Every authority-bearing durable write carries a pre-mutation `DecisionToken` and post-mutation `AuthorityReceipt`. | GOV | #2357 (closed); owner-doc writeback #2375 | "No authority-bearing durable write without GOV DecisionToken and receipt" |
| D3 | Require StorePort and no private DSN/store construction in new work. | Platform persistence resolves through `StorePort`; PDM owns DSNs, migrations, lifecycle. | PDM | #2358 (first seam); broad adoption unfiled — file when widened | "No PDM bypass for platform persistence/store resolution" |
| D4 | Use ContextBundle for scoped candidate evidence with non-authority posture. | Retrieval emits `ContextBundle` with scope + provenance; RCA never writes HKA. | RCA | #2359 (first conformance rail) | "Retrieval becomes truth" failure mode; ContextBundle candidate-only |
| D5 | Use MemoryRecord with review state, provenance, confidence, staleness, correction, forgetting, and GOV promotion path. | Memory carries review/provenance; promotion to HKA only via GOV. | MEM | #2360 (first adapter) | "No memory promotion to HKA without GOV" |
| D6 | Route side effects through ExecutionRequest with DecisionToken reference. | CAO coordinates cognition only; all side effects via `ExecutionRequest` through EXE after GOV. | CAO / EXE | #2361 | "No direct tool side effects from CAO without GOV/EXE" |
| D7 | Use the ReplicationEnvelope delivery contract before widening sync; keep SourceObservationEvent as the observed-source payload unless/until an EBF payload contract is scheduled. | Watcher/sync events carry idempotency, ordering/causal placeholders, replay/backfill, and failure visibility through the SFC-owned `ReplicationEnvelope` contract. | SFC / EBF | #2362 first seam; #2411 owner-doc reconciliation | "Event envelope lacks delivery semantics" failure mode |
| D8 | Normalize provider details at EBF/DRI/RCA/EXE boundaries. | No vendor/model/tool fields in HKA/SIP/GOV public contracts. | EBF | none filed (fitness P2 — file when audited) | "No provider-specific fields in HKA/SIP/GOV public contracts" |
| D9 | Classify rules as manual now, CI later, CI now, or blocking invariant; ship CI rails as boundaries stabilize. | P0 fitness rules enforced by deterministic CI checks. | OEF | #2381 | Fitness-rule roadmap P0/P1/P2 in `SBS_FITNESS_RULES.md` |
| D10 | Keep artifact-origin facts in HKA and decision/action receipts in GOV; keep SIP/DRI rebuildable. | HKA owns artifact-origin facts, GOV owns receipts; SIP/DRI fully rebuildable from source anchors. | SIP / DRI | none filed (tie to #2359/#2358 verification) | "No DRI record that is non-rebuildable unless reclassified"; "SIP becomes irreplaceable shadow store" failure mode |
| D11 | Classify Builder System work through `SBS_OPERATING_MODEL.md` §3; route Product contract changes through CES practice only when Product SBS truth changes. | CES remains lean Product SBS contract stewardship; Builder System workflows, skills, BuilderOps records, and TCD governance keep their own enabling-system boundary. | CES practice / Builder System | #2422 first reconciliation; #2420 for repo-local skill alignment | "No Builder System artifact becomes a Product SBS runtime subsystem or runtime MEM/HKA without authority promotion" |
| D12 | Use BuilderOps records, issue/PR receipts, skills, transition debt, fitness rules, roadmap updates, and prompt/policy PRs as the only durable Builder learning destinations unless Product authority is explicit. | Builder learning and TCD signals are routinely captured, routed, and verified without becoming Product runtime memory or hidden prompt state. | Builder System / OEF | none filed — file when mechanical completeness checks or metrics schema are specified | "No Builder learning or TCD signal bypasses the governed Builder destination path or silently promotes into runtime/user memory" |

## Known debt categories represented

The mission-required debt categories are each represented above (confirmed present; code-level confirmation tracked per row status):

- Active vault / vault path as global architecture concept — D1.
- Direct durable writes without governed DecisionToken — D2.
- Persistence/store construction outside PDM ownership — D3 (first seam delivered; broader extent `to verify`).
- Retrieval result shape not formalized as ContextBundle — D4 (first conformance rail delivered; broader extent `to verify`).
- Memory records lacking review/provenance lifecycle — D5 (first adapter delivered; broader extent `to verify`).
- Agent runtime performing side effects without EXE/GOV seam — D6 (`to verify`).
- Watcher/sync event envelope lacking delivery semantics — D7 (first ReplicationEnvelope seam delivered; broader extent `to verify`).
- Provider-specific assumptions leaking into core semantics — D8 (`to verify`).
- OEF/fitness rules not yet enforcing boundaries — D9 (two CI rails shipped).
- SIP/DRI non-rebuildable shadow store — D10 (`to verify`).
- CES overloading into the whole Builder System — D11 (containing through the Builder System boundary model).
- Builder learning / TCD signal capture gaps — D12 (containing through the governance loop; mechanical completeness `to verify`).

## Register Rule

Every new target-state implementation slice should either reduce one debt item, add a bounded new debt item, or explicitly state that it does not affect SBS transition debt. A row moves to `resolved` only when the violated boundary is actually enforced on the path (contract adopted **and** a fitness rule/test prevents regression), with the resolving PR/issue linked.
