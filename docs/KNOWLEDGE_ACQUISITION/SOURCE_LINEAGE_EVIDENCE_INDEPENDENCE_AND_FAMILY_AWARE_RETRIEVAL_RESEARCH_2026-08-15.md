State: Advisory architecture/research snapshot, 2026-08-15. Repository baseline `main` at `c79026ab38171f269f14a53d96112dd196a830f9`. Subordinate to the cited owner documents; this report does not enact an ontology, schema, storage topology, retrieval behavior, review policy, or implementation backlog.
Doc role: Reference (cross-cutting architecture research)
Authority: Evidence-led comparison of external provenance, evidence, retrieval, and information-architecture patterns against the current Yggdrasil/Mimer design. Owner documents and accepted ADRs win on conflict.
Owner posture: Architecture spine; primary semantic stewardship in SIP, with HKA, DRI, RCA, GOV, HIX, EBF, WSP, PDM, SFC, and OEF implications.
Filing note: Stored as a non-normative sibling in the already indexed Knowledge Acquisition capability directory because source acquisition is the nearest existing research context. This location does not transfer cross-cutting ownership to Knowledge Acquisition.
Temporal class: snapshot
Review cadence: event-driven after material changes to the functional ontology, relation taxonomy, Knowledge Acquisition, retrieval contracts, cognitive-load projections, or multi-vault contracts.
Last verified against: `main` at `c79026ab38171f269f14a53d96112dd196a830f9`
Related issue: #4906

# Source Lineage, Evidence Independence, and Family-Aware Retrieval

## 1. Executive finding

Yggdrasil already contains most of the architecture required to organise, expose, and govern a large body of source material and machine-produced knowledge artifacts. The current design already distinguishes durable artifacts, citable segments, sources, claims, typed relations, rebuildable projections, retrieval results, source role, authority state, evidence role, governed promotion, persistence surfaces, multi-vault context, and cognitive-load projections.

The unresolved capability is narrower than a new knowledge architecture:

> Yggdrasil does not yet have one explicit cross-source contract for grouping representations and derivatives of the same source object, representing when separately published sources share an underlying evidence basis, collapsing redundant retrieval results without losing exact citations, and exposing that distinction to the human.

This report therefore rejects a parallel ontology, a second graph authority, a vault-first partitioning scheme, and a universal scalar trust score. It recommends a bounded cross-boundary capability:

**Source Lineage, Evidence Independence, and Family-Aware Retrieval.**

The capability should add:

1. a logical source-lineage grouping for one source object, its versions, representations, fragments, and derivatives;
2. an evidence-lineage or equivalent governed assessment for sources that depend on the same study, observation, dataset, event, or argument line;
3. family-aware retrieval that finds at segment level but collapses and diversifies at lineage level;
4. explicit review scope, so `reviewed` never implies more verification than occurred;
5. a source-family projection within the existing HIX and Cognitive Load Projection model;
6. corpus, rebuild, synchronization, recovery, and storage-amplification budgets before any physical vault, store, or index split.

The governing invariant is:

> Derivatives may increase accessibility, readability, coverage, and retrieval utility, but they must not increase the counted number of independent evidence lineages.

## 2. Scope, assumptions, and method

### 2.1 Question

How should Yggdrasil organise, expose, and value a growing body of source material and automatically produced knowledge artifacts when one source can produce raw material, transcripts, extractions, summaries, topic-specific analyses, and further derivatives?

The alternatives are tested against:

- provenance;
- epistemic weight and evidence independence;
- searchability;
- cognitive load;
- portability;
- scalability and operational reversibility.

### 2.2 Repository scope

The comparison uses the pinned repository baseline above, with attention to:

