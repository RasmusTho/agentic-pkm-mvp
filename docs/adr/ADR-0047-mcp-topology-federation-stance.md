State: Deferred (owner decision, 2026-07-04; RESEARCH-08 decision D4). The owner deferred ratifying the four-rule MCP topology stance until a concrete remote/sibling MCP server is actually on the table (Option 2). The stance as designed in `docs/architecture/ecosystem-federation.md` remains the leading candidate; this ADR records the deferral and the residual risk, and files no follow-up issues. Constituent model per ADR-0044 (Yggdrasil = the whole; Mimer + Heimdall constituents): "Yggdrasil" as the current MCP-consumer system reads as Mimer post-rename (deferred); the deferral and residual risk are unaffected.
Doc role: Decision record (ADR)
Authority: Authoritative for the *decision* of how MCP server/registry ownership and remote-attachment admission are governed at the ecosystem-federation seam. MCP's protocol-tier status is unchanged (ADR-0036; doctrine §2.7); this ADR does not promote MCP to architecture. The design content is owned by `docs/architecture/ecosystem-federation.md` § Dual-role + MCP → *MCP topology stance*; this ADR ratifies its adoption, it does not restate the design.
Owner: Architecture / CES stewardship
Temporal class: Durable decision (supersede via a new ADR only if the stance is reversed, or when a real remote/sibling MCP server first attaches and the follow-up fixes are evaluated against real traffic).
Source of truth: This ADR plus `docs/architecture/ecosystem-federation.md` § Dual-role + MCP → *MCP topology stance* and § Owner decisions (D4); ADR-0036; `docs/foundation/00-yggdrasil-doctrine.md` §2.7.

# ADR-0047: Defer the four-rule MCP topology stance for the acknowledged SoS constituents

**Date:** 2026-07-04
**Status:** Deferred (owner decision, 2026-07-04)

---

## Context

Part of RESEARCH-08 (`docs/architecture/ecosystem-federation.md`, #2852), the companion-thread
artifact resolving the 2026-07-04 Fable research week's ecosystem-federation design. The audit and
its descendant artifact found that MCP server/registry ownership has no stated stance, and that the
existing remote-MCP seam has three concrete gaps: a silent exception swallow, no admission
allowlist, and an untyped settings flag. Siblings will need a decided topology before the first one
attaches; without a stance, the next MCP-related change re-litigates ownership from scratch.

Current reality, stated honestly (all anchors verified against code): Yggdrasil today is an MCP
**tool consumer only**. `RemoteMCPProvider` is a `Protocol` with **zero production
implementations** — test fakes only
(`app/orchestrator/mcp_tool_provider.py:14-27`). No MCP server exists anywhere in `app/`. The
silent-fallback gap is real today, not hypothetical: `MCPToolProvider.list_descriptors` merges
remote descriptors into the local registry only when `mcp_remote_multiplex_enable` is truthy and a
remote provider is injected, and on any remote exception it swallows the failure and falls back to
the local registry unremarked (`except Exception: pass`,
`app/orchestrator/mcp_tool_provider.py:41-43`). The contract confirms there is **no separate
admission allowlist** for remote providers — "Enabling remote multiplex is currently the admission
gate" (`docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md:31,62-68`) — and the Integration
Fabric Contract's phrase "remote MCP servers behind the flagged multiplex seam"
(`docs/INTEGRATION_FABRIC_CONTRACT.md:44`) is target-state language describing a seam that exists
as a flag, not as an attached reality (divergence DV-3). The multiplex flag itself is an untyped
`tool_settings` dict key with no settings-schema declaration (divergence DV-4).

This is **not** a boundary reshape. Per the binding SBS-reconciliation classification
(`docs/architecture/ecosystem-federation.md` § SBS reconciliation, rows 7–9): rule 1 below
**conforms** to the already-settled MCP-is-protocol-tier posture (ADR-0036; doctrine §2.7); rules
2–4 **extend** it — design rules for a surface (a Yggdrasil-operated MCP server, a real remote
sibling attachment) that does not exist yet. Per the boundary audit §13, even Extend-class items
affecting the ecosystem-federation seam are owner-gated and routed through an ADR before
enactment; this ADR is that route for decision D4. Enactment travels the normal implementation
lane (filed follow-up issues), not a CES boundary-reshape route.

## Decision

### 1. The four-rule MCP topology stance is NOT ratified now

The owner deferred D4. The four-rule stance below is not adopted by this ADR — it remains the
leading design candidate, preserved here so the record is self-contained, but it carries no
decision force until a concrete remote/sibling MCP server exists and the stance is ratified against
that real attachment (Option 2 in the artifact).

### 2. The deferred candidate stance (not yet adopted)

**Rule 1 — MCP stays protocol-tier (Conform).** Federation does not promote MCP to architecture.
Capability contracts are the boundary; MCP is one adapter among several, exactly as ADR-0036
already decided ("Standards are adapters, not the ontology") and as doctrine §2.7 commits
(`docs/foundation/00-yggdrasil-doctrine.md:65-67`). This rule restates existing decisions; it adds
no new constraint.

**Rule 2 — Constituent-owned servers (Extend).** Each constituent owns and operates the MCP
server(s) exposing *its own* capability contracts. Yggdrasil's future MCP server, if and when
built, would expose Yggdrasil's own capability surfaces (knowledge, memory, reasoning,
knowledge-graph, document); each sibling constituent exposes its own domain capabilities behind its
own server. No shared ecosystem mega-server; no third-party-hosted registry of the operator's
surfaces. Server ownership follows capability ownership, exactly as adapter ownership follows the
port today.

