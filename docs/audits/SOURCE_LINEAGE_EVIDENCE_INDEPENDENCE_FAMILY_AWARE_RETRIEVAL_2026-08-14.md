State: Advisory architecture audit snapshot (2026-08-14). Non-normative and subordinate to `docs/DOCS_INDEX.md`, current-state owner documents, accepted architecture contracts, implementation evidence, and live GitHub delivery state. This audit authorizes no runtime, schema, storage, vault-topology, backlog, or implementation change.
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis of source lineage, evidence independence, derivative redundancy, review semantics, retrieval presentation, multi-vault portability, and corpus-scale limits. Repository anchors reflect `main` at `c79026ab38171f269f14a53d96112dd196a830f9`; owner documents and shipped code/tests win on conflict.
Owner: Architecture research; proposed future ownership is allocated to existing Mimer control boundaries in this audit.
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed — repository contracts/current-state documents plus external standards and research.
Last reviewed: 2026-08-14
Last verified against: `main` commit `c79026ab38171f269f14a53d96112dd196a830f9`; the repository documents and live Issues named below.
Promotion state: advisory-only. No accepted `PromotionIntent` transition or corresponding `BuilderOpsReceipt` was available during this review; therefore no capability specification, parent feature Issue, or implementation Issue is authorized by this document.

# Yggdrasil Source Lineage, Evidence Independence, and Family-Aware Retrieval — Architecture Audit

## Executive finding

Yggdrasil does **not** need a second general knowledge-artifact architecture to manage a growing body of source material and machine-produced derivatives. The current design already supplies most of the required substrate:

- `Artifact`, `Segment`, `Claim`, `Relation`, `Source`, `Projection`, and `RetrievalResult` are distinct functional objects;
- `source_role`, `authority_state`, and `evidence_role` are orthogonal;
- acquisition preserves immutable raw material, content identity, derivation, stage/model identity, replay, and non-destructive candidate materialization;
- machine memory, projections, and generated proposals are non-authoritative by default;
- cognitive-load projections preserve source visibility and separate source, interpretation, uncertainty, and action; and
- multi-vault selection and binding identity are modeled independently from scope and authority.

The remaining material gap is narrower:

> Yggdrasil can largely explain how an object was derived, but it cannot yet consistently express or use the fact that several artifacts share one source lineage, or that several apparently different sources rely on the same underlying study, observation, dataset, event, or argument line.

This creates two failure modes:

1. **Derivative multiplication:** a source, transcript, extraction, summary, analysis, and several chunks can occupy several result positions even though they add no independent evidence.
2. **Report multiplication:** an article, abstract, press release, and news report can appear to provide four corroborating sources while all ultimately report one underlying evidence origin.

The recommended future capability is therefore:

> **Source lineage, evidence independence, and family-aware retrieval**, implemented inside the existing ontology and SBS boundaries.

The minimum coherent architecture delta is to:

- derive and expose source-lineage groupings;
- represent evidence-independence posture separately from source identity;
- introduce review assessments with explicit scope;
- collapse redundant retrieval candidates while preserving exact citations;
- diversify result sets across known evidence lineages;
- render source families and uncertainty through the existing Cognitive Load Projection Layer; and
- establish quantitative corpus, rebuild, freshness, recovery, and synchronization budgets before physical topology changes.

This audit is suitable for a docs-only advisory PR. Converting it into an executable specification or GitHub Issue requires the separate governed promotion transition.

---

## 1. Scope, baseline, and limitations

The review examines how Yggdrasil should organize, expose, search, and value raw material, transcripts, extractions, summaries, topic-specific analyses, syntheses, and other derivatives while preserving provenance, epistemic weight, low cognitive burden, Obsidian compatibility, multi-vault portability, and scale.

Repository-specific conclusions were compared against `main` at `c79026ab38171f269f14a53d96112dd196a830f9`. The review inspected the functional ontology, semantic dimensions, metadata bundle, relation taxonomy, acquisition refinement pipeline, YouTube Source Note v2, retrieval contract/current retrieval documentation, Cognitive Load Projection Layer, vault topology, multi-vault runtime, requirements coverage, and relevant live Issues.

This was not a local full-code or production-corpus audit. The session did not have executable runtime telemetry or a write-capable BuilderOps authority surface. Later implementation work must revalidate current code, schemas, tests, corpus characteristics, runtime configuration, open Issues/PRs, and exact branch truth.

The report separates:

- **general research conclusions** supported by standards and mature practice;
- **repository observations** grounded in current Yggdrasil documents and live delivery state; and
- **implementation validation questions** that require code, data, or operational evidence.

---

## 2. Core terminology and non-conflation rules

