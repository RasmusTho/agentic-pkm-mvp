State: Initial agent/tool execution security addendum for security foundation wave (#1590).
Doc role: Security addendum
Authority: Security interpretation of current tool/MCP/A2A execution controls. Subordinate to current-state contracts for shipped behavior.
Owner: Security architecture / agent runtime
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-04
Last verified against: docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md, docs/contracts/A2A_CONTRACT_AND_TRACE.md, docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md, docs/SECURITY_TRUST_BOUNDARIES.md, docs/SECURITY_REVIEW_METHOD.md

# Agent / Tool Execution Security Addendum

## Purpose

This addendum records security review inputs for agent/tool execution. It is not a runtime
implementation plan and does not change tool, MCP, A2A, timeout, policy, or audit behavior.

Use this document with:

- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md`
- `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md`
- `docs/SECURITY_TRUST_BOUNDARIES.md`
- `docs/SECURITY_REVIEW_METHOD.md`

## Current-state versus future-hardening map

| Area | Current-state claim | Future hardening need |
| --- | --- | --- |
| Descriptor trust | Local YAML registry and legacy in-code descriptors define known tools. Descriptor fields include stable id, protocol, server, description, allowed args, and optional mock result. | Remote descriptor trust, descriptor versioning, signature/provenance, and admission review are not fully governed. |
| Remote MCP admission | Remote multiplex is behind `mcp_remote_multiplex_enable`; failures fall back to local registry; unsupported tools are filtered. | Enabling remote multiplex is currently the admission gate. A stronger remote-provider allowlist/admission contract is needed before broader exposure. |
| Allowlists and flags | Real vault append requires `allowed_mcp_tools` plus MCP enable flag. BuilderOps real execution requires `mcp_builderops_enable` plus allowlist. | Future real tools should inherit explicit per-tool flags, allowlists, and policy checks rather than using descriptor presence as authorization. |
| Argument validation | Executor validates top-level declared argument types and required fields. It does not coerce values or validate deep schemas/min/max constraints. | Rich JSON Schema validation and path/domain-specific constraints may be needed for higher-risk tools. |
| Policy enforcement | `POLICY_ENFORCE=1` requires an `agent_id` and calls `assert_tool_allowed`; current policy is minimal for known tools. | Stronger per-agent, per-tool, per-surface authorization is future work. |
| Timeout and call budget | Per-tool `tool_timeout_seconds`, optional `max_tool_calls`, and optional plan timeout budgets are supported by executor/orchestrator surfaces. | Default timeout/call-budget policy should be explicit for high-risk real tools. |
| Mock versus real execution | Most tools return deterministic mock payloads; real execution is limited and flag/allowlist controlled. | Reviews must prevent test/mock assumptions from being mistaken for production real-tool behavior. |
| Egress and secrets | Tools and providers may produce outbound or sensitive data flows only when configured; secrets are governed by `docs/SECURITY.md` and `docs/PRIVACY.md`. | Remote tools/providers need explicit egress, secrets, and prompt/data minimization review before non-local exposure. |
| Trace/audit | Tool calls emit started/finished outbox events with trace ids where available; A2A emits request/response/error audit events; timeout errors are observable. | Tool validation failures/timeouts may rely on orchestrator-level error events rather than tool-specific error receipts. |

## Descriptor trust model

Tool descriptors are capability declarations, not authority grants.

Current controls:

- descriptor ids are stable names in local registry or legacy in-code descriptors;
- `allowed_args` constrains accepted top-level argument names and primitive types;
- `required` fields are enforced separately;
- unsupported remote-discovered tools are filtered before execution;
- real execution requires relevant flags and allowlists for currently implemented real tool families.

Security interpretation:

- A descriptor can describe what a tool can accept, but it does not prove the tool is safe, current,
  complete, or authorized for a specific agent.
- Descriptor presence must not bypass policy, flags, allowlists, WriteGuard, or governance.
- Remote descriptors are less trusted than local repo descriptors until an explicit admission
  contract governs source identity, version, and allowed capabilities.

## Remote MCP admission model

Current remote MCP posture is bounded and experimental:

- `mcp_remote_multiplex_enable` must be truthy before remote multiplex is used.
- If no remote provider is available or the provider fails, execution falls back to the local
  registry with deterministic route reason codes.
- Remote descriptor listing is best-effort and failures are swallowed.
- The current contract records no separate admission allowlist for remote providers.

Security review rule:

Remote MCP changes require at least Level 2 review. A remote provider that can execute real tools,
return descriptors, or influence tool selection should normally receive Level 3 review before
supported LAN/Tailscale/public use.

## Allowlist and flag model

Flags and allowlists are necessary but not sufficient:

| Control | Security role | Non-bypass rule |
| --- | --- | --- |
| `mcp_vault_enable` / `mcp.enable` | Enables real vault append path for eligible tool. | Does not bypass allowed-tool checks or write governance. |
| `mcp_builderops_enable` | Enables real BuilderOps tool execution. | Does not promote BuilderOps records into repo/product truth. |
| `allowed_mcp_tools` | Names tools allowed for real execution. | Does not validate arguments beyond descriptor rules or authorize unrelated tools. |
| `POLICY_ENFORCE` | Turns on agent id and tool-allowed check. | Minimal current policy must not be treated as full authorization. |
| `may_write` flags in context/bundles | Communicate bundle authority posture. | Never bypass WriteGuard, policy, or admission. |

## Argument validation expectations

Current accepted baseline:

- reject unexpected or wrong-type top-level args;
- reject missing required args;
- do not coerce inputs;
- preserve deterministic error type `invalid_tool_args`;
- keep nested schema, numeric bounds, path containment, and domain-specific validation in the
  owning tool/handler when needed.

Security review trigger:

A new real tool should document where domain-specific validation lives, especially for paths,
queries, provider URLs, command-like arguments, vault references, external identifiers, and data
that may cross into prompts, logs, GitHub, BuilderOps, or vault writes.

## Timeout and call-budget expectations

Current controls:

- `tool_timeout_seconds` can bound an individual tool call;
- `max_tool_calls` can bound plan-level call count;
- `plan_timeout_seconds` can bound total plan runtime;
- timeout errors are observable via `tool_timeout` and `plan_timeout` classifications;
- A2A has no central timeout scheduler or production delivery SLA.

Security interpretation:

- Timeouts are availability and containment controls, not correctness or authorization controls.
- For local personal use, lack of default timeout on a low-risk mock path is usually acceptable.
- For remote, real, or expensive tools, the review should require an explicit timeout/call-budget
  posture before treating the surface as supported.

## Mock/real execution distinction

Mock results are deterministic support surfaces. They must not be used as evidence that a real tool
is safe, authorized, or fully validated.

Review questions:

- Does the tool run in mock mode, real mode, or both?
- Which flags and allowlists move it into real mode?
- What side effects exist in real mode?
- Is the PR/test evidence exercising the same mode that production/staging will use?
- If a failure is mocked as success, is that acceptable for the route/review level?

## Egress and secrets expectations

Tools and providers must preserve these rules:

- no secrets in descriptors, prompts, logs, traces, BuilderOps records, or GitHub issues;
- no raw vault text in external payloads unless the provider path is explicitly configured and the
  privacy posture accepts that data flow;
- no remote tool/provider execution should become supported public exposure without an auth,
  egress, and secrets review;
- tool output that contains URLs, paths, prompt text, retrieved note text, or provider diagnostics
  should be treated as less trusted until validated by the owning consumer.

## Trace and audit expectations

Current execution emits operational traces, not always human-legible receipts.

| Surface | Current accountability support | Security note |
| --- | --- | --- |
| Tool calls | `mcp.tool.call.started` and `mcp.tool.call.finished` events with plan/step/tool/trace data where available. | Started/finished traces support reconstruction; they are not automatically user-facing receipts. |
| Tool failures | Raised `StepExecutionError` handled by orchestrator-level error events. | Consider whether high-risk tools need explicit failure/audit events. |
| A2A messages | `agent.request.created`, `agent.response.created`, `agent.error.created`. | In-process schema and audit support only; no production transport claim. |
| Timeout failures | `tool_timeout` and `plan_timeout` error types. | Availability/accountability support, not authority. |
| BuilderOps tools | BuilderOps records and receipts through the controlled boundary. | Operational-plane accountability only; no product truth without repo gate. |

## Tool-output manipulation failure mode

Tool output is an untrusted or less-trusted input unless the owning consumer validates it.

Failure pattern:

1. A tool returns plausible but false, stale, malformed, or adversarial output.
2. A downstream prompt, UI, memory, context bundle, or governance path treats the output as
   authoritative.
3. The result influences a proposal, memory candidate, receipt, or durable write without visible
   validation/provenance.

Controls to preserve:

- provenance remains visible;
- context bundles carry authority flags and exclusions;
- memory promotion requires review;
- governance-bearing writes route through policy/WriteGuard/idempotency/receipt;
- BuilderOps material cannot launder itself into repo/product truth.

## Review checklist for new or changed tools

- Identify descriptor source: local YAML, legacy in-code, remote MCP, or generated.
- State whether execution is mock, real, or both.
- Name flags and allowlists required for real execution.
- Name argument validation layer and limits.
- State timeout and call-budget posture.
- State egress and secrets posture.
- State trace/audit/receipt expectation.
- Classify tool-output manipulation risk using `docs/SECURITY_REVIEW_METHOD.md`.
- Confirm that no flag, descriptor, `may_write`, or model output bypasses governance.