- `docs/architecture/functional-ontology.md`;
- `docs/architecture/semantic-dimensions.md`;
- `docs/architecture/metadata-bundle.md`;
- `docs/architecture/retrieval-contract.md`;
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`;
- `docs/CONCEPTS/RELATION_TAXONOMY.md`;
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`;
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`;
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`;
- `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`;
- `docs/KNOWLEDGE_ACQUISITION/**`;
- `docs/YOUTUBE_SOURCE_NOTE_V2/**`;
- `docs/MULTI_VAULT_RUNTIME/**`;
- `docs/contracts/ACTIVE_CONTEXT_SET.md`;
- `docs/RETRIEVAL.md`;
- the HKA, SIP, DRI, RCA, GOV, HIX, EBF, WSP, PDM, SFC, and OEF boundary charters.

This is not a complete code audit. Statements about shipped behavior remain subordinate to `docs/ARCHITECTURE.md`, `docs/STATUS.md`, code, tests, and live runtime evidence.

### 2.3 External research scope

The external comparison uses established reference patterns rather than treating any one standard as Yggdrasil's ontology:

- W3C PROV-O and PAV for entities, activities, agents, derivation, authorship, curation, and digital creation;
- W3C DQV for purpose-dependent quality;
- Cochrane guidance on multiple reports from one study;
- SEPIO, ECO, CiTO, and Web Annotation for claims, evidence, methods, typed citation relations, and fragment anchoring;
- C2PA for the distinction between provenance validity and truth, plus progressive provenance disclosure;
- RO-Crate for portable compound-object packaging;
- DCAT for federated catalogues;
- CQRS and materialised-view patterns for rebuildable read models;
- redundancy-aware retrieval research for duplicate-rich corpora.

## 3. General research conclusions

### 3.1 Provenance, quality, truth, authority, and relevance are separate dimensions

Provenance can show that an artifact was generated by an activity that used another entity and involved a human, organisation, model, or software agent. It does not prove that the result is true. Quality is also purpose-dependent: an artifact can be sufficient for orientation but insufficient for a decision or factual verification.

Yggdrasil should therefore avoid a single `trust`, `quality`, or `confidence` scalar that collapses:

- origin and transformation history;
- source quality for a purpose;
- fidelity to the source;
- evidence independence;
- human review;
- internal authority;
- current retrieval relevance.

The repository's existing separation of `source_role`, `authority_state`, and `evidence_role` is the correct foundation. New dimensions must complement, not replace, those fields.

### 3.2 The artifact is not necessarily the epistemic counting unit

Cochrane treats the study, not every report about the study, as the analysis unit. Several articles, abstracts, press releases, or follow-up reports may contain useful but non-independent information about one study.

The same distinction applies at two levels in Yggdrasil:

1. one source object can have many versions, representations, fragments, and derivatives;
2. several source objects can depend on the same underlying evidence.

A transcript, translation, extraction, summary, and topic analysis may be five useful artifacts but usually add no independent evidence beyond their source. A synthesis of five independent sources integrates five evidence lineages; the synthesis does not automatically become a sixth.

### 3.3 Human versus machine is not a sufficient artifact classification

A human may author a source, software may transcribe it, an agent may summarise it, and another human may correct and accept the result. Origin, transformation, review, and authority must remain separate:

- production origin: human, machine, hybrid;
- contribution role: author, curator, translator, analyst, editor;
- transformation class: lossless, normalising, extractive, abstractive, interpretive, synthetic;
- review scope and outcome;
- authority state and accepted purpose.

A machine-produced verbatim extraction may be more source-faithful than a human-written free summary. Machine origin is not itself low quality, and human involvement is not itself factual validation.

### 3.4 Artifacts and claims are different modelling levels

A note can express several claims with different evidence, temporal validity, uncertainty, and review posture. Yggdrasil already has `Claim`, `Segment`, and typed `Relation`. The appropriate extension is selective use of those objects for durable, decision-relevant, contradictory, or highly reusable knowledge. It is not sentence-level graph materialisation across the whole corpus.

### 3.5 Redundancy is both a retrieval and evidence problem

