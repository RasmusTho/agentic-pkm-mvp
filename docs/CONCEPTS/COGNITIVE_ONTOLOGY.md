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
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`

## Open clarification points

The ontology in this document is active, but some areas need further sharpening as the active SoT
docs are revised.

The most important current clarification points are:
- **Vault Note as explicit class**: the ontology likely needs to elevate the warm-surface `Vault Note`
  from an example of `Work Artifact` to an explicit specialization, because the active docs treat it
  as a distinct human contract surface.
- **Artifact vs projection**: the ontology currently emphasizes artifacts more than projections,
  mirrors, and runtime representations. Future revisions should make this distinction more explicit.
- **Review vs promotion vs maturity**: the runtime currently compresses some of these semantics. The
  ontology should continue to treat them as distinct transitions / state families unless a later
  contract says otherwise.
- **Plan as commitment support vs execution artifact**: a distinction is emerging between
  commitment/project structure and generated execution plans. The ontology should likely separate
  these more clearly.
- **Source as artifact-role vs emitter attribution**: the term `source` is overloaded between
  epistemic role and operational attribution; future revisions should keep those meanings distinct.
- **System artifact subclasses**: `Receipt Artifact`, `Mirror Artifact`, and `Execution Artifact`
  may need explicit treatment rather than living only under the broader `System Artifact` class.

Runtime evidence gathered from the first seam review:
- `app/ingest/vault_alpha.py` treats the vault note as a distinct ingest path with:
  - frontmatter UUID as canonical identity,
  - mirror UUID only as healing/provenance support,
  - a dedicated mirror path under `System/Metadata/VaultMirror`,
  - and repeated `kind="note"` projections into runtime stores and indexes.
- `app/planner/schema.py` models `Plan` as an execution artifact with `source_object_uuid`,
  `trigger`, and step kinds such as `agent_call`, `tool_call`, and `decision`; this is much closer
  to an execution plan than to a human project or commitment structure.
- `app/promotion/consumer.py` and `app/services/note_update.py` currently realize promotion mainly
  as a frontmatter/store mutation of `review_state`, even when the payload language refers to
  `maturity` or promotion intent. This supports keeping `review`, `promotion`, and `maturity`
  distinct in the ontology even if the runtime currently compresses them.
- `app/services/note_log.py` defines the mirror path as a canonical per-note log location, but the
  implementation is still thin. This supports separating `Mirror Artifact` from richer receipt/log
  artifacts in later ontology passes.

These are refinement points, not evidence that the ontology direction is wrong.

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

The canonical ontology has six top-level layers:
1. Actors
2. Artifacts
3. Commitment structures
4. Cognitive and creative operations
5. Metacognitive layer
6. Provenance and accountability

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

## 2. Artifacts

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

A vault note is a human-facing editable work artifact in the warm plane.

It is a special case of work artifact that deserves explicit treatment because the active system
already treats it as a distinct contract surface:
- it is directly readable and editable by the human,
- it carries the most important human-visible identity/provenance markers,
- and it is projected into multiple runtime representations without being reducible to them.

### Source Artifact

A source artifact is a cognitive artifact used as evidence, grounding, memory support, or reference.

Important:
- "source" is often a role played by an artifact in context, not always its intrinsic type.

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

This class is intentionally broad for now.
Later revisions may split out narrower specializations such as:
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

## 3. Commitment structures

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

## 4. Cognitive and creative operations

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

## 5. Metacognitive layer

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

## 6. Provenance and accountability

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
3. The system must support creative work, knowledge work, planning, reflection, and memory, not only retrieval.
4. Commitment structures are first-class; the domain is not artifact-only.
5. Ask / Q&A is a narrow operational surface, not the center of the ontology.
6. Roles, states, and transitions must not be confused with entity types.
7. Provenance, receipts, and authority boundaries are part of the domain itself, not afterthought metadata.
8. The ontology must remain implementation-agnostic; schema and runtime terms may represent it, but may not redefine it.

## Sources

- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/ARCHITECTURE.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- David Chalmers & Andy Clark, "The Extended Mind"
- Edwin Hutchins, distributed cognition framing
- cognitive offloading / external memory literature
- self-regulated learning and writing-to-learn literature
- second-brain / workflow practice (including GTD-like commitment handling)
