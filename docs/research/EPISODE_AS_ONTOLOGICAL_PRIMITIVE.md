State: CANDIDATE ontology-reshape proposal (advisory research artifact). Introduces a new first-class entity (`Episode`) and a new semantic dimension (`episode_ref`). Not enacted; adoption requires an owner CES/ADR step. Subordinate to the doctrine, the cognitive ontology, and owner contracts.
Doc role: Research / candidate ontology proposal
Temporal class: timeless (changes when semantics change, not when time passes)
Review cadence: event-driven
Source of truth: mixed (academic synthesis + this repo's canonical ontology)
Last reviewed: 2026-07-06
Last verified against: docs/CONCEPTS/COGNITIVE_ONTOLOGY.md, docs/architecture/functional-ontology.md, docs/architecture/semantic-dimensions.md, docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md, docs/HEIMDAL/README.md, docs/testing/invariant-tests.md

# The Episode as an Ontological Primitive

> **Candidate.** This proposes a new first-class entity, `Episode`, as the contextual anchor of a knowledge artifact — the bounded, observer-relative lived situation an observation is *about the context of*. It is advisory until ratified by the owner through a CES/ADR reshape. It changes no runtime behavior and defines no contract on its own.

## TL;DR

- The ontology has no entity for the **lived situation** that produced an observation. Agent memory already carries an `episodic` memory type and provenance fields with nothing to point at; observations float free of the situations that gave them meaning. This is the missing primitive.
- **Episode** is that anchor: a bounded, observer-relative segment of the user's lived activity, represented as a five-dimension **situation model** — *time, space, causation, goal, protagonist* — to which observations attach downward and which binds upward to Projects/Areas.
- It is a **new** entity, verified against the existing ontology. It neighbors but does not duplicate `moment` (which *surfaces* an episode), `Context` (which *frames* the present), `Workspace` (ephemeral), the `USER_SITUATION_MODEL` "situation" (entry-state), and the Heimdal sensor `event` (a discrete sensing act; many compose into one Episode).
- Six ontological commitments are **decided** here from the academic synthesis; one modeling fork (Episode's ontology-layer placement) is an **owner decision**.

## Why this is upstream of capture

Designing the capture pipeline (Heimdal → attribution → vault) before defining the Episode would bake in assumptions about an undefined primitive. Heimdal owns *attribution* (who/what/where/when, with confidence and provenance) and its responsibility ends at a published event. The Episode is the downstream abstraction that *groups* those attributed events into the bounded situations a human recognizes as "the meeting," "the walk," "the debugging session." Capture consumes the Episode definition; it does not produce it.

## The gap, verified against the ontology

| Existing concept | What it is | Why it is not the Episode |
| --- | --- | --- |
| `moment` (`docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`) | A proposal that *this* deserves attention *now* | Relevance-surfacing trigger; surfaces an episode, is not one. Non-authoritative, ephemeral lifecycle. |
| `Context` (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`) | "A situated configuration of currently relevant spheres, role identities, purposes, commitments, and constraints" | Present-tense frame/configuration, not a durable, dated, bounded event. |
| `Workspace` (`docs/architecture/functional-ontology.md`) | Active working surface (bindings for a work session) | Explicitly ephemeral: "Closing a workspace does not change any artifact's identity." |
| `Situation` (`docs/CONCEPTS/USER_SITUATION_MODEL.md`) | The condition the human is in *when meeting the system* (no-vault / return / degraded) | Entry-state/runtime condition — the wrong sense of "situation." |
| Heimdal `event` (`docs/HEIMDAL/README.md`) | An attributed, timestamped sensing act with confidence + provenance | A discrete observation. Orthogonal: many events compose into one Episode; one Episode spans many events. |

No entity carries the five-dimension situation model as a durable, bounded, observer-relative record; and no `semantic-dimensions.md` field lets an observation name the situation it came from. The Episode and the `episode_ref` dimension close that gap.

## Working definition

> An **Episode** is a bounded segment of the user's lived activity, conceived by the user (or proposed from high-confidence attribution) to have a beginning and an end, represented as a **situation model** indexed on five dimensions — *time, space, causation, goal, protagonist* — to which observations attach and which binds upward to Projects/Areas.

This is the operational definition of the event-cognition literature (Zacks & Tversky 2001; the situation/event-indexing model of Zwaan & Radvansky 1998), scoped to a single human's knowledge system. It is deliberately **observer-relative** and does **not** commit to a canonical grain or a mind-independent identity criterion — those are the open problems below.

## Six ontological commitments (decided)

Yggdrasil is the extended mind (Clark & Chalmers), single-human, grounded in lived experience. That grounding makes most of the academic literature's open forks decidable here:

1. **Cognitive construct, not realist particular.** The Episode is observer-relative (DOLCE-descriptive), because it is the *user's* lived situation. Consequence: it is **orthogonal to `evidence_role`** — an Episode is context/frame, never an admissibility upgrade. It slots in under the orthogonal-dimensions doctrine (ADR-0029 / `docs/architecture/semantic-dimensions.md`), not as a new evidence rule.
2. **Boundaries: five-dimension shift is the operational detector.** Prediction-error (Zacks EST; Bayesian surprise, Kumar et al. 2023) is the theory; the buildable proxy over a markdown + attributed-event stream is a shift on one or more of the five dimensions (new place / new people / new goal / time-gap / causal break).
3. **Grain: non-canonical, nested, goal-relative.** A call ⊂ a workday ⊂ a project. Grain flexes to the goal in view — isomorphic to the existing PARA-style Project/Area nesting. No fixed unit.
4. **Identity: fine-grained (Kim's property-exemplification).** Re-description changes the episode (the same walk *means* different things). A single human's episode inventory is naturally bounded, so Kim's "explosion" cost is affordable here where it would not be at scale.
5. **Episodic → semantic: transformation / coexistence, not replacement** (multiple-trace / "no consolidation without representation"). Episode-specific, gist, and schema representations coexist with shifting dominance — mapping directly onto the machine-memory tiers in `docs/architecture/memory-model.md`. Nothing is overwritten.
6. **Temporal structure: minimal.** `start` / `end` / `closed` state; no interval-algebra reasoner. Closure is the load-bearing property — it drives relevance decay (below).

## Placement — recommendation + the one owner fork

**Recommendation:** model `Episode` as a durable **Artifact** (Layer 3 of `COGNITIVE_ONTOLOGY.md`; a canonical, note-serialized entity when authored or confirmed) that *relates to* — does not merge with — `Context` (Layer 2). The relation is: an Episode is the durable, dated record that a `Context` (a live frame) was active during. Episodic memory : situation model :: Episode : Context.

**Owner fork (OD-1):** place `Episode` as a **Context Structure (Layer 2)** or as an **Artifact (Layer 3)**.
- *Artifact (recommended):* gives it durable identity, note-serialization, and a canonical authority path (HKA / WriteGuard) — consistent with note-serialization (below). Cost: two situational concepts (Episode + Context) that must be kept distinct.
- *Context Structure:* keeps all situational concepts in one ontology layer. Cost: Context Structures are frames, not durable dated particulars; forcing durability onto that layer strains it.

## Relations to existing concepts

- **Heimdal `event` → feeds:** attributed events are the raw material; the Episode groups them. Heimdal owns attribution; the Episode does not re-derive it. (Note: the Heimdal README's `Munin`/`Hugin` split reads as pre-`Mimer`-undivided naming per `docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md`; naming is tracked there and does not affect this proposal.)
- **`moment` → surfaces:** a moment may propose that an Episode (or an observation within it) deserves attention now.
- **`Context` → frames:** the situated configuration active during the Episode.
- **`Workspace` → hosts:** the working surface where an Episode is authored/reviewed; ephemeral.
- **`Project` / `Area` → binds upward:** the goal dimension is also the hook to the commitment layer (`docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`) — the upward binding that makes Episodes knowledge-organizing rather than merely time-organizing.
- **Observations → attach downward** via the new `episode_ref` dimension.

## Schema (note-serialized situation model)

`Episode` is vault-canonical and note-serialized (one markdown note per episode), consistent with the write-gated, human-legible substrate.

```yaml
episode_id: ep-...
scope: ...                     # inherits the scope model (ADR-0027); episodes are scoped
title: "..."                   # human-facing, re-labelable
time: {start, end, closed}     # `closed` drives relevance decay
space: [place, ...]            # location dimension
protagonists: [person/entity]  # who was involved
goal: [project_id/area_id]     # upward binding (commitment layer) + the goal dimension
causation: [prior_episode_id]  # links to preceding episodes (causal = the dominant relation)
parent_episode: ep-...         # nesting (non-canonical grain)
segmentation: proposed         # {proposed, accepted, re-cut} — opt-out; see interaction model
derived_from: [event_id, ...]  # Heimdal attributed events this episode groups
```

### New semantic dimension: `episode_ref`

Add to `docs/architecture/semantic-dimensions.md` a dimension answering *"in what bounded lived situation does this observation originate?"* It is orthogonal to `scope_binding` (which scope), `source_role` (what kind of source), and `evidence_role` (what it may do in reasoning). Like scope and provenance, it must survive derivation (see invariants).

## Interaction model — opt-out segmentation

Episode boundaries are low-stakes and reversible, so the confirm posture is **opt-out**, distinct from the WriteGuard confirm gate that still governs canonical *knowledge* writes:

- Heimdal *proposes* an Episode boundary and segmentation via five-dimension shift. The proposal **stands by default** — silence is acceptance (`segmentation: proposed → accepted`).
- The only human action is a **re-cut**: merge, split, re-time, re-label, or re-bind goal. *Active choice changes what was suggested; it never approves it.*
- This is a low-trust contextual proposal, not a canonical mutation, so it does not pass through WriteGuard — consistent with proportional governance (`docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`, the #1881 tiers).

## Relevance decay = episode closure

When an Episode's `closed` flips true, the observations bound to it drop in retrieval salience. This is the Event Horizon Model's working-model flush (Radvansky) — the mechanism behind "the grocery list stops mattering once the shopping is done." Decay is the retrieval consequence of *closure*, not a TTL heuristic; open episodes stay hot (the Zeigarnik reinterpretation). This gives a theoretical spine to event-triggered relevance decay and connects to the salience/attentional-relevance contract (`docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`) and the Contextual Relevance Engine.

## Reconciliation with the canonical eight invariants

Against `docs/testing/invariant-tests.md`:

- **`capture_stamps_scope` → extend:** capture also stamps `episode_ref` (proposed) alongside the scope bundle.
- **`provenance_survives_derivation` → extend:** `episode_ref` joins the bundle that must survive derivation; a derived chunk carries its (correctable) episode binding.
- **`retrieval_cannot_upgrade_intrinsic_non_evidence` → conform, untouched:** the Episode is orthogonal; it never upgrades or downgrades `evidence_role`. Explicitly preserved.
- **New invariant candidate:** `observation_episode_binding_survives` — flagged for ADR/registry, not assumed enacted.

## Carried resolutions (from the capture-pipeline split)

- **Heimdal owns attribution** — the five dimensions are fed by Heimdal's attributed events; the Episode consumes, does not re-derive.
- **WriteGuard is the confirm gate for canonical writes** — unchanged; episode segmentation sits below it (opt-out).
- **Vault-canonical + outbox, not an event bus** — the Episode is a note-serialized vault entity; the outbox stays plumbing. "Event" as a term is reserved for Heimdal sensor-events and outbox plumbing, never for the Episode.

## Reshape routing (CES/ADR)

Introducing a first-class entity and a semantic dimension is an ontology **reshape**, not a clarification. Per the repo's own rule it routes through a CES/ADR step and touches, on ratification: `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`, `docs/architecture/functional-ontology.md`, `docs/architecture/semantic-dimensions.md`, the invariant registry, and (likely) the `docs/HEIMDAL/` capture line. This candidate enacts none of them.

## Owner decisions

- **OD-1 — Ontology-layer placement:** Episode as **Artifact (recommended)** vs **Context Structure**. See placement section for the consequence of each.
- **OD-2 — Confirmed already:** note-serialized (one markdown note per episode), vault-canonical. Recorded here; reopen only if OD-1 forces otherwise.

## Out of scope (downstream epics)

The capture pipeline itself (domain model, sync, failure recovery); Apple Watch / device feasibility; machine-memory consolidation mechanics; Heimdal attribution internals. This document defines the *primitive* those epics consume.

## Open research questions (for the epic)

- **RQ1** — Concrete five-dimension shift thresholds that produce *good* proposed boundaries for this user's markdown + attributed-event stream (vs. over/under-segmenting).
- **RQ2** — Under fine-grained (Kim) identity, does a re-cut (split/merge) create new episode identities or re-describe one?
- **RQ3** — The decay curve on closure, and whether it differs by scope (work vs. creative/RPG vs. private).

## Grounding

Event segmentation & boundaries: Zacks, Speer, Swallow, Braver & Reynolds 2007 (EST); Zacks & Tversky 2001; Kurby & Zacks 2008; Kumar et al. 2023 (Bayesian surprise); Baldassano et al. 2017 (nested cortical event hierarchy). Situation/event models: Zwaan & Radvansky 1998; Radvansky & Zacks 2014 (Event Horizon Model). Episodic vs. semantic memory & consolidation: Tulving 1983; Conway & Pleydell-Pearce 2000; Winocur & Moscovitch 2011 (transformation). Retrieval & closure: Michelmann, Hasson & Norman 2023; Radvansky & Copeland 2006 (location-updating). Formal ontology (for the representational reconciliation, not adopted realist): Davidson 1969/1985; Kim 1976; Quine 1985; DOLCE. Full synthesis and the alignment/conflict/silence map between the descriptive and formal literatures is the source research behind this candidate.