**Rule 3 — Registry split along the seam (Extend).** The registry *schema and admission policy* —
descriptor format, tool policy, allowlist semantics — are public Yggdrasil contracts; the existing
`docs/settings/tools/registry.yaml` + descriptor pattern generalizes to this role. The registry
*contents* for remote/sibling servers — endpoints, credentials, host bindings — are private-side
material always (INV-EF1 categories (ii)/(iii), per the companion D3 decision). The public tree
states what may attach and on what terms; the private side states what actually attaches here.

**Rule 4 — Close the silent-fallback gap before any real remote attachment (Extend).** Before any
real remote/sibling MCP server attaches, three fixes would apply, each to be routed as an
implementation follow-up if and when the stance is ratified (the audit already flagged this debt;
`docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md:322-327`):

  a. an explicit per-server **admission allowlist** — flag-as-gate is not admission;
  b. **legible degradation** — remote failure surfaces as a health/receipt signal, preserving the
     existing deterministic route-reason codes (`remote_disabled`, `remote_unavailable`,
     `remote_provider_error`, `remote_descriptor_list_error`, `ok`) but never silently merging or
     silently falling back;
  c. the multiplex flag becomes a **typed settings field** in `app/settings/models.py` rather than
     an untyped `tool_settings` dict key (this also resolves divergence DV-4).

### 3. Owner's rationale for deferring

- No concrete remote/sibling MCP server exists today: Yggdrasil is an MCP **tool consumer only**,
  and `RemoteMCPProvider` is a `Protocol` with **zero production implementations** (test fakes only;
  `app/orchestrator/mcp_tool_provider.py:14-27`).
- Ratifying server/registry ownership rules before any real server exists is premature — the rules
  would be designed against a hypothetical shape rather than a real attachment's actual constraints.
- The stance is not discarded: it stays the leading candidate in
  `docs/architecture/ecosystem-federation.md` § Dual-role + MCP → *MCP topology stance*, ready to
  ratify when a real attachment is on the table.

### 4. No follow-up issues are filed by this ADR

