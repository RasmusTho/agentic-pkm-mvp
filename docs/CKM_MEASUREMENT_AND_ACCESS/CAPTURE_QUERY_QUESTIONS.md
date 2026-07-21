---
name: Capture Query Questions
description: Record privacy-safe CKM query demand, unsupported requests, and accepted questions without granting new history or product authority.
task_id: CKM-MA-O1A
source_anchor: docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Observation-gated future work
parent_capability: CKM Measurement & Access
prerequisites: [CKM-MA-Q1B]
depends_on: [CKM-MA-Q1B]
can_parallelize_with: [CKM-MA-Q2, CKM-MA-M1]
---

# Capture Query Questions

## Purpose

Observe what CKM consumers actually ask, including unsupported historical questions, without storing sensitive payloads or treating demand as authorization for new capability.

## What This Task Does

- Define a privacy-safe, versioned outer observation adapter for already-returned supported results, typed refusals, and explicitly accepted questions.
- Record bounded structural facts such as resource/query family, filter classes, result/refusal kind, truncation, latency bucket, contract versions, and snapshot/query digests without raw free text or resource payloads.
- Persist through the BuilderOps-local adjacent observation store; Product/runtime OEF outbox, topic, worker, retry, and dead-letter paths are inapplicable.
- Produce evidence that can support a future PromotionIntent or bounded issue, never direct feature activation.
- Apply the accepted 365-day retention/correction/deletion policy to every observation record, bind its policy version, expose retained count/bytes, and support previewed explicit operator pruning.

## Concretely

After the query service returns an immutable result or typed refusal, the calling orchestration layer may pass a redacted observation input to the separate BuilderOps-local outer adapter. The query service, DTO layer, SQLite connection, and read transaction never depend on or invoke the adapter. Observation success or failure cannot change the already-returned query outcome. Unsupported historical requests are classified by typed refusal; any human-accepted question records source authority separately from the raw demand signal.

## Why This Matters

The architecture inquiry deliberately refused to guess M2 history or O2 product features. Safe observation lets real questions guide later contracts while avoiding raw-query leakage, accidental telemetry authority, or automatic expansion of CKM scope.

## Acceptance Criteria

- [ ] The event schema is versioned, BuilderOps-scoped, privacy-safe by construction, and excludes raw query text, note content, names, paths, citations, and resource payloads.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_query_observation_schema_excludes_sensitive_payloads`
- [ ] Supported results, typed refusals, unsupported historical requests, and accepted questions remain distinct event kinds with explicit contract/resource versions.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_supported_refused_and_accepted_question_events_are_distinct`
- [ ] Observation includes canonical query and snapshot digests where available, bounded filter/result metadata, truncation, and coarse performance data without enabling replay of sensitive input.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_observation_is_bounded_bound_and_non_replayable`
- [ ] The query service/store/DTO modules have no event-recorder dependency or callback; observation begins only in an outer adapter after a complete immutable result/refusal exists.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_observation_runs_only_after_query_path_returns`
- [ ] The outer observation adapter cannot mutate CKM state/revision, GitHub, repo, Product/Runtime authority, or trigger a feature, ranking, gate, alert, or promotion automatically.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_observation_has_no_authority_or_ckm_side_effect`
- [ ] Observation validation or SQLite persistence failure returns a typed BuilderOps observation error, rolls back its adjacent-store transaction, and cannot corrupt, replace, or semantically change the already-returned query result/refusal.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_observation_failure_preserves_returned_query_semantics`
- [ ] An accepted historical question records its human/source authority and remains insufficient by itself to claim general history support.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_accepted_question_records_authority_without_enabling_history`
- [ ] Every retained observation records the 365-day policy version; storage count/bytes are inspectable, expiry never occurs before 365 days without explicit operator action, and earlier pruning has a preview plus a non-content deletion marker.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_observation_retention_requires_accepted_policy`
- [ ] Observation corrections append a superseding record; required deletion removes payload content while preserving a non-content lifecycle marker, and deleted material cannot be replayed as if still available.
  Verify: `tests/builderops/ckm/test_observation_capture.py::test_observation_correction_and_deletion_preserve_lifecycle_truth`
- [ ] The owner spec records observed question categories while keeping M2 and O2 unfiled until a new source-backed executable contract exists.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Observation-gated future work`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_observation_capture.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Inspect representative event JSON for privacy exclusions and authority markers.

## Out of Scope

- Raw query logging, payload/citation capture, or user analytics.
- Event hooks, callbacks, receipt emission, or write dependencies inside the query service/read transaction.
- M2 general history, as-of reconstruction, or retroactive provenance.
- O2 UI, alerts, drift, prediction, automation, federation, or automatic issue creation.
- Choosing cadence/window/minimum evidence thresholds before observation.

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`

## Related GitHub Issues

Implementation issue #3780 was terminally delivered by PR #4060 beneath open, blocked validation parent #3775. Its reconciled contract explicitly excludes the Product/runtime OEF event path in favor of the BuilderOps-local adjacent observation store. TCD hint: Terra/high; escalate for privacy, authority, retention, or observation-failure ambiguity.
