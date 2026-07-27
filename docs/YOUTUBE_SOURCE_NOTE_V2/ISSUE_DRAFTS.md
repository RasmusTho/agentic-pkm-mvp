State: Filed GitHub Issue body records for child Issues #4108–#4119 under parent #4107. The live Issues are the executable task contracts; this file preserves their validated source bodies and label intent without claiming runtime delivery.

# YouTube Source Note v2 Child Issue Drafts

Each block below records the filed body source after parent replacement. The detailed acceptance and validation instructions remain in its linked task specification; every behavioral acceptance repeats its exact test commitment here.

## YSNV2-01 — task: reconcile YouTube Source Note v2 contract

Labels: `type:task`, `prio:high`, `agent:ready`

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/RECONCILE_SOURCE_NOTE_V2_CONTRACT`. Prepare the authoritative contract for the v2 capability; no runtime implementation is included. TCD hint: Terra/high — bounded contract reconciliation with multiple authority-sensitive doc anchors.

## Scope

Reconcile confirmed V1 defects, partial-success semantics, valid metadata mapping, and recorded D1–D6 decisions as specified by `RECONCILE_SOURCE_NOTE_V2_CONTRACT.md`.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/RECONCILE_SOURCE_NOTE_V2_CONTRACT.md :: Acceptance Criteria`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Stage execution model`

## SBS Impact

- Primary subsystem: HKA
- Secondary subsystem(s): SIP, GOV, PDM, OEF, CES practice
- Write class: governance/docs/process
- Authority impact: defines future candidate authority constraints; no runtime mutation
- Persistence impact: none
- Derived/rebuildable impact: specifies future lineage and materialization rules; no derived artifact changes in this slice
- Human knowledge impact: specifies non-destructive candidate behavior; no current human artifact mutation
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: none
- New or changed contract: Product source-note owner-contract writebacks; `docs/contracts/ARTIFACT_CONTRACT.md` applies and is unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: records the three confirmed V1 truth gaps and preserves non-defects
- Fitness rule impact: doc-anchor and schema review only; behavioral fitness remains in later child issues
- Boundary risk: medium — target-state wording must not be promoted as shipped runtime truth

## Constraints

- Do not alter recorded D1–D6 decisions.
- Do not claim v2 behavior shipped.

## Acceptance Criteria

- [ ] Confirmed V1 defect and non-defect boundaries are recorded. Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`.
- [ ] Required/optional extractor policy is defined. Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Stage execution model`.
- [ ] Metadata-bundle rules preserve top-level fields, object-form `scope_binding`, and required identity/provenance/episode/sensitivity/suppression resolution. Verify: doc writeback at `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Reconciliation baseline`.
- [ ] Recorded D1–D6 decisions are preserved, including D5 versioned proposal companions and D6 English output except for Swedish-original sources. Verify: operator receipt at `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Owner decision record`.

## Out of Scope

Runtime code, schemas, Issue filing, and changes to recorded D1–D6 decisions.

## Suggested Validation

- Review all four cited writeback/decision anchors against `docs/architecture/metadata-bundle.md` and `schemas/metadata-bundle.schema.json`.
- Run `python3 scripts/docs_guard.py` when guarded owner-doc surfaces change.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/RECONCILE_SOURCE_NOTE_V2_CONTRACT.md`

## Applies learning (optional)

None.

## YSNV2-07 — task: route content and render initial modules

