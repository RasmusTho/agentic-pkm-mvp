State: Accepted (owner decisions OD-1 + OD-2, 2026-07-06). Enacts the `Episode` entity and the `episode_ref` semantic dimension into the canonical ontology. Grounded in the research synthesis `docs/research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md`; this ADR is the normative decision, that doc is the advisory grounding.
Doc role: Decision record (ADR)
Authority: Authoritative for the existence, ontology-layer placement, and identity/boundary semantics of the `Episode` entity and the `episode_ref` dimension. It does NOT define the capture pipeline, Heimdal attribution internals, device feasibility, or runtime tuning (segmentation thresholds, decay curve) — those are downstream and owner-open.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the Episode's existence or its Artifact placement is reversed).
Source of truth: This ADR plus `docs/research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md` and the canonical ontology docs it edits (`docs/architecture/functional-ontology.md`, `docs/architecture/semantic-dimensions.md`, `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`, `docs/testing/invariant-tests.md`).

# ADR-0051: Episode is a first-class Artifact — the contextual anchor of a knowledge artifact

**Date:** 2026-07-06
**Status:** Accepted (owner decisions, 2026-07-06)

---

## Context

The ontology models artifacts, scope, provenance, memory, and evidence role, but has no entity for the **lived situation** an observation is *about the context of* — the meeting, the walk, the debugging session. Agent memory already carries an `episodic` sense and provenance fields with nothing to point at; observations float free of the situations that produced them. Without this primitive, episodic memory has nothing to be episodic about, and relevance cannot expire when a situation closes.

A general academic synthesis (event-segmentation theory — Zacks & Tversky; episodic vs. semantic memory — Tulving; the situation/event-indexing model — Zwaan & Radvansky; and the formal event ontology of Davidson/Kim/Quine/DOLCE for the representational reconciliation) was translated into a Yggdrasil-scoped proposal in `docs/research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md`. That proposal was verified against the existing ontology and found **genuinely new**: it neighbours but duplicates none of `moment` (which *surfaces* a situation), `Context` (a present-tense frame), `Workspace` (ephemeral), the `USER_SITUATION_MODEL` "situation" (an entry-state condition), or the Heimdal sensor `event` (a discrete sensing act; many compose into one Episode).

This ADR ratifies the two owner decisions the proposal surfaced (OD-1 placement; OD-2 serialization) and enacts the entity + dimension. It is downstream of Heimdal's event-intake line (ADR-0045, ADR-0049): Heimdal owns attribution; the Episode groups attributed events into recognizable situations.

## Decision (owner, locked 2026-07-06)

### 1. Episode is a first-class entity

`Episode` enters the canonical ontology as a durable, bounded, observer-relative record of a lived situation, represented as a **situation model** indexed on five dimensions: **time, space, causation, goal, protagonist**. Observations attach to it downward; it binds upward to projects/areas through its goal dimension.

### 2. Placement — Episode is an Artifact (OD-1)

Episode is modelled as a durable **Artifact** (Layer 3 of `COGNITIVE_ONTOLOGY.md`; HKA-owned, note-serialized, canonical when authored or confirmed), **not** a Layer-2 Context Structure. It *relates to* — does not merge with — `Context`: an Episode is the durable, dated record that a `Context` (a live frame) was active during. The accepted cost is keeping two situational concepts distinct (durable dated record vs. present-tense frame). The Layer-2 alternative was rejected because Context Structures are frames, not durable dated particulars.

**OD-2:** an Episode is **note-serialized** — one markdown note per episode, vault-canonical — consistent with the write-gated, human-legible substrate.

### 3. Six ontological commitments

Because Yggdrasil is the extended mind (Clark & Chalmers), single-human, grounded in lived experience, the literature's open forks are decidable here:

1. **Cognitive construct, not realist particular** (observer-relative; DOLCE-descriptive). Consequence: **orthogonal to `evidence_role`** — an Episode is context/frame, never an admissibility upgrade.
2. **Boundaries** — prediction-error is the theory; the buildable operational detector is a **shift on one or more of the five dimensions** (new place / new people / new goal / time-gap / causal break).
3. **Grain** — non-canonical, nested, goal-relative (a call ⊂ a workday ⊂ a project).

