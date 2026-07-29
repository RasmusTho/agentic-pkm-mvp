State: Current-state delivered specification for the post-MVP CKM Measurement & Access capability. All six children under parent #3775 are terminally delivered, and the supported BuilderOps-only Q1, Q2, M1, and O1 capabilities have passed their acceptance ledger. Parent #3775 records the independent final verification/closure audit; this owner-doc promotion neither performs nor claims that lifecycle mutation. M2 and O2 remain unfiled and unauthorized, and #3972 remains a separate owner-value gate rather than a dependency. CKM remains non-authoritative projection/evidence and creates no Product/Runtime truth or decision authority. Accepted predecessor CKM MVP validation hub: closed GitHub issue #3138.
Doc role: Specification directory (capability breakdown)
Authority: Owns the accepted post-MVP access, measurement, observation, dependency, and acceptance contract. Subordinate to ADR-0057 and the Builder System authority boundary.
Owner: BuilderOps governance / Capability Knowledge Model
Temporal class: operational
Review cadence: event-driven
Source of truth: this directory for implementation task shape; ADR-0057 for CKM existence and authority posture; canonical fitness registration remains in `docs/architecture/SBS_FITNESS_RULES.md`.
Last reviewed: 2026-07-29

# CKM Measurement & Access

This specification defines the delivered successor capability that makes the Capability Knowledge Model safely consumable by machines and measurable without turning CKM projections into authority. It follows the accepted CKM MVP (#3138), the architecture audit `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`, and BuilderOps inquiries `inq_20260715T062832Z_e73546a2` and `inq_20260715T090347Z_61c6d5e4` (both `consensus`). The later inquiry governs where the two inquiry handoffs differ, and the owner decisions recorded below resolve its five policy gates.

Work classification: **Builder System / CES boundary**. CKM remains projection-only BuilderOps analysis. OEF may consume descriptive observations but gains no policy or control authority. Product/Runtime artifacts and GitHub remain read-only sources. Federation remains SFC/CES-owned, and Correctness Kernel drift remains a separate declared-state contract.

## Capability boundary

The accepted successor capability provides:

- a transport-neutral, versioned CKM result/error envelope and resource DTOs;
- rebuild-stable, non-reused public resource identity plus explicit rename/delete/split/merge alias or tombstone semantics;
- a CKM epoch/state revision advanced atomically with every CKM mutation;
- immutable snapshot manifests/digests binding state revision, schemas, taxonomy, watermarks, provenance, effective audience, access-policy version, redaction profile, and completeness accounting;
- one explicit read-only SQLite transaction for each snapshot query;
- bounded exact-ID lookup and a bounded complete snapshot/export that refuses when it cannot be complete;
- CLI JSON as the first adapter over the same query service future HTTP/UI adapters would use;
- richer bounded filters and batch query plans after the correctness baseline;
- versioned descriptive metric definitions, a bounded human-advisory aggregate, and fully bound immutable observations;
- privacy-safe outer-adapter observation of already-returned query/question and unsupported-request outcomes;
- comparison only between semantically compatible immutable observations;
- one-year sampled retention, storage visibility, explicit pruning, correction, deletion, and operator-controlled export behavior under the accepted owner policy.

The capability does **not** provide general bitemporality, arbitrary as-of reconstruction, retroactive provenance, machine-produced rankings, gates, scalar-only ordering, agent scoring, automated prioritization, prediction, automation, drift detection, or federation. The single operator may use a labeled aggregate as one small advisory input, never as the sole basis for a decision.

## Accepted architecture decisions

1. Q1 is one acceptance gate: contract plus a minimal working single-transaction snapshot. Q1a may land schemas/state identity first, but Q1 is not delivered until Q1b proves the public contract on the production read path.
2. Public identity survives rebuild and display-name/slug changes and is never reused. Rename keeps the identifier; deletion leaves a content-free tombstone; split creates new identifiers and tombstones the original with successor links; merge creates a new identifier and tombstones the inputs with successor aliases. Raw row IDs are never public identifiers.
3. Snapshot identity binds epoch, transactionally advanced state revision, resource/envelope schema versions, taxonomy digest, exact watermarks, and the canonical read-set digest.
4. Query execution is read-only and side-effect free: no directory creation, schema initialization, migration, receipt emission, event callback, or mutation. O1a observation, when present, is a separate outer adapter invoked only after the immutable query result/refusal returns.
5. V1 prefers a bounded complete snapshot/export. If the configured bound cannot contain the complete declared scope, the operation returns a typed refusal and no measurement-eligible partial snapshot. Pagination is deferred until size evidence justifies it and retained immutable snapshots plus an accepted retention policy can make continuation honest.
6. Missing, unassessed, unsupported, and measured-zero are tagged distinct states. Candidate and confirmed material remain separate. Completeness is always explicit.
7. DTOs, errors, query services, and envelopes are transport-neutral. Click parses/serializes only.
8. General valid-time/system-state history is unsupported. Assessment assertion history remains supported; unsupported historical requests fail explicitly. No provenance is fabricated retroactively.
9. Metrics are descriptive and snapshot-bound. Every definition exposes intended/prohibited uses, Goodhart warnings, and `not_for_gating: true`. V1 may expose aggregate maturity as an explicitly `human_advisory_only` convenience only alongside its vector, citations, freshness, confidence, and composition. It cannot be the sole input to a decision or drive machine ranking, gating, prioritization, agent evaluation, or action. TCD applies to metric depth: add analysis only when its expected decision value exceeds development, review, and maintenance cost.
10. Comparison refuses any semantics-bearing mismatch, including identity and access-policy versions. Supported longitudinal questions are limited to change in evidence coverage/composition, source freshness, citation/confidence coverage, and candidate/finding composition across retained compatible samples. Arbitrary point-in-time reconstruction is unsupported; cadence and minimum distinct-snapshot thresholds remain evidence-driven rather than fixed in advance.
11. V1 is a trusted single-operator local environment. Results declare `effective_audience=single_operator_local`, a versioned local access policy, and `redaction_profile=none`; v1 adds no accounts, roles, authentication, multi-user authorization, or field redaction. A multi-user, remote, or externally redistributed surface requires a new policy decision before delivery.
12. Explicitly retained snapshots, observations, watermark runs, and finding evaluations use a 365-day default retention period. Storage count and byte usage are visible. Payloads may expire after 365 days or be pruned earlier only by an explicit operator action; pruning/correction/deletion preserves a non-content marker and makes unavailable-source comparisons refuse rather than fabricate history.

## Accepted pre-implementation owner decisions

The owner accepted all five decisions on 2026-07-15. No child Issue may be Ready or implementation-active until the affected task contracts and Issue bodies are reconciled to these decisions and strict readiness validation passes.

1. **Snapshot access and disclosure — accepted.** The deployment is one trusted local operator. V1 requires no user-account, role, authentication, authorization, or redaction machinery. Complete exports may be retained and moved at the operator's discretion inside that one-person posture. Any multi-user, remote, service-hosted, or third-party redistribution use reopens this gate.
2. **Metric use — accepted.** Metrics and aggregate maturity may advise the owner's development decisions as a small contextual input. They may not be the sole decision basis or drive automatic ranking, gating, prioritization, agent scoring, or action. Every aggregate travels with its components, evidence, freshness, confidence, limitations, and Goodhart warning. Metric depth and new KPI work are governed by TCD: do not build or deepen a measure when its expected decision benefit does not justify development and interpretation cost.
3. **Longitudinal scope — accepted.** V1 may compare retained compatible samples only to answer whether evidence coverage/composition, source freshness, citation/confidence coverage, or candidate/finding composition changed. It refuses arbitrary as-of reconstruction, continuous history, causal claims, and unsupported trend semantics. M2 remains unfiled until the smallest implementation for these questions is costed and source-backed; no general history substrate is implied.
4. **Identity lifecycle — accepted.** Identifiers are never reused. Rename preserves identity; deletion produces a content-free tombstone; split creates new identifiers and records successor links from the tombstoned original; merge creates a new identifier and records successor aliases from the tombstoned inputs. Historical observations retain the identities that were true when captured.
5. **Retention and correction — accepted.** Explicitly captured snapshots, observation receipts, watermark runs, and finding-evaluation history default to 365-day retention. Raw exports are not retained automatically merely because they were returned. Storage count and bytes must be inspectable; expiry after 365 days may be automatic, while earlier pruning requires an explicit operator command with preview. Corrections append a superseding record. Required deletion or pruning removes payload content, leaves a non-content marker, and causes dependent replay/comparison to refuse honestly.

## Cross-task invariants / interaction safety

These invariants are registered in `docs/architecture/SBS_FITNESS_RULES.md`; this section applies them to the task seams.

- **I-MA1 — Projection-only governed access.** Every result declares non-authoritative projection status, provenance, freshness, `effective_audience=single_operator_local`, a versioned local access policy, and `redaction_profile=none`. V1 adds no multi-user security machinery. Reads cannot mutate CKM, GitHub, repo, BuilderOps authority, or Product/Runtime state; any later multi-user or remote surface must define a new policy first.
- **I-MA2 — Snapshot consistency.** Every multi-object result comes from one read transaction and binds all CKM state via epoch/revision, versions, taxonomy, watermarks, and digest. No cross-snapshot mixing.
- **I-MA3 — Rebuild-stable lifecycle identity.** Public identity survives rebuild and mutable display metadata, is never reused, and follows accepted rename/delete/split/merge alias or tombstone semantics; row IDs stay private.
- **I-MA4 — Tagged value state.** `measured`, `missing`, `unassessed`, and `unsupported` are distinct; measured zero is not absence.
- **I-MA5 — Comparable observations.** Observation and comparison bind every semantics-bearing definition/version/config input and refuse mismatch.
- **I-MA6 — Candidate separation.** Candidate and confirmed evidence/resources remain distinct in structured results and observations.
- **I-MA7 — No scalar authority.** Aggregate maturity may be machine-readable only as `human_advisory_only`, never privileged or presented alone. Vectors, citations, freshness, confidence, composition, limitations, and Goodhart warnings stay available at the same decision point. Machine ranking, gating, prioritization, agent scoring, automation, and scalar-only decisions remain unavailable.
- **I-MA8 — Promotion-only action.** Observations may inform a proposal; normal Issue/PR/PromotionIntent/owner-doc authority paths make changes.
- **I-MA9 — Bounded complete reads.** Every v1 snapshot/export has a hard bound, deterministic order, and completeness manifest. Exceeding the bound, unknown filters, or incomplete capture refuses without a measurement-eligible partial result.
- **I-MA10 — Historical honesty.** Assessment assertions are not general bitemporality. Unsupported as-of, reconstruction, valid-time, finding-history, or watermark-history semantics refuse explicitly.
- **I-MA11 — Read-side-effect freedom.** The query path uses SQLite read-only mode and cannot initialize, migrate, receipt, call an event sink, or mutate any surface. Observation consumes an already-returned outcome outside that path.
- **I-MA12 — Conditional continuation binding.** Pagination is absent from v1. If later size evidence authorizes it, continuation must bind a retained immutable snapshot, query, versions, limit, and last key; unavailable snapshots, tampering, overlap, omission, or replay under another query fail explicitly.
- **I-MA13 — Version/semantics refusal.** Unknown schemas, resources, filters, comparison rules, or historical modes produce typed errors, never fallback or coercion.
- **Determinism.** Identical snapshot digest, canonical query, and version bundle produce byte-identical semantic results modulo explicitly excluded volatile fields such as `generated_at`.
- **No retroactive provenance.** History starts when captured; no backfill claims evidence, definition, or configuration provenance that was not recorded.
- **Complete observation binding.** Metric observations bind snapshot/query digests, schema versions, taxonomy digest, definition/version/digest, formula/detector bundles, threshold/config bundle, watermarks, provenance, and generated time.
- **Policy-bound retention.** Retained samples bind the applicable policy version and default to 365 days. Storage use is visible; automatic expiry is allowed at 365 days, while earlier pruning is an explicit operator action with preview. Correction/deletion/pruning removes or supersedes payloads without erasing the non-content lifecycle marker, and unavailable retained sources make dependent replay/comparison refuse.

Partial-failure paths:

- Q1a state identity lands but Q1b is absent: the public capability is **not delivered**; no consumer may treat schemas as a supported query surface.
- If later size evidence authorizes pagination, continuation replays its retained immutable snapshot or refuses when that snapshot is unavailable; it never follows mutable current state.
- The store is absent, old, or unsupported: query returns a typed error without creating a directory/database/schema/receipt.
- The declared single-operator access, identity-lifecycle, or retention policy version is missing or unsupported: export/history operations refuse; they do not infer a different policy.
- A metric definition or detector bundle changes: comparison refuses; it never coerces observations into a trend.
- Retaining a metric sample fails: the already-returned read result remains unchanged, no partial retained sample is eligible for comparison, and the failure is surfaced explicitly.
- O1 records an unsupported historical question: the record remains privacy-safe evidence, not authorization for M2. M2 requires an accepted question with source authority and new executable contract.
- O1 records repeated feature demand: O2 remains a proposal gate; no feature, prediction, automation, or federation work is pre-authorized.
- O1 observation persistence fails: the BuilderOps-local outer adapter returns a typed observation error and rolls back its adjacent-store transaction, while the already-returned query result/refusal and CKM state remain unchanged. Product/runtime OEF outbox, worker, retry, and dead-letter semantics do not apply.

## Implementation tasks

| Order | Task / Issue | Outcome | Dependencies | Parallelization |
| --- | --- | --- | --- | --- |
| 1 | [ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md](ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md) (Q1a, #3776) | Lifecycle-safe identity, policy-bound DTO/error/envelope schemas, epoch/revision, and complete-snapshot contract | owner decisions recorded; task and Issue contract reconciled | terminal delivered |
| 2 | [DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md](DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md) (Q1b, #3777) | Working read-only one-transaction bounded complete snapshot service and CLI JSON | #3776 | terminal delivered; Q1 parent validation retains both Q1a and Q1b receipts |
| 3a | [OPTIMIZE_BOUNDED_QUERY_PLANS.md](OPTIMIZE_BOUNDED_QUERY_PLANS.md) (Q2, #3778) | Filters, batch plans, indexes, constant query count, N+1 removal | #3777 | terminal delivered |
| 3b | [DEFINE_METRIC_REGISTRY_AND_OBSERVATIONS.md](DEFINE_METRIC_REGISTRY_AND_OBSERVATIONS.md) (M1, #3779) | Versioned metrics, explicitly retained replayable source samples, fully bound observations, storage accounting, and 365-day pruning/correction lifecycle | #3777 | terminal delivered |
| 3c | [CAPTURE_QUERY_QUESTIONS.md](CAPTURE_QUERY_QUESTIONS.md) (O1a, #3780) | Privacy-safe query/unsupported/question observation | #3777 | terminal delivered by PR #4060 |
| 4 | [COMPARE_COMPATIBLE_OBSERVATIONS.md](COMPARE_COMPATIBLE_OBSERVATIONS.md) (O1b, #3781) | Compatible immutable observation comparison | #3779 | terminal delivered |

Dependency graph:

`accepted owner decisions → task/Issue reconciliation → Q1a → Q1b → {Q2, M1, O1a}`

`M1 → O1b`

`accepted historical question from O1 → future M2 contract`

`accepted observation evidence → future O2 proposal`

## Q2 delivered bounded-query semantics

Q2 (#3778) extends the Q1 read service with a deliberately small allowlist:
bounded capability public-ID and subtree filters, capability-scoped evidence,
assessment, and finding filters, and unlinked-artifact selection. Filters are
canonicalized, deterministically ordered, completeness-accounted, and subject
to the same hard capture bound, access policy, one-transaction snapshot, and
mixed-epoch refusal rules as Q1. Unknown, invalid, or over-bound requests return
a typed refusal without a partial semantic result.

Composite indexes support the live predicates and are installed by both new-
store bootstrap and existing-store `ensure_schema()` migration. Projection and
overview rendering use one explicit read-only SQLite snapshot transaction with
a constant statement plan. The batch binds and rechecks CKM epoch/revision/schema
identity plus database-file identity, and it refuses before materialization when
any declared object-class or aggregate capture bound is exceeded. Rendering also
performs a fail-loud schema preflight and cannot initialize or migrate a missing
or outdated store. Write/CLI producers remain responsible for explicit schema
setup before producing generated files. This delivery does not add pagination,
arbitrary filters or sorting, ranking, HTTP/UI, metrics, or observation semantics.

## M1 delivered semantics

M1 (#3779) supplies a small versioned registry of descriptive, snapshot-bound
metric observations. Its outer measurement adapter retains a source payload
only after the Q1 read result exists, together with bound watermarks,
finding-evaluation material, and the observation receipt. Retention is a
versioned 365-day policy with visible storage use, previewed early pruning,
superseding correction, and non-content deletion markers. The public result
keeps confirmed and candidate material separate and carries the vector,
distribution, composition, citations, freshness, confidence, limitations,
and Goodhart warnings beside an optional `human_advisory_only` aggregate.

This does not establish a cadence, observation window, minimum snapshot
count, M2 history, O2 automation, drift detection, federation, rankings, or
machine decision authority. Those remain unresolved or out of scope until a
new source-backed contract is accepted.

## O1b delivered comparison semantics

O1b (#3781) compares only two or more replayable retained M1 observations
whose metric definition, formula/detector/configuration, schema, taxonomy,
canonical query, tagged value-state, candidate/confirmed, identity, and
access/redaction bindings all match. It returns deterministic component-wise
deltas with input identity, provenance, freshness, citations, explicit tagged
state transitions, and limitations; any mismatch, missing policy binding,
expiry/pruning/deletion, or tamper refuses without a partial result. An
aggregate is only `human_advisory_only`, co-present with components and
limitations, and never sufficient for authority. The gathered observation is
implementation/test evidence only: it establishes neither trend nor cadence.

## Observation-gated future work

- **O1a records bounded categories, not content or authority.** The delivered
  BuilderOps-local adapter distinguishes supported results, typed refusals,
  unsupported historical requests, and human-accepted questions. Accepted
  questions use the closed categories `evidence_coverage_change`,
  `source_freshness_change`, `citation_confidence_change`,
  and `candidate_finding_composition_change`.
  These categories are structural evidence only: their presence, frequency,
  or source-authority digest cannot activate a capability or create backlog.
- **M2 is not filed or Ready.** The accepted question set is limited to compatible sampled changes in evidence coverage/composition, source freshness, citation/confidence coverage, and candidate/finding composition. Filing still requires a costed smallest implementation, source authority, precise semantics, and verifiable refusal behavior. General bitemporality is not the answer.
- **O2 is not filed or pre-authorized.** Filters beyond Q2, comparison/timeline product surfaces, drift, prediction, automation, and federation require accepted observation evidence and their normal authority path.
- Two compatible snapshots are only the mathematical minimum for a delta. They do not prove a cadence, trend, window duration, or minimum evidence count.

## Linker recall baseline

Dated observation, 2026-07-29 (#4259). This is a measurement of the deterministic
linkers in `app/builderops/ckm/linkers.py`, not a change to them. It exists because
the 2026-07-28 pipeline run produced 10 855 artifacts, 2 088 evidence edges, and
10 398 unlinked artifacts, and nothing in the system distinguished "no relationship
exists" from "the linker could not see the relationship".

### Snapshot under measurement

Store `~/.local/state/builderops/builderops.sqlite3` as of 2026-07-29: 10 855
artifacts, 31 capabilities, 2 088 confirmed deterministic edges over 457 distinct
artifacts, 10 398 unlinked artifacts, 28 findings. Read-only throughout; the
measurement ran against a copy and wrote nothing back.

### Sampling method

- **Frame.** The 10 398 artifacts with no row in `ckm_evidence_edge`.
- **Stratification.** By `ckm_artifact.source`, the seven ingestion sources:
  `repo_docs`, `repo_tests`, `repo_source`, `repo_schemas`, `repo_git`,
  `github_issues`, `github_pull_requests`.
- **Size.** Equal allocation, 25 per stratum, 175 total. Equal allocation buys
  per-stratum precision; population figures below are reweighted by stratum size.
  `repo_schemas` has only 26 unlinked members, so its sample is near-census.
- **Draw rule (reproducible).** Seed `4259`. Order each stratum ascending by
  `sha256("4259:" || public_id)` and take the first 25. `public_id` is
  rebuild-stable and never reused (I-MA3), so the same seed redraws the same
  sample from any snapshot containing the same artifacts.

### Labelling rule

Each sampled artifact gets exactly one label, applied in this order.

1. **Scope test.** Does the artifact carry evidence about at least one of the 31
   CKM capabilities? Those capabilities are Product/Runtime SBS boundaries.
   Material whose entire subject is Builder System — `.codex/**`, `.github/**`,
   `docs/development/**`, `app/builderops/**`, `app/dispatcher/**`, dependency
   manifests, lint-only cleanups — is outside the taxonomy. If no capability is
   named, the label is **A — genuinely unrelated to any capability**.
2. **Reachability test.** Otherwise, does a rule using *literal string identity
   only* resolve the artifact to a specific capability, from data already present
   in the store? No synonym expansion, no topic inference, no reading of natural
   language meaning. The rule need not exist today; it only has to be
   implementable deterministically. The qualifying signals are:
   - **S1** a `changed_paths`/`changed_files` entry that is itself a linked artifact;
   - **S2** an exact capability name in the artifact text, using the same
     non-substring-bleed match as `linkers.py :: _name_selectors`;
   - **S2b** an SBS boundary code whose boundary maps to exactly one capability;
   - **S3** the artifact lives in a capability seed document's directory;
   - **S4** a `tests/` → `app/` mirror or import that resolves to a linked source file;
   - **S5** a cited path that is a seed path or an already-linked artifact.

   Any signal firing gives **B — a deterministic linker could reasonably reach this**.
3. **Otherwise C — relatable only by semantic judgement**: a relationship exists,
   but every route to it requires interpreting meaning rather than matching a token.

Two boundary decisions matter and are stated so a later run can repeat them.
First, a transitive route counts as B only when the intermediate artifact is
*already linked* — otherwise the route does not terminate at a capability today.
Second, ambiguous builder-vs-product material was labelled C, not A; A was
reserved for artifacts with no product-capability subject at all.

### Recall

Recall counts the artifacts the linkers actually reached against the artifacts
that genuinely carry capability evidence. Two denominators are reported because
they bracket the honest answer:

- **Recall** = linked / (linked + B̂ + Ĉ) — against everything relatable.
- **Deterministic recall** = linked / (linked + B̂) — against only what a
  deterministic mechanism could reach. This is the ceiling for the current design.

By artifact source:

| Source | Linked | Unlinked | B̂ | Ĉ | Â | Recall | Det. recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `github_issues` | 223 | 1 606 | 118 | 779 | 709 | 19.9% | 65.4% |
| `github_pull_requests` | 68 | 2 008 | 167 | 1 590 | 251 | 3.7% | 28.9% |
| `repo_docs` | 50 | 872 | 419 | 349 | 105 | 6.1% | 10.7% |
| `repo_git` | 0 | 3 871 | 155 | 2 323 | 1 394 | 0.0% | 0.0% |
| `repo_schemas` | 6 | 26 | 0 | 26 | 0 | 18.8% | 100.0% |
| `repo_source` | 5 | 805 | 129 | 580 | 97 | 0.7% | 3.7% |
| `repo_tests` | 105 | 1 210 | 242 | 823 | 145 | 9.0% | 30.3% |
| **Total** | **457** | **10 398** | **1 229** | **6 470** | **2 699** | **5.6%** | **27.1%** |

By maturity dimension, using the dimension each artifact would carry if linked
(`linkers.py :: _dimension` plus the `_github_links` state override):

| Dimension | Linked | Unlinked | B̂ | Ĉ | Â | Recall | Det. recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `architectural_stability` | 24 | 37 | 18 | 15 | 4 | 42.4% | 57.5% |
| `documentation_quality` | 29 | 494 | 234 | 227 | 33 | 5.9% | 11.0% |
| `functional_completeness` | 71 | 6 599 | 444 | 4 425 | 1 731 | 1.4% | 13.8% |
| `integration_completeness` | 57 | 864 | 7 | 493 | 364 | 10.2% | 89.3% |
| `requirement_coverage` | 171 | 1 194 | 285 | 488 | 421 | 18.1% | 37.5% |
| `test_completeness` | 105 | 1 210 | 242 | 823 | 145 | 9.0% | 30.3% |
| **Total** | **457** | **10 398** | **1 229** | **6 470** | **2 699** | **5.6%** | **27.1%** |

Sample label counts, for anyone re-deriving the estimates: `github_issues`
B=2/C=12/A=11; `github_pull_requests` B=2/C=20/A=3; `repo_docs` B=12/C=10/A=3;
`repo_git` B=1/C=15/A=9; `repo_schemas` B=0/C=25/A=0; `repo_source` B=4/C=18/A=3;
`repo_tests` B=5/C=17/A=3. Stratified bootstrap over the label draws (20 000
resamples, seed 4259) puts recall at 5.6% with a 95% interval of [5.1%, 6.3%]
and deterministic recall at 27.1% with [20.6%, 37.1%]. Sampling error is not what
dominates this measurement; the A-versus-C judgement is, and it is bounded — even
if every C artifact were reclassified as unrelated, recall could not exceed the
27.1% deterministic ceiling.

### Why recall is this low

Three mechanisms account for nearly all of it, each verified by reading the
linker source and the store rather than by pattern-matching:

1. **The spec vocabulary and the capability vocabulary are different namespaces.**
   385 documents under `docs/` declare `parent_capability:` across 69 distinct values.
   `_spec_links` resolves that value by exact capability name or slug, and exactly
   one value — `Commitment surfacing` — is in the 31-capability taxonomy. The
   result is 3 `spec-directory` edges. Because `_github_links` builds its spec
   lookup from those edges, the entire GitHub issue and PR path collapses onto
   three spec directories plus the seed paths.
2. **Commits have no producing linker at all.** Each linker either iterates
   artifacts filtered to `spec`, `adr`, `test`, `issue`, or `pull_request`, or
   walks the traceability matrix, whose citation extraction yields only
   `app|docs|tests|schemas` paths, markdown link targets, `github:issue:<n>`, and
   `docs/adr/ADR-<n>` prefixes — never a `git:<sha>` reference. Source files are
   reached only transitively, through `spec-source` and `test-code`. All 3 871
   commit artifacts are therefore unreachable by construction — 37% of
   the corpus and the whole of the largest stratum. They are not information-poor:
   commits carry `changed_paths`, and PRs carry `changed_files`, which no linker
   reads.
3. **The failures cascade.** For 19 of 25 sampled unlinked PRs and 16 of 25
   sampled unlinked issues, a deterministic route to a capability exists but
   terminates on an artifact that is itself unlinked. With 5 of 810 source files
   and 3 of 370 specs linked, most transitive joins have nothing to land on.

For scale, the traceability matrix the `matrix` linker reads contributes 18
numbered rows, and 1 327 of the 2 088 edges come from a single rule,
`github-ref` seed-path matching.

### Conclusion: are CKM maturity scores trustworthy enough to shape delivery drafts?

**No, not at present, and the two dimensions that still produce findings are the
two worst-measured ones.** A maturity score is currently a readout of linker
coverage far more than of system maturity.

All 28 remaining findings come from one detector, `starved_dimension`. Every one
has the same shape: a dimension scored 0.00–0.20 against `architectural_stability`
at 1.00, across 14 capabilities × 2 dimensions. That comparison is exactly the
recall gradient in the table above — `architectural_stability` is the best-covered
dimension at 42.4% recall, `requirement_coverage` sits at 18.1%, and
`functional_completeness` at 1.4%. A detector that fires when one dimension is far
below its siblings will fire on differential linker recall whether or not the
underlying capability is immature, and that is the most parsimonious reading of
all 28.

So the findings should not be treated as evidence that these capabilities lack
functional or requirement coverage. They are evidence that CKM cannot currently
see the functional and requirement material that exists. The narrower claim they
do support is sound and worth keeping: for these 14 capabilities, CKM holds
almost no confirmed source-kind or merged-PR evidence. That is a true statement
about the evidence graph. It is not a true statement about the system.

Nothing here contradicts I-MA7 or the accepted metric-use decision — maturity
was never authoritative. It does mean that until recall improves, an aggregate
maturity value is not even a *useful* advisory input on
`functional_completeness` or `requirement_coverage`, and delivery drafts should
not be shaped by it.

### What would count as an improvement

A later run is comparable when it uses seed `4259`, the same seven-stratum
allocation, and the labelling rule above, and reports both denominators.

- **The headline number is deterministic recall**, currently 27.1%. It is the
  ceiling reachable without semantic association, so it is what linker work moves.
- **First target: deterministic recall ≥ 60% and `functional_completeness`
  recall ≥ 25%.** Reaching either requires closing the three mechanisms above,
  not tuning thresholds.
- **A run is not an improvement if overall recall rises while deterministic
  recall does not** — that would mean edges arrived from somewhere other than the
  deterministic linkers, and precision would then need its own measurement.
- **Findings are not a progress metric.** Finding count can fall because recall
  improved or because a detector was narrowed; only the recall pair distinguishes
  those.
- **Re-measure before, not after, acting on a maturity score.** The gap between
  5.6% and 27.1% is the honest uncertainty in every current CKM maturity claim.

Precision was not measured. This baseline says nothing about whether the 2 088
existing edges are correct, only about how much is missing. Fixing the linkers is
out of scope for #4259 by construction — this measurement exists to decide whether
that repair is warranted, and it is.

## Capability acceptance criteria

- [x] All five owner decisions are accepted in the authoritative specification.
  Verify: decision writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted pre-implementation owner decisions`
- [x] Every affected task and Issue contract reflects the accepted owner decisions before any child resumes.
  Verify: strict readiness validation and reconciliation receipt for each affected Issue
- [x] Q1 contract and implementation prove lifecycle-safe non-reused public identity, atomic state revision, one-transaction complete snapshots, policy metadata, tagged missing states, deterministic bounded capture, completeness accounting, and exact lookup.
  Verify: Q1a and Q1b child delivery receipts plus `tests/builderops/ckm/test_query_service.py`
- [x] Query execution is read-only/side-effect free; incomplete/oversized capture and all unknown schema/version/policy/semantics states fail explicitly.
  Verify: `tests/builderops/ckm/test_query_service.py::test_query_path_is_read_only_and_side_effect_free`; `tests/builderops/ckm/test_query_service.py::test_incomplete_or_oversized_snapshot_refuses`
- [x] Q2 proves bounded indexed plans, constant query counts per complete capture, and no N+1 regression without weakening Q1 ordering/completeness guarantees.
  Verify: `tests/builderops/ckm/test_query_plans.py`
- [x] M1 emits deterministic fully bound descriptive observations with machine-readable Goodhart warnings; any aggregate is `human_advisory_only`, accompanied by its evidence-rich components, and cannot drive machine authority.
  Verify: `tests/builderops/ckm/test_metrics.py`
- [x] M1 owns complete sampled-retention delivery: explicit post-read capture of immutable source payload plus observation, 365-day policy binding, count/byte visibility, previewed early pruning, superseding correction, non-content deletion markers, and replay refusal for unavailable payloads; O1a owns the corresponding observation correction/deletion lifecycle truth.
  Verify: `tests/builderops/ckm/test_metrics.py::test_explicit_retention_runs_outside_read_path_and_binds_source_sample`; `tests/builderops/ckm/test_metrics.py::test_retained_samples_apply_storage_accounting_and_pruning_policy`; `tests/builderops/ckm/test_metrics.py::test_retained_sample_correction_and_deletion_preserve_lifecycle_truth`; `tests/builderops/ckm/test_observation_capture.py::test_observation_correction_and_deletion_preserve_lifecycle_truth`; `tests/builderops/ckm/test_metric_comparison.py::test_unavailable_or_tampered_retained_source_refuses_comparison`
- [x] O1a records privacy-safe real questions outside the read path and preserves typed unsupported requests without authorizing new capability.
  Verify: `tests/builderops/ckm/test_observation_capture.py`; validation receipt on the successor parent
- [x] O1b compares only compatible immutable observations and refuses every semantics-bearing mismatch; cadence and minimum-snapshot hypotheses remain explicitly unresolved.
  Verify: `tests/builderops/ckm/test_metric_comparison.py`; validation receipt on the successor parent
- [x] Every child has a delivery receipt, owner-doc resolution, transition-debt result, and local review/CI evidence; D11/D12 and unresolved learning candidates are terminally resolved.
  Verify: successor-parent closure ledger and child issue receipts
- [x] Owner-doc promotion states supported access/measurement truth only after all repo-verifiable acceptance criteria pass.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: State` plus post-merge owner-doc receipt

## Verification and acceptance path

Each task shipped its named focused tests, ran `ruff check app tests`, and passed current-SHA CI plus the local review gate. Every child closure posted a receipt to the successor parent. The parent remained blocked/non-pickup through resolution of the full verification ledger, owner-doc outcomes, transition debt, D11/D12, and learning outcomes; its explicit lifecycle closure is reserved for independent verification after this promotion.

Live validation hub: [#3775](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3775). Children: Q1a #3776, Q1b #3777, Q2 #3778, M1 #3779, O1a #3780, O1b #3781. GitHub owns execution state; this directory owns the implementation contract.

Parent acceptance did not require a fixed observation duration or snapshot count. It required the observation mechanism to be delivered and the evidence captured by that point to be reported truthfully. Any later feature proposal gets its own source-backed contract.

## Source docs

- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- BuilderOps inquiry `inq_20260715T062832Z_e73546a2`, terminal receipt `receipt_inq_20260715T062832Z_e73546a2_run_terminal`
- BuilderOps inquiry `inq_20260715T090347Z_61c6d5e4`, terminal receipt `receipt_inq_20260715T090347Z_61c6d5e4_run_terminal`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
