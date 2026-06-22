State: Initial target SBS fitness rule set; most rules are manual review now and candidates for OEF/CI enforcement later.
Doc role: Fitness rule catalog
Authority: Owns target SBS architecture fitness rules, enforcement posture, and failure-mode detection.
Owner: OEF / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/architecture/SBS_TRANSITION_DEBT.md

# SBS Fitness Rules

These rules make the target SBS inspectable without claiming current implementation enforcement. Enforcement status is conservative until a CI/test rule exists in the repo.

## Classification

- Manual review now: apply during architecture review, PR review, issue breakdown, and docs-to-issue extraction.
- CI check later: suitable for mechanical enforcement after the boundary has enough stable code shape.
- CI check now: should be enforced by current checks if a matching test/lint exists.
- Blocking invariant: violation should block merge or require a new ADR.

## Seed Rules

| Rule | Classification | Detection | Response |
|---|---|---|---|
| No global `activeVault` as architecture contract outside WSP/EBF/HIX adapters. | CI check now for target SBS contract stubs; manual review elsewhere | `tests/architecture/test_sbs_fitness_rules.py::test_target_sbs_contracts_do_not_reintroduce_active_vault_identity` scans target public SBS contracts outside WSP for active-vault/vault-path/root contract terms. | Replace with ActiveContextSet and source binding. |
| No authority-bearing durable write without GOV DecisionToken and receipt. | Blocking invariant target; manual review now | Durable mutation path lacks pre-mutation token or post-mutation AuthorityReceipt. | Route through GovernedWriteProtocol. |
| No direct HKA write from RCA, MEM, CAO, EXE, EBF, or HIX. | Blocking invariant target; CI check later | Non-HKA owner writes accepted human artifact state directly. | Use HKA-owned mutation under GOV decision. |
| No memory promotion to HKA without GOV. | Blocking invariant target; CI check later | MEM material becomes durable human knowledge without approval/admissibility record. | Require GOV promotion policy and receipt. |
| No direct tool side effects from CAO without GOV/EXE. | Blocking invariant target; CI check later | Agent workflow invokes external side effect directly. | Issue ExecutionRequest through EXE with DecisionToken. |
| No provider-specific fields in HKA/SIP/GOV public contracts. | Manual review now; CI check later | Public core contract contains vendor/model/tool-specific field where a stable concept is needed. | Normalize at EBF/DRI/RCA/EXE boundary. |
| No PDM bypass for platform persistence/store resolution. | Manual review now; CI check later | New subsystem constructs DSNs, migrations, or persistent stores directly. | Use StorePort and PDM-owned resolution. |
| No DRI record that is non-rebuildable unless reclassified. | Manual review now | Derived record is the only source of human meaning or accountability. | Reclassify to HKA, GOV, or MEM. |
| No SFC semantic conflict resolution without GOV policy. | Blocking invariant target | Sync transport applies semantic conflict winner without policy class. | Stage conflict and route authority-bearing resolution through GOV/HIX. |
| No OEF automatic control loop that mutates policy, memory, retrieval, knowledge, or execution. | Blocking invariant target | Metrics/evals/traces directly alter runtime behavior outside governed remediation. | OEF reports/proposes; GOV/EXE/HIX or normal development applies changes. |
| No Builder System artifact becomes a Product SBS runtime subsystem or runtime MEM/HKA without authority promotion. | Manual review now | Repo-local skills, BuilderOps records/projections, delivery receipts, worklogs, issue delivery flow, TCD routing, or release workflow state are described as runtime CAO/MEM/HKA behavior or as CES-owned Product SBS implementation. | Reclassify through `SBS_OPERATING_MODEL.md` §3; use `Builder System / CES boundary` for Builder work and update Product owner docs only through the normal authority path. |

## Failure-Mode Catalog

