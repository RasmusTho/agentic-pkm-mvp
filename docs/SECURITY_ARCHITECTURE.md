State: Initial security architecture spine. Docs-only; does not change runtime behavior or claim high current adversarial exposure.
Doc role: Core SoT
Authority: Canonical entry point for Yggdrasil security architecture framing, threat-model tiers, security invariants, and review routing. Subordinate to current runtime SoT docs for shipped behavior and to semantic authority docs for meaning/authority semantics.
Owner: Security architecture / governance
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-04
Last verified against: docs/ARCHITECTURE.md, docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/SEMANTIC_AUTHORITY_MATRIX.md, docs/SECURITY.md, docs/PRIVACY.md, docs/HUMAN-FLOWS.md, docs/HUMAN_FLOW_TO_RUNTIME_MAP.md, companion-ui/docs/LOCAL_ACCESS_MODEL.md, companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md, companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md, docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md, docs/contracts/A2A_CONTRACT_AND_TRACE.md, docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md, docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md, docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md, docs/adr/ADR-0010-builderops-vault-authority-boundary.md

# Security Architecture

## Scope

This document is the security architecture entry point for Yggdrasil / Agentic PKM. It defines the
security framing, assumptions, threat-model tiers, invariants, and review routing used before
formal STRIDE, ATT&CK-inspired, attack-path, or attack-tree work.

It is intentionally a spine, not a replacement for existing owner docs. Detailed current runtime
truth remains in `docs/ARCHITECTURE.md` and `docs/STATUS.md`. Detailed semantic authority remains
in `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` and `docs/SEMANTIC_AUTHORITY_MATRIX.md`.

## Study and proportionality framing

The current system is personal, local-first, and single-user oriented. The default posture is not a
high-probability adversarial production environment. Security architecture exists here for:

- study of agentic-system failure modes,
- design hardening before wider exposure,
- clear trust and authority boundaries,
- future readiness for LAN, Tailscale, public, multi-device, or multi-user deployment,
- and repeatable review of new authority-bearing surfaces.

Do not inflate severity merely because an attack is theoretically possible. Reviews should separate
current personal-use risk, plausible future networked risk, and study-only adversarial scenarios.

## Security assumptions

- Localhost-only personal use is lower risk than networked or public deployment.
- LAN or Tailscale exposure is an explicit operator choice and is not equivalent to public
  internet readiness.
- Public internet exposure is not supported without a separate accepted auth/TLS/reverse-proxy
  contract and implementation.
- External LLM, embedding, MCP, GitHub, and cloud-like providers are optional capability or
  integration surfaces, not semantic authority.
- Runtime mirrors can be lost and rebuilt without changing meaning; durable meaning lives in the
  human-readable continuity set and governance-recorded records.
- Security review must preserve the human-flow contract in `docs/HUMAN-FLOWS.md` and
  `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`.

## Threat-model tiers

### Realistic current personal/local-first risk

Use this tier for likely present-day failures:

- accidental LAN exposure of local API or Companion UI without auth,
- secrets, note text, prompts, or provider payloads leaking through logs, traces, or external calls,
- unsafe Markdown/rendering behavior in copied or imported notes,
- misconfigured watcher, tool, or UI path causing unintended local writes,
- dependency vulnerabilities in locally exposed services,
- stale runtime mirrors or UI projections being mistaken for authority.

### Plausible future networked/multi-user risk

Use this tier for likely future exposure:

- untrusted clients reaching mutation-capable API routes,
- token, CSRF, CORS, TLS, or reverse-proxy mistakes,
- remote MCP or provider descriptor abuse,
- multi-user approval ambiguity,
- sync/replica conflict or stale data influencing decisions,
- externally sourced artifacts poisoning context, memory, or retrieval.

### Study-only adversarial scenarios

Use this tier for learning and stress-testing architecture, not for current operational urgency:

- prompt injection inside a note attempts to direct tool use,
- context poisoning steers a proposal through plausible but false evidence,
- memory poisoning attempts to turn inferred or repeated material into hidden authority,
- tool-output manipulation influences downstream governance or receipts,
- BuilderOps material attempts to launder operational records into product/runtime truth,
- audit or receipt ambiguity hides the basis for a consequential action.

### Architectural invariants

Use this tier for properties worth preserving regardless of risk probability:

- human-authored Markdown remains primary for durable meaning,
- DB, index, and cache state are mirrors, not semantic authority,
- runtime writes follow their applicable authority lane: governance-bearing writes are receipt-bearing,
  while Canvas body co-authoring uses user-present confirmation, undo, and session-log provenance,
- Companion UI is a projection/control surface, not file authority,
- BuilderOps proposes and records, but does not replace repo/product truth,
- memory and context bundles do not bypass governance,
- `may_write` or similar flags do not bypass WriteGuard, policy, or admission.

## Security invariants

These invariants are binding review inputs:

1. Human Markdown remains primary for durable meaning.
2. DB/index/cache are rebuildable mirrors and cannot originate semantic authority.
3. Runtime writes must cross the applicable governance or co-authoring boundary and produce the
   matching accountability evidence. Governance-bearing writes produce receipts; Canvas body-edit
   co-authoring does not produce Panel governance receipts and instead records provenance through
   the session log, as defined in `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`.
4. Companion UI may project, stage, queue, and control through the runtime API; it must not read or
   write vault files directly or classify its own durable authority.
5. BuilderOps may guide, record, and propose, but product/runtime truth changes only through repo
   and target authority gates.
6. Memory is non-authoritative unless reviewed/promoted through governed gates.
7. Context bundles are inspectable evidence envelopes; they do not become memory, truth, or write
   authorization by existing.
8. `may_write` is never sufficient on its own. WriteGuard, policy, trust semantics, and admission
   still run independently. All vault-internal writes must pass WriteGuard before filesystem
   mutation, including system-owned companion files and companion healing or continuity rewrites;
   non-vault log and tmp writes are exempt by path ownership.
9. Receipts must remain human-legible accountability artifacts, distinct from raw traces.
10. External providers and tools may supply capability, inference, transport, or interface; they do
    not become authority without explicit Yggdrasil contracts.

## Relationship to existing docs

- Semantic authority docs: `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`,
  `docs/SEMANTIC_AUTHORITY_MATRIX.md`,
  `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`, and
  `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` define the meaning/authority layers
  this security model consumes.
- Human-flow docs: `docs/HUMAN-FLOWS.md` and `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` define the
  human purpose security controls must not defeat.
- Companion UI docs: `companion-ui/docs/LOCAL_ACCESS_MODEL.md`,
  `companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md`, and
  `companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md` define browser access, projection, and
  rendering boundaries.
- Tool/MCP contracts: `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`,
  `docs/contracts/A2A_CONTRACT_AND_TRACE.md`, and `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md`
  define current execution controls and non-claims.
- BuilderOps boundary docs: `docs/adr/ADR-0010-builderops-vault-authority-boundary.md`,
  `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`, and
  `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md` define build-plane authority.
- Receipt/audit contract: `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` defines receipt,
  trace, and audit distinctions.
- Existing operational security: `docs/SECURITY.md`, `docs/PRIVACY.md`, and security roadmap
  snapshots remain operational inputs, not replacements for this architecture spine.

## Review method

Use `docs/SECURITY_REVIEW_METHOD.md` to decide when to run Level 0 through Level 4 security
reviews, how to fill STRIDE-lite and attack-path worksheets, and how to classify findings without
overstating current personal-use risk.
