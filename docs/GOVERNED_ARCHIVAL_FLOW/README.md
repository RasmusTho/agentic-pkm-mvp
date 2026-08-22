State: Filed target-state capability specification; parent validation hub #5062 is open and
`agent:blocked`. PromotionIntent `prom_20260822201148_cc5214d7` was accepted by BuilderOpsReceipt
`receipt_20260822201151_94c61ba1`. No generalized runtime delivery is claimed. Existing Heimdal
HAR-01..05 is delivered evidence and is reconciled as the first raw-media adapter, not duplicated.

Doc role: Capability specification (feature-breakdown lane)

Authority: Owns the target governed archival-flow contract and acceptance shape. Current-state owner docs and class-specific runtime contracts remain authoritative until each adapter is delivered and the parent capability is accepted.

Owner: Product/Runtime architecture across HKA, SIP, GOV, PDM, DRI, and source adapters

Temporal class: strategic target-state

Review cadence: event-driven (task merge, artifact-class change, retention/revocation change, or parent acceptance)

Source of truth: this directory for the promoted target capability; GitHub parent/child Issues become execution and validation authority when filed

Last reviewed: 2026-08-22 against `origin/main` `f568e457f2bad7e15997fc405615f3deffda8abb`

# Governed Archival Flow

## Capability Boundary

Provide one type-neutral lifecycle contract for preserving or moving a durable artifact across
registered representations while retaining its identity, provenance, policy authority, gated
access, restore proof, retention/revocation semantics, deletion evidence, and honest liveness.

The capability is an overlay, not a universal store. Artifact owners retain semantic and lifecycle
authority; PDM owns storage mechanics; GOV owns access and policy decisions; SIP carries identity and
provenance; DRI owns rebuildable derivatives. Adapters map those owner-native contracts into the
common flow without copying their truth into a central archive registry.

## Current-Main Reconciliation

- Heimdal parent #3842 and HAR-01..05 (#3847–#3851) are closed. PR #5061 delivered HAR-05 at
  `f568e457f2bad7e15997fc405615f3deffda8abb`, including gated restore, consent revocation,
  `erasure_pending`, durable cold cleanup, and all-copy expiry. This supersedes the audit snapshot's
  pre-HAR-05 implementation gaps; it does not generalize the owner contract by itself.
- `app.heimdal.media_ingress` already admits `audio`, `image`, `video`, and `document` into the raw
  representation/liveness substrate. The current archive selector is modality-neutral. GAF-03
  therefore proves and exposes that behavior through the shared adapter contract rather than
  reimplementing four archive pipelines.
- The accepted artifact-classification, HKA ArtifactContract, PDM StorePort, retention-surface, and
  media-original docs already define ownership distinctions. GAF-01 reconciles and operationalizes
  them; it does not create a competing artifact ontology.

## SBS Classification

This is Product/Runtime work crossing existing subsystem boundaries:

- HKA owns durable human-authored and human-accepted artifacts and portable recovery.
- SIP owns stable identity and provenance continuity.
- GOV owns access, consent, retention/revocation authority, and receipts.
- PDM owns representation storage, migration, restore mechanics, encryption, and health.
- DRI owns rebuildable derivatives, indexes, embeddings, caches, and source-lineage checks.
- Heimdal and future source/retention adapters remain EBF/source-specific integration seams.

BuilderOps PromotionIntent and GitHub Issues authorize delivery but never become Product/Runtime
artifact or archive authority.

## Artifact-Class Posture

| Class | Governed archival posture | Adapter |
| --- | --- | --- |
| Raw evidence and admitted raw media (`audio`, `image`, `video`, `document`) | Consent/retention-bound durable source; all-copy erasure and gated restore | Existing Heimdal adapter, conformed by GAF-03 |
| Curated retained-source and media-original artifacts | Durable source after explicit keep/admission; no implicit raw-media TTL | Retained-source adapter, GAF-04 |
| Human-authored or human-accepted artifact | Portable export/recovery and governed conflict handling; no raw-evidence deletion semantics | HKA recovery adapter, GAF-05 |
| Derivative, embedding, index, OCR, thumbnail, cache | Rebuildable by default; refuse source-authority promotion unless explicitly reclassified | DRI disposition/doctor, GAF-06 |
| Receipt, tombstone, manifest, liveness record | Durable governance/system evidence; never a substitute for source content | Common contract and owner-native receipt stores |

