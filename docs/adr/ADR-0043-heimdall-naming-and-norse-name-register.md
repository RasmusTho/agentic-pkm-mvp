State: Proposed (owner decisions taken 2026-07-04; enactment deferred, no issues created — docs-only groundwork). Advisory until enacted through CES/ADR. Records the owner's naming decisions for the Heimdall sensor capability and the ecosystem-wide Norse name register, and separates those decisions from the enactment (glossary edits, concept renames). **Naming/constituent-register half SUPERSEDED by ADR-0044 (2026-07-04):** the Munin (knowledge/memory) / Hugin (agent-runtime) two-constituent split is replaced by the single undivided **Mimer** constituent (Hugin/Munin reserved); the Heimdall = sensor and observability → OEF decisions here are **retained**.
Doc role: Decision record (ADR) — Draft/Proposed
Authority: Authoritative for the *naming decisions* (which Norse name denotes which system-of-systems constituent, and how the observability alias collision is resolved). It does NOT redefine any architecture and does NOT perform any rename. Constituent boundaries and contracts stay owned by their own docs.
Owner: Architecture / CES stewardship (owner-gated naming; Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if a name assignment is reversed; mechanical enactment tracked by a later follow-up, not by editing this ADR)
Source of truth: This ADR plus `docs/GLOSSARY.md` (current Norse module vocabulary), `docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md` (the SoS model this naming serves), and the owner decision session of 2026-07-04.

# ADR-0043: Heimdall naming + ecosystem Norse name register

**Date:** 2026-07-04
**Status:** Proposed (owner-decided in principle; enactment deferred)

---

## Context

The personal agentic ecosystem is adding a new capability — continuous observation of reality,
converted into attributed, timestamped events with confidence and provenance ("Event Capture &
Attribution"). Its working name is **Heimdall** (the watchman who sees and hears everything).

Establishing the name surfaced two collisions against the *existing* Norse module vocabulary already
recorded in `docs/GLOSSARY.md`:

1. **`Heimdall` is already assigned** in the glossary to the *observability / infrastructure*
   concept ("runtime operations, metrics, logs, dashboards, and runbooks"). Crucially, the shipped
   control boundary for that concern is **OEF** (Observability, Evaluation & Fitness,
   `docs/boundaries/OEF.md`) — "Heimdall" for observability is only a *planned concept alias*, not a
   shipped artifact. Reassigning it therefore costs one glossary edit, not a code rename.
2. **`Munin`** is currently the glossary alias for a "planned media and raw-memory module for source
   artifacts," and **`Mimer`** is the "current implemented knowledge surface." The owner chose to
   consolidate the *knowledge/memory constituent* under the single name **Munin**.

Per SBS governance, name reassignments that redistribute what a name denotes are `reshape` items and
must be owner-gated through an ADR (audit §13; ADR-0041/ADR-0042 precedent). This ADR records the
owner's decisions; it performs no rename. It is deliberately **not** bundled with ADR-0041 (the
`SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` file rename) or ADR-0042 (§9 reword) — those are unrelated
concerns already in flight via #2855/#2856.

## Decision

### 1. Constituent name assignments

The ecosystem is an acknowledged System-of-Systems (see
`docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md`). Its Norse target picture is:

| Name | Denotes (going forward) | Prior glossary meaning | SBS reconciliation |
|---|---|---|---|
| **Yggdrasil** | The **whole** — the world-tree / the acknowledged SoS that constituents hang in | "the entire system" | `conform` (sharpened: whole, not a constituent) |
| **Munin** | The **knowledge/memory constituent** (durable human knowledge + machine memory read-models) | "planned media/raw-memory module" (+ `Mimer` = current knowledge surface) | `reshape` — consolidates `Mimer`+`Munin` into one constituent name |
| **Hugin** | The **agent-runtime constituent** (reasoning, orchestration, cognition) | "agent and reasoning layer concept within Yggdrasil" | `conform` (already aligned) |
| **Heimdall** | The **sensor / event-capture constituent** (observation → attributed event stream) | "infrastructure and observability boundary" | `reshape` — reassigns the name from observability to sensing |