Labels: `type:task`, `prio:med`, `agent:blocked` (YSNV2-03/05)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/ROUTE_CONTENT_AND_RENDER_INITIAL_MODULES`. V2 needs conservative content-sensitive modules without profile overclaim or a second note shape. TCD hint: Terra/high — bounded router/template work with explicit degradation and language-policy tests.

## Scope

Implement the bounded router and the initial decision-framework/documentary-science modules.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/ROUTE_CONTENT_AND_RENDER_INITIAL_MODULES.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: CAO
- Secondary subsystem(s): HKA, SIP, OEF
- Write class: derived
- Authority impact: generic degradation prevents profile overclaim
- Persistence impact: none beyond upstream extracted artifacts
- Derived/rebuildable impact: adds rebuildable routing and module projections
- Human knowledge impact: modules remain proposal-only and cannot replace owner-authored content
- Memory impact: none
- Retrieval/context impact: router consumes only source-bound evidence
- Sync/deployment impact: none
- External boundary impact: model inference remains under existing LLM routing; no source egress
- New or changed contract: bounded content-router and module schemas; `docs/contracts/CAPABILITY_CONTRACT.md` and `docs/contracts/ARTIFACT_CONTRACT.md` apply and are unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: replaces the fixed generic rendering limitation without changing note authority
- Fitness rule impact: bounded-router, module-composition, degradation, and D6 language tests
- Boundary risk: medium — misclassification or generated prose must not overclaim source/profile meaning

## Constraints

- At most two profiles; modules cannot replace the universal spine.

## Acceptance Criteria

- [ ] Router falls back to generic on uncertainty/failure. Verify: `tests/knowledge_acquisition/test_content_router.py::test_router_is_bounded_and_falls_back_to_generic_on_uncertainty_or_failure`.
- [ ] Modules compose under shared wrapper. Verify: `tests/knowledge_acquisition/test_note_modules.py::test_initial_modules_compose_under_shared_proposal_wrapper`.
- [ ] Module failure preserves required evidence note. Verify: `tests/knowledge_acquisition/test_note_modules.py::test_optional_module_failure_preserves_required_evidence_note`.
- [ ] System-generated module prose follows D6 while source wording and quotations remain original-language. Verify: `tests/knowledge_acquisition/test_note_modules.py::test_module_prose_follows_source_language_policy`.

## Out of Scope

Ontology, interest, and moments.

## Suggested Validation

- Run the four named focused tests.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/ROUTE_CONTENT_AND_RENDER_INITIAL_MODULES.md`

## Applies learning (optional)

None.

## YSNV2-08 — task: extract gated ontology proposals

Labels: `type:task`, `prio:med`, `agent:blocked` (YSNV2-05)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/EXTRACT_GATED_ONTOLOGY_PROPOSALS`. Ontology output is useful only when source evidence warrants it and must never become canonical through extraction. TCD hint: Sol/xhigh — provenance and proposal-authority boundaries have high hidden-defect cost.

## Scope

Implement the gate and evidence-anchored proposal-only ontology output.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/EXTRACT_GATED_ONTOLOGY_PROPOSALS.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: SIP
- Secondary subsystem(s): HKA, GOV, OEF
- Write class: derived
- Authority impact: no canonical ontology writes
- Persistence impact: rebuildable proposal artifacts
- Derived/rebuildable impact: ontology output remains regenerable source-bound proposal data
- Human knowledge impact: no canonical concept or relation mutation
- Memory impact: none
- Retrieval/context impact: no unscoped context reads
- Sync/deployment impact: none
- External boundary impact: model inference remains under existing LLM routing; no source egress
- New or changed contract: deterministic ontology relevance gate and proposal schema; `docs/contracts/ARTIFACT_CONTRACT.md` applies and is unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: none beyond adding the new gated proposal path
- Fitness rule impact: gate, anchoring, authority-transition, and D6 language tests
- Boundary risk: high — ontology-shaped output must never acquire canonical standing through extraction

## Constraints

- Failed gate omits section; proposal output cannot promote itself.

## Acceptance Criteria

- [ ] Gate needs distinct repeated anchored signals. Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_gate_requires_distinct_repeated_anchored_signals`.
- [ ] Output is proposal-class and fully anchored. Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_output_is_proposal_class_and_fully_anchored`.
- [ ] No canonical write/authority transition occurs. Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_extraction_has_no_canonical_write_or_authority_transition`.
- [ ] Ontology `system_paraphrase` follows D6 while source definitions and quotations retain original language. Verify: `tests/knowledge_acquisition/test_ontology_extractor.py::test_ontology_system_paraphrase_follows_source_language_policy`.

## Out of Scope

Ontology promotion or editor UI.

## Suggested Validation

- Run the four named focused tests.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/EXTRACT_GATED_ONTOLOGY_PROPOSALS.md`

## Applies learning (optional)

None.

## YSNV2-09 — task: select timestamped key moments

Labels: `type:task`, `prio:med`, `agent:blocked` (YSNV2-05)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/SELECT_TIMESTAMPED_KEY_MOMENTS`. Timestamped moments are independently valuable and must not depend on screenshots. TCD hint: Sol/xhigh — selection, provenance, and the later media seam require mechanism-level review.

## Scope

