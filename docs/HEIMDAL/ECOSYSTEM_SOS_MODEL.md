State: Draft (advisory groundwork, 2026-07-04). Proposes an acknowledged System-of-Systems model for the personal agentic ecosystem, with Heimdal as a sibling constituent. This is a `reshape` relative to the current single-system framing (ADR-0041) and is advisory until enacted through CES/ADR. It creates no runtime behavior and no GitHub work.
Doc role: Architecture decision doc (Draft) — ecosystem-level SoS model
Authority: Authoritative for the *proposed* ecosystem SoS model, its three-layer split, its repo-topology posture, and the substrate inventory. Subordinate to the owner contracts and shipped-state docs (`docs/ARCHITECTURE.md`, `docs/STATUS.md`); it does not claim shipped reality. Constituent-internal architecture stays owned by each constituent's own docs.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: this doc + `docs/architecture/system-context-overlay.md` (SoS glossary framing), `docs/boundaries/README.md` (control-boundary model), `docs/KNOWLEDGE_ACQUISITION/README.md` (KAP sibling precedent), the owner decision session 2026-07-04.

# Heimdal A1 — Ecosystem System-of-Systems model

## Purpose

Establish the architectural container that a new capability — **Heimdal** (continuous observation of
reality → attributed, timestamped events with confidence and provenance) — plugs into. This doc fixes
*where Heimdal sits* so that the capability charter (`CAPABILITY_CHARTER.md`) can hand Fable a bounded
problem. It is advisory groundwork; every load-bearing claim is tagged with its SBS reconciliation
(`conform` / `extend` / `reshape`), and every `reshape` is owner-gated through CES/ADR.

## 1. The ecosystem is an acknowledged System-of-Systems `[reshape → CES/ADR]`

The personal agentic ecosystem is treated as an **acknowledged System-of-Systems (SoS)**: a set of
constituents that are independently meaningful and independently evolvable, deliberately assembled to
serve one operator. The whole is **Yggdrasil** (the world-tree); the constituents hang in it.

Constituents (see ADR-0043 for the naming):

- **Munin** — the knowledge/memory constituent (durable human knowledge + machine-memory read-models).
- **Hugin** — the agent-runtime constituent (reasoning, orchestration, cognition).
- **Heimdal** — the sensor / event-capture constituent (observation → attributed event stream).

Heimdal is a **sibling constituent, not a subsystem of Munin**. `[reshape → CES/ADR]` The reasons
are load-bearing and were fixed before this doc:

- **Dependency direction.** Every other constituent *consumes* Heimdal's event stream. A thing that
  everyone reads from, and that reads from no one, is a peer source, not a submodule of one reader.
- **Public/private seam.** Heimdal carries the most sensitive private data in the ecosystem (raw
  observation of reality). Nesting it inside the knowledge constituent would smear that seam across a
  boundary that must stay sharp.
- **Ends at a published event.** Heimdal's responsibility ends at a *published, attributed event*,
  exactly as the Knowledge Acquisition Platform (KAP) ends at a *candidate*
  (`docs/KNOWLEDGE_ACQUISITION/README.md`). Both are acquisition constituents that stop at a
  hand-off artifact; neither owns what downstream does with it.

**SBS reconciliation.** The current SoT (ADR-0041 + `docs/architecture/system-context-overlay.md`)
holds that the only INCOSE-defensible SoS today is the operator's *assembled environment* (Yggdrasil
+ Obsidian + iCloud), and that "Yggdrasil" as documented is a *modular single system*. Promoting the
ecosystem itself to an acknowledged SoS with Yggdrasil-as-the-whole-and-Munin/Hugin/Heimdal-as-
constituents **reshapes** that framing. This doc is advisory; the reshape must be ratified in its own
ADR (with CES review) before it is treated as SoT. Until then, `docs/ARCHITECTURE.md` /
`docs/STATUS.md` remain authoritative for shipped reality.

> Terminology note: this doc avoids the word "federation" for the SoS relationship. "Federation" is
> already owned internally by the **SFC** control boundary (Synchronization, Federation & Consensus,
> `docs/boundaries/SFC.md`), which is about node/replication topology *inside* a constituent — a
> different concern. The SoS relationship here is "acknowledged constituents," not SFC federation.

