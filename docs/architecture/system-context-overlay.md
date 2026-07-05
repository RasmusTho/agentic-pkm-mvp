State: New — transcribes already-settled findings from the 2026-07-03 INCOSE boundary audit; decides
nothing new.
Doc role: Reference
Authority: ISO/IEC/IEEE 15288 context-layer vocabulary overlay for Yggdrasil. Names the System of
Interest (SoI) boundary, the enabling-system / COTS-in-deployed-configuration / external-system
classification rule, and the integrated system context model. A vocabulary layer over the existing
architecture, not a redesign — it renames nothing, restructures nothing, and grants no new
authority. Where this document and an owner doc appear to differ, the owner doc wins; this document
should be updated to match, not the other way around.
Owner: Architecture spine (docs/SYSTEM_CONTEXT_OVERLAY spec directory, task SBI-1)
Temporal class: timeless
Review cadence: event-driven
Source of truth: docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md
Last reviewed: 2026-07-03
Last verified against: docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md §1, §2, §3, §4,
§5, §9

# System Context Overlay — 15288 Vocabulary

Every claim below is a direct transcription of an already-settled finding in
`docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` (§1, §2, §3, §4, §5, §9). This document
does not introduce new analysis; it gives the audit's classification vocabulary one canonical,
citable home so downstream tasks (SBI-2, SBI-3, SBI-5, SBI-8) can reference it instead of each
restating or subtly redefining the same terms.

## System of Interest (SoI)

**Definition (15288 overlay).** The Yggdrasil SoI is the local-first cognitive-prosthesis software
system: the runtime (`app/`, `yggdrasil_runtime/`), its contracts and schemas, its system-owned
durable artifacts (companion notes, receipts, governance records), and its rebuildable machine
surfaces (object store, indexes, embeddings, outbox) — the three nested roles of
`docs/COGNITIVE_PROSTHESIS_CHARTER.md:25-40` read as one system.

**Boundary refinements the existing docs imply but never state:**

- **The human is not a component.** The human is the operator, the authority locus, and the
  principal stakeholder in the operational environment
  (`docs/foundation/00-yggdrasil-doctrine.md:24-39`, `docs/PROJECT_KERNEL.md:11`). Human memory is
  explicitly "not stored in the system" (`docs/COGNITIVE_PROSTHESIS_CHARTER.md:117`).
- **Vault content is custodied, not owned.** The human-authored Markdown corpus is an information
  artifact under human authority that must remain "comprehensible beyond the lifespan of any one
  implementation" (`docs/PROJECT_KERNEL.md:11`) and readable "with or without the system running"
  (`docs/COGNITIVE_PROSTHESIS_CHARTER.md:30-32`). In 15288 terms: the vault *surface* (format
  contract, catalog projection, write-guard discipline) is a SoI responsibility; vault *content
  authority* sits outside the SoI with the human. This is the existing kernel rule restated —
  nothing changes.
- **What it is NOT** is already well-owned: `docs/COGNITIVE_PROSTHESIS_CHARTER.md:191-204` (not
  cloud-first, not black-box, not multi-user, not a methodology, not vendor-locked) and
  `docs/PROJECT_KERNEL.md:13-20`. This overlay adds no new exclusions.

Verdict (audit §1): conform. The SoI is well-defined in substance; this overlay contributes only the
term and the two boundary refinements above.

## Lifecycle-role classification rule

15288 distinguishes systems that support the SoI's *lifecycle* (enabling systems) from systems the
SoI *interoperates with in operation* (external systems in the operational environment). The repo
already uses the enabling-system term once — the Builder System is "the continuous-development
enabling system" (`docs/architecture/SBS_OPERATING_MODEL.md:75`, `:84`) — but that category was
applied only to development tooling, never to operational infrastructure. That single omission
produces the infrastructure-classification contradictions the audit found (Ollama, Postgres/pgvector,
Colima, Tailscale, host gateway processes each described inconsistently across docs — audit §2).

