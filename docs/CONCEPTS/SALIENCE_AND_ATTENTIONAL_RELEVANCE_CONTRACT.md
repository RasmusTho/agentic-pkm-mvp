State: Concept contract companion (salience, attentional relevance, and surfacing posture; implementation-agnostic).

# Salience and Attentional Relevance Contract

## Purpose

This document clarifies how the system should think about:
- what is mentally near or far,
- what deserves resurfacing,
- what is pressing because it is still unresolved,
- and how those meanings differ from artifact identity, maturity, review posture, or context
  boundaries.

It exists to keep the runtime from using a ranking or zone overlay as if it were the ontology.

This document is subordinate to:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`

and upstream of:
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/ARCHITECTURE.md`
- `docs/RETRIEVAL.md`

## Why this document is needed

The system is meant to help with more than explicit search.
It should also help the human:
- re-orient after interruption,
- recover relevant work,
- keep open loops from disappearing,
- notice what has become newly relevant,
- and avoid drowning in everything at once.

Those needs require a semantics of attentional relevance.

Without that semantics, the repo tends to collapse several different things into one fuzzy layer:
- current attention,
- current task relevance,
- unresolved pressure,
- recency of access,
- and temperature-like labels such as `hot` / `warm` / `cold`.

That flattening is misleading.

## Core claim

Salience is real and first-class in the human system function, but it is usually not a durable
essence of an artifact.

In most cases:
- salience is situational,
- attentional relevance is relational,
- and runtime overlays such as `zone` are derived projections over multiple signals.

## Canonical distinctions

### Attentional salience

Attentional salience answers:
- what is mentally near,
- what is easy to recall,
- what is likely to pull or deserve attention right now.

It is influenced by signals such as:
- recency,
- current commitments,
- unresolved status,
- active context,
- surprise or novelty,
- and recent interaction.

Attentional salience is primarily:
- situational,
- derived,
- and revisable.

It should not normally be treated as a permanent artifact property.

### Attentional relevance

Attentional relevance answers:
- what would be useful, important, or timely to surface in the current situation.

It is not identical to salience.
Something may be highly relevant but not mentally near, or mentally near but not actually useful.

Attentional relevance is therefore a relation between:
- the human,
- the current context,
- active commitments or questions,
- and one or more artifacts or retained materials.

### Open-loop pressure

Open-loop pressure answers:
- what is still cognitively tugging on the human because it is incomplete, unclear, blocked, or not
  yet safely parked.

This is related to GTD-like open loops and commitment structures, but it should not be reduced to
task metadata alone.

Open-loop pressure is often one of the strongest drivers of surfacing need.

### Surfacing need

Surfacing need answers:
- what the system ought to help bring back into view now or soon.

It may be driven by:
- attentional relevance,
- open-loop pressure,
- time-sensitive change,
- temporal drift or staleness,
- review cadence,
- and explicit human requests.

Surfacing need is therefore an operational consequence, not the base ontology itself.

## What salience is not

Salience is not the same as:
- `sphere` or `context`,
- `operational scope`,
- `maturity`,
- `review_state`,
- temporal validity,
- source role,
- trust,
- artifact identity,
- or file location.

These may influence salience or attentional relevance, but none of them should be used as a
complete proxy for it.

## Representation posture

The default posture should be:

- **Ontology level**
  - `attentional salience` and `attentional relevance` are first-class semantic concepts.
- **Representation level**
  - they are usually represented as derived projections, scores, overlays, or situational
    judgments rather than durable canonical artifact fields.
- **Runtime level**
  - the system may compute overlays, rankings, queues, or resurfacing suggestions from multiple
    signals.
- **Human-facing level**
  - the system should be able to explain why something surfaced without pretending that its current
    salience is the artifact's permanent essence.

## Relation to zone

`Zone` is current repo/runtime language for a derived attentional overlay.

The contract is:
- zone is downstream of salience semantics,
- zone is a projection over signals,
- zone may use compatibility labels or heuristic buckets,
- but zone is not the authoritative ontology of attentional meaning.

Historical temperature metaphors may survive as runtime or UX language, but they should be treated
as provisional overlays, not canonical domain truth.

## Relation to retrieval and resurfacing

Retrieval and resurfacing should not be treated as the same thing.

- Retrieval answers: "what can be found for this query or operation?"
- Resurfacing answers: "what deserves to be brought back into view now or soon?"

Both may use salience signals, but they serve different human functions.

This matters because:
- an artifact can be retrievable without being salient,
- and something can deserve resurfacing even without an explicit query.

## Safe design implications

The system should support salience-aware behavior, but conservatively.

This means:
- use salience to influence ranking or resurfacing, not to silently override trust or scope
  boundaries,
- keep explanations available,
- avoid treating recency alone as meaning,
- and let the human recover why something surfaced.

When signals conflict or are weak:
- prefer conservative surfacing,
- show provenance,
- and avoid strong claims about why the artifact "matters."

## Status

This document establishes a semantic contract, not a final ranking algorithm or metadata schema.

It intentionally leaves open:
- exact salience signals,
- whether any durable user-facing marker is desirable,
- how surfacing queues should be implemented,
- and whether `zone` survives long-term as the preferred runtime label.
