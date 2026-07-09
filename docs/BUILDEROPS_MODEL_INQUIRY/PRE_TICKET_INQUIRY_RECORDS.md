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

- [ ] Start creates an inquiry root plus immutable question artifact before provider execution.
  Verify: `tests/builderops/test_model_inquiry_cli.py::test_start_persists_question_before_provider_call`.
- [ ] Trace output returns the question, ordered turns, synthesis, readiness result, and source refs.
  Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_links_question_turns_and_synthesis`.
- [ ] Resume does not repeat a turn that already has a persisted terminal receipt.
  Verify: `tests/builderops/test_model_inquiry_resume.py::test_resume_skips_committed_turn`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_model_inquiry_cli.py tests/builderops/test_model_inquiry_trace.py tests/builderops/test_model_inquiry_resume.py`

## Out of Scope

- provider-specific model calls;
- GitHub Issue creation;
- desktop-app packaging.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3290](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3290)
