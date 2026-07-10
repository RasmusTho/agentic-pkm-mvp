---
name: Pre-Ticket Inquiry Records
description: Persist pre-ticket questions, turns, synthesis, and restart-safe traceability.
task_id: BMI-02
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Scope
parent_capability: BuilderOps Model Inquiry
prerequisites: [BMI-01]
depends_on: [EXTERNAL_BUILDEROPS_VAULT_CONFIGURATION.md]
can_parallelize_with: []
---

# Pre-Ticket Inquiry Records

## Purpose

Create a BuilderOps-native run model before a question becomes executable backlog work.

## What This Task Does

Add a pre-ticket inquiry service, persisted artifacts, a `builderops inquiry start` command, resume
support, and trace output. Reuse the BuilderOps record envelope and source refs; do not create a
GitHub Issue during start or resume.

## Concretely

```bash
scripts/builderops_cli.sh builderops inquiry start --question-file question.md --workflow fable-gpt-architecture --json
scripts/builderops_cli.sh builderops inquiry trace inq_20260709_example --json
scripts/builderops_cli.sh builderops inquiry resume inq_20260709_example --json
```

## Why This Matters

The conversation cannot be the only state. Restarting either desktop app must not erase model inputs,
accepted turns, or the distinction between evidence and candidate conclusions.

## Acceptance Criteria

- [x] Start creates an inquiry root plus immutable question artifact and start receipt before any
  successor callback can execute.
  Verify: `tests/builderops/test_model_inquiry_cli.py::test_start_persists_question_before_provider_call`.
- [x] Equal retries are idempotent while conflicting rewrites of committed artifacts fail closed.
  Verify: `tests/builderops/test_model_inquiry_cli.py::test_inquiry_artifacts_are_immutable_and_idempotent`.
- [x] Trace output returns the question, ordered turns, synthesis, readiness result, receipts, and
  source refs, and rejects an incomplete start record.
  Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_links_question_turns_and_synthesis`.
- [x] Resume returns a plan and does not repeat a turn that already has a matching persisted
  terminal receipt.
  Verify: `tests/builderops/test_model_inquiry_resume.py::test_resume_skips_committed_turn`.
- [x] HTTP start, trace, and resume use the same service as the CLI and perform no provider or
  GitHub side effect.
  Verify: `tests/api/test_builderops_inquiry_api.py::test_inquiry_api_start_trace_resume`.

## Implemented Record Layout

Records are file-first under
`$BUILDEROPS_VAULT_ROOT/model-inquiries/<inquiry_id>/`:

- `question.json` and `manifest.json` establish the inquiry and its creation receipt;
- `turns/<sequence>.json` atomically reserves each ordered immutable turn slot;
- `turn-ids/<turn_id>.json` separately reserves each immutable turn identity;
- `synthesis.json` and `readiness.json` store optional derived artifacts;
- `receipts/*.json` stores canonical `BuilderOpsReceipt` envelopes.

Writes use same-directory temporary files and no-overwrite links, so readers do not observe a
partially serialized committed artifact. The manifest is the inquiry commit marker. Trace validates
content hashes, input-artifact edges, sequence ordering, and the start receipt before returning a
complete graph. Resume is deliberately planning-only in BMI-02; provider execution belongs to
BMI-03.

Each question, turn, synthesis, and readiness record also carries a canonical `artifact_hash` over
its identifiers, content hash, provenance, input edges, actor/workflow fields, and creation time.
Receipts and the manifest bind those hashes, so changing lineage fields without changing content
still invalidates the trace.

The no-overwrite sequence pathname prevents two local writers from committing different turns to
the same successor slot; the independent ID reservation prevents one turn identity from being
committed at two sequences. A per-inquiry OS file lock plus an in-process lock serializes
reservation, turn commit, and losing-reservation cleanup across CLI/API processes on the same host.
Cross-device iCloud
claim and locking semantics remain advisory as defined by BMI-01; if independently synchronized
devices still introduce a conflicting graph, trace fails closed instead of choosing a winner.
An orphaned reservation from process loss makes trace incomplete until an exact turn retry
reconciles it.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_model_inquiry_cli.py tests/builderops/test_model_inquiry_trace.py tests/builderops/test_model_inquiry_resume.py tests/api/test_builderops_inquiry_api.py`

## Out of Scope

- provider-specific model calls;
- GitHub Issue creation;
- desktop-app packaging.

Local SQLite remains outside the shared vault and is not used as the durable authority for these
records. BMI-02 does not add new BuilderOps SQLite object types; it reuses the existing SourceRef,
actor, and `BuilderOpsReceipt` envelope contracts for shared inquiry artifacts.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3290](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3290)
