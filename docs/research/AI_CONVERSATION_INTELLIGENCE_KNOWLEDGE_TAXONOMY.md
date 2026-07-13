State: Advisory research synthesis for issue #3197; docs-only and non-normative.
Doc role: Research
Authority: Proposes a multi-axial vocabulary for later bounded design work; owns no ontology term, runtime enum, classifier, prompt, schema, storage model, promotion policy, or product behavior.
Owner: AI Conversation Intelligence research roadmap (#3194)
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-13
Last verified against: docs/CONCEPTS/COGNITIVE_ONTOLOGY.md, docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md, docs/CONCEPTS/ONTOLOGY_VOCABULARY.md, docs/boundaries/HKA.md, docs/boundaries/SIP.md, docs/contracts/MEMORY_RECORD.md

# AI Conversation Intelligence — proposed knowledge taxonomy

Parent: [#3194](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3194) ·
Slice: [#3197](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3197) ·
Input sources: [#3195](AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md) ·
Conceptual data model: [#3196](AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md)

## Scope and research posture

This memo proposes how conversation-derived candidates can be described without pretending that one
classification answers every governance question. It classifies possible *candidate functions* and
then applies independent axes for provenance, authority, temporal standing, confidence, and
lifecycle. It does not classify a raw transcript as knowledge and does not decide that any candidate
should be retained, remembered, or promoted.

The proposal follows the repository's “MECE tree, non-MECE meaning” posture. A compact function list
can be useful for review queues and research comparison, while one fragment may legitimately support
several functions. Storage placement, artifact class, source role, memory class, authority, and
lifecycle remain separate.

## Proposed taxonomy

### A bounded set of candidate functions

These labels answer “what durable cognitive job might this candidate do if reviewed?” They are
multi-valued working labels, not intrinsic types and not claims of truth.

| Candidate function | Bounded meaning | Typical review question | Must not imply |
| --- | --- | --- | --- |
| **Descriptive claim** | A proposition about a state, event, entity, quantity, or relation. | Is the proposition precise, supported, scoped, and still valid? | Fact, evidence, truth, or canonical standing. |
| **Decision** | A selected course, interpretation, or outcome among alternatives. | Who decided, for what scope, when, with what rationale, and is it current? | That an assistant suggestion was adopted. |
| **Commitment** | A promise, obligation, next action, waiting state, or intended follow-up. | Is there an accountable actor, trigger/time, status, and explicit intent? | That future-tense language is a real commitment. |
| **Open question** | An unresolved inquiry, uncertainty, assumption to test, or missing decision. | Is it still open, who owns clarification, and what would resolve it? | That every question deserves durable retention. |
| **Rationale or evidence link** | A reason offered for another candidate, or a pointer to material that may play a source/evidence role. | What claim/decision does it support, and is the cited material independently resolvable and admissible? | That explanation is evidence, or that a citation was verified. |
| **Procedure or method** | A repeatable sequence, heuristic, practice, or operational know-how. | Is it reproducible, safe, versioned, and bounded to a context? | Permission to execute it or a canonical policy. |
| **Preference or constraint** | An expressed preference, boundary, requirement, default, or prohibition. | Was it explicitly declared or inferred, how stable is it, and what scope does it govern? | Global preference, policy authority, or indefinite validity. |
| **Relationship assertion** | A proposed relation among people, organizations, projects, concepts, artifacts, or events. | Are identities resolved, is the relation directional/temporal, and what supports it? | Global entity identity or permanent relationship. |
| **Reflection or learning** | An interpretation of experience, observed pattern, lesson, calibration, or after-action insight. | Is it a human reflection, an agent inference, or a tentative generalization? | Objective truth or cross-context generality. |
| **Creative material** | A fragment, motif, hypothesis, alternative, draft element, or generative possibility. | Is preserving its ambiguity and context more valuable than proposition-style normalization? | Settled knowledge, commitment, or factual claim. |

The set is intentionally small. “Summary,” “topic,” “citation,” “message,” “memory,” “artifact,” and
“receipt” are excluded as primary functions:

- a summary is a derived projection that may contain several candidate functions;
- a topic is subject metadata, not the candidate's cognitive job;
- a citation is a provenance/source relation, while a rationale/evidence-link candidate records why
  that relation may matter;
- a message is a source item in the conceptual data model;
- memory is a MEM lifecycle/ownership route;
- artifact is the broader ontology class; and
- a receipt accounts for a transition or action rather than classifying its semantic content.

### Orthogonal axes

Every candidate needs axes kept separate from candidate function. Values below are research value
families, not proposed enums.

#### 1. Function

Zero, one, or several labels from the bounded set above. Zero is valid when a fragment has no
durable use, is too ambiguous, is purely connective, or should remain only in retained source
material.

#### 2. Authority and review standing

| Posture | Meaning |
| --- | --- |
| source material / noncanonical | The content exists in acquired material; source presence grants no acceptance. |
| derived candidate | A named method proposed an interpretation; review has not accepted it. |
| human-asserted candidate | A human explicitly stated or corrected the candidate, but canonical standing still depends on the relevant owner/governance contract. |
| reviewed for a bounded route | A human or governed process accepted it for a named MEM or HKA route. |
| governed durable standing | HKA carries the accepted artifact plus the GOV authority receipt. |

Provider roles such as `user`, `assistant`, `system`, and `tool` belong to source attribution. A
`user` message is not automatically canonical; an `assistant` message is not automatically false;
neither role determines evidence or authority.

#### 3. Provenance and derivation

Record source binding, acquisition, exact spans, observed participant assertions, and all
transformation/review activities. Distinguish at least:

- source-observed or source-asserted content;
- copied or mechanically normalized content;
- single-source derivation;
- multi-source synthesis;
- human correction/assertion; and
- unknown or unresolved origin.

Provenance is a graph, not a confidence score. A candidate can be high-confidence extraction from a
low-authority source, or low-confidence extraction from a highly authoritative artifact.

#### 4. Temporal standing

| Posture | Question answered |
| --- | --- |
| occurrence-bound / historical | Did it describe a bounded past event or Episode? |
| current-with-validity-window | During what interval is it claimed to hold? |
| prospective | Is it about an intention, commitment, expected event, or condition? |
| recurring / procedural | Does it describe a repeatable practice rather than one occurrence? |
| timeless-claiming | Does it present itself as general, while still requiring scope and review? |
| validity unknown | Is time posture absent or unsafe to infer? |

Staleness, contradiction, and supersession may change how a candidate is used, but they do not erase
its original temporal claim. Episode binding remains a separate context relation.

#### 5. Confidence and uncertainty

Avoid one blended “confidence” number. At minimum, review should be able to distinguish:

- **extraction confidence:** did the transform correctly capture what the source expressed?
- **identity/link confidence:** do proposed participant, entity, citation, or cross-conversation
  links refer to the intended things?
- **support posture:** how direct, independent, and admissible is the cited support?
- **content uncertainty:** how qualified, ambiguous, contested, or incomplete is the proposition?

These measures do not grant authority. Unknown is a legitimate value; disagreement should remain
visible rather than averaged away.

#### 6. Lifecycle and disposition

| Disposition | Meaning and correction rule |
| --- | --- |
| proposed | Candidate created with source spans and derivation receipt. |
| under review | A named reviewer/process is evaluating it; source remains unchanged. |
| deferred | No decision yet; record reason and revisit condition when known. |
| accepted for MEM | Routed into an explicit MemoryRecord lifecycle; still advisory unless later promoted through GOV. |
| accepted for HKA governance | Submitted for governed durable-artifact transition; not canonical until receipt exists. |
| rejected | Not accepted for the proposed use; preserve rationale and lineage. |
| corrected | A new candidate narrows or changes it; retain the relation and original source. |
| contradicted | Incompatible candidates or sources coexist pending resolution; contradiction alone chooses no winner. |
| superseded | A later candidate or accepted artifact replaces its current-use standing without erasing history. |
| archived / forgotten under owner contract | Removed from ordinary active use according to HKA or MEM rules; do not invent deletion semantics here. |

Correction creates an attributable correction/revision relation. Rejection records disposition rather
than deleting the source. Supersession changes current standing while preserving the prior candidate.
Contradiction connects claims and support; it must not silently choose the most recent, frequent, or
model-confident version.

### Required non-taxonomic envelope

Scope binding, sensitivity, rights/consent, source role, evidence role, Episode posture, identity,
and exact lineage remain mandatory governance context even though they are not axes in the knowledge
taxonomy. The minimum provenance envelope is defined as research in the #3196 data-model memo; this
taxonomy consumes that separation and does not replace it.

## Mapping to existing Yggdrasil concepts

### Candidate-function mappings and non-equivalences

| Proposed function | Closest Yggdrasil concepts | Alignment | Conflict or non-equivalence to preserve |
| --- | --- | --- | --- |
| Descriptive claim | `Claim` semantic identity under SIP; Cognitive Artifact after durable representation. | Can become meaning-bearing content with explicit provenance. | A candidate is not an accepted HKA artifact, evidence, or a source artifact by itself. |
| Decision | Cognitive Operation/transition; Project Artifact or Receipt Artifact when durably recorded. | Records a chosen outcome and its accountable context. | Not every uttered selection is human intent; decision content is distinct from its receipt. |
| Commitment | Commitment, Project, Next Action, Waiting State. | May bind knowledge to responsible future action. | Commitment is an ontology layer, not merely a content tag or MEM class. |
| Open question | Inquiry, Open Loop, Surfacing Need. | Preserves unresolved work and uncertainty. | A question is not automatically the primitive for all retrieval and need not become HKA. |
| Rationale or evidence link | Source Role, provenance, typed relation under SIP, Receipt Artifact. | Makes justification and cited dependencies inspectable. | A projection/citation is not evidence; SIP describes lineage while GOV decides admissibility/standing. |
| Procedure or method | Procedural memory, Cognitive Operation, Work/Project Artifact. | Can support repeatable work and explanation. | Procedural MEM is advisory; an executable policy or delegation belongs to its owning authority boundary. |
| Preference or constraint | Preference memory, Context/Operational Scope, policy/authority boundary. | Can support bounded personalization or explicit constraints. | An inferred preference is not a declared policy; scope and review determine permitted use. |
| Relationship assertion | SIP semantic identity and typed relations; Shared Participation where context overlap is meant. | Fits provenance-bearing relation views. | It does not resolve global identity or create a cross-scope allowance. |
| Reflection or learning | Reflective Artifact, metacognitive state, semantic or episodic memory candidate. | Supports self-observation, calibration, and later learning. | Human reflection and agent-generated learning are not the same authority class. |
| Creative material | Creative Artifact, Work Artifact, cognitive/creative operation. | Preserves generative and exploratory value. | It should not be forced into propositional truth, semantic memory, or settled knowledge. |

### Axis mappings

| Proposed axis | Existing owner/concept | Guardrail |
| --- | --- | --- |
| Function | Cognitive Ontology artifact/commitment/operation meanings; HKA only after durable acceptance. | Function is contextual and multi-valued, not necessarily an intrinsic artifact class. |
| Authority/review | GOV transitions; HKA carries accepted standing; MEM owns memory review lifecycle. | HKA never self-promotes, and MEM never becomes shadow HKA. |
| Provenance/derivation | SIP typed relations and lineage; HKA carries survival-critical origin anchors. | Source role, evidence role, and authority state stay orthogonal. |
| Temporal standing | Temporal validity, staleness, Episode/context, commitment timing. | Do not collapse validity, maturity, review state, salience, and lifecycle. |
| Confidence/uncertainty | MEM confidence/contradiction posture; provenance and review explanations. | Confidence influences review, not truth or authority. |
| Lifecycle/disposition | Candidate/review/promote/reject/revise/decay; ontology transitions. | Promotion is a transition, not an entity; correction never rewrites the source. |

### Vocabulary collisions to avoid

- **Knowledge:** use narrowly for human-authored or human-accepted durable meaning when HKA standing
  matters; do not use it as a blanket name for transcripts, candidates, or model memory.
- **Memory:** qualify human memory, agent memory, MemoryRecord, cache, or retained artifact; the word
  alone does not establish owner or authority.
- **Source:** qualify source role, source binding, emitter, origin, or `source_ref`.
- **Fact:** prefer descriptive-claim candidate until support, scope, validity, and authority are
  explicitly reviewed.
- **Decision:** distinguish proposed option, human intent, accepted decision artifact, and receipt.
- **Preference:** distinguish explicit declaration, inferred candidate, contextual default, and
  policy constraint.
- **Summary:** treat as a projection with lineage, not as a settled knowledge category.
- **Evergreen:** treat as a role/quality/state outcome rather than a base class.

### External standards alignment, not adoption

[W3C SKOS](https://www.w3.org/TR/skos-reference/) separates concepts, concept schemes, labels,
hierarchical/associative relations, collections, and cross-scheme mappings. It supports the research
choice to keep one bounded scheme with explicit mappings rather than claim exact equivalence with
Yggdrasil's ontology. This memo does not propose SKOS/RDF serialization or treat broader/narrower
links as the full meaning model.

[W3C PROV-O](https://www.w3.org/TR/prov-o/) grounds the separation of entities, derivation
activities, responsible agents, attribution, and revision lineage. [DCMI Metadata Terms](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/)
separates resource type, subject, relation, source, provenance, version, and replacement terms. Both
reinforce the need to keep content function, topic, provenance, and lifecycle relations distinct;
neither is adopted as a runtime contract.

## Worked examples

The examples illustrate classification possibilities, not extraction behavior. In every case the
raw fragment remains acquired source material. Any candidate is a new derived object with source-span
lineage; HKA or MEM standing requires its own review path.

### Example 1 — zero candidates

Fragment:

> Human: “Thanks!”  Assistant: “Any time.”

Possible disposition: zero candidate functions. The exchange may remain useful as conversational
context or audit provenance, but no durable cognitive job justifies extraction. Zero is preferable
to inventing a relationship, preference, or positive-sentiment “fact.”

### Example 2 — one candidate, still not knowledge

Fragment:

> Human: “For this project, keep review summaries under five bullets.”

Possible output: one **preference or constraint** candidate, source-asserted by the human, scoped to
the named project, current validity unknown, high extraction confidence, lifecycle `proposed`.

It is not yet a global preference, system policy, hidden instruction, or HKA artifact. Review could
route it to preference MEM, preserve it as a project artifact, correct its scope, or reject retention.

### Example 3 — several candidates with correction and supersession

Fragment:

> Human: “Let's release Tuesday. I will email Legal today.”
> Later: “Correction: release Thursday, pending Legal approval.”

Possible outputs:

1. a **decision** candidate for Tuesday, later `corrected`/`superseded`;
2. a **decision** candidate for Thursday, prospective and conditional;
3. a **commitment** candidate for emailing Legal, with actor and intended time;
4. a **preference or constraint** candidate that Legal approval gates release; and
5. optionally an **open question** candidate if approval ownership/status remains unresolved.

The later message does not erase the first source span. Recency alone does not prove the correction
was authorized, and none becomes HKA without the appropriate governed path.

### Example 4 — assistant claim plus unverified citation

Fragment:

> Assistant: “The retention rule is 30 days,” followed by a link.

Possible outputs: a **descriptive claim** candidate and a **rationale or evidence link** candidate,
both assistant-source and noncanonical. Extraction may be confident while content support remains
unknown. The link must be independently resolved, preserved, and checked; provider citation syntax
does not make it evidence. If the claim conflicts with an owner doc, record contradiction and route
review rather than overwrite either source.

### Example 5 — creative material resists factual flattening

Fragment:

> Human: “What if the archive felt like a winter garden—quiet paths, recurring constellations?”

Possible outputs: one or more **creative material** candidates and perhaps an **open question**. It
should not be normalized into claims that the archive *is* a garden or that “winter” is a stable UI
requirement. Review may preserve the fragment as a Creative Artifact with its ambiguity intact.

### Example 6 — one fragment, different owner routes

Fragment:

> Human: “The deployment failed because the token expired; next time refresh credentials before the run.”

Possible outputs include a historical **descriptive claim**, a **reflection or learning**, and a
**procedure or method** candidate. The occurrence may relate to an Episode; the method may be a
procedural MemoryCandidate; a durable postmortem could become a Project or Reflective Artifact.
Those are different routes with different reviews. A single transcript-level “promote” action would
collapse them incorrectly.

## Recommendation, open questions, and next bounded issues

### Recommendation

Use the ten candidate-function labels only as a research vocabulary for fixture annotation and
human review experiments. Require independent provenance, authority, temporal, uncertainty, and
lifecycle axes for every candidate, plus the non-taxonomic governance envelope. Permit zero and
multi-label outcomes. Preserve correction, contradiction, supersession, and rejection as explicit
relations/dispositions.

Before any adoption, test the vocabulary against representative, consented fixtures from #3195 and
the source/derivation model from #3196. Prefer adding a mapping or relation over expanding the
function set whenever the new concern is actually a topic, artifact class, source role, memory
class, confidence measure, temporal property, or lifecycle state.

Do not create runtime enums, classifiers, prompts, database fields, retrieval facets, automatic
truth scoring, or promotion behavior from this memo. Normative adoption requires a bounded contract
issue or ADR through the owning HKA/SIP/MEM/GOV paths.

### Open questions

- Do the ten functions cover representative exports without turning “other” into a large hidden
  category or forcing creative/reflexive material into claim form?
- Which functions are useful enough to justify extraction, and which should be created only on
  explicit human selection?
- When should commitment language require confirmation before even creating a candidate?
- How should candidate granularity work when one sentence contains several dependent propositions?
- Which confidence components can reviewers understand without false numerical precision?
- What constitutes independent support for assistant-generated claims and citation links?
- Which temporal postures and validity corrections are necessary before resurfacing candidates?
- How should contradictions across scopes be visible without leaking sensitive content?
- Which dispositions belong to a shared candidate-review layer versus HKA- or MEM-owned lifecycle?
- When should creative material remain a whole source fragment instead of decomposed candidates?

### Recommended next bounded issues

1. **Taxonomy annotation study:** annotate a small, consented, provider-diverse fixture set with zero/
   one/multiple functions; record disagreement, missing categories, and reviewer burden.
2. **Candidate granularity and span contract:** decide how atomic candidates reference exact,
   non-contiguous, or cross-conversation spans and how redaction preserves lineage.
3. **Review disposition contract:** define propose/defer/accept/reject/correct/contradict/supersede
   semantics and which transitions are common versus HKA/MEM-owned.
4. **Authority-routing decision:** map candidate functions and evidence postures to allowable MEM,
   HKA, project/commitment, creative, or no-retention routes without automatic promotion.
5. **Contradiction and temporal-validity study:** test correction, disagreement, staleness, and
   supersession examples across scopes and Episodes.
6. **Classifier feasibility experiment:** only after the annotation study, compare deterministic,
   model-assisted, and human-selected classification for precision, provenance, privacy, and cost;
   produce no production classifier.
7. **Vocabulary adoption ADR/contract:** if fixture evidence supports adoption, decide canonical
   names, versioning, mappings, ownership, and migration posture through docs governance.

Creating or implementing these issues is outside #3197.

## Source register and traceability

| Source | What this memo takes from it | What this memo does not claim |
| --- | --- | --- |
| [Cognitive Ontology](../CONCEPTS/COGNITIVE_ONTOLOGY.md) | Artifact, commitment, operation, role/state/property/transition, provenance, receipt, human-authority distinctions. | No new canonical artifact class or ontology layer. |
| [Context and Artifact Dimensions](../CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md) | Separate dimension families; MECE storage can coexist with non-MECE meaning; stable identity and low-friction capture outrank taxonomy purity. | The proposed functions do not control storage paths or become intrinsic metadata. |
| [Agent Memory and Knowledge Contract](../CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md) | MEM classes and explicit observe/candidate/review/promote/reject/revise/decay lifecycle. | MEM classes are not durable-knowledge categories and memory is not hidden authority. |
| [Artifact, Projection, and Source Contract](../CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md) | Artifacts, bounded projections, and source role must not be collapsed. | A summary, transcript, or classifier output is not an accepted artifact by default. |
| [Ontology Vocabulary](../CONCEPTS/ONTOLOGY_VOCABULARY.md) | Canonical meanings and drift warnings for source, memory, review, promotion, artifact, projection, receipt, plan, and action. | Working taxonomy labels do not replace canonical terms. |
| [HKA boundary](../boundaries/HKA.md) | Durable human-authored/accepted knowledge and origin anchors require governed standing. | No candidate self-promotes or changes HKA policy. |
| [SIP boundary](../boundaries/SIP.md) | Semantic identity, typed relations, attribution, lineage, and provenance continuity. | SIP does not decide authority or admissibility. |
| [MemoryRecord](../contracts/MEMORY_RECORD.md) | Explicit review, provenance, confidence, staleness, contradiction, correction, forgetting, and promotion-request posture. | A taxonomy label does not create a MemoryRecord. |
| [Conceptual conversation data model](AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md) | Source-scoped identity, acquired material, derivation activities, candidates, exact spans, governed outcomes, and conceptual lifecycles. | This memo does not add a schema to that model. |
| [W3C SKOS](https://www.w3.org/TR/skos-reference/) | Concept schemes, labels, hierarchy/association, collections, and explicit cross-scheme mappings. | No SKOS/RDF adoption or exact mapping to Yggdrasil ontology. |
| [W3C PROV-O](https://www.w3.org/TR/prov-o/) | Entity/activity/agent, derivation, attribution, and revision-lineage grounding. | No PROV/RDF serialization is selected. |
| [DCMI Metadata Terms](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/) | Comparative separation of resource type, subject, relation, source, provenance, version, and replacement. | DCMI terms are not selected as runtime fields or taxonomy labels. |

## Explicit non-claims

- This taxonomy is advisory research, not a canonical ontology, HKA contract, MEM contract,
  classifier specification, prompt, schema, runtime enum, storage model, retrieval facet, or UI.
- Candidate function does not establish truth, evidence, authority, durability, scope, identity, or
  retention.
- Provider role labels do not determine authorship beyond the source assertion and never determine
  authority.
- Raw transcripts and normalized projections are not promoted by classification.
- Confidence is not authority, repetition is not corroboration, and recency is not correction.
- No recommended issue is created and no runtime or product behavior is implemented by this slice.