## Implementation Tasks

| Order | Task | ID | Issue | Depends on | TCD hint — cheapest acceptable |
| --- | --- | --- | --- | --- | --- |
| 1 | [Define archival contract](DEFINE_ARCHIVAL_CONTRACT.md) | GAF-01 | #5063 | — | Terra / high; architecture and authority boundaries |
| 2 | [Implement verified transition kernel](IMPLEMENT_VERIFIED_TRANSITION_KERNEL.md) | GAF-02 | #5064 | GAF-01 | Sol / high; state machine, data-loss and concurrency risk |
| 3 | [Adapt Heimdal raw media](ADAPT_HEIMDAL_RAW_MEDIA.md) | GAF-03 | #5065 | GAF-02 | Sol / high; protected raw-data and erasure path |
| 4 | [Adapt retained source artifacts](ADAPT_RETAINED_SOURCE_ARTIFACTS.md) | GAF-04 | #5066 | GAF-02, GAF-03 | Terra / high; new durable source adapter |
| 5 | [Adapt human artifact recovery](ADAPT_HUMAN_ARTIFACT_RECOVERY.md) | GAF-05 | #5067 | GAF-02, GAF-03 | Terra / high; HKA authority and conflict-safe recovery |
| 6 | [Govern rebuildable derivatives](GOVERN_REBUILDABLE_DERIVATIVES.md) | GAF-06 | #5068 | GAF-01 | Terra / medium; bounded classification and read-only doctor |
| 7 | [Verify cross-class archival lifecycle](VERIFY_CROSS_CLASS_ARCHIVAL_LIFECYCLE.md) | GAF-07 | #5069 | GAF-03, GAF-04, GAF-05, GAF-06 | Terra / high; cross-adapter validation and parent receipt |

TCD hints are non-binding. `issue-to-code` re-derives the current model/reasoning from the live
Issue, code risk, and standard escalation triggers. Implementation defaults to one fresh Issue
agent at a time; GAF-04, GAF-05, and GAF-06 are scheduling-independent after their prerequisites,
but concurrency is used only when it lowers total delay more than it adds context and coordination.

## Execution Order

Flat dependency order:

`GAF-01 → GAF-02 → GAF-03 → (GAF-04, GAF-05, GAF-06) → GAF-07`

GAF-06 may begin after GAF-01, but the default low-TCD delivery queue keeps one implementation agent
active and preserves a slot for verification/recovery. GAF-07 is the final child and owns the parent-
closure handoff, not the parent closure itself.

## Cross-Task Invariants / Interaction Safety

1. **Identity is never reconstructed from location.** Every adapter preserves owner-native artifact
   identity, content identity where applicable, origin/provenance, generation, and opaque
   representation references. A copied path, mount, filename, or manifest cannot mint authority.
2. **No central authority fork.** The common kernel may orchestrate and receipt transitions, but an
   adapter's owner-native registry remains authoritative. A common receipt cannot replace an HKA
   artifact, Heimdal raw record, retained source, GOV decision, or DRI rebuild recipe.
3. **Verification precedes source retirement.** Destination reservation, durable bytes, identity
   verification, owner-native receipt, and activation all complete before a superseded
   representation can retire. Any partial failure preserves a readable authoritative source or a
   loud retryable state.
4. **Policy is class-specific and fail-closed.** Raw evidence may expire or revoke automatically;
   retained sources require their explicit retention policy; HKA recovery never inherits raw TTL;
   rebuildable derivatives may be discarded only when their source/rebuild recipe is proven.
5. **Access and restore share the production gate.** An archive mount or backend capability never
   authorizes a read. Every adapter restores through its owner-native access path and emits a
   redacted receipt only after successful verification.
6. **Terminal liveness requires terminal physical outcome.** A pending external cleanup, lease,
   conflict, missing object, stale generation, or unverified restore projects a typed non-terminal
   state. No API or parent receipt rewrites it as `erased`, `restored`, or accepted.