| Term | Meaning in this audit | Yggdrasil consequence |
| --- | --- | --- |
| **Source object** | Origin entity or locator from which an artifact or claim derives. | Reuse canonical `Source`; do not introduce a competing base type. |
| **Source lineage** | One source object, its acquired versions/representations, and artifacts or projections derived from them. | Prefer a rebuildable projection over existing identity and provenance before adding a canonical object. |
| **Evidence lineage** | The underlying study, observation, dataset, measurement, event, or argument line that may provide independent support. | Must not be inferred from URL, publisher, file path, or source identity alone. |
| **Derivative** | Transcript, extraction, translation, summary, analysis, synthesis, candidate, or other result based on prior objects. | Existing `Artifact`, `Projection`, `Claim`, proposal, and `derived_from` semantics remain authoritative. |
| **Review assessment** | A judgment about a target version for a named scope, method, and outcome. | Complements review and authority transitions; does not replace `authority_state`. |
| **Family-aware retrieval** | Fine-grained retrieval followed by lineage grouping, representative selection, redundancy collapse, and evidence-lineage diversification. | Extends RCA/DRI while preserving GOV eligibility, exact citations, and scope isolation. |

### Source lineage is not evidence lineage

```text
One source object and its derivatives
    = one source lineage

Several publications reporting one underlying study
    = several source lineages, potentially one evidence lineage
```

Different URLs, authors, publishers, or files do not establish evidential independence. `unknown` must remain a normal, visible state.

---

## 3. General research conclusions

1. **Provenance is not truth.** W3C PROV and C2PA support reconstructing entities, activities, agents, origin, and integrity, but do not establish epistemic correctness. Yggdrasil must keep provenance, review, authority, evidence role, independence, and query relevance separate.
2. **Quality is task-dependent.** W3C DQV treats quality as contextual. A summary may be useful for orientation but unsuitable for verification. One universal trust score would create false precision.
3. **The evidence-counting unit may not be the publication.** Cochrane links multiple reports of one study and uses the study as the analytical unit to avoid double counting. Yggdrasil should count distinct evidence lineages, not files, chunks, URLs, or summaries.
4. **Authorship, curation, transformation, review, and digital production are distinct contributions.** PAV provides the relevant distinction. Human-created is not automatically correct; machine-created is not automatically unfaithful.
5. **Claims may require fragment-level evidence.** SEPIO, ECO, CiTO, and Web Annotation support separating assertions from the documents and fragments that support them. Yggdrasil already has `Claim` and `Segment`; use them selectively rather than graphing every sentence.
6. **Redundancy is both a retrieval and an epistemic problem.** Retrieval may operate at segment level for recall, but results should aggregate and diversify at source/evidence-lineage level.
7. **Provenance should use progressive disclosure.** The UI should show a compact identity/review/lineage strip first, then a lineage summary, then full technical history on demand.
8. **Packages, catalogues, and indexes solve different problems.** RO-Crate, DCAT, and materialized-view/CQRS patterns imply distinct source bundles, resolver/catalog projections, and search indexes. They should not be collapsed into one authority store.

External standards are adapters and evidence sources, not imported Yggdrasil ontology.

---

## 4. Architecture-pattern comparison

Scores are relative to this use case: 1 = weak, 3 = conditional, 5 = strong. They are not empirical benchmarks and should not be summed into one automatic decision.

| Pattern | Provenance | Evidence independence | Search | Cognitive load | Portability | Scale | Main consequence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Flat artifact collection | 2 | 1 | 2 | 2 | 4 | 2 | Low initial cost, but files/projections become implicit evidence units and duplicate results proliferate. |
| Source dossier / compound object | 4 | 3 | 3 | 5 | 5 | 3 | Best user grouping of one source and its derivatives; does not resolve several sources sharing one evidence origin. |
| Lifecycle/storage zones | 3 | 2 | 4 | 4 | 4 | 5 | Useful for retention, sync, and active/cold separation; location must not become epistemic status. |
| Provenance graph | 5 | 4 | 4 | 2 | 4 | 4 | Strong lineage and impact analysis; requires bounded profiles and progressive projections. |
| Claim/evidence graph | 5 | 5 | 5 | 3 | 4 | 3 | Strongest for contested or decision-critical knowledge; too costly as a universal sentence-level model. |
| Federated catalogue + read projections | 3 | 3 | 4 | 3 | 5 | 5 | Strong multi-vault posture; does not itself define semantic independence or authority. |

No single pattern is sufficient. The lowest-change composition is to retain Yggdrasil's current artifact/source/projection ontology, add a source-lineage dossier projection, add selective evidence-lineage assessments, preserve bounded provenance and claim/evidence modeling, and use resolver/index projections for multi-vault and large-corpus operation.

---

## 5. Comparison with the current Yggdrasil design

