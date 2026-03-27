State: Concept contract (archive/retention function; terminology still provisional).

# Archive / Retention Function Contract — long-horizon memory and source continuity

## Purpose

This document defines the archive/retention function in human terms.

The file path keeps the older `archive_brain` naming for continuity.
Current repo language in this document often uses `retention surface`, but that should be read as
provisional working language rather than as a field-settled canonical term.
See `docs/research/cognitive-semantics-literature-memo.md`.

It exists to answer:
- why the system needs a retained-material function at all,
- which human problems it solves,
- how it differs from the current repo working concept of a writing surface,
- what kinds of artifacts belong there,
- and which functions must survive even if storage or retrieval implementations change.

This is not primarily a storage or indexing spec.
It is a function and ontology contract.

Related documents:
- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`

## Why the archive / retention function exists

Human cognition is limited:
- working memory is narrow,
- active attention is scarce,
- and not everything worth keeping can or should be rewritten into notes immediately.

The user also works across long time horizons.
Material that is not active today may still matter later for:
- writing,
- learning,
- research,
- projects,
- reflection,
- hobby work,
- audit,
- and personal continuity.

The archive / retention function exists so that useful material can remain cognitively available without
requiring that everything first be transformed into active, hand-curated note form.

## Core claim

The archive / retention function is a first-class cognitive function for preserving, rediscovering,
citing, and reusing source-rich material over long time horizons.

It is part of the human second-brain environment itself, not merely a hidden storage subsystem.

## Problems solved

The archive / retention function helps solve problems such as:
- finding something again after once having found it,
- preserving source material that exceeds active note-taking bandwidth,
- keeping evidence and provenance available for later judgment,
- supporting delayed understanding, where something is kept now and interpreted later,
- retaining project and life material beyond the horizon of current attention,
- and reducing the pressure to prematurely rewrite or summarize everything in order to keep it.

## What the current repo calls the retention surface

In current repo working language, the retention surface is:
- a durable retained-material surface,
- a source-oriented retention and retrieval surface,
- a place for heterogeneous materials that may become useful later,
- and a support for long-horizon continuity across work, learning, projects, and life domains.

Typical retained materials include:
- PDFs and documents,
- web captures and reference files,
- emails or messages kept as evidence or memory support,
- media,
- project artifacts that are important to retain even when they are not active notes,
- hobby/reference collections,
- and other source-like objects whose value may emerge or return later.

## What the current repo's retention-surface language does not mean

The archive / retention function is not:
- a dumping ground whose contents are effectively lost,
- merely low-level storage with no human cognitive function,
- a replacement for active writing and note work,
- a demand that every retained object be equally organized or equally visible,
- or proof that all meaningful material should be flattened into one representation.

This distinction is not about "cold" versus "hot" access.
It is about different cognitive jobs:
- active writing and manipulation,
- versus retained availability for later rediscovery, evidence, and reuse.

## Relationship to writing artifacts

The current repo working labels `writing surface` and `retention surface` describe different
functions:

- Writing surfaces support active writing, manipulation, synthesis, and ongoing human-authored work.
- The current repo's `retention surface` language points to preservation, rediscovery, citation,
  inspection, and later reuse.

These functions should cooperate without collapsing into each other.

Important consequences:
- retained material does not need to become a note in order to remain useful,
- notes do not need to become retained artifacts in order to remain durable,
- and moving from retained material into active writing is a meaningful transition, not a trivial
  copy.

## Archive / retention artifact roles

Within the ontology, this function most often carries:
- `Retained Artifact`,
- `Source Artifact`,
- and sometimes `Primary Human Artifact` when a retained item is itself directly meaningful to the
  human over time.

Examples of the last case include:
- a directly read reference document,
- an important letter,
- a durable project brief,
- or a human-authored file that remains meaningful even outside the current runtime.

The key distinction is functional:
- retained artifacts are kept for long-horizon reuse,
- source artifacts are used as evidence or grounding,
- primary human artifacts remain directly understandable to the human.

One artifact may satisfy more than one of these descriptions.

## Core archive / retention operations

The archive / retention function should support at least these operations:

- **Preserve**: keep material without forcing premature transformation.
- **Rediscover**: find something again from partial memory, vague clues, or later need.
- **Inspect**: preview or examine source material while preserving provenance.
- **Cite**: use archive material as evidence or grounding without laundering it into unattributed claims.
- **Extract**: take a bounded excerpt or reference when needed.
- **Materialize**: intentionally bring something from retained material into active writing as a
  note,
  excerpt, synthesis, or project artifact.
- **Reuse**: let earlier material support later work, learning, writing, or creativity.

## Contract rules (must hold)

1. **The archive / retention function is first-class.** It must be treated as a real cognitive function of the system, not as a secondary overflow bucket.
2. **Retention usefulness does not depend on note conversion.** Retained material may remain cognitively useful while still being retained material.
3. **Provenance must survive reuse.** Retrieval, citation, extraction, and materialization must preserve intelligible links back to the retained source.
4. **Writing and retention have different jobs.** Their relationship must be cooperative, not reductive.
5. **Heterogeneity is expected.** This function may contain mixed formats, varying levels of structure, and material whose future value is not yet clear.
6. **Re-entry from weak memory matters.** The system must support later rediscovery even when the human only partially remembers what exists.
7. **Retention behavior remains bounded by contextual integrity, operational scope, explicit cross-scope allowances, and trust where those constraints apply.** First-class does not mean unbounded.
8. **Derived structures remain subordinate.** Indexes, embeddings, mirrors, and summaries may support this function, but they do not replace the retained artifacts.
9. **Long-horizon continuity matters.** Retained material must remain usable across years, devices, and evolving implementations.

## Boundary with archive exposure

This document defines what the archive / retention function is for.

`docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md` defines something narrower:
- how retained material may be exposed safely into other human workflows,
- what discovery, preview, citation, and materialization mean,
- and how operational-scope, cross-scope, and trust constraints protect against accidental leakage or laundering.

The distinction matters:
- this contract is about cognitive function and ontology,
- the exposure contract is about bounded access and safety.

## Sources

Internal:
- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`

External framing sources:
- [Risko et al., "Varieties of Offloading Memory: A Framework"](https://academic.oup.com/book/59599/chapter/503179878)
- [O'Hara et al., "Memories for Life: A Review of the Science and Implications for Design"](https://kieronohara.com/wp-content/uploads/2023/11/memories-for-life.pdf)
- [Gemmell et al., "Supporting Human Memory with a Personal Digital Lifetime Store"](https://www.microsoft.com/en-us/research/publication/supporting-human-memory-personal-digital-lifetime-store/)
- [Jones et al., "Information Behaviour That Keeps Found Things Found"](https://www.microsoft.com/en-us/research/publication/information-behaviour-keeps-found-things-found/?locale=zh-cn)
- [Zhang & Norman, "Representations in Distributed Cognitive Tasks"](https://pages.ucsd.edu/~scoulson/203/zhang.pdf)
- [Kirsh & Maglio, "On Distinguishing Epistemic from Pragmatic Action"](https://philpapers.org/archive/KIRODE.pdf)
