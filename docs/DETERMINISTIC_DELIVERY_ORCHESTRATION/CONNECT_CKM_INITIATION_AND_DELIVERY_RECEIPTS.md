---
name: Connect CKM Initiation and Delivery Receipts
description: Let devUI use CKM evidence to draft delivery, then approve and follow it through a separate governed boundary inside one owner experience.
task_id: DDO-06
github_issue: 4169
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Architecture reconciliation for autonomous scheduled bug delivery
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-02, DDO-05]
depends_on: [DEFINE_CARRIER_NEUTRAL_DELIVERY_CONTRACTS.md, BIND_DELIVERY_EFFECTS_TO_BUILDEROPS_RECONCILIATION.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "Authenticated external boundary plus CKM authority separation and cross-system integration."
---

# Connect CKM Initiation and Delivery Receipts

## Purpose

Give the owner a capability-centric initiation and overview loop in the unified devUI experience
without making CKM, its static HTML, or the devUI shell a delivery control plane.

Reconciliation note (2026-08-06): the unified-devUI wording and owner-state correction in this task
spec are proposed target writeback. Live Issue #4169 must be reconciled to them before pickup; this
docs pass did not change the Issue or authorize implementation.

## What This Task Does

- Adds a CKM-side draft builder for carrier-neutral `DeliveryRequest.v1`.
- Invokes the pure compiler for `DeliveryPreview.v1` before approval, with scope, exclusions, waves,
  risk, policy, acceptance meaning, and estimated TCD.
- Adds a separate authenticated approval/handoff boundary outside the static Direction B HTML but
  inside the owner-perceived devUI flow.
- Approves the exact request and preview hashes into `DeliveryInitiation.v2`; authority drift
  requires a new preview and approval.
- Admits the approved initiation and typed lifecycle commands through BuilderOps' command/journal
  transaction; the action endpoint does not start a worker or execute an external effect. The DDO
  reducer chooses the next legal effect and BuilderOps outbox/effect adapters execute/reconcile it.
- Projects `DeliveryRunView.v1` through devUI's separately authenticated action region and the
  operator CLI/API, never through a polling or mutating static cockpit.
- Projects terminal `DeliveryReceipt.v2` evidence back into CKM with source links, freshness, and
  explicit derived/non-authoritative framing.
- Projects additive attempt-terminal evidence, observed outcome quality, failure mechanism,
  coordinator/worker model and reasoning, human intervention, retries, lead time, and limitations
  into an explainable TCD capability recommendation for later approved deliveries.
- Fires a reevaluation signal when terminal delivery evidence contradicts or advances a CKM
  capability claim, retains the last-good generated artifact on render failure, and provides manual
  regeneration fallback.

## Concretely

The generated cockpit may render inert capability evidence, gaps, and a request/preview reference.
It cannot fetch, approve, or execute. In the target owner experience, the Product Owner stays in
devUI while its separately authenticated action region approves the exact request+preview hashes or
requests typed pause, resume, cancel, or supersession. The same operations remain available through
the governed CLI/API. The receipt projection later displays accepted/partial/blocked/failed/
cancelled/superseded evidence with links, but cannot close an Issue or mark a capability
authoritative.

## Why This Matters

devUI becomes the coherent place to understand and initiate delivery. CKM supplies its
non-authoritative evidence lens, while overview, authorization, execution, and evidence keep
separate internal owners and trust boundaries.

## Acceptance Criteria

- [ ] CKM request generation uses only `DeliveryRequest.v1` and captured projection evidence.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_ckm_request_is_carrier_neutral_and_projection_bound`.
- [ ] CKM remains `single_operator_local` unless a new access-policy decision explicitly binds
  remote audience, read auth/scope, redaction, redistribution, and version refusal. A service or
  remote adapter fails closed without that decision.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_remote_ckm_read_refuses_without_access_policy`.
- [ ] Preview calls the pure compiler and performs no authority mutation.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_ckm_preview_precedes_approval_and_is_read_only`.
- [ ] Static Direction B HTML contains no approval, network, persistence, or execution path.
  - Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_delivery_draft_remains_inert`.
- [ ] The separate approval boundary authenticates the exact canonical request and preview hashes,
  checks freshness, and cannot expand compiler scope.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_approval_binds_exact_request_and_preview_hashes`.
- [ ] Request, preview, initiation, reducer handoff, and `DeliveryReceipt.v2` preserve one exact
  acceptance-profile reference and hash. Profile mismatch or freshness drift requires a new
  preview; no boundary infers or defaults the profile.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_acceptance_profile_reference_is_exact_across_handoff`.
- [ ] The operator surface derives **AI can continue**, **Needs your decision**, and **Blocked by
  evidence/system** only from explicit typed authority/gate state; missing, conflicting, or
  ambiguous technical authority fails closed to **Blocked by evidence/system**. **Needs your
  decision** requires one explicit canonical Human Exception authority category.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_owner_action_language_is_rule_derived_and_fail_closed`.
- [ ] Specs, code, tests, acceptance evidence, gaps, and freshness are exposed as distinct
  capability proof groups rather than inferred from one aggregate score.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_capability_delivery_proof_groups_remain_distinct`.
- [ ] devUI's separate authenticated action region displays `DeliveryRunView.v1` and sends only
  typed, version-bound lifecycle commands; the static cockpit has no active-run polling path and the
  owner does not have to switch products to keep context.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_active_run_and_controls_stay_outside_static_cockpit`.
- [ ] Receipt projection preserves exact source refs, freshness, limitations, and non-authority
  framing.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_delivery_receipt_projection_is_explainable_and_non_authoritative`.
- [ ] Capability routing consumes immutable terminal delivery evidence and can recommend
  Luna/low, Terra/medium, or a justified escalation with TCD reasons. CKM has no lease, selection,
  transition, retry, worker, merge, closure, or release mutation channel.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_capability_route_uses_terminal_delivery_evidence_without_lifecycle_authority`.
- [ ] `retriable_technical`, `blocked_technical`, `claim_collision`, and `needs_owner` render as
  distinct outcomes; technical ambiguity never renders as `needs_owner` without the canonical
  authority classification.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_technical_ambiguity_does_not_render_as_needs_owner`.
- [ ] Terminal evidence creates a CKM reevaluation signal; failed regeneration retains the last-good
  snapshot with failure evidence and manual regeneration remains available.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_terminal_evidence_refreshes_or_preserves_last_good`.
- [ ] Any interactive delivery console implementation passes the
  `yggdrasil-design-handoff` source/token gate before visual implementation begins.
  - Verify: delivery-console PR receipt names the exact handoff artifact and design-system source.

## How to Verify (Pre-Merge)

- Run all named CKM bridge and static-cockpit boundary tests.
- Run the full focused CKM query/overview/reevaluation suite.
- Run `ruff check app tests` and `mypy app`.
- Run the auth/external-API/state-machine convergence review before expensive validation.

## Out of Scope

- Turning Direction B HTML into an interactive control plane.
- Automatic prioritization from CKM scores.
- Selecting Issues, interpreting observed delivery success as lifecycle authority, or using
  LearningSignals/retrospectives as live coordination state.
- Product/Runtime UI or memory changes.
- Choosing the durable intent carrier in this slice unless the preceding semantic gate has resolved
  it.
- Requiring the static cockpit or devUI for CLI/API delivery availability.

## Related Docs

- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/DEVUI.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `.codex/skills/yggdrasil-design-handoff/SKILL.md`
- `docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md`
- `docs/audits/AUTONOMOUS_BUG_DELIVERY_ARCHITECTURE_2026-08-05.md`

## Related GitHub Issues

Live task: [#4169](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4169), blocked on DDO-02
[#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165) and DDO-05
[#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168).