Implement evidence-linked candidate generation, bounded selection, and timestamp-only degradation.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/SELECT_TIMESTAMPED_KEY_MOMENTS.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: SIP
- Secondary subsystem(s): HKA, EBF, OEF
- Write class: derived
- Authority impact: source-bound moment rationale
- Persistence impact: rebuildable moment artifacts
- Derived/rebuildable impact: timestamp selections remain rebuildable and frame-independent
- Human knowledge impact: no human-authored content mutation
- Memory impact: none
- Retrieval/context impact: selection consumes only source-bound transcript/chapter/claim evidence
- Sync/deployment impact: none
- External boundary impact: none; this slice forbids media acquisition and source egress
- New or changed contract: bounded timestamped-moment selection; `docs/contracts/ARTIFACT_CONTRACT.md` applies and is unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: none beyond adding the new moment projection
- Fitness rule impact: lineage, selection-budget, no-media, and D6 rationale tests
- Boundary risk: medium — timestamp evidence and later media capture must remain separable

## Constraints

- Do not acquire media or create frames.

## Acceptance Criteria

- [ ] Selected moments are timestamped, anchored, and lineage-bearing. Verify: `tests/knowledge_acquisition/test_key_moments.py::test_selected_moments_are_timestamped_anchored_and_lineage_bearing`.
- [ ] Selection enforces budget/diversity/evidence relevance. Verify: `tests/knowledge_acquisition/test_key_moments.py::test_moment_selection_enforces_budget_diversity_and_evidence_relevance`.
- [ ] Timestamp-only moments require no frame/media egress. Verify: `tests/knowledge_acquisition/test_key_moments.py::test_timestamp_only_moments_need_no_frame_or_media_egress`.
- [ ] System-generated moment rationale follows D6 while source wording and quotations remain original-language. Verify: `tests/knowledge_acquisition/test_key_moments.py::test_moment_rationale_follows_source_language_policy`.

## Out of Scope

Frame capture and temporary video.

## Suggested Validation

- Run the four named focused tests.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/SELECT_TIMESTAMPED_KEY_MOMENTS.md`

## Applies learning (optional)

None.

## YSNV2-10 — task: apply governed interest overlay

Labels: `type:task`, `prio:med`, `agent:blocked` (YSNV2-05; future vault-wide profile contract; D4 direction recorded)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/APPLY_GOVERNED_INTEREST_OVERLAY`. The owner chose a behavior-derived relevance profile shared across the vault; YouTube must consume it rather than create a separate profile. The future ProfileAgent is the sole system-agent writer of approved profile content. Other agents may submit inspectable ProfileUpdateCandidate A2A handoffs, but those are data rather than instructions or approval. ProfileAgent may offer an update only as an unchecked item in the profile document's high-placement AI panel; a checked item must complete governed Panel confirmation, ProfileAgent's write, and a receipt before its result is consumable. A direct owner correction remains owner authority and is never silently overwritten. TCD hint: Sol/xhigh — cross-scope profile authority and admission semantics are critical; this Issue remains blocked until the separate authoritative contract exists.

## Scope

Implement the read-only consumer of the future vault-wide profile projection and the four-part connection renderer.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/APPLY_GOVERNED_INTEREST_OVERLAY.md :: Acceptance Criteria`
- `docs/architecture/cross-scope-flow.md`
- `docs/PANEL_AGENT.md :: Canonical confirmation semantics`
- `docs/AGENT-FLOWS.md :: Handoff artifacts and agent-to-agent continuity`
- Future vault-wide relevance-profile owner contract (not yet authored)

## SBS Impact

- Primary subsystem: RCA
- Secondary subsystem(s): MEM, GOV, WSP, HKA, SIP, CAO
- Write class: derived
- Authority impact: read-only, ProfileAgent-written, receipted vault-wide behavior profile; no local profile construction or consumption of handoffs/pending proposals
- Persistence impact: none
- Derived/rebuildable impact: overlay connections are rebuildable proposals
- Human knowledge impact: no profile or source-note human-content mutation
- Memory impact: consumes only the future approved ProfileAgent projection; pending candidates/proposals are inadmissible
- Retrieval/context impact: same-scope allowlisted read only; no secret, suppressed, unrelated, or ungranted cross-scope context
- Sync/deployment impact: none
- External boundary impact: none
- New or changed contract: read-only overlay consumer; `docs/contracts/CONTEXT_BUNDLE.md`, `docs/contracts/MEMORY_RECORD.md`, `docs/contracts/A2A_CONTRACT_AND_TRACE.md`, and the future vault-wide profile contract apply
- Owner-doc impact: will-update-in-PR
- Transition debt impact: remains explicitly blocked; no YouTube-local profile fallback is permitted
- Fitness rule impact: admission, field-separation, cold-start, and D6 language tests after the external contract exists
- Boundary risk: critical — profile authority, A2A data, confirmation state, and cross-scope access must not collapse

## Constraints

- No secret/suppressed, unapproved or unrelated agent-memory, or ungranted cross-scope reads; no ProfileUpdateCandidate handoff or pending ProfileAgent proposal consumption; no local behavior-profile construction. The approved ProfileAgent projection is the sole agent-memory exception.

## Acceptance Criteria

- [ ] Only the authorized same-scope, ProfileAgent-written vault-wide profile projection with a completed confirmation receipt is consumed; ProfileUpdateCandidate handoffs and pending proposals are rejected. Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_consumes_only_authorized_vault_wide_profile_projection`.
- [ ] Connections need separated anchor and owner-link fields. Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_connection_requires_anchor_and_owner_link_with_separated_fields`.
- [ ] Cold start does not construct a local behavior profile. Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_cold_start_does_not_construct_local_behavior_profile`.
- [ ] Overlay system inference and suggested-use prose follow D6 while `source_says` and quotations remain original-language. Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_system_inference_and_suggested_use_follow_source_language_policy`.

## Out of Scope

Creating/proposing/mutating the vault-wide profile, its ProfileAgent, ProfileUpdateCandidate A2A handoffs, its high-placement AI panel, or automatic follow-up actions.

## Suggested Validation

- Run the four named focused tests.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/APPLY_GOVERNED_INTEREST_OVERLAY.md`

