State: Advisory audit snapshot (2026-07-14). Subordinate to `docs/DOCS_INDEX.md`, ADR-0057, and CKM owner contracts. No implementation or backlog mutation is enacted by this document.
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis; file:line anchors reflect `main` at merge commit `9ad54cfe163bb661efba8c6a3c836a6b816c3f10`. Where this audit and an owner document disagree, the owner document wins.

# CKM Measurement and Access — Architecture Research

Date: 2026-07-14

Scope: (1) make the complete Capability Knowledge Model safely accessible and measurable; (2) establish an observation model that can justify later functionality from system evidence.

System classification: Builder System / CES boundary. CKM remains derived BuilderOps analysis; Product/Runtime sources are read-only.

## 1. Research questions

- **RQ1 — Access:** What stable read contract lets agents, tools, and later interfaces inspect the whole CKM without parsing HTML/Markdown or treating SQLite as a public API?
- **RQ2 — Measurement:** Which measurements are valid now, and which need additional history or provenance before longitudinal claims are honest?
- **RQ3 — Observation:** What is the minimum observation loop needed before adding filters, comparisons, timelines, drift, prediction, or closed-loop actions?
- **RQ4 — Correctness:** Which invariants prevent measurement from becoming authority, hiding freshness, or rewarding proxy manipulation?
- **RQ5 — Backlog:** Which work is genuinely new versus already delivered, deferred, or owned by another capability?

## 2. Evidence baseline

The current CKM offers concrete in-process reads through `CkmStore`, fixed Markdown projections, one-capability `ckm show`, and the static HTML overview (`app/builderops/ckm/store.py:256-273,311-321,692-705,836-874,1026-1055`; `app/builderops/cli.py:552-601`). CKM-09 deliberately excludes HTTP and conversational query from MVP (`docs/CAPABILITY_KNOWLEDGE_MODEL/CKM_PROJECTIONS_AND_QUERY.md:59-62`). The broader SRS nevertheless names lookup, subtree, explained maturity, gaps, drift, evolution, and grounded query as the eventual read surface (`docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md:273-279`).

The store already preserves append-only assessment snapshots with scores, frozen citations, formula identifiers, candidate shares, watermarks, `valid_from`, and `asserted_at` (`app/builderops/ckm/schema.py:116-147`; `app/builderops/ckm/assess.py:385-445`). It does not preserve equivalent history for capabilities, artifacts, findings, or watermarks (`app/builderops/ckm/schema.py:30-57,149-170`). Edge history exists but is not exposed as an enumerable query (`app/builderops/ckm/store.py:591-620`).

ADR-0057 is binding: all outputs are derived, cited, watermarked projections; CKM never gains action authority (`docs/adr/ADR-0057-capability-knowledge-model-kvasir.md:23-25,49-51`).

## 3. Ranked structural weaknesses

Ranked by systemic impact (blast radius × silence of failure).

### W1 — There is no stable, structured snapshot/query contract

All external surfaces are Markdown or HTML; commands have no JSON form (`app/builderops/cli.py:552-601`). Complete machine access therefore requires importing the concrete SQLite store, querying its schema, or parsing human projections. Store calls expose rows without a shared snapshot envelope or transaction-scoped watermark (`app/builderops/ckm/store.py:50-79,360-363`). This makes implementation detail the accidental API and allows different reads to describe different freshness states.

### W2 — The implemented time model cannot support the requested evolution picture

Assessments are append-only and recover their selected evidence, formula, and watermark snapshot (`app/builderops/ckm/store.py:753-861`; `tests/builderops/ckm/test_assessment_engine.py:316-364`). But `valid_from` and `asserted_at` default to the same instant and there is no validity interval or two-axis as-of query (`app/builderops/ckm/store.py:753-789`). Capabilities and artifacts are current-row upserts, findings are current disposable projections, and watermarks overwrite in place (`app/builderops/ckm/schema.py:30-57,149-170`). The docs' “bitemporal” claim is therefore stronger than the general queryable semantics implemented (`docs/CAPABILITY_KNOWLEDGE_MODEL/MATURITY_ASSESSMENT_ENGINE.md:31`).

### W3 — Today’s scores are useful diagnostics but unsafe optimization targets

