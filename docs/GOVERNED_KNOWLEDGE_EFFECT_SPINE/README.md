State: Filed capability specification. Implementation is not yet shipped; parent validation hub: GitHub Issue #3553.

# Governed Knowledge Effect Spine

## Purpose

This capability makes the evidence-to-effect chain fail closed without turning the SBS into a module diagram. Heimdal ends at durable evidence/candidates; Mimer owns semantic identity, governance, effect execution, and rebuildable derived state.

## TCD decision

The seven small deliveries below minimize expected accepted-delivery cost: first one shared contract, then two independent P0 tracks. This prevents silent data loss and unauthorized mutation early, while avoiding an unsupported serial dependency between semantic identity and DecisionToken enforcement.

## Execution order

1. [DEFINE_EFFECT_SPINE_CONTRACTS](DEFINE_EFFECT_SPINE_CONTRACTS.md)
2. In parallel after GKES-01: [MAKE_HEIMDAL_INTAKE_DURABLE](MAKE_HEIMDAL_INTAKE_DURABLE.md) and [ENFORCE_GOVERNED_EFFECT_TOKENS](ENFORCE_GOVERNED_EFFECT_TOKENS.md)
3. [PERSIST_CANDIDATE_EVIDENCE_POSTURE](PERSIST_CANDIDATE_EVIDENCE_POSTURE.md) after durable intake
4. [CONSOLIDATE_SEMANTIC_IDENTITY_AUTHORITY](CONSOLIDATE_SEMANTIC_IDENTITY_AUTHORITY.md) after candidate posture
5. [RECONCILE_TERMINAL_AUTHORITY_OUTCOMES](RECONCILE_TERMINAL_AUTHORITY_OUTCOMES.md) after token enforcement
6. [REPAIR_DERIVED_STATE_DETERMINISTICALLY](REPAIR_DERIVED_STATE_DETERMINISTICALLY.md) after durable intake and semantic identity authority

## Cross-Task Invariants / Interaction Safety

- A cursor can advance only after the corresponding candidate is durable or a durable recovery state names it. Retry cannot silently drop or duplicate a candidate.
- Heimdal evidence remains candidate/evidence material; no task promotes it into HKA or lets it become a decision.
- Every authority-bearing effect is authorized before mutation and has exactly one durable terminal outcome or an inspectable recovery state after mutation failure.
- Semantic identity is minted by one logical authority. DRI consumes durable sources and identity events; it never becomes a source of truth.
- New runtime preconditions include every producer, bootstrap/migration path, existing-resource migration, test fixture, and fail-loud preflight in the same change.

Partial failure is not completion: a mutation without its receipt remains recoverable, not successful; a blocked candidate write leaves its cursor unadvanced; a DRI repair does not claim freshness until its source history is fully processed.

## Acceptance

- The P0 evidence, identity, effect, receipt, and derived-state findings have task-level verification receipts.
- The parent Issue holds the post-merge evidence and only then triggers owner-doc promotion.
- P1 work (WSP/SFC convergence, EBF lifecycle, HIX intent, broader OEF and CES automation) remains outside this capability unless a verified security bypass requires a separately bounded issue.

## Relationship to GitHub issues

The parent feature issue and child issue numbers are recorded in [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) after filing. This directory is the source specification; GitHub issues are the pickup contracts.