A duplicate-rich corpus can fill top-k retrieval with near-identical chunks from raw text, transcripts, summaries, and analyses. This reduces useful diversity and can create apparent corroboration.

Yggdrasil should retain fragment-level retrieval for recall and citation accuracy while grouping and presenting results by source lineage and, where known, evidence lineage. Redundant artifacts can improve task fit and coverage without increasing independent-evidence count.

### 3.6 Provenance should be persistent but progressively disclosed

The user should be able to determine:

- what the object is;
- where it came from;
- what transformation occurred;
- whether it was reviewed and for what;
- why this representation is shown now.

The ordinary reading view should not require inspection of a full graph. A compact identity line should lead to an expandable provenance summary, full lineage and version history, and finally technical receipts when needed.

### 3.7 Bundles, catalogues, and indexes serve different purposes

A source bundle packages a source and related representations, derivatives, and metadata. A catalogue resolves identity and location across stores or vaults. An index optimises retrieval and presentation.

They must not be conflated:

- source bundle: portable and inspectable compound object;
- catalogue or resolver: thin identity/location projection;
- index: rebuildable read model;
- durable human knowledge, accepted semantic relations, reviews, authority transitions, and governance receipts: authority-bearing or accountability surfaces.

## 4. Evaluation criteria

| Criterion | Acceptable outcome | Typical failure |
| --- | --- | --- |
| Provenance | Every derivative resolves to exact inputs, transformation activity, responsible agents, and source anchors | A summary merely appears related to a source |
| Epistemic weight | Multiple derivatives or reports do not become multiple independent supports | Five summaries from one study display as five corroborating sources |
| Searchability | Exact fragments remain findable and citable while result sets are diversified | Top-k is dominated by sibling chunks and summaries |
| Cognitive load | Identity, origin, relationship, standing, and reason-for-attention are immediately understandable | Filenames, folders, badges, and colours require manual interpretation |
| Portability | Identity and relations survive rename, vault move, store migration, and index replacement | Paths or plugin-private rows are the only identity |
| Scalability | Workload, retention, rebuild, sync, security, and failure domains can be separated when measured limits require it | Every artifact must be synced, opened, backed up, and indexed as one unit |
| Governability | Machine inference cannot silently become durable semantic or epistemic authority | A similarity score becomes a permanent same-evidence assertion |
| Reversibility | Grouping, review, promotion, and topology changes preserve history and support correction | An incorrect merge destroys prior identities |

## 5. Architecture-pattern comparison

| Pattern | Provenance | Epistemic weight | Searchability | Cognitive load | Portability | Scalability | Main consequence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Flat artifact estate | 2 | 1 | 2 | 2 | 5 | 2 | Simple Markdown representation, but file, identity, presentation, and epistemic unit become conflated |
| Source dossier / compound object | 4 | 3 | 3 | 5 | 5 | 3 | Strong source-family and export unit; does not solve cross-source independence |
| Lifecycle / persistence zones | 3 | 3 | 4 | 4 | 4 | 5 | Strong operational separation; physical placement must not become hidden authority state |
| Provenance graph | 5 | 4 | 4 | 2 | 4 | 4 | Strong lineage and audit; requires profiles and projected views to avoid graph explosion |
| Claim/evidence model | 5 | 5 | 5 | 3 | 4 | 3 | Strongest epistemic precision; too costly as a universal sentence-level model |
| Federated catalogue with read projections | 3 | 3 | 4 | 3 | 5 | 5 | Strong multi-vault scaling; requires stable identity and does not itself solve evidence semantics |

No pattern satisfies every criterion. The appropriate architecture is a composition:

- source dossier as the human-facing and portable unit;
- provenance graph as logical lineage;
- selective claim/evidence modelling for important knowledge;
- lifecycle and persistence surfaces for operations;
- a thin resolver and rebuildable read projections for multi-vault scale.

## 6. Fit with the current Yggdrasil design

