# Boundary: EBF — External Boundary Fabric

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** EBF owns **the boundary between Yggdrasil and things it does not
fully control**. External systems provide mechanisms, observations, candidate evidence, inference,
transport, or interface — they do not become authority without explicit governance.

## Purpose

Own external attachment and adapter isolation — sources, watchers, importers, model/embedding
providers, tool/MCP descriptors, parsers/OCR, and external UI/editor shells — so provider churn
never leaks into core semantics, and so external mechanisms never become authority on their own.

## Owns

- Source adapters, watcher adapters, import adapters, parser/OCR adapters, external UI/editor
  adapters (`SYSTEM_BREAKDOWN_STRUCTURE.md:707-720`).
- Model provider adapters, embedding provider adapters, tool/MCP adapters.
- Provider identity and versioning, egress policy enforcement (in coordination with GOV), external
  result normalization, external availability and fallback posture.
- **Integration lifecycle management — owned but not yet implemented.** There is currently no
  runtime integration registry: provider identity and versioning are assigned to EBF
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:717`; audit §7 "Lifecycle management") but no mechanism tracks
  which integrations are attached, their versions, or their health over time. This gap is
  acceptable while integration count is small; EBF is the charter this mechanism attaches to when
  it is eventually built. This charter states the responsibility now so a future implementation has
  an owning boundary — it does not build the registry.

## Does not own

- Semantic authority, artifact identity → **HKA**/**SIP**.
- Policy decisions, authorization → **GOV**.
- Sync/federation semantics → **SFC**.
- Agent planning → **CAO**.
- Durable knowledge → **HKA**; memory lifecycle → **MEM**.
- Execution of authorized side effects → **EXE** (EBF is the adapter EXE calls through, not the
  authorizer or the execution-status owner).

> **Ownership-drift rule.** EBF translates and isolates external mechanisms; it must not become a
> dumping ground for core semantics. If an external signal implies a semantic, policy, or authority
> decision, EBF passes it to the owning boundary (SIP/HKA/GOV) rather than resolving it locally.

## Inputs

- Provider contracts and calls from **RCA**, **DRI**, **CAO**, **EXE**, **HIX**, **SFC**, and
  **PDM** (`SYSTEM_BREAKDOWN_STRUCTURE.md:1441` — EBF is called by these subsystems, it does not
  originate requests to them).
- External events: source/file changes, provider responses, tool/MCP results, egress policy from
  GOV.

## Outputs

- `SourceObservationEvent` — records observed external/local source changes and source binding.
  Watcher/source-observation delivery semantics are currently owned by SFC `ReplicationEnvelope`
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1498`).
- Normalized external results, provider health/availability signals, fallback-posture status.

## Calls allowed

- Serves **RCA**, **DRI**, **CAO**, **EXE**, **HIX**, **SFC**, and **PDM** through provider/adapter
  contracts (`SYSTEM_BREAKDOWN_STRUCTURE.md:1441`) — it is called for external attachment, it does
  not drive semantics. Individual caller charters currently enumerate this relationship with varying
  granularity (e.g. `docs/boundaries/DRI.md` names EBF explicitly for embedding/model providers;
  `docs/boundaries/RCA.md` and `docs/boundaries/HIX.md` do not yet list EBF in their own
  "Calls allowed" sections). This charter states EBF's side of the SBS-level caller list; narrowing
  or reconciling each caller's enumerated dependency list is CES stewardship, not an EBF authority
  change.
- **GOV** — coordinate egress policy enforcement; defer any admissibility decision to GOV.

## Calls forbidden

- **Leaking provider-specific concepts into HKA/SIP/GOV** — vendor/API choices must not become
  architecture (`SYSTEM_BREAKDOWN_STRUCTURE.md:1461`).
- **Granting authority** — an external observation, provider response, or tool result is not
  admissible evidence or durable truth until GOV/SIP/HKA say so.
- **Silent fallback without legible degradation** — a remote/provider failure must surface as a
  visible availability/fallback signal, not a silent substitution (audit §6, item 3: "the remote MCP
  multiplex seam falls back silently on remote failure and has no admission allowlist" is a named
  gap this charter does not resolve, but a future EBF fallback implementation must not repeat it).

## Required metadata

EBF **originates `source_role`** for externally observed material (what kind of external source
this came from) and **must not set `authority_state` or `evidence_role`** — those remain GOV/SIP
decisions downstream of the observation. EBF preserves `scope_binding` and `sensitivity` as declared
by the calling subsystem; it does not infer either from provider identity.

## Policy obligations

- Egress policy enforcement happens in coordination with GOV — EBF enforces the mechanic, GOV owns
  the policy decision.
- External availability/fallback posture must be observable (via OEF), never a silent substitution
  that hides degraded service from the human or from GOV.

## Provenance obligations

- Every `SourceObservationEvent` carries source binding and provider identity so downstream
  subsystems (SIP, HKA) can attribute origin without re-deriving it.
- Provider identity/versioning is preserved on the adapter side; it must not be stripped or
  collapsed into a generic "external" tag before reaching SIP.

## Invariants owned

- External systems are mechanisms, not authority (matrix row EBF; `SYSTEM_BREAKDOWN_STRUCTURE.md:1339`).
- Provider-specific concepts do not leak into HKA/SIP/GOV (matrix #forbidden-dependencies;
  `SYSTEM_BREAKDOWN_STRUCTURE.md:1461`).
- Standards/MCP are adapters, not the ontology (traceability matrix principle #18).

## Failure modes

- **Authority leak:** treating a provider response or tool result as accepted truth without routing
  through GOV/SIP/HKA.
- **Vendor bleed:** provider-specific naming, schemas, or assumptions appearing in core contracts.
- **Silent degradation:** a provider/transport failure that falls back without a visible signal —
  named live at the remote MCP multiplex seam (audit §6); any future EBF fallback mechanism must
  close this, not extend it.
- **Ungoverned lifecycle:** integrations attached, upgraded, or retired with no registry tracking
  identity/version/health — the deliberate current gap named in Owns, not yet a failure while
  integration count stays small, but the container this charter reserves for it.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `external_mechanisms_not_authority`
- `provider_concepts_do_not_leak`
- `fallback_is_legible_not_silent`

## Related ADRs

- ADR-0036 (standards/MCP are adapters, not architecture tier).
- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- `SourceObservationEvent` (SBS Part 5); provider/tool contracts named at
  `docs/INTEGRATION_FABRIC_CONTRACT.md:3,103`; `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`.

## Related issues

- Charter: [#2836](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2836) (SBI-7) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
