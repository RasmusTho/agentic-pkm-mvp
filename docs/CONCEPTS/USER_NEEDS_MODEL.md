State: Concept contract companion (explicit user needs and intended benefits).
Doc role: Core SoT
Authority: Canonical statement of the human needs the system is meant to serve; ontology, product, and implementation docs should derive from this model rather than redefining the needs ad hoc.

# User Needs Model

## Purpose

This document makes the human needs behind the system explicit.

Its role is to answer:
- what the user is trying to accomplish,
- what burdens the system is meant to reduce,
- what kinds of support the user actually needs,
- and what benefits the user should receive if the system is working well.

This is not an implementation document.
It is a stable description of intended human value.

Related docs:
- `docs/HUMAN-FLOWS.md`
- `docs/PROJECT_KERNEL.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`

## How to use this document

Use this document when:
- defining product intent,
- checking whether a proposed feature solves a real human problem,
- deciding whether an ontology distinction matters,
- writing user stories or acceptance criteria,
- or reviewing whether implementation work still serves the intended user value.

Do not use this document to:
- define event schemas,
- define storage layout,
- or justify implementation complexity without a corresponding user need.

## Core framing

The user does not primarily need:
- a database,
- a retrieval pipeline,
- an agent framework,
- or a note automation engine.

The user needs help with cognition, action, learning, creativity, continuity, and trust.

The system exists only insofar as it helps with those things.

## Primary user needs

### 1. Not losing what matters

The user needs to avoid losing:
- ideas,
- obligations,
- insights,
- sources,
- fragments,
- plans,
- and meaningful context.

The user benefit:
- less fear of forgetting,
- less dependence on working memory,
- and greater confidence that important material can be recovered later.

### 2. Being able to think outside the head

The user needs a place where thought can be:
- captured,
- arranged,
- compared,
- revised,
- and developed.

The user benefit:
- better reasoning,
- better writing,
- better synthesis,
- and reduced cognitive overload during complex work.

### 3. Recovering orientation

The user needs to regain orientation after:
- interruption,
- time passing,
- context switches,
- and partial forgetting.

The user benefit:
- lower restart cost,
- less rework,
- and less time spent reconstructing what was already known or intended.

### 4. Managing commitments without mental overload

The user needs help maintaining:
- projects,
- open loops,
- next actions,
- waiting states,
- and review practices.

The user benefit:
- less stress from untracked obligations,
- clearer actionability,
- and more trustworthy follow-through over time.

### 5. Learning in a way that compounds

The user needs support for:
- linking sources to understanding,
- retaining and revising concepts,
- noticing confusion,
- and revisiting prior learning.

The user benefit:
- better long-term understanding,
- better retention,
- and less repeated effort from re-learning the same thing from scratch.

### 6. Creating without premature closure

The user needs room for:
- fragments,
- motifs,
- incomplete drafts,
- speculative structures,
- and half-formed ideas.

The user benefit:
- increased creative continuity,
- less loss of fragile material,
- and better conditions for emergence and recombination.

### 7. Supporting hobby and world-based work

The user needs a system that can also hold:
- campaigns,
- lore,
- world-building,
- characters,
- scenarios,
- and other hobby-specific structures.

The user benefit:
- continuity across long-running creative/hobby efforts,
- less fragmentation,
- and the ability to move between inspiration, notes, planning, and play material.

### 8. Preserving authorship and control

The user needs the system to help without:
- silently changing meaning,
- laundering uncertain material into truth,
- or obscuring who decided what.

The user benefit:
- trust,
- reversibility,
- intelligibility,
- and continued ownership of meaning and commitments.

### 9. Being able to trust system action

The user needs to distinguish:
- what the system knows,
- what it suggests,
- what it did,
- and why it did it.

The user benefit:
- lower fear of hidden damage,
- higher willingness to use automation,
- and better ability to correct mistakes.

### 10. Being able to evolve the system over time

The user needs the system to remain changeable as understanding, practices, and priorities evolve.

This includes:
- not knowing all future needs in advance,
- being able to add or revise capabilities later,
- being able to improve one part of the system without rewriting everything else,
- and being able to keep using the system while parts of it remain transitional.

The user benefit:
- less fear of getting trapped in an early model,
- better long-term fit between the system and lived practice,
- and better conditions for iterative development rather than one irreversible design bet.

### 11. Being able to access the system across devices without abandoning local-first principles

