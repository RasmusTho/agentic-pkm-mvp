State: Filed target-state capability specification; no total-loss recovery capability is shipped by this document. Shared validation epic: #5258 (`agent:blocked`).
Doc role: Capability specification
Authority: Defines bounded delivery for reconstructing machine state from retained human authority and for fencing operational state whose lineage is absent.
Owner: Architecture / CES boundary, with HKA, SIP, GOV, PDM, DRI, WSP/MVR, Builder System, and Platform/Ops retaining local authority.
Temporal class: Target-state specification
Review cadence: At each child delivery and before parent acceptance.
Source of truth: Retained human documents, companions, and document-backed governance receipts remain continuity authority; this directory owns delivery decomposition only.

# Rebuildable System Continuity

## Capability Boundary

The system must tolerate loss or corruption of databases, indexes, embeddings, queues, caches,
projections, and runtime state without losing or changing human meaning. Reconstruction begins from
retained human-authored or accepted artifacts, companions, and document-backed governance receipts.
Machine mirrors never become authority because they are useful during recovery.

Operational journals, leases, ownership records, and recovery fences protect effects rather than
human meaning. When their lineage is missing, the supported posture is a **new fenced bootstrap
epoch**: start inactive, read authoritative sources and external systems, reconcile, emit durable
receipts, and activate only after convergence. The system never pretends that a new epoch restored
old ownership, and it never replays an effect solely because the lost local database cannot prove
whether that effect happened.

## Cross-Task Invariants / Partial Failure Safety

1. **Retained authority survives mirror loss.** Loss of a machine representation cannot alter
   semantic meaning, governance authority, or accepted human authorship.
2. **Every derived state has a replay tuple.** Source identity, source/content generation, and
   recipe/version are sufficient to rebuild or to refuse use.
3. **Readiness is fail-closed.** Empty, stale, corrupt, or provenance-incomplete mirrors remain
   unavailable until rebuild and integrity checks converge.
4. **Operational loss creates a new epoch.** Missing lease/journal/recovery lineage fences all
   affected effects and requires owner-native readback; ownership and terminal outcomes are never
   inferred.
5. **No effect replay from absence.** External or durable effects are reconciled by authoritative
   readback and idempotent owner protocols, not by assuming an empty local row means “not done.”
6. **Diagnostics are read-only.** Doctor/report paths emit typed states and redacted evidence; they
   cannot repair, delete, activate, restore, or claim closure.
7. **Exceptions stay class-specific.** Raw retained evidence and document-backed receipts keep
   their own retention authority. Their durability does not justify general DB/archive authority.
8. **Backup is optional evidence, not semantic authority.** A snapshot may aid forensics or speed,
   but absence of backup never legitimizes a false readiness claim or blocks a supported rebuild.

## Implementation Tasks And Execution Order

1. [Reconcile Continuity Authority](RECONCILE_CONTINUITY_AUTHORITY.md) — RSC-01. Depends on DSP-01;
   align owner docs and diagnostic-retention wording with the selected new-bootstrap posture.
2. [Prove Product Total Loss](PROVE_PRODUCT_TOTAL_LOSS.md) — RSC-02. Depends on RSC-01; establish
   the Product DB/readiness loss kernel from retained source fixtures.
3. [Rebuild Product Projections](REBUILD_PRODUCT_PROJECTIONS.md) — RSC-03. Depends on RSC-02;
   converge object/vector/relation projections and reconstructable queue work.
4. [Diagnose Mirror Corruption](DIAGNOSE_MIRROR_CORRUPTION.md) — RSC-04. Depends on RSC-02 and
   RSC-03; expose typed, read-only inventory and refusal evidence.
5. [Specify MVR New Bootstrap](SPECIFY_MVR_NEW_BOOTSTRAP.md) — RSC-05. Depends on RSC-01; amend the
   existing MVR owner contract and existing #2143 chain without duplicate recovery authority.
6. [Apply MVR New Bootstrap](APPLY_MVR_NEW_BOOTSTRAP.md) — RSC-06. Depends on RSC-05 and applicable
   live MVR prerequisites; implement fenced epoch/readback/activation behavior.
7. [Bootstrap BuilderOps From Authority](BOOTSTRAP_BUILDEROPS_FROM_AUTHORITY.md) — RSC-07. Depends on
   RSC-01 and coordinates with #5056; seed a fresh authority epoch, read GitHub truth, and converge
   before enabling writers.
8. [Verify Cross-System Total Loss](VERIFY_CROSS_SYSTEM_TOTAL_LOSS.md) — RSC-08. Depends on RSC-04,
   RSC-06, and RSC-07; prove integrated refusal, reconstruction, readback, and activation.

Delivery is serial by default. Existing MVR and BuilderOps Issues remain authoritative for their
distinct scopes; this capability adds only the missing total-loss contracts and proof.

## Capability Acceptance

- [ ] RSC-01 through RSC-08 are terminally delivered with exact-head evidence and parent receipts.
- [ ] Product projections reconstruct from retained sources and exact recipes; corrupted or
  incomplete sources produce typed refusal and no stale serving.
- [ ] MVR and BuilderOps use fresh fenced epochs after lost operational lineage and activate only
  after owner-native or GitHub readback converges.
- [ ] Integrated evidence proves duplicate/retry safety and proves that no unknown external effect
  is replayed or silently declared complete.
- [ ] HKA/GAF, raw evidence, diagnostic dumps, and backups remain correctly classed and do not become
  a generic restore program.

## Reconciliation — Do Not Duplicate

- #5056 owns the rebuildable, backup-non-gating BuilderOps VM deployment and its later live
  activation. RSC-07 owns only fresh control-plane authority bootstrap/readback semantics.
- #2143 and #3863–#3869 own Multi-Vault Runtime delivery. RSC-05/06 must amend or depend on that
  chain rather than creating a parallel registry, journal, or supervisor.
- #5067 remains a blocked HKA recovery proposal with protected gaps. This capability does not revive
  it; retained HKA remains authority and mirror loss is handled by reconstruction.
- #5162, #4659, #2899, and #3553 retain their distinct dormant-binding, vault-append, runtime-audit,
  and governed-effect scopes.
- GAF raw-evidence retention remains class-specific and is not a DB recovery precedent.

## Relationship To The Shared Epic

This directory shares one validation epic with `docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/`. The design
packet capability is consumed here as a compact routing guard, while all continuity semantics stay
with the Product, MVR, BuilderOps, and Platform/Ops owners named above.

## Source Authority

- `docs/audits/REBUILDABILITY_RECOVERY_AUTHORITY_AUDIT_2026-08-31.md`
- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`
- `docs/SEMANTIC_AUTHORITY_MATRIX.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
- `docs/DB_SCHEMA.md`
- `docs/EVENTS.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
- `docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md`
