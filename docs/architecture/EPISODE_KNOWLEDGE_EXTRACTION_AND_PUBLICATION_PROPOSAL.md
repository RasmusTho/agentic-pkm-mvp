State: Advisory architecture proposal (2026-07-20). Preserves the full design intent for intelligent episode handling before it can be represented losslessly in the Capability Knowledge Model (CKM). Defines no shipped behavior, changes no CKM schema or runtime contract, and creates no GitHub work.
Doc role: Architecture / capability proposal (pre-CKM, cross-constituent)
Authority: Authoritative only for the proposal's preserved design intent and its promotion conditions. Subordinate to ADR-0044 (Yggdrasil constituents), ADR-0049 (Heimdal ingestion boundary), ADR-0051 (Episode), ADR-0054 (Episode Resolution Engine placement), `docs/CAPABILITY_CONTRACT_MODEL.md`, and current-state docs. Where this proposal and those authorities differ, they win.
Owner: Architecture / CES stewardship
Temporal class: strategic
Review cadence: event-driven (CKM evolution, constituent-boundary decision, or promotion review)
Source of truth: this proposal for the unpromoted design; the cited owner docs for current architecture and shipped reality

# Episode Knowledge Extraction and Publication — Architecture Proposal

## Status and recommendation

This proposal preserves a requested **Episode Intelligence Pipeline**: classify an Episode, select a
domain model and extractor, extract structured knowledge, create knowledge-object candidates, and
publish them to downstream consumers. It is intentionally not simplified to fit today's CKM.

The architecture review does **not** recommend promoting that entire pipeline as one Heimdal
capability. The requested boundary crosses three already-owned responsibilities:

1. **Heimdal** publishes minimized, attributed observations and may contribute single-stream boundary
   hints. It ends at the published observation seam (ADR-0049, ADR-0054).
2. The **Mimer Episode Resolution Engine (ERE)** constructs canonical first-class `Episode` artifacts,
   performs multi-stream fusion, and assigns `episode_ref` (ADR-0051, ADR-0054).
3. **Mimer cognition and governance** interpret Episodes, form knowledge-object candidates, and admit
   any durable knowledge effect.

The recommended future decomposition is therefore:

- retain Heimdal's existing observation-publication responsibility rather than minting a duplicate
  "episode intelligence" capability inside Heimdal;
- introduce **Episode Knowledge Extraction** as the new proposal-class Mimer capability;
- compose it with context building, ERE, and a reusable governed **Knowledge Object Publication
  Pipeline** rather than giving extraction direct mutation authority.

The phrase **Episode Intelligence Pipeline** in this document names that logical composition, not an
atomic capability and not a new constituent. Domain plugins implement the extraction capability;
they are not capabilities in their own right.

This placement is deliberate. A file under `docs/HEIMDAL/` would imply that semantic interpretation
and knowledge creation belong to the sensor constituent. The proposal instead lives under
`docs/architecture/`, the existing home for cross-constituent proposals, and is linked from the
Heimdal index for discoverability.

## Problem Statement

An Episode is not useful merely because its transcript exists. The system must understand what kind
of bounded situation the Episode represents, choose the domain ontology appropriate to that
situation, extract typed knowledge with evidence and confidence, and route the resulting objects to
the consumers able to use them.

A transcript-only or summary-first design loses the distinctions that matter:

- a standup contains status, blockers, and commitments;
- a workshop contains ideas, hypotheses, and experiments;
- an architecture review contains decisions, trade-offs, quality attributes, rationale, and risks.

All three may be meetings and all three may arrive as speech, but they do not share an information
model. Treating them as one generic summary shape discards domain semantics before Mimer can reason
over them.

The current CKM can register a capability node and attach evidence and maturity assessments to it. It
cannot yet represent the composition, domain profiles, plugin implementations, ontology variants,
typed output variants, publication profiles, or stage-level ownership needed by this design. A
flattened CKM entry would therefore create false architectural precision while losing the design's
load-bearing structure.

## Motivation

The proposal enables one reusable pattern across meetings, voice memos, podcasts, lectures, code
reviews, customer interviews, field observations, and later Episode classes not yet known. Its value
comes from keeping two things true at once:

