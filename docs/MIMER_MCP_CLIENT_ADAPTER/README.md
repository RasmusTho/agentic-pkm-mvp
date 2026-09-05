State: delivery and acceptance record (parent #3366; children #3368–#3371). The 2026-08-21
[owner-decision receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3371#issuecomment-5375222455)
accepts ADR-0061's A2/B1/C1 bundle. #3368 and #3369 delivered the governed five-tool semantics and
isolated stdio transport; #3370 records the composed acceptance evidence. The accepted support level
is one hermetic JSON-RPC stdio-client journey against an isolated governed runtime, not general
third-party-client support or production activation.
Doc role: Capability specification and delivery index
Authority: Specifies the owner-accepted Mimer MCP client-adapter capability and delivery sequence.
ADR-0061 owns the A2/B1/C1 decision; `docs/contracts/MIMER_CLIENT_CONTRACT.md` owns the authority
envelope. The parent acceptance receipt owns the bounded supported-client evidence.

# Mimer MCP Client Adapter

## Capability Boundary

This capability admits MCP at the contract layer as an additional protocol-tier adapter over
Mimer's existing client contract, then exposes the already-shipped ask,
governed capture, retrieve/search, note-read, and health operations to MCP clients. It does not
create a second knowledge API or a new vault-write path.

The capability is Product/Runtime System work. Its primary SBS owner is **EBF** because it adds an
external protocol adapter. **GOV** owns preservation of the capture authority envelope and receipt;
**HIX/RCA** are consumed through existing ask/retrieval/read surfaces; **OEF** owns health and
acceptance evidence. No Builder System behavior is changed.

## Non-Goals

- No generic third-party MCP server receives direct vault-write access.
- No reuse of `app/mcp/vault_tools.py` as an external transport; it remains internal orchestrator
  plumbing.
- No separate receipt read-back endpoint or tool.
- No new semantic authority, hidden durable store, retrieval engine, or client-local source of
  truth.
- No Direction A connector configuration and no Direction C external-signal consumption.
- No claim of support for a client or runtime deployment that lacks its own acceptance evidence.
- No Streamable HTTP listener or per-device authentication in v1; B2 + C2 are separately gated
  follow-ons and cannot be enabled implicitly.

## Task List

1. [RATIFY_MCP_CLIENT_ADAPTER.md](RATIFY_MCP_CLIENT_ADAPTER.md) — apply the accepted A2/B1/C1
   decision and its linked owner receipt to ADR-0061 and the client contract.
2. [EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md](EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md) — implement
   the protocol-neutral MCP tool surface over existing Mimer client operations.
3. [PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md](PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md) — package
   the owner-selected wire transport, configuration, security posture, and service health.
4. [PROVE_CLIENT_COMPATIBILITY_AND_ACCEPT_MIMER_MCP.md](PROVE_CLIENT_COMPATIBILITY_AND_ACCEPT_MIMER_MCP.md)
   — prove the composed capability and reconcile acceptance truth.

## Flat Execution Order

1. `RATIFY_MCP_CLIENT_ADAPTER.md`
2. Only after the accepted ADR/client-contract writeback lands and downstream readiness is
   reconciled, run
   `EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md` and
   `PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md` in parallel when isolated worktrees and file scopes
   make that safe.
3. Run `PROVE_CLIENT_COMPATIBILITY_AND_ACCEPT_MIMER_MCP.md` after both implementation tasks land.

In shorthand: `MIMER-MCP-01 -> (MIMER-MCP-02 || MIMER-MCP-03) -> MIMER-MCP-04`.

## Cross-Task Invariants / Interaction Safety

- **MCP is an adapter, never an authority path.** The accepted tool layer delegates to the
  operations and authority envelope recorded in the accepted client contract. It does not call internal vault tooling,
  write files, or reinterpret successful and failed outcomes.
- **Capture is terminal only with the existing governed acknowledgement.** A successful MCP capture
  returns the capture response's PolicyDecision, DecisionToken, and AuthorityReceipt without
  fabrication or loss. If the API reports `not_acknowledged`, timeout, WriteGuard denial, or vault
  selection failure, the MCP call fails legibly and does not retry or fall back to filesystem
  mutation.
- **No hidden state bridges partial failure.** The adapter and transport are stateless apart from
  ephemeral connection state. If the transport dies after the runtime accepted a capture but before
  the client receives the response, the client sees an ambiguous outcome governed by the client
  contract's verify-before-retry rule; the server does not queue a replay.
- **Read truth remains honest.** Search/index misses retain the documented index-lag posture, ask
  failures never become answers from adapter memory, and note paths are not promoted into stable
  cross-host identifiers.
- **Transport cannot widen exposure.** v1 is stdio only and opens no network listener. Any
  Streamable HTTP/listener or per-device-auth work requires a separately accepted B2 + C2 follow-on;
  it cannot enter through packaging defaults.
- **Acceptance is composed.** MIMER-MCP-02 or MIMER-MCP-03 may be locally correct while the other is
  absent; neither changes owner-doc truth alone. MIMER-MCP-04 accepts the capability only after the
  semantic tool surface and hardened transport pass together.

## Capability-Level Acceptance Criteria

- [x] An owner-accepted decision and client-contract update admit MCP as an additional adapter
      without replacing HTTP or direct-filesystem semantics.
  Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Classification and transports`
  Verify: doc writeback at `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Owner decision receipt`
- [x] The server exposes exactly ask, governed capture, retrieve/search, note read, and health, with
      governed capture receipts and failure semantics preserved.
  Verify: `tests/mcp/test_mimer_server.py::test_server_exposes_exact_contracted_tool_set`
- [x] The packaged transport exposes stdio only, opens no network listener, and reports
      deterministic health.
  Verify: `tests/mcp/test_mimer_server_security.py::test_stdio_production_entrypoint_opens_no_network_listener`
- [x] A composed smoke proves protocol negotiation, read operations, one governed capture receipt,
      restart recovery, and no receipt-readback tool.
  Verify: `tests/mcp/test_mimer_server_smoke.py::test_composed_mimer_mcp_journey`
- [x] Acceptance evidence and owner-doc writeback are reconciled without claiming unverified client
      compatibility.
  Verify: runtime acceptance receipt: parent feature issue #3366
  Verify: doc writeback at `docs/STATUS.md :: Current Snapshot`

## Verification Path

- MIMER-MCP-01 preserves the proposal history, links the owner-decision receipt, moves ADR-0061 to
  Accepted, and writes exactly A2/B1/C1 into the client contract without claiming implementation.
- MIMER-MCP-02 uses in-process MCP tool tests with stubbed existing client operations plus the
  existing API contract suites.
- MIMER-MCP-03 uses stdio lifecycle, no-listener production-entrypoint, packaging, and dependency-consistency
  tests.
- MIMER-MCP-04 runs the composed protocol smoke and records durable compatibility evidence on the
  parent feature issue.

## Validation / Acceptance Path

The owner has ruled on topology, wire transport, and auth. #3368 and #3369 are delivered; #3370
records the composed isolated-runtime receipt on the parent validation hub. The receipt establishes
only the named hermetic JSON-RPC stdio client path. It does not promote an untested client or a
production deployment into supported status.

## Evidence Surface

- This directory owns stable capability intent and task-level verification commitments.
- Child issues own pickup state; their PRs own pre-merge verification receipts.
- The parent feature issue owns composed validation, client-compatibility evidence, and the
  final acceptance checklist.
- Current-state truth remains in `docs/ARCHITECTURE.md`, `docs/STATUS.md`, and the Mimer client
  contract until accepted implementation changes them.

## Relationship to GitHub Issues

- Parent validation hub: #3366 (open validation/acceptance record).
- MIMER-MCP-01: #3371 — applies the accepted A2/B1/C1 owner decision to ADR-0061 and the client
  contract; no server code belongs to this slice.
- MIMER-MCP-02: #3368 — delivered governed five-tool semantic adapter.
- MIMER-MCP-03: #3369 — delivered isolated v1 stdio sidecar with no listener or new auth.
- MIMER-MCP-04: #3370 — records the bounded composed acceptance evidence and owner-doc reconciliation.

[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) points to the live validation hub; GitHub owns
pickup/lifecycle truth and this directory owns the task contracts.

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after the composed smoke and parent ledger prove the exact
tool set, governed capture receipt, failure behavior, hardened exposure posture, restart behavior,
and at least one supported client path. The owner decision changes what implementation is allowed;
the decision alone does not claim a running server.
