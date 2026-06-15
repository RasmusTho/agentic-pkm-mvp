State: Concept contract companion (context model, artifact dimensions, and catalog projection discipline).

# Context and Artifact Dimensions

## Purpose

This document exists to support further development without prematurely freezing either:
- the final context ontology,
- the final artifact metadata model,
- or the final filesystem/catalog structure.

It answers:
- which distinctions seem semantically important,
- which of those should likely become explicit metadata versus relations or derived projections,
- how overlapping human context can coexist with a MECE filesystem tree,
- and how a future hierarchical catalog structure can remain pragmatic without becoming the whole
  ontology.

This document is upstream of:
- detailed schema choices,
- final path conventions,
- and any strict filesystem taxonomy.

It should be read after:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`

and before:
- final ontology hardening,
- storage/path contracts,
- and implementation-specific catalog rules.

For the current provisional path-family posture, see:
- `docs/CONCEPTS/CATALOG_PROJECTION_PRINCIPLES.md`

## Why this document is needed

The system must eventually store artifacts in a real filesystem.
A filesystem requires:
- one concrete tree,
- one concrete location per stored file at a time,
- stable naming rules,
- and deterministic path behavior.

Human life and human meaning do not behave like that.
They are often:
- overlapping,
- re-used across spheres,
- role-sensitive,
- and not cleanly MECE.

If we collapse those two facts into one model, we get the wrong result either way:
- the ontology becomes too rigid because it starts inheriting filesystem constraints,
- or the filesystem becomes unstable because it tries to encode every semantic nuance.

This document exists to keep those layers separate.

## Core claim

The system needs at least three distinct modeling layers here:

1. **Human context model**
   What part of life, role, concern, or practice something belongs to or matters within.

2. **Artifact dimension model**
   What kind of artifact something is, what function it serves, and which durable descriptors or
   relations matter for later use.

3. **Catalog projection model**
   How a concrete filesystem tree, vault layout, or syncable storage structure organizes artifacts
   for practical reasons.

These layers must inform each other, but they must not be silently collapsed.

## Human context is not the same thing as storage scope

The literature and the current user model both suggest that lived context is not fully captured by
one exclusive bucket.

Useful distinctions include:
- overlapping spheres,
- situated contexts,
- role identities,
- operational scopes,
- shared participation across overlapping parts of life,
- and explicit cross-scope allowances where runtime permissions need to be durable.

This means:
- one artifact may matter in several spheres,
- one role identity may cut across several spheres,
- and one operational scope may be narrower than the full human meaning of the artifact.

Therefore:
- a future filesystem tree may need one primary home for an artifact,
- while the ontology still allows multiple contextual relations around that artifact.

## Dimension families

The system likely needs several families of artifact-facing dimensions.
They do not all belong to the same layer.

### 1. Artifact class and function

These answer questions such as:
- what kind of artifact is this,
- what job is it meant to do,
- and how should the human relate to it?

Examples:
- vault note,
- retained artifact,
- source artifact,
- project artifact,
- reflective artifact,
- creative artifact,
- receipt artifact,
- execution artifact.

These are relatively good candidates for stable explicit representation.

### 2. Trust, provenance, and authorship

These answer questions such as:
- who authored or emitted this,
- what kind of evidence stands behind it,
- and under what authority can it be used or changed?

Examples:
- human-authored,
- imported,
- machine-generated,
- grounded in a source artifact,
- suggested versus asserted versus applied.

These are good candidates for explicit contracts and metadata because they are safety-critical.

### 3. Commitment relations

These answer questions such as:
- does this support a project,
- is it a next action,
- is it waiting,
- is it under review,
- does it represent or advance a commitment?

These are important, but they often belong more to commitment structure than to artifact essence.

### 4. Context relations

These answer questions such as:
- what spheres matter here,
- which role identities are relevant,
- what operational scope is active,
- and what overlap relations, allowances, or boundaries apply?

These are often many-to-many relations rather than simple single-value fields.

### 5. Time and standing

These answer questions such as:
- is this fleeting or durable,
- what is its long-horizon value,
- what is its maturity,
- what review posture does it currently have?

Some of these are already covered by existing state contracts.
Others may remain partly interpretive and should not be over-encoded too early.

### 6. Salience and centrality

These answer questions such as:
- how mentally near this feels right now,
- how central it is to the person's self-understanding,
- and how much it currently matters in lived practice.

These are usually poor candidates for hard intrinsic artifact metadata.
They are more often:
- relations,
- derived projections,
- or user-facing ordering signals.

### 7. Interruptibility

This family is different from the six above: it does not describe an *artifact*, it describes the
*human's current state* — how interruptible the person is right now. It is named here because the
Contextual Relevance Engine reads the same context model for two different purposes, and this is the
second one.

It answers questions such as:
- how interruptible is the human right now,
- what would it cost to reach out at this moment versus wait,
- and is this a state in which the system must not reach out at all?

It is grounded in the existing cognitive-load surface rather than inventing a parallel one:
`docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` already names the human-facing load areas
(working-memory, reading, decision/confirmation, orientation/resumption, resurfacing) and the
non-authoritative, scarce, "reduce friction, not intelligence" posture. Interruptibility is the
reach-out-facing reading of that same load picture: low load (e.g. at home, no meeting active) →
higher tolerance → a lower bar to surface; high load (a 1-1, deep focus) → lower tolerance → a higher
bar.

**One context model, two consumers.** The relevance reading of the context model asks *what to
surface*; the interruptibility reading asks *whether and how to reach out*. They are deliberately
separated so intelligence about *what matters* never relaxes the discipline about *when to intrude*
(`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §3.1, §3.3). The moment artifact carries an
interruptibility snapshot for provenance, but the reach-out decision belongs to the scarcity gate
(CRE-02), not to the artifact.

