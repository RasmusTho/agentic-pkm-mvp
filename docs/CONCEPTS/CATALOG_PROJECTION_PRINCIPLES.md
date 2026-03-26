State: Concept contract companion (provisional catalog and path-family principles).

# Catalog Projection Principles

## Purpose

This document defines the current design posture for hierarchical catalog structure and path
families.

It does **not** freeze the final vault taxonomy.
It exists to ensure that future catalog work:
- follows the human-first ontology already established in the repo,
- stays compatible with local files and portable paths,
- takes concrete inspiration from the current icon-prefixed core layout already used in tests and
  vault bootstrap flows,
- and remains flexible enough to evolve.

Related documents:
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
- `docs/PROJECT_KERNEL.md`

## Current default projection posture

The repo already carries a small central root layout in its vault bootstrap/test posture:
- a system root,
- an inbox/capture root,
- and a workbench/active-work root.

In current defaults these roots are icon-prefixed so they are:
- visually scannable,
- stable as navigation anchors,
- and clearly different in function.

This should be understood as a **current default projection**, not as the whole ontology.

The important claim is narrower:
- the system benefits from a small number of obvious top-level functional anchors,
- and those anchors should be easy to recognize in a human filesystem.

## Why the current root layout is directionally right

The existing root triad is directionally strong because it reflects three distinct jobs:

- **System**
  configuration, runtime support, receipts, and operational notes

- **Inbox**
  low-friction capture and watcher-facing intake

- **Workbench**
  active human work, drafting, and ongoing manipulation

This is useful because it organizes the vault around functions the user can recognize immediately,
without forcing the whole ontology into a single early taxonomy.

## Design principles

### 1. A small set of top-level anchors should reflect human function

Top-level roots should exist because they support a distinct cognitive or operational job, not
because they are convenient buckets for every future classification need.

### 2. Root folders are navigation anchors, not full semantic truth

The root layout should stay legible and stable.
It should not attempt to encode:
- all context relations,
- all artifact roles,
- all project structure,
- or every future distinction the ontology may need.

### 3. Icon-prefixing is acceptable when it improves human scanability

The current icon-prefixed roots are justified pragmatically:
- they are easy to recognize,
- easy to keep visually distinct,
- and they work as durable anchors in a human-facing file tree.

The icons are therefore a UI/navigation aid, not the ontology itself.

### 4. Path families should be few, stable, and understandable

Catalog structure should prefer a small number of stable path families over a large number of brittle
semantic folders.

That means:
- clearer defaults,
- less churn,
- and easier cross-device use.

### 5. New path families should be added only when they represent a genuinely different job

A new root or path family should exist only when it solves a clear problem that cannot be handled by:
- existing roots,
- richer metadata,
- relations,
- or higher-level views.

### 6. Active defaults can be pragmatic before they are final

It is acceptable to have a current default root structure before the full long-term catalog model is
finished, as long as:
- the defaults are explicit,
- path semantics stay limited,
- and migration remains possible.

## Likely path-family levels

The repo should think in terms of path families rather than pretending every path segment is equally
ontological.

The most useful levels are likely:

### Root anchors

Small number of top-level functional surfaces such as:
- system,
- inbox,
- active workbench,
- and possibly later retained-material families.

### Collection or working area

A narrower grouping that helps human organization, such as:
- project area,
- topic area,
- source collection,
- or bounded domain/scope grouping.

### Artifact leaf

The actual file or artifact path.
This should preserve:
- stable identity,
- readable naming,
- and portable path behavior.

## What should probably not drive path directly

The catalog should avoid making path depend directly on:
- current salience,
- current actionability,
- transient review queue status,
- personal significance,
- or other meanings that are relational, projected, or likely to change often.

Those belong better in:
- metadata,
- relations,
- views,
- receipts,
- or search/ranking logic.

## Current recommendation for vault bootstrap

For new vault initialization, the repo should continue to treat the current icon-prefixed root
layout as the bootstrap default.

That means:
- the default should be represented in settings/templates,
- initialization code should create a vault layout note and root folders from those defaults,
- and runtime path resolution should be able to discover those defaults without relying on hardcoded
  folder literals in code.

This keeps the current functional projection visible while avoiding hard semantic lock-in.

## What this document does not decide yet

This document does **not** yet decide:
- the full long-term retained-material root strategy,
- whether context/sphere-specific storage families deserve their own roots,
- whether project-first or collection-first organization should dominate below the root level,
- or the final migration strategy from current defaults to any richer future taxonomy.

Those should come later, after more use and after the artifact-dimension model has matured further.
