State: Normative target-state contract for GAF-01; no production implementation claim.
Doc role: Product/Runtime contract
Authority: Owns the shared archival vocabulary and adapter boundary. HKA, SIP, GOV, PDM, DRI, and
source-class owner contracts remain authoritative for their own semantics.
Owner subsystem: Cross-boundary contract coordinated by PDM with HKA/SIP/GOV/DRI and source adapters
Temporal class: strategic target-state
Review cadence: event-driven

# Governed Archival Flow Contract

## Boundary

The governed archival flow is a type-neutral lifecycle overlay for durable source artifacts. It
preserves owner-native identity, provenance, policy authority, gated access, restore evidence,
retention/revocation outcomes, deletion evidence, and liveness while a representation is moved or
preserved. It is not a central artifact registry, central archive registry, central archive store,
universal archive table, storage backend, or new SBS authority.

Ownership remains separated:

- HKA owns human-authored and human-accepted artifact meaning and portable recovery.
- SIP owns stable identity and provenance continuity.
- GOV owns access, consent, retention/revocation policy and receipts.
- PDM owns representation storage, migration, restore mechanics, encryption and health.
- DRI owns rebuildable derivatives, indexes, embeddings, caches and source-lineage checks.
- Source adapters own admission-specific capture and class semantics.

## Contract vocabulary

The Provider-free `app.archival` values are the shared vocabulary. An adapter must preserve these
axes independently; no status string or storage location may collapse authority, derivation,
durability, policy, generation, or lifecycle stage.

- `ArtifactClass`: raw source, retained source, human artifact, derived artifact, or receipt.
- `Durability`: durable, ephemeral, or rebuildable.
- `AuthorityOwner`: HKA, SIP, GOV, PDM, DRI, or source adapter.
- `PolicyProfile`: raw evidence, retained source, HKA recovery, or rebuildable derivative.
- `ArtifactIdentity`: stable opaque owner-native identity.
- `RepresentationRef`: opaque registered representation reference.
- `Provenance`: source references, origin, and capture time.
- `ArtifactDescriptor`: identity, class, durability, owner, policy, generation and provenance.
- `RepresentationDescriptor`: opaque ref, artifact identity, generation, content identity, format,
  and encryption posture.
- `TransitionStage`, `Liveness`, and `Receipt`: typed lifecycle evidence with no filesystem path
  authority.

Opaque identity and representation references reject paths and URIs. Path text can identify a
backend binding inside PDM, but it cannot mint artifact identity, representation identity, or read
authority.

## Adapter protocol

`ArchivalAdapter` is a provider-free protocol. Owner-native adapters implement:

- enumerate and resolve registered representations;
- authorize a read through the owner-native access gate;
- reserve, verify, activate and retire a representation;
- restore through the production gate;
- erase or revoke only where the class policy permits it; and
- doctor/reconcile orphan, mismatch, stale-generation and cleanup states.

This task defines no orchestration, persistence, migration, backend selection, or production import.
The protocol is an enabling seam, not runtime authority.

## Policy separation

Policy profiles have distinct terminal outcomes. Raw evidence may reach `erased` only after all
registered representations and cleanup obligations converge. Retained sources preserve their
source until explicit policy says otherwise. HKA recovery is conflict-safe and must not inherit raw
evidence TTL. Rebuildable derivatives are disposable/rebuildable by default and cannot become the
last authoritative copy of meaning. HKA recovery conflicts remain typed, non-terminal states
awaiting governed resolution; `unavailable` liveness is retryable doctor/read evidence, not a
terminal policy outcome. Receipts and tombstones are durable governance evidence, not source
content.

## Invariant kernel

These entries extend the existing invariant registry; this contract creates no competing registry.

- **ARCHIVE-MUST-01 — Identity is not location.** Representation movement preserves stable identity,
  content identity where applicable, provenance, generation and opaque reference.
- **ARCHIVE-MUST-02 — Access is gated.** Restore and ordinary reads use the owner-native gate;
  mounts, paths and manifests never authorize reads.
- **ARCHIVE-MUST-03 — No authority fork.** Archive manifests and receipts describe custody and
  verification without replacing HKA, SIP, GOV, PDM, DRI or source-owner truth.
- **ARCHIVE-MUST-04 — Verify before retirement.** Reservation, durable copy, identity verification,
  owner receipt and activation precede retirement of a superseded representation.
- **ARCHIVE-MUST-05 — All-copy deletion precedes terminal erasure.** Pending external cleanup keeps
  liveness non-terminal and retryable.
- **ARCHIVE-MUST-06 — Admission is atomic.** Every admitted durable source has identity,
  origin/provenance, policy/consent class, generation, and one registered initial representation,
  or admission fails closed.
- **ARCHIVE-MUST-07 — Reads are resolver-bound.** A representation is readable only through a
  registered resolver that verifies encryption/key posture, byte/content identity, and active
  generation.
- **ARCHIVE-GATE-01 — Adapter restore proof.** Every adapter proves restore through its production
  gated-read seam and emits a redacted receipt.
- **ARCHIVE-GATE-02 — Cross-class matrix.** The capability matrix covers source, human, derived and
  receipt classes with explicit exclusions.
- **ARCHIVE-GATE-03 — Retention/revocation proof.** Adapters prove no false success, generation
  non-resurrection and retryable cleanup.
- **ARCHIVE-GATE-04 — Parent acceptance receipt.** Scope coverage and owner-doc promotion follow a
  redacted cross-class validation receipt.
- **ARCHIVE-DOCTOR-01 — Representation reconciliation.** Detect orphan bytes, missing bytes and
  identity/content mismatches.
- **ARCHIVE-DOCTOR-02 — Liveness reconciliation.** Detect missing tombstones, stale generations,
  unresolved cleanup and wrong resolver bindings.
- **ARCHIVE-DOCTOR-03 — Source-authority reconciliation.** Detect derivatives, indexes or caches
  treated as source authority and human artifacts lacking durable origin evidence.

## Non-goals

This contract does not create a generic archive store, central registry, cloud provider, universal
ID, retention policy, production adapter, or migration. Each future adapter requires its own bounded
Issue, owner authority, production-path verification and current-state documentation.
