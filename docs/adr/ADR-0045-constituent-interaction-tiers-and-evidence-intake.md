State: Accepted (owner decision, 2026-07-04; RESEARCH-08 decision D2). Adopts a three-tier classification of **constituent interaction** in the acknowledged SoS (Yggdrasil the whole; Mimer + Heimdal constituents — ADR-0044) and names the **inbound governed-candidate event/evidence intake** shape that Heimdal's published-event stream requires. ADR-0020 (SFC) is left untouched. Per ADR-0043/#2886, the SoS relationship is **not** called "federation" (SFC owns that word); the relationship is acknowledged constituents interoperating via capability contracts. Enactment (the `docs/GLOSSARY.md` reconciliation; per-surface exposure-gate application) is deferred to follow-up issues; this ADR performs no doc edit.
Doc role: Decision record (ADR)
Authority: Authoritative for the *decision* of how interactions between constituents of the acknowledged SoS are classified and governed, and for the intake shape by which one constituent's published output enters another as evidence. Naming/SoS scope stay owned by ADR-0044; SFC and ADR-0020 are unchanged. Design content: `docs/architecture/ecosystem-federation.md` § Interaction tiers (read through ADR-0044's conformance) and `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` §2 (event-log vs projection).
Owner: Architecture / CES stewardship
Temporal class: Durable decision (supersede via a new ADR only if the tier/intake rule is reversed or SFC's charter is extended to own inter-constituent topology).
Source of truth: This ADR plus `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` §2, `docs/architecture/ecosystem-federation.md` § Interaction tiers, `docs/adr/ADR-0020-sfc-single-node-upgrade-path.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1077-1132` (SFC charter), `docs/boundaries/SFC.md`.

# ADR-0045: Constituent interaction rule — three tiers + governed-candidate event/evidence intake

**Date:** 2026-07-04
**Status:** Accepted (owner decision, 2026-07-04)

---

## Context

In the acknowledged SoS (ADR-0044: Yggdrasil the whole; Mimer + Heimdal constituents),
constituents interoperate. Two governance questions arise:

- **Word collision.** "Federation" is already owned by **SFC** (Synchronization, Federation &
  Consensus, `docs/boundaries/SFC.md`; charter `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1077-1132`;
  ADR-0020) for *intra-constituent* node/replication topology. Per ADR-0043/#2886, the *inter-constituent*
  SoS relationship is **not** called federation — it is acknowledged constituents interoperating via
  capability contracts. This ADR uses that vocabulary. (RESEARCH-08's source artifact used
  "ecosystem federation"; read here through ADR-0044's conformance.)
- **Where do Tier-1/Tier-2 interactions land?** Some constituent interactions (a constituent caching
  another's content; a constituent writing toward another's durable surface) touch ground ADR-0020
  reserves. And exposing a constituent's capability surface over the mesh is a new network-exposure
  shape that must pass the "explicit and proportionate" gate (`docs/SECURITY_TRUST_BOUNDARIES.md:37`).

The concrete driver is **Heimdal**, the sensor constituent (ADR-0043): it *emits* an append-only
stream of attributed events, which downstream constituents consume. `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md`
§2 already fixes the rule — Heimdal owns the fact stream; Mimer projects events into durable
knowledge under its own governed-promotion rules and reads them as candidate evidence in its
cognition (the Hugin facet), never as authority. This ADR names the interaction taxonomy that classifies that flow, per boundary audit §13
routing (CES/`docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`).

## Decision

### 1. Three-tier constituent-interaction classification

Every interaction between two constituents is classified into one tier, selecting the governing
machinery:

| Tier | Interaction shape | Governing machinery | ADR-0020 status |
| --- | --- | --- | --- |
| **0** | Stateless, read-only capability call — one constituent asks, another answers, no retained state | Capability-contract adapter + tool policy + authority rule | **No SFC involvement** — the no-conflict zone |
| **1** | A constituent holds derived state of another's content (caches, mirrors, subscriptions) | Adapter + explicit staleness/refresh contract; **must run ADR-0020's own validation obligation** (`docs/adr/ADR-0020-sfc-single-node-upgrade-path.md:31`) before build | SFC-adjacent; classification mandatory before build |
| **2** | A constituent writes toward another's durable surface, or multi-write topology | Full capability-promotion path + GOV + SFC semantics | The ground ADR-0020 reserves; not licensed by the SoS framing |

### 2. Inbound governed-candidate event/evidence intake (the Heimdal shape)

A constituent that **emits data toward** another (Heimdal's published-event stream → Mimer) is
**not** Tier 0 (that is answer-on-request), **not** Tier 1 (holding another's content), and **not**
Tier 2 (authoritative write). It is a distinct **inbound governed-candidate event/evidence intake**:
the producer publishes attributed, provenance-bearing events; the consumer ingests them as
**candidates/evidence** and, where they become durable knowledge, only through its own governed path
(WriteGuard → DecisionToken → governed promotion → AuthorityReceipt; ADR-0019 / ADR-0031). This
conforms to the authority rule ("influence travels as evidence/candidates, never as direct
authority") and to ADR-0039 (derived inputs are candidate context, not authority). It stays **outside**
Tier 2 precisely because the producer never writes authoritatively into the consumer's surface — it
matches `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` §2 (event log vs. projection) exactly.

### 3. Authority boundary

Each constituent holds domain authority in its own domain (Heimdal owns the fact stream; Mimer owns
durable knowledge/memory and reasoning/orchestration); the human is apex. Published events are
evidence to consumers, not facts imposed by fiat.

### 4. ADR-0020 / SFC untouched; mesh exposure gated per-surface

The rule invokes ADR-0020's obligations at Tier 1 and reserves Tier 2 to SFC/ADR-0020; it does not
rescope, relax, or extend either. Exposing any constituent capability surface (or accepting any
inbound intake) over the mesh must pass the `docs/SECURITY_TRUST_BOUNDARIES.md:37` "explicit and
proportionate" gate **per-surface** (existing gate, applied — not a new one).

### 5. Enactment is a separate follow-up

Any `docs/GLOSSARY.md` reconciliation (ensuring "federation" reads as SFC-only and the SoS
relationship is described as acknowledged-constituent interoperation, consistent with ADR-0043) and
per-surface exposure-gate rows are follow-up work (#2891, aligned to ADR-0043's naming register). The
concrete Heimdal intake contract lives with Heimdal's own enactment (`docs/HEIMDAL/**`, #2886), not
here.

## Constraints honored

- Decision record only — no glossary, boundary-doc, or contract edit lands in this ADR's PR.
- ADR-0020 and SFC's charter are unchanged; the word collision is resolved by adopting ADR-0043's
  vocabulary (federation = SFC only), not by reshaping either owner.
- Reshape routed through CES / `SBS_OPERATIONALIZATION_PLAN.md`, per audit §13.
- Naming/SoS scope deferred to ADR-0043 (owner-reserved); single-user stance preserved.

## Consequences

- Every constituent interaction gets a checkable classification before build; Heimdal's event stream
  classifies immediately as inbound governed-candidate intake, keeping its data as evidence and off
  the Tier-2 authoritative-write path — consistent with the merged Heimdal SoS model.
- Tier-1 interactions inherit ADR-0020's validation discipline automatically.
- The "federation" word-collision is resolved by conforming to ADR-0043 (SFC owns the word), not by
  minting new vocabulary.
- A standing per-surface exposure-gate obligation applies to any mesh exposure or inbound intake.

## When to revisit

Supersede if the tier/intake rule proves insufficient, or if a future decision extends SFC's charter
to own inter-constituent topology.

## References

- `docs/adr/ADR-0043-heimdall-naming-and-norse-name-register.md`; `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` §2 (event log vs projection).
- `docs/architecture/ecosystem-federation.md` § Interaction tiers (read through ADR-0044's conformance).
- `docs/adr/ADR-0020-sfc-single-node-upgrade-path.md` (unchanged); `docs/boundaries/SFC.md`; `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1077-1132`.
- `docs/SECURITY_TRUST_BOUNDARIES.md:37` (exposure gate); ADR-0019 / ADR-0031 (governed writes); ADR-0039 (candidate-not-authority).
- ADR-0044 (D1 conformance); ADR-0046 (D3 INV-EF1); ADR-0047 (D4 MCP deferred).
