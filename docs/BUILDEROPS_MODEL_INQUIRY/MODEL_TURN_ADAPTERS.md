---
name: Model Turn Adapters
description: Execute structured Fable and GPT/Codex turns through explicit adapters and bounded review rounds.
task_id: BMI-03
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: BuilderOps Model Inquiry
prerequisites: [BMI-02]
depends_on: [PRE_TICKET_INQUIRY_RECORDS.md]
can_parallelize_with: []
---

# Model Turn Adapters

## Purpose

Make model interaction executable without relying on copy-paste or desktop-window automation.

## What This Task Does

Define one structured response contract and adapter boundary. Support configured OpenAI/Anthropic
API adapters or explicitly configured local commands. Run independent drafts before cross-review,
limit adversarial rounds, and persist provider request IDs and output hashes.

## Concretely

```bash
scripts/builderops_cli.sh builderops inquiry run inq_20260709_example --dry-run --json
scripts/builderops_cli.sh builderops inquiry run inq_20260709_example --max-rounds 5 --json
```

## Why This Matters

Direct desktop-app control is brittle and opaque. A provider adapter makes failure, retry, costs,
and audit evidence explicit.

## Acceptance Criteria

- [ ] Independent Fable and GPT/Codex drafts receive the same immutable initial context packet.
  Verify: `tests/builderops/test_model_inquiry_runner.py::test_independent_drafts_share_context_hash`.
- [ ] A review turn can only consume persisted input artifacts and emits schema-valid output.
  Verify: `tests/builderops/test_model_inquiry_runner.py::test_review_turn_uses_persisted_inputs_and_validates_output`.
- [ ] Every persisted provider turn retains its provider request ID and output hash, and trace output
  returns both values. Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_includes_provider_request_id_and_output_hash`.
- [ ] The runner terminates at consensus, maximum rounds, provider refusal, or malformed output.
  Verify: `tests/builderops/test_model_inquiry_runner.py::test_runner_records_all_terminal_conditions`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_model_inquiry_runner.py`
- `scripts/builderops_cli.sh builderops inquiry run <fixture-run> --dry-run --json`

## Out of Scope

- silent fallback from one provider to another;
- direct automation of a desktop UI;
- external browsing or product/runtime writes.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3291](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3291)