- the processing lifecycle is stable enough to share; and
- the semantics are specialized enough to preserve what each Episode type means.

The capability should produce machine-addressable, evidence-backed knowledge-object candidates, not
just prose for a human to reread. Summaries may be downstream projections of those objects, but they
are not the primary result.

## Scope

In scope for the logical Episode Intelligence Pipeline:

- admission of a resolved `Episode` plus its permitted evidence;
- context assembly before semantic extraction;
- Episode-type classification with explicit uncertainty;
- selection of a versioned domain profile;
- selection and invocation of a compatible extractor implementation;
- production and validation of typed knowledge-object candidates;
- object-level provenance and calibrated confidence;
- routing through a publication profile to declared downstream consumers;
- replay through newer extractors or ontology versions without erasing prior lineage.

Out of scope:

- general capture, sensors, recording, raw-media retention, ASR, or Heimdal's overall responsibility;
- multi-stream Episode segmentation, canonical Episode identity, `episode_ref` assignment, closure,
  or re-cutting, all owned by ERE;
- direct creation of canonical human knowledge without governance;
- replacing the Mimer entity register, context contracts, metadata bundle, or authority-transition
  path;
- implementing plugins, schemas, runtime services, CKM changes, or publication consumers;
- creating issues or selecting a delivery sequence.

## Capability Boundaries

### Constituent and authority boundary

| Stage | Owner | Output | Explicit non-responsibility |
| --- | --- | --- | --- |
| Capture, transcription, attribution, observation publication | Heimdal | Published observation events, evidence references, confidence, provenance, optional single-stream boundary hints | Does not decide Episode meaning or create knowledge |
| Multi-stream segmentation and Episode identity | Mimer ERE | First-class `Episode`, bindings, closure state | Does not perform domain extraction |
| Context assembly | Mimer context/retrieval capabilities | Admissible, provenance-bearing context packet | Does not decide what knowledge is true |
| Episode Knowledge Extraction | Proposed Mimer capability | Typed, noncanonical knowledge-object candidates | Does not mutate durable knowledge |
| Knowledge Object Publication Pipeline | Mimer governance/execution composition | Routed candidates, proposals, receipts, or governed effects according to object class | Does not reinterpret the Episode |

The core new capability is **Episode Knowledge Extraction**, with authority class **proposal**. It
accepts an Episode, an admissible context packet, and a domain profile; it returns typed candidates.
The publication pipeline is composed after it because publication may cross authority and side-effect
classes that an extraction capability must not own.

### Why this is not one Heimdal capability

ADR-0049 fixes the seam: Heimdal owns watch/fetch/transcribe/attribute and Mimer owns extract
meaning/integrate/promote. ADR-0054 further fixes multi-stream Episode construction and
`episode_ref` assignment in Mimer. Moving ontology selection, semantic extraction, or knowledge
object creation into Heimdal would make the sensor decide meaning and duplicate ERE's Episode
ownership.

The proposal therefore preserves the requested end-to-end behavior while rejecting its original
single-owner boundary. This is a decomposition correction, not a reduction of capability.

### Why this is not one capability per Episode type

`Standup Extraction`, `Workshop Extraction`, and `Architecture Review Extraction` should not become
separate top-level capabilities merely because their ontologies differ. They share the same human
move and authority posture: derive structured, evidence-backed knowledge candidates from a resolved
Episode. Their differences belong in versioned domain profiles and extractor plugins.

A type becomes a separate capability only if it develops a different purpose, authority class,
side-effect contract, or independent caller-facing input/output contract—not merely a specialized
ontology.

## Design Principles

### Capability-first

The stable unit is the surface-independent cognitive function: extract domain-appropriate knowledge
from an Episode. Callers bind to its typed contract, not to a meeting bot, model prompt, UI, or plugin.

### Plugin-second

Plugins are replaceable implementations selected behind the capability contract. A plugin packages
support for one or more domain profiles, extractor versions, validation rules, and publication
defaults. Installing or replacing a plugin must not change the capability's identity.

`plugin != capability`, and `episode type != plugin`. One plugin may support several compatible
types; one type may have several competing extractors.

### Context-first

