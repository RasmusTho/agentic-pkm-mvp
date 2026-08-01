State: Active parent validation-hub contract. GitHub Issue #4131 exists and remains open and unaccepted; children #4308–#4313 are filed, #4308–#4312 carry terminal receipts, and terminal child #4313 posts its receipt and the conditional-acceptance ledger on merge. The remaining work is then the independent parent acceptance audit, which a child slice may not perform or close.
Doc role: Parent feature Issue specification
Authority: Stable acceptance shape for live parent #4131; GitHub owns current labels, comments, and closure state.
Owner: Builder System / CKM
Temporal class: active specification

# CKM Design-Agent Integration Parent Validation Hub

## Context

Live parent [#4131](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4131) governs acceptance of
the capability specified in this directory. It is a validation hub, not an implementation pickup.

## Scope

Validate the complete child ledger for the provider-neutral design-run contracts, exact adapter
registry, governed lifecycle, CLI control surface, read-only CKM projection, and end-to-end
acceptance. Preserve the CKM/Builder System/BuilderOps authority split.

## Source Anchors

- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Capability boundary`
- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Capability acceptance`

## SBS Impact

- Primary subsystem: Builder System / CKM
- Secondary subsystem(s): BuilderOps model-access and design-run execution boundary
- Write class: Builder operational records and derived read-only CKM projection
- Persistence impact: durable design-run artifacts/receipts; no Product or human-knowledge writes
- Derived/rebuildable impact: cockpit projection remains rebuildable
- New or changed contract: design-run request/admission/approval/receipt/handoff family
- Owner-doc impact: conditional post-acceptance update only
- Transition debt impact: no parallel dashboard; reuses Direction B and the shared model-access substrate
- Boundary risk: CKM projection must never become provider execution or decision authority

## Constraints

- CDH-02 and every execution slice remain blocked until #4286 closes with its repo-verifiable Phase
  1 acceptance ledger. Withdrawn provider-enabled inquiry and bridge-retirement receipts, metered
  credentials, and active provider-backed inference are not prerequisites.
- Generated Direction B HTML remains inert, local, deterministic, JS-off complete, and printable.
- No provider ranking, automatic selection/fallback, GitHub mutation, Product/Runtime write, release,
  or promotion.
- Governed results become repo truth only through Issue, PR, PromotionIntent, or owner-doc flow.

## Acceptance Criteria

- [ ] Every child has a terminal PR/SHA/Verify receipt and owner-doc/transition-debt result.
  Verify: `runtime receipt: ckm_design_hub.child_ledger.v1`
- [ ] Production acceptance proves exact provider success/refusal semantics and no authority
  leakage or fallback.
  Verify: `tests/builderops/test_design_hub_acceptance.py::test_design_hub_production_matrix_is_fail_closed`
- [ ] The final read-only cockpit has a passing Yggdrasil Design Handoff receipt and preserves
  Direction B deterministic, print, JS-off, and non-execution guarantees.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_design_hub_projection_preserves_direction_b_authority`
- [ ] The exact live Yggdrasil design-system ID and matching live/repo token hashes are accepted.
  Verify: `runtime receipt: ckm_design_hub.yggdrasil_handoff.v1`
- [ ] Conditional independent parent acceptance authorizes a docs-only promotion PR; a fresh audit
  after merge verifies the exact CKM and Builder System owner-doc diff before closure.
  Verify: `runtime receipt: ckm_design_hub.terminal_acceptance.v1`

## Implementation Tasks

See the ordered list in `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Implementation tasks and order`.

## Verification Path

Each child owns its named tests and PR-level validation. Child delivery receipts are appended to
#4131. The final task reruns the production-path matrix plus the focused CKM, design-run, and model
inquiry regression suites.

## Validation / Acceptance Path

After all children merge, an independent parent audit verifies the child ledger, exact merged-main
tests, Yggdrasil receipt, deterministic/print artifact evidence, D11/D12 posture, and absence of
unowned follow-up work. A passing audit first records a conditional acceptance that authorizes one
docs-only promotion PR updating the exact CKM and Builder System owner docs. After that PR merges, a
fresh independent audit verifies the diff and only then authorizes parent closure and supported
language.

## Out of Scope

- Direct implementation from the parent.
- Product/Runtime, release, promotion, or deterministic-delivery-orchestration work.
- Treating a design result as accepted repo or product truth.

## Suggested Validation

- `python -m pytest -q tests/builderops/test_design_hub_acceptance.py`
- `python -m pytest -q tests/builderops/ckm/test_design_cockpit.py`
- `python -m pytest -q tests/builderops tests/builderops/ckm`
- `python3 scripts/docs_guard.py`
- Validate the Yggdrasil receipt, deterministic HTML digest, and full-content print artifact on #4131.

## Source Docs

- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/MODEL_ACCESS_SUBSTRATE/README.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/adr/ADR-0064-model-access-substrate.md`

## Applies learning (optional)

Reuses the delivered Direction B renderer and shared model-access substrate to avoid parallel
dashboard and provider-transport machinery.
