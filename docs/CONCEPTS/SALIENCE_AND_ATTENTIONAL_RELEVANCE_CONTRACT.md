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

It is primarily situational and derived rather than a permanent artifact property.

### Attentional relevance

Attentional relevance answers:
- what would be useful, important, or timely to surface in the current situation.

It is not identical to salience.
Something may be highly relevant but not mentally near, or mentally near but not actually useful.

### Open-loop pressure

Open-loop pressure answers:
- what is still cognitively tugging on the human because it is incomplete, unclear, blocked, or not
  yet safely parked.

### Surfacing need

Surfacing need answers:
- what the system ought to help bring back into view now or soon.

It may be driven by attentional relevance, open-loop pressure, temporal drift, review cadence, or
explicit human requests.

## Relation to zone

`Zone` is current repo/runtime language for a derived attentional overlay.

The contract is:
- zone is downstream of salience semantics,
- zone is a projection over signals,
- but zone is not the authoritative ontology of attentional meaning.

Historical temperature metaphors may survive as runtime or UX language, but they should be treated
as provisional overlays, not canonical domain truth.

## Relation to retrieval and resurfacing

Retrieval and resurfacing should not be treated as the same thing.

- Retrieval answers: "what can be found for this query or operation?"
- Resurfacing answers: "what deserves to be brought back into view now or soon?"

Both may use salience signals, but they serve different human functions.

## Status

This document establishes a semantic contract, not a final ranking algorithm or metadata schema.
