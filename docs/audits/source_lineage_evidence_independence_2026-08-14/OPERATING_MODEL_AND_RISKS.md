State: Advisory appendix to `../SOURCE_LINEAGE_EVIDENCE_INDEPENDENCE_FAMILY_AWARE_RETRIEVAL_2026-08-14.md`. Non-normative; the parent audit and current owner documents govern interpretation.
Doc role: Reference (audit appendix)

# Operating model, scaling, risks, and invariant kernel

## 7. Human-facing projection

The default result should be the source family, not a flat derivative list:

```text
Agentic development at Company X
Research report · published 2026-07-12

1 source lineage · 7 derivatives · 2 reviewed
Evidence lineage: one known lineage
Selected view: human-corrected summary
Source fidelity reviewed; factual accuracy not separately reviewed

[Open selected view] [Open source] [Show derivatives]
[Evidence] [Lineage] [Versions] [Technical details]
```

Every visible object should answer without opening raw metadata:

- what is this;
- who or what created it;
- which source it derives from;
- which transformation occurred;
- what was reviewed and what was not;
- why this representation was selected.

Use progressive disclosure:

1. immediate type/origin/review/source/freshness signal;
2. compact source/evidence-lineage summary;
3. full activity/version/review/promotion history;
4. technical hashes, models, prompts/policies, failures, retries, and receipts.

A result explanation should say, for example:

```text
Shown because:
- a transcript segment matched the query;
- the reviewed summary is the best orientation view in this source lineage;
- five related derivatives were collapsed;
- this result contributes one evidence lineage to the current set.
```

Attention should be reserved for states requiring judgment: new or uncertain independent evidence, contradiction with accepted knowledge, changed/retracted sources, active decisions relying on insufficiently reviewed material, broken lineage, explicit review requests, or stale/incomplete indexes that materially threaten retrieval.

---

## 8. Physical scaling without preselecting topology

Preserve four logical roles even when they initially share one tree:

1. **writing and accepted knowledge surface** — human-readable, actively editable, low navigation noise;
2. **source and derivative retention surface** — originals, snapshots, transcripts, extractions, machine intermediates, and lineage history;
3. **index and read projections** — chunks, embeddings, lexical indexes, ranking features, graph projections, thumbnails, and caches;
4. **identity/location resolver projection** — stable IDs, current location, schema version, lineage group, and availability posture.

The resolver and indexes remain projections over source-owned identity and provenance. Deleting them must not lose source evidence, accepted knowledge, human annotations, review assessments, authority transitions, decisions, or migration-critical provenance. Rebuildability means no semantic loss, not zero recovery cost.

Physical separation should be triggered by measured budgets, not a universal file count or vault ideology:

| Dimension | Measure |
| --- | --- |
| Interactive performance | p50/p95 open, navigation, query, and metadata-update latency |
| Index freshness | change-to-searchable delay |
| Ingestion capacity | arrival rate, backlog age, retry volume |
| Rebuild | full and incremental rebuild duration and resource use |
| Recovery | RTO/RPO, backup and restore duration |
| Sync | transfer volume, lag, conflict rate, convergence time |
| Storage amplification | retained bytes compared with original source bytes |
| Failure domain | maximum corpus portion affected by corruption or rebuild |
| Security/retention | distinct access, export, deletion, or retention obligations |
| Working set | active versus cold access and mutation frequency |
| Device footprint | realistic local corpus for laptop, tablet, or phone |

Strong split reasons are real differences in security, ownership, lifecycle, sync, failure domain, recovery, or measured workload. Topic categories, file extensions, or an arbitrary age threshold are insufficient on their own.

---

## 9. SBS reconciliation and allocation

This table is a reconciliation against the current SBS, not a silent reassignment
of responsibility. The SBS and the cited owner contracts remain authoritative;
the audit only states where a later, owner-approved contract delta would fit.

