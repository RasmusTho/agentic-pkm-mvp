---
name: Connect CKM Initiation and Delivery Receipts
description: Let CKM draft and display delivery initiation and receipts through a separate governed boundary.
task_id: DDO-06
github_issue: 4169
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Architecture reconciliation after DDO-03
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-02, DDO-05]
depends_on: [DEFINE_CARRIER_NEUTRAL_DELIVERY_CONTRACTS.md, BIND_DELIVERY_EFFECTS_TO_BUILDEROPS_RECONCILIATION.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "Authenticated external boundary plus CKM authority separation and cross-system integration."
---

# Connect CKM Initiation and Delivery Receipts

## Purpose

Give the owner a capability-centric initiation and overview loop without making CKM or its static
HTML a delivery control plane.

## What This Task Does

- Adds a CKM-side draft builder for carrier-neutral `DeliveryRequest.v1`.
- Invokes the pure compiler for `DeliveryPreview.v1` before approval, with scope, exclusions, waves,
  risk, policy, acceptance meaning, and estimated TCD.
- Adds a separate authenticated approval/handoff boundary outside the static Direction B HTML.
- Approves the exact request and preview hashes into `DeliveryInitiation.v2`; authority drift
  requires a new preview and approval.
- Projects `DeliveryRunView.v1` through the separate authenticated console/CLI, never through a
  polling or mutating static cockpit.
- Projects terminal `DeliveryReceipt.v2` evidence back into CKM with source links, freshness, and
  explicit derived/non-authoritative framing.
- Fires a reevaluation signal when terminal delivery evidence contradicts or advances a CKM
  capability claim, retains the last-good generated artifact on render failure, and provides manual
  regeneration fallback.

## Concretely

The generated cockpit may render inert capability evidence, gaps, and a request/preview reference.
It cannot fetch, approve, or execute. The Product Owner uses a separate governed console/command/API
to approve the exact request+preview hashes and request typed pause, resume, cancel, or supersession.
The receipt projection later displays accepted/partial/blocked/failed/cancelled/superseded evidence
with links, but cannot close an Issue or mark a capability authoritative.

## Why This Matters

CKM becomes the place to understand and initiate delivery while the reasons to change for overview,
authorization, execution, and evidence remain separate.

## Acceptance Criteria

- [ ] CKM request generation uses only `DeliveryRequest.v1` and captured projection evidence.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_ckm_request_is_carrier_neutral_and_projection_bound`.
- [ ] Preview calls the pure compiler and performs no authority mutation.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_ckm_preview_precedes_approval_and_is_read_only`.
- [ ] Static Direction B HTML contains no approval, network, persistence, or execution path.
  - Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_delivery_draft_remains_inert`.
- [ ] The separate approval boundary authenticates the exact canonical request and preview hashes,
  checks freshness, and cannot expand compiler scope.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_approval_binds_exact_request_and_preview_hashes`.
- [ ] The operator surface derives **AI can continue**, **Needs your decision**, and **Blocked by
  evidence/system** only from explicit typed authority/gate state; missing, conflicting, or
  ambiguous authority fails closed to **Needs your decision**.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_owner_action_language_is_rule_derived_and_fail_closed`.
- [ ] Specs, code, tests, acceptance evidence, gaps, and freshness are exposed as distinct
  capability proof groups rather than inferred from one aggregate score.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_capability_delivery_proof_groups_remain_distinct`.
- [ ] The separate authenticated surface displays `DeliveryRunView.v1` and sends only typed,
  version-bound lifecycle commands; the static cockpit has no active-run polling path.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_active_run_and_controls_stay_outside_static_cockpit`.
- [ ] Receipt projection preserves exact source refs, freshness, limitations, and non-authority
  framing.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py::test_delivery_receipt_projection_is_explainable_and_non_authoritative`.
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
- Product/Runtime UI or memory changes.
- Choosing the durable intent carrier in this slice unless the preceding semantic gate has resolved
  it.
- Requiring the static cockpit or interactive console for CLI/API delivery availability.

## Related Docs

- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `.codex/skills/yggdrasil-design-handoff/SKILL.md`
- `docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md`

## Related GitHub Issues

Live task: [#4169](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4169), blocked on DDO-02
[#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165) and DDO-05
[#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168).
