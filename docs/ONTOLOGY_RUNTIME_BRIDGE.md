State: SoT v5.5 baseline + v5.x forward line reference.
Doc role: Reference
Authority: Cross-layer reading guide that connects human flows, ontology classes, runtime contracts, and infrastructure without redefining the owning SoT documents.
# Ontology Runtime Bridge

This document bridges three things that are easy to flatten when read separately:
- the human functions the system exists to support,
- the ontology/policy concepts used to describe meaning and boundary intent,
- and the runtime contracts that implement a narrower operational slice of that meaning.

It is a reading aid, not a replacement owner.
`docs/HUMAN-FLOWS.md` remains the human-facing behavior contract.
`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` and related concept docs remain the semantic owners.
`docs/ARCHITECTURE.md`, `docs/FRONTMATTER.md`, and `docs/DATA_MODEL.md` remain the active runtime and persistence contract surfaces.

## Four-layer reading model

### 1. Human function layer
This layer answers: what human burden or loop is the system trying to support?
It uses language such as capture, retrieval, orientation, learning, commitments, reflection, and creative development.
This is a product-level design lens.
It does not imply that every human function must map to a separate runtime agent, queue, or service.

### 2. Ontology/policy layer
This layer answers: what kind of thing is this, what relations or boundaries matter, and what policy or authority applies?
It distinguishes artifacts, commitments, contexts, operations, receipts, relations, and authority basis.
It also clarifies boundary semantics such as operational scope, overlap, provenance, review posture, and authorization.

### 3. Runtime orchestration layer
This layer answers: how does the current runtime carry out bounded work safely and inspectably?
It uses stores, events, watchers, panel/planner/orchestrator paths, ASK retrieval, mutation guardrails, and receipt-bearing actions.
Not every runtime unit is a rich agent.
Deterministic pipelines remain valid runtime substrate wherever they are the clearest and safest fit.

### 4. Infrastructure layer
This layer answers: where do persistence, transport, indexing, provider calls, and process boundaries actually live?
It includes the vault filesystem, Postgres/pgvector, DB outbox, CLI/API surfaces, and provider-facing components.
Infrastructure should support the upper layers without silently redefining their meaning.

## Compact semantic classes

These classes are intentionally compact.
They are a bridge vocabulary for reading the current repo, not a schema proposal.

| Class | Meaning in this bridge |
| --- | --- |
| artifact | A meaning-bearing thing the human may read, write, cite, retain, or develop over time. |
| commitment | A responsibility structure such as an open loop, promise, project obligation, next action, or waiting state. |
| context | A human situational boundary or belonging structure that shapes interpretation, retrieval, authority, and acceptable overlap. |
| operation | A bounded system or human-system action such as ingest, classify, retrieve, propose, execute, or mutate. |
| receipt | An accountability artifact showing what happened, under what basis, with which inputs, and with what effect. |
| relation | A typed connection such as source-of, supports, belongs-in, overlaps-with, depends-on, or derived-from. |
| authority basis | The basis on which the system may expose, infer, or change something: provenance, policy, explicit user intent, confirmed review, or bounded runtime authorization. |

Reading rule:
- a human-facing note is an artifact,
- a task/project/waiting structure is a commitment,
- a runtime audit row or event log is an operational trace, not a receipt by itself,
- receipts are distinct accountability artifacts that may be assembled or derived from operational traces plus execution context,
- and a single stored record may project more than one class without collapsing those classes into one meaning.

## Persistence surfaces

The current system persists across three surfaces that should not be conflated:

### Writing surface
Human-authored, editable, meaning-bearing material.
This is where authorship, durable prose meaning, and human-legible structure remain primary.

### Retention surface
Retained source-rich material kept for retrieval, citation, inspection, and later reuse without forcing it into the writing surface.
This is where source continuity and bounded exposure matter more than authorial drafting.

### System surface
Runtime records such as mirrors, indexes, traces, receipts, audit rows, execution artifacts, and configuration/runtime support structures.
These exist for execution, accountability, safety, and rebuildability.

Reading rule:
- writing and retention surfaces can both contain canonical artifacts,
- the system surface can contain durable accountability records,
- but the system surface should not silently become the only remaining copy of meaning.

## Receipts

Receipts are distinct accountability artifacts, not a synonym for every operational record.
They should make a meaningful action legible in terms of what happened, under what authority, on what basis, and with what result.

Raw audit rows, outbox events, and similar operational traces do not automatically satisfy receipt requirements by themselves.
They may support receipt construction and reconstruction, but a receipt remains a distinct accountability artifact assembled from traces plus the relevant execution context.

## Retrieval, orientation, and resurfacing

These terms are related but distinct:

- retrieval is the act of finding or returning relevant material in response to a query, task, or bounded runtime need.
- orientation is the act of helping the human regain situational understanding: what this is, why it matters, what context is active, and what to do next.
- resurfacing is the act of bringing something back into attention because timing, salience, review cadence, or changed circumstances suggest it should be revisited.

A system can retrieve without orienting well.
A system can resurface something without it being the best direct answer to a query.
The runtime should therefore avoid flattening all three into ranking alone.

## Human loops and runtime substrate

The human loops in `docs/HUMAN-FLOWS.md` should be read as product-level loops that the runtime helps support.
They are not a one-to-one execution topology.
Some loops may involve rich agent behavior.
Others may be best served by deterministic ingest, retrieval, routing, policy checks, or confirmation pipelines.

Deterministic pipelines therefore remain a valid runtime substrate.
The point of the ontology/runtime bridge is not to replace deterministic paths with agents everywhere.
The point is to keep the meaning of artifacts, commitments, context, and accountability legible as the runtime evolves.
