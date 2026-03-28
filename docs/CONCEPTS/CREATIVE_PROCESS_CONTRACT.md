State: Concept contract companion (creative process, iteration, and exploratory development; implementation-agnostic).

# Creative Process Contract

## Purpose

This document clarifies how the system should understand creative process beyond the existence of
`Creative Artifact` as a class.

It exists to answer:
- how fragments become richer without needing premature closure,
- how creative work differs from both settled knowledge development and commitment execution,
- how motifs, scenes, lore, outlines, and speculative structures evolve over time,
- and how the system should support iteration without flattening ambiguity.

This document is subordinate to:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`

and upstream of:
- `docs/plans/USER_STORIES_AND_REQUIREMENTS.md`
- `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`
- future runtime or UX work for creative support.

## Why this document is needed

The system already recognizes creative work as legitimate, but the ontology is still thinner here
than it is for knowledge development or commitments.

Without a clearer process contract, creative material risks being misread as one of three things:
- immature knowledge that should simply mature,
- unclarified commitments that should become tasks,
- or miscellaneous notes without their own process logic.

That is wrong.

Creative work often depends on:
- preserving ambiguity,
- carrying alternatives in parallel,
- returning to fragments later,
- recombining motifs and materials,
- iterating without forced closure,
- and selectively stabilizing only some parts of a larger evolving body of work.

## Core claim

Creative process is a first-class cognitive process in its own right.

It should not be reduced to:
- knowledge maturation,
- project management,
- or temporary incompleteness on the way to some single final stable form.

Some creative artifacts do become more settled over time.
But the process itself must preserve exploration, iteration, and parallel possibility.

## Canonical distinctions

### Creative fragment

A creative fragment is a partial, suggestive, or exploratory artifact that is valuable before its
final role is known.

Examples:
- motif fragments,
- scene fragments,
- outline pieces,
- speculative notes,
- character seeds,
- setting fragments,
- tone or form experiments.

A creative fragment should not be treated as defective merely because it is incomplete.

### Creative thread

A creative thread is a recognizable line of development that connects related fragments,
alternatives, revisions, motifs, or world elements across time.

Problem solved:
- creative development is often distributed across many artifacts and sessions rather than contained
  in one clean object.

### Iteration

Iteration is a return to creative material in which it is varied, extended, recombined, sharpened,
or otherwise worked further.

Iteration does not imply linear progress.
It may include:
- divergence,
- recombination,
- substitution,
- refinement,
- or deliberate return to earlier variants.

### Revision

Revision is a more directed reshaping of a creative artifact or thread toward a changed or clearer
form.

Revision differs from simple correction:
- it may change tone, structure, emphasis, pacing, framing, or world assumptions,
- and it may preserve creative identity while altering expression significantly.

### World continuity

World continuity is the ongoing coherence of a fictional, game, or hobby world across time, even
while parts of it remain exploratory.

Problem solved:
- creative and hobby work often mixes stable lore, provisional ideas, scenario prep, and active
  session material in one evolving body of work.

World continuity does not require that everything be equally settled.

### Selective stabilization

Selective stabilization is the process by which some creative material becomes intentionally more
settled while other parts remain open, variant, or exploratory.

This matters because:
- a creative world or draft may contain both canon-like material and open possibilities,
- and forcing one maturity posture onto all of it is cognitively harmful.

## What creative process is not

Creative process is not the same as:
- `maturity`,
- `review_state`,
- task completion,
- project closure,
- or temporal validity.

These may still matter around creative work, but they do not define the process.

In particular:
- not every fragment is "immature knowledge",
- not every revision is a review transition,
- and not every creative thread should be pushed toward evergreen-like stabilization.

## Relation to other ontology areas

### Relation to knowledge development

Knowledge development usually aims at clearer, more stable understanding.

Creative development may instead aim at:
- generative richness,
- possibility space,
- evocative coherence,
- usable draft material,
- or playability.

The two can overlap, but they should not be collapsed.

### Relation to commitments

Creative work may participate in projects and commitments, but the creative process itself is not
just a commitment structure.

Examples:
- a campaign prep project may contain creative fragments,
- a writing project may have next actions,
- but the fragments themselves should not be reduced to those commitments.

### Relation to reflection and review

Creative work benefits from reflection, but review here often means:
- revisiting,
- sensing coherence,
- comparing variants,
- noticing what wants development,
- or deciding what should remain open.

This is broader than approval or correctness review.

## Representation posture

The system should support a creative-process posture in which:
- fragments can remain first-class,
- alternatives can coexist,
- threads of development can be followed across artifacts,
- settled and unsettled material can coexist,
- and the system does not force all creative work into note, task, or evergreen knowledge molds.

This does not require one specific metadata model yet.
It does require that future schema, retrieval, and UX work preserve these distinctions.

## Hobby and RPG implications

Hobby and RPG material is a major validating case for this contract.

The system should be able to support:
- world-building,
- lore development,
- campaign continuity,
- scenario preparation,
- character evolution,
- partial canon and provisional ideas living side by side.

That is not a marginal edge case.
It is one of the clearest reasons the creative process needs explicit ontology support.

## Status

This document establishes semantic guardrails, not a final creative workflow engine.

It intentionally leaves open:
- whether creative threads become explicit stored relations,
- how alternatives or variants should be surfaced,
- how much "canon vs provisional" structure belongs in metadata,
- and how creative support should differ across devices or satellites.