| Boundary | Proposed responsibility if promoted | Posture against current SBS |
| --- | --- |
| SIP | define source-lineage and evidence-lineage semantics; own typed relations/assessments and provenance continuity | **Extends.** A general lineage assessment extends the existing provenance/typed-relation responsibility and requires owner approval. |
| EBF / Knowledge Acquisition | produce source-specific identity, content identity, acquisition evidence, and adapter provenance | **Conforms.** Uses existing acquisition and provenance producers; creates no new acquisition owner. |
| HKA | preserve durable source bundles, human-confirmed semantic relations, scoped reviews where human meaning would otherwise be lost, and accepted syntheses | **Extends.** A scoped-review record is a proposed contract extension to the durable-knowledge role. |
| DRI | build rebuildable source-lineage groups, collapse metadata, resolver, and index projections | **Extends.** Family collapse is a proposed new projection behavior. |
| RCA | retrieve finely; group, collapse, select representatives, diversify, and assemble context without changing authority | **Extends.** Family-aware ranking/presentation is a proposed retrieval-contract delta, not shipped behavior. |
| GOV | govern review assessments, confirmation of epistemically material relations, admissibility, and authority transitions | **Conforms.** Reuses governed confirmation and authority transitions; no new authority path is proposed. |
| HIX | render source-family cards, evidence posture, uncertainty, and “why shown” explanations | **Extends.** The family card is a proposed HIX projection, pending an approved interface contract. |
| WSP | resolve active vault/context bindings; does not grant authority | **Conforms.** Consumes the existing binding seam only. |
| PDM | store and migrate objects without redefining semantic identity | **Conforms.** Storage remains subordinate to semantic identity and does not gain an evidence role. |
| SFC | preserve lineage and identity across replicas/federation | **Conforms.** Retains replica/convergence responsibility; no federation model is selected. |
| OEF | measure duplicate rate, lineage quality, diversity, latency, freshness, rebuild, and recovery | **Extends.** The proposed measures extend the existing observability role and remain pending acceptance. |
| CES | steward the contract delta and prevent parallel terminology or ownership drift | **Conforms.** Architecture stewardship only; it does not create a runtime subsystem. |

This is a cross-boundary capability, not a proposal for another runtime subsystem.

---

## 10. Risks and controls

| Risk | Failure | Control |
| --- | --- | --- |
| Apparent evidence multiplication | Derivatives or retellings appear as independent support. | Distinct source/evidence-lineage grouping and conservative `unknown`. |
| False merge | Independent sources are collapsed. | Confidence, evidence, human override, reversible relations, and evaluation corpus. |
| Review laundering | `reviewed` is interpreted as factual validation or acceptance. | Explicit scope, method, target version, outcome, and separate authority transition. |
| Graph explosion | Every chunk/run becomes permanent semantic graph state. | Provenance profiles, bounded granularity, rebuildable projections. |
| Claim explosion | Every sentence becomes a durable claim. | Selective claim/evidence modeling. |
| Artifact noise | Every generated derivative becomes a top-level Obsidian note. | Source-family projection and materialization policy. |
| Index drift | Read projection diverges from canonical objects. | Version markers, freshness health, invalidation, and rebuild tests. |
| Path lock-in | File path becomes identity. | Stable object identity and resolver projection. |
| Model non-reproducibility | Regeneration changes a decision-relevant artifact. | Preserve used output, inputs, versions, receipts, and decision dependency. |
| Topology overreach | Vault split substitutes for missing semantics. | Logical contracts and measurement before physical partitioning. |

---

## 11. Gap ledger

`Allowed disposition` is deliberately separate from the proposed action: this is
an advisory audit with no accepted `PromotionIntent`, so no finding is accepted
for backlog creation here.

