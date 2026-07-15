State: Target-state specification directory for the post-MVP CKM Measurement & Access capability. Backlog is filed as parent #3775 with children #3776-#3781. The five owner decisions are accepted below, but every child remains blocked pending reconciliation and strict revalidation of its task and Issue contract. Accepted predecessor CKM MVP validation hub: closed GitHub issue #3138. No successor implementation claim.
Doc role: Specification directory (capability breakdown)
Authority: Owns the accepted post-MVP access, measurement, observation, dependency, and acceptance contract. Subordinate to ADR-0057 and the Builder System authority boundary.
Owner: BuilderOps governance / Capability Knowledge Model
Temporal class: operational
Review cadence: event-driven
Source of truth: this directory for implementation task shape; ADR-0057 for CKM existence and authority posture; canonical fitness registration remains in `docs/architecture/SBS_FITNESS_RULES.md`.
Last reviewed: 2026-07-15

# CKM Measurement & Access

This specification defines how a successor capability will make the delivered Capability Knowledge Model safely consumable by machines and measurable without turning CKM projections into authority. It follows the accepted CKM MVP (#3138), the architecture audit `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`, and BuilderOps inquiries `inq_20260715T062832Z_e73546a2` and `inq_20260715T090347Z_61c6d5e4` (both `consensus`). The later inquiry governs where the two inquiry handoffs differ, and the owner decisions recorded below now resolve its five policy gates.

Work classification: **Builder System / CES boundary**. CKM remains projection-only BuilderOps analysis. OEF may consume descriptive observations but gains no policy or control authority. Product/Runtime artifacts and GitHub remain read-only sources. Federation remains SFC/CES-owned, and Correctness Kernel drift remains a separate declared-state contract.

## Capability boundary

Once parent acceptance is complete, the specified successor capability will provide:

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
- O1 records an unsupported historical question: the record remains privacy-safe evidence, not authorization for M2. M2 requires an accepted question with source authority and new executable contract.
- O1 records repeated feature demand: O2 remains a proposal gate; no feature, prediction, automation, or federation work is pre-authorized.
- O1 event recording fails: the failure follows the authoritative OEF contract, while the already-returned query result/refusal and CKM state remain unchanged.

## Implementation tasks

| Order | Task / Issue | Outcome | Dependencies | Parallelization |
| --- | --- | --- | --- | --- |
| 1 | [ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md](ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md) (Q1a, #3776) | Lifecycle-safe identity, policy-bound DTO/error/envelope schemas, epoch/revision, and complete-snapshot contract | owner decisions recorded; task and Issue contract reconciled | serial |
| 2 | [DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md](DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md) (Q1b, #3777) | Working read-only one-transaction bounded complete snapshot service and CLI JSON | #3776 | serial; completes Q1 gate |
| 3a | [OPTIMIZE_BOUNDED_QUERY_PLANS.md](OPTIMIZE_BOUNDED_QUERY_PLANS.md) (Q2, #3778) | Filters, batch plans, indexes, constant query count, N+1 removal | #3777 | may parallelize after Q1 with M1/O1a if ownership stays isolated |
| 3b | [DEFINE_METRIC_REGISTRY_AND_OBSERVATIONS.md](DEFINE_METRIC_REGISTRY_AND_OBSERVATIONS.md) (M1, #3779) | Versioned metrics and fully bound observations | #3777 | may parallelize after Q1 with Q2/O1a |
| 3c | [CAPTURE_QUERY_QUESTIONS.md](CAPTURE_QUERY_QUESTIONS.md) (O1a, #3780) | Privacy-safe query/unsupported/question observation | #3777 | may parallelize after Q1; must reconcile any authoritative OEF event contract |
| 4 | [COMPARE_COMPATIBLE_OBSERVATIONS.md](COMPARE_COMPATIBLE_OBSERVATIONS.md) (O1b, #3781) | Compatible immutable observation comparison | #3779 | may follow M1 independently of Q2 unless live scale disproves the Q1 bound |

Dependency graph:

`accepted owner decisions → task/Issue reconciliation → Q1a → Q1b → {Q2, M1, O1a}`

`M1 → O1b`

`accepted historical question from O1 → future M2 contract`

`accepted observation evidence → future O2 proposal`

## Observation-gated future work

- **M2 is not filed or Ready.** The accepted question set is limited to compatible sampled changes in evidence coverage/composition, source freshness, citation/confidence coverage, and candidate/finding composition. Filing still requires a costed smallest implementation, source authority, precise semantics, and verifiable refusal behavior. General bitemporality is not the answer.
- **O2 is not filed or pre-authorized.** Filters beyond Q2, comparison/timeline product surfaces, drift, prediction, automation, and federation require accepted observation evidence and their normal authority path.
- Two compatible snapshots are only the mathematical minimum for a delta. They do not prove a cadence, trend, window duration, or minimum evidence count.

## Capability acceptance criteria

- [x] All five owner decisions are accepted in the authoritative specification.
  Verify: decision writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted pre-implementation owner decisions`
- [ ] Every affected task and Issue contract reflects the accepted owner decisions before any child resumes.
  Verify: strict readiness validation and reconciliation receipt for each affected Issue
- [ ] Q1 contract and implementation prove lifecycle-safe non-reused public identity, atomic state revision, one-transaction complete snapshots, policy metadata, tagged missing states, deterministic bounded capture, completeness accounting, and exact lookup.
  Verify: Q1a and Q1b child delivery receipts plus `tests/builderops/ckm/test_query_service.py`
- [ ] Query execution is read-only/side-effect free; incomplete/oversized capture and all unknown schema/version/policy/semantics states fail explicitly.
  Verify: `tests/builderops/ckm/test_query_service.py::test_query_path_is_read_only_and_side_effect_free`; `tests/builderops/ckm/test_query_service.py::test_incomplete_or_oversized_snapshot_refuses`
- [ ] Q2 proves bounded indexed plans, constant query counts per complete capture, and no N+1 regression without weakening Q1 ordering/completeness guarantees.
  Verify: `tests/builderops/ckm/test_query_plans.py`
- [ ] M1 emits deterministic fully bound descriptive observations with machine-readable Goodhart warnings; any aggregate is `human_advisory_only`, accompanied by its evidence-rich components, and cannot drive machine authority.
  Verify: `tests/builderops/ckm/test_metrics.py`
- [ ] O1a records privacy-safe real questions outside the read path and preserves typed unsupported requests without authorizing new capability.
  Verify: `tests/builderops/ckm/test_observation_capture.py`; validation receipt on the successor parent
- [ ] O1b compares only compatible immutable observations and refuses every semantics-bearing mismatch; cadence and minimum-snapshot hypotheses remain explicitly unresolved.
  Verify: `tests/builderops/ckm/test_metric_comparison.py`; validation receipt on the successor parent
- [ ] Every child has a delivery receipt, owner-doc resolution, transition-debt result, and local review/CI evidence; D11/D12 and unresolved learning candidates are terminally resolved.
  Verify: successor-parent closure ledger and child issue receipts
- [ ] Owner-doc promotion states supported access/measurement truth only after all repo-verifiable acceptance criteria pass.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: State` plus post-merge owner-doc receipt

## Verification and acceptance path

Each task ships its named focused tests, runs `ruff check app tests`, and passes current-SHA CI plus the local review gate. Every closure posts a receipt to the successor parent. The parent stays blocked/non-pickup until the full verification ledger, owner-doc resolutions, transition debt, D11/D12, and learning outcomes are resolved.

Live validation hub: [#3775](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3775). Children: Q1a #3776, Q1b #3777, Q2 #3778, M1 #3779, O1a #3780, O1b #3781. GitHub owns execution state; this directory owns the implementation contract.

Future parent acceptance will not require a fixed observation duration or snapshot count. It will require the observation mechanism to be delivered and the evidence captured by that point to be reported truthfully. Any later feature proposal gets its own source-backed contract.

## Source docs

- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- BuilderOps inquiry `inq_20260715T062832Z_e73546a2`, terminal receipt `receipt_inq_20260715T062832Z_e73546a2_run_terminal`
- BuilderOps inquiry `inq_20260715T090347Z_61c6d5e4`, terminal receipt `receipt_inq_20260715T090347Z_61c6d5e4_run_terminal`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