**Bands are seeded, then learned.** The interruptibility-affecting bands that matter — home /
meeting / focus / sleep — are *seeded by the human* and then refined from observed engagement vs.
dismissal. They are illustrative anchors, not a fixed closed enum; the dimension must stay open and
extensible like the rest of the context model.

**Zero-tolerance states are a hard floor.** Some states carry **zero tolerance** for reach-out:
**sleep** and **declared do-not-disturb**. In a zero-tolerance state the system never pushes,
regardless of urgency — this is a deterministic, non-negotiable floor, not a derived preference. When
interruptibility is *uncertain*, the safe default is the higher threshold (silence). The derived load
reading adapts; the declared zero-tolerance floor does not.

Most of interruptibility is therefore **derived/provisional** (the current load → tolerance reading),
but its floor is **explicit and durable** (the human's declared sleep / do-not-disturb states, which
are authoritative never-interrupt constraints). It must never be encoded as fast-changing path or
storage metadata.

## What should likely be explicit vs derived

### Likely explicit and durable

- artifact class/function
- provenance/trust-critical markers
- stable identity
- timestamps
- explicit commitment structures when intentionally represented
- bounded operational scope when the user wants it represented
- state fields with already-defined contracts such as `maturity` and `review_state`
- declared interruptibility floors (sleep / do-not-disturb), which the human sets and which act as
  durable, authoritative never-interrupt constraints

### Likely relational rather than intrinsic

- sphere membership
- role-identity relevance
- shared participation
- explicit cross-scope allowances when intentionally represented
- project support relations
- source-grounding relations

### Likely derived or provisional

- attentional salience
- current mental distance
- current navigational centrality
- access likelihood
- personal significance unless explicitly declared
- current interruptibility (the derived load → tolerance reading), bounded below by the declared
  zero-tolerance floor noted above

## MECE tree, non-MECE meaning

The system will likely need a MECE hierarchical catalog structure for actual file storage.
That is not a problem by itself.

The problem only appears if we let that tree pretend to be the whole meaning model.

The right posture is:
- the storage tree may be MECE,
- the semantic model does not need to be,
- and the tree should be treated as a pragmatic projection over richer meaning.

One artifact may therefore have:
- one primary stored location,
- several contextual relations,
- several retrieval views,
- and several future reuse paths,
without requiring duplication or semantic flattening.

## Principles for a future hierarchical catalog structure

### 1. One primary home, not one total meaning

Each stored artifact should have one primary canonical home in the filesystem.
That does **not** imply:
- one sphere only,
- one use only,
- or one meaning only.

### 2. Path should encode only a small, stable subset of meaning

The path should be based on dimensions that are:
- durable enough,
- understandable enough,
- and operationally useful enough
to justify affecting storage layout.

Good path candidates are things like:
- broad artifact function,
- storage plane / storage family,
- stable collection or source grouping,
- and predictable naming rules.

Poor path candidates are things like:
- current salience,
- temporary project urgency,
- transient role activation,
- current review queue status,
- or other rapidly changing projections.

### 3. Stable identity beats perfect categorization

The system must prefer:
- stable identity,
- understandable provenance,
- and reversible reorganization
over trying to place every artifact in a perfect conceptual slot immediately.

### 4. Low-friction capture beats early taxonomy purity

The catalog structure should not require the human to solve the whole ontology during capture.
It should support:
- rough placement,
- later refinement,
- and progressive clarification.

### 5. Path changes should not be required for every semantic change

If every new relation or reinterpretation requires moving the file, the tree is carrying too much
meaning.

The future design should therefore aim for:
- semantic enrichment without constant relocation,
- and relocation only when the primary home genuinely changes.

### 6. Multiple views should exist above the tree

The filesystem tree is one projection.
The human should also be able to work through:
- search,
- links,
- indexes,
- maps,
- commitment views,
- receipts,
- and other derived navigational surfaces.

### 7. Device and satellite use must remain possible

The tree should support:
- partial replicas,
- device-specific subsets,
- eventual sync,
- and meaningful use even when not every derived structure is present everywhere.

This means the tree must stay:
- portable,
- deterministic enough,
- and understandable without relying on one live database or one full graph view.

## Plausible organizing principles for later catalog work

This document does **not** pick a winner yet, but it makes the choice set clearer.

Possible primary organizing strategies include:
- by broad artifact function,
- by storage family or plane,
- by source/collection lineage,
- by operational scope,
- by project/commitment anchor,
- or a hybrid of these.

A pragmatic hybrid is likely.
The main design question is not "which one is philosophically pure?"
It is:
- which small set of stable principles gives the best tradeoff between human comprehensibility,
  low-friction capture, portability, later evolution, and safe retrieval behavior.

## Recommended posture now

1. Keep context semantics richer than filesystem semantics.
2. Keep artifact dimensions richer than path semantics.
3. Let the future tree be MECE without forcing the ontology to be MECE.
4. Avoid path schemes that depend on fast-changing or relational meanings.
5. Treat directory structure as a projection problem, not the master ontology.
6. Delay any final filesystem taxonomy until the repo has decided which dimensions are truly stable
   enough to deserve path authority.

## What this enables next

This document should make the next steps safer:
- clearer context modeling,
- clearer artifact-dimension modeling,
- safer future frontmatter/schema choices,
- and later path/catalog design that can remain pragmatic without becoming semantically brittle.

It is also the right place to anchor future work on:
- canonical path families,
- path derivation rules,
- collection/grouping semantics,
- and the boundary between filesystem placement and richer metadata/relations.
