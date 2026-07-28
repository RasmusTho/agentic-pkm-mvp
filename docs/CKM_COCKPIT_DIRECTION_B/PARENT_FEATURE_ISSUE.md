State: ACCEPTED/CLOSED parent validation contract. [#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080) independently accepted Direction B and closed on 2026-07-28 after children #4081–#4086 and completion #4222 delivered. This parent was never a pickup Issue.

# CKM Cockpit Direction B — Parent Validation Hub

## Context

CKM Direction A was delivered by #3689 / PR #3692, CKM Measurement & Access by parent #3775,
and owner Gate A by #3972. The owner authorized a small Direction B cockpit design and feature
breakdown, not automation or a control plane. Parent
[#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080) was the validation hub for the
contract at `docs/CKM_COCKPIT_DIRECTION_B/README.md`; it was never a pickup issue. CKM Evidence
Profile Phase 1 delivered before implementation, preventing the cockpit from preserving the retired
scalar/maturity-band picture.

## Scope

Validate six bounded child slices that enhance the existing generated CKM Development Overview with
portfolio trust framing, descriptive hazards, exact O1b pairwise comparison/refusal, optional local
filters, inert proposal drafts, and deterministic print behavior. Hold child receipts, visual/PDF
evidence, cross-task acceptance, owner-doc promotion, and closure truth.

## Source Anchors

- `docs/CKM_COCKPIT_DIRECTION_B/README.md :: Capability boundary`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md :: Capability acceptance ledger`
- `docs/CKM_EVIDENCE_PROFILE/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: O1b delivered comparison semantics`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md :: Decision`

## SBS Impact

- Primary subsystem: Builder System / CES boundary — BuilderOps CKM generated projection
- Secondary subsystem(s): none; Product/Runtime is read-only and unaffected
- Write class: target-state specification followed by derived local HTML output only
- Authority impact: none; cockpit remains non-authoritative and cannot act
- Persistence impact: none in the cockpit; reads existing CKM and explicit metric-retention stores
- Derived/rebuildable impact: generated HTML is fully rebuildable from bound inputs
- Human knowledge impact: none; proposal text is inert BuilderOps draft material
- Memory impact: none; no runtime/user memory
- Retrieval/context impact: none
- Sync/deployment impact: none; local file generation only
- External boundary impact: no network, GitHub mutation, hosting, or multi-user surface
- New or changed contract: opt-in `ckm overview --cockpit`, render-context, filter-script, proposal, and print contracts
- Owner-doc impact: target-state link now; promotion only after parent acceptance
- Transition debt impact: avoids a parallel dashboard; later owner-doc promotion removes temporary Direction A/cockpit split
- Fitness rule impact: preserves CKM projection-only and adds deterministic/no-action cockpit checks
- Boundary risk: persuasive generated interpretation must not become authority, diagnosis, or action

## Constraints

- This parent is never claimed or labeled `agent:ready`.
- During delivery, each child remained `agent:blocked` until its live dependencies closed and its
  exact body passed strict readiness validation.
- CKM Evidence Profile Phase 1 was delivered before CKM-DB-01 began.
- Extend the existing overview renderer/CLI; do not create a parallel dashboard or service.
- No automatic ranking, gating, prioritization, agent scoring, prediction, causal claims, or mutation.
- No clipboard, GitHub prefill, fetch, network, storage, cookies, or hosted/multi-user behavior.
- Comparison uses exactly the newest two active retained records, presents that selected pair to O1b
  as `(older, newer)` so signed deltas are newer minus older, and never searches older rows after a
  refusal.
- Default Direction A output stays script-free; cockpit output may have exactly one filtering-only
  script.

## Acceptance Criteria

- [x] The Evidence Profile prerequisite is delivered with its terminal real-store receipt.
  Verify: closed Evidence Profile parent/children plus `docs/CKM_EVIDENCE_PROFILE/README.md :: Verification and acceptance path`
- [x] All six Direction B children are delivered in dependency order with current-SHA CI, local review, and parent handoff receipts.
  Verify: child delivery receipt ledger on this parent
- [x] Capability-level invariants and every refusal/partial-failure state are proven on the production CLI/render path.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_cli_renders_comparison_and_refusal_states`; `tests/builderops/ckm/test_overview_html.py::test_cockpit_answers_fixed_owner_questions_without_authority`
- [x] The final generated HTML and PDF contain full trust, hazard, comparison/refusal, map/detail, gaps, proposal, and provenance content without network or hidden filtered omissions.
  Verify: deterministic HTML digest and manual PDF receipt posted on this parent by CKM-DB-06
- [x] Every child has a PR-specific owner-doc result and transition-debt result.
  Verify: child closure receipts and post-merge owner-doc comments
- [x] Owner docs are promoted only once the full capability is accepted; this reconciliation records
  the terminal supported truth.
  Verify: final docs PR updates `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md` and `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`, linked from this parent

## Implementation Tasks

1. CKM-DB-01 [#4081](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4081) —
   `docs/CKM_COCKPIT_DIRECTION_B/ESTABLISH_TRUST_AND_PORTFOLIO_FRAMING.md`; delivered.
2. CKM-DB-02 [#4082](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4082) —
   `docs/CKM_COCKPIT_DIRECTION_B/SURFACE_INTERPRETATION_HAZARDS_HONESTLY.md`; delivered.
3. CKM-DB-03 [#4083](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4083) —
   `docs/CKM_COCKPIT_DIRECTION_B/RENDER_COMPATIBLE_OBSERVATION_COMPARISONS.md`; delivered.
4. CKM-DB-04 [#4084](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4084) —
   `docs/CKM_COCKPIT_DIRECTION_B/FILTER_CAPABILITY_MAP_HONESTLY.md`; delivered.
5. CKM-DB-05 [#4085](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4085) —
   `docs/CKM_COCKPIT_DIRECTION_B/GENERATE_GOVERNED_PROPOSAL_DRAFTS.md`; delivered.
6. CKM-DB-06 [#4086](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4086) —
   `docs/CKM_COCKPIT_DIRECTION_B/SUPPORT_DETERMINISTIC_PRINT_OUTPUT.md`; delivered.

## Verification Path

Each child executed every named `Verify:` target, the focused CKM suite, `ruff check app tests`,
`mypy app`, current-head CI, and independent local review. Each merged child posted exact PR/SHA,
checks, visual or refusal evidence, and its parent-handoff result on #4080.

## Validation / Acceptance Path

The terminal child regenerated the artifact from a stable fixture, recorded its digest, validated
JS-off behavior, and attached the manually inspected PDF. Completion issue
[#4222](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4222) supplied the protected
production-CLI comparison/refusal evidence. Independent
[#4080 acceptance](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080#issuecomment-5102696743)
then verified live GitHub state, every exact receipt, Evidence Profile delivery, and owner-doc
posture before the
[terminal closure](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080#issuecomment-5102745391).

## Out of Scope

- Direct implementation from this parent
- CKM Evidence Profile implementation
- New scoring, history, cadence, retention, linker, or observation semantics
- Hosted UI, Companion UI, Product/Runtime, release, or promotion work

## Suggested Validation

- Run every child `Suggested Validation` command and its exact `Verify:` targets.
- Verify every closed child has no `agent:*` label and its merge is reachable from current
  `origin/main`.
- Verify the parent receipt ledger, deterministic HTML digest, manual PDF receipt, transition-debt
  outcomes, and PR-specific post-merge owner-doc receipts.
- Re-run `python3 scripts/validate_source_anchors.py < parent-body-file.md` against the live parent
  body before terminal closure.

## Source Docs

- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CKM_EVIDENCE_PROFILE/README.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Applies learning (optional)

The owner Gate A receipt on #3972 and the Claude Design Direction B handoff are design provenance.
The live-reconciliation refinement that sequences Direction B behind CKM Evidence Profile Phase 1
prevents duplicate scalar-retirement work and a contradictory target-state contract.