Context is assembled and admitted before the transcript or other episode evidence is semantically
interpreted. Calendar entries, participants, prior Episodes, GitHub Issues, documents, projects, and
knowledge-graph neighborhoods are not after-the-fact enrichment. They constrain classification,
entity resolution, reference disambiguation, ontology choice, and extraction.

Context-first does not mean ambient access. Every context item remains scope- and policy-admitted,
provenance-bearing, and visible as an input to the extraction result.

### Episodes as first-class objects

The pipeline consumes the Mimer `Episode` defined by ADR-0051, not a transcript file, recording, or
Heimdal capture-session identifier pretending to be an Episode. The Episode provides stable identity,
time bounds, participants/protagonists, goals, causal context, scope, and evidence bindings.

Heimdal's historical payload field `episode_id` is a single-capture grouping hint. It is not the
canonical Mimer Episode and must not be used to bypass ERE.

### Common pipeline

Every supported Episode type passes through the same stage lifecycle, observability contract,
failure vocabulary, replay discipline, and authority boundary.

**A common pipeline does not imply a common information model.** The common part is control flow and
the candidate envelope; the domain payload remains ontology-specific.

### Domain-specific ontologies

Each domain profile names the concepts and relations it can produce. The ontology may reuse Mimer's
canonical primitives (`Artifact`, `Claim`, `Concept`, `Relation`, `Episode`, `Proposal`) while adding
a typed domain payload such as blocker, hypothesis, experiment, decision, or trade-off candidate.
Those proposed types are not current ontology claims until separately accepted.

### Domain-specific extractors

Extraction logic is specialized for the ontology and evidence pattern. A generic meeting extractor
may provide a safe fallback, but it cannot be treated as semantically equivalent to a workshop or
architecture-review extractor.

### Provenance

Every knowledge-object candidate must resolve to the Episode, the evidence fragments used, the
context items used, the domain-profile version, the extractor version, and any model/provider
invocation. A candidate without resolvable evidence is invalid, not merely low confidence.

### Confidence

Confidence is attached to the claims it qualifies and keeps distinct axes where failure modes differ:
Episode-type classification, entity/reference resolution, extraction fidelity, and domain
interpretation. A single scalar may be a presentation projection, never the stored semantic model.

### Publication Pipeline

Extraction produces candidates. Publication validates, deduplicates, routes, and—only where the
target contract permits—submits a governed proposal or effect. Publication never launders an
extracted candidate into canonical knowledge merely by storing or delivering it.

## Architecture Overview

The logical flow is:

```text
Heimdal observations + other registered streams
    -> Mimer Episode Resolution Engine
    -> first-class Episode + evidence bindings
    -> context assembly and admission
    -> Episode type classification
    -> domain-profile resolution
    -> ontology-compatible extractor selection
    -> structured knowledge-object candidates
    -> provenance/confidence validation
    -> Publication Pipeline
    -> declared downstream consumers / governed promotion paths
```

Three separations are load-bearing:

1. **observation is not Episode** — ERE performs the situation-level resolution;
2. **Episode is not knowledge** — extraction derives proposals from evidence;
3. **publication is not promotion** — delivery to a consumer does not confer authority.

## Capability Decomposition

### Existing components reused

- Heimdal observation publication, attribution, provenance, and single-stream boundary hints;
- ERE Episode construction, binding, closure, and human re-cut posture;
- context/retrieval contracts for admissible context assembly;
- Mimer functional ontology and metadata bundle for common identity/authority/provenance fields;
- governance and governed-write contracts for effects that cross into durable knowledge;
- CKM as a Builder System projection of capability existence and maturity, once it can represent
  this design losslessly.

### Proposed logical components

1. **Episode Type Classifier** — returns a ranked classification with evidence, confidence, and an
   explicit `unknown`/`generic` posture.
2. **Domain Profile Resolver** — maps the classification and context to a versioned domain profile.
3. **Extractor Selector** — selects a compatible extractor by ontology version, modality/evidence
   requirements, egress posture, quality profile, and availability.
4. **Domain Extractor** — produces typed candidates and evidence anchors; has no publication authority.
5. **Candidate Validator** — checks ontology conformance, provenance completeness, scope, confidence,
   and idempotency identity.
6. **Publication Router** — applies the domain profile's publication model and routes each candidate
   to declared consumers or governance surfaces.