| ID | Finding | Evidence anchors or open status | Allowed disposition | Proposed action |
| --- | --- | --- | --- | --- |
| F1 | Existing ontology and semantic dimensions cover the core objects and authority distinctions. | `docs/architecture/functional-ontology.md:62-68`, `docs/architecture/functional-ontology.md:103-110` | **Deferred.** No accepted promotion. | **Reuse.** No parallel ontology or scalar trust model. |
| F2 | Acquisition lineage strongly models one source item and its derivatives. | `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md:120-127`, `docs/YOUTUBE_SOURCE_NOTE_V2/README.md:85-86` | **Deferred.** No accepted promotion. | **Generalize selectively.** Derive source-lineage projection from existing identities and provenance. |
| F3 | Whether a general evidence-lineage/independence concept is needed remains open. | **Open.** No anchored owner contract in this reviewed baseline establishes that general concept. | **Requires owner decision.** | First-class object versus typed relation/assessment remains open. |
| F4 | Retrieval is candidate-centric and does not specify family collapse or evidence-lineage diversification. | `docs/architecture/retrieval-contract.md:17-95` | **Deferred.** No accepted promotion. | **Contract delta.** Preserve eligibility-before-ranking and exact citations. |
| F5 | Whether cross-cutting review posture needs a general scoped-assessment envelope remains open. | **Open.** The reviewed retrieval and artifact/projection contracts do not establish that envelope. | **Requires owner decision.** | **Bounded assessment contract.** Do not replace authority state. |
| F6 | Cognitive-load rules fit the required source-family UI, but the specific projection is not defined. | `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md:64-76`, `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md:158-163` | **Deferred.** No accepted promotion. | **Projection delta.** No new UI authority. |
| F7 | Multi-vault topology and identity rules are strong, but no topology should be selected here. | `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md:113-120` | **Deferred.** No accepted promotion. | **Defer physical choice** until logical contracts and measurements exist. |
| F8 | Quantitative NFR and scalability targets for this proposed capability remain open. | **Open.** This audit did not establish a baseline NFR owner or measurement corpus. | **Requires owner decision.** | Add corpus/rebuild/sync/recovery budgets before partitioning. |
| F9 | #4107/#4112/#4113/#4119 already cover source bundles, anchors, claims, and quality evaluation. | `docs/YOUTUBE_SOURCE_NOTE_V2/PARENT_FEATURE_ISSUE.md:1-5`, `docs/YOUTUBE_SOURCE_NOTE_V2/PARENT_FEATURE_ISSUE.md:64-71` | **Deferred.** Reconcile before any accepted promotion. | **Reconcile.** Do not create a competing YouTube capability. |
| F10 | #2143 remains the multi-vault runtime validation hub. | `docs/MULTI_VAULT_RUNTIME/README.md:11-12`, `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md:49-59` | **Deferred.** Reconcile before any accepted promotion. | **Reconcile.** Consume active bindings; do not replace the runtime. |

---

## 12. Invariant kernel for a promoted design

The following is a proposed enforcement classification, not a statement that the
listed enforcement exists today. `MUST` fails loud at runtime; `GATE` is a
CI/PR-blocking test; `DOCTOR` is read-only reconciliation or measurement. The minimal proposed kernel is
SLEI-01, SLEI-03 through SLEI-11. SLEI-02 is an explanatory corollary of
SLEI-01/SLEI-03, while SLEI-12 is a topology-health rule and therefore not in the
minimal kernel.

| ID | Proposed invariant | Class | Current enforcement posture | Kernel |
| --- | --- | --- | --- | --- |
| SLEI-01 | Derivatives never increase the counted number of independent evidence lineages. | MUST | **New.** Existing projection-not-evidence rules support it, but no lineage counter exists. | yes |
| SLEI-02 | Different locators or publications never imply independence. | MUST | **New.** The current source/provenance model does not infer independence. | no — corollary |
| SLEI-03 | `unknown` independence remains explicit and conservative. | MUST | **New.** Requires an approved assessment vocabulary. | yes |
| SLEI-04 | Exact source-fragment citation survives grouping and representative selection. | MUST | **Exists — keep.** Retrieval/segment contracts preserve citation; grouping preservation is new. | yes |
| SLEI-05 | Scope/policy eligibility precedes ranking and grouping. | MUST | **Exists — keep.** Retrieval admissibility exists; family grouping must preserve it at runtime. | yes |
| SLEI-06 | Machine-inferred lineage is non-authoritative until governed confirmation. | MUST | **New.** Existing authority transitions inform the rule; lineage confirmation needs runtime enforcement. | yes |
| SLEI-07 | Review scope never implies broader review or authority. | MUST | **New.** Requires the proposed scoped-assessment envelope. | yes |
| SLEI-08 | Source lineage, evidence lineage, source role, authority state, and evidence role remain distinct. | MUST | **Exists — keep.** Current semantic dimensions separate the latter three; the two lineage concepts are new. | yes |
| SLEI-09 | Index and resolver loss causes no semantic or authority loss. | GATE | **Exists — keep.** Rebuildable-projection and topology rules exist; test source-lineage recovery. | yes |
| SLEI-10 | Artifact and lineage identity survive path and vault movement. | MUST | **Exists — keep.** Vault identity survives relocation; lineage identity is new. | yes |
| SLEI-11 | Human-authored or decision-relevant changes remain attributable and receipted. | MUST | **Exists — keep.** Existing governance/receipt posture must fail loud for promoted lineage changes. | yes |
| SLEI-12 | Physical partitioning is reversible and justified by measured boundaries. | DOCTOR | **New.** Report the measurement posture before a topology decision. | no — health rule |

---
