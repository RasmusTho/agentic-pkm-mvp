State: Advisory audit snapshot (2026-07-03). Subordinate to `docs/DOCS_INDEX.md` and owner contracts. Backlog handoff in §14 routes through `feature-breakdown`; executable form lives in the specification directory `docs/SYSTEM_CONTEXT_OVERLAY/`. No reshape is enacted here.
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis under an INCOSE / ISO-IEC-IEEE 15288 lens; file:line anchors reflect `origin/main` at db662a24 (2026-07-03; verified at 75792973 and re-checked after the #2823 fast-forward, which touched no anchored surface). Where this audit and an owner doc disagree, the owner doc wins and the divergence should be raised via issue, not silently resolved. INCOSE vocabulary is applied as a context-layer overlay only (owner decision 2026-07-03); it renames and restructures nothing.

# Mimer System Boundary Review — INCOSE / ISO-15288 Lens

Method: architecture-research pass (`.codex/skills/architecture-research/SKILL.md`) — nine parallel
read-only explorers cut along SBS boundaries, central synthesis, and independent adversarial
skeptics on every reshape-class claim. Reshape-tagged items follow the binding SBS-reconciliation
rule (precedent: `docs/architecture/runtime-semantics.md :: SBS boundary mapping`): they are
proposals routed through CES / `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` / ADR + owner
decision, never enacted by this audit.

## Executive summary

Five corrections, most systemic first (blast radius × silence of failure):

1. **The missing layer is classification vocabulary, not structure.** Internal boundary discipline
   is strong and largely code-verified (down to zero vendor-SDK imports anywhere in `app/` or
   `yggdrasil_runtime/`, §7). But nothing classifies the *running external things* — the Postgres
   instance, Ollama, Docker/Colima, Tailscale, iCloud, GitHub, Obsidian — as SoI elements, enabling
   systems, or external systems. The same Ollama is an "optional external provider"
   (`docs/ARCHITECTURE.md:109`) and a first-party compose service (`docker-compose.yaml:16-31`);
   the same Postgres is extension fabric inside the system
   (`docs/MODULAR_ARCHITECTURE.md:58`) and an "external durable store"
   (`docs/INTEGRATION_FABRIC_CONTRACT.md:41`). One overlay (§2, backlog SBI-1/SBI-2) resolves this
   without touching the authority architecture.
2. **"System of Systems" is a category error for the internal decomposition — and the repo's own
   text proves it.** The spine says its subsystems are "not separate deployments, services, or
   processes" (`docs/MODULAR_ARCHITECTURE.md:26`); no SoS taxon (directed, acknowledged,
   collaborative, virtual) admits constituents with no independent operability. The intent behind
   the term — modularity with replaceability (`docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md:97-101`,
   ADR-0015) — is correct and preserved; only the taxonomy is wrong. One defensible SoS reading
   exists *outside* the SoI: the operator's assembled environment (Yggdrasil + Obsidian + iCloud,
   `docs/ARCHITECTURE.md:198`). Fix is a glossary entry (none exists today) plus a one-paragraph
   overlay note; any rename is a CES-routed reshape (§3, SBI-1, owner question Q2).
3. **Two structural taxonomies, no crosswalk.** The 8-subsystem spine and the 8-macrodomain /
   14-boundary SBS coexist with no row-level mapping; the spine's "Capability" subsystem silently
   splits across CAO and RCA; docs cite one taxonomy or the other (§4, §6). One crosswalk table in
   the existing mapping doc closes it (SBI-3).
4. **Requirements truth is scattered; no SRS exists and nothing says so.** Of twenty
   requirement axes, seven are scattered and two absent (non-functional requirements;
   scalability-as-requirement); no document self-identifies as a requirements baseline, and the
   deliberate single-user omission of scale/perf budgets is nowhere stated as deliberate (§8,
   SBI-5). The fix is an index overlay and two owner decisions — not writing an SRS in this pass.
