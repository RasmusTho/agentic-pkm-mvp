State: Active target-state specification. Parent #4375 owns live validation state; TIA-01 #4376 is blocked on BCP-06 #3793, TIA-02 #4377 needs an owner decision, and #4378–#4381 remain dependency-blocked.
Doc role: Builder System capability specification
Authority: Owns the bounded target, decomposition, cross-task invariants, dependency order, verification path, and acceptance path. GitHub Issues own executable lifecycle state after filing.
Owner: Builder System governance
Temporal class: operational
Review cadence: event-driven
Source of truth: this directory for the capability contract; live GitHub, BuilderOps PostgreSQL receipts, PRs, CI, and merge evidence for delivery truth
Last reviewed: 2026-07-29

# BuilderOps Temporal Intention Authority

## Capability boundary

This target-state Builder System capability admits owner-authorized temporal-intention lifecycle
evidence without becoming Product intention, commitment, attention, memory, artifact, or UI
authority. It reuses the BuilderOps PostgreSQL transaction, receipt, and outbox kernel selected by
ADR-0062 and constrained by ADR-0065.

No runtime behavior is delivered by this specification. The canonical writer may be activated only
after [BCP-06 #3793](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3793) is closed with its
authority-cutover receipt proving that the authenticated BuilderOps PostgreSQL API is the active
writer and legacy writers cannot recreate authority.

## Approved semantics

The client-admissible disposition vocabulary is closed:

| Disposition | Meaning | Reappearance or reversal |
| --- | --- | --- |
| `done` | The underlying intention is fulfilled or closed. | A new owner decision or a new intention identity, recorded by a new append-only receipt. |
| `ignore` | Suppression is bounded by an explicit policy expiry or condition. | The recorded expiry or an explicit owner action, recorded by a new append-only receipt. |
| `never_show_again` | Suppression is durable and scope-bound. | Explicit owner action only, recorded by a new append-only receipt. |

An allowed expiry or explicit reversal appends `disposition_expired` or
`disposition_reversed`, reduces the record to the existing BuilderOps `active` lifecycle state with
no current disposition, and preserves all prior receipts. `active` is not a fourth admissible
disposition.

## First capability slice

The first implementation slice, after BCP-06, is:

> Admit opaque temporal-intention lifecycle evidence through the canonical BuilderOps transaction.

It adds one registry-backed, non-content-bearing record shape; explicitly maps that shape to the
PostgreSQL authority envelope; atomically creates or replays a stable opaque identity; commits
guarded state with append-only receipt lineage and existing outbox intent; and produces a
rebuildable read-only projection.

Until a separate privacy/retention decision is accepted, every authoritative record, receipt,
idempotent result, outbox intent, log, metric, backup-visible value, and projection remains free of
prompts, summaries, free text, raw paths, raw identifiers of underlying sources or Product
artifacts, fingerprints, linkable deterministic derivatives, HMAC material, and unknown fields.

## Cross-task invariants / interaction safety

- **INV-TIA-1 — one authority.** Only the authenticated BuilderOps PostgreSQL API may admit
  canonical lifecycle evidence. Markdown, JSONL, SQLite, local files, and projections are never
  competing state.
- **INV-TIA-2 — cutover before activation.** No implementation may become ready, activate a route,
  or claim canonical-write acceptance until #3793 is closed with the BCP-06 cutover receipt.
- **INV-TIA-3 — Builder evidence does not mutate Product truth.** A disposition records
  owner-authorized BuilderOps evidence; it cannot complete, delete, suppress, resurface, or
  reinterpret the underlying Product artifact.
- **INV-TIA-4 — opaque-first and content-free.** The first record shape accepts only the semantic
  payload allowed by ADR-0065 D5 and fails closed on content-bearing or unknown fields at every
  durability and observability surface.
- **INV-TIA-5 — closed disposition vocabulary.** Clients may admit only `done`, `ignore`, and
  `never_show_again`; expiry and reversal are receipt-backed reducer events, not additional
  disposition values.
- **INV-TIA-6 — atomic, idempotent lineage.** Guarded state, stable opaque identity, idempotency
  result, append-only receipt, and outbox intent commit through the existing kernel. Equal replay
  returns the original result; conflicting reuse fails closed.
- **INV-TIA-7 — projections do not write.** Projections are explicitly non-authoritative,
  read-only, deletable, and rebuildable from canonical records and receipt lineage. Projection
  absence, duplication, corruption, or staleness cannot cause a lifecycle transition.
- **INV-TIA-8 — deferred scope stays gated.** Content, identifiers or derivatives, retention,
  erasure, collectors, migration, cross-host behavior outside the selected API, and human-facing
  projections require their own accepted decision and bounded Issue before implementation.

### Partial-failure paths

- Concurrent equal admissions serialize to one opaque identity and one logical lifecycle effect;
  callers receive the same committed receipt lineage.
- Conflicting reuse of an idempotency identity fails closed without changing state, receipts, or
  outbox.
- A response lost after commit is recovered through equal replay of the original committed result,
  never a second record or receipt.
- A projection worker repeats or restarts: canonical opaque identity plus receipt lineage dedupes
  the read model without changing authority.
- A content-bearing or unknown field reaches admission, logging, metrics, receipt, outbox, backup
  payload, or projection construction: the operation fails before commit or emission.
- BCP-06 proof is missing or later invalidated: admission remains unavailable; a test adapter cannot
  substitute for the cutover receipt.

## Implementation tasks and dependency order

1. [TIA-01 — Admit opaque lifecycle evidence](ADMIT_OPAQUE_LIFECYCLE_EVIDENCE.md)
   ([#4376](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4376)) — blocked on BCP-06 #3793;
   first implementation slice.
2. [TIA-02 — Decide privacy, retention, and erasure authority](DECIDE_PRIVACY_RETENTION_AND_ERASURE.md)
   ([#4377](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4377)) — owner-decision lane; may be
   prepared now but cannot authorize implementation without an accepted decision.
3. [TIA-03 — Extend to content-bearing evidence](EXTEND_CONTENT_BEARING_EVIDENCE.md)
   ([#4378](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4378)) — blocked on TIA-01 and the
   accepted TIA-02 decision.
4. [TIA-04 — Add collectors, cross-host behavior, and migration](ADD_COLLECTION_SYNC_AND_MIGRATION.md)
   ([#4379](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4379)) — blocked on TIA-01, the
   accepted TIA-02 decision where data is involved, and a separate accepted
   source/topology/migration decision.
5. [TIA-05 — Add a human-facing projection](ADD_HUMAN_FACING_PROJECTION.md)
   ([#4380](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4380)) — blocked on TIA-01 and a
   separate accepted Product/HIX surface-and-authority decision.
6. [TIA-06 — Enforce retention and physical erasure](ENFORCE_RETENTION_AND_PHYSICAL_ERASURE.md)
   ([#4381](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4381)) — blocked on TIA-01 and the
   accepted TIA-02 decision.

The order is dependency order, not a promise that deferred tasks are authorized. TIA-03 through
TIA-06 remain blocked until every named decision gate is accepted.

## Capability acceptance

- TIA-01 must prove BCP-gated canonical admission, exact envelope mapping, concurrent
  create-or-replay, conflict rejection, immutable receipt lineage, and rebuild deduplication.
- Every deferred task must either carry an accepted decision and terminal delivery evidence or an
  explicit superseding owner decision before the parent capability can close.
- Current-state owner docs may claim delivery only after the parent validation hub resolves the
  corresponding runtime receipts and merge evidence.

## Source authority

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/POSTGRES_TRANSACTION_KERNEL.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/audits/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY_2026-07-29.md` (advisory evidence only)
