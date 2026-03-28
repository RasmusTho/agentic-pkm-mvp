State: Concept contract companion (cognitive relevance axes, overlapping spheres, and scope clarification).

# Cognitive Axes and Spheres — relevance, centrality, salience, horizon

## Purpose

This document exists to prevent several different human phenomena from being collapsed into one
label.

It answers:
- which kinds of "importance" the system may need to represent,
- which of those are artifact attributes versus relations or projections,
- why overlapping life spheres are not well-described by strict either/or domains,
- and how these ideas should relate to the ontology without prematurely freezing implementation or
  metadata choices.

This document is upstream of detailed ontology and requirements language.
It should be read after:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`

and before:
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`

Terminology note:
- this document distinguishes underlying cognitive phenomena before final semantic lock-in,
- and some current repo terms such as `sphere`, `context`, `domain`, `writing plane`, and
  `retention plane` remain partly provisional.
- See `docs/research/cognitive-semantics-literature-memo.md`.

## Why this document is needed

The system needs to represent things such as:
- what is mentally near versus far,
- what is central to the self or to a role,
- what matters over long stretches of time,
- what is actionable right now,
- what is deeply integrated into ongoing thinking,
- and what belongs to overlapping parts of life.

Those are not all the same kind of fact.

If we collapse them, we get misleading binaries such as:
- hot vs cold,
- active vs archived,
- domain A vs domain B,
- central vs peripheral as if those were simple file properties.

The result is ontology drift:
- storage metaphors start carrying cognitive meaning,
- rigid scope labels start standing in for lived overlap,
- and transient attention states start being treated as durable artifact essence.

## Core claim

The system needs a small set of cognitive axes, but those axes do **not** all belong to the same
ontological layer.

Some are:
- relatively durable artifact descriptors,
- some are human-artifact relations,
- some are commitment relations,
- some are situational projections,
- and some are about membership in overlapping life spheres rather than exclusive categories.

Therefore these concepts should not be modeled as one flat metadata bundle.

## The main axes

### 1. Attentional salience / mental distance

Question answered:
- how mentally near, activated, or ready-to-hand something is right now.

This is closest to:
- current attention,
- foreground vs background,
- ease of recall,
- recency of engagement,
- and current practical relevance.

Important:
- this is **not** an intrinsic artifact property,
- it is a situational or derived projection,
- and access frequency may be one signal among several, but not the whole meaning.

Ontology status:
- primarily metacognitive / projection-level,
- secondarily representable on artifacts for UX if clearly treated as derived.

### 2. Self-relevance / identity centrality

Question answered:
- how central something is to the person's self-understanding, role identities, life structure, or
  deeply held concerns.

This is closer to:
- identity salience,
- identity prominence,
- personal significance,
- and role-linked meaning.

Important:
- this is not just "importance" in a generic productivity sense,
- and it is not well modeled as a purely artifact-internal property.

Ontology status:
- primarily a human-artifact relation,
- often mediated by role identity, sphere, and life context.

### 3. Temporal durability / horizon

Question answered:
- whether something is expected to matter for minutes, days, months, years, or decades.

This is closer to:
- time horizon,
- expected persistence,
- long-term reference value,
- and future revisit-worthiness.

Important:
- this is more durable than momentary salience,
- but still partly interpretive rather than fully objective.

Ontology status:
- often representable as an artifact-facing descriptor or policy/standing signal,
- but should remain distinct from salience, access frequency, or review posture.

### 4. Integration into thinking

Question answered:
- how far something has been metabolized into the person's own thinking, writing, and conceptual
  network.

This is closer to:
- fleeting vs integrated,
- source capture vs synthesis,
- idea development,
- and note usefulness inside an ongoing thinking practice.

Important:
- this is not identical to truth,
- not identical to review state,
- and not identical to time horizon.

Ontology status:
- often a relation between artifact and the human's thinking practice,
- sometimes partially reflected by artifact maturity or artifact role.

### 5. Actionability / commitment proximity

Question answered:
- how directly something bears on current commitments, next actions, review cycles, or active
  projects.

This is central in GTD and related methods.

Important:
- this usually belongs more to commitment structure than to artifact essence,
- although artifacts may support or represent active commitments.

Ontology status:
- primarily commitment-relation or operational relevance,
- not a stable universal attribute of all artifacts.

## Are these artifact attributes?

Not in any simple or uniform sense.

The cleanest modeling rule is:

### Artifact descriptors

These may reasonably live on artifacts or artifact contracts when stable enough:
- temporal durability / horizon,
- role in thinking practice when intentionally declared,
- certain standing or maturity-like signals,
- explicit sphere memberships when the human wants them represented.

