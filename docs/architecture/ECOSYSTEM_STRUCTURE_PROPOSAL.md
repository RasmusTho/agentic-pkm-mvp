State: Advisory design proposal (Fable-5 architecture pass, 2026-07-04). Design only — no code, no shipped schemas, no GitHub work. Every load-bearing claim carries an SBS reconciliation tag (`[conform]` / `[extend]` / `[reshape]`); every `reshape` is a routed proposal to the owner via CES/ADR, never enacted here. Where this proposal and an owner doc disagree, the owner doc wins until the owner decides otherwise.
Doc role: Ecosystem structure proposal (advisory)
Inputs: docs/SYSTEM_BREAKDOWN_STRUCTURE.md; docs/boundaries/** (14 charters + CES); docs/foundation/00-yggdrasil-doctrine.md; docs/architecture/system-context-overlay.md; docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md; docs/HEIMDAL/** (A1/A3/A4/A5) + ADR-0043 (historical proposed input; PR #2888 closed unmerged — the ADR-0044–0047 reconciliation is current); docs/architecture/ecosystem-federation.md (RESEARCH-08, merged); docs/KNOWLEDGE_ACQUISITION/README.md; docs/DESIGN_PRINCIPLES.md; docs/MODULAR_ARCHITECTURE.md; ADR-0041; docs/RUNTIME_CORRECTNESS_KERNEL/README.md; docs/testing/invariant-tests.md (referenced).

# Ecosystem Structure Proposal — one breakdown, Heimdal placed

---

## 0. Owner decisions — LOCKED 2026-07-04

The owner reviewed this proposal and locked the eight decisions below. **These override the body
where they differ.** The body (§1–§11) is Fable's analysis of record and is preserved verbatim;
where it recommends "Yggdrasil = the knowledge constituent," read the owner's refinement in OD-1.

**Naming reading key (OD-1):** the owner kept **Yggdrasil = the whole / apex** (their prior
D-NAME-WHOLE) but dissolved Fable's structural objection by *not* splitting the knowledge system.
So throughout §1–§11, **"the knowledge-and-cognition constituent (Fable: Yggdrasil / C1)" = `Mimer`**,
and **"Yggdrasil" = the apex / the whole SoS**. Structure is identical to Fable's recommendation;
only the labels move: Yggdrasil rises to the apex, the current system (code `yggdrasil_runtime/`,
doctrine, SBS, SoI) reverts to its original name **Mimer** (Mímir — the well of wisdom at Yggdrasil's
root). This is a restoration, not an arbitrary rename.

| OD | Decision (locked) |
|---|---|
| **OD-1** | **Yggdrasil = the whole / apex** (world-tree; nothing is metaphorically bigger). **Mimer** = the knowledge-and-cognition constituent (undivided). **Heimdal** = sensor. **Hugin/Munin** reserved (ravens; a future agent-runtime/knowledge split only if it ever passes the constituent test). **Pantheon-per-constituent** naming principle — Norse names for constituents + the ecosystem only; control boundaries keep their 3-letter codes; capabilities keep descriptive names. |
| **OD-2** | Apex framing becomes **primary in current-state docs when Heimdal is *chartered*** (earlier clarity; accept the SoI-doc rewrite churn). |
| **OD-3** | Resolved by OD-1: Mimer is **one** constituent; no Munin/Hugin split. |
| **OD-4** | **Charter the private bindings constituent now (thin):** a contract + a private home + the INV-EF1 burn-down as its backlog. |
| **OD-5** | Promote the **three contracts** (event-bus, identity register, provenance/replay standard) at Heimdal design-acceptance; implementations stay module-lazy. |
| **OD-6** | **Proportional, not maximal isolation.** The raw→published seam and raw-layer access controls are **designed-in from day one** (structural, upgradeable), but Heimdal's raw store does **not** get separate credentials/process/host isolation now — encryption + access control in the shared deployment. See the cross-cutting principle below. |
| **OD-7** | Adopt the naming scheme; carry **OD-1 + OD-3 + OD-7** in **one** superseding/amending ADR against ADR-0043. |
| **OD-8** | **Hold PR #2888**, reconcile it with this structure, land **one** coherent ratification (this structure + Mimer naming + RESEARCH-08 D1/D2/D3 references; D4 orthogonal). |

### Cross-cutting owner principle (new, from OD-6) — applies to ALL systems

> **Uniform privacy/security posture across every constituent; security is good but not primary
> given the low threat model of this infrastructure; cost-efficiency is a first-class constraint
> (storage, compute, tokens are limited); but every system is *designed* with the seam/isolation in
> mind from the start so the posture can be tightened without a redesign if the threat model rises.**

Consequence for this proposal: Heimdal is not privacy-special-cased with heavy isolation; it gets
the same proportional posture as Mimer and every future sibling. The structural seam (§4) stays —
it is cheap to *design* and expensive to retrofit — while the *implementation* isolation is deferred
and proportional. Heimdal's always-on-OFF default, event minimization, and event-triggered decay
(A-docs) directly serve cost-efficiency, not only privacy.

### Status of this doc

Advisory design, decisions locked. **Enactment is not performed here:** the superseding naming ADR
(OD-1/3/7), the #2888 reconciliation (OD-8), the thin bindings charter (OD-4), and the three
substrate contracts (OD-5) are follow-up work, filed via `docs-to-issue` when the owner proceeds.
The `Mimer` code/doc rename (`yggdrasil_runtime/` → Mimer, doctrine/SBS/SoI) is a bounded, mechanical
enactment task, not done by this docs-only proposal.

---

## 0.1 Addenda — owner refinements (2026-07-04, later)

### KAP / acquisition fit (the "YouTube epic")

KAP (Knowledge Acquisition Platform; Phase-2 vertical = YouTube, #2795/#2796–#2801) is a **capability
inside Mimer**, **not** a constituent. It acquires from *external public sources* (YouTube, RSS,
podcasts): no private-observation seam, no independent volatility clock beyond its EBF source
plugins, and it lives in Mimer's runtime + authority chain. `[conform]`

KAP and Heimdal are **symmetric as pipelines, asymmetric as structure**: both end at a hand-off
artifact (KAP → *candidate*, Heimdal → *published event*), both feed the **one** GOV promotion gate,
and both conform to the shared Layer-2 **provenance/replay standard**. So **KAP is the pathfinder** —
it builds the acquire→hand-off→promote backbone *now* (batch, public sources) that Heimdal later
**generalizes** to a streaming sensor. Practical rule for the YouTube epic: build provenance/replay,
the candidate contract, and entity extraction **generalizably** (design as if a second consumer
exists — because it does), even while implementations stay module-lazy (OD-5). KAP's spec phrase
"standalone platform" means a clean, pluggable in-Mimer capability — **not** an SoS constituent; no
demotion, no conflict. Naming: KAP is a *capability* (descriptive name; optional alias **Ratatosk** —
the squirrel carrying messages up and down the tree). `[extend]`

### OD-9 — Canonical entity register (promote the contract early; broad entity scope)

Refines the identity-register decision. The identity substrate is **not just speaker/person
identity** — it is a **canonical entity register** for *people, organizations, projects, places,
devices, and topics*, because the goal is to **link and connect everything** across systems (one
canonical "Acme Corp" that both a YouTube-derived candidate and a Heimdal event reference). It is
the cross-system linking substrate that makes single-source-of-truth work *across* constituents.
`[extend]`

- **Decision (locked):** promote the **entity-register contract + a thin resolution interface now**
  — both KAP (entity extraction) and Heimdal (attribution) are already consumers, so the
  module-lazy "wait for the second consumer" test is already met for the *contract*. The graph
  richness grows on top later; implementation stays proportional (cost-efficiency principle).
- **Ownership:** Layer-2 substrate, owned by no constituent. It owns canonical **entity existence +
  ID**; **SIP** (in Mimer) maps knowledge-artifact identity onto register entities and keeps
  artifact semantic/provenance identity. Register is upstream of SIP; neither forks the other.

### Two-way communication + single-source-of-truth / system-of-record integrity

Fable's "pure producer" framing is refined: Heimdal is the sole producer of the **event stream**
(the fact-plane dependency is one-way), but constituents **communicate bidirectionally through
contracts** (entity lookups, corrections, control/consent, enrichment) — never by reaching into
another's internals (ECO-1). SSoT is preserved by one rule:

> **One system-of-record per domain.** Heimdal is SoR for *observed events*; Mimer/HKA is SoR for
> *durable human knowledge*; the entity register is SoR for *canonical entities*. Every other holder
> is a **rebuildable projection**, never truth. No fact has two owning systems; cross-system
> references are **by ID against the owner's SoR**, never by copy-as-truth. The only path to
> canonical remains the one GOV promotion gate.

Corrections sent *back* to a producer become **new records** (e.g. a correction to a Heimdal event
is a new event — append-only intact, HEIM-1), never in-place edits. **Consequence for the substrate:**
the Layer-2 **event-bus contract must support bidirectional / request-response**, not only
fire-and-forget pub/sub.

- **ECO-11 — One system-of-record per domain.** No domain fact has two owning systems; cross-system
  references resolve by ID against the owning SoR; projections are rebuildable and never canonical.
  Enforcement: Medium — contract + design-review gate. `[extend]`

**Enactment note:** OD-9 (entity-register contract) joins OD-5's substrate-contract promotion set;
ECO-11 and the bidirectional-bus requirement fold into the event-bus + provenance contracts designed
at Heimdal design-acceptance. Still advisory; nothing built here.

---

## 1. Executive summary

**Recommended structure.** The apex is the **Personal Agentic Ecosystem** — an acknowledged System-of-Systems under one human apex authority, governed by contracts (CES/ADR), never by a runtime component. It has exactly three constituents today: **Yggdrasil** (the knowledge-and-cognition system — the current SoI, with all 14 control boundaries + CES intact inside it), **Heimdal** (the sensor — observation → attributed, append-only published events; its raw layer is the innermost private ring), and the **private bindings constituent** (proto; operator-bound configuration, born outside the public repo). Future private siblings (home automation, network) are slots, not builds. A thin **platform substrate** (event-bus contract, identity/entity register, provenance/replay standard, build/CI, container base, host topology) is owned by no constituent; promotion into it is owner-gated. KAP stays a capability inside Yggdrasil. Repo stays a monorepo with a hard internal seam until a named split-trigger fires.

**Recommended answer to "what is Yggdrasil":** Yggdrasil denotes the **knowledge-and-cognition constituent** — the current single system — not the whole ecosystem. This contradicts draft ADR-0043's D-NAME-WHOLE and is deliberately surfaced as owner decision OD-1 with full reasoning (§10).

---

## 2. Recommended structure

### 2.1 The two models, and the third one hiding inside "Model B"

The brief frames a two-way tension; the evidence shows **three** models:

- **Model A** (SBS + ADR-0041 + INCOSE audit): Yggdrasil = a modular *single system*; 14 control boundaries; the internal decomposition is explicitly **not** an SoS (audit §3, settled; the owner paid 27-doc churn to remove that vocabulary).
- **Model B1** (RESEARCH-08, merged): apex = Personal Agentic Ecosystem (acknowledged SoS, target-state, activation-gated); **Yggdrasil = a constituent** (the public knowledge/reasoning system); *no internal boundary is a constituent*; siblings are private-side systems.
- **Model B2** (historical Heimdal A1 + draft ADR-0043 / closed-unmerged PR #2888): **Yggdrasil = the whole**; constituents = Munin (knowledge/memory), Hugin (agent-runtime), Heimdal (sensor). The current reconciliation is ADR-0044–0047.

B1 and B2 agree the ecosystem is an acknowledged SoS with Heimdal as a peer constituent and a public/private seam. They **disagree** on the apex name, on Yggdrasil's referent, and — critically — on whether the knowledge/agent split is a constituent split. This proposal resolves the triangle by taking: the SoS apex from B1/B2 `[reshape → CES/ADR]`, the constituent set from B1 (Yggdrasil undivided) `[conform to audit §3]`, Heimdal's peer status from B1/B2 `[reshape → CES/ADR]`, and Model A unchanged **inside** Yggdrasil `[conform]`.

### 2.2 Apex — Personal Agentic Ecosystem

- **What it is:** an acknowledged SoS: constituents are independently meaningful, independently evolvable, deliberately assembled to serve **one human** (single-user invariant intact; constituent count grows, human count does not). `[reshape → CES/ADR — this is RESEARCH-08 D1 / Heimdal A1 §1, refined; routed, not enacted]`
- **What it is not:** a runtime. Apex authority is exercised through Layer-1 governance: CES stewardship, ADRs, cross-constituent contracts (event contract, identity register, provenance standard, seam invariant). No orchestrator service, no shared mega-server. `[conform — Heimdal A1 §3 Layer 1]`
- **The SoS relation is "acknowledged constituents,"** never "federation" — that word is owned internally by the SFC control boundary and stays there. `[conform]`

### 2.3 Constituents

Each constituent is justified by the four tests the repo's contract-first, module-lazy principle demands: an independent volatility clock, distinct ownership, a distinct failure mode, and a distinct authority posture. Anything failing all four stays inside an existing constituent.

#### C1 — Yggdrasil: the knowledge-and-cognition constituent

- **Purpose (one line):** durable human knowledge, meaning, memory, retrieval, agent cognition, and governed action for one human — the current SoI, unchanged inside.
- **Why it is its own constituent:** it *is* the existing system; its authority posture is unique in the ecosystem (it holds the Human Authority Kernel — HKA/SIP/GOV — and is the only constituent that can make anything canonical); its failure mode is knowledge corruption / hidden authority escalation, which the 14 boundaries exist to prevent.
- **Why it is ONE constituent (no Munin/Hugin split):** the knowledge/agent line is a seam that the load-bearing invariant chains cross constantly — CAO→GOV→EXE→HKA (proposal→authorization→execution→durable write), MEM→GOV→HKA (memory promotion), RCA→CAO (evidence→reasoning), and the entire nine-invariant runtime correctness kernel. RESEARCH-08's own TCD tiebreaker states the rule: *do not split across a seam that invariants must cross*. The INCOSE audit already found every internal boundary fails the constituent-independence test ("Subsystems, not constituents"). Splitting would also orphan 6 of 14 boundaries (see §6, Alternative A). `[conform to audit §3 + RESEARCH-08 claim 4; reshape vs draft ADR-0043's constituent register → routed as OD-3]`
- **Contains:** all 14 control boundaries + CES (see §3), the correctness kernel, and **KAP** as an in-constituent acquisition capability (EBF class 11; ends at candidate; settled precedent). `[conform]`
- **Public/private posture:** code and contracts public (operator-invariant per INV-EF1); all runtime data (vault, stores, receipts) private.

#### C2 — Heimdal: the sensor constituent

- **Purpose (one line):** continuous, consent-gated observation of reality → attributed, timestamped, confidence- and provenance-carrying events; responsibility **ends at a published event**.
- **Why it is its own constituent (all four tests pass):**
  - *Volatility clock:* sensor hardware, capture pipelines, ASR/vision models churn on a clock independent of knowledge-system churn — the fastest-moving surface in the ecosystem.
  - *Ownership:* a pure producer. Every other constituent consumes its stream; it consumes no one's internals. A thing everyone reads from and that reads from no one is a peer source, not a submodule of one reader. `[reshape → CES/ADR — same reshape as Heimdal A1 §1; routed]`
  - *Failure mode:* capture gaps and mis-attribution — categorically different from knowledge corruption, and neither side may take the other down.
  - *Authority posture:* zero semantic authority (a Heimdal event is candidate evidence, never truth — HEIM-8) while holding **custody of the most-private raw data** in the ecosystem. Maximal privacy custody + minimal authority is the inverse of Yggdrasil's kernel; nesting them would smear the seam.
- **Internal shape (sketch, not a 14-boundary clone):** capture adapters (consent-gated) → raw observation layer (encrypted, isolated, CrossScopeFlow-gated reads, bounded hard retention) → minimize/attribute/publish (resolving against the shared identity register) → append-only published stream. Heimdal *instantiates the boundary disciplines* (its own EBF-like adapters, PDM-like raw store, GOV-pattern consent enforcement, OEF-pattern self-observability) without importing or sharing the 14 boundary instances — those are Yggdrasil's internal law, not ecosystem law. `[extend]`
- **What Heimdal does NOT own:** knowledge promotion, memory, agent action, the identity register (shared substrate), the bus (shared substrate), what downstream does with an event.

#### C3 — Private bindings constituent (proto)

- **Purpose (one line):** resolve every operator-bound binding — endpoints, credentials, device inventory, vault labels, host names — that the public tree must not carry.
- **Why it is its own constituent:** the *seam test* — its substance is private (INV-EF1 categories ii–v as content); it cannot live in the public tree at any cost. Ownership/failure/authority: it binds, it never decides; its failure mode is misconfiguration, not corruption. It is "born outside" the public monorepo — not a split, a birth. `[extend — names the proto-constituent RESEARCH-08 already identified]`

#### C4 — Future private siblings (slots, not builds)

Home automation, network/personal infra: sourced OSS where mature upstreams absorb domain volatility (TCD sourcing test), attached via capability contracts through EBF-tier adapters, holding domain authority in their own domains only. Named here so the structure has their slots; nothing is built or chartered by this proposal. `[conform to RESEARCH-08]`

### 2.4 Platform substrate (Layer 2)

Shared mechanisms every constituent needs and none may own. Promotion into this layer is itself owner-gated (R-PROMOTE) and evidence-driven: a mechanism is promoted when the **second** constituent actually needs it — contract-first, module-lazy applied to the substrate. `[extend]`

| Substrate item | Shared vs constituent-owned | Notes |
|---|---|---|
| **Event-bus contract** (envelope, topics, idempotency, delivery/replay semantics) | **Shared (Layer 2)** — the *contract*; the transport implementation is the Heimdal capability window's open design (generalize the DB outbox vs stream-native — D-BACKBONE stays open) | Must generalize, not fork, the correctness-kernel discipline already being built (KERNEL-02 mandatory idempotency, KERNEL-08 topic schema registry, KERNEL-11 handler idempotency) `[extend]` |
| **Identity / entity register** | **Shared (Layer 2)** — owner-decided (D-IDENTITY) | Seam to name explicitly: the register owns *entity* identity (who/what exists — people, places, devices); **SIP keeps** semantic/provenance identity of knowledge artifacts and maps entity references. The register is upstream of SIP; neither forks the other `[extend]` |
| **Provenance / replay standard** | **Shared (Layer 2)** — fixed guardrail | One standard both KAP (acquire→candidate) and Heimdal (observe→publish) conform to; raw evidence immutable + replayable through improved stages `[extend]` |
| **Build / CI skeleton** | **Shared** — constituent-agnostic; per-constituent gates compose onto it | `[conform]` |
| **Container base / runtime image** | **Shared** base + per-constituent compose fragments | `[conform]` |
| **Hardware / host topology** (Tailscale mesh, hosts) | **Shared enabling substrate** — transport and placement, never authority; sensor capture may pin dedicated hardware | `[conform]` |
| **Stores / persistence** | **Constituent-owned** — Yggdrasil's PDM; Heimdal's raw store is a separate instance under PDM discipline | Never a shared database across constituents — a shared store would be a hidden authority channel `[extend]` |
| **Observability** | **Constituent-owned** (OEF per constituent) + one future ecosystem capability: independent observation of a constituent's substrate from outside its failure domain | `[conform to RESEARCH-08 §Dual-role]` |

### 2.5 Where Heimdal and KAP slot in — stated plainly

- **Heimdal = constituent C2**, a peer of Yggdrasil, on the private side of the seam, publishing across it. It is **not** an EBF adapter of Yggdrasil, not a 15th control boundary, and not a subsystem of the knowledge system. From *Yggdrasil's* internal viewpoint, Heimdal's stream nonetheless enters through an **EBF adapter under the Integration Fabric authority rule** — external mechanisms are not authority — exactly like any attached system. Both statements are true at their own level; confusing the levels is the failure mode to guard.
- **KAP = capability inside C1 (Yggdrasil)**, not a constituent: it shares Yggdrasil's runtime, deployment, and authority chain; it has no independent volatility clock beyond what EBF source plugins already isolate; its substance is public-source acquisition (no seam pressure). The symmetry with Heimdal is *contractual*, not structural: both end at a hand-off artifact (candidate / published event), both conform to the shared provenance/replay standard, both feed the **same** GOV promotion gate. `[conform to KAP spec + RESEARCH-08 TCD test 4a]`

---

## 3. The 14-boundary → constituent mapping

**Grouping decision:** all fourteen boundaries + CES remain **inside Yggdrasil (C1)** — they are that constituent's internal decomposition, not ecosystem law. The ecosystem's law is the far smaller cross-constituent contract set (event contract, identity register, provenance standard, seam invariant, governed-promotion rule). The boundaries are not redefined; each row adds only its **ecosystem-facing role**. `[conform — the audit's "subsystems, not constituents" verdict, applied]`

| ID | Boundary | Constituent | Ecosystem-facing role |
|---|---|---|---|
| HIX | Human Interaction & Intent | Yggdrasil | Human surfaces stay per-constituent; the ecosystem has no shared UI. Heimdal's consent/review surfaces are its own, HIX-patterned |
| WSP | Workspace, Scope & Principal Context | Yggdrasil | ActiveContextSet may later bind ecosystem-topology posture (which constituents are attached) — a binding, not new authority `[extend]` |
| HKA | Human Knowledge & Artifact Substrate | Yggdrasil | Terminal target of ALL governed promotion — events and candidates alike become durable knowledge only here |
| SIP | Semantic Identity & Provenance | Yggdrasil | Consumes the Layer-2 entity register; keeps semantic/provenance identity of artifacts; provenance chains resolve back through the shared standard to Heimdal raw evidence |
| GOV | Governance, Policy, Authority & Receipts | Yggdrasil | Its governed-write/DecisionToken/receipt pattern is the *template* the cross-constituent contracts reuse (pattern export, not shared runtime); CrossScopeFlow grants gate Heimdal raw-layer reads |
| EBF | External Boundary Fabric | Yggdrasil | **The ecosystem attachment fabric**: sibling constituents (Heimdal stream, future sibling servers) attach here as adapters under the IFC authority rule |
| PDM | Persistence & Data Management | Yggdrasil | Per-constituent discipline; Heimdal's raw store is a separate PDM-patterned instance, never a shared DB |
| DRI | Derived Representation & Indexing | Yggdrasil | Projections of the event stream are DRI-class: rebuildable from the stream, never truth |
| RCA | Retrieval & Context Assembly | Yggdrasil | Events surface to cognition as candidate evidence in ContextBundles, provenance intact |
| MEM | Machine Memory & Learning | Yggdrasil | Events may spawn memory candidates; promotion semantics unchanged (advisory until promoted) |
| CAO | Cognitive Capability & Agent Orchestration | Yggdrasil | Agents read events as evidence, never authority (HEIM-8); propose only |
| EXE | Capability Execution & Automation | Yggdrasil | Actuation toward siblings/substrate crosses tool policy with the availability-impact declaration (RESEARCH-08); execution never self-authorizes, ecosystem-wide |
| SFC | Synchronization, Federation & Consensus | Yggdrasil | **Intra-constituent distribution only** (replicas, nodes, causal ordering). Never the SoS relation. Sibling interaction is governed by the Tier-0/1/2 rule (RESEARCH-08 D2); Heimdal→Yggdrasil stream consumption is Tier-1 and must carry ADR-0020's delivery/idempotency/replay classification `[conform/extend]` |
| OEF | Observability, Evaluation & Fitness | Yggdrasil | Per-constituent observability; ecosystem-level fitness rules (§9) are OEF-patterned but CES-stewarded; independent substrate observation is a future sibling capability |
| CES | Contract & Evolution Stewardship (practice) | Cross-cutting | **Extends upward**: CES stewards the Layer-1 ecosystem contracts (constituent charters, cross-constituent interface versions, the name register, the seam register) exactly as it stewards Product SBS contracts — still lean, still not runtime `[extend]` |

---

## 4. The public/private seam — where it runs

The seam is **one boundary with three concentric expressions**, not three seams. Sharpest innermost:

1. **Ring 0 — Heimdal's raw observation layer (most private).** Raw capture of reality. Encrypted at rest, isolated, bounded hard retention; reads are policy-gated (CrossScopeFlow grant + receipt) for trusted downstream agents — not human-only, not open. Nothing here crosses outward except by governed grant. `[conform to D-PRIVACY]`
2. **Ring 1 — the raw→published seam (the sharpest line in the diagram).** Only **minimized, attributed, published events** cross by default. This is the seam the sensor exists to hold, and the primary structural reason Heimdal is a constituent: the seam is *between systems*, enforceable by contract and process isolation, rather than a discipline inside one runtime. `[conform to charter FIXED 5]`
3. **Ring 2 — the ecosystem's private data plane vs the public artifact plane (INV-EF1).** Everything running — events, vault content, memory, receipts, bindings — is the private data plane of one operator. The **public artifact plane is the monorepo**: operator-invariant code + contracts for the public-side constituents (strict in product scope; registered exceptions in builder/ops scope; secrets absolute everywhere). The private bindings constituent is the seam's other side made systematic. `[extend — adopts RESEARCH-08 INV-EF1, decision D3; not ratified here]`

Consequences the structure encodes: constituent *code* may be public while its *state* is private; Heimdal's raw store and the bindings constituent are private by substance and can never migrate to the public plane; a published event is private-plane data (ecosystem-internal), not public data — nothing becomes public without a separate, owner-level act.

---

## 5. Event-log vs projection — the data flow

Heimdal extends the repo's settled rule (retrieval is not truth; memory is advisory; projections are rebuildable) **upstream to the point of observation** `[extend]`. The append-only stream is canonical *for what was observed* — never for what is true or known:

```
 reality
   │  consent-gated capture (opt-in per place/session; third parties marked/degraded)
   ▼
 ┌──────────────────────────── HEIMDAL (C2) ────────────────────────────┐
 │  RAW OBSERVATION LAYER (Ring 0: encrypted, isolated, hard retention,  │
 │  CrossScopeFlow-gated reads + receipts)                               │
 │        │ minimize · attribute (Layer-2 identity register)             │
 │        │ confidence + provenance stamped; corrections = new events    │
 │        ▼                                                              │
 │  APPEND-ONLY PUBLISHED EVENT STREAM  ← canonical for "what was        │
 └────────┬──────────────────────────────  observed", immutable ─────────┘
          │  Layer-2 event-bus contract (idempotency, replay, ordering)
          │  ══════ SEAM: only minimized, attributed events cross ══════
          ▼
 ┌──────────────────────────── YGGDRASIL (C1) ───────────────────────────┐
 │  EBF adapter (Tier-1: delivery/replay/idempotency classified)         │
 │        ▼                                                              │
 │  READ-MODELS (all rebuildable from the stream, never truth):          │
 │    DRI  → indexes/projections of events                               │
 │    RCA  → events as candidate evidence in ContextBundles              │
 │    MEM  → memory candidates (advisory until promoted)                 │
 │    CAO  → agents reason over evidence; propose only        (HEIM-8)   │
 │        ▼                                                              │
 │  GOV GOVERNED PROMOTION GATE — DecisionToken · WriteGuard · receipt   │
 │        ▼                                  ▲                           │
 │  HKA durable human knowledge              │ KAP candidates join the   │
 │  (the ONLY canonical store)               │ same gate (acquire→cand.) │
 └───────────────────────────────────────────┴───────────────────────────┘
          │
          └╌╌▶ future siblings subscribe to the same stream (target-state)
```

Load-bearing properties: (a) the stream is upstream of every read-model and downstream of nothing; (b) both acquisition paths (Heimdal, KAP) converge on **one** promotion gate — there is exactly one door to canonical `[conform — fixed invariants 3 + 4]`; (c) attribution errors are corrected by *new* events, never edits `[conform — HEIM-1]`; (d) losing every read-model loses no observed fact; losing the stream loses no accepted knowledge.

---

## 6. Alternatives considered

### Alternative A — "Yggdrasil = the whole" (Heimdal A1 / draft ADR-0043 as written)

Apex = Yggdrasil-as-SoS; constituents = Munin (knowledge/memory), Hugin (agent-runtime), Heimdal (sensor).

*For:* maximal metaphor coherence (constituents hang in the world-tree; the ravens report to the watchman's horn); matches the owner's captured 2026-07-04 in-principle naming decision; "Yggdrasil" keeps naming the biggest thing.

*Against — structural:* the Munin/Hugin constituent split fails the independence test the audit settled. Try to assign the 14 boundaries and 6 are unassignable:

| Munin? | Hugin? | Unassignable (shared spine) |
|---|---|---|
| HKA, SIP, PDM, DRI, RCA?, MEM? | CAO, EXE | **GOV, WSP, HIX, EBF, SFC, OEF** |

Even the "clean" ones argue: RCA exists to feed CAO; MEM is machine memory *for* agents; the governed-write chain (CAO→GOV→EXE→HKA) crosses the split on every durable mutation. Splitting here violates "do not split across a seam invariants must cross" and would force either duplicating GOV/WSP/OEF per constituent or minting a shared runtime core — a fourth thing the model doesn't name.

*Against — referent churn:* hundreds of artifacts (`yggdrasil_runtime/` package, "Yggdrasil doctrine," "Yggdrasil SBS," the SoI definition) use "Yggdrasil" to mean the current single system; shifting the referent up one level makes them all ambiguous or wrong, and reintroduces the sentence "Yggdrasil is a system-of-systems" the day after ADR-0041 paid 27-doc churn to delete it — same words, different referent, guaranteed confusion.

*Verdict:* the metaphor is buyable only at the price of a structurally unsound constituent split or a permanently two-level name. Rejected; surfaced as OD-1 option B because the naming half is genuinely the owner's call.

### Alternative B — "No SoS": Heimdal as a 15th boundary / EBF-attached capture subsystem inside the single system

*For:* smallest possible structure; zero apex machinery; no new governance layer; Model A untouched.

*Against:* fixed invariant 2 says the public/private seam is the **sharpest** boundary and the sensor carries the most-private raw data. A boundary sharper than any internal boundary cannot live *inside* the system whose boundaries it out-sharpens — the raw layer's isolation requirement (separate encryption/credential/process posture, D-PRIVACY) is precisely what internal control boundaries do not provide (they are explicitly "not necessarily runtime services"). It also buries the dependency direction (everyone reads Heimdal; Heimdal reads no one — a peer-source signature), erases the independent volatility clock of capture hardware/models, and contradicts the owner's prior sibling decision. Rejected.

**Why the recommendation beats both:** it is the smallest structure in which every fixed invariant has a *structural* (not merely disciplinary) home — the seam gets a between-systems boundary, the event log gets a pure producer, governed writes keep one gate, the correctness kernel keeps one runtime, and the single human stays apex.

---

## 7. Naming scheme proposal (output; all Norse names free)

Rules first — names never drive structure:

1. **Norse names attach only to constituents and the ecosystem.** Control boundaries keep their 3-letter codes (HIX…OEF, CES); capabilities keep descriptive names (human-first naming). This prevents the alias-drift that produced the Heimdal/OEF collision.
2. **One name register** (carry ADR-0043 §5's register forward, amended per below) remains the collision guard; reassignment requires a superseding ADR.
3. **Environments/vaults stay mutable and never hardcoded** (unchanged).

Recommended assignments (consistent with the recommended structure; final call is OD-7):

| Name | Denotes | Rationale / disposition |
|---|---|---|
| **Yggdrasil** | The knowledge-and-cognition constituent (C1) | Zero-churn continuity with the entire doc/code corpus (`yggdrasil_runtime/`, doctrine, SBS, SoI). Recommended referent — OD-1 |
| **Personal Agentic Ecosystem** | The apex | Descriptive primary name (human-first). A Norse apex alias is *optional and deferrable*; if wanted, mint from the register's free pool (e.g. **Asgard** — the operator's realm) via a small ADR. Do not block structure on it |
| **Heimdal** | The sensor constituent (C2) | Keep — the watchman metaphor is exact, the A-docs already use it, and the observability alias reverts to boundary code **OEF** (that half of ADR-0043 is kept as-is) |
| **Hugin / Munin** | **Reserved, unassigned** | Do not attach to non-constituents. Reserve Hugin for an agent-runtime constituent *if it ever passes the constituent test* (a real split-trigger), Munin likewise for a knowledge-side split. Reserving beats retiring (keeps the raven metaphor available) and beats assigning (avoids names outrunning structure) |
| **Mimer** | Deprecated alias → Yggdrasil's knowledge surface | As ADR-0043 already proposes |
| **Ratatosk** | Optional alias for KAP | The squirrel carrying messages up and down the tree; register already holds it for ingest/pipeline. Cosmetic; take or leave |
| **Private bindings constituent** | Descriptive name for now | Name it in Norse only when chartered (OD-4); candidates from the free pool |

If the owner instead ratifies **Yggdrasil = whole** (OD-1 option B), this scheme still functions with one substitution: C1 needs a new Norse name (Mimir/Munin-class), and the churn plan in Alternative A's cost list must be accepted explicitly.

`[reshape → all naming lands via a superseding/amending ADR against ADR-0043; PR #2888 should be reconciled with this proposal before merge — OD-8]`

---

## 8. Repo topology + split-triggers

**Posture: monorepo with a hard internal seam.** `[conform — Heimdal A1 §4]` Constituent code gets a top-level home (e.g. `heimdal/` beside `app/` + `yggdrasil_runtime/`) with import-boundary enforcement (lint/CI) so the seam is mechanical, not aspirational. Cross-constituent interaction goes through published contracts only.

**Refinement:** the monorepo rule applies to **public-side** constituents. The private bindings constituent is *born outside* the repo — private-by-substance content is never "split out," it never enters. `[extend]`

**Split-triggers** (adopt Heimdal A1's five `[conform]`; any acceptance is owner-gated, R-SPLIT):

1. **Independent release cadence** — Heimdal must ship/roll back on a clock that fights Yggdrasil's.
2. **Isolation requirement** — the privacy/threat model requires the raw layer in a separately deployable, separately credentialed process/host. ⚠️ *This one is live on day one:* D-PRIVACY's "encrypted + isolated" posture arguably fires it for Heimdal's **raw store** (not its code) immediately — surfaced as OD-6 rather than silently assumed.
3. **Independent scaling / hardware** — sensor capture pins dedicated hardware the monorepo deployment cannot express.
4. **Ownership divergence** — a distinct agent-fleet owns a constituent end-to-end.
5. **Blast-radius containment** — a fault class in one constituent can take others down at build/deploy time.

**Concrete tripwires to watch (proposal-specific):** Heimdal's CI wall-time dominating the shared pipeline (trigger 5's early smell); capture-model updates needing same-day deploys while Yggdrasil is mid-promotion (trigger 1); a second host in the mesh dedicated to capture (trigger 3).

---

## 9. Proposed fitness invariants for the new structure

Style of `docs/testing/invariant-tests.md`; each = name + one line + enforcement level. Heimdal-internal invariants HEIM-1..8 stay owned by the capability charter; these are **ecosystem-structure** invariants.

| ID | Invariant (one line) | Enforcement |
|---|---|---|
| **ECO-1 Contract-only attachment** | No constituent reads another's internals; every cross-constituent flow rides a published contract through a boundary adapter | High — import-boundary lint + CI gate |
| **ECO-2 Seam invariance** | Public tree is operator-invariant in product scope; builder/ops exceptions are registered; secrets absolute everywhere (= INV-EF1) | High — GATE lint on PR diff + DOCTOR reconcile (adoption = RESEARCH-08 D3) |
| **ECO-3 Append-only stream** | A published event is immutable; corrections are new events (HEIM-1 elevated to ecosystem law) | High — bus-contract schema + runtime guard |
| **ECO-4 One door to canonical** | Nothing — event, candidate, memory, sync result — becomes durable human knowledge except through the GOV promotion gate with DecisionToken + receipt | High — WriteGuard runtime (exists) + invariant tests |
| **ECO-5 Gated raw access** | Every raw-layer read carries a CrossScopeFlow grant and produces a receipt; no ungoverned raw path exists | High — runtime + audit fitness rule |
| **ECO-6 One identity** | No constituent mints a divergent canonical entity identity; attribution resolves against the Layer-2 register; SIP maps, never forks | Medium — contract conformance test |
| **ECO-7 Substrate neutrality** | Layer-2 mechanisms are owned by no constituent; promotion/demotion only via ADR (R-PROMOTE) | Process — CES review checklist |
| **ECO-8 SFC ≠ SoS** | Intra-constituent distribution vocabulary/machinery never governs cross-constituent attachment; sibling interaction is tiered (Tier-1 requires ADR-0020's delivery-semantics classification before build) | Process — CES + design-review gate (adoption = RESEARCH-08 D2) |
| **ECO-9 Kernel survival** | The nine-invariant runtime correctness kernel remains fully enforced inside Yggdrasil regardless of ecosystem framing; the Layer-2 bus contract generalizes (never forks) its idempotency/schema discipline | High — existing kernel tests remain gating (fixed invariant 5) |
| **ECO-10 Observer independence (target)** | Ecosystem-level observation of a constituent's substrate comes from outside its failure domain | Advisory — future capability; no machinery now |

---

## 10. Surfaced owner decisions

Each is the owner's call; options + consequences; recommendations flagged, never enacted.

**OD-1 — What does "Yggdrasil" denote?** *(the required question; recommendation flagged)*
- **Option A (RECOMMENDED): Yggdrasil = the knowledge-and-cognition constituent (C1);** apex = Personal Agentic Ecosystem. *Consequences:* near-zero churn (every existing "Yggdrasil" reference stays correct, including `yggdrasil_runtime/`); INCOSE-honest (no constituent split forced); coherent with merged RESEARCH-08 and ADR-0041's paid-for vocabulary cleanup. Cost: contradicts draft ADR-0043's D-NAME-WHOLE — requires amending/superseding that draft before PR #2888 merges; the world-tree metaphor no longer names the whole.
- **Option B: Yggdrasil = the whole (SoS),** per draft ADR-0043. *Consequences:* metaphor-maximal and matches the 2026-07-04 in-principle decision; but forces either the structurally unsound Munin/Hugin constituent split (§6 Alt A) or a new name + mass re-referencing for the current system, and re-introduces "Yggdrasil is an SoS" post-ADR-0041.
- **Option C: dual-scope** ("Yggdrasil" means both, disambiguated by context). *Consequences:* zero immediate churn, permanent ambiguity — the exact disease the boundary-language guardrails exist to prevent. Not recommended.

**OD-2 — Ratify the apex, and its activation semantics.** The Personal Agentic Ecosystem as acknowledged SoS (refines RESEARCH-08 D1). *Option A (recommended):* ratify now with the bridge/target posture — current-state docs unchanged; ecosystem framing becomes primary when the first non-Yggdrasil constituent **runs** (Heimdal v1 capturing), not when it is chartered. *Option B:* chartering Heimdal counts as activation → immediate reframing churn across SoI-stating docs. *Option C:* decline; Heimdal becomes Alt-B-style internal capture — conflicts fixed invariant 2.

**OD-3 — Constituent posture of the knowledge/agent split.** *Option A (recommended):* one constituent now; Hugin/Munin names reserved; an agent-runtime split becomes a future split-trigger question with evidence. *Option B:* ratify Munin/Hugin as constituents per Heimdal A1 → must answer §6 Alt A's unassignable-boundary problem explicitly (where do GOV/WSP/HIX/EBF/SFC/OEF live?). *Consequence of A:* draft ADR-0043's constituent register needs amendment (bundle with OD-1/OD-7).

**OD-4 — Charter the private bindings constituent now, or leave it proto?** *Option A (recommended):* charter it (thin: a contract + a private home + the INV-EF1 burn-down as its backlog) — it is the seam's other side and Heimdal's raw-layer config will need it immediately. *Option B:* leave proto until Heimdal implementation forces it. *Consequence of B:* Heimdal bindings accrete in `.env`/ops-script form and migrate later at higher cost.

**OD-5 — Substrate promotion timing (R-PROMOTE).** Promote now: the *contracts* for event bus, identity register, provenance standard (paper Layer-2, no shared runtime yet)? *Option A (recommended):* promote the three contracts at Heimdal design-acceptance; implementations stay module-lazy. *Option B:* defer all promotion until two constituents demonstrably need each item. *Consequence of B:* Heimdal v1 builds Heimdal-private identity/provenance, guaranteeing a later migration against D-IDENTITY's intent.

**OD-6 — Is D-PRIVACY already split-trigger 2 for Heimdal's raw store?** *Option A (recommended):* yes for the **data/process plane** — raw store runs separately credentialed/isolated from birth — while code stays in the monorepo (trigger applies to deployment, not repo). *Option B:* no — raw store starts inside the shared deployment with encryption only. *Consequence of B:* cheaper start; the seam is disciplinary, not structural, until a migration.

**OD-7 — Adopt the naming scheme (§7) and amend the name register.** Options: adopt as proposed / adopt with Norse apex name minted now / keep ADR-0043's register unchanged (implies OD-1 option B). Consequence: whichever way, **one** superseding/amending ADR should carry OD-1 + OD-3 + OD-7 together — they are one naming coherence decision.

**OD-8 — Historical sequencing against PR #2888 and RESEARCH-08 D1–D4.** This record predates the current reconciliation: #2888 was closed unmerged, and ADR-0044–0047 landed the relevant decisions. At the time, #2888 (ratifying ADR-0043 + the A1 model) partially conflicted with this proposal (Yggdrasil referent; Munin/Hugin constituents). *Option A (recommended):* hold #2888, reconcile it with this proposal, land one coherent ratification (this structure + amended naming + D1/D2/D3 adoptions referenced, D4 orthogonal). *Option B:* merge #2888 as-is, then supersede — double churn. These options are historical, not active work. This proposal *assumes* the substance of RESEARCH-08 D2 (tier rule → ECO-8) and D3 (INV-EF1 → ECO-2); those remain their own owner decisions.

---

## 11. SBS reconciliation summary

| # | Load-bearing claim | Tag | Routing |
|---|---|---|---|
| 1 | Apex = Personal Agentic Ecosystem, acknowledged SoS, governance-by-contract (Layer 1, not runtime) | **reshape** | CES/ADR via OD-2 (refines RESEARCH-08 D1; reconcile with PR #2888) |
| 2 | Yggdrasil denotes the knowledge-and-cognition constituent (C1), not the whole | **reshape** | CES/ADR via OD-1 + OD-7 (amends/supersedes draft ADR-0043 D-NAME-WHOLE) |
| 3 | Heimdal is a sibling constituent, not a subsystem of the knowledge system | **reshape** | CES/ADR — same reshape Heimdal A1 §1 routes; carried, not re-decided |
| 4 | Knowledge/agent split is NOT a constituent split; Munin/Hugin reserved, unassigned | **conform** (audit §3, RESEARCH-08 claim 4) / **reshape** vs draft ADR-0043 register | OD-3, bundled into the OD-7 ADR |
| 5 | All 14 boundaries + CES remain Yggdrasil-internal; boundaries grouped, not redefined | **conform** | none |
| 6 | CES stewardship extends upward to Layer-1 ecosystem contracts | **extend** | CES practice update at enactment |
| 7 | Heimdal's stream enters Yggdrasil via EBF adapter under the IFC authority rule; Tier-1 classification obligation applies | **conform** (IFC, EBF charter) / **extend** (tier rule = RESEARCH-08 D2) | ECO-8 adoption rides D2 |
| 8 | Event-log-vs-projection extended upstream to observation; one GOV promotion gate for events and candidates | **extend** / **conform** (fixed invariants 3–4) | Heimdal capability window designs the contract |
| 9 | Layer-2 substrate: bus contract, identity register, provenance standard shared; stores/observability constituent-owned | **extend** | R-PROMOTE per item via ADR (OD-5) |
| 10 | Bus contract generalizes the correctness-kernel outbox discipline (KERNEL-02/08/11); kernel invariants untouched | **conform** (fixed invariant 5) / **extend** (generalization) | Heimdal window D-BACKBONE design |
| 11 | Entity register upstream of SIP; SIP keeps artifact semantic/provenance identity | **extend** | Contract design at enactment; watch the SIP-fork failure mode |
| 12 | KAP stays an in-constituent capability (EBF class 11, ends at candidate) | **conform** | none |
| 13 | Public/private seam = three concentric expressions; INV-EF1 adopted as ECO-2 | **extend** | RESEARCH-08 D3 (owner) |
| 14 | Monorepo + five split-triggers; private-by-substance constituents born outside the repo | **conform** (A1 §4) / **extend** (born-outside refinement) | OD-4, OD-6 |
| 15 | Naming scheme: Norse names for constituents/ecosystem only; boundaries keep codes; register amended | **reshape** | One ADR bundling OD-1/OD-3/OD-7 |
| 16 | Fitness invariants ECO-1..10 | **extend** | Invariant-registry pattern; adoption at enactment |

No reshape is enacted by this proposal. All reshapes exist only as routed owner decisions (OD-1…OD-8).

---

## Appendix — structure sketch (SVG)

Same image as `ecosystem_structure_sketch.svg` (sibling file in this scratchpad).

```svg
<svg viewBox="0 0 900 600" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif">
  <defs>
    <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333"/>
    </marker>
    <marker id="arrR" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#8f2d2d"/>
    </marker>
  </defs>

  <!-- ======== APEX ======== -->
  <rect x="140" y="12" width="620" height="62" rx="8" fill="#1d3557"/>
  <text x="450" y="36" fill="#ffffff" font-size="15" font-weight="bold" text-anchor="middle">PERSONAL AGENTIC ECOSYSTEM — apex (acknowledged SoS)</text>
  <text x="450" y="56" fill="#cdd9ea" font-size="11" text-anchor="middle">Layer 1 = governance by contract (CES / ADR), not runtime · one human = apex authority</text>

  <!-- apex -> constituents connectors -->
  <line x1="160" y1="74" x2="160" y2="106" stroke="#7a8aa0" stroke-width="1.5"/>
  <line x1="560" y1="74" x2="560" y2="106" stroke="#7a8aa0" stroke-width="1.5"/>

  <!-- ======== SEAM ======== -->
  <line x1="316" y1="92" x2="316" y2="452" stroke="#b02a2a" stroke-width="3" stroke-dasharray="10 6"/>
  <text x="322" y="102" fill="#b02a2a" font-size="11" font-weight="bold">PUBLIC / PRIVATE SEAM — sharpest boundary</text>
  <text x="322" y="115" fill="#b02a2a" font-size="10">only minimized, attributed, published events cross by default</text>

  <!-- ======== HEIMDAL (private side, top-left) ======== -->
  <rect x="20" y="122" width="276" height="178" rx="8" fill="#fbeeee" stroke="#8f2d2d" stroke-width="1.6"/>
  <text x="158" y="141" fill="#6e1f1f" font-size="13" font-weight="bold" text-anchor="middle">HEIMDAL — sensor constituent</text>
  <text x="158" y="155" fill="#6e1f1f" font-size="10" text-anchor="middle">Event Capture &amp; Attribution · ends at a published event</text>

  <rect x="32" y="164" width="120" height="30" rx="4" fill="#ffffff" stroke="#b98585"/>
  <text x="92" y="177" fill="#553" font-size="9.5" text-anchor="middle">capture adapters</text>
  <text x="92" y="188" fill="#553" font-size="9.5" text-anchor="middle">(consent-gated, opt-in)</text>

  <rect x="32" y="204" width="120" height="84" rx="4" fill="#5b1f1f"/>
  <text x="92" y="222" fill="#ffffff" font-size="10" font-weight="bold" text-anchor="middle">RAW OBSERVATION</text>
  <text x="92" y="234" fill="#ffffff" font-size="10" font-weight="bold" text-anchor="middle">LAYER — most private</text>
  <text x="92" y="250" fill="#e8c9c9" font-size="9" text-anchor="middle">encrypted at rest · isolated</text>
  <text x="92" y="262" fill="#e8c9c9" font-size="9" text-anchor="middle">reads = CrossScopeFlow grant</text>
  <text x="92" y="274" fill="#e8c9c9" font-size="9" text-anchor="middle">+ receipt · hard retention</text>

  <rect x="166" y="204" width="118" height="84" rx="4" fill="#ffffff" stroke="#b98585"/>
  <text x="225" y="226" fill="#6e1f1f" font-size="9.5" text-anchor="middle">minimize · attribute</text>
  <text x="225" y="238" fill="#6e1f1f" font-size="9.5" text-anchor="middle">(shared identity register)</text>
  <text x="225" y="250" fill="#6e1f1f" font-size="9.5" text-anchor="middle">confidence + provenance</text>
  <text x="225" y="262" fill="#6e1f1f" font-size="9.5" text-anchor="middle">→ PUBLISH</text>
  <line x1="152" y1="246" x2="166" y2="246" stroke="#8f2d2d" stroke-width="1.4" marker-end="url(#arrR)"/>
  <line x1="92" y1="194" x2="92" y2="204" stroke="#8f2d2d" stroke-width="1.4" marker-end="url(#arrR)"/>

  <!-- ======== EVENT STREAM crossing the seam ======== -->
  <line x1="284" y1="246" x2="368" y2="246" stroke="#8f2d2d" stroke-width="2.4" marker-end="url(#arrR)"/>
  <circle cx="340" cy="246" r="3.5" fill="#8f2d2d"/>
  <text x="326" y="234" fill="#8f2d2d" font-size="10" font-weight="bold">append-only published event stream</text>

  <!-- stream to future siblings (dashed, target-state) -->
  <path d="M 340 246 L 340 292 L 296 292 L 296 318 L 240 318" fill="none" stroke="#8f2d2d" stroke-width="1.3" stroke-dasharray="5 4" marker-end="url(#arrR)"/>
  <text x="348" y="286" fill="#8f2d2d" font-size="9">subscribe (target-state)</text>

  <!-- ======== FUTURE PRIVATE SIBLINGS (dashed) ======== -->
  <rect x="20" y="308" width="222" height="60" rx="8" fill="none" stroke="#7a5a2d" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text x="131" y="326" fill="#7a5a2d" font-size="11" font-weight="bold" text-anchor="middle">Future private siblings (slots)</text>
  <text x="131" y="340" fill="#7a5a2d" font-size="9.5" text-anchor="middle">home automation · network / personal infra</text>
  <text x="131" y="352" fill="#7a5a2d" font-size="9.5" text-anchor="middle">sourced OSS · attach via capability contracts</text>

  <!-- ======== PRIVATE BINDINGS CONSTITUENT (proto, dashed) ======== -->
  <rect x="20" y="380" width="276" height="60" rx="8" fill="none" stroke="#4a4a7a" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text x="158" y="398" fill="#4a4a7a" font-size="11" font-weight="bold" text-anchor="middle">Private bindings constituent (proto)</text>
  <text x="158" y="412" fill="#4a4a7a" font-size="9.5" text-anchor="middle">endpoints · credentials · device inventory · vault labels</text>
  <text x="158" y="424" fill="#4a4a7a" font-size="9.5" text-anchor="middle">born OUTSIDE the public repo (private by substance)</text>
  <path d="M 296 410 L 400 410 L 400 396" fill="none" stroke="#4a4a7a" stroke-width="1.3" stroke-dasharray="5 4" marker-end="url(#arr)"/>
  <text x="332" y="404" fill="#4a4a7a" font-size="9">resolves bindings at deploy</text>

  <!-- ======== YGGDRASIL (right of seam) ======== -->
  <rect x="336" y="122" width="544" height="274" rx="8" fill="#eef3ee" stroke="#2d5a34" stroke-width="1.8"/>
  <text x="608" y="142" fill="#1e3d23" font-size="13" font-weight="bold" text-anchor="middle">YGGDRASIL — knowledge &amp; cognition constituent (recommended referent)</text>
  <text x="608" y="156" fill="#1e3d23" font-size="10" text-anchor="middle">the current SoI, internally unchanged: 14 control boundaries + CES · public code, private data</text>

  <!-- read-model flow chain -->
  <rect x="352" y="176" width="88" height="66" rx="4" fill="#ffffff" stroke="#6b8f70"/>
  <text x="396" y="196" fill="#1e3d23" font-size="10" font-weight="bold" text-anchor="middle">EBF adapter</text>
  <text x="396" y="210" fill="#445" font-size="8.5" text-anchor="middle">event subscription</text>
  <text x="396" y="221" fill="#445" font-size="8.5" text-anchor="middle">Tier-1: replay +</text>
  <text x="396" y="232" fill="#445" font-size="8.5" text-anchor="middle">idempotency classified</text>

  <rect x="456" y="176" width="128" height="66" rx="4" fill="#ffffff" stroke="#6b8f70"/>
  <text x="520" y="192" fill="#1e3d23" font-size="10" font-weight="bold" text-anchor="middle">read-models / projections</text>
  <text x="520" y="206" fill="#445" font-size="9" text-anchor="middle">DRI indexes · RCA evidence</text>
  <text x="520" y="218" fill="#445" font-size="9" text-anchor="middle">MEM candidates</text>
  <text x="520" y="232" fill="#445" font-size="8.5" text-anchor="middle">rebuildable · never truth</text>

  <rect x="600" y="176" width="128" height="66" rx="4" fill="#fdf6df" stroke="#a8862d"/>
  <text x="664" y="192" fill="#6b5312" font-size="10" font-weight="bold" text-anchor="middle">GOV promotion gate</text>
  <text x="664" y="206" fill="#6b5312" font-size="9" text-anchor="middle">DecisionToken · WriteGuard</text>
  <text x="664" y="218" fill="#6b5312" font-size="9" text-anchor="middle">AuthorityReceipt</text>
  <text x="664" y="232" fill="#6b5312" font-size="8.5" text-anchor="middle">only path to canonical</text>

  <rect x="744" y="176" width="122" height="66" rx="4" fill="#dfe9df" stroke="#2d5a34" stroke-width="1.4"/>
  <text x="805" y="196" fill="#1e3d23" font-size="10" font-weight="bold" text-anchor="middle">HKA durable</text>
  <text x="805" y="209" fill="#1e3d23" font-size="10" font-weight="bold" text-anchor="middle">human knowledge</text>
  <text x="805" y="226" fill="#445" font-size="8.5" text-anchor="middle">human authority locus</text>

  <line x1="440" y1="209" x2="456" y2="209" stroke="#333" stroke-width="1.4" marker-end="url(#arr)"/>
  <line x1="584" y1="209" x2="600" y2="209" stroke="#333" stroke-width="1.4" marker-end="url(#arr)"/>
  <line x1="728" y1="209" x2="744" y2="209" stroke="#333" stroke-width="1.4" marker-end="url(#arr)"/>

  <!-- agents + KAP notes -->
  <rect x="352" y="258" width="232" height="58" rx="4" fill="#ffffff" stroke="#6b8f70" stroke-dasharray="4 3"/>
  <text x="468" y="276" fill="#1e3d23" font-size="10" font-weight="bold" text-anchor="middle">CAO / EXE — agents (Hugin facet)</text>
  <text x="468" y="290" fill="#445" font-size="9" text-anchor="middle">read events as candidate evidence only (HEIM-8)</text>
  <text x="468" y="302" fill="#445" font-size="9" text-anchor="middle">propose → GOV authorizes → EXE acts</text>

  <rect x="600" y="258" width="266" height="58" rx="4" fill="#ffffff" stroke="#6b8f70" stroke-dasharray="4 3"/>
  <text x="733" y="276" fill="#1e3d23" font-size="10" font-weight="bold" text-anchor="middle">KAP — acquisition capability (in-constituent)</text>
  <text x="733" y="290" fill="#445" font-size="9" text-anchor="middle">external sources → candidate; joins the same</text>
  <text x="733" y="302" fill="#445" font-size="9" text-anchor="middle">GOV promotion gate; shares provenance standard</text>

  <text x="608" y="338" fill="#1e3d23" font-size="9.5" text-anchor="middle">Boundary grouping: HIX · WSP · HKA · SIP · GOV · EBF · PDM · DRI · RCA · MEM · CAO · EXE · SFC · OEF (+ CES)</text>
  <text x="608" y="352" fill="#445" font-size="9" text-anchor="middle">all fourteen remain THIS constituent&#8217;s internal law — SFC = intra-constituent distribution, never the SoS relation</text>
  <text x="608" y="366" fill="#445" font-size="9" text-anchor="middle">nine-invariant runtime correctness kernel unchanged (fixed invariant 5)</text>
  <text x="608" y="384" fill="#6b5312" font-size="9" font-weight="bold" text-anchor="middle">persistence &#8800; authority — nothing becomes canonical without governed promotion</text>

  <!-- ======== PLATFORM SUBSTRATE (base) ======== -->
  <rect x="20" y="466" width="860" height="86" rx="8" fill="#e9ecf2" stroke="#5a6b8a" stroke-width="1.5"/>
  <text x="450" y="486" fill="#2c3a55" font-size="12" font-weight="bold" text-anchor="middle">PLATFORM SUBSTRATE — Layer 2 · shared mechanisms owned by no constituent · promotion owner-gated (R-PROMOTE)</text>
  <rect x="34" y="498" width="132" height="42" rx="4" fill="#ffffff" stroke="#8a97b0"/>
  <text x="100" y="515" fill="#2c3a55" font-size="9.5" text-anchor="middle" font-weight="bold">event bus contract</text>
  <text x="100" y="528" fill="#556" font-size="8.5" text-anchor="middle">envelope · idempotency · replay</text>
  <rect x="178" y="498" width="132" height="42" rx="4" fill="#ffffff" stroke="#8a97b0"/>
  <text x="244" y="515" fill="#2c3a55" font-size="9.5" text-anchor="middle" font-weight="bold">identity / entity register</text>
  <text x="244" y="528" fill="#556" font-size="8.5" text-anchor="middle">one canonical &#8220;who/what&#8221;</text>
  <rect x="322" y="498" width="140" height="42" rx="4" fill="#ffffff" stroke="#8a97b0"/>
  <text x="392" y="515" fill="#2c3a55" font-size="9.5" text-anchor="middle" font-weight="bold">provenance / replay standard</text>
  <text x="392" y="528" fill="#556" font-size="8.5" text-anchor="middle">shared by Heimdal + KAP</text>
  <rect x="474" y="498" width="118" height="42" rx="4" fill="#ffffff" stroke="#8a97b0"/>
  <text x="533" y="515" fill="#2c3a55" font-size="9.5" text-anchor="middle" font-weight="bold">build / CI skeleton</text>
  <text x="533" y="528" fill="#556" font-size="8.5" text-anchor="middle">per-constituent gates compose</text>
  <rect x="604" y="498" width="118" height="42" rx="4" fill="#ffffff" stroke="#8a97b0"/>
  <text x="663" y="515" fill="#2c3a55" font-size="9.5" text-anchor="middle" font-weight="bold">container base</text>
  <text x="663" y="528" fill="#556" font-size="8.5" text-anchor="middle">shared image + fragments</text>
  <rect x="734" y="498" width="132" height="42" rx="4" fill="#ffffff" stroke="#8a97b0"/>
  <text x="800" y="515" fill="#2c3a55" font-size="9.5" text-anchor="middle" font-weight="bold">hosts / mesh topology</text>
  <text x="800" y="528" fill="#556" font-size="8.5" text-anchor="middle">transport, never authority</text>

  <!-- substrate connectors -->
  <line x1="158" y1="440" x2="158" y2="466" stroke="#8a97b0" stroke-width="1.3" stroke-dasharray="3 3"/>
  <line x1="608" y1="396" x2="608" y2="466" stroke="#8a97b0" stroke-width="1.3" stroke-dasharray="3 3"/>

  <!-- ======== FOOTER ======== -->
  <text x="450" y="572" fill="#555" font-size="9.5" text-anchor="middle">Everything drawn at runtime is the PRIVATE data plane of one operator. The PUBLIC artifact plane is the monorepo:</text>
  <text x="450" y="586" fill="#555" font-size="9.5" text-anchor="middle">operator-invariant code + contracts for all public-side constituents (seam invariant INV-EF1). Advisory sketch — enacts nothing.</text>
</svg>
```