The seven formulas and weighted-min aggregate are explicit and reproducible (`app/builderops/ckm/assess.py:24-40,132-339`; `tests/builderops/ckm/test_assessment_engine.py:133-152`). Several dimensions remain proxies: any non-placeholder `State:` document can improve documentation quality (`app/builderops/ckm/assess.py:183-206`); one source plus one distinct surface kind yields full integration (`:209-237`); candidate evidence contributes fully to scores while candidate share is an unweighted count (`:418-445`); and architectural “recent churn” has no time window (`:257-278`). ADR-0057 already warns that the scalar must remain a labeled convenience (`docs/adr/ADR-0057-capability-knowledge-model-kvasir.md:49-51`).

### W4 — Complete reads scale as full scans and repeated N+1 queries

List methods use unbounded `fetchall()` without filters, cursors, or pagination (`app/builderops/ckm/store.py:270-273,318-321,692-705,845-857,1039-1055`). Latest assessment loads all history for a capability (`:845-861`). Projections and HTML repeat per-capability edge, finding, assessment, and freshness reads (`app/builderops/ckm/projections.py:184-195,288-300`; `app/builderops/ckm/overview_html.py:204-214,303-324`). Every store call opens a new connection (`app/builderops/ckm/store.py:73-79`), preventing one consistent read transaction.

### W5 — Observation provenance is incomplete for honest trend comparison

Current inventory, assessment, confidence, staleness, and gap counts are derivable from stored rows (`app/builderops/ckm/schema.py:30-170`; `app/builderops/ckm/gaps.py:191-420`). But findings do not persist detector/formula/threshold/watermark context, and disappeared findings leave no history (`app/builderops/ckm/schema.py:149-159`). Watermark-only evidence changes intentionally do not append assessments (`tests/builderops/ckm/test_assessment_engine.py:221-244`). A chart can therefore show assertion history, but cannot honestly claim a complete continuous system history.

## 4. Research-question resolutions

### RQ1 — Access

The minimum safe contract is a read-only, versioned CKM snapshot envelope—not an HTTP server and not HTML parsing. It must identify itself as a projection and carry `schema_version`, `generated_at`, one immutable watermark set, query parameters, stable capability IDs, provenance, and pagination/cursor metadata. Initial primitives should cover snapshot summary, capability lookup/subtree, evidence, latest/explained assessment, assessment assertions, findings, and unlinked artifacts. Transport can begin as CLI JSON; HTTP is an adapter over the same contract only after a real multi-process consumer exists.

### RQ2 — Measurement

Safe now: inventory counts, current coverage/composition, seven-dimensional latest assessments, formula IDs, candidate share, low-confidence/staleness counts, current findings, unlinked backlog, and assertion-to-assertion assessment changes. Unsafe now: continuous maturity trends, as-of graph reconstruction, time-to-maturity prediction, historical gap rates, and comparisons across detector/formula versions. Those require additional history/provenance contracts before visualization.

### RQ3 — Observation

The minimum loop is: capture a versioned snapshot → compute named measures from that snapshot → retain the measure definition and source watermark → compare only compatible definitions → publish an observation receipt → use observations to propose, never automatically enact, feature/backlog changes. A 4–6 week observation window or a minimum number of materially distinct snapshots is more informative than adding interactive features immediately; event-based snapshots should supplement, not be replaced by, a calendar cadence.

### RQ4 — Correctness

The measurement plane must preserve non-authority, stable identity, snapshot consistency, freshness visibility, candidate/confirmed separation, formula/detector version comparability, missing-is-not-zero, and promotion-only action. Aggregate rankings must never be the sole selection or gate signal.

### RQ5 — Backlog

CKM-01..11 are delivered; #3138 remains the validation hub. No open issue owns structured snapshot/query or longitudinal observation. Drift is a separate deferred requirement gated by the Correctness Kernel registry (`docs/adr/ADR-0057-capability-knowledge-model-kvasir.md:27-31,66`); automatic gap→issue/drift→ADR action requires governed promotion and potentially an SBS/ADR decision (`docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md:291-296,385-388`). Predictive maturity and cross-repo federation remain premature and distinct.

## 5. Invariant set

Minimal kernel:

- **I-MA1 — Projection-only access (MUST).** Every query/export response self-identifies as derived, includes provenance/freshness, and cannot mutate CKM, GitHub, repo, or Product/Runtime state. Existing partial enforcement: INV-CKM-2 and projection tests; extend to structured responses.
- **I-MA2 — Snapshot consistency (MUST).** Every multi-object response is produced inside one read transaction against one watermark set. New.
- **I-MA3 — Stable identity (GATE).** Capability references use immutable IDs; mutable name/slug is display/lookup metadata only. Partial: store IDs exist, CLI accepts slug only (`app/builderops/ckm/projections.py:96-125`).
- **I-MA4 — Missing is not zero (GATE).** Unavailable, unassessed, unsupported, and measured-zero remain distinct in query and metric schemas. Partial: Direction A HTML enforces the distinction.
- **I-MA5 — Comparable measures (MUST).** Every persisted observation names metric definition/version, formula/detector versions, source snapshot, thresholds, and generated time. New.
- **I-MA6 — Candidate separation (GATE).** Candidate evidence is exposed separately and cannot silently become confirmed or be hidden by an aggregate. Existing—keep.
- **I-MA7 — No scalar authority (GATE).** Aggregate maturity cannot be the sole ranking, gate, or automated action input; vector, citations, freshness, and confidence remain available at the decision point. Partial—documented, not generally enforced.
- **I-MA8 — Promotion-only action (MUST).** Observations may produce a proposal/PromotionIntent; issues, docs, ADRs, and runtime changes follow their normal authority paths. Existing BuilderOps/ADR boundary—keep.

Defense in depth:

- **I-MA9 — Bounded reads (DOCTOR/GATE).** Query surfaces use filters, limits/cursors, indexed predicates, and expose truncation.
- **I-MA10 — Historical honesty (GATE).** Evolution output labels assertion series versus valid-time/system-state history and refuses unsupported time semantics.

## 6. SBS reconciliation

All claims **conform to** the current SBS operating model: CKM is Builder System analysis, not a Product/Runtime SBS subsystem. A read/measurement layer extends the BuilderOps CKM physical surface without reshaping the Product SBS. OEF may consume observations and evaluate trends, but it does not gain policy or control authority (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:103,1321,1351`). Any automated action, federation topology, or Product contract write would **propose reshaping** and must route through CES/ADR/owner decision; this audit enacts none.

## 7. Dependency-ordered advisory backlog

This is a feature-breakdown handoff, not filed work.

1. **Q1 — Versioned snapshot/query contract.** Define the envelope, typed resources, stable IDs, freshness/provenance, filters/cursors, error semantics, and CLI JSON transport. Verify kernel: schema fixtures reject authority ambiguity, missing freshness, unbounded reads, and missing/zero collapse.
2. **Q2 — Consistent store read model.** Add one read port and transaction-scoped snapshot implementation; remove N+1 paths for the query contract. Depends on Q1. Verify kernel: concurrent watermark advance cannot create a mixed response; bounded query plans are asserted.
3. **M1 — Metric registry and observation receipt.** Name current safe metrics, definitions, versions, compatibility rules, source snapshots, thresholds, and Goodhart warnings. Depends on Q1. Verify kernel: same snapshot+definition is reproducible; incompatible versions refuse direct comparison.
4. **M2 — Historical evidence needed for honest evolution.** Decide and implement only the minimum history required by accepted observation questions (watermark runs, finding snapshots, formula/detector context; full graph bitemporality only if justified). Depends on M1. Verify kernel: supported historical claims reconstruct; unsupported claims fail explicitly.
5. **O1 — Observation projection and review cadence.** Produce comparison reports across compatible snapshots, attach receipts to #3138 or its successor validation hub, and collect which questions users actually ask. Depends on M1; M2 only for historical claims selected in scope.
6. **O2 — Feature-selection gate.** Convert observed repeated needs into bounded proposals for filters, comparison, timeline, drift, or other features. Depends on an accepted observation window. Verify kernel: every proposed feature cites observation receipts and retains authority boundaries.

### Reconciliation notes

- Extend #3138 as the validation/evidence hub; do not create a second CKM parent until feature-breakdown establishes whether access+measurement is one successor capability or bounded children under #3138.
- Do not reopen delivered CKM-09: it truthfully delivered the MVP CLI/Markdown scope. Q1 is post-MVP structured access.
- Keep drift separate until the Correctness Kernel integration contract is explicitly reconciled.
- #3264/PR #3295 already consume CKM projections in reevaluation and preserve promotion boundaries; structured access may later replace parsing but does not duplicate reevaluation governance.
- Predictive maturity, automatic writeback, and federation remain out of scope until observation evidence justifies them.

## 8. Independent-model inquiry charter

A Sol/Fable architecture inquiry is justified because Q1/M1/M2 jointly set durable public semantics and carry Goodhart and temporal-model risk. Ask the models to challenge—not implement—the minimal kernel, especially whether a snapshot-first CLI contract is sufficient, which history is truly necessary, and how to prevent metrics from becoming targets. Inquiry output remains advisory and must reconcile back into this audit before feature-breakdown.