## Applies learning (optional)

None.

## YSNV2-11 — task: capture opt-in source frames

Labels: `type:task`, `prio:low`, `agent:blocked` (YSNV2-09; D1 resolved)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/CAPTURE_OPT_IN_SOURCE_FRAMES`. Frames are source-dependent media derivatives with rights, retention, and egress implications. TCD hint: Sol/xhigh — media rights, retention, egress, and deletion receipts carry high defect cost.

## Scope

Use the recorded opt-in capture posture, retaining one contextual frame on successful acquisition, plus exception metadata and deletion receipts.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/CAPTURE_OPT_IN_SOURCE_FRAMES.md :: Acceptance Criteria`
- `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md :: media_derivative`

## SBS Impact

- Primary subsystem: EBF
- Secondary subsystem(s): HKA, SIP, GOV, PDM, OEF
- Write class: derived
- Authority impact: frame remains source-dependent derivative
- Persistence impact: approved durable frames; temporary media must be deleted
- Derived/rebuildable impact: retained frames are source-dependent exceptions, not ordinary rebuildable extractions
- Human knowledge impact: no candidate or human-authored content overwrite
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: bounded temporary media egress
- New or changed contract: explicit opt-in capture, contextual-frame exception, rights metadata, and deletion receipt; `docs/contracts/ARTIFACT_CONTRACT.md` applies and is unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: none beyond the separately gated media capability
- Fitness rule impact: production call-site opt-in, degradation, cleanup inventory, lineage, and pHash tests
- Boundary risk: high — rights, temporary-media retention, path safety, and deletion receipts must fail visibly

## Constraints

- No pickup until timestamped moments are available; capture must follow the recorded D1 posture.

## Acceptance Criteria

- [ ] The production capture call site requires the recorded opt-in/context-frame posture. Verify: `tests/knowledge_acquisition/test_source_frames.py::test_capture_call_site_requires_explicit_opt_in_and_retains_context_frame`.
- [ ] Successful capture retains one contextual frame; failure becomes timestamps-only. Verify: `tests/knowledge_acquisition/test_source_frames.py::test_context_frame_is_retained_when_capture_succeeds_and_failure_degrades_to_timestamps_only`.
- [ ] Cleanup leaves only approved frames and emits receipt. Verify: `tests/knowledge_acquisition/test_source_frames.py::test_temporary_video_deletion_leaves_only_approved_frames_with_receipt`.
- [ ] Retained frames carry exception metadata and pHash dedup. Verify: `tests/knowledge_acquisition/test_source_frames.py::test_retained_frames_have_exception_metadata_and_phash_deduplication`.

## Out of Scope

Always-on frames, video retention, and publishing.

## Suggested Validation

