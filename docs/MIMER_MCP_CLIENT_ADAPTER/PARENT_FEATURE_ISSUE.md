State: FILED as GitHub issue #3366 (`agent:blocked` validation hub). This file is the archived local
contract pointer; GitHub owns live backlog and validation state.

# type:feature: expose Mimer to MCP clients through the governed client contract

## Context

The app-connectivity audit ranks a Mimer MCP server as its highest-leverage build item, but current
authority explicitly says MCP is not a Mimer client transport. This feature first prepares an
owner-gated decision proposal that revisits ADR-0047 and ADR-0056. Implementation may begin only if
the owner explicitly accepts topology, wire transport, and authentication in a durable receipt.

## Scope

- Draft `docs/adr/ADR-0061-mimer-mcp-client-adapter.md` as a **Proposed** decision with alternatives
  and a recommendation; do not mark it Accepted or superseding without the owner's receipt.
- If accepted, implement the exact MCP tool surface without creating a second authority or
  vault-write path.
- If accepted, package the owner-selected wire transport with explicit configuration, trust enforcement, lifecycle,
  and health behavior.
- Prove composed client compatibility and retain acceptance evidence on this parent validation hub.

## Source Anchors

- `docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 Build list (ranked) — B1`
- `docs/ROADMAP.md :: External-connectivity (MCP) sequencing`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Classification and transports`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Callable HTTP surface (v1, shipped)`
- `docs/adr/ADR-0047-mcp-topology-federation-stance.md :: When to revisit`
- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md :: When to revisit`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md :: MCP integration boundary`

## SBS Impact

- Primary subsystem: EBF
- Secondary subsystem(s): GOV, HIX, RCA, OEF; CES stewardship for the ADR/contract task
- Write class: governance/docs/process for the owner-gated decision proposal; mechanical authority-mediated capture for runtime execution if accepted; reads otherwise
- Authority impact: MCP receives no semantic or independent write authority; governed capture retains WriteGuard, DecisionToken, AuthorityReceipt, and outbox semantics
- Persistence impact: no adapter-owned durable state; existing vault writes and receipts retain their current durability
- Derived/rebuildable impact: search/retrieval projections remain rebuildable and may lag
- Human knowledge impact: MCP capture enters the existing inbox posture and does not become canonical knowledge automatically
- Memory impact: none; adapter/session state must not become runtime or user memory
- Retrieval/context impact: exposes existing ask/retrieve/read behavior without changing ranking, grounding, or context assembly
- Sync/deployment impact: adds a managed client transport whose binding, restart, and exposure posture must be explicit
- External boundary impact: adds a constituent-owned protocol adapter and client-facing trust boundary
- New or changed contract: Proposed ADR-0061 first; accepted/superseding ADR and `docs/contracts/MIMER_CLIENT_CONTRACT.md` change only after an explicit owner receipt; tool-policy contract changes only if internal adapter semantics change
- Owner-doc impact: will-update-in-PR per child; final current-state promotion belongs to the acceptance child
- Transition debt impact: no SBS transition-debt effect expected; any newly discovered adapter/authority deviation becomes bounded debt
- Fitness rule impact: strengthens the manual external-adapter/authority review with production-call-site tests

## Constraints

- The parent is a validation hub, never an `agent:ready` implementation issue.
- #3371 remains `agent:needs-human` after the spec merges. Drafting the proposal does not authorize
  an agent to choose topology, wire transport, authentication, or mark ADR-0061 Accepted.
- #3368 and #3369 remain blocked until ADR-0061 is Accepted with a linked owner-decision receipt.
- Preserve the client contract's authority, index-lag, ambiguous-write, trace, and no-hidden-truth
  rules.
- Do not expose `app/mcp/vault_tools.py` or internal orchestrator descriptors as the client server.
- Do not add a receipt read-back endpoint/tool, generic vault writes, Direction A connector setup,
  or Direction C external-signal consumption.
- Keep credentials, concrete private host bindings, and operator-specific client configuration out
  of the public repository.

## Acceptance Criteria

