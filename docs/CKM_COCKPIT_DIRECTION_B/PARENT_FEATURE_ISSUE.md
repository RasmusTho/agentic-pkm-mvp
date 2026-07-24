State: Pre-filing parent feature issue contract. GitHub creation is forbidden until this specification is merged and stable on `origin/main`. After filing, GitHub becomes the live backlog/validation surface and this file must be reconciled immediately.

# CKM Cockpit Direction B — Parent Validation Hub

## Context

CKM Direction A was delivered by #3689 / PR #3692, CKM Measurement & Access by parent #3775,
and owner Gate A by #3972. The owner authorized a small Direction B cockpit design and feature
breakdown, not automation or a control plane. This parent is the validation hub for the target-state
contract at `docs/CKM_COCKPIT_DIRECTION_B/README.md`; it is never a pickup issue.

Implementation is dependency-blocked until CKM Evidence Profile Phase 1 is delivered. That merged
spec retires the current scalar/maturity-band render and must precede Direction B so the cockpit
cannot preserve a known false picture or duplicate its repair.

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
- All children remain `agent:blocked` until their live dependencies are closed and their exact bodies
  pass strict readiness validation.
- CKM Evidence Profile Phase 1 must be delivered before CKM-DB-01 begins.
- Extend the existing overview renderer/CLI; do not create a parallel dashboard or service.
- No automatic ranking, gating, prioritization, agent scoring, prediction, causal claims, or mutation.
- No clipboard, GitHub prefill, fetch, network, storage, cookies, or hosted/multi-user behavior.
- Comparison uses exactly the newest two active retained records and never searches older rows after
  a refusal.
- Default Direction A output stays script-free; cockpit output may have exactly one filtering-only
  script.

## Acceptance Criteria

- [ ] The Evidence Profile prerequisite is delivered with its terminal real-store receipt.
  Verify: closed Evidence Profile parent/children plus `docs/CKM_EVIDENCE_PROFILE/README.md :: Verification and acceptance path`
- [ ] All six Direction B children are delivered in dependency order with current-SHA CI, local review, and parent handoff receipts.
  Verify: child delivery receipt ledger on this parent
- [ ] Capability-level invariants and every refusal/partial-failure state are proven on the production CLI/render path.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_cli_renders_comparison_and_refusal_states`; `tests/builderops/ckm/test_overview_html.py::test_cockpit_answers_fixed_owner_questions_without_authority`
- [ ] The final generated HTML and PDF contain full trust, hazard, comparison/refusal, map/detail, gaps, proposal, and provenance content without network or hidden filtered omissions.
  Verify: deterministic HTML digest and manual PDF receipt posted on this parent by CKM-DB-06
- [ ] Every child has a PR-specific owner-doc result and transition-debt result.
  Verify: child closure receipts and post-merge owner-doc comments
- [ ] Owner docs are promoted only once the full capability is accepted.
  Verify: final docs PR updates `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md` and `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`, linked from this parent

## Implementation Tasks

1. `docs/CKM_COCKPIT_DIRECTION_B/ESTABLISH_TRUST_AND_PORTFOLIO_FRAMING.md`
2. `docs/CKM_COCKPIT_DIRECTION_B/SURFACE_INTERPRETATION_HAZARDS_HONESTLY.md`
3. `docs/CKM_COCKPIT_DIRECTION_B/RENDER_COMPATIBLE_OBSERVATION_COMPARISONS.md`
4. `docs/CKM_COCKPIT_DIRECTION_B/FILTER_CAPABILITY_MAP_HONESTLY.md`
5. `docs/CKM_COCKPIT_DIRECTION_B/GENERATE_GOVERNED_PROPOSAL_DRAFTS.md`
6. `docs/CKM_COCKPIT_DIRECTION_B/SUPPORT_DETERMINISTIC_PRINT_OUTPUT.md`

## Verification Path

Each child executes every named `Verify:` target, the focused CKM suite, `ruff check app tests`,
`mypy app`, current-head CI, and independent local review. Each merged child posts exact PR/SHA,
checks, visual or refusal evidence, and its parent-handoff result here.

## Validation / Acceptance Path

Keep this parent blocked while children are outstanding. The terminal child regenerates the artifact
from a stable fixture, records its digest, validates JS-off behavior, and attaches a manually
inspected PDF. Independent parent closure verifies live GitHub state, every exact receipt, Evidence
Profile delivery, and owner-doc posture before closing the capability.

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
- Re-run `python3 scripts/validate_source_anchors.py --body-file <parent-body-file>` against the live
  parent body before terminal closure.

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
