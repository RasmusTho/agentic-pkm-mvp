State: Initial Level 2 STRIDE-lite security review for foundation wave (#1588).
Doc role: Security review report
Authority: Point-in-time STRIDE-lite review over current security-relevant surfaces. Findings are analysis inputs, not implemented mitigations.
Owner: Security architecture / governance
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-04
Last verified against: docs/SECURITY_ARCHITECTURE.md, docs/SECURITY_TRUST_BOUNDARIES.md, docs/SECURITY_DATA_FLOWS.md, docs/security/API_SECURITY_MATRIX.md, docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md, companion-ui/docs/PRODUCTION_EXPOSURE_SECURITY_PROFILE.md

# STRIDE-Lite Review - Security Foundation Wave

## Scope and framing

This is the first Level 2 STRIDE-lite review using `docs/SECURITY_REVIEW_METHOD.md`. It reviews the
current security-relevant architecture surfaces and the foundation inputs produced by #1587, #1590,
and #1589.

The review is proportionate to the current personal/local-first system. It does not claim current
high adversarial exposure, does not implement mitigations, and does not create follow-up issues.

## Inputs

- `docs/SECURITY_ARCHITECTURE.md`
- `docs/SECURITY_TRUST_BOUNDARIES.md`
- `docs/SECURITY_DATA_FLOWS.md`
- `docs/security/API_SECURITY_MATRIX.md`
- `docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md`
- `companion-ui/docs/PRODUCTION_EXPOSURE_SECURITY_PROFILE.md`

## Findings classification table

| ID | Surface | STRIDE category | Finding | Classification | Current controls | Gap / follow-up candidate |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | Runtime API | Spoofing / EoP | Loopback routes have no route-specific auth; non-loopback exposure would let any reachable client call mutation routes. | Plausible future networked/multi-user risk | Trusted-device server default, public unsupported, feature flags/WriteGuard on some routes. | Define auth/rate-limit implementation only if non-loopback support is accepted. |
| F2 | Runtime API | Information Disclosure | Read and diagnostic routes can expose vault body, paths, outbox events, status, or settings posture. | Realistic current personal-use risk | Path validation, health redaction, trusted-device server default. | Keep diagnostic routes loopback-only; review before LAN/Tailscale exposure. |
| F3 | Governance/write | Repudiation | Not all body writes produce governance receipts because human/body co-authoring uses provenance, not Panel receipts. | Architectural invariant | Session logs, content hashes, WriteGuard/data-safety checks, explicit lane distinction. | Preserve wording so governance-bearing receipts are not incorrectly required for body co-authoring. |
| F4 | Governance/write | Tampering / EoP | `may_write`, UI confirmation, context-bundle flags, or model output could be mistaken as write authorization. | Study-only adversarial scenario | Security invariants, bundle consumers rejecting `may_write=true` for read-only frames, WriteGuard/policy lanes. | Include in future attack-path exercises. |
| F5 | Companion UI | Spoofing / CSRF | LAN/Tailscale or future cookie/session use could let another browser origin trigger mutation-capable routes. | Plausible future networked/multi-user risk | trusted-device server default, public unsupported, explicit non-loopback review posture. | Token/session/CORS/CSRF implementation issue only if exposure support is approved. |
| F6 | Companion UI | Information Disclosure | Renderer and workspace responses expose note text to the browser by design; unsafe rendering could widen exposure. | Realistic current personal-use risk | Runtime API boundary, renderer read-only contract, no direct vault access. | Keep plugin/code execution out of renderer; review sanitizer/asset behavior before broader exposure. |
| F7 | Tool/MCP | Tampering / EoP | Remote descriptors or tool outputs could influence downstream decisions if treated as authoritative. | Plausible future networked/multi-user risk | Local registry default, flags/allowlists for real execution, unsupported remote tools filtered. | Add remote MCP admission/version/provenance contract before supported remote use. |
| F8 | Tool/MCP | DoS | Real or remote tools without explicit timeout/call budgets can exhaust local resources. | Plausible future networked/multi-user risk | Optional per-tool timeout, max calls, plan timeout. | Require explicit timeout/call-budget posture for high-risk real tools. |
| F9 | Memory/context | Tampering / EoP | Context or memory candidates could become hidden authority if promoted or reused without review. | Study-only adversarial scenario | Memory non-authority contract, context bundle bridge contract, review/promotion lifecycle. | Run targeted memory/context attack-path review later. |
| F10 | BuilderOps/repo | EoP / Repudiation | BuilderOps records or generated projections could be laundered into repo/product truth without target gates. | Study-only adversarial scenario | ADR-0010 boundary, promotion gateway, GitHub issue/PR authority gates. | Include BuilderOps/product-truth laundering in future Level 3 review if automation expands. |

## Surface worksheets

### Runtime API Boundary

- Review level: Level 2
- Boundary: Runtime API boundary
- Current exposure assumption: trusted-device server default; loopback opt-out; public unsupported.
- Existing controls: route path validation on vault reads/writes, feature flags on Canvas/workspace update paths, WriteGuard on selected write paths, health redaction, route-level limits on several list/tail routes.

| STRIDE category | Finding / not applicable | Notes |
| --- | --- | --- |
| Spoofing | Future risk: no route-specific auth under non-loopback exposure. | Current trusted-device personal server use is proportionate; non-loopback support needs auth posture. |
| Tampering | Mutation routes exist for ingest, Panel confirm, Canvas/workspace/body save, BuilderOps writes. | Controls differ by lane; matrix records each route. |
| Repudiation | Some routes emit traces, receipts, or session provenance; simple reads do not. | Body co-authoring should not be misclassified as missing governance receipts. |
| Information Disclosure | Vault note reads, workspace aggregate, event tail, debug panel, settings/status routes expose sensitive local data if reachable. | Main current risk is accidental exposure beyond trusted-device server access. |
| Denial of Service | List/search/provider routes can consume local resources. | Several routes have limits; no global rate-limit contract. |
| Elevation of Privilege | API reachability could grant mutation capability under wrong exposure. | Exposure profile and route matrix are prerequisite controls. |

### Governance / Write Boundary

- Review level: Level 2
- Boundary: Governance/write boundary
- Current exposure assumption: local runtime-controlled mutation lanes.
- Existing controls: WriteGuard, policy/idempotency/receipt on Panel confirmation, feature flags, content hashes, frontmatter rejection for body-edit routes, session-log provenance for Canvas.

| STRIDE category | Finding / not applicable | Notes |
| --- | --- | --- |
| Spoofing | A caller could claim user intent if mutation endpoints are exposed without auth. | Future networked risk, not current public-exposure claim. |
| Tampering | Durable body writes exist; metadata/governance writes route separately. | Preserve body co-authoring versus governance-bearing lane split. |
| Repudiation | Governance-bearing writes need receipts; body co-authoring needs session/user-present provenance. | Current SoT now reflects the Canvas exception. |
| Information Disclosure | Receipts/provenance may include note paths or rationale. | Keep human-legible without leaking secrets/raw data unnecessarily. |
| Denial of Service | Write endpoints can generate file writes, proposals, or events. | Feature flags and WriteGuard reduce accidental use. |
| Elevation of Privilege | `may_write`, UI state, or model output must not bypass WriteGuard/policy/admission. | Architectural invariant. |

### Companion UI Projection / Control Boundary

- Review level: Level 2
- Boundary: Browser/UI boundary and environment/exposure boundary
- Current exposure assumption: localhost dev/staging default.
- Existing controls: no direct vault access, runtime API mediation, read-only renderer contract, server-side authority classification, explicit unsupported public posture.

| STRIDE category | Finding / not applicable | Notes |
| --- | --- | --- |
| Spoofing | Future LAN/Tailscale auth/session ambiguity. | Token/session posture required before supported non-loopback production use. |
| Tampering | UI could stage or call mutation routes, but server owns classification. | UI state must never become authority. |
| Repudiation | UI displays receipts/provenance but does not author receipts. | Keep provenance visible at interaction time. |
| Information Disclosure | Browser receives note text, paths, link indexes, receipts, memory posture. | Expected for local UI; exposure-dependent risk. |
| Denial of Service | Rendering large notes, link indexes, or vault browser lists can consume browser/runtime resources. | Existing caps help; broader exposure may need rate limits. |
| Elevation of Privilege | UI projection may appear authoritative to user or downstream code. | Semantic projection alignment controls this conceptually. |

### Tool / MCP Boundary

- Review level: Level 2
- Boundary: Tool/MCP and agent/A2A boundaries
- Current exposure assumption: local registry default; remote multiplex optional/flagged.
- Existing controls: descriptor registry, top-level arg validation, required fields, flags, allowlists, optional timeouts/call budgets, trace events.

| STRIDE category | Finding / not applicable | Notes |
| --- | --- | --- |
| Spoofing | Remote providers/descriptors could claim tool identity. | Remote admission model is future hardening. |
| Tampering | Tool output can manipulate downstream prompts/proposals if trusted blindly. | Treat outputs as less-trusted inputs. |
| Repudiation | Started/finished traces exist; tool failures may rely on orchestrator errors. | High-risk real tools may need explicit audit expectations. |
| Information Disclosure | Tool args/results and provider payloads may contain note text, paths, or secrets. | Egress/secrets review required for remote tools. |
| Denial of Service | Real/remote tools can hang or overrun budgets. | Timeout/call-budget posture should be explicit. |
| Elevation of Privilege | Descriptor presence, flags, or remote output could be mistaken for authority. | Flags are not authorization by themselves. |

### Memory / Context Bundle Boundary

- Review level: Level 2
- Boundary: Memory/context bundle boundary
- Current exposure assumption: local read/projection and review/promotion paths.
- Existing controls: memory lifecycle, context bundle authority flags, no hidden memory authority, bundle consumers reject write-capable bundles for read-only orientation/resurfacing paths.

| STRIDE category | Finding / not applicable | Notes |
| --- | --- | --- |
| Spoofing | Context or memory source could be misrepresented. | Provenance/source refs are required controls. |
| Tampering | Poisoned context could steer suggestions. | Study/future risk unless external/untrusted inputs expand. |
| Repudiation | Memory handoff intents are traces, not candidate creation or receipts. | Keep candidate/review/promotion transitions explicit. |
| Information Disclosure | Bundles expose selected/excluded context and authority flags. | Expected locally; provider/export use needs review. |
| Denial of Service | Large bundles/retrieval can consume resources. | Keep limits/expiry/staleness visible. |
| Elevation of Privilege | Bundle `may_write` or memory recall could be treated as write authority. | Explicitly prohibited by security invariants. |

### BuilderOps / Repo Boundary

- Review level: Level 2
- Boundary: BuilderOps/repo and GitHub/issues/PR boundaries
- Current exposure assumption: local BuilderOps boundary plus explicit GitHub actions.
- Existing controls: ADR-0010, promotion gateway, BuilderOps boundary, GitHub issue/PR authority gates, BuilderOps receipt model.

| STRIDE category | Finding / not applicable | Notes |
| --- | --- | --- |
| Spoofing | Actor/source refs in BuilderOps records can be wrong if callers lie. | Current boundary validates shape, not identity proof. |
| Tampering | BuilderOps records can propose repo/product changes. | Promotion gateway does not mutate authority surfaces directly. |
| Repudiation | BuilderOps receipts support operational accountability. | GitHub remains executable task-contract authority. |
| Information Disclosure | Worklogs/signals may include sensitive local or repo context. | Keep secrets/raw private content out of records. |
| Denial of Service | Record flooding can clutter operational plane. | Low current local risk; rate/admission for broader automation may be needed. |
| Elevation of Privilege | Generated projections or PromotionIntents could be mistaken for repo truth. | Architectural invariant and ADR boundary prohibit this. |

## Recommended follow-up issues

Do not create these automatically from this report. They are candidates for a later explicitly
requested security wave:

- Define non-loopback auth/rate-limit implementation for Companion UI/API only if supported
  LAN/Tailscale production use is accepted.
- Define remote MCP provider admission/version/provenance contract before supported remote
  execution.
- Define diagnostic route exposure policy for `/events/tail`, `/api/debug/*`, status, and settings
  routes if non-loopback exposure expands.
- Run a Level 3 attack-path review for memory/context poisoning if external ingestion or remote
  provider input becomes a larger source of context.

## Completion statement

This Level 2 review found no reason to reclassify the current personal/local-first system as high
adversarial exposure. The main current risks are accidental non-loopback exposure, sensitive local
data appearing in browser/API/diagnostic surfaces, and confusion between projection/provenance and
authority. Future hardening should be triggered by exposure, remote provider/tool, or multi-user
changes rather than by theoretical attack paths alone.