5. **SBS enforcement drift is real but almost entirely self-documented** — the register and
   transition-debt files already record most gaps (D2, D4-D6, D8). The audit adds only what the
   register itself gets wrong: two misanchors (SIP's registered module is an embeddings/provider
   module its own charter excludes; OEF's is a latency-metrics file), a contract-name split
   (`MemoryItem` vs `MemoryRecord`), and a legacy provider surface (`app/llm/adapter.py`, dead;
   plus `app/llm/embeddings.py`, still doc-cited as the registry) that docs present as canonical
   while the live access layer is `app/components/llm/` (§6, SBI-4).

Charter-premise corrections found while auditing (evidence discipline applies to the charter too):
the sentence "not a supporting external system" attributed to `docs/INFRASTRUCTURE.md` exists
nowhere in the repo — that file is descriptive ops documentation (self-declared,
`docs/INFRASTRUCTURE.md:1`) making no architectural-status claim at all; the Integration Fabric
Contract defines **eleven** integration classes, not ten (the acquisition-source class landed
2026-07-02 via #2794, `docs/INTEGRATION_FABRIC_CONTRACT.md:48`); and the audit baseline had to be
re-pinned to `origin/main` mid-pass after the local checkout proved five commits stale.

---

## 1. System of Interest

**Definition (15288 overlay).** The Mimer SoI is the local-first cognitive-prosthesis software
system: the runtime (`app/`, `yggdrasil_runtime/`), its contracts and schemas, its system-owned
durable artifacts (companion notes, receipts, governance records), and its rebuildable machine
surfaces (object store, indexes, embeddings, outbox) — the three nested roles of
`docs/COGNITIVE_PROSTHESIS_CHARTER.md:25-40` read as one system.

**Boundary refinements the existing docs imply but never state:**

- **The human is not a component.** The human is the operator, the authority locus, and the
  principal stakeholder in the operational environment (`docs/foundation/00-yggdrasil-doctrine.md:24-39`,
  `docs/PROJECT_KERNEL.md:11`). Human memory is explicitly "not stored in the system"
  (`docs/COGNITIVE_PROSTHESIS_CHARTER.md:117`).
- **Vault content is custodied, not owned.** The human-authored Markdown corpus is an information
  artifact under human authority that must remain "comprehensible beyond the lifespan of any one
  implementation" (`docs/PROJECT_KERNEL.md:11`) and readable "with or without the system running"
  (`docs/COGNITIVE_PROSTHESIS_CHARTER.md:30-32`). In 15288 terms: the vault *surface* (format
  contract, catalog projection, write-guard discipline) is a SoI responsibility; vault *content
  authority* sits outside the SoI with the human. This is exactly the existing kernel rule
  restated — nothing changes.
- **What it is NOT** is already well-owned: `docs/COGNITIVE_PROSTHESIS_CHARTER.md:191-204` (not
  cloud-first, not black-box, not multi-user, not a methodology, not vendor-locked) and
  `docs/PROJECT_KERNEL.md:13-20`. The overlay adds no new exclusions.

**Verdict:** conform. The SoI is well-defined in substance; the overlay contributes only the
term and the two boundary refinements above (SBI-1).

## 2. Enabling systems and external systems

15288 distinguishes systems that support the SoI's *lifecycle* (enabling systems) from systems the
SoI *interoperates with in operation* (external systems in the operational environment). The repo
already uses the former term — once: the Builder System is "the continuous-development enabling
system" (`docs/architecture/SBS_OPERATING_MODEL.md:75`, `:84`). The category exists; it was applied
to development tooling and never to operational infrastructure. That single omission produces every
infrastructure-classification contradiction found:

- Ollama: "optional local or remote LLM/embedding provider" outside the repo boundary
  (`docs/ARCHITECTURE.md:109`) *and* a first-party compose service with healthcheck and volume
  (`docker-compose.yaml:16-31`).
- Postgres/pgvector: listed under extension fabric as "runtime persistence/index implementations"
  (`docs/MODULAR_ARCHITECTURE.md:58`) *and* as an "external durable store" integration
  class (`docs/INTEGRATION_FABRIC_CONTRACT.md:41`) *and* an unlabeled service
  (`docs/INFRASTRUCTURE.md:17`).
- Colima, Tailscale, the host gateway processes: described operationally
  (`docs/INFRASTRUCTURE.md:15`, `ops/host-setup/README.md:7-14`,
  `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:16`) with no architectural status anywhere.

**Resolution principle (the overlay's core rule).** The *port/adapter is always a SoI element*;
the attached thing's classification follows its lifecycle role:

| Classification | Meaning | Members (evidence) |
| --- | --- | --- |
| SoI component | Ships inside the system; versioned with it | `app/`, `yggdrasil_runtime/`, schemas, companion-note surface; embedded libraries incl. TTS engines (`requirements-tts.txt:8-9` — pip deps in the runtime image) |
| COTS system element (deployed configuration) | Third-party product the SoI's own deployment provisions and supervises; replaceable behind a port, but part of the deployed system | Postgres/pgvector instance (`docker-compose.yaml:3`, behind PDM `StorePort`, `app/stores/base.py`); Ollama *when run as the compose service* (`docker-compose.yaml:16-31`) |
| Enabling system | Supports lifecycle stages; not part of the operating system-of-interest | Builder System incl. GitHub/CI (`docs/architecture/SBS_OPERATING_MODEL.md:75,84` — already settled); Docker/Colima (`docs/INFRASTRUCTURE.md:15`); Tailscale mesh + host provisioning (`ops/host-setup/README.md:7-14`); ops/start scripts (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:522` names them "deliberately outside the SBS") |
| External system (operational environment) | Independently operated/managed; the SoI interoperates via contracts | Obsidian (`docs/INTEGRATION_FABRIC_CONTRACT.md:34` — dual-class by design); iCloud/sync transports (`:42` — "operational plumbing only"); cloud LLM/embedding APIs incl. Gemini fallback (ADR-0023); acquisition sources (`:48`); telemetry consumers (`:46`); *Ollama when reached as a host/remote service* (`docs/ARCHITECTURE.md:109`) |

Ollama legitimately appears twice — the classification attaches to the *deployment binding*, not
the product name, which is precisely why a name-based table can't answer it and a classification
column can (SBI-2). Note the trust posture is orthogonal and already settled: whatever the
classification, external components are "mechanisms, not authority"
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1339`; `docs/INTEGRATION_FABRIC_CONTRACT.md:90-96`;
`docs/SECURITY_TRUST_BOUNDARIES.md:31`). The IFC's word "external" describes trust/control posture,
not 15288 location — the overlay should say so in one sentence.

**Allocated-architecture status (seed hypothesis 4b, skeptic-verified).** The allocation chain
exists *piecewise*: boundary→module in the register's "Current modules" column
(`docs/architecture/SBS_BOUNDARY_REGISTER.md:28-44`), module→container→host in the deployment
matrix (`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:28-67`, created 2026-06-29 precisely
because "the system had no deployment source-of-truth", `:13`) and compose. What is missing is the
*composition* (deployment docs contain zero SBS codes) and, decisively, the classification layer
above. The recommendation is therefore **not** a new allocation table: it is one classification
column/section extending `docs/ARCHITECTURE.md :: System Context` (or
`SBS_OPERATING_MODEL.md` §3), referencing — not duplicating — the register and deployment matrix,
explicitly non-SBS-owned (the register itself disclaims allocation readings,
`SBS_BOUNDARY_REGISTER.md:16-17`), and sequenced against deployment epic #2655 S5/S7, which is
about to replace every deployment unit it would cite
(`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:146-156`).

**Dual-role hazard (named, deferred).** The same infrastructure can be an enabling system (it runs
the SoI) *and* a domain of interest the SoI provides capability about (mapping, documenting,
monitoring, acting on the operator's environment). Where that happens, EXE/OEF develop a
self-reference: the system observes and actuates the platform it depends on (the EXE charter's
external-action surface and OEF's observation surface are the two attachment points,
`docs/boundaries/EXE.md:21-24`, `docs/boundaries/OEF.md:22-24`). This audit names the hazard and
its attachment points and **defers the stance** to the companion thread
(`FABLE5_PROMPT_INFRA_DOMAIN_AND_MCP_TOPOLOGY.md`), per the review brief's scope split. The MCP
server/registry topology question is likewise deferred there.

## 3. "System of Systems" — term audit (skeptic-verified)

**Finding.** Thirteen docs use the term (full inventory verified); the flagship usage frames the
internal 8-subsystem decomposition as an SoS while stating those subsystems are "conceptual
decompositions of the same single local-first runtime… not separate deployments, services, or
processes" (`docs/MODULAR_ARCHITECTURE.md:26`). Every recognized SoS taxon requires
constituents that retain independent operability and usefulness; this fails all of them, including
directed SoS. The target SBS repeats the term for a hierarchical decomposition
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:272`, `:2099`) — a hierarchical system/subsystem breakdown is
the textbook contrast case to SoS. `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md:97-101`
confirms what the term actually means here: "modularity with replaceability, not one monolithic
agent runtime."

**Scoped correctly after adversarial review:** no SoS exists *within the SoI boundary*. Outside it,
one usage has a defensible INCOSE reading — `docs/ARCHITECTURE.md:198`'s "small system-of-systems
arrangement" describing the operator's assembled environment (Yggdrasil + Obsidian + iCloud:
independently operated, independently useful constituents jointly delivering an emergent
capability; a collaborative/virtual SoS reading is legitimate, and whether to adopt it is an SoI
boundary *choice*, not an error).

**Recommendation (extend + reshape-routed):**
- *Extend:* add a `System of Systems` entry to `docs/GLOSSARY.md` (none exists today) and a
  one-paragraph overlay note in the spine doc stating: the internal usage is colloquial for
  "modular, authority-separated single system"; the intent (ADR-0015's modularity commitment) is
  preserved, not overruled; the one INCOSE-defensible reading is the operator's assembled
  environment.
- *Reshape (routed, not enacted):* renaming `docs/MODULAR_ARCHITECTURE.md` and rewording
  `docs/DESIGN_PRINCIPLES.md:115-119` (§9 "System-of-Systems Thinking" — which actually describes
  independent evolution speeds, i.e. volatility isolation) are CES/ADR decisions (owner question
  Q2). The audit recommends *against* a near-term rename: thirteen referencing docs and the reading
  paths make the churn cost real, and the overlay note removes the ambiguity at zero rename cost.

**Constituent-independence test applied (seed hypothesis / review brief §5.3):**

| Candidate | Operational independence | Managerial independence | Verdict |
| --- | --- | --- | --- |
| 8 spine subsystems / 14 SBS boundaries | No (`MODULAR_ARCHITECTURE.md:26`) | No | Subsystems, not constituents |
| Builder System | Partial | Same operator | Enabling system (already settled, `SBS_OPERATING_MODEL.md:84`) |
| SFC replicas (future) | No — one system's nodes, one operator | No | Distributed system, not SoS (ADR-0020 single-node V1) |
| Obsidian, iCloud | Yes — independent vendors, independently useful | Yes | External systems; *optionally* readable with Yggdrasil as a collaborative SoS at the environment level (`ARCHITECTURE.md:198`) |
| LLM/embedding providers | Yes | Yes | External systems behind EBF adapters; no joint management, no SoS |
| Future home automation / EXE targets | Yes | Yes | The genuine future SoS candidate — when Yggdrasil coordinates independently-owned actuating systems; belongs to the companion-thread stance |

## 4. Integrated system context model

One view, reconciling both taxonomies (this is the model SBI-1 turns into an owned artifact):

```
                        ┌─────────────────────────────────────────────┐
   HUMAN (operator,     │                MIMER SoI                    │   EXTERNAL SYSTEMS
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

Taxonomy reconciliation inside this view: spine Human Surface→HIX; Knowledge & Artifact→HKA(+SIP);
Runtime Projection→PDM+DRI; **Capability→CAO+RCA (the split no doc currently states)**;
Agent/Orchestration→CAO; Governance/Authority→GOV; Integration Fabric→EBF; Observability/Fitness→OEF.
WSP, SFC, MEM, EXE have no dedicated spine ancestor — they are target-state refinements, which is
exactly why the spine must stay a *bridge* (its own claim, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:63`)
and why the crosswalk belongs in `SBS_CURRENT_TO_TARGET_MAPPING.md` as rows, not prose (SBI-3).
Control flows and authority gates are already owned by `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
(canonical control flows, `:1352-1394`) — the context model adds the environment side only.

## 5. Functional decomposition and the FBS question

`docs/architecture/functional-ontology.md` is an object ontology (canonical objects), not a
function tree — it never claimed otherwise. The de-facto functional decomposition lives in
`docs/HUMAN-FLOWS.md`, `docs/AGENT-FLOWS.md`, the charter's cognitive arc
(`docs/COGNITIVE_PROSTHESIS_CHARTER.md:91-110`), `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`, and
`docs/CAPABILITY_CONTRACT_MODEL.md`.

**Implementation-independence check (review brief §5.5):** the kernel-level flow statements are clean;
the known leak is self-admitted — `docs/PROJECT_KERNEL.md:110`: several flow/component docs "embed
implementation details (flags, endpoints, tool names) that the kernel intentionally avoids", with
the de-framework follow-up at `:111` still open. No *vendor* dependence was found in functional
statements (the leak hunt in §7 covers code; flow docs name surfaces and flags, not providers).

**FBS verdict (skeptic-gated): do not introduce an FBS — and do not introduce a function-ID
register either.** This audit's own draft recommendation (a lightweight ID register) was refuted at
the skeptic gate: the question is settled repo record. Closed issue #2409 ("deliver SBS functional
allocation and verification view") explicitly rejected a full FBS and delivered the derivative view
instead — `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` binds every canonical flow to primary/secondary SBS
owners, the SBS-owned interfaces crossed, derived testable requirement(s), verification anchor(s),
and debt/fitness rules (mapping table, `:45-53`), adds verb-level "Functions / subfunctions"
decomposition for the high-risk scenarios (`:61-68`), and guards itself: "This is not a full
Functional Breakdown Structure and not a parallel source of truth" (`:103-105`). Stable function
identifiers already exist in the repo's native idiom (the canonical loop names of
`docs/HUMAN-FLOWS.md` §3; the capability contract's mandated stable Name field,
`docs/CAPABILITY_CONTRACT_MODEL.md:45`; the `doc :: anchor` convention). Synthetic AF-xx/CAP-xx
codes would contradict the owner's human-first-naming stance and create a rot-prone parallel
registry. No recorded incident anywhere attributes a failure to missing function-level
traceability. The genuine residual is verification *maturity*, not function identity — most
flow-map verification anchors read "Manual review now" — and that residual is already owned by
#2781 (invariant synthesis) and the transition-debt register.

Standing recommendation: the SBI-1 overlay cites `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` as the
system's functional-allocation view (conform — a pointer, not a new artifact). Falsifiers that
would reopen the question: a recorded failure traceable to function-level ambiguity; a machine
consumer (CI check or agent tool) that must resolve function keys programmatically; or a future
staleness pass showing the flow map's verification-anchor columns rotting — the last would argue
for a CI consistency check on the *existing* map, still not an FBS.

## 6. SBS evaluation (evaluate, not redesign)

**Completeness.** The 14 boundaries + CES cover the responsibility space; the one structural hole
found since adoption (runtime process lifecycle) was resolved by charter extension into WSP rather
than a new subsystem (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:522-536`) — the decomposition absorbs
gaps without growing, which is the property that matters. Charter coverage is 11/14: HIX, EBF, DRI
remain pending (`docs/architecture/traceability-matrix.md:79`, `docs/boundaries/README.md:59,64,66`).
EBF's absence is the most consequential — it is the SoI edge this audit's overlay attaches to, and
both EXE and SFC charters delegate real responsibilities to it
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1481`, `:522`).

**Cohesion/coupling.** Dependency rules, forbidden dependencies, inversion points, and a
change-impact matrix all exist and are internally consistent
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1413-1483`, `:1532-1579`). No boundary-pair conflation was
found at the contract level. Conform; no change recommended.

**Consistency — where documents and code diverge (all anchored, most already self-tracked):**

| # | Divergence | Evidence | Status |
| --- | --- | --- | --- |
| C1 | SIP's registered runtime module is an embedding/provider wrapper — a responsibility SIP's own charter assigns to DRI and forbids treating as semantic authority | `docs/architecture/SBS_BOUNDARY_REGISTER.md:33` names `app/index/embeddings.py`; `docs/boundaries/SIP.md:32,55-58` | Not self-tracked → SBI-4 |
| C2 | OEF has no runtime module; register anchors it to a hybrid-latency metrics file; `TraceEvent`/`FitnessRule` types exist nowhere in `app/` | `SBS_BOUNDARY_REGISTER.md:43` → `app/fitness/metrics.py`; grep confirms no `class TraceEvent` | Partially self-tracked ("Partial current CI") → SBI-4 note |
| C3 | MEM contract name split: charter + schema say `MemoryItem`, SBS Part 5 + code say `MemoryRecord`; only the latter has code | `docs/boundaries/MEM.md:23`; `schemas/memory-item.schema.json`; `app/agent_memory/memory_record.py:87` | Not self-tracked → SBI-4 (CES glossary) |
| C4 | Charter "calls allowed" contradicts SBS Part 5 dependency table: RCA omits HKA; CAO omits HKA/SIP while SBS grants "HKA read contracts" | `docs/boundaries/RCA.md:49` vs `SYSTEM_BREAKDOWN_STRUCTURE.md:1444`; `CAO.md:47` vs `:1446` | Not self-tracked → SBI-4 |
| C5 | Governed-write invariant absolute in charter, partial in runtime: only production EXE call site passes `decision_token=None`; MEM promotion module never touches GOV | `docs/boundaries/GOV.md:66`; `app/orchestrator/executor.py:340`; `app/agent_memory/promotion.py:1-18` | Self-tracked: D2/D5/D6 (`SBS_TRANSITION_DEBT.md:24-28`) — verify-enforcement confirms the debt register is truthful |
| C6 | PDM storage-leak failure mode is live: direct `psycopg` + raw SQL in an API route and a vector module outside PDM ports | `app/api/routes/search.py:6,18,41-46`; `app/store/vector_store.py:5,20,27-38`; charter names exactly this at `docs/boundaries/PDM.md:82` | Self-named failure mode; no debt row → SBI-4 (add to debt register, mechanical) |
| C7 | Docs still present the legacy `app/llm/*` provider surface as canonical: `app/llm/adapter.py` has zero runtime importers (cited as the provider surface by `docs/INVENTORY.md:22-25`), and `docs/LLM.md:31` + `docs/EMBEDDINGS.md:227` present `app/llm/embeddings.py::PROVIDER_REGISTRY` as the adapter registry — while the live canonical access layer is `app/components/llm/` and an architecture test enforces the split the docs don't describe | `docs/INVENTORY.md:22-25`; `docs/LLM.md:31`; `docs/EMBEDDINGS.md:227` vs `docs/COMPONENTS.md:95`; `tests/architecture/test_import_rules.py:104-119` | Not self-tracked → SBI-4 |
| C8 | WSP charter claims a single governed context binding; runtime resolves vaults independently per process | `docs/boundaries/WSP.md:18-19` vs D13/D14 (`SBS_TRANSITION_DEBT.md:35-36`) | Self-tracked |

**Term-level note (seed hypothesis 4a):** the repo's "SBS" is an authority/bounded-context
decomposition, deliberately "not a service decomposition" (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:44`).
Under 15288 an SBS is a physical/product breakdown, so the *term* collides while the *content* is
sound and deliberate. Verdict: keep the name (it is load-bearing across the register, mapping,
debt, fitness docs and the issue template), and let the SBI-1 overlay state the difference in one
sentence. Renaming would be a high-churn reshape with no information gain.

**Enforcement verification of the three settled positions (review brief §2):**

1. *Standards/MCP are adapters, not ontology* — **holds in code.** Zero provider-SDK imports in
   `app/` and `yggdrasil_runtime/` (no `anthropic`/`openai`/`google.generativeai`/`ollama`/
   `litellm` imports; egress is `httpx`/`requests` against configurable base URLs,
   `app/services/llm.py:45`). Every `mcp` string is a tool-id/kind-tag at the doc-assigned adapter
   tier (`docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md:3`; `app/planner/schema.py:12`).
   Model-name literals exist only as config defaults in settings/adapter modules
   (`app/settings/models.py:194,203`; `app/components/llm/router.py:76,80`) — consistent with
   config-as-product. Residuals: `OllamaDeliberationAgent` as a class name in the Agentic-Lab
   reasoning path (`app/reasoning/provider.py:98-100`) and an undocumented tier for `app/tts/` —
   cosmetic, D8 already tracks the vigilance obligation (`SBS_TRANSITION_DEBT.md:30`).
2. *Infrastructure is not the architecture's identity* — **holds in contracts**
   (`SYSTEM_BREAKDOWN_STRUCTURE.md:124`), with the classification gap of §2 as the only residue.
3. *Local-first; providers never semantic authority* — **holds**; enforced in trust-boundary terms
   (`docs/SECURITY_TRUST_BOUNDARIES.md:31`) and the IFC authority rule
   (`docs/INTEGRATION_FABRIC_CONTRACT.md:90-96`). One governance gap worth a debt row: the remote
   MCP multiplex seam falls back silently on remote failure and has no admission allowlist
   (`docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md:229-243`, `:235`) — legible-degradation
   is a kernel constraint (`MODULAR_ARCHITECTURE.md:68`) and silent fallback strains it.

## 7. Integration system

Tier separation, confirmed and named (review brief §5.7):

- **Integration responsibility** — the class taxonomy + contract fields + authority rule
  (`docs/INTEGRATION_FABRIC_CONTRACT.md:36-50, 52-64, 86-96`): owns *what may attach and on what
  terms*. Eleven classes (the review brief said ten; the eleventh, acquisition source, added
  2026-07-02 by the taxonomy-revisit rule — evidence the taxonomy self-extends correctly).
- **Connector responsibility** — per-adapter contracts (tool/MCP, A2A, LLM, embeddings, cloud
  connectors; named at `docs/INTEGRATION_FABRIC_CONTRACT.md:3` and `:103`).
- **Protocol implementations** — MCP sits here and only here: a `kind` literal among
  `mcp|internal|cli` (`app/planner/schema.py:12`), descriptor registry + policy gate
  (`docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md:22-36,183-194`). Confirmed protocol/
  technology tier, not architecture tier (doctrine §7, ADR-0036:23-25).
- **Technology choices** — provider identity as config strings (`docs/LLM_ROUTING.md:23`), swap
  behind registry (`docs/EMBEDDINGS.md:227`).
- **Lifecycle management** — the deliberate gap: no runtime integration registry
  (`docs/INTEGRATION_FABRIC_CONTRACT.md:102`), provider identity/versioning assigned to EBF
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:717`), which has no charter. Acceptable while integration count
  is small; the EBF charter (SBI-7) is the right container for it, not a new mechanism.
- **Connector governance** — tool policy + egress review addendum
  (`docs/security/AGENT_TOOL_EXECUTION_SECURITY_ADDENDUM.md:37`); the silent remote-multiplex
  fallback noted in §6 is the one hole.

## 8. Requirements / SRS coverage

Twenty-axis map (verdicts: **W**ell-specified / **S**cattered / **A**bsent; anchors abbreviated —
full anchors in the explorer evidence retained in session transcript, spot-verified):

| Axis | V | Home(s) |
| --- | --- | --- |
| Mission | W | `PROJECT_KERNEL.md:9-11`; charter §1 |
| Purpose | W | charter §§1-2; `HUMAN-FLOWS.md` |
| Stakeholder needs | W | `docs/CONCEPTS/USER_NEEDS_MODEL.md`; kernel §2 |
| System objectives | W | kernel §3; context packet |
| Operational concept | S | split across `ARCHITECTURE.md`, `HUMAN_FLOW_TO_RUNTIME_MAP.md`, `STATUS.md` — no single ConOps owner |
| System context | W→ | `ARCHITECTURE.md:95-110` (repo-boundary vocabulary; SBI-1 upgrades to 15288 vocabulary) |
| Functional requirements | S | flows + `CORE_CONTRACT.md` + charter — no consolidating surface |
| Non-functional requirements | **A** | fitness functions exist (`ARCHITECTURE.md:144-148`); no NFR targets anywhere |
| Architectural constraints | W | `ARCHITECTURE.md:107-110`; `DESIGN_PRINCIPLES.md`; SBS |
| Design principles | W | `DESIGN_PRINCIPLES.md` (11 principles: 1, 2, 2A, 2B, 3-9) |
| Assumptions | S | strewn across security docs, spine, ADRs |
| External interfaces | W | `INTEGRATION_FABRIC_CONTRACT.md` |
| Supporting systems | S | `DEPENDENCIES.md`, `ENVIRONMENTS.md`, compose — the §2 classification gap |
| Quality attributes | S | fitness rules, invariant tests, security docs — no QA register |
| Verification strategy | W | `Verify:` convention (`docs/development/DEV_WORKFLOW.md:224-270`; `.codex/skills/_shared/ISSUE_CONTRACT.md:53-72`); `TESTING.md` |
| Lifecycle | W | `ENVIRONMENTS.md`; `RELEASE_CHANNELS/`; `OPERATIONS.md` |
| Maintainability | S | CES practice + principles — framed as stewardship, never as a requirement |
| Scalability | **A** | single-user scope statements exist (`ARCHITECTURE.md:404` etc.); *no doc states the omission of scale/perf budgets is deliberate* — the intent is real but unrecorded |
| Knowledge preservation | W | ADR-0017; SBS HKA; `OPERATIONS.md` recovery |
| AI governance | W | `AGENT-FLOWS.md`; ADR-0019; `guardrails.md` |

Cross-cutting findings: **no document self-identifies as an SRS/requirements baseline** (repo-wide
grep, zero hits); the traceability matrix traces 18 *doctrine* rows — invariants, not requirements
axes (`docs/architecture/traceability-matrix.md:39-60`); requirement→test binding exists only at
issue granularity via `Verify:` markers (strong, but issues are transient artifacts);
`docs/PRIVACY.md` covers the local-only posture and defers real compliance mechanics to a
hypothetical cloud deployment (last reviewed 2026-02-05).

**Recommended revisions (not an SRS draft):** one thin SRS index that maps the twenty axes to owner
docs (most cells already filled per the table above), plus three owner decisions: (Q1) adopt an NFR
section or record deliberate absence; (Q5) where the index lives; and one sentence somewhere owned
recording that scale/perf budgets are deliberately absent by single-user choice — currently that
rationale exists only in owner memory. SBI-5.

## 9. Architecture principles

The 11 principles hold up well under the 15288 lens; most candidate "gaps" turn out to be owned
elsewhere: requirement-traceability discipline is doctrine §4 ("a doctrine statement with no
contract/test path is philosophy", `docs/foundation/00-yggdrasil-doctrine.md:107`);
boundary-first/contract-first cover architecture description discipline. Two genuine residues:

- **Enabling-system boundary** as a principle — the Builder/Product split exists operationally
  (`SBS_OPERATING_MODEL.md` §3) but no design principle states "development machinery and
  operational infrastructure never define product architecture." Cheap extend, bundled with SBI-1
  (a sentence, not a new principle document).
- **§9 "System-of-Systems Thinking"** describes volatility isolation, not SoS (§3 above). Rewording
  is reshape-routed (Q2/Q4); the glossary note de-risks it meanwhile.

No new principles are recommended beyond these — consistent with the owner's
human-first-over-compliance-machinery stance.

## 10. Future evolution

The kernel/extension-fabric split plus the SBS change-impact matrix
(`SYSTEM_BREAKDOWN_STRUCTURE.md:1532-1579`) and 2030 stress tests (`:1912-2093`) cover model,
provider, storage, retrieval, memory, agent-runtime, UI, and Obsidian-removal change vectors, and
the §7 evidence (string-config providers, registry dispatch, zero SDK imports, conformance tests)
shows the absorption machinery is real, not aspirational. The taxonomy-revisit rule demonstrably
fired once (acquisition source, #2794). Weakest evolution surface: deployment (single bind-mounted
checkout across all three channels, self-flagged anti-pattern,
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:15,52`) — already owned by epic #2655; no new
recommendation beyond sequencing SBI-2 after it.

---

## 11. Invariant extraction

Extends `docs/testing/invariant-tests.md` semantics; no competing registry. Categories: MUST
(fail-loud runtime) / GATE (CI-blocking) / DOCTOR (read-only reconciliation).

| ID | Invariant | Category | Status |
| --- | --- | --- | --- |
| INV-SB1 | No provider SDK imports or vendor types outside the adapter tier | GATE | Exists — keep (`tests/architecture/test_import_rules.py:104-119`) |
| INV-SB2 | Every `SBS_BOUNDARY_REGISTER.md` module anchor must not fall inside its own boundary's exclusion list | DOCTOR | New (would have caught C1/C2) |
| INV-SB3 | Every deployed runtime element (compose service, host process) carries exactly one lifecycle classification (SoI component / COTS element / enabling / external) | DOCTOR | New — after SBI-2 |
| INV-SB4 | Authority-bearing side effects carry a DecisionToken and produce an AuthorityReceipt | GATE (target MUST) | Violated today (`app/orchestrator/executor.py:340`); owned by D2/D6 — keep register ownership, no new machinery |

Minimal kernel: INV-SB1 + INV-SB3 carry this audit's claims; SB2 is defense in depth; SB4 is
restated existing debt, listed for completeness only.

## 12. Research-question resolutions (charter §4 seed hypotheses)

| RQ | Verdict |
| --- | --- |
| 1. SoS misuse | Confirmed for the internal decomposition; scoped by skeptic — one defensible environment-level reading (`ARCHITECTURE.md:198`). Retire-by-overlay, rename reshape-routed. §3 |
| 2. Two taxonomies unreconciled | Confirmed; no row-level crosswalk exists; Capability→CAO+RCA split undocumented. §4, SBI-3 |
| 3. Adapter vs external-thing conflation | Premise mis-quoted (sentence nonexistent); real inconsistency confirmed across spine/IFC/ARCHITECTURE; resolved by lifecycle-role classification; dual-role hazard named and deferred. §2 |
| 4a. "SBS" term category error | Real at term level, deliberate at content level; keep name + overlay sentence. §6 |
| 4b. Allocated architecture missing | Refuted as stated (exists piecewise); missing = composition + classification column; scoped recommendation. §2 |
| 5. No SRS / scattered requirements | Confirmed; 20-axis map; index overlay + 3 owner decisions. §8 |
| 6. FBS value | Rejected — settled by closed #2409: `HUMAN_FLOW_TO_RUNTIME_MAP.md` already *is* the functional-allocation view (flow → SBS owner → derived requirement → verification anchor, with subfunction decomposition for high-risk scenarios); this audit's draft ID-register alternative was itself refuted at the skeptic gate; the residual is verification maturity, owned by #2781. §5 |

## 13. SBS-reconciliation section (binding)

Per-claim classification against `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` + `docs/architecture/SBS_*`:

| Claim / recommendation | Classification |
| --- | --- |
| SoI definition + human/vault boundary refinements (§1) | **Conform** — restates kernel/charter/doctrine in 15288 vocabulary |
| Lifecycle-role classification of infra + classification column (§2, SBI-2) | **Extend** — new non-SBS current-reality view; touches no boundary, no authority rule |
| Dual-role hazard naming (§2) | **Conform** (naming only; stance deferred to companion thread) |
| SoS glossary entry + overlay note (§3) | **Extend** — glossary + one paragraph; preserves ADR-0015 intent |
| Renaming spine doc / rewording DESIGN_PRINCIPLES §9 (§3, §9) | **Reshape — routed** to CES/ADR + owner (Q2/Q4); not enacted |
| Spine↔SBS crosswalk rows incl. Capability→CAO+RCA (§4, SBI-3) | **Extend** — completes `SBS_CURRENT_TO_TARGET_MAPPING.md`'s own charter |
| Register misanchor fixes C1/C2, calls-allowed sync C4, debt row for C6, doc fix C7 (§6, SBI-4) | **Conform** — corrections the register/charter framework already demands |
| `MemoryItem`→`MemoryRecord` name reconciliation (§6, SBI-4) | **Extend** — CES glossary decision; whichever name wins, routed through CES practice |
| "Keep the SBS name, add overlay sentence" (§6) | **Conform** |
| SRS index + NFR/scale-budget statements (§8, SBI-5) | **Extend** — new index surface; no owner doc loses authority |
| Functional view: cite `HUMAN_FLOW_TO_RUNTIME_MAP.md` as the functional-allocation view in the overlay; no FBS, no ID register (honors settled #2409) (§5) | **Conform** — pointer only |
| Enabling-system principle sentence (§9) | **Extend** |
| EBF/HIX/DRI charter completion (SBI-7) | **Conform** — already-tracked #2533-line work |

No reshape is enacted by this audit. Reshape items exist only as routed proposals above.

## 14. Reconciled backlog handoff (§7.8 — input to `feature-breakdown`)

Reconciliation notes first (searched: epic #2778 + RESEARCH tasks, SBS stewardship plan #2337/#2355
lines, #2825, #2535 (closed), sibling doc-audit Wave-B, companion infra thread):

- **#2778 epic**: RESEARCH-02 (#2780, closed) and RESEARCH-04 (#2782, open) carry the same binding
  SBS-reconciliation clause this audit used; **#2785 (Architectural Constitution, runs last) must
  consume SBI-1's overlay vocabulary** — extend #2785's input list rather than duplicating
  principles work there. SBI tasks create no parallel research hub; they hang off this audit.
- **#2825** (ARCHITECTURE.md `context_dimensions` owner-gap): absorbed as a *sibling*, not
  duplicated — SBI-2 edits the same `docs/ARCHITECTURE.md` §System Context region; the
  feature-breakdown pass should sequence SBI-2 after (or bundle review with) #2825 to avoid
  double-editing one section in parallel.
- **Sibling doc-audit Wave-B** (`docs/audits/DOC_STALENESS_CONSOLIDATION_2026-07-02.md:105-106`):
  the deferred `schemas/README.md` + `ops/host-setup/README.md` index rows and the index-authority
  pass are absorbed into SBI-5 (they are SRS-adjacent index work; a second index pass would collide).
- **SBS stewardship** (`SBS_OPERATIONALIZATION_PLAN.md`): owns enactment of any reshape (Q2/Q4);
  SBI-4's register fixes are Phase-1-mapping-hygiene consistent with its charter — extend, no new plan.
- **Companion thread** (`FABLE5_PROMPT_INFRA_DOMAIN_AND_MCP_TOPOLOGY.md`): owns the dual-role
  stance and MCP topology; SBI-1 names and links, decides nothing.
- **#2655 deployment epic**: SBI-2 is sequenced after S5/S7 (or explicitly re-verified against the
  pinned-image topology) so the classification column describes the surviving topology.

Dependency-ordered tasks (each with a `Verify:`-able acceptance kernel):

| ID | Task | Depends on | Verify: |
| --- | --- | --- | --- |
| SBI-1 | 15288 context-layer overlay: SoI definition (§1), lifecycle-role classification rule (§2), integrated context model (§4), SoS glossary entry + spine overlay note (§3), enabling-system principle sentence (§9), and a pointer naming `HUMAN_FLOW_TO_RUNTIME_MAP.md` as the functional-allocation view (§5). One doc under `docs/architecture/`, linked from spine + SBS + GLOSSARY | — | doc exists with the five sections; `docs/GLOSSARY.md` has a System-of-Systems entry; `DOCS_INDEX.md` row present; spine doc links the overlay note; overlay names the flow map as the functional-allocation view |
| SBI-2 | Infra classification column/section extending `docs/ARCHITECTURE.md :: System Context`: one row per deployed element (db, ollama, api, worker, watcher, companion-ui gateways, Colima, Tailscale, GitHub, iCloud) with SoI/COTS/enabling/external class; resolves the Ollama dual-listing explicitly; references register + deployment matrix | SBI-1; sequence vs #2655 S5/S7 and #2825 | every service in `docker-compose.yaml` and every host process in `DEPLOYMENT_AND_ENVIRONMENTS.md:28-67` has exactly one classification row; Ollama's two bindings both classified |
| SBI-3 | Spine↔SBS crosswalk: 8 rows (one per spine subsystem) in `SBS_CURRENT_TO_TARGET_MAPPING.md`, incl. Capability→CAO+RCA | SBI-1 (vocabulary) | all 8 spine names appear as row labels mapping to SBS codes; Capability row names both CAO and RCA |
| SBI-4 | Register/charter hygiene: fix SIP anchor (C1), annotate OEF anchor (C2), reconcile `MemoryItem`/`MemoryRecord` via CES glossary (C3), sync charter calls-allowed with SBS Part 5 (C4), add debt row for live PDM leak (C6), mark `app/llm/adapter.py` superseded in LLM/EMBEDDINGS/INVENTORY docs (C7) | — | `SBS_BOUNDARY_REGISTER.md:33` no longer anchors SIP to an embeddings module; grep for `app/llm/adapter.py` in docs returns only superseded-marked references; one contract name for MEM in charter+schema+SBS |
| SBI-5 | SRS index overlay: 20-axis → owner-doc map; record deliberate absence of scale/perf budgets; absorb Wave-B index rows (`schemas/README.md`, `ops/host-setup/README.md`) + index-authority pass; surface Q1/Q5 to owner | SBI-1 | index doc exists w/ 20 rows; `DOCS_INDEX.md` has rows for `schemas/README.md` + `ops/host-setup/README.md`; a sentence in an owned doc records the deliberate scale-budget absence |
| SBI-7 | Complete pending boundary charters (EBF first — the SoI edge; then HIX, DRI), extending the existing #2533-line tracking, not a new hub | — | `docs/boundaries/EBF.md`, `HIX.md`, `DRI.md` exist; `docs/boundaries/README.md` shows 14/14; traceability-matrix pending note removed |
| SBI-8 | Owner-gated reshape bundle: spine-doc rename decision, DESIGN_PRINCIPLES §9 rewording — CES/ADR route | SBI-1 (Q2/Q4 answered) | an ADR (or explicit owner decline) exists for each |

SBI-6 is deliberately not allocated: the FBS / function-register question resolved to "do nothing"
at the skeptic gate (§5); the surviving pointer folds into SBI-1. The gap in the ID sequence is
kept so cross-references in review threads stay stable.

## 15. Open architectural questions requiring owner decisions

- **Q1 — NFR posture.** Adopt a minimal NFR section (latency/availability/durability targets for
  the prosthesis loop) or record "no quantitative NFRs by design at single-user scale"? Both are
  legitimate; today neither is stated. (Consequence of silence: fitness functions have no targets
  to check against, and future contributors re-litigate it.)
- **Q2 — SoS naming.** Keep `MODULAR_ARCHITECTURE.md` title with the overlay note
  (recommended: zero churn, ambiguity removed), or rename via CES/ADR (13 referencing docs churn)?
- **Q3 — Dual-role infrastructure stance.** Named here, decided in the companion thread
  (`FABLE5_PROMPT_INFRA_DOMAIN_AND_MCP_TOPOLOGY.md`) — listed so the decision has a visible home.
- **Q4 — DESIGN_PRINCIPLES §9.** Reword "System-of-Systems Thinking" → volatility-isolation
  language now, or leave until the next principles revision? (Reshape either way.)
- **Q5 — SRS index home.** New `docs/REQUIREMENTS_INDEX.md` vs a section in `DOCS_INDEX.md` vs
  extending the traceability matrix. Recommendation: separate thin index (the traceability matrix
  deliberately traces doctrine, not requirements; DOCS_INDEX was just slimmed by #2830).