Because the stance is deferred, not adopted, none of the rule-4 fixes or the availability-impact
descriptor field are filed as follow-up work here. They remain candidate work items in the artifact,
to be filed only once D4 is ratified.

## Constraints honored

- Decision record only — no code in `app/orchestrator/mcp_tool_provider.py`,
  `app/settings/models.py`, or the tool-policy contract changes in this ADR's PR.
- MCP's protocol-tier status is unchanged: this ADR does not promote MCP to architecture and takes
  no dependency on any real remote/sibling server existing today (none does).
- Single-user stance preserved: server ownership follows constituent ownership under one human
  apex authority; no multi-tenant or shared-registry reasoning is introduced.
- Reshape-adjacent items are Extend, not Reshape: no existing boundary charter, contract, or ADR is
  altered by this decision (`docs/architecture/ecosystem-federation.md` § SBS reconciliation, rows
  7–9). Enactment travels the implementation lane, not a CES boundary-reshape route.
- D1 (SoI framing), D2 (SFC interaction tiers), and D3 (INV-EF1 seam invariant) stand independently;
  this decision does not presuppose any of them, though rule 3's private-side registry contents
  align with D3's category (ii)/(iii) classification if D3 is adopted.

## Consequences

- The topology question the boundary audit raised stays undecided for now — deferred rather than
  re-litigated ad hoc, with the leading candidate stance preserved in the artifact for when a real
  attachment appears.
- **Residual risk, named honestly:** the silent-fallback gap (`except Exception: pass`,
  `app/orchestrator/mcp_tool_provider.py:41-43`) remains live and unaddressed by this deferral. It is
  reachable today by enabling `mcp_remote_multiplex_enable` with any injected remote provider — no
  admission allowlist gates it. Deferring D4 does not close this gap; it stays open until rule 4 (or
  an equivalent fix) is separately adopted and enacted.
- No implementation follow-up issues are filed by this ADR — the admission allowlist, legible
  degradation, typed multiplex flag, and availability-impact descriptor field are candidate work
  items only, contingent on future ratification.
- The operator's incoming private sibling constituent, the **Heimdall** sensor system, may reopen
  this question sooner than expected. However, a sensor system may attach via a non-MCP adapter
  (capture/ingest pipeline or A2A) rather than as an MCP server, so deferring D4 now is coherent —
  it does not presuppose Heimdall will be the trigger.

## When to revisit

Revisit when a concrete remote/sibling MCP server — or any MCP-based sibling attachment — first
appears. If the operator's incoming **Heimdall** sensor system attaches via MCP rather than a
non-MCP adapter, that is a possible trigger. At that point, ratify, revise, or decline the four-rule
stance against the real attachment's actual constraints, and evaluate the rule-4 fixes against
genuine remote traffic rather than the current `RemoteMCPProvider` test fake.

## References

- `docs/architecture/ecosystem-federation.md` § Dual-role + MCP → *MCP topology stance*, § Owner
  decisions (D4), § SBS reconciliation (rows 7–9).
- `app/orchestrator/mcp_tool_provider.py:14-27` (`RemoteMCPProvider` Protocol, zero production
  implementations), `:41-43` (silent exception swallow).
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md:229-243` (remote MCP admission model;
  no separate admission allowlist recorded).
- `docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md:31,62-68` (flag-as-admission-gate
  finding).
- `docs/INTEGRATION_FABRIC_CONTRACT.md:44` (target-state phrasing; divergence DV-3).
- ADR-0036 (standards are adapters, not the ontology); `docs/foundation/00-yggdrasil-doctrine.md:65-67`
  (§2.7 commitment).
- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md:322-327,339-342` (debt recommendation;
  MCP protocol-tier finding).
- ADR-0044 (D1 — SoI target-state framing); ADR-0045 (D2 — SFC interaction-tier rule); the
  companion D3 record (INV-EF1 public/private invariant) in
  `docs/architecture/ecosystem-federation.md` § Owner decisions.