- [ ] ADR-0061 presents explicit topology, wire-transport, and authentication alternatives plus a
      recommendation while remaining Proposed until the owner rules.
  - Verify: doc writeback at `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Options and recommendation`
- [ ] The owner decision is recorded durably before ADR-0061 becomes Accepted or supersedes existing
      authority, and the client contract changes only to the accepted choice.
  - Verify: owner-decision receipt on GitHub Issue #3371 linked from `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Owner decision receipt` plus doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Classification and transports`
- [ ] The exact contracted MCP tool surface delegates to existing client operations and preserves
      the governed capture response and error envelope.
  - Verify: `tests/mcp/test_mimer_server.py::test_server_exposes_exact_contracted_tool_set`
- [ ] The packaged transport enforces the owner-accepted trust posture on its production call path and
      survives a supervised restart without durable adapter state.
  - Verify: `tests/mcp/test_mimer_server_security.py::test_transport_rejects_untrusted_production_call` and `tests/mcp/test_mimer_server_transport.py::test_supervised_restart_restores_service_without_replay`
- [ ] The composed capability passes a real protocol journey and records supported-client evidence.
  - Verify: `tests/mcp/test_mimer_server_smoke.py::test_composed_mimer_mcp_journey` plus runtime acceptance receipt on this parent issue
- [ ] Every child has a delivery receipt and exactly one owner-doc writeback resolution before the
      capability is accepted.
  - Verify: parent verification ledger under `## Validation / Acceptance Path`

## Out of Scope

- Third-party connector installation or configuration.
- Mimer consuming external MCP signals.
- A general remote MCP registry or ecosystem mega-server.
- New Mimer API semantics, receipt lookup, direct vault mutation, or client-side durable queues.
- Claiming all MCP clients are supported without individual evidence.

## Suggested Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/mcp/test_mimer_server.py tests/mcp/test_mimer_server_transport.py tests/mcp/test_mimer_server_security.py tests/mcp/test_mimer_server_smoke.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_ask_contract.py tests/api/test_capture_inbox_api.py tests/api/test_search_canonical_substrate.py tests/api/test_artifact_note_read_api.py tests/api/test_health_contract_api.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_docs_index.py tests/architecture/test_requirements_consistency.py`
- Review the parent comments for child PR/merge/CI receipts, supported-client evidence, and one
  owner-doc writeback resolution per child.

## Source Docs

- `docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md`
- `docs/ROADMAP.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/adr/ADR-0047-mcp-topology-federation-stance.md`
- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/MIMER_MCP_CLIENT_ADAPTER/README.md`

## Applies learning (optional)


## Implementation Tasks

1. #3371 (`agent:needs-human`) — `docs/MIMER_MCP_CLIENT_ADAPTER/RATIFY_MCP_CLIENT_ADAPTER.md`
2. In parallel only after ADR-0061 is owner-accepted with a linked decision receipt:
   - #3368 — `docs/MIMER_MCP_CLIENT_ADAPTER/EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md`
   - #3369 — `docs/MIMER_MCP_CLIENT_ADAPTER/PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md`
3. #3370 — `docs/MIMER_MCP_CLIENT_ADAPTER/PROVE_CLIENT_COMPATIBILITY_AND_ACCEPT_MIMER_MCP.md`

## Verification Path

Each child issue executes the tests and doc targets named inline in its task specification. Child
PR receipts are posted here; the final child re-runs the composed protocol, security, and relevant
existing API suites against the integrated head.

## Validation / Acceptance Path

Keep this parent blocked while children are open. Spec merge does not unblock #3371; it stays
`agent:needs-human` until the owner-decision receipt exists, and #3368/#3369 stay blocked until the
accepted ADR lands. Record for every child: issue, PR, merge SHA, CI,
declared `Verify:` results, owner-doc resolution, and transition-debt outcome. After all four child
receipts exist, record the composed smoke, restart/failure evidence, supported-client matrix, and
any operator observation. Close only when all parent ACs are satisfied and current-state docs match
the accepted capability.
