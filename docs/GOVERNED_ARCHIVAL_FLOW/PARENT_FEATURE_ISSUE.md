# Parent Feature Issue #5062 — Governed Archival Flow

State: Filed live validation hub #5062 (`agent:blocked`). GitHub owns current backlog/lifecycle
state. This parent is never direct pickup work.

Live title: `feature: governed archival flow across durable artifact classes`

## Context

The accepted architecture audit found that Heimdal already carries a strong governed archive
mechanism, but its owner contract is raw-media-specific while HKA, retained sources, media originals,
and rebuildable derivatives have different authority and lifecycle rules. PromotionIntent
`prom_20260822201148_cc5214d7` and receipt `receipt_20260822201151_94c61ba1` authorize conversion of
that research into this specification and bounded backlog.

## Scope

Deliver a type-neutral archival contract, verified transition kernel, owner-native adapters for
Heimdal raw media, retained source artifacts, and HKA recovery, plus derivative disposition and a
cross-class validation/doctor path. Preserve class-specific policy and avoid a central archive
authority.

## Source Anchors

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Capability Boundary`
- `docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md :: Why the narrow implementation happened`
- `docs/EVENTS.md :: Heimdal local archive restore + all-copy expiry`
- `docs/contracts/ARTIFACT_CONTRACT.md :: Invariants`
- `docs/contracts/STORE_PORT.md :: Invariants`

## SBS Impact

- Primary subsystem: PDM - Persistence & Data Management
- Secondary subsystem(s): HKA, SIP, GOV, DRI, EBF/Heimdal
- Write class: authority-bearing durable runtime representations plus governance/docs contracts
- Persistence impact: durable owner-native representations, transition/restore/deletion receipts, and typed liveness; no central registry
- Derived/rebuildable impact: explicit refusal and doctor path for derivatives, embeddings, indexes, and caches
- New or changed contract: GovernedArchivalFlow adapter and transition contract
- Owner-doc impact: follow-up owner-doc promotion after parent validation
- Transition debt impact: reduces source-specific archive duplication and implicit cross-modality behavior
- Boundary risk: the common kernel must never absorb artifact meaning, policy authority, or storage ownership from HKA/SIP/GOV/PDM/DRI

## Constraints

- Existing #3842 and HAR-01..05 remain closed prior art and must not be duplicated.
- No central archive database or new SBS subsystem.
- No artifact inherits another class's retention/revocation policy.
- No production source retires before durable verified destination activation.
- Restore always uses the owner-native access/governed-write seam.
- No implementation from this parent Issue; only bounded children are pickup work.

## Acceptance Criteria

- [ ] All GAF child Issues reach verified terminal closure and their parent receipts bind exact merge SHAs.
  - Verify: runtime receipt: builderops.epic-delivery-ledger.v1
- [ ] The common kernel and every delivered adapter satisfy the cross-task invariant matrix without a central authority fork.
  - Verify: `tests/archival/test_cross_class_conformance.py::test_cross_class_adapters_preserve_owner_authority`
- [ ] Audio, image, video, and document raw media pass the existing production Heimdal gate, restore, retention, revocation, and liveness paths.
  - Verify: `tests/archival/test_heimdal_adapter.py::test_all_admitted_raw_modalities_conform_to_archive_contract`
- [ ] Retained-source and HKA recovery adapters prove their distinct policy and conflict behavior.
  - Verify: `tests/archival/test_cross_class_conformance.py::test_source_and_hka_policy_profiles_do_not_collapse`
- [ ] A durable redacted validation receipt proves restore, partial-failure refusal, deletion/liveness truth, and read-only doctor behavior across the representative matrix.
  - Verify: runtime receipt: governed-archival-validation.v1
- [ ] Owner docs claim the generalized capability only after that receipt exists on delivered `main`.
  - Verify: doc writeback at `docs/EVENTS.md :: Governed archival flow`

## Implementation Tasks

1. GAF-01 — #5063 — `DEFINE_ARCHIVAL_CONTRACT.md`
2. GAF-02 — #5064 — `IMPLEMENT_VERIFIED_TRANSITION_KERNEL.md`
3. GAF-03 — #5065 — `ADAPT_HEIMDAL_RAW_MEDIA.md`
4. GAF-04 — #5066 — `ADAPT_RETAINED_SOURCE_ARTIFACTS.md`
5. GAF-05 — #5067 — `ADAPT_HUMAN_ARTIFACT_RECOVERY.md`
6. GAF-06 — #5068 — `GOVERN_REBUILDABLE_DERIVATIVES.md`
7. GAF-07 — #5069 — `VERIFY_CROSS_CLASS_ARCHIVAL_LIFECYCLE.md`

## Verification Path

Each child resolves every `Verify:` target in its task specification and Issue body at exact head.
Stateful or enforcement claims are proved through production call sites. Existing Heimdal HAR tests
remain mandatory for GAF-03; GAF-07 runs the full cross-adapter conformance matrix and read-only
doctor.

## Validation / Acceptance Path

After each child merge, append one exact-SHA receipt to this Issue. GAF-07 emits
`governed-archival-validation.v1` and hands off parent closure. The parent remains open until the
receipt is read back, owner docs are promoted once, and every child is terminal.

## Out of Scope

- New cloud/off-site storage, key-provider selection, retention-duration changes, legal-policy
  decisions, universal file scanning, or unrestricted archive browsing.
- Reimplementation of HAR-01..05.
- Runtime implementation in this parent Issue.

## Suggested Validation

- Run every child Issue's declared test ledger.
- Run `pytest -q tests/archival` after each adapter wave.
- Run existing `tests/heimdal/test_local_archive*.py` for GAF-03 and final validation.
- Validate the final parent receipt against exact merged SHAs and current owner docs.

## Source Docs

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md`
- `docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md`
- `docs/architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/STORE_PORT.md`
- `docs/HEIMDAL_LOCAL_ARCHIVE/README.md`

## Applies learning (optional)

The audit's “Why the narrow implementation happened” analysis shaped the shared-kernel-versus-
adapter cut. Accepted promotion: `prom_20260822201148_cc5214d7` /
`receipt_20260822201151_94c61ba1`.