These are stages/components of the logical pipeline. CKM promotion should not automatically register
each as a top-level capability; that decision depends on whether a stage exposes an independently
reusable contract.

## Episode Model

The pipeline's minimum Episode input is a stable reference plus a resolvable view containing:

- canonical `episode_id` and `episode_ref` bindings;
- time bounds and closure/re-cut state;
- scope binding and sensitivity;
- participants/protagonists and entity references where available;
- goal, place, and causal dimensions where available;
- bound observations, transcripts, documents, or other evidence;
- provenance and confidence inherited from each source;
- supersession/correction lineage;
- context-admission policy and temporal validity.

The Episode remains the context anchor for every derived candidate. A candidate may outlive the
Episode's immediate relevance, but it never loses the `derived_from Episode -> evidence fragments`
lineage.

## Domain Extraction Model

### Domain profile

A domain profile is a versioned declaration, not executable capability identity. It contains at
least:

| Field | Meaning |
| --- | --- |
| `profile_id` / `version` | Stable identity and compatibility version |
| `episode_types` | Classifications for which the profile is eligible |
| `ontology_ref` / `ontology_version` | Types, relations, and validation rules the extractor may emit |
| `extractor_contract` | Required inputs and typed candidate outputs |
| `eligible_extractors` | Implementations compatible with this profile |
| `context_requirements` | Required/optional context kinds and admission rules |
| `confidence_policy` | Axes, calibration expectations, and fail/degrade thresholds |
| `publication_profile` | Candidate-type-to-consumer routing and authority posture |
| `fallback_profile` | Explicit safe degradation when classification or extractor selection fails |

### Candidate envelope and domain payload

The common candidate envelope carries identity, Episode lineage, evidence, scope, authority posture,
and confidence. Its `domain_payload` is ontology-specific. This is the central answer to the apparent
tension between reuse and specialization:

- the envelope and pipeline are common;
- the payload types and relations are not;
- common metadata makes heterogeneous objects governable and traceable without flattening them.

### Extraction failure posture

- Unknown Episode type -> use an explicitly generic profile or return `classification_unresolved`;
  never guess a specialized ontology.
- Missing required context -> return `context_incomplete` or run a profile-declared degraded mode.
- No compatible extractor -> fail legibly; do not substitute an unrelated extractor.
- Invalid candidate -> quarantine the candidate with diagnostics; do not publish it as knowledge.
- Low confidence -> retain the candidate as uncertain or route it to review according to policy;
  never silently raise confidence.

## Common Metadata

Every candidate should carry a common metadata envelope compatible in intent with Mimer's existing
metadata/provenance contracts:

- candidate identity and idempotency key;
- `episode_ref` and source Episode version/cut;
- evidence fragment references, offsets/timestamps, and content identities;
- context-item references and admission basis;
- domain-profile and ontology identity/version;
- extractor identity/version and model/provider/egress posture where applicable;
- candidate type and typed subject/object/entity references;
- scope binding, sensitivity, source role, evidence role, and noncanonical authority state;
- confidence axes with method and calibration;
- creation/assertion time and temporal-validity bounds;
- correction, supersession, and replay lineage;
- publication-profile version, target consumer, delivery state, and any resulting receipt reference.

This metadata is shared. The semantic fields inside a decision, hypothesis, blocker, commitment, or
observation candidate are not forced into one universal payload.

## Publication Pipeline

Publication is a typed pipeline after extraction:

1. **Validate** candidate shape, evidence, ontology version, confidence, and scope.
2. **Deduplicate/fold** by stable candidate identity while preserving revisions and corrections.
3. **Classify authority**: analytical output, read-only projection, proposal, or governed effect.
4. **Route** by candidate type and publication profile to a declared consumer.
5. **Apply governance** before any durable or external effect.
6. **Emit delivery evidence**: result, error class, trace, and receipt where required.

Different domains may publish differently. An architecture decision candidate may enter a decision
review surface; a blocker may feed commitment or project views; a hypothesis may feed an experiment
backlog; a field observation may remain a cited evidence object. Reusing one pipeline does not require
one target store, one consumer, or one authority class.

## Scenarios

### Scenario 1 — meeting types require different ontologies

All three inputs are meetings, but the domain meaning differs:

| Episode type | Primary knowledge-object candidates | Why a generic extractor is insufficient |
| --- | --- | --- |
| Standup | status, blocker, commitment | Must bind owner, state, dependency, and time; idea/decision language is usually incidental |
| Workshop | idea, hypothesis, assumption, experiment | Must preserve exploration and falsifiability rather than mislabeling tentative material as commitments |
| Architecture Review | decision, alternative, trade-off, quality attribute, rationale, risk | Must relate decisions to alternatives and constraints and preserve why one choice dominates another |

The same sentence can mean different things by Episode type. "We will try the event log" in a
workshop may be an experiment; in an architecture review it may be a decision; in a standup it may be
a commitment. Context and ontology determine the object type. A single extractor trained to emit one
meeting schema either drops distinctions or produces misleading certainty.

### Scenario 2 — the same pipeline across unrelated Episodes

| Episode | Same pipeline | Domain-specific variation |
| --- | --- | --- |
| Voice Memo | context -> classify -> profile -> extract -> validate -> publish | intent/claim/commitment ontology; private publication profile |
| Podcast | same | argument/source/claim ontology; citation-oriented publication |
| Lecture | same | concept/definition/example/prerequisite ontology; learning-oriented publication |
| Code Review | same | defect/risk/suggestion/decision ontology; repository/PR publication |
| Customer Interview | same | need/pain point/workaround/quote/hypothesis ontology; research publication |
| Field Observation | same | observation/condition/anomaly/measurement ontology; evidence-first publication |

The reusable asset is the pipeline contract. The ontology, extractor, validation rules, and
publication model vary by domain. No modality is privileged: speech, text, screen-derived activity,
and mixed-evidence Episodes can use the same capability if they satisfy a domain profile's input
contract.

### Scenario 3 — context before transcript analysis

An architecture meeting Episode is resolved by ERE. Before semantic extraction, the context builder
assembles and admits:

- the calendar event and meeting title;
- participants and their project roles;
- prior Episodes in the same architecture thread;
- linked GitHub Issues and their current scope;
- relevant architecture docs and ADRs;
- active project/scope bindings;
- the knowledge-graph neighborhood for the named components.

Only then does the classifier and architecture-review extractor analyze the transcript.

This improves extraction because "Context Engine" resolves to the correct component, "move" can be
distinguished from a temporary experiment, the named issue constrains the decision scope, prior ADRs
show whether the statement reverses or extends an earlier decision, and participant/project context
helps distinguish an owner decision from a suggestion. The result still cites exactly which context
items affected it; hidden ambient context is not allowed.

### Scenario 4 — transcription is evidence; knowledge is structured

Transcript evidence:

> "We should move the Context Engine to Heimdal."

Illustrative candidate result:

```yaml
type: architecture_decision_candidate
subject: Context Engine
action: relocate
target: Heimdal
rationale: reduced coupling
confidence:
  classification: 0.94
  entity_resolution: 0.91
  domain_interpretation: 0.87
evidence:
  episode_ref: ep-architecture-review-2026-07-20
  transcript_timestamp: "00:18:42"
authority_state: proposed
```

The example is deliberately a **candidate**, not an accepted decision. The transcript remains the
evidence; the object makes subject, action, target, rationale, confidence, and evidence addressable.
A prose summary can later render this object, but the summary is a projection and cannot replace it.

### Scenario 5 — specialization without capability churn

An initial release may support only `Generic Meeting`, with a conservative ontology and publication
profile. Later profiles can add:

- Workshop;
- Architecture Review;
- Design Review;
- Customer Interview;
- Incident Review.

The capability contract stays stable. New specialization arrives through versioned domain profiles,
ontologies, extractor plugins, validation corpora, and publication profiles. Callers continue to invoke
Episode Knowledge Extraction. The capability itself changes only if its purpose, authority class, or
typed outer contract changes—not whenever a new Episode type is learned.

## Relation to Heimdal

Heimdal is an upstream evidence producer. This proposal reuses, rather than duplicates, Heimdal's:

- published observation events;
- transcription and attribution results;
- provenance and confidence;
- correction/revision lineage;
- single-stream Episode boundary hints.