- Run the four named focused tests and byte-inventory fixture check.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/CAPTURE_OPT_IN_SOURCE_FRAMES.md`

## Applies learning (optional)

None.

## YSNV2-12 — task: evaluate source note quality

Labels: `type:task`, `prio:med`, `agent:blocked` (final child after YSNV2-01..11; YSNV2-10 also requires the external profile contract)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/EVALUATE_SOURCE_NOTE_QUALITY`. V2 needs a quality gate that measures evidence integrity and selection before broad upgrade/re-extraction; this is the final child and owns the end-to-end invariant matrix plus parent-closure handoff after YSNV2-01 through YSNV2-11. TCD hint: Sol/xhigh — the final gate validates persistence, provenance, replay, media, profile authority, and cross-task convergence.

## Scope

Implement the versioned gold-set/evaluation harness, operator annotation receipt boundary, end-to-end invariant matrix, and parent-closure handoff.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/EVALUATE_SOURCE_NOTE_QUALITY.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: OEF
- Secondary subsystem(s): HKA, SIP, GOV, PDM, EBF, RCA, MEM, CAO
- Write class: derived
- Authority impact: evaluation does not promote or edit notes
- Persistence impact: versioned evaluation fixtures/receipts
- Derived/rebuildable impact: metrics and evaluation reports remain rebuildable from versioned fixtures
- Human knowledge impact: no candidate or human-authored content mutation
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: none; evaluation and replay are no-egress
- New or changed contract: source-note gold set, quality metrics, and operator annotation receipt; `docs/contracts/ARTIFACT_CONTRACT.md` applies and is unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: creates the acceptance evidence needed before broad re-extraction
- Fitness rule impact: claim entailment, anchor validity, must-capture recall, consent receipt, no-mutation, and capability-wide invariant tests
- Boundary risk: high — a weak evaluation must not launder plausible output into accepted capability truth

## Constraints

- Evaluation and replay must remain no-egress and non-mutating.
- Do not run or merge this final validation child before YSNV2-01 through YSNV2-11 are delivered; YSNV2-10 remains blocked until its separate profile contract exists.

## Acceptance Criteria

- [ ] Unanchored/non-entailing claims fail quality gate. Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_gate_rejects_unanchored_or_non_entailing_claims`.
- [ ] Metrics include anchor validity and must-capture recall with fixture lineage. Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_metrics_record_anchor_validity_and_must_capture_recall`.
- [ ] Gold-set annotation scope and source/media consent are represented by an operator receipt rather than inferred. Verify: operator receipt on the live parent feature Issue validation ledger identified by `docs/YOUTUBE_SOURCE_NOTE_V2/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`.
- [ ] Evaluation stays no-egress and non-mutating. Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_quality_evaluation_is_no_egress_and_non_mutating`.
- [ ] A representative v2 fixture proves the capability-wide invariants and supplies the parent-closure handoff after all prerequisite children are delivered. Verify: `tests/knowledge_acquisition/test_source_note_quality.py::test_v2_end_to_end_invariant_matrix`.

## Out of Scope

Automatic subjective acceptance and background re-extraction.

## Suggested Validation

- Run the four named focused tests, including the final end-to-end invariant matrix.
- Record and inspect the operator receipt for gold-set annotation scope and any source/media consent at the parent validation hub.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/EVALUATE_SOURCE_NOTE_QUALITY.md`

## Applies learning (optional)

None.

## YSNV2-02 — bug: correct candidate truth surfaces

Labels: `type:bug`, `prio:high`, `agent:blocked` (YSNV2-01)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/FIX_CANDIDATE_TRUTH_SURFACES`. V1 renders hardcoded transcript availability, drops validated confidence, and silently truncates summary input. TCD hint: Terra/high — bounded truth-surface correction with focused tests and a current-state owner-doc writeback.

## Scope

Implement only the three truth-surface corrections in `FIX_CANDIDATE_TRUTH_SURFACES.md`.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/FIX_CANDIDATE_TRUTH_SURFACES.md :: Acceptance Criteria`
- `app/knowledge_acquisition/candidate_writeback.py :: assemble_candidate`
- `app/knowledge_acquisition/extractors/summary_extractor.py :: _MAX_PROMPT_SEGMENTS`

## SBS Impact

- Primary subsystem: HKA
- Secondary subsystem(s): SIP, OEF
- Write class: derived
- Authority impact: makes review-visible evidence truthfully bounded
- Persistence impact: none
- Derived/rebuildable impact: corrects candidate projection fields and summary coverage metadata
- Human knowledge impact: no change to first-write-wins or human-authored content
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: none
- New or changed contract: corrected candidate truth surfaces and source owner-doc writeback; `docs/contracts/ARTIFACT_CONTRACT.md` applies and is unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: removes the three confirmed V1 truth-surface defects
- Fitness rule impact: transcript-availability, confidence, coverage, and owner-doc tests
- Boundary risk: medium — human review depends on these fields being truthful

