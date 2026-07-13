State: Advisory research synthesis for issue #3196; docs-only and non-normative.
Doc role: Research
Authority: Recommends a provider-neutral conceptual model for later bounded design work; owns no runtime schema, API, database, event, migration, ontology reshape, or product behavior.
Owner: AI Conversation Intelligence research roadmap (#3194)
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-13
Last verified against: docs/CONCEPTS/COGNITIVE_ONTOLOGY.md, docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md, docs/architecture/metadata-bundle.md, docs/research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md, docs/boundaries/SIP.md, docs/boundaries/HKA.md, docs/contracts/MEMORY_RECORD.md

# AI Conversation Intelligence — conceptual conversation data model

Parent: [#3194](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3194) ·
Slice: [#3196](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3196) ·
Input-source research: [#3195](AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md)

## Scope and research posture

This memo asks what concepts are needed to reason safely about imported AI conversations before an
adapter, storage model, extraction pipeline, or product surface is designed. It is a conceptual
model, not a serialized shape. Names below are working research names and do not extend the
canonical ontology.

The model deliberately starts from three repository constraints:

1. a conversation supplied by a provider is retained material that may play a source role; its
   imported or normalized representations are projections, not durable knowledge by default;
2. provenance, scope, authority, and evidence are orthogonal and must survive every derivation; and
3. machine memory and extracted candidates remain advisory until a governed transition promotes
   something into HKA.

The source-options memo recommends human-selected material and official exports for discovery, with
caller-side API or machine-readable CLI capture as the future-facing path. The conceptual model
therefore cannot assume one provider's notion of a thread, message, branch, tool call, or stable ID.

## Conceptual entity model

### Model at a glance

| Concept | Meaning in this research model | Identity posture | Nearest existing concept or boundary |
| --- | --- | --- | --- |
| `SourceBinding` | Provider, product, account/workspace scope, acquisition mode, and any source-scoped identifiers needed to interpret a capture. | Local identity; provider identifiers are unique only within the declared binding. | SIP source role and attribution; metadata-bundle provenance. |
| `Acquisition` | One bounded act of selecting, exporting, receiving, or capturing source material. | New identity for each act, including repeat captures of the same conversation. | Provenance activity/receipt; not an Episode. |
| `ConversationRecord` | The source-observed conversation container as acquired, including title and provider/thread metadata when present. | Source-scoped identity plus acquisition lineage; no cross-provider equality is inferred. | Retained artifact in a source role; imported form may be a projection. |
| `InteractionItem` | One ordered source-observed item: human/assistant/system message, tool request/result, attachment reference, edit marker, branch marker, or unknown item. | Source-scoped item identity where supplied; otherwise acquisition-local position plus hash is only a locator, not semantic identity. | Observation or source material; never automatically a Claim or MemoryRecord. |
| `ContentPart` | A typed part of an item, such as text, image reference, file, citation, reasoning summary, or provider-unknown payload. | Bound to the item and acquisition; external resources retain their own source references. | Partial projection of retained material. |
| `ParticipantAssertion` | What the source says about the item's role or actor: human, assistant, system, tool, application, unknown, or named identity hint. | An assertion within a source binding, not a globally resolved Actor identity. | Actor attribution under SIP; global entity resolution is deferred. |
| `ConversationRelation` | Source-observed ordering, reply, branch, continuation, edit/revision, tool pairing, attachment, or cross-conversation link. | Relation identity is acquisition-local unless the source supplies a stable identifier. | Typed relation/provenance view under SIP. |
| `NormalizedProjection` | A provider-neutral view that preserves source meaning while exposing common concepts. | Rebuildable and versioned; always points back to source material and transformation. | Projection, never the underlying artifact or evidence by itself. |
| `DerivationActivity` | A bounded transformation such as parsing, normalization, chunking, summarization, classification, or candidate extraction. | Distinct activity with method/version/agent/time and input/output links. | SIP provenance activity; aligns with W3C PROV's activity pattern. |
| `KnowledgeCandidate` | A reviewable proposition, decision, commitment, question, insight, or other candidate extracted from one or more source spans. | New candidate identity; may have multiple supporting and contradicting spans. | Proposal/Claim candidate; taxonomy is the subject of #3197. |
| `MemoryCandidate` | A candidate observation intended for the MEM lifecycle rather than durable human knowledge. | New candidate identity, explicit review/confidence/staleness/correction posture. | `MemoryRecord` input; advisory unless governed promotion occurs. |
| `AcceptedArtifactRef` | A link to an existing or newly governed HKA artifact after a human/governance transition. | Uses the HKA artifact identity and authority receipt; never minted by extraction alone. | HKA durable human knowledge. |

### Containment and lineage

The minimum useful structure is not just `conversation -> messages`. It has two overlapping graphs:

```text
SourceBinding
  └─ Acquisition
       └─ ConversationRecord
            ├─ InteractionItem (ordered and/or related)
            │    ├─ ContentPart
            │    └─ ParticipantAssertion
            └─ ConversationRelation

source spans ──used by──> DerivationActivity
DerivationActivity ──generates──> NormalizedProjection / KnowledgeCandidate / MemoryCandidate
reviewed candidate ──governed transition──> AcceptedArtifactRef
```

Containment answers where material was observed. Lineage answers how a later representation or
candidate came to exist. They must not be collapsed: an item can belong to one acquired
conversation while a candidate is derived from spans across several conversations.

### Conversation is not Episode

A provider conversation is a source/container boundary. An Episode is the durable, observer-relative
record of the smallest coherent lived situation that can close independently. The two can relate,
but neither determines the other:

- one conversation may span several Episodes;
- one Episode may include several conversations and non-conversation observations;
- an import may have no credible Episode binding and must remain `unbound` rather than invent one;
- a later proposed Episode binding is contextual metadata and never raises evidence or authority.

### Ordering, branching, and revision

Source order should be represented as an observed relation, not treated as a universal total order.
Some providers expose branches, revisions, tool sub-events, or timestamps with different precision;
exports may flatten or omit them. The conceptual model therefore distinguishes:

- source-declared sequence or parent/reply relations;
- acquisition order, which is only the order in the acquired representation;
- observed timestamps with their stated precision and timezone posture;
- later inferred relations, which must identify the inference activity and uncertainty.

An edited message is not silently overwritten in the research model. If the source exposes versions,
they are related as revisions. If it exposes only the latest state, the acquisition records that
limitation; the model does not fabricate prior versions.

### Identity boundaries

Provider IDs are source-scoped locators, not universal semantic identity. A usable identity key is
conceptually the tuple `(source binding, provider object kind, provider identifier)`. When no ID is
available, an acquisition-local locator may support traceability, but matching two captures remains
a hypothesis.

Content hashes help detect byte- or normalized-content equality. They do not establish that two
messages, participants, conversations, claims, or Episodes are the same thing. Cross-export
deduplication and cross-provider conversation linking are explicit future decisions with reversible
match evidence.

## Authority and derivation boundaries

### Five distinct layers

| Layer | What may be asserted | What must not be inferred |
| --- | --- | --- |
| 1. Acquired source material | “This payload was obtained through this acquisition from this source binding.” | Completeness, truth, authorship beyond source assertion, or canonical standing. |
| 2. Source-faithful projection | “This common-field view corresponds to these source fields under this transform.” | That normalization preserved facts the source did not expose. |
| 3. Derived candidate | “This method proposed this candidate from these spans, with this uncertainty.” | Human acceptance, evidentiary sufficiency, durable knowledge, or instruction authority. |
| 4. Reviewed disposition | “A human or governed process accepted, rejected, corrected, deferred, or linked this candidate.” | That accepting one candidate validates the whole conversation or all sibling candidates. |
| 5. Durable artifact or memory record | “This governed artifact or explicit MEM record now has the standing recorded by its owning boundary.” | That the source record itself changed authority or that a memory became HKA without GOV. |

This layering preserves the repository's separation of source role, evidence role, and authority
state. Human-authored text inside a chat is still not automatically canonical. Assistant text,
tool output, citations, and model-generated summaries are not evidence merely because a provider
exported them. A cited external artifact can play a source role only when it is independently
resolved and its provenance is retained.

### Epistemic status of values

Every consequential value in a projection or candidate should be distinguishable as one of:

- `source_observed`: present in the acquired material;
- `source_asserted`: stated by the source about actor, role, time, or relation;
- `copied`: transferred without semantic transformation;
- `normalized`: mechanically transformed under a named rule;
- `derived`: inferred or synthesized by a named activity;
- `human_asserted`: supplied or corrected by a human during review;
- `unknown`: unavailable or not safely inferable.

These are conceptual statuses, not a proposed enum. Their purpose is to prevent derived labels,
resolved identities, generated timestamps, and summaries from masquerading as source facts.

### Candidate boundaries

A candidate is a new object with lineage, not an annotation that rewrites its source. It may cite
precise source spans, including non-contiguous or cross-conversation spans. It also needs explicit
support, contradiction, correction, supersession, and rejection relations so later review is
auditable.

`KnowledgeCandidate` and `MemoryCandidate` are deliberately separate routing intentions. A useful
personal preference might enter the MEM review lifecycle; a durable accepted decision may target
HKA. Extraction confidence alone never chooses the final owner or performs promotion.

### External standards alignment, not adoption

[W3C PROV-O](https://www.w3.org/TR/prov-o/) supplies a useful minimal vocabulary: entities,
activities, and responsible agents connected by use, generation, derivation, attribution, and
association. [PROV-DM](https://www.w3.org/TR/prov-dm/) further distinguishes specialization and
alternate entities. This memo uses those distinctions as research grounding for explicit lineage
and version posture; it does not propose adopting RDF, PROV serialization, or global IRIs.

[Activity Streams 2.0](https://www.w3.org/TR/activitystreams-core/) demonstrates a generalized
separation among objects, actors, activities, attachments, attribution, context, and reply
relations. It supports treating provider-specific interaction items as extensible source objects,
but it is a social-activity interchange model, not an AI-conversation schema. This memo therefore
borrows no normative types from it.

## Minimum provenance envelope

This is the minimum information a future representation would need to answer “where did this come
from, what happened to it, and what standing does it have?” It is a conceptual checklist, not a
field or JSON contract.

| Family | Minimum questions to answer | Notes |
| --- | --- | --- |
| Source binding | Which provider/product and account/workspace scope? Which acquisition mode and source role? | Avoid recording unnecessary account secrets or personal identifiers. |
| Acquisition | When and by whom/what was it acquired? Was it selected, exported, API-captured, or CLI-captured? What receipt or consent applies? | Repeat acquisitions remain distinct. |
| Source identity | What source-scoped object kind and identifier were supplied? What acquisition-local locator exists if none was supplied? | Never promote provider IDs to global identity without evidence. |
| Content integrity | What original payload or retained artifact is referenced? What hash, media type, encoding, and preservation posture apply? | A hash proves content equality under its algorithm, not truth or semantic identity. |
| Observed context | What timestamps and precision, participant assertions, ordering/branch relations, scope binding, sensitivity, and Episode posture were observed? | Missing remains unknown; Episode may be `unbound` or `pending`. |
| Transformation | Which activity, method/version, agent, and time created this representation? Which exact inputs or spans were used? | Required for parsing, normalization, chunking, classification, and synthesis. |
| Standing | What are the independent source-role, authority-state, and evidence-role postures? Is there an authority receipt? | A projection or candidate has no promotion receipt by default. |
| Review and correction | Who reviewed it, with what disposition and rationale? What was corrected, rejected, superseded, or left open? | Retain history; do not rewrite the source to match the correction. |

The repository metadata bundle already provides the target vocabulary for many of these questions:
identity, scope/context, orthogonal semantic dimensions, provenance, lifecycle, `derived_from`,
`created_by`, `created_at`, content hash, provenance events, and authority receipt. Future design
should extend or project that contract only through its owning governance path; this research memo
does not change it.

### Provenance invariants for later design

1. Every normalized or derived object points to the source material and the activity that produced
   it.
2. Every candidate can resolve to exact source spans or explicitly state why span precision is
   unavailable.
3. Source-scoped identifiers always travel with their source binding.
4. Missing information remains unknown; inference is recorded as derivation.
5. Scope, sensitivity, provenance, and Episode posture survive derivation.
6. Review changes candidate disposition, not the acquired source record.
7. A durable-knowledge reference requires a GOV authority receipt; a memory record remains advisory
   unless separately promoted.

## Recommendation, open questions, and next bounded issues

### Recommendation

Use the layered model above as a vocabulary for the next design slices: immutable acquired material,
rebuildable provider-neutral projections, explicitly attributed derivation activities, reviewable
candidates, and separately governed HKA/MEM outcomes. Keep conversation, Episode, knowledge
artifact, and memory identities distinct. Treat source-scoped identifiers and exact span lineage as
the minimum bar for any future extraction experiment.

Do not select a database, event envelope, transport, provider adapter interface, canonical schema,
deduplication algorithm, or product review surface from this memo. Those decisions need bounded
issues after representative source samples and the #3197 taxonomy are available.

### Open questions

- What is the smallest lossless common item model across representative official exports and
  caller-side API/CLI captures, especially for branches, edits, tool calls, citations, and files?
- Which parts of provider payloads may be retained, and for how long, under each scope and
  sensitivity posture?
- What granularity of source spans remains stable across re-export, normalization, and redaction?
- How should two acquisitions propose “same source conversation” without irreversible merging?
- When is participant resolution useful enough to justify privacy and false-match risk?
- How should redaction preserve auditability when the original content cannot remain available?
- Which candidate dispositions and correction relations are necessary for useful human review?
- What evidence is sufficient to propose an Episode binding for retrospective conversations?

### Recommended next bounded issues

1. **Representative-format fixture study:** collect consented, minimized fixtures from the approved
   #3195 acquisition modes; characterize loss, branches, tools, attachments, timestamps, and IDs.
2. **Provider-neutral projection decision:** compare the conceptual entities against those fixtures
   and propose a versioned logical contract, explicitly excluding persistence and transport.
3. **Span-addressing and redaction contract:** decide stable citation locators, integrity checks,
   deletion/redaction behavior, and provenance continuity.
4. **Identity reconciliation experiment:** evaluate reversible matching signals across repeated
   acquisitions without automatic merge or global participant identity.
5. **Candidate review lifecycle contract:** map #3197 taxonomy classes to propose/review/correct/
   reject/supersede outcomes and HKA versus MEM routing.
6. **Privacy and retention threat model:** enumerate sensitive source fields, consent receipts,
   scope crossings, model-processing exposure, deletion obligations, and failure recovery.

Creating or implementing these issues is outside #3196.

## Source register and traceability

| Source | What this memo takes from it | What this memo does not claim |
| --- | --- | --- |
| [Cognitive Ontology](../CONCEPTS/COGNITIVE_ONTOLOGY.md) | Actor/artifact/context/provenance separation; human authority; Episode and artifact distinctions. | No new canonical entity or ontology layer. |
| [Artifact, Projection, and Source Contract](../CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md) | Conversation material can be an artifact in a source role; normalized forms are bounded projections. | A projection is not the underlying artifact or evidence. |
| [Mimer Metadata Bundle](../architecture/metadata-bundle.md) | Identity, scope, semantic, provenance, lifecycle, derivation, Episode, and receipt question families. | No change to its fields, schema, or shipped behavior. |
| [Episode research and enacted decision](EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md) | Episode is a durable lived-situation artifact, distinct from a provider conversation. | No automatic segmentation or retrospective Episode creation. |
| [SIP boundary](../boundaries/SIP.md) | SIP owns semantic identity, typed relations, attribution, lineage, and provenance continuity. | SIP does not decide authority or admissibility. |
| [HKA boundary](../boundaries/HKA.md) | Durable accepted knowledge requires governed transition and origin anchors. | Imported or extracted conversation material is not automatically HKA. |
| [MemoryRecord](../contracts/MEMORY_RECORD.md) | Machine memory requires explicit review, provenance, confidence, staleness, and correction posture. | A candidate is not a memory record or durable knowledge by extraction alone. |
| [Input-source options](AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md) | Acquisition modes, provenance risks, and the recommendation that the model remain provider-neutral. | No adapter or ingestion path is assumed. |
| [W3C PROV-O](https://www.w3.org/TR/prov-o/) and [PROV-DM](https://www.w3.org/TR/prov-dm/) | Entity/activity/agent separation, derivation, attribution, specialization, and alternate-version grounding. | No adoption of RDF, PROV serialization, or its complete ontology. |
| [W3C Activity Streams 2.0](https://www.w3.org/TR/activitystreams-core/) | Comparative grounding for extensible objects, actors, activities, attachments, attribution, context, and replies. | It is not selected as the conversation data model. |

## Explicit non-claims

- This memo does not define runtime behavior, a provider adapter, API, schema, database, event,
  migration, retention policy, or UI.
- Working concept names are not additions to the canonical Yggdrasil ontology.
- No provider export is assumed complete, truthful, stable, or available.
- No conversation, message, participant, Episode, claim, or artifact identity is resolved globally.
- No source content, agent output, memory, or extraction is promoted to canonical knowledge here.
- No recommended follow-up issue is created or implemented by this slice.
