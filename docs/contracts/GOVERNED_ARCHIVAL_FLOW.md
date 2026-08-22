State: Enabling contract for GAF-01; no production adapter, persistence migration, backend, or generalized archival lifecycle is wired by this document.
Doc role: Cross-owner contract overlay
Authority: Defines only the provider-free values and adapter seam for governed archival flow. It is subordinate to HKA artifact authority, SIP identity/provenance, GOV policy and access decisions, PDM storage mechanics, DRI derivative posture, and every class-specific owner contract.
Owner: Product/Runtime architecture across HKA, SIP, GOV, PDM, DRI, and class adapters
Temporal class: enabling current implementation / future adapter contract
Review cadence: event-driven (adapter, policy, or liveness change)
Source of truth: GAF-01 common vocabulary; class-specific owner state remains authoritative
Last reviewed: 2026-08-22

# Governed Archival Flow Contract

## Purpose

Define a type-neutral vocabulary for moving or preserving a durable artifact across registered representations. The vocabulary preserves owner-native identity, generation, provenance, policy, access, liveness, and receipts without creating a new artifact ontology or storage authority.

This contract MUST NOT create a central archive authority, registry, or store. HKA owns human artifact meaning and recovery; SIP owns identity and provenance continuity; GOV owns policy, access, and accountability; PDM owns physical storage mechanics; DRI owns rebuildable derivatives. A class adapter maps its owner-native state into these types and never copies that state into this contract.

## Values and classification

`app.archival.contracts` defines the following provider-free values:

- `ArtifactIdentity` is an opaque owner-native identity, never a generated universal archive ID. A class-adapter identity carries its concrete adapter namespace, so equal native IDs from different adapters cannot collide.
- `RepresentationRef` is an opaque adapter-local resolver handle. A filesystem path, mount, URL, manifest location, or object key is not an identity, representation reference, or access grant.
- `ArtifactDescriptor` keeps artifact class (`source`, `human`, `derived`, `receipt`), derivation, durability, authoritative owner, generation, provenance references, and policy profile separate.
- `Liveness` reports typed active, pending, stale, missing, erased, or refused state. Only verified terminal physical outcome may project `erased`.
- `ArchivalReceipt` is redacted transition evidence. It cannot replace HKA artifact state, SIP identity, GOV policy/receipt authority, PDM representation state, or DRI rebuild lineage.

Location is routing context only. It MAY remain private adapter implementation detail, but it MUST NOT mint identity or read authority, and it MUST NOT appear in the common receipt surface.

## Policy profiles

The common vocabulary deliberately carries class-specific terminal outcomes rather than a universal delete operation:

| Profile | Owner-native terminal outcome |
| --- | --- |
| `raw_evidence` | Erase only on its consent/retention or revocation authority. |
| `retained_source` | Retain until its source owner explicitly retires it. |
| `hka_recovery` | Restore through the owner-native path with conflict checks. |
| `rebuildable_derivative` | Discard only after source and rebuildability proof. |

No profile inherits another profile's retention, revocation, or erasure authority.

## Adapter seam

`ArchivalAdapter` is a protocol, not a runtime service. A later owner-native adapter provides enumerate and resolve; authorize read; reserve a representation; verify; activate; retire; restore; erase or revoke where its policy allows; and read-only doctor/reconcile. The protocol does not select a backend, allocate a database, write a receipt, or authorize a caller itself.

Every adapter MUST use the owner's production read gate for normal reads and restore. It MUST retain a readable authoritative representation or a loud retryable state when reservation, verification, activation, retirement, or external cleanup is incomplete.

## Promoted archival kernel

The entries below are registered in `docs/testing/invariant-tests.md`; later runtime slices promote their enforcement only through their own production-path tests.

| ID | Normative rule |
| --- | --- |
| ARCHIVE-MUST-01 | Identity, provenance, generation, and opaque representation reference are never reconstructed from location. |
| ARCHIVE-MUST-02 | Ordinary reads and restore use the same owner-native gated read seam. |
| ARCHIVE-MUST-03 | A manifest or receipt records custody; it never forks HKA, SIP, GOV, PDM, or DRI authority. |
| ARCHIVE-MUST-04 | Reserve, durable copy, verification, receipt, and activation precede retirement. |
| ARCHIVE-MUST-05 | Terminal erasure follows all-representation handling, durable evidence, and completed physical cleanup. |
| ARCHIVE-MUST-06 | Durable admission has identity, provenance, policy, generation, and initial representation or fails closed. |
| ARCHIVE-MUST-07 | A representation is readable only through a registered resolver verifying identity and active generation. |
| ARCHIVE-GATE-01 | Each adapter proves gated restore, provenance preservation, and a redacted receipt. |
| ARCHIVE-GATE-02 | Cross-class validation covers raw media, human artifacts, and a rebuildable derivative with exclusions explicit. |
| ARCHIVE-GATE-03 | Durable adapters prove all-copy retention/revocation, no false success, and retryable cleanup. |
| ARCHIVE-GATE-04 | Parent acceptance and owner-doc promotion await all mandatory adapter gates. |
| ARCHIVE-DOCTOR-01 | Read-only doctor detects orphaned, missing, and identity-mismatched representations. |
| ARCHIVE-DOCTOR-02 | Read-only doctor detects absent identity without tombstone, stale generation, unresolved cleanup, and resolver mismatch. |
| ARCHIVE-DOCTOR-03 | Read-only doctor detects a derivative treated as source authority or human identity/provenance held only in a projection. |

## Non-goals

This contract does not add production wiring, persistence migration, backend/provider selection, cloud provisioning, a generic archive table, an archive content store, a universal artifact ID, or a new policy authority. GAF-02 and the class-adapter Issues own executable transition behavior.

## Related authority

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md` — capability boundary and cross-task invariants.
- `docs/contracts/ARTIFACT_CONTRACT.md` — HKA artifact authority.
- `docs/contracts/STORE_PORT.md` — PDM storage mechanics.
- `docs/architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md` — classification axes.
- `docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md` — accepted research basis.
