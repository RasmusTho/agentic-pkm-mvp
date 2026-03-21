State: Concept contract (human-first ontology for the second-brain domain; implementation-agnostic).

# Cognitive Ontology — actors, artifacts, commitments, operations

## Purpose

This document defines the canonical human-first ontology for the system.

It exists to answer questions of meaning before questions of representation:
- what kinds of things exist in the domain,
- what they mean,
- how they relate,
- what should be modeled as an actor, artifact, commitment, operation, role, state, transition, or receipt.

This is a domain contract, not a schema document.

Related documents:
- `docs/PROJECT_KERNEL.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`

## Current ontology posture

The ontology in this document is now explicit on several points that were previously muddy:
- `Vault Note` is treated as a distinct human-facing artifact class,
- `Commitment` structures are distinct from execution artifacts,
- `Mirror Artifact`, `Receipt Artifact`, and `Execution Artifact` are explicit subclasses,
- and review posture, maturity, and promotion are treated as distinct semantics rather than one
  blended lifecycle idea.

The main remaining sharpening work is now narrower:
- relating context structures such as sphere, context, situated role identity, shared
  participation, and operational scope more precisely to future boundary policy and
  representation rules,
- clarifying how explicit cross-scope permissions should relate to broader human overlap without
  letting runtime policy become the ontology,
- keeping current repo working language such as `writing plane` and `retention plane` explicitly
  provisional until better semantic grounding is chosen,
- and continuing to translate the sharper ontology into runtime and architecture deltas without
  overstating current implementation.

## Why this ontology exists

The system is not merely a note store or a retrieval surface.
It is intended to function as a human second-brain environment:
- an external cognitive workspace,
- an external memory surface,
- a support system for knowledge work, creative work, planning, reflection, and responsible action.

This aligns with the broad perspective from distributed cognition, cognitive offloading, self-regulated learning, and second-brain / workflow practice:
- cognition is distributed across people, artifacts, and procedures,
- external artifacts support memory, attention, planning, and creation,
- the human remains the primary bearer of meaning and responsibility.

## Core claim

The system is an external cognitive and practical work environment in which a human, supported by bounded system agents, works with artifacts, commitments, and processes in order to think, create, remember, orient, learn, plan, and act over time.

Knowledge artifacts are only one subset of the artifacts in this domain.

## Ontological layers

The canonical ontology has seven top-level layers:
1. Actors
2. Context structures
3. Artifacts
4. Commitment structures
5. Cognitive and creative operations
6. Metacognitive layer
7. Provenance and accountability

These layers are distinct and must not be collapsed into one another.

## 1. Actors

### Actor

An actor is something that can participate in processes, initiate or influence actions, and carry attribution.

### Human

The human is the primary actor in the system.

The human:
- gives meaning,
- carries intention,
- sets priorities,
- accepts or rejects proposals,
- retains final authority over durable meaning and consequential changes.

### System Agent

A system agent is a bounded assisting actor that can observe, retrieve, propose, structure, transform, plan, or execute within an explicitly constrained scope.

A system agent:
- may operate on delegation, policy, or explicit intent,
- does not own final meaning,
- must remain attributable and auditable.

### Delegation

Delegation is a first-class relation between a human and a system agent.

Delegation defines:
- what the agent may do,
- under which conditions,
- with what review or confirmation requirements,
- how the delegation can be revoked or narrowed.

## 2. Context structures

The system exists across different human contexts, not only across different files or workflows.

These structures are first-class in the ontology because they shape meaning, relevance, trust, and
appropriate action.

### Sphere

A sphere is an overlapping region of human life, concern, practice, or meaning.

Problem solved:
- human life is not naturally partitioned into one exclusive set of buckets,
- and the same artifact, commitment, or concern may genuinely matter across several parts of life
  at once.

Examples:
- work,
- private life,
- creative practice,
- roleplaying/world-building,
- reflective/self-development work,
- learning.

A sphere is therefore not a file bucket.
It is a first-class ontological structure for lived belonging and relevance.