**Resolution principle (the overlay's core rule).** The *port/adapter is always a SoI element*; the
attached thing's classification follows its lifecycle role:

| Classification | Meaning | Members (evidence) |
| --- | --- | --- |
| SoI component | Ships inside the system; versioned with it | `app/`, `yggdrasil_runtime/`, schemas, companion-note surface; embedded libraries incl. TTS engines (`requirements-tts.txt:8-9` — pip deps in the runtime image) |
| COTS system element (deployed configuration) | Third-party product the SoI's own deployment provisions and supervises; replaceable behind a port, but part of the deployed system | Postgres/pgvector instance (`docker-compose.yaml:3`, behind PDM `StorePort`, `app/stores/base.py`); Ollama *when run as the compose service* (`docker-compose.yaml:16-31`) |
| Enabling system | Supports lifecycle stages; not part of the operating system-of-interest | Builder System incl. GitHub/CI (`docs/architecture/SBS_OPERATING_MODEL.md:75,84` — already settled); Docker/Colima (`docs/INFRASTRUCTURE.md:15`); Tailscale mesh + host provisioning (`ops/host-setup/README.md:7-14`); ops/start scripts (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:522` names them "deliberately outside the SBS") |
| External system (operational environment) | Independently operated/managed; the SoI interoperates via contracts | Obsidian (`docs/INTEGRATION_FABRIC_CONTRACT.md:34` — dual-class by design); iCloud/sync transports (`:42` — "operational plumbing only"); cloud LLM/embedding APIs incl. Gemini fallback (ADR-0023); acquisition sources (`:48`); telemetry consumers (`:46`); *Ollama when reached as a host/remote service* (`docs/ARCHITECTURE.md:109`) |

Ollama legitimately appears twice — the classification attaches to the *deployment binding*, not the
product name. Note the trust posture is orthogonal and already settled: whatever the classification,
external components are "mechanisms, not authority" (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1339`;
`docs/INTEGRATION_FABRIC_CONTRACT.md:90-96`; `docs/SECURITY_TRUST_BOUNDARIES.md:31`). The IFC's word
"external" describes trust/control posture, not 15288 location.

This overlay defines the classification rule and vocabulary only. It does not populate the infra
classification table (that is `docs/architecture/SBS_OPERATING_MODEL.md` §3 / `docs/ARCHITECTURE.md
:: System Context` extension, SBI-2) or the spine↔SBS crosswalk rows (`SBS_CURRENT_TO_TARGET_MAPPING.md`,
SBI-3). It also does not decide the dual-role infrastructure stance (the same infrastructure as both
enabling system and a domain of interest the SoI observes/actuates) or the MCP server/registry
topology question — both are named and deferred to the companion thread
`docs/architecture/ecosystem-federation.md` per audit §2.

## Integrated system context model

One view, reconciling both existing taxonomies (audit §4):

```
                        ┌─────────────────────────────────────────────┐
   HUMAN (operator,     │              YGGDRASIL SoI                  │   EXTERNAL SYSTEMS
   authority locus)     │                                             │   (operational env.)
     │ intent/review    │  Human Experience ─ HIX ◄──────────────────┼── Obsidian (editor;
     ▼                  │  Cognitive Context ─ WSP · SFC             │    dual-class human
   vault Markdown ◄─────┼─► Human Authority Kernel ─ HKA · SIP · GOV │    surface + UI shell)
   (human-owned content,│  Cognitive Augmentation ─ RCA · MEM · CAO  │◄── iCloud / sync
   SoI-custodied        │  Governed Execution ─ EXE                  │    transports
   surface)             │  Machine Substrate ─ PDM · DRI             │◄── cloud LLM/embedding
                        │  External Boundary ─ EBF (all adapters)    │    APIs (Gemini, …)
                        │  Trust & Evolution ─ OEF (+ CES practice)  │◄── acquisition sources
                        │        │ StorePort        │ telemetry      │    (YouTube, RSS, …)
                        └────────┼──────────────────┼────────────────┘◄── telemetry consumers
                                 ▼                  ▼
                        COTS elements in the deployed configuration:
                          Postgres/pgvector · Ollama-as-service
                        ─────────────────────────────────────────────
                        ENABLING SYSTEMS: Builder System (agents, CI,
                        GitHub) · Docker/Colima · Tailscale mesh ·
                        host provisioning (ops/host-setup) · ops scripts
```

**Taxonomy reconciliation.** This view reconciles the 8-subsystem architecture spine
(`docs/MODULAR_ARCHITECTURE.md`) with the 14-boundary target SBS
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md`): spine Human Surface→HIX; Knowledge & Artifact→HKA(+SIP);
Runtime Projection→PDM+DRI; **Capability→CAO+RCA (the split no doc currently states)**;
Agent/Orchestration→CAO; Governance/Authority→GOV; Integration Fabric→EBF; Observability/Fitness→OEF.
WSP, SFC, MEM, EXE have no dedicated spine ancestor — they are target-state refinements, which is
exactly why the spine must stay a *bridge* (its own claim, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:63`)
and why the full crosswalk belongs in `SBS_CURRENT_TO_TARGET_MAPPING.md` as rows, not prose (SBI-3;
this overlay states the reconciliation principle only, it does not populate the crosswalk table).
Control flows and authority gates are already owned by `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
(canonical control flows, `:1352-1394`) — this context model adds the environment side only.

## System of Systems (SoS) — repo usage vs INCOSE

`docs/GLOSSARY.md :: System of Systems` is the canonical entry for this term (added by this task,
audit §3). In summary: the repo's internal usage is colloquial for "modular, authority-separated
single system" (`docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md:97-101`'s "modularity with
replaceability, not one monolithic agent runtime"), consistent with ADR-0015's modularity intent; the
INCOSE sense requires operationally- and managerially-independent constituents and does not apply to
the internal 8-subsystem decomposition (`docs/MODULAR_ARCHITECTURE.md:26` states those
subsystems are "not separate deployments, services, or processes") — this is cited as advisory from
the 2026-07-03 audit §3, not a settling ruling. The one INCOSE-defensible SoS reading in the repo is
the operator's assembled environment (Yggdrasil + Obsidian + iCloud, `docs/ARCHITECTURE.md:239`).
Whether to rename `docs/MODULAR_ARCHITECTURE.md` on the strength of that reading is an open
owner decision (audit §15 Q2, routed to SBI-8) — this overlay links the question, it does not answer
it. See also the overlay note in `docs/MODULAR_ARCHITECTURE.md` itself.

## Enabling-system principle

**Principle (audit §9):** development machinery and operational infrastructure never define product
architecture. The Builder/Product split already exists operationally
(`docs/architecture/SBS_OPERATING_MODEL.md` §3); this overlay states it as the missing design
principle rather than adding a new principles document. The companion "Volatility Isolation"
principle in `docs/DESIGN_PRINCIPLES.md` §9 describes volatility isolation, not SoS in the INCOSE
sense (audit §3); it was reworded from "System-of-Systems Thinking" per ADR-0042 / #2856.

## Functional allocation

`docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` is the system's functional-allocation view (audit §5). It binds
every canonical human flow to primary/secondary SBS owners, the SBS-owned interfaces crossed, derived
testable requirement(s), verification anchor(s), and debt/fitness rules, and explicitly guards
itself: "This is not a full Functional Breakdown Structure and not a parallel source of truth." No
FBS and no function-ID register are introduced by this overlay or recommended by the audit — that
question was raised and refuted at the audit's own skeptic gate: closed issue #2409 already delivers
the derivative functional-allocation view, and synthetic `AF-xx`/`CAP-xx`-style codes would contradict
the owner's human-first-naming stance and create a rot-prone parallel registry.

## Related docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` — source audit (§1, §2, §3, §4, §5, §9)
- `docs/SYSTEM_CONTEXT_OVERLAY/README.md` — spec directory this task belongs to
- `docs/MODULAR_ARCHITECTURE.md` — architecture spine (8-subsystem map); carries the SoS
  overlay note pointing back here
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` — target 14-boundary SBS
- `docs/GLOSSARY.md` — `System of Systems` entry
- `docs/DESIGN_PRINCIPLES.md` — §9 "Volatility Isolation" (reworded per ADR-0042 / #2856; not by this task)
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — functional-allocation view
- `docs/foundation/00-yggdrasil-doctrine.md`, `docs/PROJECT_KERNEL.md`,
  `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — SoI boundary sources
- `docs/architecture/ecosystem-federation.md` — companion thread owning the dual-role
  infrastructure stance and MCP topology question (named here, decided there)