## Constraints

- Do not change title-bearing paths or persistence architecture.

## Acceptance Criteria

- [ ] Transcript availability reflects usable evidence. Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_candidate_transcript_availability_reflects_usable_evidence`.
- [ ] Rendered summary retains model confidence. Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_rendered_summary_preserves_model_confidence`.
- [ ] Summary coverage is complete or explicit. Verify: `tests/knowledge_acquisition/test_summary_extractor.py::test_summary_coverage_is_complete_or_explicitly_declared`.
- [ ] Current-state source documentation describes only the corrected truth surfaces without claiming v2 modules shipped. Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`.

## Out of Scope

New render modules or durable extraction persistence.

## Suggested Validation

- Run the three named focused tests.
- Review `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback` against the corrected implementation and confirm no broader v2 module claim was added.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/FIX_CANDIDATE_TRUTH_SURFACES.md`

## Applies learning (optional)

None.

## YSNV2-03 — task: compose review-required proposal note

Labels: `type:task`, `prio:high`, `agent:blocked` (YSNV2-02)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE`. The V1 renderer is fixed-shape and cannot compose new registered extraction results safely. TCD hint: Terra/high — bounded renderer work with authority-sensitive non-overwrite tests.

## Scope

Implement the authority-banded composable renderer defined by `COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md`.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md :: Acceptance Criteria`
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Human content is non-destructive`

## SBS Impact

- Primary subsystem: HKA
- Secondary subsystem(s): GOV, SIP, OEF
- Write class: derived
- Authority impact: preserves human-first proposal boundary
- Persistence impact: candidate materialization only
- Derived/rebuildable impact: generated proposal bands remain source-derived
- Human knowledge impact: owner-authored band is preserved byte-for-byte
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: none
- New or changed contract: composable authority-banded candidate renderer; `docs/contracts/ARTIFACT_CONTRACT.md` and `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` apply and are unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: replaces fixed rendering while retaining first-write-wins behavior
- Fitness rule impact: human-band preservation, wrapper, rhetoric, and terminality tests
- Boundary risk: high — generated output must never overwrite or masquerade as human content

## Constraints

- Generated content must never overwrite owner-authored content.

## Acceptance Criteria

- [ ] Human band survives rerun unchanged. Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_preserves_human_authored_band_on_rerun`.
- [ ] Proposals have one wrapper and omit empty modules. Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_wraps_proposals_and_omits_absent_modules`.
- [ ] Banned generated phrasing fails closed. Verify: `tests/knowledge_acquisition/test_note_renderer.py::test_renderer_rejects_banned_generated_phrasing`.
- [ ] Candidate becomes terminal only on materialization. Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_candidate_is_terminal_only_after_note_materialization`.

## Out of Scope

Claims, persistence, transcript bundle, and modules.

## Suggested Validation

- Run the four named focused tests.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md`

## Applies learning (optional)

None.

## YSNV2-04 — task: persist anchored transcript and extractions

Labels: `type:task`, `prio:high`, `agent:blocked` (YSNV2-03 delivered; D5 resolved; atomic governed HKA create-if-absent blocked by #4132)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS`. V1 extraction results are process-local; v2 needs durable evidence lineage without note overwrite. Pre-implementation reconciliation proved that D5 proposal companions require the canonical atomic governed KnowledgePort create-if-absent boundary tracked by #4132; #4111 remains blocked until that boundary is delivered. TCD hint: Sol/xhigh — persistence, provenance, replay, partial failure, and non-destructive authority semantics have high defect cost.

## Scope

Persist anchors/extractions and implement declared required/optional materialization semantics plus D5 versioned proposal companions.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS.md :: Acceptance Criteria`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Lineage and replay`

## SBS Impact

- Primary subsystem: HKA
- Secondary subsystem(s): PDM, SIP, GOV, EBF, OEF
- Write class: derived
- Authority impact: preserves first-write candidate authority
- Persistence impact: durable rebuildable artifacts
- Derived/rebuildable impact: transcript anchors and extraction outputs survive restart with lineage
- Human knowledge impact: re-extraction creates a versioned proposal companion and never overwrites human content
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: replay remains no-egress
- New or changed contract: durable extraction persistence, required/optional materialization policy, and versioned proposal companions; `docs/contracts/ARTIFACT_CONTRACT.md`, `docs/contracts/STORE_PORT.md`, and `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` apply
- Owner-doc impact: will-update-in-PR
- Transition debt impact: replaces process-local extraction state and all-or-nothing optional failure
- Fitness rule impact: restart, partial-failure, replay-source, and non-overwrite tests
- Boundary risk: critical — persistence, replay authority, partial success, and human-content protection must converge

