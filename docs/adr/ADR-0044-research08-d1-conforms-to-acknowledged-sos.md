State: Accepted (owner decisions, 2026-07-04; RESEARCH-08 D1 + Heimdal structure decisions OD-1/OD-3/OD-7). Ratifies the acknowledged System-of-Systems structure from the 2026-07-04 Fable-5 structure pass (`docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md`, PR #2914): the ecosystem apex is named **Yggdrasil** (the whole); its constituents are **Mimer** (knowledge-and-cognition, undivided — the current system, reverting to its original name), **Heimdal** (sensor), and a thin **private-bindings** constituent. **Supersedes the naming half of ADR-0043**: ADR-0043's Munin (knowledge/memory) / Hugin (agent-runtime) two-constituent split is replaced by the single undivided **Mimer** constituent, with **Hugin/Munin reserved**; ADR-0043's Heimdal-sensor and observability→OEF decisions are retained. Enactment (the `yggdrasil_runtime/`→Mimer code/doc rename, glossary reconciliation, entity-register + substrate contracts) is deferred to follow-ups; this ADR performs no rename.
Doc role: Decision record (ADR)
Authority: Authoritative for the ecosystem's top-level structure and constituent-naming decision (the apex, the constituent set, and the "what does Yggdrasil denote" question), superseding ADR-0043 on constituent naming only. It does not redefine any constituent's internals (Mimer keeps the 14 control boundaries + CES + correctness kernel; Heimdal keeps its A-doc charter). SoS scope and naming are owner-reserved (R-SOS/R-NAME) and are recorded here as the owner's locked decision, not an agent's.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the apex/constituent structure or the Yggdrasil referent is reversed).
Source of truth: This ADR plus `docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md` (the Fable-5 pass + locked OD-1..9), `docs/adr/ADR-0043-heimdall-naming-and-norse-name-register.md` (superseded in part), `docs/HEIMDAL/**`, and `docs/architecture/ecosystem-federation.md` § Owner decisions (D1).

# ADR-0044: Ecosystem structure + naming ratification (RESEARCH-08 D1) — Yggdrasil = the whole; Mimer the knowledge-and-cognition constituent

**Date:** 2026-07-04
**Status:** Accepted (owner decision, 2026-07-04)

---

## Context

Three owner-directed lines of work converged on the same architectural ground on 2026-07-04:

