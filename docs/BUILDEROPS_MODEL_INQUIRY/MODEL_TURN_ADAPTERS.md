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

The implementation uses a BuilderOps-only adapter boundary; it does not reuse Product/Runtime LLM
routing because that surface returns text without the required provider envelope and may select a
mock fallback. Role adapters are configured explicitly through the machine-local
`BUILDEROPS_INQUIRY_ADAPTERS_JSON` environment value. The shared vault stores only sanitized
identity, request IDs, hashes, structured output, and classified receipts.

Each role configuration must explicitly set matching `role_identity`, a non-mock provider, and a
distinct adapter ID plus runtime-target fingerprint. This is operator attestation, not proof that a
remote model is genuinely Fable; parent acceptance must retain provider-returned request evidence.
Example shape (credentials stay in the separately named local environment variable):

```json
{
  "fable": {
    "kind": "anthropic",
    "role_identity": "fable",
    "adapter_id": "fable-primary",
    "provider": "anthropic",
    "model": "configured-fable-model",
    "endpoint": "https://api.anthropic.com/v1/messages",
    "api_key_env": "LOCAL_FABLE_API_KEY"
  },
  "gpt_codex": {
    "kind": "openai",
    "role_identity": "gpt_codex",
    "adapter_id": "gpt-primary",
    "provider": "openai",
    "model": "configured-gpt-model",
    "endpoint": "https://api.openai.com/v1/chat/completions",
    "api_key_env": "LOCAL_OPENAI_API_KEY"
  }
}
```

A configured remote subscription host may provide local command adapters for both roles. Its
versioned profile uses explicit `xhigh` reasoning effort for Fable and GPT/Codex, a 540-second
inner command deadline, and a 600-second host adapter deadline. Credentials, subscription sessions,
and host-specific executable paths remain outside Git. It never substitutes Codex, Claude,
Anthropic, OpenAI, mock, or the deterministic dry-run planner for a missing Fable role.

## Concretely

```bash
scripts/builderops_cli.sh builderops inquiry run inq_20260709_example --dry-run --json
scripts/builderops_cli.sh builderops inquiry run inq_20260709_example --max-rounds 5 --json
```

## Why This Matters

Direct desktop-app control is brittle and opaque. A provider adapter makes failure, retry, costs,
and audit evidence explicit.

## Acceptance Criteria

- [x] Independent Fable and GPT/Codex drafts receive the same immutable initial context packet.
  Verify: `tests/builderops/test_model_inquiry_runner.py::test_independent_drafts_share_context_hash`.
- [x] A review turn can only consume persisted input artifacts and emits schema-valid output.
  Verify: `tests/builderops/test_model_inquiry_runner.py::test_review_turn_uses_persisted_inputs_and_validates_output`.
- [x] Every persisted provider turn retains its adapter request ID, nullable real provider request
  ID, request/input/context/output hashes, and adapter/provider/model identity, and trace output
  returns both values. Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_includes_provider_request_id_and_output_hash`.
- [x] The runner durably terminates at consensus, maximum rounds, provider refusal, malformed
  output, unavailable provider, provider error, or persistence failure.
  Verify: `tests/builderops/test_model_inquiry_runner.py::test_runner_records_all_terminal_conditions`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_model_inquiry_runner.py`
- `pytest -q tests/builderops/test_model_inquiry_adapters.py`
- `scripts/builderops_cli.sh builderops inquiry run <fixture-run> --dry-run --json`

## Response And Consensus Contract

Provider output must be exactly one `builderops.model-turn-response.v1` JSON object. Extra or
missing fields fail validation. The object carries stance, content, claims, risks, blocking
questions, reviewed artifact refs, and an optional accepted artifact hash. Consensus exists only
when both reviewer roles explicitly accept the same prior persisted artifact hash.

Dry-run is a deterministic, read-only plan: it performs no adapter call and creates no vault or
receipt file. Provider-enabled execution serializes one runner per inquiry on the host, persists a
valid turn before any successor, and derives restart progress from deterministic turn IDs plus
terminal receipts.

Local commands receive canonical JSON on stdin with `shell=False`, an explicit environment
allowlist, a timeout, and an incremental output ceiling. Stderr is discarded rather than persisted.
On a command failure, receipts may retain only the allowlisted adapter ID, diagnostic class, and
numeric exit code when present. HTTP and command adapters reject output containing a configured
credential value. Raw provider errors, headers, argv, inherited environment, and credentials never
enter receipts or trace.

## Out of Scope

- silent fallback from one provider to another;
- direct automation of a desktop UI;
- external browsing or product/runtime writes.
- provider-enabled parent acceptance without an explicitly configured Fable adapter.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3291](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3291)