Odin's ravens **Hugin** (thought) and **Munin** (memory) fly over the world and report what they
observe; **Heimdall** is the watchman. The metaphor is internally coherent for a thought-runtime, a
memory system, and a sensor.

### 2. Observability keeps its shipped boundary code

The observability concern **reverts to its canonical boundary code `OEF`** (`docs/boundaries/OEF.md`)
and drops the "Heimdall" Norse alias. No new Norse name is minted for observability in this ADR; the
owner may assign one later if desired. No shipped code changes — `OEF` is already the real boundary.

### 3. `Mimer` becomes a deprecated alias

`Mimer` (current implemented knowledge surface) folds into **Munin**. `Mimer` is retained only as a
deprecated alias pointing at Munin until references are updated.

### 4. Munin's former "raw-media" role is absorbed by Heimdall

The raw-observation / raw-source substrate that `Munin` used to imply is absorbed by **Heimdall's raw
observation layer** (the append-only fact stream, see the SoS model doc). Heimdall owns raw capture;
Munin owns the durable knowledge/memory read-models downstream.

### 5. Name register (collision guard)

The register below is the collision guard for all future naming. **Do not** reuse a `taken` name for
a new concept without a superseding ADR. Environment/vault names are mutable per
`docs/ENVIRONMENTS.md` and must never be hardcoded in docs — they are listed here only so new
constituent naming avoids them.

| Name | Assigned to | Kind | Status |
|---|---|---|---|
| Yggdrasil | The whole / acknowledged SoS | Ecosystem | taken |
| Munin | Knowledge/memory constituent | Constituent | taken (this ADR) |
| Hugin | Agent-runtime constituent | Constituent | taken |
| Heimdall | Sensor / event-capture constituent | Constituent | taken (this ADR) |
| Ratatosk | Ingest / pipeline boundary | Boundary concept | taken |
| Brokkr | Project-workshop boundary (planned) | Boundary concept | taken |
| Tyr | Formal-records boundary (planned) | Boundary concept | taken |
| OEF | Observability, Evaluation & Fitness | Control boundary (shipped code) | taken |
| Mimer | → Munin | Deprecated alias | deprecated |
| Niflheim | Dev vault | Environment (mutable) | in use |
| Bifröst | Test vault | Environment (mutable) | in use |
| Midgård | Prod vault | Environment (mutable) | in use |
| Gjallarhorn, Vedrfölnir, Muspelheim, Asgard, Valhalla, … | — | — | available |

### 6. Enactment is a separate, deferred follow-up (does not happen here)

The glossary edits (reassign `Heimdall`, consolidate `Munin`, deprecate `Mimer`, drop the
observability alias) and any downstream reference updates are **not** performed in this ADR and **no
issue is created here** — this is docs-only groundwork. When the ecosystem SoS model is enacted, a
follow-up (docs lane) performs the glossary reconciliation. Until then the current glossary stands
with this ADR as the recorded intent.

## Constraints honored

- Decision record only. No glossary edit, no code rename, no shipped-artifact rename lands here.
- Not bundled with ADR-0041 / ADR-0042. Their enactment (#2855/#2856) is independent.
- Only *concept aliases* are reassigned; the shipped observability boundary (`OEF`) is untouched.

## Consequences

- The ecosystem gets a coherent Norse target picture (Yggdrasil ⊃ {Munin, Hugin, Heimdall}) and a
  collision guard so future naming does not silently reuse a taken name.
- One-time glossary churn is deferred to a later enactment follow-up; until then `Heimdall`,
  `Munin`, and `Mimer` carry their old glossary meanings and this ADR is the recorded forward intent.

## When to revisit

Supersede with a new ADR only if a name assignment is reversed, or if a constituent is split/merged
such that a single name no longer maps cleanly.

## References

- `docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md` — the acknowledged-SoS model this naming serves.
- `docs/GLOSSARY.md` — current Norse module vocabulary (pre-enactment).
- `docs/boundaries/OEF.md` — the shipped observability boundary the alias reverts to.
- `docs/ENVIRONMENTS.md` — vault/environment naming (mutable; not hardcoded).
- ADR-0041 / ADR-0042 — unrelated in-flight rename/reword decisions; deliberately not bundled.