## Constraints

- Each re-extraction must create a new versioned proposal companion; neither the candidate nor human-authored content may be overwritten.
- Reuse the canonical atomic governed KnowledgePort create-if-absent boundary once #4132 delivers it; do not duplicate it or use a check-then-write substitute in this slice.

## Acceptance Criteria

- [ ] Persisted output keeps anchors and lineage after restart. Verify: `tests/knowledge_acquisition/test_extraction_persistence.py::test_persisted_extraction_preserves_anchor_and_lineage_across_restart`.
- [ ] Optional failure materializes a visible degraded candidate only with required evidence. Verify: `tests/knowledge_acquisition/test_acquire.py::test_optional_extractor_dead_letter_materializes_degraded_candidate_without_erasing_evidence`.
- [ ] Required failure blocks candidate and preserves successful evidence. Verify: `tests/knowledge_acquisition/test_acquire.py::test_required_extractor_dead_letter_blocks_candidate_and_preserves_successes`.
- [ ] Re-extraction writes a versioned proposal companion and never overwrites the candidate. Verify: `tests/knowledge_acquisition/test_extraction_persistence.py::test_reextraction_writes_versioned_proposal_companion_without_overwriting_candidate`.
- [ ] Replay reads raw, not a transcript derivative. Verify: `tests/knowledge_acquisition/test_replay.py::test_replay_reads_raw_not_transcript_derivative`.

## Out of Scope

Bundle layout and synthesis/claims.

## Suggested Validation

- Run the five named focused tests and inspect persisted lineage fixtures.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS.md`

## Applies learning (optional)

None.

## YSNV2-05 — task: produce evidence-anchored synthesis and claims

Labels: `type:task`, `prio:high`, `agent:blocked` (YSNV2-04; D6 resolved)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS`. V2 replaces free-text summary with anchored, coverage-aware synthesis and claims. TCD hint: Sol/xhigh — evidence provenance and language semantics require high-confidence contract work.

## Scope

Implement only the extractor/rendering evidence rules and D6-resolved language policy.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: SIP
- Secondary subsystem(s): HKA, CAO, OEF
- Write class: derived
- Authority impact: prevents anchorless claims
- Persistence impact: rebuildable evidence outputs
- Derived/rebuildable impact: synthesis and claims remain reproducible source-bound proposals
- Human knowledge impact: no promotion or human-content mutation
- Memory impact: none
- Retrieval/context impact: none beyond cited source evidence
- Sync/deployment impact: none
- External boundary impact: model inference remains under existing LLM routing; replay has no source egress
- New or changed contract: anchored synthesis/claim schemas, confidence/coverage, and D6 language policy; `docs/contracts/ARTIFACT_CONTRACT.md` applies and is unchanged
- Owner-doc impact: will-update-in-PR
- Transition debt impact: replaces unanchored free-text summary output
- Fitness rule impact: anchor, wording separation, confidence/coverage, and D6 language tests
- Boundary risk: high — fluent but ungrounded or mistranslated output must fail closed

## Constraints

- System prose and `system_paraphrase` are English unless the source's original language is Swedish; direct quotations and `source_wording` retain original source language.

## Acceptance Criteria

- [ ] Anchorless claims/sentences do not render. Verify: `tests/knowledge_acquisition/test_evidence_synthesis.py::test_renderer_drops_anchorless_claims_and_synthesis_sentences`.
- [ ] Source wording and paraphrase remain distinct. Verify: `tests/knowledge_acquisition/test_claims_extractor.py::test_claim_wording_and_paraphrase_are_structurally_distinct`.
- [ ] Coverage and caption-quality confidence cap are visible. Verify: `tests/knowledge_acquisition/test_evidence_synthesis.py::test_synthesis_reports_coverage_and_caption_quality_confidence_cap`.
- [ ] System prose is English unless the source is Swedish-original; source wording and quotations retain original language. Verify: `tests/knowledge_acquisition/test_evidence_synthesis.py::test_synthesis_language_policy_uses_english_unless_source_is_swedish_and_preserves_quotes`.

## Out of Scope

Modules, overlay, ontology, and translation presented as source wording or quotation.