## 2. Event log vs. projection `[extend]`

Heimdal owns an **append-only fact stream**: the canonical, immutable record of "what was observed,
when, attributed to whom, with what confidence and provenance." Everything downstream is a
**read-model / projection** of that stream:

- **Munin** projects events into durable knowledge and memory items (still governed by its own
  authority-transition rules — an event does not become canonical knowledge without governed
  promotion).
- **Hugin** (agents) read events as candidate evidence, never as authority.

This mirrors the repo's existing separation rules (`docs/boundaries/README.md`): storage preserves
but does not define meaning; retrieval produces candidate evidence, not truth; memory is noncanonical
until promoted. Heimdal extends that model *upstream* to the point of observation. `[extend]`

## 3. Three-layer model `[extend]`

The ecosystem is organized in three layers. Confusing them is the main architectural failure mode.

| Layer | What it is | Who owns it | Enacted via |
|---|---|---|---|
| **1. SoS authority** | Governance, cross-constituent contracts, the public/private seam, name register, consent posture | No runtime component — CES stewardship + ADRs | CES/ADR, **not** runtime |
| **2. Platform substrate** | Shared mechanisms every constituent needs but none should own | The platform, owned by no single constituent | Platform-substrate promotion (see §5) |
| **3. Constituents** | Munin, Hugin, Heimdal — the systems that do the work | Each constituent owns its own internals | The constituent's own backlog |

**Layer 1 is not runtime.** `[conform]` It is the CES practice (`docs/boundaries/CES.md`) plus ADRs.
Cross-constituent rules (who may read the raw layer, what a published event must carry, how identity
is canonical) are contracts, not a service.

## 4. Repo topology: monorepo until a forcing function `[conform]`

The ecosystem stays a **monorepo with a hard internal seam** between constituents. Splitting into
separate repositories is deferred until a *concrete forcing function* appears. This conforms to the
repo's standing "contract-first, module-lazy" adoption principle
(`docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`): commit to the boundaries now; instantiate a
separate physical surface only when a second independent volatility clock justifies it.

**Split-triggers (any one is a candidate forcing function):**

1. **Independent release cadence** — Heimdal must ship/roll back on a clock that fights Munin's.
2. **Isolation requirement** — the privacy/threat model requires the raw layer to run in a separately
   deployable, separately credentialed process or host.
3. **Independent scaling / hardware** — sensor capture needs dedicated hardware or a topology that
   the monorepo deployment cannot express cleanly.
4. **Ownership divergence** — a distinct team/agent-fleet owns a constituent end-to-end.
5. **Blast-radius containment** — a fault class in one constituent must not be able to take the
   others down at build/deploy time.

Until a trigger fires, the seam is enforced by import boundaries and contracts, not by repo
separation. `[conform]`

## 5. Substrate inventory — what must be promoted to Layer 2 `[extend]`

Heimdal makes explicit a set of mechanisms that are today implicitly *Munin-internal* (or unbuilt)
but that all constituents will need. These must be **promoted to the platform substrate (Layer 2)**,
owned by no single constituent. This is the concrete build-list this model implies.

