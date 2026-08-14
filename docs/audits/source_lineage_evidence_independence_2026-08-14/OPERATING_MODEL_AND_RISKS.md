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

## 9. SBS allocation

| Boundary | Responsibility |
| --- | --- |
| SIP | define source-lineage and evidence-lineage semantics; own typed relations/assessments and provenance continuity |
| EBF / Knowledge Acquisition | produce source-specific identity, content identity, acquisition evidence, and adapter provenance |
| HKA | preserve durable source bundles, human-confirmed semantic relations, scoped reviews where human meaning would otherwise be lost, and accepted syntheses |
| DRI | build rebuildable source-lineage groups, collapse metadata, resolver, and index projections |
| RCA | retrieve finely; group, collapse, select representatives, diversify, and assemble context without changing authority |
| GOV | govern review assessments, confirmation of epistemically material relations, admissibility, and authority transitions |
| HIX | render source-family cards, evidence posture, uncertainty, and “why shown” explanations |
| WSP | resolve active vault/context bindings; does not grant authority |
| PDM | store and migrate objects without redefining semantic identity |
| SFC | preserve lineage and identity across replicas/federation |
| OEF | measure duplicate rate, lineage quality, diversity, latency, freshness, rebuild, and recovery |
| CES | steward the contract delta and prevent parallel terminology or ownership drift |

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

| ID | Finding | Disposition |
| --- | --- | --- |
| F1 | Existing ontology and semantic dimensions cover the core objects and authority distinctions. | **Reuse.** No parallel ontology or scalar trust model. |
| F2 | Acquisition lineage strongly models one source item and its derivatives. | **Generalize selectively.** Derive source-lineage projection from existing identities and provenance. |
| F3 | No general evidence-lineage/independence concept was identified. | **Owner decision.** First-class object versus typed relation/assessment remains open. |
| F4 | Retrieval is candidate-centric and does not specify family collapse or evidence-lineage diversification. | **Contract delta.** Preserve eligibility-before-ranking and exact citations. |
| F5 | Review posture does not generally state review scope in the reviewed cross-cutting contracts. | **Bounded assessment contract.** Do not replace authority state. |
| F6 | Cognitive-load rules fit the required source-family UI, but the specific projection is not defined. | **Projection delta.** No new UI authority. |
| F7 | Multi-vault topology and identity rules are strong, but no topology should be selected here. | **Defer physical choice** until logical contracts and measurements exist. |
| F8 | Quantitative NFR and scalability targets are absent/open. | **Owner decision.** Add corpus/rebuild/sync/recovery budgets before partitioning. |
| F9 | #4107/#4112/#4113/#4119 overlap source bundles, anchors, claims, and quality evaluation. | **Reconcile.** Do not create a competing YouTube capability. |
| F10 | #2143 owns multi-vault runtime selection. | **Reconcile.** Consume active bindings; do not replace the runtime. |

---

## 12. Invariant kernel for a promoted design

A future promoted design should preserve at least these invariants:

- **SLEI-01:** derivatives never increase the counted number of independent evidence lineages;
- **SLEI-02:** different locators or publications never imply independence;
- **SLEI-03:** `unknown` independence remains explicit and conservative;
- **SLEI-04:** exact source-fragment citation survives grouping and representative selection;
- **SLEI-05:** scope/policy eligibility precedes ranking and grouping;
- **SLEI-06:** machine-inferred lineage is non-authoritative until governed confirmation;
- **SLEI-07:** review scope never implies broader review or authority;
- **SLEI-08:** source lineage, evidence lineage, source role, authority state, and evidence role remain distinct;
- **SLEI-09:** index and resolver loss causes no semantic or authority loss;
- **SLEI-10:** artifact and lineage identity survive path and vault movement;
- **SLEI-11:** human-authored or decision-relevant changes remain attributable and receipted;
- **SLEI-12:** physical partitioning is reversible and justified by measured boundaries.

---