7. **Adapter rollout is additive.** Before an adapter is wired, the kernel has no production effect.
   After wiring, existing class-specific tests remain binding. If GAF-02 lands but GAF-03 is blocked,
   HAR continues on its current implementation path; no half-migrated producer is allowed.
8. **Recovery does not overwrite newer authority.** A restored HKA or retained-source representation
   is staged and conflict-checked. A newer owner-native generation remains authoritative until a
   governed promotion accepts the recovered representation.
9. **Derivatives never become the last copy of meaning.** GAF-06 may classify or diagnose but cannot
   archive a rebuildable artifact as source authority. An explicit reclassification routes to HKA or
   retained-source ownership before archival admission.

## Capability Acceptance Criteria

- [ ] The shared contract and transition kernel preserve identity, authority ownership, verified
      ordering, typed liveness, and class-specific policy without a central archive registry.
      Verify: `tests/archival/test_transition_kernel.py::test_verified_transition_is_durable_before_source_retirement`
- [ ] Existing Heimdal raw archive behavior conforms for audio, image, video, and document media and
      retains all HAR-05 gated restore/erasure guarantees.
      Verify: `tests/archival/test_heimdal_adapter.py::test_all_admitted_raw_modalities_conform_to_archive_contract`
- [ ] One curated retained source can archive and restore without path authority, implicit TTL, or
      loss of source provenance.
      Verify: `tests/archival/test_retained_source_adapter.py::test_retained_source_round_trip_preserves_identity_and_provenance`
- [ ] One HKA artifact can export and recover in human-readable form without overwriting a newer
      authoritative generation.
      Verify: `tests/archival/test_hka_recovery_adapter.py::test_human_artifact_recovery_refuses_newer_generation_overwrite`
- [ ] Rebuildable derivatives remain non-authoritative and the doctor detects missing source/rebuild
      evidence without mutation.
      Verify: `tests/archival/test_derived_disposition.py::test_rebuildable_derivative_is_not_archive_authority`
- [ ] The cross-class matrix emits a durable redacted parent-validation receipt and proves no false
      success across restore, retention, revocation, deletion, and liveness outcomes.
      Verify: runtime receipt: governed-archival-validation.v1
- [ ] Current-state owner docs are promoted only after the delivered matrix is accepted on `main`.
      Verify: doc writeback at `docs/EVENTS.md :: Governed archival flow`

## Relationship to GitHub Issues

- Parent feature Issue: #5062 is the live blocked validation hub; `PARENT_FEATURE_ISSUE.md` mirrors
  its contract and must stay lifecycle-truthful.
- Child Issues #5063–#5069 are filed from GAF-01..07; every task frontmatter carries its exact
  `github_issue:` join in this breakdown delivery.
- Closed #3842 and #3847–#3851 remain delivery evidence for the Heimdal adapter. No HAR Issue is
  reopened or duplicated.
- The parent remains `agent:blocked` while children are outstanding. GAF-01 is initially
  `agent:ready`; dependency-bound children start `agent:blocked`.

## Verification and Validation Evidence

- Child PRs prove their exact task `Verify:` ledger at current head.
- Each delivered child posts one compact receipt to the parent Issue.
- GAF-07 produces `governed-archival-validation.v1` from the production adapters and read-only
  doctor; it does not infer acceptance from green unit tests alone.
- Parent acceptance then triggers one owner-doc promotion pass and parent closure.

## Out of Scope

- A universal archive database, new SBS subsystem, cloud/off-site provider, or replacement for PDM.
- Changing any artifact class's retention duration, consent policy, legal retention, or HKA
  ownership rules.
- Treating all files as durable sources, or archiving caches/embeddings/indexes by default.
- Unrestricted browsing of raw or retained source bytes.
- Reopening or rewriting delivered Heimdal HAR-01..05.

## Source Anchors

- `docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md`
- `docs/architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/STORE_PORT.md`
- `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_RETENTION_SURFACE_CONTRACT.md`
- `docs/HEIMDAL_LOCAL_ARCHIVE/README.md`
- `docs/EVENTS.md`