| Substrate | Today | Target (Layer 2) | SBS reconciliation |
|---|---|---|---|
| **Event bus** | No cross-constituent bus; the DB outbox (`docs/EVENTS.md`) is Munin-internal | A shared publish/subscribe seam Heimdal publishes to and others subscribe to. **Design resolved (#4545):** generalize the outbox discipline (append-only log + per-consumer cursors, DB-native; stream-native deferred as an ADR-gated transport swap) — see [`docs/architecture/layer2-event-bus-and-kap-backbone.md :: Event-bus direction`](../architecture/layer2-event-bus-and-kap-backbone.md#event-bus-direction) | `extend` (generalize outbox) or `reshape` if it changes outbox ownership |
| **Identity / entity register** | Implicit; entities resolved per-surface | **Shared canonical register** (owner decision, §6) so "Rasmus"/"Anna" mean the same entity across Heimdal and Munin | `extend` |
| **Build / CI** | Monorepo CI owned by the repo | Constituent-agnostic build/CI substrate; per-constituent gates compose onto it | `conform` |
| **Container base / runtime image** | Per-app compose | Shared base image + compose fragments constituents extend | `conform` |
| **Hardware / host topology** | Mac-mini + gaming-PC + thin-client over Tailscale (`ops/host-setup/README.md`) | Substrate all constituents schedule onto; sensor capture may pin dedicated hardware | `conform` |
| **Provenance / replay primitives** | KAP defines source-plugin + refinement + provenance/replay (`docs/KNOWLEDGE_ACQUISITION/`) | Candidate Layer-2 standard both KAP and Heimdal conform to. **Design resolved (#4545):** one shared backbone contract (the Heimdal published-observation backbone, on the fixed shared provenance primitives) — see [`docs/architecture/layer2-event-bus-and-kap-backbone.md :: KAP-backbone decision`](../architecture/layer2-event-bus-and-kap-backbone.md#kap-backbone-decision) | `extend` |

Promotion of any substrate item is itself a governed move (Layer 1) and lands via ADR/CES when it is
enacted; nothing here is built by this doc.

## 6. Fixed owner decisions this model rests on

Captured 2026-07-04 (full rationale in `OWNER_DECISIONS.md`):

- **Naming** — Yggdrasil = whole; Munin = knowledge/memory constituent; Hugin = agent-runtime;
  Heimdal = sensor (observability alias → `OEF`). Recorded in ADR-0043. `[reshape → ADR-0043]`
- **Consent posture** — single-party consent; always-on capture **OFF** by default (opt-in per
  place/session); third parties are marked/degraded in events. `[extend — fixed guardrail]`
- **Raw-layer privacy seam** — raw observation layer is encrypted at rest and isolated; access is
  **policy-gated** (CrossScopeFlow-grant) for trusted downstream agents, not human-only; only
  published, minimized, attributed events cross the seam by default. `[extend — fixed guardrail]`
- **Identity/entity register** — shared Layer-2 platform substrate (this §5 row). `[extend]`
- **Retention/decay** — event-triggered relevance decay is the primary model, plus a bounded hard
  retention on the raw layer for privacy. `[conform — aligns with the established decay direction]`
- **Heimdal vs. KAP backbone** — **left open for Fable**; the fixed guardrail is a shared provenance
  standard, the stream-vs-batch architecture is Fable's to design. `[open]` *(Since resolved at
  design level: [`docs/architecture/layer2-event-bus-and-kap-backbone.md :: KAP-backbone decision`](../architecture/layer2-event-bus-and-kap-backbone.md#kap-backbone-decision), #4545.)*

## SBS reconciliation summary

| Claim | Reconciliation | Routing |
|---|---|---|
| Ecosystem is an acknowledged SoS; Yggdrasil = whole; constituents = Munin/Hugin/Heimdal | `reshape` | Own ADR + CES (not minted here) |
| Heimdal is a sibling constituent, not a Munin subsystem | `reshape` | Same ADR |
| Naming reassignments | `reshape` | ADR-0043 |
| Event-log-vs-projection; three-layer model; substrate promotion; identity register | `extend` | Platform-substrate promotion via ADR/CES at enactment |
| Consent + raw-layer privacy seam guardrails | `extend` | Charter FIXED section |
| Monorepo-until-forcing-function; Layer 1 is not runtime; CI/container/hardware substrate | `conform` | No routing needed |
| Retention = event-triggered relevance decay | `conform` | Aligns with established direction |
| Heimdal-vs-KAP backbone | `open` → resolved at design level ([#4545 design](../architecture/layer2-event-bus-and-kap-backbone.md#kap-backbone-decision)) | Fable design within guardrail |

## References

- ADR-0043 — Heimdal naming + Norse name register.
- `CAPABILITY_CHARTER.md` — the FIXED-vs-OPEN charter handed to Fable.
- `OWNER_DECISIONS.md` — what Fable may not decide, and the captured owner decisions.
- `docs/boundaries/README.md`, `docs/boundaries/SFC.md`, `docs/boundaries/CES.md` — control-boundary model.
- `docs/KNOWLEDGE_ACQUISITION/README.md` — KAP sibling-constituent precedent (acquire→candidate→publish).
- `docs/architecture/system-context-overlay.md`, ADR-0041 — current single-system SoS framing this reshapes.
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` — contract-first, module-lazy adoption.