| Failure mode | Symptom | Detection | Mitigation |
|---|---|---|---|
| Governance god-core | GOV owns mechanics, storage, formatting, routing, or implementation detail. | GOV APIs carry storage/rendering/adapter/execution fields. | GOV owns admissibility and receipts; state owners own mutation mechanics. |
| Advisory governance | Mutations can proceed with warnings only. | Durable writes lack DecisionToken or AuthorityReceipt. | Enforce GovernedWriteProtocol. |
| Storage leak | Storage tables, DSNs, or migrations are constructed across subsystems. | Direct store construction outside PDM-owned ports. | Route through StorePort. |
| Scope collapse into active vault | Vault/root/path becomes system-wide identity. | Contracts pass vault path instead of ActiveContextSet. | Use WSP ActiveContextSet and source bindings. |
| Retrieval becomes truth | Ranked evidence becomes accepted knowledge. | RCA writes HKA or facts appear without review. | Keep ContextBundle candidate-only; HKA/GOV own acceptance. |
| Memory becomes hidden instruction | Unreviewed memory silently changes agent behavior. | CAO consumes memory without review/provenance/confidence posture. | MemoryRecord review/provenance plus GOV policy. |
| Sync resolves meaning | Transport rules decide semantic conflicts. | SFC applies last-write-wins to authority-bearing records. | Stage conflicts; route policy decisions through GOV/HIX. |
| UI state becomes authoritative | Client/UI state is the only place decisions or accepted changes exist. | HIX state is read as HKA/MEM/GOV truth. | Persist domain state in owner subsystem with receipts. |
| Event envelope lacks delivery semantics | Events are shaped but can drop/reorder without visibility. | No idempotency, replay/backfill, ordering, or failure visibility. | Define SourceObservationEvent/ReplicationEnvelope semantics. |
| OEF becomes control loop | Fitness or metrics mutate runtime behavior. | OEF writes to policy/memory/retrieval/knowledge/execution. | OEF observes, reports, and blocks CI when configured; remediation is governed. |
| SIP becomes irreplaceable shadow store | Semantic projection holds only copy of meaning/accountability. | HKA/GOV cannot rebuild without SIP. | HKA owns artifact-origin facts; GOV owns receipts; SIP remains rebuildable. |
| Provider-specific concepts leak into core semantics | Vendor/model/tool fields become HKA/SIP/GOV contract language. | Replacing provider changes semantic authority. | Translate provider details behind EBF/DRI/RCA/EXE. |
| Agent runtime owns policy/retrieval/memory/tool side effects | Agent framework absorbs adjacent subsystem authority. | Replacing agent runtime requires redesigning GOV/RCA/MEM/EXE. | CAO coordinates cognition; consumes contracts; EXE executes effects. |
| Derived representations contain non-rebuildable meaning | Index/projection/embedding/mirror loss loses human meaning. | DRI record cannot be rebuilt from source anchors. | Reclassify non-rebuildable material into HKA/GOV/MEM. |
| Builder System collapses into CES or runtime memory | Builder workflow artifacts are treated as Product SBS runtime subsystems, CES-owned implementation surfaces, or runtime/user memory. | Issues/PRs use Product SBS owners for pure builder workflow changes; docs describe repo-local skills or BuilderOps records as runtime CAO/MEM/HKA truth. | Classify as Builder System or boundary work; promote into Product contracts only through repo PR/issue authority and owner-doc writeback. |

## First Enforcement Candidates

- Shipped first rail: `tests/architecture/test_sbs_fitness_rules.py::test_target_sbs_contracts_do_not_reintroduce_active_vault_identity` is a read-only pytest check for new public `activeVault`/`vaultPath`/vault-root contract usage in target SBS contracts outside WSP ActiveContextSet.
- Shipped second rail: `tests/architecture/test_sbs_fitness_rules.py::test_non_hka_contracts_do_not_claim_direct_hka_mutation` is a read-only contract-doc check that the non-HKA target contracts (RCA/MEM/CAO/EXE) do not claim direct durable HKA/artifact mutation and route knowledge mutation through GOV / GovernedWriteProtocol.
- Contract tests for authority-bearing write paths once DecisionToken and AuthorityReceipt exist in code.
- Dependency checks that prevent RCA/MEM/CAO/EXE direct HKA writes once those subsystems have stable physical modules (a literal code import-direction map; the contract-doc rail above is the interim enforcement).
- Provider-field checks for HKA/SIP/GOV contract files.
- Docs/PR template checks requiring SBS impact classification for major work.

## Prioritized Fitness Rule Roadmap

This roadmap orders rules by how load-bearing the boundary is and how mechanically checkable it is today. Its lifecycle is owned by `docs/architecture/SBS_OPERATING_MODEL.md` §11: a rule is only **CI check now** when a real, fail-loud test enforces it; promoting a rule from manual to CI is itself SBS work (issue + test + posture update). "Enforcement now" states reality; "Target enforcement" states the intended end state.

