State: Initial transition debt register; entries are seeded from target SBS risk categories and require verification before implementation claims.
Doc role: Transition debt register
Authority: Owns known and likely deviations from the target SBS while current runtime remains in transition.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/ARCHITECTURE.md, docs/STATUS.md

# SBS Transition Debt

This register names deviations and likely deviations from the target SBS. "To verify" means the debt category is architecturally plausible but needs code/doc inspection before a fix scope is filed as implementation-ready.

| Debt | Violated target boundary | Risk | Severity | Containment | Follow-up issue |
|---|---|---|---|---|---|
| Active vault / vault path used as global architecture concept | WSP vs HKA/EBF/PDM | Scope collapses into storage/source location. | High | Route new work through ActiveContextSet; treat vault/source binding as implementation detail. | #2343 |
| Direct durable writes without governed DecisionToken | GOV vs HKA/MEM/EXE | Governance becomes advisory and accountability can be skipped. | High | Use GovernedWriteProtocol for authority-bearing durable mutations. | #2344 |
| Persistence/store construction outside PDM ownership | PDM vs all state owners | Storage technology leaks into semantics and migrations scatter. | High | Require StorePort and no private DSN/store construction in new work. | #2346 |
| Retrieval result shape not formalized as ContextBundle | RCA vs HIX/CAO/MEM/HKA | Retrieval output can be treated as truth or prompt stuffing. | Medium | Use ContextBundle for scoped candidate evidence and non-authority posture. | #2347 |
| Memory records lacking explicit review/provenance lifecycle | MEM vs GOV/HKA/RCA | Memory can become hidden instruction or shadow knowledge. | High | Use MemoryRecord with review state, provenance, confidence, staleness, correction, forgetting, and GOV promotion path. | #2348 |
| Agent runtime performing side effects without EXE/GOV seam | CAO vs EXE/GOV | Agents can bypass authorization and receipts. | High | Route side effects through ExecutionRequest with DecisionToken reference. | #2349 |
| Watcher/sync event envelope lacking delivery semantics | EBF/SFC vs DRI/HKA/GOV/OEF | Events can drop, reorder, or fail replay/backfill invisibly. | Medium | Use SourceObservationEvent or ReplicationEnvelope delivery semantics before widening sync. | #2350 |
| Provider-specific assumptions leaking into core semantics | EBF/DRI/RCA vs HKA/SIP/GOV | Vendor/model/tool choices become architecture. | Medium | Normalize provider details at EBF/DRI/RCA/EXE boundaries. | #2351 |
| OEF/fitness rules not yet enforcing SBS boundaries | OEF/CES vs all subsystems | Architecture remains documentation-only and drifts. | Medium | Classify rules as manual now, CI later, CI now, or blocking invariant. | #2351 |
| SIP projection could become irreplaceable shadow store | SIP vs HKA/GOV | Semantic projections could carry unrecoverable meaning. | High | Keep artifact-origin facts in HKA and decision/action receipts in GOV. | #2345 |

## Register Rule

Every new target-state implementation slice should either reduce one debt item, add a bounded new debt item, or explicitly state that it does not affect SBS transition debt.
