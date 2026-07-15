State: Target-state specification directory for the post-MVP CKM Measurement & Access capability. Backlog filed as parent #3775 with children #3776-#3781; all children remain dependency-blocked until this specification merges. Accepted predecessor CKM MVP validation hub: closed GitHub issue #3138. No successor implementation claim.
Doc role: Specification directory (capability breakdown)
Authority: Owns the accepted post-MVP access, measurement, observation, dependency, and acceptance contract. Subordinate to ADR-0057 and the Builder System authority boundary.
Owner: BuilderOps governance / Capability Knowledge Model
Temporal class: operational
Review cadence: event-driven
Source of truth: this directory for implementation task shape; ADR-0057 for CKM existence and authority posture; canonical fitness registration remains in `docs/architecture/SBS_FITNESS_RULES.md`.
Last reviewed: 2026-07-15

# CKM Measurement & Access

This successor capability makes the delivered Capability Knowledge Model safely consumable by machines and measurable without turning CKM projections into authority. It follows the accepted CKM MVP (#3138), the architecture audit `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`, and BuilderOps inquiry `inq_20260715T062832Z_e73546a2` (`consensus`).

Work classification: **Builder System / CES boundary**. CKM remains projection-only BuilderOps analysis. OEF may consume descriptive observations but gains no policy or control authority. Product/Runtime artifacts and GitHub remain read-only sources. Federation remains SFC/CES-owned, and Correctness Kernel drift remains a separate declared-state contract.

## Capability boundary

The delivered capability provides:

- a transport-neutral, versioned CKM result/error envelope and resource DTOs;
- rebuild-stable public resource identity, independent of mutable names, slugs, and SQLite row IDs;
- a CKM epoch/state revision advanced atomically with every CKM mutation;
- immutable snapshot manifests/digests binding state revision, schemas, taxonomy, watermarks, and provenance;
- one explicit read-only SQLite transaction for each snapshot query;
- bounded exact-ID lookup and deterministic keyset pagination with explicit truncation;
- CLI JSON as the first adapter over the same query service future HTTP/UI adapters would use;
- richer bounded filters and batch query plans after the correctness baseline;
- versioned descriptive metric definitions and fully bound immutable observations;
- privacy-safe outer-adapter observation of already-returned query/question and unsupported-request outcomes;
- comparison only between semantically compatible immutable observations.

The capability does **not** provide general bitemporality, arbitrary as-of reconstruction, retroactive provenance, rankings, gates, scalar-only ordering, agent scoring, prioritization, prediction, automation, drift detection, or federation.

## Accepted architecture decisions

1. Q1 is one acceptance gate: contract plus a minimal working single-transaction snapshot. Q1a may land schemas/state identity first, but Q1 is not delivered until Q1b proves the public contract on the production read path.
2. Public identity survives rebuild and display-name/slug changes. Raw row IDs are never public identifiers.
3. Snapshot identity binds epoch, transactionally advanced state revision, resource/envelope schema versions, taxonomy digest, exact watermarks, and the canonical read-set digest.
4. Query execution is read-only and side-effect free: no directory creation, schema initialization, migration, receipt emission, event callback, or mutation. O1a observation, when present, is a separate outer adapter invoked only after the immutable query result/refusal returns.
5. Results have stable total order ending in immutable public ID. Cursors bind contract/resource versions, canonical query digest, snapshot digest, limit, and last key; tampering or changed state refuses explicitly.
6. Missing, not-applicable, unsupported, and measured-zero are tagged distinct states. Candidate and confirmed material remain separate. Truncation is always explicit.
7. DTOs, errors, query services, and envelopes are transport-neutral. Click parses/serializes only.
8. General valid-time/system-state history is unsupported. Assessment assertion history remains supported; unsupported historical requests fail explicitly. No provenance is fabricated retroactively.
9. Metrics are descriptive and snapshot-bound. Every definition exposes Goodhart warnings and `not_for_gating: true`; aggregate/scalar ordering and automated authority are rejected.
10. Comparison refuses any semantics-bearing mismatch. Cadence, observation-window length, and minimum distinct snapshots remain hypotheses until observed.

## Cross-task invariants / interaction safety

These invariants are registered in `docs/architecture/SBS_FITNESS_RULES.md`; this section applies them to the task seams.

- **I-MA1 — Projection-only access.** Every result declares non-authoritative projection status, provenance, and freshness. Reads cannot mutate CKM, GitHub, repo, BuilderOps authority, or Product/Runtime state.
- **I-MA2 — Snapshot consistency.** Every multi-object result comes from one read transaction and binds all CKM state via epoch/revision, versions, taxonomy, watermarks, and digest. No cross-snapshot mixing.
- **I-MA3 — Rebuild-stable public identity.** Public identity survives rebuild and mutable display metadata; row IDs stay private.
- **I-MA4 — Tagged value state.** `measured`, `missing`, `not_applicable`, and `unsupported` are distinct; measured zero is not absence.
- **I-MA5 — Comparable observations.** Observation and comparison bind every semantics-bearing definition/version/config input and refuse mismatch.
- **I-MA6 — Candidate separation.** Candidate and confirmed evidence/resources remain distinct in structured results and observations.
- **I-MA7 — No scalar authority.** Vectors, citations, freshness, confidence, and composition stay available; ranking, gating, prioritization, or scalar-only decisions are unavailable.
- **I-MA8 — Promotion-only action.** Observations may inform a proposal; normal Issue/PR/PromotionIntent/owner-doc authority paths make changes.
- **I-MA9 — Bounded reads.** Every scan has a hard limit, stable order, keyset cursor, and explicit truncation. Unknown/unbounded filters refuse.
- **I-MA10 — Historical honesty.** Assessment assertions are not general bitemporality. Unsupported as-of, reconstruction, valid-time, finding-history, or watermark-history semantics refuse explicitly.
- **I-MA11 — Read-side-effect freedom.** The query path uses SQLite read-only mode and cannot initialize, migrate, receipt, call an event sink, or mutate any surface. Observation consumes an already-returned outcome outside that path.
- **I-MA12 — Cursor/snapshot binding.** Cursor tokens bind query, snapshot, versions, limit, and last key; tampering, state change, overlap, omission, or replay under another query fails explicitly.
- **I-MA13 — Version/semantics refusal.** Unknown schemas, resources, filters, comparison rules, or historical modes produce typed errors, never fallback or coercion.
- **Determinism.** Identical snapshot digest, canonical query, and version bundle produce byte-identical semantic results modulo explicitly excluded volatile fields such as `generated_at`.
- **No retroactive provenance.** History starts when captured; no backfill claims evidence, definition, or configuration provenance that was not recorded.
- **Complete observation binding.** Metric observations bind snapshot/query digests, schema versions, taxonomy digest, definition/version/digest, formula/detector bundles, threshold/config bundle, watermarks, provenance, and generated time.

Partial-failure paths:

- Q1a state identity lands but Q1b is absent: the public capability is **not delivered**; no consumer may treat schemas as a supported query surface.
- A CKM mutation commits after page one: continuation refuses `snapshot_changed`; it never mixes pages.
- The store is absent, old, or unsupported: query returns a typed error without creating a directory/database/schema/receipt.
- A metric definition or detector bundle changes: comparison refuses; it never coerces observations into a trend.
- O1 records an unsupported historical question: the record remains privacy-safe evidence, not authorization for M2. M2 requires an accepted question with source authority and new executable contract.
- O1 records repeated feature demand: O2 remains a proposal gate; no feature, prediction, automation, or federation work is pre-authorized.
- O1 event recording fails: the failure follows the authoritative OEF contract, while the already-returned query result/refusal and CKM state remain unchanged.

## Implementation tasks

| Order | Task / Issue | Outcome | Dependencies | Parallelization |
| --- | --- | --- | --- | --- |
| 1 | [ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md](ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md) (Q1a, #3776) | Stable identity, DTO/error/envelope schemas, epoch/revision, snapshot and cursor contracts | predecessor #3138 accepted; spec PR merged | serial |
| 2 | [DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md](DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md) (Q1b, #3777) | Working read-only one-transaction query service and CLI JSON | #3776 | serial; completes Q1 gate |
| 3a | [OPTIMIZE_BOUNDED_QUERY_PLANS.md](OPTIMIZE_BOUNDED_QUERY_PLANS.md) (Q2, #3778) | Filters, batch plans, indexes, constant query count, N+1 removal | #3777 | may parallelize after Q1 with M1/O1a if ownership stays isolated |
| 3b | [DEFINE_METRIC_REGISTRY_AND_OBSERVATIONS.md](DEFINE_METRIC_REGISTRY_AND_OBSERVATIONS.md) (M1, #3779) | Versioned metrics and fully bound observations | #3777 | may parallelize after Q1 with Q2/O1a |
| 3c | [CAPTURE_QUERY_QUESTIONS.md](CAPTURE_QUERY_QUESTIONS.md) (O1a, #3780) | Privacy-safe query/unsupported/question observation | #3777 | may parallelize after Q1; must reconcile any authoritative OEF event contract |
| 4 | [COMPARE_COMPATIBLE_OBSERVATIONS.md](COMPARE_COMPATIBLE_OBSERVATIONS.md) (O1b, #3781) | Compatible immutable observation comparison | #3779 | may follow M1 independently of Q2 unless live scale disproves the Q1 bound |

Dependency graph:

`Q1a → Q1b → {Q2, M1, O1a}`

`M1 → O1b`

`accepted historical question from O1 → future M2 contract`

`accepted observation evidence → future O2 proposal`

## Observation-gated future work

- **M2 is not filed or Ready.** It requires a concrete accepted historical question, source authority, precise semantics, and verifiable refusal behavior. General bitemporality is not the default answer.
- **O2 is not filed or pre-authorized.** Filters beyond Q2, comparison/timeline product surfaces, drift, prediction, automation, and federation require accepted observation evidence and their normal authority path.
- Two compatible snapshots are only the mathematical minimum for a delta. They do not prove a cadence, trend, window duration, or minimum evidence count.

## Capability acceptance criteria

- [ ] Q1 contract and implementation prove rebuild-stable public identity, atomic state revision, one-transaction snapshots, tagged missing states, deterministic bounded scans, exact lookup, and snapshot/query/version-bound cursors.
  Verify: Q1a and Q1b child delivery receipts plus `tests/builderops/ckm/test_query_service.py`
- [ ] Query execution is read-only/side-effect free and all unknown schema/version/semantics/cursor states fail explicitly.
  Verify: `tests/builderops/ckm/test_query_service.py::test_query_path_is_read_only_and_side_effect_free`; `tests/builderops/ckm/test_query_service.py::test_cursor_tampering_and_snapshot_change_refuse`
- [ ] Q2 proves bounded indexed plans, constant query counts per page, and no N+1 regression without weakening Q1 ordering/cursor guarantees.
  Verify: `tests/builderops/ckm/test_query_plans.py`
- [ ] M1 emits deterministic fully bound descriptive observations with machine-readable Goodhart warnings and rejects semantically incompatible comparison inputs.
  Verify: `tests/builderops/ckm/test_metrics.py`
- [ ] O1a/O1b record privacy-safe real questions and compare only compatible immutable snapshots; cadence and minimum-snapshot hypotheses remain explicitly unresolved.
  Verify: `tests/builderops/ckm/test_observation_capture.py`; `tests/builderops/ckm/test_metric_comparison.py`; validation receipts on the successor parent
- [ ] Every child has a delivery receipt, owner-doc resolution, transition-debt result, and local review/CI evidence; D11/D12 and unresolved learning candidates are terminally resolved.
  Verify: successor-parent closure ledger and child issue receipts
- [ ] Owner-doc promotion states supported access/measurement truth only after all repo-verifiable acceptance criteria pass.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: State` plus post-merge owner-doc receipt

## Verification and acceptance path

Each task ships its named focused tests, runs `ruff check app tests`, and passes current-SHA CI plus the local review gate. Every closure posts a receipt to the successor parent. The parent stays blocked/non-pickup until the full verification ledger, owner-doc resolutions, transition debt, D11/D12, and learning outcomes are resolved.

Live validation hub: [#3775](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3775). Children: Q1a #3776, Q1b #3777, Q2 #3778, M1 #3779, O1a #3780, O1b #3781. GitHub owns execution state; this directory owns the implementation contract.

Acceptance does not require a fixed observation duration or snapshot count. It requires the delivered observation mechanism and truthful evidence captured so far. Any later feature proposal gets its own source-backed contract.

## Source docs

- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- BuilderOps inquiry `inq_20260715T062832Z_e73546a2`, terminal receipt `receipt_inq_20260715T062832Z_e73546a2_run_terminal`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
