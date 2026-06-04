State: Initial security review method. Docs-only; does not mandate runtime implementation.
Doc role: Review method / template
Authority: Canonical method for proportionate security reviews over Yggdrasil trust boundaries, data flows, and agentic failure modes.
Owner: Security architecture / governance
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-04
Last verified against: docs/SECURITY_ARCHITECTURE.md, docs/SECURITY_TRUST_BOUNDARIES.md, docs/SECURITY_DATA_FLOWS.md, docs/development/DEV_WORKFLOW.md, docs/development/GITHUB_GOVERNANCE_SETUP.md

# Security Review Method

## Purpose

This document defines how to perform proportionate security review for Yggdrasil. It is a review
method, not a claim that every current path has already undergone formal STRIDE or ATT&CK-style
analysis.

Use this with:

- `docs/SECURITY_ARCHITECTURE.md`
- `docs/SECURITY_TRUST_BOUNDARIES.md`
- `docs/SECURITY_DATA_FLOWS.md`

## When to use security review

Run a security review when a change introduces or materially changes:

- new API routes,
- new write paths,
- new tool or MCP capabilities,
- new external providers,
- Companion UI exposure, auth, rendering, editor, or mutation behavior,
- memory, context-bundle, promotion, or receipt behavior,
- BuilderOps/repo authority boundary behavior,
- sync, replica, device, environment, LAN, Tailscale, or public exposure behavior,
- secrets, tokens, provider keys, or CI/GitHub credentials,
- durable state transitions or generated artifacts that could be mistaken for authority.

## Proportionate review levels

| Level | Name | Use when | Expected output |
| --- | --- | --- | --- |
| 0 | No security impact | Docs wording, typo, purely internal refactor with no boundary/data-flow change | State "Level 0" and why. |
| 1 | Checklist only | Minor docs/route/config change inside existing boundary | Boundary touched, existing controls, no new gaps or one small follow-up. |
| 2 | STRIDE-lite | New route, write path, provider, tool, UI state, memory/context influence, or receipt path | STRIDE worksheet for touched boundary plus findings if any. |
| 3 | Full STRIDE + attack path | New exposed service, mutation-capable browser flow, remote tool/provider, sync/replica authority, or durable authority transition | Full worksheet, attack path, mitigations, residual risk. |
| 4 | Study/adversarial review | Architecture learning, red-team-style prompt/tool/memory/governance exercise | Study-only scenarios clearly separated from current operational risk. |

## Likelihood and impact tiers

Use plain tiers instead of inflated severity:

- Likelihood: `realistic current`, `plausible future`, `study-only`
- Impact: `low`, `medium`, `high`, `architecture-invariant`

`architecture-invariant` means the property should be preserved even if current likelihood is low.

## STRIDE worksheet template

```markdown
### STRIDE-Lite Worksheet

- Review target:
- Review level:
- Boundary from `SECURITY_TRUST_BOUNDARIES.md`:
- Data flows from `SECURITY_DATA_FLOWS.md`:
- Current exposure assumption:
- Existing controls:

| STRIDE category | Question | Finding / not applicable | Notes |
| --- | --- | --- | --- |
| Spoofing | Can a caller, actor, tool, provider, or artifact pretend to be another? | | |
| Tampering | Can data, state, receipts, projections, or tool outputs be changed improperly? | | |
| Repudiation | Can meaningful action happen without accountable receipt/audit linkage? | | |
| Information disclosure | Can note text, secrets, prompts, traces, or provider payloads leak? | | |
| Denial of service | Can malformed input, provider calls, rendering, or tool execution exhaust resources? | | |
| Elevation of privilege | Can a lower-authority surface gain write, memory, receipt, repo, or product authority? | | |

- Residual risk:
- Follow-up candidate:
```

## Attack-path worksheet template

```markdown
### Attack-Path Worksheet

- Scenario:
- Likelihood tier: realistic current / plausible future / study-only
- Impact tier: low / medium / high / architecture-invariant
- Starting point:
- Target authority or asset:
- Preconditions:

| Step | Boundary crossed | Data/control used | Existing control | Gap |
| --- | --- | --- | --- | --- |
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

- Would the path require non-default exposure?
- Would the path require compromised local machine, trusted LAN, or external provider?
- Mitigation candidates:
- Residual uncertainty:
```

## ATT&CK-inspired mapping guidance

Use ATT&CK as adapted vocabulary, not strict enterprise SOC coverage. The goal is shared language
for agentic and local-first failure modes, not a claim that Yggdrasil operates as an enterprise
network.

Suggested adapted mappings:

| Adapted concern | ATT&CK-like idea | Yggdrasil interpretation |
| --- | --- | --- |
| Credential access | Steal or expose secrets | Provider keys, API keys, GitHub auth, local tokens. |
| Initial access | Reach a surface | Localhost, LAN, Tailscale, browser, API route, tool provider. |
| Execution | Run a capability | Tool/MCP call, watcher auto-exec, Panel/Canvas write path. |
| Persistence | Survive into future runs | Poisoned note, memory candidate, BuilderOps record, generated projection. |
| Defense evasion | Hide evidence | Missing or ambiguous receipt, trace-only accountability, stale projection. |
| Collection | Gather data | Retrieval, context bundle, vault browser, provider prompt assembly. |
| Exfiltration | Send data outward | LLM/provider payloads, logs, GitHub/BuilderOps publication. |
| Impact | Change durable state | Vault mutation, memory promotion, repo doc change, future automation rule. |

## Agentic failure-mode taxonomy

Use this taxonomy during Level 2 through Level 4 reviews:

| Failure mode | Description | Typical boundary |
| --- | --- | --- |
| Prompt injection | A note, source, or user input attempts to override system/tool rules | Vault/provider/tool |
| Context poisoning | Retrieved or bundled context is false, stale, malicious, or out of scope | Retrieval/context bundle |
| Memory poisoning | Candidate or inferred memory becomes hidden authority | Memory/governance |
| Authority escalation | Proposal, UI state, bundle flag, memory, or mirror gains authority without governance | Governance/write |
| Tool-output manipulation | Tool result is treated as trustworthy without validation/provenance | Tool/MCP |
| Governance bypass | Durable state changes outside policy, WriteGuard, idempotency, or receipt path | Write boundary |
| Receipt/audit ambiguity | Action cannot be reconstructed by human-legible accountability | Receipt/trace/audit |
| UI trust confusion | Browser projection appears more authoritative than server/runtime truth | Companion UI |
| BuilderOps/product-truth laundering | Operational build-plane material becomes repo/product truth without target gate | BuilderOps/repo |

## Finding format

Use this format for findings. Do not create issues automatically from findings unless explicitly
asked.

```markdown
### <Title>

- Scenario:
- Affected boundary:
- Review level:
- Likelihood tier: realistic current / plausible future / study-only
- Impact tier: low / medium / high / architecture-invariant
- Current controls:
- Gap:
- Mitigation candidate:
- Classification: current / future / study-only
```

## Review completion criteria

A review is complete when it states:

- the review level,
- the boundaries and data flows considered,
- whether the scenario is current, future, or study-only,
- existing controls,
- residual gaps,
- and whether any mitigation is required before the change proceeds.