## Suggested Validation

- Run the four named focused tests.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md`

## Applies learning (optional)

None.

## YSNV2-06 — task: materialize portable YouTube source bundle

Labels: `type:task`, `prio:high`, `agent:blocked` (YSNV2-04; D2/D3 resolved; D5 companion seam required)

## Context

Parent validation hub: #4107. Implements `YOUTUBE_SOURCE_NOTE_V2/MATERIALIZE_PORTABLE_YOUTUBE_SOURCE_BUNDLE`. The attachment layout preserves flat note paths. D2 requires a vault transcript and note link; D3 requires a configurable YouTube attachment root with immutable content-identity/version children beneath the stable source folder; D5 requires an existing candidate upgrade to use a versioned proposal companion rather than rewrite the original. TCD hint: Sol/xhigh — configured paths, persistence, provenance, replay, and non-destructive upgrade semantics require high capability.

## Scope

Implement the approved flat-note/configured-attachment layout, immutable content-versioned bundle members, derived transcript, valid manifest mapping, and D5-based non-destructive upgrade route.

## Source Anchors

- `docs/YOUTUBE_SOURCE_NOTE_V2/MATERIALIZE_PORTABLE_YOUTUBE_SOURCE_BUNDLE.md :: Acceptance Criteria`
- `docs/architecture/metadata-bundle.md :: Required rules`

## SBS Impact

- Primary subsystem: HKA
- Secondary subsystem(s): WSP, PDM, SIP, EBF, OEF
- Write class: derived
- Authority impact: transcript remains non-authoritative derivative
- Persistence impact: stable source folder with immutable content-identity/version directories and rebuildable members
- Derived/rebuildable impact: each version's transcript and manifest are rebuildable projections; raw remains replay authority
- Human knowledge impact: flat candidate note and human-authored content remain non-destructive
- Memory impact: none
- Retrieval/context impact: note-to-transcript links improve inspection without changing authority
- Sync/deployment impact: none
- External boundary impact: none; this slice performs no source-media acquisition
- New or changed contract: validated `youtube_attachment_root`, identity-keyed attachment bundle, and resolved metadata manifest; `docs/contracts/ARTIFACT_CONTRACT.md`, `docs/contracts/ACTIVE_CONTEXT_SET.md`, and `docs/contracts/STORE_PORT.md` apply
- Owner-doc impact: will-update-in-PR
- Transition debt impact: adds portable vault artifacts without migrating existing note paths
- Fitness rule impact: path safety, source-root stability, immutable content-versioning, replay-source, linkage, schema, and migration tests
- Boundary risk: critical — path traversal, attachment relocation, cross-version retargeting, invalid metadata, and replay-source confusion must fail closed

## Constraints

- Preserve the flat note path; reject an attachment-root configuration that escapes the vault.
- Preserve immutable bundle members per content identity/version beneath the stable source-identity folder; never overwrite or retarget an older candidate's links.
- A bundle upgrade for an existing candidate must use a new versioned proposal companion and leave the original candidate byte-identical.

## Acceptance Criteria

- [ ] Configured attachment folder identity is stable and non-destructive. Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_configured_attachment_root_is_source_identity_keyed_and_note_is_non_destructive`.
- [ ] Bundle members are immutable and versioned by content identity beneath the stable source folder, so newer content cannot retarget older candidate evidence. Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_bundle_members_are_immutable_and_versioned_by_content_identity`.
- [ ] Attachment-root configuration is vault-relative and safe. Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_youtube_attachment_root_is_configurable_and_vault_relative`.
- [ ] Transcript is anchored derived reference, never replay input. Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_transcript_projection_is_anchored_derived_and_never_replay_input`.
- [ ] A new candidate or D5 versioned proposal companion links its derived transcript from synthesis/evidence and lineage without rewriting an existing original candidate. Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_note_links_derived_transcript_from_synthesis_and_lineage`.
- [ ] Manifest validates resolved bundle fields. Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_bundle_manifest_validates_resolved_metadata_bundle`.
- [ ] Existing flat V1 candidate notes remain byte-identical and bundle upgrades use versioned proposal companions. Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_existing_candidate_bundle_upgrade_uses_versioned_companion_without_note_mutation`.

## Out of Scope

Source-media acquisition and sibling upgrades.

## Suggested Validation

- Run the seven named focused tests and schema validation.

## Source Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/MATERIALIZE_PORTABLE_YOUTUBE_SOURCE_BUNDLE.md`

## Applies learning (optional)

None.
