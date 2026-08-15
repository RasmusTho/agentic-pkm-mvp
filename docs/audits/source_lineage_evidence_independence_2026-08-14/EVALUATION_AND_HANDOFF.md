State: Advisory appendix to `../SOURCE_LINEAGE_EVIDENCE_INDEPENDENCE_FAMILY_AWARE_RETRIEVAL_2026-08-14.md`. Non-normative; the parent audit and current owner documents govern interpretation.
Doc role: Reference (audit appendix)

# Evaluation and promotion-gated handoff

## 13. Evaluation criteria

A future implementation should measure:

- duplicate candidate rate before and after collapse;
- distinct source lineages and evidence lineages in top-k;
- false-collapse and missed-collapse rates;
- representative-selection accuracy by task type;
- exact-citation correctness after grouping;
- independence-assessment calibration and `unknown` rate;
- user time to identify origin, transformation, review scope, and evidential contribution;
- retrieval latency and index freshness;
- full/incremental rebuild duration;
- cross-vault identity and lineage preservation;
- storage amplification and device footprint;
- recovery time and semantic-loss tests.

Required scenarios include:

```text
A. One source creates ten derivatives.
   Retrieval presents one family, exact citations remain available, and no extra evidence is counted.

B. Four publications report one study.
   The system can represent same, overlapping, independent, or unknown evidence lineage.

C. A human edits a machine summary.
   Machine generation, human contribution, review scope, and authority transition remain distinct.

D. A source changes.
   Dependent artifacts can be found and marked potentially stale without rewriting history.

E. A file moves to another vault.
   Identity, review, claims, provenance, and lineage survive.

F. The index is deleted and rebuilt.
   No source evidence, human review, accepted knowledge, or authority receipt is lost.
```

---

## 14. Dependency-ordered next steps

These are recommendations, not authorized backlog.

1. **Governed promotion:** create a BuilderOps `PromotionIntent` for this audit; record dispositions for F1–F10; accept, reject, narrow, or defer through the gateway and receipt path.
2. **Reconciliation:** compare accepted findings against #4107/#4112/#4113/#4119, #2143, and any newer source/retrieval work before creating a parent Issue.
3. **Docs-only contract delta:** decide exact definitions, relation/assessment model, ownership, metadata extension, retrieval fields, review scopes, evaluation plan, and NFR budgets.
4. **Deterministic source lineage first:** use an existing vertical such as YouTube Source Note v2 to derive source families from current identity/provenance without new epistemic claims.
5. **Family-aware retrieval:** add grouping, collapse, representative selection, exact-citation preservation, transparent collapsed counts, and evaluation.
6. **Human projection:** add source-family cards and progressive lineage/evidence views under the existing Cognitive Load Projection Layer.
7. **Scoped review:** implement explicit review assessment semantics.
8. **Evidence-lineage proposals:** add machine-suggested same/overlapping/independent/unknown assessments only after deterministic lineage exists; require visible evidence, uncertainty, confirmation, and reversibility.
9. **Scale and topology:** measure the real corpus and set budgets before changing physical vault/storage/index topology.

No new GitHub Issue should be created from this audit until the promotion receipt exists. The Issue should then be a design/reconciliation hub, not an immediate implementation epic.

---

## 15. Open owner decisions

1. Should evidence lineage be a first-class functional object or a typed assessment/relation over existing Sources and Claims?
2. Which independence vocabulary is expressive but small enough for reliable review?
3. Which review scopes are canonical and which remain extensible?
4. Which source-lineage fields belong in the metadata bundle versus a DRI projection extension?
5. Does representative selection belong in `RetrievalResult`, a later result-set projection, or both?
6. What conservative rule applies when independence is unknown in decision-critical synthesis?
7. Which minimal latency, freshness, rebuild, recovery, sync, and storage-amplification budgets are appropriate for a single-human but potentially very large corpus?
8. Should promoted work extend #4107, create a sibling capability after reconciliation, or be decomposed into existing ontology/retrieval/multi-vault parents?

---

## 16. Sources

### Repository authorities and active delivery

- `docs/architecture/functional-ontology.md`
- `docs/architecture/semantic-dimensions.md`
- `docs/architecture/metadata-bundle.md`
- `docs/architecture/retrieval-contract.md`
- `docs/CONCEPTS/RELATION_TAXONOMY.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md`
- `docs/RETRIEVAL.md`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`
- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/REQUIREMENTS_INDEX.md`
- live Issues #2143, #4107, #4112, #4113, and #4119

### External research and standards

- W3C PROV-O: <https://www.w3.org/TR/prov-o/>
- W3C Data Quality Vocabulary: <https://www.w3.org/TR/vocab-dqv/>
- W3C Web Annotation Data Model: <https://www.w3.org/TR/annotation-model/>
- W3C DCAT 3: <https://www.w3.org/TR/vocab-dcat-3/>
- C2PA Explainer: <https://spec.c2pa.org/specifications/specifications/2.4/explainer/Explainer.html>
- C2PA UX Guidance: <https://spec.c2pa.org/specifications/specifications/2.2/ux/UX_Recommendations.html>
- PAV ontology paper: <https://jbiomedsem.biomedcentral.com/articles/10.1186/2041-1480-4-37>
- SEPIO: <https://obofoundry.org/ontology/sepio.html>
- ECO: <https://obofoundry.org/ontology/eco.html>
- CiTO: <https://www.sparontologies.net/ontologies/cito>
- Cochrane Handbook, chapter 5: <https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-05>
- RO-Crate 1.2 profiles: <https://www.researchobject.org/ro-crate/specification/1.2/profiles.html>
- CQRS pattern: <https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs>
- Redundancy-aware retrieval benchmark: <https://aclanthology.org/2026.acl-long.923/>