| Area | Current design | Disposition |
| --- | --- | --- |
| Core ontology | `Artifact`, `Segment`, `Claim`, `Concept`, `Relation`, `Source`, `Projection`, and `RetrievalResult` are distinct | Already canonical; reuse them |
| Source versus representation | Source, artifact, segment, projection, source role, and content identity are separated | Already canonical or substantially present |
| Authority and evidence | `source_role`, `authority_state`, and `evidence_role` are orthogonal | Stronger than a generic trust model; preserve unchanged |
| Transformation lineage | `derived_from`, immutable raw, stage/version, events, and replay exist in Knowledge Acquisition | Partially canonical and partly delivered |
| Source-family grouping | YouTube/KAP have source-specific item and content identity plus staged derivation | Partially present; not a generic cross-source projection |
| Evidence independence | Claims and evidence roles exist, but no explicit general contract states that several sources share one underlying study or observation | Missing or unresolved |
| Human/machine contributions | Creation, review, proposal, promotion, and authority transition are separated | Largely canonical; add transformation and review-scope detail only if needed |
| Claim/evidence anchoring | Claims and segments are first-class; source-note work adds exact anchors | Target-state fit is strong; delivery is incomplete across all source paths |
| Retrieval | Candidate-level ranking and exact citations exist; family collapse and evidence-lineage diversification are not established | Material gap |
| Cognitive-load UI | Existing projection model separates source, interpretation, uncertainty, and `why_now` | Reuse; add a concrete source-family projection |
| Persistence surfaces | Writing, retention, mirrors/indexes, operational traces, and receipts are distinguished | Strong fit; do not treat all system data as disposable |
| Multi-vault | Registry, vault bindings, `ActiveContextSet`, dimensions, and provenance-preserving composition exist or are specified | Strong logical base; complete resolver/runtime behavior remains to validate |
| Quantitative scale budgets | Repository recognises NFR gaps but lacks the corpus/rebuild/sync budgets needed for this decision | Missing |

The central semantic gap is the difference between source derivation and evidence independence.

### 6.1 Source lineage

Source lineage means the same source object across versions, representations, fragments, and derivatives.

Example:

```text
Video Y1
├── content identity v1
│   ├── raw media
│   ├── transcript
│   ├── extraction
│   └── summary
└── content identity v2
    ├── raw media
    ├── transcript
    └── analysis
```

Most of this grouping can be derived deterministically from existing source identity, content identity, `derived_from`, and stage/version metadata. It should therefore be primarily a rebuildable DRI projection, although it may require a stable public grouping identity for references and UI state.

### 6.2 Evidence lineage

Evidence lineage means that separately published sources depend on the same underlying study, observation, dataset, event, or argument line.

Example:

```text
Study E1
├── journal article S1
├── conference abstract S2
├── university press release S3
└── news report S4
```

Four sources and their derivatives may still represent one evidence lineage. Different URLs, authors, publishers, paths, files, or vaults do not establish independence.

This relation is often uncertain. `independence_unknown` must be a normal state. Machine suggestions may be useful, but an inference that changes counted evidence or durable semantic meaning must remain a non-authoritative projection until accepted through the existing SIP/GOV mechanisms.

## 7. Proposed capability boundary

### 7.1 Minimum logical additions

Do not introduce a new central super-model. Validate the minimum additions to existing contracts:

- source-lineage grouping or projection;
- evidence-lineage / overlap / independence assessment;
- review or assessment scope;
- family-aware retrieval result projection;
- source-family HIX projection;
- evaluation and operating budgets.

### 7.2 Suggested ownership