The user needs access from different devices while keeping local files and eventual synchronization as core principles.

This includes:
- being able to work from more than one device,
- tolerating that not every device has the same capabilities at the same time,
- allowing synchronization to catch up later rather than requiring perfect simultaneity,
- and preserving the user's confidence that local artifacts remain primary.

The user benefit:
- continuity across contexts and devices,
- less pressure to centralize everything in one always-online system,
- and better practical fit for real-life use across home, work, travel, and satellite setups.

### 12. Keeping major capabilities modular rather than locked to one solution

The user needs important capability areas, such as memory support, retrieval, and sync, to remain developable rather than frozen into one irreversible implementation choice.

This includes:
- being able to evolve memory modules over time,
- being able to improve sync behavior without redefining the whole system,
- and being able to replace or extend supporting mechanisms while preserving human value.

The user benefit:
- better longevity,
- less architectural lock-in,
- and a clearer path to continuous improvement without abandoning the system's core principles.

### 13. Preserving contextual integrity across role identities and domains

The user needs different life contexts to remain cognitively legible because they correspond to
different responsibilities, tones, expectations, and role identities.

This includes:
- not wanting work and RPG/private contexts to bleed into each other by default,
- wanting the system to support different context-bound modes of self across contexts,
- allowing overlap where it is genuinely useful,
- and keeping that overlap explicit enough that it does not feel like contamination.

The user benefit:
- lower cognitive friction when switching contexts,
- better support for context-specific thinking and behavior,
- and continuity across life domains without collapse into one undifferentiated identity.

### 14. Ensuring central artifacts outlive the current system

The user needs central human artifacts to remain fully comprehensible and usable even if the current system changes radically or disappears.

This includes:
- wanting notes and central artifacts to stay understandable without the runtime,
- accepting that metadata, connections, and machine-side structures may evolve more freely,
- and treating the system as something that may develop or die while the human material remains.

The user benefit:
- confidence in long-term continuity,
- less fear of tool death or stack churn,
- and a clearer distinction between durable meaning and replaceable system support.

## Need clusters by work mode

### Knowledge work needs

The user needs:
- source-grounded retrieval,
- concept development,
- synthesis support,
- durable reference material,
- and traceable claims.

### Archive/source needs

The user needs:
- non-note materials to remain usable as first-class sources,
- archive retrieval without forced conversion into notes,
- provenance-preserving citation and reuse,
- and continuity between archive material and later thinking or output.

### Commitment/GTD needs

The user needs:
- capture of open loops,
- clarification,
- next-action identification,
- waiting-state handling,
- and recurring review.

### Learning needs

The user needs:
- working representations of what is being learned,
- links between sources and understanding,
- support for reflection,
- and support for revisiting confusion or incomplete mastery.

### Creative needs

The user needs:
- low-friction capture of generative fragments,
- protection against premature closure,
- recombination,
- and support for gradual development.

### Hobby/RPG needs

The user needs:
- coherent continuity across materials,
- support for both canonical and exploratory content,
- and ways to navigate between lore, structure, preparation, and inspiration.

### Reflective needs

The user needs:
- self-observation,
- after-action reflection,
- periodic review,
- and ways to calibrate whether the system still reflects lived reality.

### Evolution and portability needs

The user needs:
- a system that can evolve with changing practice,
- modular capability areas that are not locked too early,
- cross-device continuity without requiring strict real-time sameness,
- preservation of local-first artifact ownership,
- contextual integrity across role identities and domains,
- and central artifacts that remain understandable beyond the current system.

## Needs the system must not accidentally destroy

The system must not optimize one need by damaging another.

Examples:
- better retrieval must not destroy authorship,
- stronger automation must not destroy accountability,
- clearer structure must not destroy creative openness,
- stronger commitment handling must not flatten all work into tasks,
- cross-domain continuity must not destroy domain separation,
- cross-domain overlap must not destroy contextual integrity,
- greater modularity must not destroy usability,
- cross-device support must not destroy local ownership or intelligibility,
- and richer metadata must not become a prerequisite for understanding central artifacts.

## Design test

A feature, ontology choice, or implementation direction is aligned only if it can answer:
- which user need does this serve,
- what concrete burden does it reduce,
- what user benefit should result,
- and what other user need must it avoid damaging?

If those questions cannot be answered clearly, the work is not yet well grounded.