> **Amendment (owner decision, 2026-07-11; #3436):** The grain example is `a call ⊂ a workday, bound to a project`. Projects and series are structures that Episodes bind to through the goal dimension, not ancestor Episodes. The demarcation is continuity of lived presence versus required re-entry; see the [2026-07-11 definitional-iteration addendum](../research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md#addendum-2026-07-11--definitional-iteration-owner-directed-fable-5--external-gpt-5-review) for the full test.
4. **Identity** — fine-grained (Kim's property-exemplification): re-description changes the episode; a single human's inventory bounds the cost.
5. **Episodic → semantic** — transformation / coexistence, not replacement (maps onto the machine-memory tiers of `memory-model.md`).
6. **Temporal** — minimal (`start` / `end` / `closed`); closure is the load-bearing property.

### 4. `episode_ref` is a new orthogonal semantic dimension

A new dimension answers *"in what bounded lived situation did this originate?"* It is orthogonal to `scope_binding` (which scope), `source_role` (what kind of source), `authority_state` (what standing), and `evidence_role` (what it may do). Owned by SIP; honored by RCA and MEM. Like scope and provenance, it must survive derivation.

### 5. Opt-out segmentation

Episode boundaries proposed by capture (Heimdal) **stand by default** — silence is acceptance. The only human action is a **re-cut** (merge / split / re-time / re-label / re-bind goal); active choice changes what was suggested, it never approves it. This is a low-trust contextual proposal, **not** a canonical mutation, so it does not pass through WriteGuard — consistent with proportional governance. The WriteGuard confirm gate is unchanged for canonical *knowledge* writes.

> **Amended by [ADR-0054](./ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) (2026-07-07):** the *proposer* is refined. Heimdal contributes **single-stream** boundary proposals from its own attributed events; the **Mimer Episode Resolution Engine** fuses those with other streams (calendar, location, vault activity), resolves canonical episodes, and assigns `episode_ref`. The opt-out posture stated here is unchanged.

### 6. "Event" stays reserved for plumbing

`Episode` is the term for the lived situation. "Event" remains reserved for the Heimdal sensor event (a discrete attributed sensing act) and outbox plumbing. The three carried resolutions hold: Heimdal owns attribution; WriteGuard is the confirm gate for canonical writes; vault-canonical + outbox, not an event bus.

## Constraints honored

- Decision record + canonical ontology edits only — no code, schema, or runtime change.
- Extends the ontology; does not fork it. Episode is added alongside existing concepts with explicit non-collapse rules against `moment`, `Context`, `Workspace`, and the Heimdal event.
- Preserves the orthogonal-role doctrine (ADR-0029): `episode_ref` is a new orthogonal dimension, and Episode never touches `evidence_role`.
- Downstream and owner-open items (capture pipeline, thresholds, decay curve, device feasibility) are explicitly left out of scope.

## Consequences

- `Episode` appears in `functional-ontology.md` (§3), `COGNITIVE_ONTOLOGY.md` (Layer 3), and `episode_ref` in `semantic-dimensions.md`.
- A new fitness invariant `observation_episode_binding_survives` is registered as `future_runtime` (named for when the capture slice lands).
- Event-triggered relevance decay gains a theoretical spine: decay is the retrieval consequence of episode **closure** (Event Horizon Model), not a TTL.
- The downstream **capture-pipeline epic** now has a defined primitive to consume (RQ1–RQ3 in the grounding doc: shift thresholds, identity-under-recut, decay curve).

## When to revisit

Supersede with a new ADR only if the owner reverses Episode's existence, moves it out of the Artifact layer, or collapses it into `Context`/`moment`. Runtime tuning does not require an ADR revision.

## References

- Grounding: [EPISODE_AS_ONTOLOGICAL_PRIMITIVE](../research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md)
- Ontology edited: [functional-ontology](../architecture/functional-ontology.md) §3, [semantic-dimensions](../architecture/semantic-dimensions.md), [COGNITIVE_ONTOLOGY](../CONCEPTS/COGNITIVE_ONTOLOGY.md) Layer 3, [invariant registry](../testing/invariant-tests.md)
- Related ADRs: ADR-0027 (scope as frame), ADR-0029 (orthogonal roles), ADR-0044 (ecosystem structure — Yggdrasil/Mimer/Heimdal), ADR-0045 (Heimdal → downstream event/evidence intake), ADR-0049 (Heimdal ingestion organ)
- Neighbours (non-collapse): [MOMENT_ARTIFACT_CONTRACT](../CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md), [USER_SITUATION_MODEL](../CONCEPTS/USER_SITUATION_MODEL.md)
