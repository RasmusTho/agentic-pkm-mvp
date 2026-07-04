State: Accepted (owner decision, 2026-07-04; RESEARCH-08 decision D1). Records that RESEARCH-08's D1 question — whether the personal agentic ecosystem is ratified as a System of Systems and how — is **resolved by conforming to ADR-0043** (Heimdall naming + ecosystem Norse name register, PR #2886) and its owner-captured decision **D-NAME-WHOLE**: **Yggdrasil = the whole (the acknowledged SoS)**; constituents are **Munin** (knowledge/memory), **Hugin** (agent-runtime), and **Heimdall** (sensor/event-capture). This ADR does not re-decide naming or SoS scope (both owner-reserved, R-SOS/R-NAME, and owned by ADR-0043); it records that RESEARCH-08 adopts that framing. The RESEARCH-08 design artifact `docs/architecture/ecosystem-federation.md` still uses an earlier "Yggdrasil-as-constituent / Personal Agentic Ecosystem parent / federation" framing — reconciling that artifact to ADR-0043 is a flagged follow-up (#2890), not done here.
Doc role: Decision record (ADR)
Authority: Authoritative only for the *conformance* of the RESEARCH-08 line of work to ADR-0043's acknowledged-SoS model. It defines no naming and no SoS scope of its own — those stay owned by ADR-0043 and `docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md` / `docs/HEIMDALL/OWNER_DECISIONS.md`.
Owner: Architecture / CES stewardship
Temporal class: Durable decision (supersede only if ADR-0043's SoS model is reversed, in which case RESEARCH-08's conformance target changes with it).
Source of truth: This ADR plus `docs/adr/ADR-0043-heimdall-naming-and-norse-name-register.md`, `docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md`, `docs/HEIMDALL/OWNER_DECISIONS.md` (D-NAME-WHOLE), and `docs/architecture/ecosystem-federation.md` § Owner decisions (D1).

# ADR-0044: RESEARCH-08 D1 conforms to the acknowledged-SoS model of ADR-0043

**Date:** 2026-07-04
**Status:** Accepted (owner decision, 2026-07-04)

---

## Context

Two owner-directed lines of work landed on the same day (2026-07-04) over the same architectural
ground:

- **RESEARCH-08** (`docs/architecture/ecosystem-federation.md`, #2852) posed owner decision **D1**:
  ratify the personal agentic ecosystem as the aspirational System of Interest, and in what shape.
  Its design artifact framed the ecosystem as a **"Personal Agentic Ecosystem" parent** with
  **Yggdrasil as a constituent**, using the word **"federation"** for the inter-system relationship.
- **#2886** (`docs/HEIMDALL/**` + ADR-0043) established the Heimdall sensor constituent and, in doing
  so, captured the owner-reserved SoS and naming decisions (R-SOS, R-NAME). Its captured decision
  **D-NAME-WHOLE** resolves the pivotal question directly: **Yggdrasil is the whole** — the
  world-tree / the acknowledged SoS — and the constituents are **Munin** (knowledge/memory),
  **Hugin** (agent-runtime), and **Heimdall** (sensor). #2886 also deliberately **avoids "federation"**
  for the SoS relationship, because SFC (Synchronization, Federation & Consensus) already owns that
  word for intra-constituent replication.

These two framings **conflict** on what "Yggdrasil" denotes (the whole vs. a constituent), on the
parent's name, and on the "federation" vocabulary. SoS scope and naming are owner-reserved
(R-SOS/R-NAME per `docs/HEIMDALL/OWNER_DECISIONS.md`) and must not be decided by an agent. The owner
resolved the conflict on 2026-07-04: **#2886's framing is canonical; RESEARCH-08 conforms to it.**

## Decision

### 1. RESEARCH-08 adopts ADR-0043's acknowledged-SoS model

The personal agentic ecosystem is an **acknowledged System of Systems** with **Yggdrasil as the
whole** and **Munin / Hugin / Heimdall** as constituents, exactly as ADR-0043 and
`docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md` define. RESEARCH-08's D1 is answered by that model, not by a
competing "Personal Agentic Ecosystem parent / Yggdrasil-constituent" framing. The word "federation"
is not used for the SoS relationship (it is SFC's term); the relationship is **acknowledged
constituents interoperating via capability contracts**.

### 2. This ADR re-decides nothing owner-reserved

Naming and SoS scope stay owned by ADR-0043 (R-NAME, R-SOS). This record only registers RESEARCH-08's
conformance so the two threads do not drift. Heimdall's own design, charter, and enactment stay in
`docs/HEIMDALL/**` and #2886 — there is one home for Heimdall.

### 3. The RESEARCH-08 artifact's model-alignment is a flagged follow-up

`docs/architecture/ecosystem-federation.md` still carries the earlier Yggdrasil-as-constituent /
"federation" framing. Aligning that merged artifact to ADR-0043's model is tracked as a follow-up
(#2890); it is **not** performed in this PR. Until then, where the artifact and ADR-0043 disagree,
**ADR-0043 wins**.

## Constraints honored

- Decision record only — no naming or SoS-scope decision is minted here; no doc is reframed to a
  competing model.
- Owner-reserved decisions (R-SOS, R-NAME) are respected: this ADR conforms to the owner's captured
  choice, it does not substitute an agent's.
- Single-user stance preserved: one operator, one ecosystem; constituents grow, the human does not.

## Consequences

- RESEARCH-08's remaining decisions are read through ADR-0043's model: D2 (constituent interaction,
  ADR-0045) describes Heimdall→downstream event/candidate intake; D3 (INV-EF1, ADR-0046) and D4 (MCP,
  ADR-0047) are model-agnostic and stand as decided.
- The follow-up that previously would have reframed current-state docs to a Yggdrasil-as-constituent
  parent model is repurposed (#2890) to reconcile `ecosystem-federation.md` **to** ADR-0043 instead.
- Heimdall onboarding is not a separate RESEARCH-08 issue (the former #2889 was closed as superseded
  by #2886).

## When to revisit

Supersede only if ADR-0043's acknowledged-SoS model is itself reversed or restructured.

## References

- `docs/adr/ADR-0043-heimdall-naming-and-norse-name-register.md` (canonical naming + SoS model, #2886).
- `docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md` (A1), `docs/HEIMDALL/OWNER_DECISIONS.md` (A4, D-NAME-WHOLE).
- `docs/architecture/ecosystem-federation.md` § Owner decisions (D1) — the RESEARCH-08 source (model-alignment pending, #2890).
- ADR-0045 (D2 constituent interaction), ADR-0046 (D3 INV-EF1), ADR-0047 (D4 MCP deferred).