| Requirement | Current coverage | Remaining delta |
| --- | --- | --- |
| Artifact versus projection | Existing artifact/projection contracts and functional ontology distinguish durable meaning from rebuildable views. | No parallel artifact hierarchy is needed. |
| Durable identity versus location | Artifact identity is not path identity; vault/binding identity is separate from scope. | Validate source/artifact resolver behavior across all retained objects and vault bindings. |
| Semantic standing | `source_role`, `authority_state`, and `evidence_role` are orthogonal. | Add independence and review scope as separate assessments, not replacement state axes. |
| Provenance | Metadata bundles preserve `derived_from`, creators, timestamps, hashes, and provenance events. | Determine the smallest lineage extension/profile required for grouping. |
| Relation authority | Inferred relations are rebuildable suggestions; confirmed semantic edges are governed and durable. | Use the same model for proposed versus confirmed evidence-lineage relations. |
| Acquisition lineage | Raw, normalized, extracted, and candidate stages preserve identity, version, model, anchors, replay, and non-authoritative posture. | Generalize source-lineage projection beyond source-specific pipelines. |
| Evidence-anchored derivatives | YouTube Source Note v2 requires immutable evidence, lineage, anchored claims, and non-destructive human authority. | Reconcile with #4107/#4112/#4113/#4119; do not create a competing YouTube capability. |
| Retrieval | Policy eligibility precedes ranking; candidates carry metadata, admissibility, evidence role, explanations, and citation ranges. | Add group identity, representative choice, collapsed count, and evidence-lineage diversification. |
| Cognitive-load UI | Existing projection rules preserve source visibility and distinguish source, interpretation, uncertainty, and action. | Define a concrete source-family projection and “why shown” explanation. |
| Multi-vault | Vault, instance, binding, selection, and scope semantics are separated; single-vault remains the floor. | Consume #2143's active bindings; do not create a second multi-vault registry. |
| Scale | Quantitative NFR and scalability targets remain absent/open. | Add minimal corpus, latency, freshness, rebuild, recovery, sync, and storage-amplification budgets before partitioning. |

### Main gap statement

The current design strongly models **derivation from a source**. It does not yet provide one general contract for:

- grouping all versions, representations, and derivatives of one source for retrieval and presentation;
- expressing that several separate source objects share or may share one underlying evidential basis;
- preventing those objects from being counted or ranked as independent corroboration;
- explaining collapsed results and unresolved independence to the human.

---

## 6. Recommended logical capability

### 6.1 Source-lineage projection

Source-lineage membership should first be derived from existing facts such as:

```text
source identity / item_ref
content_identity
raw_record_id
derived_from
stage and stage version
proposal predecessor
```

The initial source-lineage group should be a rebuildable DRI projection over SIP- and acquisition-owned identity/provenance facts. The UI may call it a **source family**. It must not become a new authority store.

### 6.2 Evidence-lineage assessment

Evidence lineage concerns separate source objects that may rest on the same study, observation, dataset, measurement, event, or argument line. A minimal posture should support:

```text
same
overlapping
independent
unknown
```

The exact vocabulary is an owner decision. Machine output may only propose an assessment with supporting evidence, confidence/uncertainty, and explanation. An unconfirmed assessment is a rebuildable projection. A human-confirmed assessment that changes durable evidence interpretation must use the existing governed relation/assessment and receipt path.

### 6.3 Family-aware retrieval

A target flow is:

```text
1. Resolve active vault/context bindings.
2. Apply scope, sensitivity, suppression, and policy eligibility.
3. Retrieve candidates at artifact/segment/projection granularity.
4. Map candidates to source lineage.
5. Collapse redundant candidates within each lineage.
6. Select a representative according to task fit.
7. Diversify across evidence lineages where known.
8. Preserve unknown independence conservatively.
9. Apply final context admission and citation policy.
10. Present one family result with expandable derivatives and exact source citations.
```

The selected representative is a presentation choice, not source substitution. Citations continue to target exact admitted source fragments.

A conceptual valuation model is:

```text
family_retrieval_utility = max(task_fit(candidate))
                         + bounded complementary-coverage bonus

epistemic_count = count(distinct confirmed evidence lineages)
```

Within-lineage contribution must be bounded or saturating, never linearly additive.

### 6.4 Separate value questions

Yggdrasil should keep at least three values distinct:

- **retrieval utility:** which representation best serves orientation, verification, analysis, or decision;
- **epistemic contribution:** how much independent support the object adds; and
- **attention value:** whether the object requires human judgment now.

A machine summary can have high retrieval utility, zero new evidential contribution, and low attention value.

### 6.5 Scoped review

A generic `reviewed` badge is insufficient. A review assessment should identify:

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

Potential scopes include `format`, `completeness`, `source_fidelity`, `citation_integrity`, `factual_accuracy`, `method_quality`, `argument_quality`, `fit_for_purpose`, and `authority_acceptance`.

Review does not erase machine origin or imply canonical authority. Promotion remains a separate governed transition and may materialize a separate HKA artifact where the owner contract requires it.

---


## Appendices

- [Operating model, scaling, risks, gap ledger, and invariant kernel](source_lineage_evidence_independence_2026-08-14/OPERATING_MODEL_AND_RISKS.md)
- [Evaluation, promotion-gated handoff, open decisions, and sources](source_lineage_evidence_independence_2026-08-14/EVALUATION_AND_HANDOFF.md)