Heimdal does not select Mimer domain ontologies, run semantic knowledge extractors, create canonical
Episodes, or publish knowledge objects. Keeping that boundary lets Heimdal remain reusable for all
consumers of observed events, including consumers that do not need knowledge extraction.

## Relation to Munin

There is no active Munin constituent to integrate with. ADR-0044 superseded the earlier
Munin/Hugin split: **Mimer** is the undivided knowledge-and-cognition constituent, while Munin and
Hugin are reserved/inactive names. Historical Heimdal documents that say "Munin" must be read through
that amendment.

The design responsibility the prompt associates with Munin therefore belongs to Mimer today. A
future Munin activation would require a constituent-independence decision and a new ADR; this proposal
must not pre-allocate the capability to that hypothetical constituent.

## Relation to CKM

CKM (Kvasir) is a Builder System projection of which platform capabilities exist, the evidence for
them, and their maturity. It is not the runtime ontology, plugin registry, extractor router, or
publication engine. CKM may eventually describe this capability, but it will never execute it or make
its outputs authoritative.

The proposal remains outside the confirmed CKM seed until promotion criteria are met. Registering a
single flattened node now would incorrectly suggest that ownership, composition, ontology variation,
and publication semantics had been resolved.

## CKM Limitations

### What CKM can represent today

The current `CkmCapability` / `ckm_capability` model can represent:

- stable public/internal identity, name, and short definition;
- one optional parent capability;
- lifecycle (`candidate`, `confirmed`, `deprecated`);
- existence provenance;
- one optional `boundary_ref`;
- evidence artifacts and typed evidence edges;
- cited maturity assessments across seven dimensions;
- gaps and missing-evidence findings.

That is sufficient to say "a capability candidate exists, has this parent/boundary, and has this
evidence/maturity." It is not sufficient to preserve this proposal.

### What CKM cannot represent without information loss

Today's CKM has no first-class representation for:

- a logical composition spanning existing and proposed capabilities;
- multiple constituent/control-boundary allocations by pipeline stage;
- the distinction between capability, plugin implementation, domain profile, ontology, extractor,
  and publication profile;
- typed capability inputs, outputs, authority class, or side-effect class from the Capability
  Contract Model;
- a stage graph or ordering/dependency constraints;
- Episode-type-to-domain-profile eligibility;
- ontology-specific output variants under one common candidate envelope;
- extractor compatibility, fallback, egress posture, or version constraints;
- candidate-type-to-consumer publication routing;
- object-level provenance and multidimensional confidence requirements;
- profile-level maturity (for example, Generic Meeting active while Architecture Review remains
  experimental);
- compatibility and migration relations across ontology/extractor/profile versions.

Encoding those facts in `definition`, overloading `parent_id`, or choosing one `boundary_ref` would be
lossy. Evidence edges cannot substitute for architecture edges: `evidence_kind` intentionally describes
builder-plane evidence and must not be repurposed into runtime composition or semantic relations.

## Required CKM Evolution

CKM must remain projection-only, but it needs an additive representation capable of describing:

1. **Capability contracts** — typed inputs/outputs, authority class, side effects, provenance,
   fallback, maturity, and replacement strategy.
2. **Composition edges** — `composes`, `depends_on`, `precedes`, and `publishes_to`, distinct from
   evidence edges.
3. **Multiple allocations** — stage/component allocation to constituent and control boundary, without
   pretending the composite has one owner.
4. **Implementation edges** — `implemented_by` plugin/extractor relations that preserve
   capability-first/plugin-second identity.
5. **Domain profiles** — Episode-type eligibility, ontology ref/version, context requirements,
   confidence policy, publication profile, and fallback profile.
6. **Typed output variants** — a common envelope plus ontology-specific knowledge-object candidate
   families.
7. **Profile-level lifecycle and maturity** — so capability maturity is not falsely inferred from one
   mature or immature domain profile.
8. **Version and compatibility relations** — successor, compatible-with, migration-required, and
   replay posture for profiles, ontologies, and extractors.

This is a representational requirement, not a proposed CKM schema migration. The CKM owner must decide
the minimal model and keep architecture/composition relations orthogonal to evidence edges and runtime
semantic dimensions.

## Open Questions

- Should the promoted unit be one `Episode Knowledge Extraction` capability plus a separate shared
  publication capability, or should an existing governed-effect spine own publication entirely?
