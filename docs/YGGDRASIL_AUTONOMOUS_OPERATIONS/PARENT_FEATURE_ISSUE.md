State: Filed parent feature contract. GitHub Issue #5329 is the authoritative blocked validation hub while child Issues #5330-#5340 are outstanding.

# Parent Feature Issue — Yggdrasil Autonomous Operations

## Context

Yggdrasil has domain-specific GUI and runtime capabilities but no complete shared operations layer
that gives humans and agents equivalent governed behavior. The accepted target-state contract and
this specification directory define the missing capability without claiming it is shipped.

## Scope

Deliver one operations contract and execution kernel; owner-native discovery, create/edit,
move/rename, classification/tag/order, archive/restore, and safe batch adapters; the corresponding
Companion human flow; and MCP v2 parity. Preserve MCP v1 as the ADR-0061 compatibility subset.

## Source Anchors

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Capability boundary`
- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Human flow`
- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Agent flow`
- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Conformance and acceptance`
- BuilderOps PromotionIntent `prom_20260904191308_31955ed2`

## SBS Impact

- Primary subsystem: Product/Runtime capability execution and Companion interaction surfaces
- Secondary subsystem(s): CES adapter boundary, Store/index/link projections, governed archival, multi-vault context
- Write class: authority-bearing coordination over owner-native writers
- Persistence impact: durable operation receipts and owner-native source effects
- Derived/rebuildable impact: explicit Store/index/link convergence and repair
- New or changed contract: `ygg.operation.v1` and MCP v2 parity profile
- Owner-doc impact: follow-up after parent acceptance
- Transition debt impact: reduces duplicated GUI/API/MCP behavior while retaining bounded MCP v1 compatibility
- Boundary risk: adapters or orchestration must not become a second source, vault, archive, or policy authority

## Constraints

- Fail closed on missing context, policy denial, stale versions, collisions, and ambiguous effects.
- Reuse existing StorePort, governed-write, archival, link, index, and multi-vault owners.
- Keep artifact identity distinct from mutable paths and names.
- No generic filesystem write tool and no per-file approval loop inside an already bounded delegation.
- Do not claim current support until terminal parent validation succeeds.

## Acceptance Criteria

- [ ] Every operation family resolves through one owner-native path with cross-surface outcome parity.
  - Verify: `tests/operations/test_cross_surface_conformance.py::test_all_operation_families_share_owner_native_semantics`
- [ ] Human and agent flows enforce the same bounded authority, receipt, conflict, and recovery rules.
  - Verify: `tests/operations/test_cross_surface_conformance.py::test_human_and_agent_flows_share_authority_and_recovery_semantics`
- [ ] Partial failure, restart, concurrent mutation, ambiguous response, and batch interruption remain truthful and recoverable.
  - Verify: `tests/operations/test_operations_failure_matrix.py::test_operations_failure_matrix_is_fail_closed_and_recoverable`
- [ ] MCP v1 remains compatible while MCP v2 proves the broader operation matrix.
  - Verify: `tests/mcp/test_mimer_v2_parity.py::test_v1_compatibility_and_v2_operation_parity`
- [ ] Accepted current-state owner docs and the capability directory are promoted only after the proof above.
  - Verify: doc writeback at `docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/README.md :: Owner-Doc Promotion`

## Out of Scope

- Replacing domain stores, WriteGuard, archival policy, index/link semantics, or vault selection.
- Production deployment or stable-channel promotion.
- Unbounded natural-language shell or filesystem access.

## Suggested Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations tests/mcp/test_mimer_v2_parity.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_autonomous_operations_boundaries.py`
- `ruff check app tests companion-ui/companion-app`
- Run the parent acceptance/UAT procedure defined by the terminal child and post its exact-SHA receipt here.

## Source Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/README.md`
- `docs/adr/ADR-0061-mimer-mcp-client-adapter.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`

## Applies learning (optional)

- BuilderOps PromotionIntent `prom_20260904191308_31955ed2` and accepted-transition receipt `receipt_20260904191321_abc17ad3`.

## Implementation Tasks

See the eleven ordered task files in `docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/README.md :: Implementation Tasks`.
The live child set is #5330-#5340; readiness and dependency state remain authoritative on GitHub.

## Verification Path

Each child resolves its own pre-merge `Verify:` ledger. Delivered children post exact Issue, PR,
head, validation, and owner-doc status receipts to this parent. The terminal child consumes those
receipts and reruns the integrated production-path matrix.

## Validation / Acceptance Path

Keep this parent open and `agent:blocked` while children remain. Accept only after the terminal
cross-surface suite, Companion UAT, MCP client proof, restart/failure matrix, and child ledger are
complete on current main. Then route parent closure and owner-doc promotion through the governed
closure workflow.