| Boundary | Responsibility |
| --- | --- |
| SIP | Meaning and identity of source lineage, evidence lineage, overlap, independence, and accepted semantic relations |
| EBF / Knowledge Acquisition | Stable source/item/content identity and acquisition provenance |
| HKA | Durable human-confirmed groupings, accepted syntheses, and human-authored or promoted knowledge artifacts |
| DRI | Rebuildable source-lineage projections, collapse metadata, and resolver projections |
| RCA | Grouping, representative selection, diversification, and result composition after eligibility filtering |
| GOV | Review scope, human confirmation, authority transition, and policy constraints |
| HIX | Source-family cards, artifact stacks, uncertainty, progressive provenance, and why-shown explanations |
| WSP | Active vault bindings and context selection |
| PDM / SFC | Physical storage, location, replication, and resolver mechanics without becoming semantic authority |
| OEF | Duplicate-rate, false-merge/split, retrieval diversity, freshness, rebuild, and recovery observability |

### 7.3 Retrieval ordering

The target pipeline should preserve existing eligibility and citation rules:

```text
1. Apply scope, sensitivity, policy, and admissibility checks.
2. Retrieve candidates at artifact/segment level for recall.
3. Map eligible candidates to source lineage.
4. Collapse redundant siblings without deleting access to them.
5. Select the best representation for the task: orientation, verification, analysis, or audit.
6. Diversify over evidence lineage where known; preserve unknown explicitly.
7. Assemble context under existing GOV constraints.
8. Cite the exact source and segment used.
9. Present one family result with expandable siblings and a why-shown explanation.
```

Family collapse must not occur before policy eligibility, and it must not replace exact citation with a generic family citation.

### 7.4 Three independent value dimensions

A single score should not determine every behavior. At least three values are needed:

1. **Retrieval utility** — which representation best serves the current task?
2. **Epistemic contribution** — how much independent support does the object add?
3. **Attention value** — does this require human attention now?

A machine summary may have high retrieval utility, zero new independent evidence, and low attention value. A new contradictory independent study may have high epistemic and attention value even if its initial presentation is poor.

### 7.5 Review scope

A general `reviewed` badge is insufficient. A review should identify:

```yaml
reviewer:
target_object:
target_version:
review_scope:
review_method:
outcome:
reviewed_at:
evidence_or_notes:
```

Candidate scopes include format, completeness, source fidelity, citation integrity, factual accuracy, method quality, argument quality, fit for purpose, and authority acceptance.

Review is not authority. A source-fidelity-reviewed draft may still be unaccepted, non-normative, and not fact-verified.

### 7.6 Human-facing projection

The default search and reading view should normally show one source family rather than a flat list of derivatives.

Example:

```text
Agentic Development at Company X
Research report · external source

1 source lineage · 7 derivatives · 2 versions
1 known evidence lineage
Selected view: human-corrected summary
Source fidelity reviewed; factual accuracy not separately reviewed

[Open selected view] [Original] [Show derivatives]
[Evidence and lineage] [Technical details]
```

The projection should explain why it is shown:

- which segment matched;
- why this representation was selected;
- how many siblings were collapsed;
- whether the result adds a new, shared, or unknown evidence lineage.

The projection is non-authoritative and cannot itself mutate grouping, review, or authority state.

### 7.7 Thin catalogue or resolver

Future cross-vault discovery may require a thin resolver containing stable identity, current locations, vault bindings, schema versions, and selected lineage projections.

It must remain:

- subordinate to HKA/SIP/GOV authority;
- rebuildable where its facts can be recovered;
- explicit about stale or unresolved entries;
- separate from the vault registry and `ActiveContextSet`;
- unable to promote machine-inferred evidence relations.

## 8. Invariant kernel