- Which existing context-building contract becomes the normative pre-extraction input?
- What is the minimum generic candidate envelope that remains compatible with the Mimer metadata
  bundle without pretending every domain payload is a canonical Mimer object?
- Who governs domain ontology versions and compatibility decisions?
- Is Episode classification a reusable capability in its own right, or an internal stage until a
  second caller appears?
- How are ambiguous multi-type Episodes handled: one dominant profile, several profile passes, or a
  composite profile?
- Which confidence axes require calibration data before publication, and which may remain explicitly
  heuristic?
- How are human corrections represented so replay can improve objects without erasing prior lineage?
- Which publication consumers accept proposals, which accept read-only analytical objects, and which
  require governed effects?
- How are domain plugins trusted, sandboxed, and prevented from bypassing context admission or
  publication governance?
- What is the retention/suppression behavior when Episode evidence is revoked or corrected?

## Future Workstreams

These are architectural workstreams, not backlog items created by this proposal:

1. **Boundary decision** — ratify or refine the recommended decomposition against ADR-0049/0054.
2. **CKM representation design** — add lossless composition/profile/implementation semantics while
   preserving CKM's projection-only authority boundary.
3. **Capability contract** — answer all twelve fields in the Capability Contract Model for Episode
   Knowledge Extraction and for the selected publication capability.
4. **Domain-profile contract** — define versioning, compatibility, fallback, and ontology governance.
5. **Publication contract** — define candidate routing, deduplication, correction, receipt, and
   authority semantics.
6. **Evaluation design** — build an evidence corpus spanning at least Generic Meeting, Workshop, and
   Architecture Review, including ambiguous and context-missing cases.
7. **Security and policy review** — prove context admission, observed-content quarantine, egress
   declarations, and scope preservation across plugins.
8. **Pilot specialization** — validate that a generic profile and one specialized profile can share
   the pipeline without semantic flattening or caller changes.

## Promotion Criteria

The proposal may be promoted into the official CKM capability model only when all of the following
are true:

- CKM can represent the capability, composition, allocations, profiles, implementations, typed
  outputs, and publication relations without encoding them in free-text fields;
- the Heimdal/Mimer/ERE boundary is explicitly preserved or changed through the appropriate ADR;
- the promoted atomic capability has all twelve Capability Contract Model fields resolved;
- extraction remains proposal-class and any publication effect has an explicit governance owner;
- the canonical Mimer Episode is the input anchor; no Heimdal capture-session id substitutes for it;
- a common candidate envelope and at least two materially different domain ontologies prove that
  common pipeline does not mean common information model;
- plugin replacement leaves the capability identity and caller contract unchanged;
- provenance resolves from every candidate through Episode and evidence fragments to source;
- confidence axes and calibration posture are explicit and cannot be silently collapsed or upgraded;
- context admission occurs before semantic extraction and every used context item is visible in
  provenance;
- publication models name consumers, authority class, deduplication/correction behavior, and receipts;
- generic fallback, unknown classification, missing context, incompatible extractor, and invalid
  candidate all have fail-legible behavior;
- profile/ontology/extractor versioning and replay compatibility are specified;
- evaluation evidence demonstrates Standup/Workshop/Architecture Review separation and at least one
  non-meeting Episode family;
- current-state docs continue to distinguish proposed, experimental, and shipped support.

Until then, this document is the future architecture reference. CKM may cite it as evidence of an
unpromoted proposal, but must not flatten it into a confirmed capability.

## References

- `docs/HEIMDAL/README.md`, `docs/HEIMDAL/CAPABILITY_CHARTER.md`,
  `docs/HEIMDAL/FABLE_COMPANION.md`
- `docs/adr/ADR-0044-research08-d1-conforms-to-acknowledged-sos.md`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/adr/ADR-0051-episode-as-ontological-primitive.md`
- `docs/adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md`
- `docs/EPISODE_RESOLUTION_ENGINE/README.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/architecture/functional-ontology.md`, `docs/architecture/metadata-bundle.md`,
  `docs/architecture/semantic-dimensions.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`,
  `docs/CAPABILITY_KNOWLEDGE_MODEL/CKM_STORE_AND_OBJECT_MODEL.md`