### Situated Role Identity

A situated role identity is the human's context-bound mode of self within a situation:
the posture, tone, responsibility structure, and expectations that make that situation livable and
usable.

Problem solved:
- different contexts do not only contain different content; they often involve different ways of
  thinking, deciding, speaking, and judging relevance.

The canonical base term in the relevant literature is role identity; "situated" matters here
because what is salient depends on context.

The ontology does not require a heavy identity engine.
It does require acknowledging that context boundaries protect different situated ways of being,
working, and deciding.

### Context

A context is a situated configuration of currently relevant spheres, role identities, purposes,
commitments, and constraints.

Problem solved:
- what matters in a given moment is often more specific than long-lived sphere membership,
- and different operations may be appropriate in one situation even when the broader spheres are the
  same.

Context is therefore more temporal and situational than sphere.
It helps explain why the same artifact may be approached differently at different times.

### Operational Scope (`domain` in current repo language)

An operational scope is a narrower working boundary used by the system for retrieval, action
gating, path defaults, and other runtime decisions.

Current caution:
- current repo language often says `domain` here,
- but operational scope should not be mistaken for the whole human semantics of belonging.

Problem solved:
- the runtime still needs a stricter working boundary than the full human context model provides.

Examples:
- the active work scope for a retrieval,
- the current private scope on a device,
- a bounded scope used for suggestions or writes.

Operational scope may later be represented on artifacts and operations, but it is not the same
thing as sphere or context.

### Shared Participation

Shared participation is the relation by which an artifact, commitment, or concern meaningfully
belongs to more than one sphere or situated context.

Problem solved:
- human life contains genuine overlap,
- and the system should not force that overlap into a false one-bucket fiction.

Shared participation is the primary ontological explanation for overlap.
It says that overlap is real, not exceptional.

### Explicit Cross-Scope Allowance (`bridge` in current repo language)

An explicit cross-scope allowance is a bounded permission that authorizes recurring or reusable
runtime exposure across operational scopes without collapsing them into one undifferentiated space.

Problem solved:
- some real human overlap needs a durable operational expression,
- and the system must support that without turning it into accidental contamination.

A cross-scope allowance:
- authorizes a bounded kind of reuse or exposure across operational scopes,
- preserves the fact that the participating scopes remain distinct,
- and makes persistent crossing intelligible rather than implicit.

`Bridge` may remain acceptable as current repo working language for this narrower mechanism, but it
should not be treated as the primary mental model of overlap.

### Shared Artifact Participation

An artifact may participate in more than one sphere or context because its meaning genuinely spans
them.

Problem solved:
- some artifacts are genuinely reusable across contexts and should not be forced into a false
  single-home fiction at the meaning level.

This does not erase operational boundaries.
It describes how overlap can exist without collapse.
When persistent runtime crossing is needed, an explicit cross-scope allowance may be added on top of
that broader overlap.

## 3. Artifacts

### Cognitive Artifact

A cognitive artifact is any persistent or semi-persistent object used in thinking, creating, remembering, orienting, planning, reflecting, or reusing work.

This is the broadest artifact class in the domain.

### Work Artifact

A work artifact is a cognitive artifact primarily used to advance ongoing work or thinking.

Examples:
- working notes,
- drafts,
- sketches,
- concept notes,
- planning material.

### Vault Note

A vault note is a human-facing editable work artifact in the writing plane.

It is a special case of work artifact that deserves explicit treatment because the active system
already treats it as a distinct contract surface:
- it is directly readable and editable by the human,
- it carries the most important human-visible identity/provenance markers,
- and it is projected into multiple runtime representations without being reducible to them.

### Primary Human Artifact

A primary human artifact is a human-facing artifact intended to remain directly intelligible and
usable over time without requiring hidden runtime state in order to make basic sense.

Problem solved:
- the user's core meaning-bearing artifacts should outlive any one implementation, stack, or support
  mechanism.

Examples:
- vault notes,
- reflective artifacts the human revisits directly,
- project artifacts used as enduring human reference surfaces,
- other human-facing artifacts intentionally treated as primary meaning surfaces.