| ID | Invariant | Enforcement posture |
| --- | --- | --- |
| INV-SLER-1 | Derivatives and alternate reports never increase independent-evidence count merely by existing | MUST |
| INV-SLER-2 | Family collapse preserves exact source and segment citations used in the answer or synthesis | MUST |
| INV-SLER-3 | Different paths, URLs, publishers, authors, files, or vaults do not imply evidence independence | MUST |
| INV-SLER-4 | Machine-inferred source/evidence-lineage relations remain proposal/projection class until governed confirmation | GATE |
| INV-SLER-5 | Every displayed reviewed status exposes review scope, target version, reviewer, and outcome | MUST |
| INV-SLER-6 | Rebuilding an index or lineage projection cannot lose canonical artifacts, accepted semantic relations, human reviews, authority transitions, or receipts | MUST |
| INV-SLER-7 | Cross-vault grouping preserves original vault binding, source identity, scope, sensitivity, and per-source provenance | MUST |
| INV-SLER-8 | `independence_unknown` remains visible and cannot be silently upgraded by ranking or UI composition | GATE |
| INV-SLER-9 | A source-family UI projection is non-authoritative | MUST |
| INV-SLER-10 | Physical partitioning follows measured operating limits and remains reversible to a supported simpler topology | DOCTOR/GATE |

## 9. Physical scaling criteria

Logical separation should precede physical separation:

- writing and accepted human knowledge;
- retained source and artifact estate;
- rebuildable indexes and projections;
- durable governance receipts;
- optional thin identity/location catalogue.

Physical boundaries should be introduced only when measured budgets are persistently violated.

| Dimension | Required measurement |
| --- | --- |
| Interactive performance | p50/p95 open, browse, search, and metadata-update latency |
| Index freshness | source or artifact change to searchable result |
| Ingestion capacity | arrival rate, queue time, retries, and backlog |
| Rebuild | full and incremental rebuild time and resources |
| Recovery | backup/restore time, RTO, and RPO |
| Sync | transferred volume, backlog, conflicts, and time to consistency |
| Storage amplification | total retained and derived bytes relative to original sources |
| Failure domain | maximum material affected by corruption, stale projection, or unavailable store |
| Security and retention | subsets requiring different access, export, deletion, or legal posture |
| Working set | active versus cold access and mutation rates |
| Mobile footprint | material that must exist on constrained devices |
| Ownership | different stewards, release cycles, or governance regimes |

No universal file-count or gigabyte threshold is defensible without runtime and device measurements. Single-user does not imply small corpus.

## 10. Main risks

| Risk | Failure mode | Mitigation |
| --- | --- | --- |
| Apparent corroboration | siblings or reports of one study display as independent support | lineage-aware counts and collapse |
| False merge | independent sources are grouped together | confidence, human correction, reversible relations, retained identities |
| False split | repeated reports remain separate | citation/provenance analysis and explicit unknown |
| Review laundering | human reviewed is read as full factual validation | mandatory review scope and outcome |
| Scalar trust distortion | one number hides origin, quality, independence, authority, and relevance | orthogonal dimensions and contextual explanation |
| Graph explosion | every chunk and run step becomes a durable semantic node | provenance profiles and selective permanence |
| Claim explosion | every sentence becomes an assertion object | selective claim modelling |
| Artifact noise | every generation becomes a visible note | family projection, virtualisation, and materialisation policy |
| Index drift | catalogue or index differs from canonical objects | versions, watermarks, health checks, deterministic rebuild |
| Path lock-in | location becomes identity | stable IDs and resolver |
| AI non-reproducibility | regeneration changes an output that influenced a decision | preserve decision-used outputs and generation receipts |
| Source mutation | mutable external source invalidates derivatives | snapshots, acquisition time, content identity/hash, invalidation |
| Rights mismatch | source and derivative have different permissible use | rights and retention per representation and artifact |
| Poisoning | untrusted source content influences control metadata or instructions | trust boundaries, schema validation, content quarantine |

## 11. Repository-validated disposition

### 11.1 Findings suitable for an architecture-validation issue

The following findings are sufficiently grounded to enter a bounded architecture issue:

- source lineage and evidence lineage are distinct concerns;
- derivatives must not add independent-evidence count;
- retrieval should remain fragment-capable but compose results at lineage level;
- review needs explicit scope;
- the UI should expose one source-family projection through progressive disclosure;
- physical topology must remain undecided until operating budgets exist.

### 11.2 Actions not authorised by this report

This report authorises none of the following:

- new runtime classes or database tables;
- a graph database;
- a new vault or folder layout;
- a global catalogue service;
- changes to retrieval ranking;
- automatic evidence-independence decisions;
- new authority states;
- universal claim extraction;
- implementation issues before the owner-document contract is accepted.

### 11.3 Required reconciliation

The architecture work must reconcile with, not absorb or duplicate:

- YouTube Source Note v2 parent #4107;
- evidence-anchored synthesis and claims #4112;
- portable YouTube source bundle #4113;
- final source-note quality evaluation #4119;
- Knowledge Acquisition source/item/content identity and replay;
- Multi-vault Runtime parent #2143 and `ActiveContextSet`;
- CKM Evidence Profile's distinct-artifact/shared-evidence precedent;
- current retrieval and context-bundle contracts.

The new work is cross-source architecture. Existing YouTube tasks remain source-specific delivery contracts.

## 12. Open decisions

1. Is source lineage a first-class functional object, a deterministic projection, or a projection with stable public identity?
2. Is evidence lineage a first-class object, typed relation cluster, assessment, or combination?
3. Which independence states are canonical, and which may affect counted evidence?
4. Which lineage relations may be suggested, accepted, revised, or revoked?
5. Which review scopes and outcomes form the minimum shared contract?
6. At what stage does family collapse occur relative to ranking, reranking, GOV admission, and context assembly?
7. How is a representative artifact selected for orientation, verification, analysis, and audit?
8. Which lineage metadata belongs in canonical artifacts versus rebuildable DRI projections?
9. What identity and resolver behavior is required across vault bindings?
10. Which SLOs and corpus budgets trigger physical separation?
11. Which evaluation corpus measures false merge, false split, duplicate top-k, citation preservation, and diversity?
12. Does the accepted design require an ADR, owner-document amendments only, or a dedicated capability specification?

## 13. Recommended next step

Use issue #4906 as the blocked Product/Runtime architecture-validation hub. It should:

- validate these findings against the complete repository and selected runtime paths;
- assign exact ownership across SIP, HKA, DRI, RCA, GOV, HIX, EBF, WSP, PDM, SFC, and OEF;
- resolve the representation and authority decisions above;
- propose the minimum owner-document contract delta;
- define an evaluation corpus and measurable operating budgets;
- reconcile adjacent YouTube, Knowledge Acquisition, retrieval, and multi-vault work;
- only then produce a dependency-ordered implementation issue set.

The first implementation experiment, if later authorised, should use deterministic source lineage on the existing YouTube path. Evidence-lineage inference should not be the first implementation slice.

## 14. External references

- W3C PROV-O: <https://www.w3.org/TR/prov-o/>
- W3C Data Quality Vocabulary: <https://www.w3.org/TR/vocab-dqv/>
- PAV ontology paper: <https://jbiomedsem.biomedcentral.com/articles/10.1186/2041-1480-4-37>
- Cochrane Handbook, multiple reports of the same study: <https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-05>
- SEPIO: <https://obofoundry.org/ontology/sepio.html>
- ECO: <https://obofoundry.org/ontology/eco.html>
- CiTO: <https://www.sparontologies.net/ontologies/cito>
- W3C Web Annotation Data Model: <https://www.w3.org/TR/annotation-model/>
- C2PA explainer: <https://spec.c2pa.org/specifications/specifications/2.4/explainer/Explainer.html>
- C2PA UX guidance: <https://spec.c2pa.org/specifications/specifications/2.2/ux/UX_Recommendations.html>
- RO-Crate profiles: <https://www.researchobject.org/ro-crate/specification/1.2/profiles.html>
- W3C DCAT 3: <https://www.w3.org/TR/vocab-dcat-3/>
- CQRS pattern: <https://learn.microsoft.com/azure/architecture/patterns/cqrs>
- Redundancy-aware RAG evaluation: <https://aclanthology.org/2026.acl-long.923/>