- **RESEARCH-08** (`docs/architecture/ecosystem-federation.md`, #2852) posed owner decision **D1**:
  ratify the personal agentic ecosystem as the aspirational System of Interest, and in what shape. Its
  artifact framed the ecosystem as a **Personal Agentic Ecosystem parent** with **Yggdrasil as a
  constituent**, using "federation" for the inter-system relationship.
- **#2886** (`docs/HEIMDAL/**` + ADR-0043) established the Heimdal sensor constituent and captured
  the owner's first-pass naming (**D-NAME-WHOLE**): **Yggdrasil = the whole**, constituents **Munin**
  (knowledge/memory), **Hugin** (agent-runtime), **Heimdal** (sensor); "federation" avoided (SFC
  owns it).
- **The 2026-07-04 Fable-5 structure pass** (`docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md`, PR
  #2914) drew one coherent breakdown, and the owner **locked decisions OD-1..9** on it, resolving the
  conflicts the first two lines left open.

The unresolved pivot was **what "Yggdrasil" denotes** (the whole vs. a constituent) and **whether
knowledge and agent-runtime are two constituents** (ADR-0043's Munin/Hugin split). The Fable-5 pass
found the split **structurally unsound**: it fails the INCOSE constituent-independence test the
2026-07-03 boundary audit settled — 6 of the 14 control boundaries (GOV, WSP, HIX, EBF, SFC, OEF) are
unassignable to either side, and the governed-write invariant chain (CAO→GOV→EXE→HKA) crosses the
split on every durable mutation. Knowledge and cognition are therefore **one** constituent, not two.

## Decision (owner, locked 2026-07-04)

### 1. Acknowledged System of Systems; the apex is named **Yggdrasil**

The personal agentic ecosystem is an **acknowledged System of Systems** under one human apex
authority, governed by contracts (CES/ADR) at Layer 1 — **not** by any runtime component. Its apex /
whole is named **Yggdrasil** (the world-tree; nothing in the cosmology is larger, so it is the
natural name for the whole). "Personal Agentic Ecosystem" is its descriptive name. This keeps the
owner's D-NAME-WHOLE answer (**Yggdrasil = the whole**) and resolves RESEARCH-08's D1 in its favour
over the artifact's "Yggdrasil-as-constituent" framing.

### 2. Constituents: Mimer, Heimdal, private-bindings (Hugin/Munin reserved)

- **Mimer** — the knowledge-and-cognition constituent: the **current system** (the present Single
  system of Interest), internally unchanged (all 14 control boundaries + CES, the correctness kernel,
  and **KAP** as an in-constituent acquisition capability). It **reverts to its original name Mimer**
  — the system was named Mimer before it was renamed Yggdrasil; Mímir is the well of wisdom at
  Yggdrasil's root. It is **one undivided constituent**, not split into knowledge and agent-runtime.
- **Heimdal** — the sensor / event-capture constituent (unchanged from ADR-0043 + `docs/HEIMDAL/**`).
- **Private-bindings** — a thin constituent for operator-bound configuration (endpoints, credentials,
  device inventory), born outside the public repo (OD-4).
- **Hugin / Munin — reserved, unassigned.** They stay available for a future agent-runtime or
  knowledge split **only if** it ever passes the constituent-independence test.

### 3. Supersede the naming half of ADR-0043

ADR-0043's constituent register — **Munin** (knowledge/memory) + **Hugin** (agent-runtime) as two
constituents — is **superseded**: the knowledge-and-cognition system is the single **Mimer**
constituent; Hugin/Munin are reserved. **Retained from ADR-0043:** Heimdal = sensor, the
observability alias → boundary code **OEF**, and the ecosystem Norse name register — amended here so
Munin/Hugin move to *reserved*, Mimer is added, and the **pantheon-per-constituent** principle holds
(Norse names for constituents + the ecosystem only; control boundaries keep their 3-letter codes;
capabilities keep descriptive names).

### 4. "Federation" stays SFC's word

The SoS relationship is **acknowledged constituents interoperating via capability contracts**, never
"federation" (SFC — Synchronization, Federation & Consensus — owns that term for intra-constituent
replication). RESEARCH-08's "federation" vocabulary is read through this ADR.

### 5. This records the owner's locked decision; enactment is deferred

SoS scope and naming are owner-reserved (R-SOS/R-NAME); this ADR records the owner's **locked**
OD-1/OD-3/OD-7 (with OD-2/4/5/6/8/9 in `docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md` §0). It
performs **no** rename: the `yggdrasil_runtime/`→Mimer code/doc rename, the `docs/GLOSSARY.md`
reconciliation, and the entity-register + substrate contracts (OD-5/OD-9) are deferred follow-ups.

## Constraints honored

- Decision record only — no code/doc rename, no glossary edit lands here.
- No constituent's internals are redefined; Mimer keeps the 14 boundaries + CES + correctness kernel;
  Heimdal keeps its A-doc charter.
- Single-user stance preserved: one operator, one ecosystem; constituents grow, the human does not.
- The one reshape vs ADR-0043 (Munin/Hugin → Mimer, no split) is owner-gated and recorded here, per
  boundary-audit §13 routing (CES / `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`).

## Consequences

- The ecosystem has one coherent structure: **Yggdrasil** (whole) ⊃ { **Mimer**, **Heimdal**,
  private-bindings }, on a Layer-2 platform substrate. RESEARCH-08 D2/D3/D4 (ADR-0045/0046/0047) read
  through it.
- ADR-0043 is **superseded in part** (naming / constituent register); its Heimdal/OEF half stands.
- The RESEARCH-08 artifact (`ecosystem-federation.md`) and any remaining "Munin/Hugin" or
  "Yggdrasil-as-constituent" prose are reconciled to this model as a flagged follow-up (#2890); until
  then, **this ADR wins** where they disagree.
- A bounded, mechanical enactment task exists (the Mimer rename); it is not performed here.

## When to revisit

Supersede only if the apex/constituent structure or the Yggdrasil referent is reversed, or if a
future split-trigger promotes an agent-runtime or knowledge constituent (activating a reserved raven
name).

## References

- `docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md` — the Fable-5 structure pass + locked OD-1..9 (PR #2914).
- `docs/adr/ADR-0043-heimdall-naming-and-norse-name-register.md` — superseded in part (naming); Heimdal/OEF half retained.
- `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` (A1), `docs/HEIMDAL/OWNER_DECISIONS.md` (A4).
- `docs/architecture/ecosystem-federation.md` § Owner decisions (D1) — RESEARCH-08 source (model-alignment pending, #2890).
- ADR-0045 (D2 constituent interaction), ADR-0046 (D3 INV-EF1), ADR-0047 (D4 MCP deferred).