Not every artifact is primary in this sense.
Mirrors, indexes, and other derivative system structures may support primary artifacts without
becoming their ontological equals.

### Source Artifact

A source artifact is a cognitive artifact used as evidence, grounding, memory support, or reference.

Important:
- "source" is often a role played by an artifact in context, not always its intrinsic type.

### Retained Artifact

A retained artifact is a cognitive artifact preserved primarily for long-horizon retention,
rediscovery, citation, or later reuse rather than for immediate writing-surface editing.

Problem solved:
- not everything worth keeping should have to become a note before it can remain cognitively useful.

Examples:
- PDFs,
- documents,
- media,
- messages,
- project files,
- reference collections,
- hobby/reference material.

A retained artifact often plays the role of source artifact, but the two ideas are not identical:
- `retained` names a preservation/reuse function,
- `source` names an epistemic role in context.

### Creative Artifact

A creative artifact is a cognitive artifact whose primary function is generative or exploratory creation rather than settled knowledge.

Examples:
- fragments,
- motifs,
- idea seeds,
- partial drafts,
- form experiments,
- speculative notes.

### Project Artifact

A project artifact is a cognitive artifact tied to a commitment or multi-step effort over time.

Examples:
- briefs,
- plans,
- decision drafts,
- delivery drafts,
- project notes.

### Reflective Artifact

A reflective artifact is a cognitive artifact used for self-observation, interpretation, learning, or review.

Examples:
- journals,
- after-action reflections,
- learning logs,
- weekly reviews.

### System Artifact

A system artifact is an artifact whose primary purpose is to support coordination, explainability, traceability, or automation rather than to serve directly as human-authored meaning.

Examples:
- proposals,
- receipts,
- traces,
- mirrors,
- plans generated for execution.

This class remains broad, but explicit subclasses now include:
- receipt artifacts,
- mirror artifacts,
- execution artifacts.

### Mirror Artifact

A mirror artifact is a system artifact that preserves a portable machine-side projection of a
human-facing artifact together with selected metadata or history.

It is not the same thing as the primary human artifact.
Its role is to support portability, healing, provenance, and cross-instance continuity.

### Receipt Artifact

A receipt artifact is a system artifact whose main purpose is to provide a human-legible account of
what happened, under what authority, and with what result.

### Execution Artifact

An execution artifact is a system artifact produced to coordinate or record execution rather than to
act as a human project or commitment in itself.

Examples:
- generated execution plans,
- orchestration traces,
- run-scoped control artifacts.

## 4. Commitment structures

The system is not only an artifact environment; it is also a commitment and attention environment.

These structures are first-class in the ontology.

### Commitment

A commitment is something the human experiences as needing attention, maintenance, progress, or decision.

### Project

A project is a commitment that requires multiple steps over time.

### Next Action

A next action is the next concrete actionable step that can advance a commitment or project.

### Waiting State

A waiting state is a commitment or sub-commitment that is blocked, deferred, or dependent on another actor or event.

### Focus Area

A focus area is a stable zone of responsibility, concern, or ongoing maintenance in the human's life or work.

### Review Cycle

A review cycle is a recurring practice of re-orienting, re-evaluating, and restoring trust in the external system.

### Context of Action

A context of action is the situational frame that determines when a next action is relevant, feasible, or appropriate.

## 5. Cognitive and creative operations

### Cognitive Operation

A cognitive operation is a meaningful activity in which actors work with artifacts or commitments in order to understand, create, decide, remember, or advance work.

### Core operations

The following are canonical examples:
- capture,
- clarify,
- organize,
- review,
- engage,
- explore,
- associate,
- compare,
- synthesize,
- plan,
- decide,
- create,
- revise,
- refine,
- retrieve,
- reuse,
- reflect.

### Ask / retrieval

Question-answering is not a foundational ontological primitive.

It is a special case of broader operations such as:
- inquiry,
- retrieval,
- synthesis,
- orientation.

## 6. Metacognitive layer

