---
status: Accepted
owner: Architecture / CES
date: 2026-10-29
---

# ADR-0069: Admit the bounded MCP v2 operation profile

## Owner decision receipt

The owner accepted this complete bounded profile on 2026-10-29 in the durable
[owner decision on Issue #5340](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5340#issuecomment-6489124965),
accepting the exact proposal recorded in
[the preceding owner comment](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5340#issuecomment-6488956317).
The accepted proposal's SHA-256 is
`39a8ab716cab2d562577b73c8216c7205483a7c9c45cbd88eb6d85fb28327f4c`.

This decision admits a bounded MCP v2 design profile. It does not grant authority to an MCP client,
establish runtime support or conformance, or authorize deployment.

## Context

[ADR-0061](ADR-0061-mimer-mcp-client-adapter.md) accepted a constituent-owned stdio sidecar with
exactly five MCP v1 operations. The delivered fence in
[Issue #5354 / PR #5398](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5354) requires a
superseding accepted ADR and matching owner-contract updates before broader external MCP execution.
This ADR supplies the bounded v2 design decision while retaining the v1 profile and its topology,
transport, and authentication posture.

## Decision

1. Partially supersede ADR-0061 **only for the external operation boundary of an explicitly
   versioned MCP v2 profile**. Preserve its A2 constituent-owned sidecar topology, B1 stdio-only
   transport with no network listener, and C1 inherited trust and authentication posture. MCP v1's
   exact `ask`, governed `capture`, `retrieve/search`, `note-read`, and `health` operations and their
   behavior remain unchanged.
2. Admit capability-derived v2 mapping of the owner-governed operation families: discovery, read,
   search, and related resources; capture and typed creation; body and allowed-metadata editing;
   identity-preserving move and rename; owner-governed classification, tags, and ordering;
   archive and restore; finite batch execution; and operation status, receipt, convergence, and
   recovery observation. Each advertised operation must be supported by a qualified production
   runtime. Uninstalled, dependency-blocked, or unsupported operations remain truthfully and
   typed-unavailable; listing an operation never makes it executable.
3. V2 delegates only to the shared authenticated production operations HTTP boundary owned by
   #5352. It must not construct domain owners, access vault files, use internal `vault_tools`,
   invent receipts, select arbitrary URLs, add policy or retries, or create another durable
   mutation path. Context/runtime initialization, reload, and settings controls retain their
   separately declared grants. Specialized Canvas, Panel, memory, briefing, TTS, and Ask actions
   gain no authority from this profile.
4. Every effect uses current host-resolved active context and principal, MVR-05C effect-capable
   delegation/DecisionToken authorization, bounded targets and cardinality, policy ceilings,
   expected versions, and native owner semantics. Client-supplied paths, service readers, keys,
   policy decisions, receipts, or raw delegation are not authority. Read-only MVR-05B selection
   cannot authorize a write. Preview and batch confirmation cannot expand their frozen target set.
5. Preserve exact typed refused, conflicted, unknown, pending, and partial outcomes; original native
   source and GOV receipts; and independent projection lag. Lost replies or restart require durable
   readback and reconciliation before retry. The adapter cannot convert an ambiguous effect into
   success or blindly repeat it. Cancellation cannot erase completed effects or receipts.
6. Implementation is eligible only after this ADR and the matching owner-contract updates are
   accepted and merged. Shipped-capability claims and #5329 closure additionally require current-SHA
   direct/HTTP/Companion/MCP conformance, negative-authority and failure/restart proof, a real external
   MCP client journey in an isolated runtime, Companion UAT, and complete child and owner-document
   receipts. ADR acceptance alone is not a runtime or deployment receipt.

## Consequences

An authorized external MCP client may request the admitted operations through the same governed
surface as Companion after those operations are qualified and implemented. The sidecar remains a
protocol adapter; domain and authority ownership stay with their existing owners. Capability-derived
availability and fail-closed recovery add verification obligations without adding a policy or
receipt store. The v1 compatibility surface remains available. Network transport changes,
per-device authentication, direct-filesystem fallback, and production rollout remain separate
decisions and effects.

## Alternatives

- Accept this bounded v2 profile and continue #5340 after its dependencies and technical proof. This
  preserves the existing transport and authority envelope while recording the requested parity
  direction.
- Keep MCP at its five-operation v1 boundary. #5352 and #5339 may still deliver, while broader v2
  execution and #5329 terminal acceptance remain gated.

## References

- [ADR-0061 — MCP v1 topology, transport, and authentication](ADR-0061-mimer-mcp-client-adapter.md)
- [Mimer Client Contract](../contracts/MIMER_CLIENT_CONTRACT.md)
- [Yggdrasil Autonomous Operations Contract](../contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md)
- [MCP v2 parity task](../YGGDRASIL_AUTONOMOUS_OPERATIONS/EXPOSE_AND_PROVE_MCP_V2_PARITY.md)
- [Owner decision receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5340#issuecomment-6489124965)