### Human-artifact relations

These should usually not be treated as simple intrinsic artifact properties:
- self-relevance,
- identity centrality,
- role-linked importance,
- personally meaningful value.

They describe how an artifact matters **to someone** in a certain life configuration.

### Situational projections

These should be treated as derived or contextual rather than ontological essence:
- attentional salience,
- mental distance,
- current activation,
- access likelihood,
- foreground/background status.

### Commitment relations

These belong primarily to commitment modeling:
- actionability,
- next-step relevance,
- blocked/waiting status,
- project proximity.

Artifacts may participate in these, but should not be reduced to them.

## Spheres, contexts, and domains

The current `domain` language in the repo may be too rigid if read as the full human semantic
model.

### Sphere

A sphere is an overlapping region of human life, practice, concern, or meaning.

Examples:
- work,
- family/private life,
- health,
- learning,
- writing,
- self-development,
- roleplaying/world-building,
- friendship/community.

Properties of spheres:
- they may overlap,
- they need not be MECE,
- one artifact may belong meaningfully to several spheres,
- and one role identity may cut across several spheres.

### Context

A context is a situated momentary configuration of:
- one or more spheres,
- one or more role identities,
- current commitments,
- current attentional state,
- and current purpose.

Contexts are therefore narrower and more temporal than spheres.

### Domain

`Domain` may still remain useful, but only if treated more narrowly:
- as an operational scope,
- a policy boundary,
- or a deliberately selected working partition.

If kept, `domain` should not silently stand in for the whole human context model.

### Boundary and overlap

Overlap is normal.
What matters is not enforcing MECE purity, but making overlap:
- intelligible,
- reviewable,
- and governable when needed.

This means the system may eventually need:
- overlapping sphere membership,
- narrower operational scopes,
- and explicit boundary rules where the user wants friction or protection.

## Modeling consequences

1. Do not collapse salience, centrality, durability, and actionability into one field.
2. Do not assume all context membership is exclusive.
3. Do not treat access frequency as the meaning of importance.
4. Do not let operational scope labels redefine lived human overlap.
5. Let some signals be projected or derived rather than ontologically primitive.
6. Keep commitment semantics separate from artifact semantics even when the two interact closely.

## Documentation placement

This document belongs in `docs/CONCEPTS/` because it is:
- more stable than a planning note,
- more upstream than schema or runtime modeling,
- and prior to choosing which distinctions become first-class ontology entities versus derived
  projections.

Recommended reading chain:
1. `docs/HUMAN-FLOWS.md`
2. `docs/CONCEPTS/USER_NEEDS_MODEL.md`
3. this document
4. `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
5. `docs/CONCEPTS/LAYERING_MODEL.md`
6. requirement and implementation docs

## Current guidance for the repo

Until this is fully propagated:
- treat `writing/retention/system plane` as provisional working language for exposure surfaces,
- treat `domain` as provisional language for a stricter scope/boundary idea,
- and do not assume those labels exhaust the human semantics of belonging, importance, or
  long-term meaning.

## Sources

Internal:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`

External framing sources:
- [Tiago Forte, PARA](https://fortelabs.com/para/)
- [Tiago Forte on organizing by actionability](https://fortelabs.com/blog/the-box-twyla-tharp-on-project-based-organizing/)
- [David Allen, Horizons of Focus](https://gettingthingsdone.com/insights/horizons-of-focus/)
- [David Allen, Levels of Your Work](https://gettingthingsdone.com/wp-content/uploads/2014/10/Levels_of_Your_Work.pdf)
- [Nick Milo / LYT Glossary](https://blog.linkingyourthinking.com/notes/lyt-glossary)
- [Nick Milo / Maps of Content](https://blog.linkingyourthinking.com/maps/)
- [Nick Milo / MOCs definition](https://blog.linkingyourthinking.com/notes/mocs-%28defn%29)
- [Sönke Ahrens](https://www.soenkeahrens.de/en/takesmartnotes)
- [Zettelkasten Method on fleeting, literature, permanent, and project notes](https://zettelkasten.de/posts/concepts-sohnke-ahrens-explained/)
- [Burke & Stets on multiple identities](https://academic.oup.com/book/44675/chapter/378751007)
- [Role identities arranged by salience](https://academic.oup.com/academicmedicine/article/84/Supplement_1/S135/8353843)
- [Supporting the self-concept with memory](https://academic.oup.com/scan/article/10/12/1684/2502563)
- [Personal digital belongings / personal archives](https://www.microsoft.com/en-us/research/publication/the-long-term-fate-of-our-personal-digital-belongings-toward-a-service-model-for-personal-archives/)