The system must support not only cognition but also metacognition.

### Metacognitive State

A metacognitive state describes the human's or system's orientation toward understanding, uncertainty, priority, and cognitive load.

### Attention State

An attention state describes what currently competes for the human's focus or concern.

### Open Loop

An open loop is anything that still has the human's attention without yet being sufficiently clarified, organized, delegated, or closed.

### Monitoring

Monitoring is the act of checking whether something is understood, remembered, progressing, trustworthy, or in need of re-evaluation.

### Calibration

Calibration is the alignment between:
- what the human believes is covered by the system,
- what is actually represented,
- what the system can safely do,
- what still requires human attention.

### Cognitive Load

Cognitive load is the practical burden placed on the human's working attention and control capacity.

The system should reduce unnecessary load without erasing orientation or responsibility.

## 7. Provenance and accountability

### Provenance

Provenance is the context that explains where an artifact, proposal, action, or claim came from, what it depended on, and how it was transformed.

### Receipt

A receipt is a human-legible record that something happened, by whom or by what, with which authority, on what basis, and with what result.

### Authority Boundary

An authority boundary defines what the system may:
- suggest,
- prepare,
- execute,
- or never do without explicit human approval.

### Trust Boundary

A trust boundary defines when the human may rely on system outputs without losing control, understanding, or the ability to audit what happened.

## Roles, states, properties, and transitions

### Roles

Roles are contextual functions, not entities.

Examples:
- source,
- working surface,
- reference,
- evidence,
- draft,
- evergreen,
- decision support,
- target of change.

### States

States describe how something is at a given time.

Examples:
- raw,
- preliminary,
- active,
- paused,
- reviewed,
- refined,
- archived.

### Properties

Properties describe entities without defining their ontological kind.

Examples:
- title,
- identity,
- domain,
- provenance,
- trust level,
- recency,
- salience.

Important:
- `domain` may appear as a property on artifacts, operations, or records,
- but ontologically it refers back to a first-class context structure rather than being only a
  metadata field.

### Transitions

Transitions are changes over time.

Examples:
- capture,
- review,
- refine,
- promote,
- accept,
- reject,
- archive.

Important:
- promotion is a transition, not a standalone entity,
- review is a transition or process, not merely a label,
- promotion, review, and maturity should be kept distinct unless an explicit contract collapses
  them for a specific runtime path,
- "evergreen" should be treated as a role or quality/state outcome rather than as a base class.

## Contract rules

1. The human remains the primary bearer of meaning and final authority.
2. System agents are bounded assisting actors, not autonomous owners of meaning.
3. Context structures such as sphere, context, situated role identity, shared participation, and
   operational scope are first-class; they are not only metadata or access filters.
4. The system must support creative work, knowledge work, planning, reflection, and memory, not only retrieval.
5. Commitment structures are first-class; the ontology is not artifact-only.
6. Ask / Q&A is a narrow operational surface, not the center of the ontology.
7. Roles, states, and transitions must not be confused with entity types.
8. Provenance, receipts, and authority boundaries are part of the ontology itself, not afterthought metadata.
9. The ontology must remain implementation-agnostic; schema and runtime terms may represent it, but may not redefine it.

## Sources

- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/ARCHITECTURE.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- [Stets & Burke, "Identity Theory and Social Identity Theory"](https://voidnetwork.gr/wp-content/uploads/2016/09/Identity-Theory-and-Social-Identity-Theory-by-Jan-E.-Stets-and-Peter-J.-Burke.pdf)
- [Kaplan, Garner et al., Frontiers paper using "situated role identity" / DSMRI framing](https://informalscience.org/wp-content/uploads/2025/01/Kaplan-Garner-Rush-Smith-2023-Frontiers-in-Education.pdf)
- David Chalmers & Andy Clark, "The Extended Mind"
- Edwin Hutchins, distributed cognition framing
- cognitive offloading / external memory literature
- self-regulated learning and writing-to-learn literature
- second-brain / workflow practice (including GTD-like commitment handling)