### P0 — authority and identity integrity (highest priority)

| Rule | Owner | Rationale | Enforcement now | Target enforcement | Issue / status |
|---|---|---|---|---|---|
| No global `activeVault`/`vaultPath` in target public contracts outside WSP. | WSP / OEF | Prevents scope collapse into a storage/source location; keeps `ActiveContextSet` the context seam. | CI check now — `tests/architecture/test_sbs_fitness_rules.py::test_target_sbs_contracts_do_not_reintroduce_active_vault_identity`. | CI check now (extend coverage as contracts grow). | #2363 shipped (PR #2376); coverage extension under #2381. |
| Authority-bearing durable writes require `DecisionToken` and `AuthorityReceipt`. | GOV | Stops governance from being advisory; makes accountability non-skippable. | Manual review now; first adapter on the capture path (#2357). | Blocking invariant (CI contract test once tokens exist on enough paths in code). | Token-dependent; tracked by #2381 (deferred portion) + debt D2. |
| No direct HKA mutation from RCA/MEM/CAO/EXE/EBF/HIX. | HKA / OEF | Prevents retrieval/memory/agents/UI from becoming knowledge authority. | CI check now — `tests/architecture/test_sbs_fitness_rules.py::test_non_hka_contracts_do_not_claim_direct_hka_mutation` (contract-doc level: RCA/MEM/CAO/EXE contracts disclaim direct HKA mutation and route through GOV / GovernedWriteProtocol). | Blocking invariant; extend toward a literal dependency/import-direction check once subsystems have stable physical modules (Boundary Register shows Partial/No today). | #2381 — first contract-doc CI rail shipped; literal module-import map deferred. |

### P1 — substrate and cognitive contract integrity

| Rule | Owner | Rationale | Enforcement now | Target enforcement | Issue / status |
|---|---|---|---|---|---|
| No private platform store construction outside PDM. | PDM / OEF | Keeps storage technology from becoming architecture; centralizes migrations. | Manual review now. | CI check later (DSN/store-construction scan) once PDM seam inventoried. | Debt D3 / #2358. |
| `ContextBundle` must carry scope and provenance. | RCA | Keeps retrieval output candidate-only and explainable, never truth. | CI check now for production retrieval bundle emission; manual review elsewhere. | Extend CI conformance coverage across remaining retrieval/search outputs. | Debt D4 / #2359. |
| `MemoryRecord` must carry review state and provenance. | MEM | Stops unreviewed memory from becoming hidden instruction. | CI check now for review-entry and promoted-recall adapter projection; manual review elsewhere. | Extend CI conformance coverage across remaining memory lifecycle classes. | Debt D5 / #2360. |
| `ExecutionRequest` must carry governed authorization for side effects. | EXE / GOV | Separates agents from side-effecting execution; ties effects to a decision. | Manual review now. | Blocking invariant (CI contract test once EXE seam exists). | Debt D6 / #2361. |

### P2 — provider, sync, and observability neutrality

| Rule | Owner | Rationale | Enforcement now | Target enforcement | Issue / status |
|---|---|---|---|---|---|
| No provider-specific fields in HKA/SIP/GOV public contracts. | EBF / OEF | Keeps vendor/model/tool choices out of core semantics. | Manual review now. | CI check later (provider-field scan on core contract files). | Debt D8 (unfiled — file when audited). |
| No SFC semantic conflict resolution without GOV policy. | SFC / GOV | Prevents sync transport from deciding meaning. | Manual review now (SFC is no-op/single-node today). | Blocking invariant when federation is implemented. | Debt D7 / #2362. |
| No OEF automatic control loop mutating policy/memory/retrieval/knowledge/execution. | OEF / GOV | Keeps observability from becoming an ungoverned control loop. | Manual review now; OEF reports and blocks CI only. | Blocking invariant. | Roadmap-level; no loop exists yet. |
| No Builder System artifact classified as Product runtime subsystem or runtime memory. | CES practice / Builder System | Keeps CES lean and prevents builder worklogs, skills, receipts, and BuilderOps records from becoming Product SBS or runtime MEM/HKA truth by shortcut. | Manual review now via SBS impact classification and PR review. | CI check later only if stable template/doc patterns justify mechanical detection. | Debt D11 / #2422; skill alignment follow-up #2420. |
