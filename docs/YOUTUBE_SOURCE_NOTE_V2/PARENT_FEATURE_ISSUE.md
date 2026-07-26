State: Unfiled parent-feature Issue draft. Do not claim as a GitHub issue until child contracts validate.

# feature: YouTube Source Note v2 — evidence-anchored review-required source bundles

Proposed labels: `type:task`, `prio:high`, `agent:blocked`

## Context

V1 delivers a governed, review-required YouTube candidate but its rendered truth surfaces are incomplete and its summary cannot be checked against evidence. This parent is the validation hub for the bounded v2 contracts in `docs/YOUTUBE_SOURCE_NOTE_V2/README.md`.

## Scope

Deliver the v2 source-note capability through its twelve child task contracts. The parent does not authorize direct implementation; it owns cross-task validation, decision gating, and owner-doc promotion.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Lineage and replay`
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`

## SBS Impact

- Primary subsystem: HKA
- Secondary subsystem(s): SIP, GOV, PDM, EBF, RCA, MEM, CAO, OEF, WSP
- Write class: authority-bearing candidate materialization plus derived/rebuildable child writes
- Authority impact: preserves review-required proposal posture; no automatic promotion
- Persistence impact: introduces bounded durable derived artifacts only through child contracts
- Derived/rebuildable impact: lineage-preserving extraction/transcript/bundle evolution
- Human knowledge impact: candidate notes are never overwritten
- Memory impact: none
- Retrieval/context impact: governed overlay only after its child contract
- Sync/deployment impact: none
- External boundary impact: bounded optional frame-media egress only through YSNV2-11 under the recorded D1 opt-in posture
- New or changed contract: `docs/YOUTUBE_SOURCE_NOTE_V2/*`; `docs/contracts/ARTIFACT_CONTRACT.md`, `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`, `docs/contracts/STORE_PORT.md`, `docs/contracts/CONTEXT_BUNDLE.md`, `docs/contracts/MEMORY_RECORD.md`, and `docs/contracts/A2A_CONTRACT_AND_TRACE.md` apply
- Owner-doc impact: will-update-in-PR at accepted capability truth
- Transition debt impact: reduces untruthful V1 candidate surfaces
- Fitness rule impact: strengthens provenance, replay, and human-authority preservation
- Boundary risk: high — persistence, evidence provenance, human-authored content, media egress, and future profile authority must remain separated across child slices

## Constraints

- Preserve every invariant in `README.md :: Cross-Task Invariants / Interaction Safety`.
- Implement frame capture only under the recorded D1 opt-in/context-frame posture.
- Apply D6: system prose is English unless the source's original language is Swedish; quotations remain original-language.
- Do not treat the external design brief as authority.

## Acceptance Criteria

- [ ] All twelve child contracts are delivered, with each merged child posting its `Verify:` receipt to this parent; until the separate vault-wide profile contract exists, YSNV2-10 and this parent remain truthfully dependency-blocked.
  Verify: parent issue validation ledger mirrors `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Execution order and proposed issue state`.
- [ ] A representative v2 note proves immutable evidence, anchored claims, non-destructive candidate materialization, and no-egress replay together.
  Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_v2_end_to_end_invariant_matrix`.
- [ ] Owner docs describe only accepted v2 behavior and retain undelivered dependencies as gates.
  Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`.

## Implementation Tasks

1. `RECONCILE_SOURCE_NOTE_V2_CONTRACT.md`
2. `FIX_CANDIDATE_TRUTH_SURFACES.md`
3. `COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md`
4. `PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS.md`
5. `PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md`
6. `MATERIALIZE_PORTABLE_YOUTUBE_SOURCE_BUNDLE.md`
7. `ROUTE_CONTENT_AND_RENDER_INITIAL_MODULES.md`
8. `EXTRACT_GATED_ONTOLOGY_PROPOSALS.md`
9. `SELECT_TIMESTAMPED_KEY_MOMENTS.md`
10. `APPLY_GOVERNED_INTEREST_OVERLAY.md`
11. `CAPTURE_OPT_IN_SOURCE_FRAMES.md`
12. `EVALUATE_SOURCE_NOTE_QUALITY.md` — final invariant matrix and parent-closure handoff after tasks 1–11

## Verification Path

Run each child’s focused `Verify:` targets. YSNV2-12 owns the parent invariant matrix and runs it only after prerequisite children 1–11 are merged; after YSNV2-12 merges, its receipt supplies the parent-closure handoff. Use host leasing for any repo-wide suite the child contract requires.

## Validation / Acceptance Path

The parent remains `agent:blocked` while children or the vault-wide profile dependency remain. Record the operator-approved gold-set annotation scope and any source/media consent directly on the live parent validation ledger; the static spec cannot serve as that receipt. At candidate acceptance, validate the invariant matrix, attach receipts for recorded decisions where applicable, and promote current-state owner docs in one explicit PR.

## Out of Scope

Automatic promotion, candidate-note mutation, cross-source generalization, a UI, and media capture outside the recorded D1 posture.

## Suggested Validation

- `pytest -q tests/knowledge_acquisition/test_source_note_quality.py::test_v2_end_to_end_invariant_matrix`
- Review child receipts against `README.md :: Cross-Task Invariants / Interaction Safety`.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`

## Applies learning (optional)

None.
