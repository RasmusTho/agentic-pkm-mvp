State: Working requirements scaffold derived from the human-function docs.
Doc role: Plan
Authority: Operational translation layer from user needs and human flows into user stories, requirement themes, and acceptance-oriented checkpoints; subordinate to the concept contracts.

# User Stories and Requirements

## Purpose

This document translates the human-first function documents into a format that can be used for:
- feature planning,
- acceptance criteria,
- ontology-driven modeling decisions,
- and implementation prioritization.

It is intentionally more operational than:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`

But it remains upstream of detailed implementation tickets or schemas.

## How to use this document

Recommended sequence:
1. Start with `docs/HUMAN-FLOWS.md` for the overall human function.
2. Use `docs/CONCEPTS/USER_NEEDS_MODEL.md` to identify the exact user need involved.
3. Use this document to derive:
   - user stories,
   - requirement themes,
   - acceptance checks,
   - and ontology implications.
4. Only then derive implementation work.

## Structure

Each area below contains:
- user need,
- representative user stories,
- requirement implications,
- and modeling/ontology implications.

## 1. Capture

### User need

The user needs to get thoughts, obligations, fragments, and sources out of working memory before
they disappear.

### User stories

- As a user, I want to capture a thought quickly so I do not lose it before I decide what it is.
- As a user, I want to capture a source or reference so I can revisit it later with provenance intact.
- As a user, I want to capture a fragment without being forced to fully classify it immediately.

### Requirement implications

- capture must be low-friction,
- incomplete capture must remain possible,
- later clarification must be supported,
- and captured material must remain recoverable.

### Ontology implications

- not everything captured starts as stable knowledge,
- open loops and creative fragments must remain first-class,
- source artifacts and work artifacts must remain distinguishable.

## 2. Retrieval and orientation

### User need

The user needs to recover relevant material and regain context after time or interruption.

### User stories

- As a user, I want to find the material that matters for my current work without searching blindly.
- As a user, I want to return after interruption and quickly see what I was doing and why.
- As a user, I want retrieved answers to preserve provenance so I can judge whether to trust them.

### Requirement implications

- retrieval must support orientation, not only answer generation,
- provenance must remain visible,
- and restart cost after interruption should be reduced.

### Ontology implications

- retrieval operates over projections, but must remain interpretable in terms of artifacts and
  sources,
- provenance cannot be optional.

## 2A. Archive and cold-brain work

### User need

The user needs archived materials such as PDFs, emails, media, and project files to remain usable
as first-class sources without being forced into note form.

### User stories

- As a user, I want to retrieve an archived source without first converting it into a note.
- As a user, I want to cite or reuse archive material while keeping provenance intact.
- As a user, I want archive material to support writing, learning, and projects without becoming a
  dumping ground or disappearing from the active system.

### Requirement implications

- archive material must remain retrievable as a first-class source surface,
- citation and preview must be possible without forced materialization into warm notes,
- and archive use must preserve provenance, domain boundaries, and exposure rules.

### Ontology implications

- cold/archive artifacts must remain first-class,
- source usefulness must not depend on note-conversion,
- and archive exposure is a real domain function, not only a storage concern.

## 3. Knowledge development

### User need

The user needs to move from raw material toward clearer, more reusable understanding.

### User stories

- As a user, I want to refine an idea over time without losing its earlier context.
- As a user, I want some material to become durable and reusable when it earns that standing.
- As a user, I want review posture and maturity to stay intelligible rather than collapsing into one status.

### Requirement implications

- standing and review posture must remain distinguishable,
- concept development must be gradual,
- and durable knowledge must remain traceable to sources or prior work.

### Ontology implications

- `maturity` and `review_state` must remain distinct,
- promotion must remain a transition rather than a flat status flag.

## 4. Commitment support

### User need

The user needs to manage projects and commitments without carrying them all in memory.

### User stories

- As a user, I want to distinguish between a project and its next action.
- As a user, I want to preserve waiting states so blocked work does not disappear.
- As a user, I want review cycles that let me restore trust in my commitments.

### Requirement implications

- projects, next actions, waiting, and review cycles must be representable,
- actionability must be distinguishable from general concern,
- and recurring review must be supported conceptually even before all runtime features exist.

### Ontology implications

- commitment structures must remain first-class,
- execution plans must not replace human commitments.

## 5. Learning

### User need

The user needs help learning in a way that compounds over time.

### User stories

- As a user, I want sources and understanding to stay linked so I can revisit how I learned something.
- As a user, I want to notice what I do not yet understand.
- As a user, I want previous learning to be recoverable and revisable rather than frozen or lost.

### Requirement implications

- source-to-understanding continuity matters,
- reflective revisiting matters,
- and partial understanding must remain representable.

### Ontology implications

- reflective artifacts and source artifacts must remain distinct but related,
- metacognitive states matter.

## 6. Creative work

### User need

The user needs a space for generative material that is not prematurely forced into stable knowledge
or task structures.

### User stories

- As a user, I want to keep a fragment even when I do not yet know what it becomes.
- As a user, I want to revisit and recombine creative material later.
- As a user, I do not want exploratory material to be treated as finalized knowledge by default.

### Requirement implications

- exploratory material must remain low-friction,
- premature stabilization should be avoided,
- and creative artifacts must remain developable over time.

### Ontology implications

- creative artifacts must remain first-class,
- not all artifact development is knowledge maturation.

## 7. Hobby / RPG work

### User need

The user needs support for worlds, campaigns, characters, scenarios, and other hobby structures
that persist and evolve over time.

### User stories

- As a user, I want campaign and lore material to stay coherent across time.
- As a user, I want to separate exploratory ideas from more settled world material.
- As a user, I want inspiration, prep, reference, and active session material to remain navigable together.

### Requirement implications

- the system must not assume only work/private or only factual knowledge use,
- hobby continuity is a real use case,
- and world-based material needs both exploration and structure.

### Ontology implications

- creative and project artifacts must support hobby/RPG realities,
- domain boundaries remain important.

## 8. Trust and accountability

### User need

The user needs help without losing authorship, control, or intelligibility.

### User stories

- As a user, I want to know whether something is a suggestion or an accepted durable change.
- As a user, I want to inspect what the system did and why.
- As a user, I want uncertain situations to degrade safely rather than silently overreach.

### Requirement implications

- receipts must remain inspectable,
- silent meaning-changing writes are disallowed,
- and uncertain cases should default toward suggestion, visibility, and reversibility.

### Ontology implications

- `Receipt` remains first-class,
- `Delegation` and `Authority Boundary` remain first-class,
- mirror and receipt remain distinct.

## 9. System evolution and modularity

### User need

The user needs the system to remain changeable over time because not all future needs are known in advance.

### User stories

- As a user, I want the system to evolve with my practice instead of locking me into an early model.
- As a user, I want major capability areas such as memory support to be improvable without replacing the whole system.
- As a user, I want transitional periods to remain usable while some parts of the system are more mature than others.

### Requirement implications

- major capability areas should remain replaceable or extensible in principle,
- the system should preserve continuity across iterative change,
- and improvements must be judged by whether they preserve human value rather than whether they preserve one current mechanism.

### Ontology implications

- human functions must remain more stable than implementation modules,
- module boundaries should serve evolvability rather than become domain truth,
- and artifacts must remain more primary than supporting mechanisms.

## 10. Multi-device local-first access

### User need

The user needs access across devices without abandoning local files as the primary surface of ownership.

### User stories

- As a user, I want to use the system from multiple devices even if they are not perfectly identical at all times.
- As a user, I want synchronization to catch up later rather than requiring constant global consistency.
- As a user, I want satellite devices or narrower device roles to remain legitimate parts of the system.

### Requirement implications

- local artifact ownership must remain primary,
- eventual synchronization must be acceptable where appropriate,
- device roles may differ,
- and cross-device use must preserve intelligibility rather than pretend all devices are the same.

Core continuity functions should remain available even on narrower devices.

### Ontology implications

- the system must distinguish core user-facing continuity from internal synchronization mechanics,
- local artifacts remain primary even when distributed,
- and satellite-like configurations are compatible with the ontology if they preserve continuity and trust.

## 11. Contextual integrity and controlled overlap

### User need

The user needs different life spheres and situated contexts to remain cognitively distinct because
they support different role identities, responsibilities, and ways of working.

### User stories

- As a user, I want work and RPG/private contexts to stay different enough that they do not contaminate each other by default.
- As a user, I want recurring overlap between spheres and contexts to be possible when it reflects real overlap in my life.
- As a user, I want repeated cross-scope reuse, when it is needed operationally, to feel intentional and understandable rather than accidental.

### Requirement implications

- operational scope separation must support contextual integrity rather than mere isolation,
- reusable overlap across spheres and contexts must be possible,
- and repeated cross-scope reuse, when needed, must remain explicit, bounded, and reviewable.

### Ontology implications

- spheres and contexts describe human belonging and situated use more faithfully than one flat domain term,
- shared participation is the primary overlap relation,
- operational scope remains a narrower runtime boundary,
- and explicit cross-scope allowances are bounded permission structures rather than the main mental model of overlap.

## 12. Artifact longevity and system independence

### User need

The user needs central artifacts to remain understandable and usable beyond the lifespan of the current system.

### User stories

- As a user, I want my central notes and artifacts to make sense even if this implementation disappears.
- As a user, I want richer metadata and connections when useful, but I do not want them to be required for basic intelligibility.
- As a user, I want the system to be something my artifacts survive, not something they are trapped inside.

### Requirement implications

- central human artifacts must remain directly comprehensible,
- derived metadata and connections may be more system-specific only if they are non-authoritative or rebuildable,
- and core meaning must not depend on hidden runtime state.

### Ontology implications

- primary human artifacts must remain more durable than system support structures,
- mirrors, indexes, and metadata layers remain downstream,
- and system mortality must not imply artifact mortality.

## Cross-cutting requirement themes

These themes recur across most user needs:
- low-friction capture,
- recoverability over time,
- provenance visibility,
- accountability,
- domain sensitivity,
- contextual integrity,
- reversibility,
- artifact longevity,
- gradual clarification,
- support for interruption and return,
- support for both structured and exploratory work.

## Next use

This document should next be used to produce one or more of:
- prioritized product requirement groups,
- acceptance criteria by scenario,
- ontology coverage checks,
- implementation-track requirement maps,
- or updates to `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`.
