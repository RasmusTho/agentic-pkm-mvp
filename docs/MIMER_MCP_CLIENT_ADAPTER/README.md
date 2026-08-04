State: FILED specification directory (parent #3366; children #3368–#3371). MIMER-MCP-01/#3371
remains `agent:needs-human` after this specification merges because MCP topology, wire transport,
and authentication are owner-deferred. MIMER-MCP-02/#3368 and MIMER-MCP-03/#3369 remain blocked
until an explicit owner-decision receipt accepts the proposed ADR. No implementation or current MCP
transport support is claimed.
Doc role: Capability specification and future delivery index
Authority: Specifies the proposed Mimer MCP client-adapter capability. Until the owner accepts the
decision proposal and an accepted ADR lands, `docs/contracts/MIMER_CLIENT_CONTRACT.md`, ADR-0047,
and ADR-0056 remain authoritative and MCP is not an admitted Mimer client transport.

# Mimer MCP Client Adapter

## Capability Boundary

This capability proposes admitting MCP as an additional protocol-tier adapter over Mimer's existing
client contract, then—only if the owner accepts the proposal—exposes the already-shipped ask,
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
- No claim that MCP is a current transport before an explicit owner decision accepts the proposed
  ADR and the accepted decision lands.

## Task List

1. [RATIFY_MCP_CLIENT_ADAPTER.md](RATIFY_MCP_CLIENT_ADAPTER.md) — draft the decision proposal and
   wait for the owner's explicit topology/transport/auth ruling before admission.
2. [EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md](EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md) — implement
   the protocol-neutral MCP tool surface over existing Mimer client operations.
3. [PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md](PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md) — package
   the owner-selected wire transport, configuration, security posture, and service health.
4. [PROVE_CLIENT_COMPATIBILITY_AND_ACCEPT_MIMER_MCP.md](PROVE_CLIENT_COMPATIBILITY_AND_ACCEPT_MIMER_MCP.md)
   — prove the composed capability and reconcile acceptance truth.

## Flat Execution Order

1. `RATIFY_MCP_CLIENT_ADAPTER.md`
2. Only after the owner-decision receipt accepts the proposed ADR, run
   `EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md` and
   `PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md` in parallel when isolated worktrees and file scopes
   make that safe.
3. Run `PROVE_CLIENT_COMPATIBILITY_AND_ACCEPT_MIMER_MCP.md` after both implementation tasks land.

In shorthand: `MIMER-MCP-01 -> (MIMER-MCP-02 || MIMER-MCP-03) -> MIMER-MCP-04`.

## Cross-Task Invariants / Interaction Safety

- **MCP is an adapter, never an authority path.** If accepted, the tool layer delegates to the
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
- **Transport cannot widen exposure.** Packaging applies the owner-accepted binding/auth posture before a
  network listener is considered usable. A healthy protocol handler on an unapproved interface is
  a failed deployment, not partial success.
- **Acceptance is composed.** MIMER-MCP-02 or MIMER-MCP-03 may be locally correct while the other is
  absent; neither changes owner-doc truth alone. MIMER-MCP-04 accepts the capability only after the
  semantic tool surface and hardened transport pass together.

## Capability-Level Acceptance Criteria

- [ ] An owner-accepted decision and client-contract update admit MCP as an additional adapter
      without replacing HTTP or direct-filesystem semantics.
  Verify: doc writeback at `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Classification and transports`
  and owner-decision receipt on GitHub Issue #3371 linked from
  `docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Owner decision receipt`
- [ ] The server exposes exactly ask, governed capture, retrieve/search, note read, and health, with
      governed capture receipts and failure semantics preserved.
  Verify: `tests/mcp/test_mimer_server.py::test_server_exposes_exact_contracted_tool_set`
- [ ] The packaged transport rejects exposure or callers outside the owner-accepted trust posture and
      reports deterministic health.
  Verify: `tests/mcp/test_mimer_server_security.py::test_transport_rejects_untrusted_production_call`
- [ ] A composed smoke proves protocol negotiation, read operations, one governed capture receipt,
      restart recovery, and no receipt-readback tool.
  Verify: `tests/mcp/test_mimer_server_smoke.py::test_composed_mimer_mcp_journey`
- [ ] Acceptance evidence and owner-doc writeback are reconciled without claiming unverified client
      compatibility.
  Verify: runtime acceptance receipt on the parent feature issue plus doc writeback at `docs/STATUS.md :: Current Snapshot`

## Verification Path

- MIMER-MCP-01 drafts `ADR-0061` in `Proposed` state with alternatives and a recommendation, then
  waits for the owner-decision receipt before any Accepted/superseding language or contract change.
- MIMER-MCP-02 uses in-process MCP tool tests with stubbed existing client operations plus the
  existing API contract suites.
- MIMER-MCP-03 uses transport lifecycle, security-call-site, packaging, and dependency-consistency
  tests.
- MIMER-MCP-04 runs the composed protocol smoke and records durable compatibility evidence on the
  parent feature issue.

## Validation / Acceptance Path

The specification is filed, but #3371 remains `agent:needs-human` until the owner explicitly rules
on topology, wire transport, and auth. The parent remains a blocked validation hub while children
are open. #3368/#3369 cannot become Ready merely because the spec merges; they require an accepted
ADR plus its owner-decision receipt. Each merged child posts its PR and verification receipt to the
parent. Only MIMER-MCP-04 may recommend current-state owner-doc promotion, and only after the
composed runtime receipt exists.

## Evidence Surface

- This directory owns stable capability intent and task-level verification commitments.
- Child issues own pickup state; their PRs own pre-merge verification receipts.
- The parent feature issue owns composed validation, client-compatibility evidence, and the
  final acceptance checklist.
- Current-state truth remains in `docs/ARCHITECTURE.md`, `docs/STATUS.md`, and the Mimer client
  contract until accepted implementation changes them.

## Relationship to GitHub Issues

- Parent validation hub: #3366 (`agent:blocked`).
- MIMER-MCP-01: #3371 — `agent:needs-human`; drafts ADR-0061 as Proposed and waits for the explicit
  owner-decision receipt. Spec merge does not make it autonomous.
- MIMER-MCP-02: #3368 — blocked on an owner-accepted ADR-0061 receipt, not only issue/PR completion.
- MIMER-MCP-03: #3369 — blocked on the same owner-accepted ADR-0061 receipt; may run parallel with
  #3368 only after that gate is satisfied.
- MIMER-MCP-04: #3370 — blocked on #3368 and #3369; final acceptance/closure handoff.

[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) points to the live validation hub; GitHub owns
pickup/lifecycle truth and this directory owns the task contracts.

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after the composed smoke and parent ledger prove the exact
tool set, governed capture receipt, failure behavior, hardened exposure posture, restart behavior,
and at least one supported client path. The owner decision changes what implementation is allowed;
the decision alone does not claim a running server.
