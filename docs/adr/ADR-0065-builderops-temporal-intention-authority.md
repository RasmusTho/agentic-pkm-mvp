State: Accepted (owner decision, 2026-07-29). Defines the future BuilderOps authority, lifecycle semantics, first-slice content boundary, and delivery gates for temporal-intention evidence. Docs/architecture decision only; no product or runtime behavior changes here.
Doc role: Decision record (ADR)
Authority: Authoritative for BuilderOps temporal-intention evidence semantics, canonical-writer sequencing, projection posture, and the content-free first capability slice. Layers on ADR-0010 and ADR-0062 without changing Product/Runtime artifact semantics.
Owner: BuilderOps governance / Architecture spine
Temporal class: Durable decision; supersede through a later ADR when the authority, disposition semantics, or privacy/retention posture changes.
Source of truth: This ADR plus ADR-0062 and `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`. `docs/audits/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY_2026-07-29.md` is advisory evidence, not authority.

# ADR-0065: BuilderOps temporal-intention lifecycle evidence is PostgreSQL-only, opaque-first, and receipt-backed

**Date:** 2026-07-29
**Status:** Accepted (owner decision, 2026-07-29)

## Context

Builder work can produce durable evidence that an underlying intention was completed or should be
suppressed. Today that evidence has no shared BuilderOps authority or lifecycle vocabulary. Existing
Product concepts are not interchangeable: commitments, Moments, attention logs, proposal-decline
state, and Temporal Posture each own narrower semantics. Reusing any of them would silently transfer
Product authority into the Builder System.

BuilderOps also has two materially different storage postures:

- the current deployed/local posture includes SQLite and file projections that cannot prove a
  cross-host canonical writer; and
- ADR-0062 selects one authenticated API with PostgreSQL authority, atomic receipt/outbox
  transactions, and no production SQLite or Markdown authority after BCP cutover.

The advisory 2026-07-29 audit found that the transaction kernel can support the capability, but
identified four unresolved authority hazards: a pre-cutover writer would create split truth;
`done`, `ignore`, and `never_show_again` had no common owner; no privacy/retention decision covers
content-bearing intention evidence; and the local object envelope needs an explicit PostgreSQL
mapping. The owner decisions below settle the safe authority and lifecycle posture while keeping
content collection and erasure outside this decision.

## Decision

### D1 — BuilderOps evidence, not Product intention truth

Temporal-intention lifecycle evidence is a Builder System operational capability. It records an
owner-authorized disposition and its lineage; it does not own, reinterpret, complete, delete, or
resurface the underlying Product artifact or human intention.

Product commitments, Moments, attention state, memories, artifacts, and UI state retain their own
owner contracts. No existing Product lifecycle value is automatically mapped to this vocabulary.
Any future Product-to-Builder adapter requires its own contract and must preserve the authority
boundary.

### D2 — One future canonical writer, gated on BCP-06 cutover

The only future canonical writer is the authenticated BuilderOps API backed by the PostgreSQL
authority selected by ADR-0062. Admission must use the existing BuilderOps transaction, receipt, and
outbox kernel; it must not introduce a second registry, JSONL ledger, Markdown state file, direct
database client, SQLite fallback, or temporary local authority.

Implementation may not activate or claim canonical-write acceptance until issue #3793 (BCP-06) is
closed with the authority-cutover receipt proving that PostgreSQL is the active writer and legacy
writers cannot recreate authority. Repository specifications and blocked Issues may be prepared
before that gate. A local test adapter remains test-only and cannot satisfy the gate.

### D3 — Closed disposition vocabulary and explicit reversals

The capability admits exactly three dispositions:

| Disposition | Meaning | Only permitted reappearance or reversal |
| --- | --- | --- |
| `done` | The underlying intention is fulfilled or closed. The evidence is terminal for that intention identity. | An explicit new owner decision or a new intention identity, recorded through a new append-only receipt. No automatic resurfacing. |
| `ignore` | Suppression bounded by an explicit policy expiry or condition. It asserts neither completion nor a permanent preference. | The recorded policy expiry or an explicit owner action, recorded through a new append-only receipt. No heuristic reappearance. |
| `never_show_again` | Durable, scope-bound suppression. It does not physically delete the underlying evidence. | Explicit owner action only, recorded through a new append-only receipt. No expiry or heuristic reappearance. |

`dismissed`, `deferred`, `expired`, `skipped`, `declined`, `archived`, and similar Product or
BuilderOps lifecycle values are not aliases. A correction never rewrites a prior receipt: it appends
new evidence that names the prior state and decision lineage.

When an allowed expiry or explicit reversal takes effect for the same opaque identity, the canonical
transaction appends a `disposition_expired` or `disposition_reversed` lifecycle receipt, returns the
record to the existing BuilderOps `active` lifecycle state, and leaves it with no current
disposition. `active` and the absence of a current disposition are not fourth disposition values and
cannot be admitted directly by a client; they are reducer outcomes of a receipt-backed expiry or
owner-authorized reversal. The prior disposition remains immutable in receipt lineage. A later
`done`, `ignore`, or `never_show_again` requires a new admitted decision and receipt.

### D4 — Opaque, registry-backed first record shape

The first capability slice adds one registry-backed BuilderOps record type and an explicit mapping
to the PostgreSQL authority envelope. Its authoritative transaction must:

