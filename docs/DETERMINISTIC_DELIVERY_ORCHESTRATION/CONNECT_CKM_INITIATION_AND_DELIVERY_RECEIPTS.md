---
name: Connect CKM Initiation and Delivery Receipts
description: Let CKM draft and display delivery initiation and receipts through a separate governed boundary.
task_id: DDO-06
github_issue: 4169
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: CKM bridge
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-02, DDO-05]
depends_on: [DEFINE_CARRIER_NEUTRAL_DELIVERY_CONTRACTS.md, BIND_DELIVERY_EFFECTS_TO_BUILDEROPS_RECONCILIATION.md]
can_parallelize_with: []
---

# Connect CKM Initiation and Delivery Receipts

## Purpose

Give the owner a capability-centric initiation and overview loop without making CKM or its static
HTML a delivery control plane.

## What This Task Does

- Adds a CKM-side draft builder for carrier-neutral `DeliveryInitiation.v1`.
- Invokes the pure compiler for a read-only preview with scope, exclusions, waves, risk, policy, and
  estimated TCD.
- Adds a separate authenticated approval/handoff boundary outside the static Direction B HTML.
- Projects terminal `DeliveryReceipt.v1` evidence back into CKM with source links, freshness, and
  explicit derived/non-authoritative framing.
- Fires a reevaluation signal when delivery evidence contradicts a CKM capability claim.

## Concretely

The generated cockpit may render an inert draft and preview. It cannot fetch, approve, or execute.
An operator uses the separate governed command/API boundary to approve the exact payload hash. The
receipt projection later displays delivered/partial/failed/superseded evidence with links, but
cannot close an Issue or mark a capability authoritative.

## Why This Matters

CKM becomes the place to understand and initiate delivery while the reasons to change for overview,
authorization, execution, and evidence remain separate.

## Acceptance Criteria

- [ ] CKM draft generation uses only the carrier-neutral contract and captured projection evidence.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_ckm_draft_is_carrier_neutral_and_projection_bound`.
- [ ] Preview calls the pure compiler and performs no authority mutation.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_ckm_preview_is_read_only`.
- [ ] Static Direction B HTML contains no approval, network, persistence, or execution path.
  - Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_delivery_draft_remains_inert`.
- [ ] The separate approval boundary authenticates the exact canonical payload and cannot expand
  compiler scope.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_approval_binds_exact_initiation_hash`.
- [ ] Receipt projection preserves exact source refs, freshness, limitations, and non-authority
  framing.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_delivery_receipt_projection_is_explainable_and_non_authoritative`.
- [ ] Contradictory delivery evidence creates a CKM reevaluation signal rather than silently
  rewriting capability truth.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_delivery_contradiction_routes_to_reevaluation`.

## How to Verify (Pre-Merge)

- Run the six named CKM bridge tests.
- Run the full focused CKM query/overview/reevaluation suite.
- Run `ruff check app tests` and `mypy app`.
- Run the auth/external-API/state-machine convergence review before expensive validation.

## Out of Scope

- Turning Direction B HTML into an interactive control plane.
- Automatic prioritization from CKM scores.
- Product/Runtime UI or memory changes.
- Choosing the durable intent carrier in this slice unless the preceding semantic gate has resolved it.

## Related Docs

- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Related GitHub Issues

Live task: [#4169](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4169), blocked on DDO-02
[#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165) and DDO-05
[#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168).