1. atomically create or replay one stable opaque temporal-intention identity under one idempotency
   key;
2. validate the closed disposition vocabulary and its allowed transition/reversal;
3. commit guarded state plus an append-only lifecycle receipt, including the defined
   `active`/no-current-disposition reducer outcome for an allowed expiry or reversal;
4. use the existing outbox path for any derived projection work; and
5. return the original committed identity and receipt lineage on equal replay while rejecting
   conflicting reuse.

The mapping must name the PostgreSQL authority-envelope fields, registry type, state payload,
idempotency identity, receipt event, and projection/outbox identity. A projection event may be
replayed or rebuilt; it cannot grant or alter authority.

### D5 — The first slice is strictly content-free

Until a separate privacy/retention decision is accepted, the authoritative record and every receipt,
outbox intent, log, metric, backup-visible value, and projection must contain no:

- prompt or prompt fragment;
- summary, free text, or captured content;
- raw source path or host-private reference;
- raw identifier of an underlying intention, source artifact, person, prompt, host item, or Product
  artifact;
- fingerprint, fingerprint input, digest used as a proxy for source identity, or linkable
  deterministic derivative; or
- HMAC key, key reference, derived HMAC, or other new key material.

The permitted semantic payload is limited to the server-validated opaque record identity, the
mandatory existing BuilderOps authority envelope (including the ADR-0062-required `RepoRef` and
scope), the selected disposition, a non-content policy
expiry/condition code for `ignore`, a non-content scope class for `never_show_again`, schema/version
metadata, idempotency identity, and receipt lineage. The specification must fail closed on unknown
or content-bearing fields. This decision does not authorize collectors or a mapping store that can
reverse an opaque identity to source content.

### D6 — Projections are rebuildable, read-only views

Any Markdown or other human-readable projection is generated from canonical PostgreSQL records and
append-only receipts. It is read-only, labels itself non-authoritative, and can be deleted and
rebuilt without changing disposition state or receipt lineage.

Rebuild deduplication is keyed by canonical opaque identity plus receipt lineage. Projection absence,
staleness, duplication, or corruption cannot cause a lifecycle transition or re-admission. A
cockpit/UI is not part of the first slice.

### D7 — Deferred capabilities require separate gates

The following are not implicit follow-ons and are not authorized by this ADR:

- collectors, prompt/summarization capture, raw source references, raw identifiers, fingerprints,
  HMAC derivation, or any content-bearing payload;
- cross-host synchronization outside the already selected authenticated API;
- migration/import of historical state or a compatibility writer;
- cockpit/UI or Product runtime projections;
- physical erasure, crypto-shredding, retention expiry, key custody, or deletion of canonical
  receipts; and
- automatic inference of dispositions or reversals.

Content-bearing fields, identifiers/derivatives, retention, and physical erasure require a separate
accepted privacy/retention decision before specification or implementation. Collectors, migration,
cross-host behavior, and user-facing projections each require an independently bounded task and any
owner decision their authority boundary needs.

### D8 — Delivery sequencing

After this ADR is merged, `feature-breakdown` may create the specification directory, parent feature
Issue, and dependency-ordered child Issues. The parent is a validation hub and remains blocked on
#3793 until the BCP-06 cutover receipt proves the canonical PostgreSQL writer.

The first implementation slice after that gate is:

> Admit opaque temporal-intention lifecycle evidence through the canonical BuilderOps transaction.

It covers the registry-backed content-free record shape, PostgreSQL envelope mapping, atomic
create-or-replay, append-only lifecycle receipt, the three dispositions, and a rebuildable read-only
projection. Its verification must include concurrent admission, equal replay/conflicting reuse,
receipt lineage, and rebuild deduplication. Later slices must not smuggle any D7 item into that
scope.

## Consequences

- The owner-approved semantics are durable repo authority, while the audit remains advisory.
- Planning and Issue creation can proceed now; production/runtime implementation remains blocked on
  #3793.
- The first slice can reuse the delivered development transaction kernel without treating that
  kernel as deployment/cutover proof.
- BuilderOps gains no competing Markdown or file authority and Product lifecycle owners do not
  change.
- The content-free posture trades immediate observability richness for a bounded privacy and
  retention risk. Richer evidence waits for an explicit decision.
- This ADR does not claim that the record type, API route, database mapping, projection, tests, or
  live writer exists today.

## Rejected alternatives

### Use Markdown or JSONL until PostgreSQL cutover

Rejected because it creates the duplicate authority and migration burden this capability is meant
to prevent.

### Use local SQLite as an interim canonical writer

Rejected because per-database atomicity cannot prove one cross-host authority and ADR-0062 forbids
production SQLite fallback after cutover.

### Reuse a Product lifecycle or suppression ledger

Rejected because the terms have different owners and semantics; reuse would silently couple Builder
evidence to Product truth.

### Store content now and decide retention later

Rejected because backup, receipt, log, and projection persistence would make the later decision
retroactive and potentially impossible to honor.

## Source docs and evidence

- `docs/audits/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY_2026-07-29.md`
- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/POSTGRES_TRANSACTION_KERNEL.md`
- `docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- Issue #3788 (BuilderOps control-plane parent)
- Issue #3793 (BCP-06 authority cutover gate)
