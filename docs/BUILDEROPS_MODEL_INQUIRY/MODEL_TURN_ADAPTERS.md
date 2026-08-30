---
name: Model Turn Adapters
description: Execute structured neutral Model Inquiry perspectives through one configured Sol target.
task_id: BMI-03
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: BuilderOps Model Inquiry
prerequisites: [BMI-02]
depends_on: [PRE_TICKET_INQUIRY_RECORDS.md]
can_parallelize_with: []
---

State: Implemented. Model Inquiry is permanently configured as explicit
`single_target` acceptance over the `sol` Builder capability. The concrete provider/model remains
declared in `docs/settings/models/providers.yaml`; inquiry intent and perspective code never choose
that concrete target. The host-local subscription session is the sanctioned operational auth path.

# Model Turn Adapters

## Purpose

Make model interaction executable without copy-paste or desktop-window automation while keeping
provider/model selection in the Builder Model Access resolver.

## Contract

The caller supplies `BUILDEROPS_INQUIRY_ROLE_INTENT_JSON`, a provider-free document containing the
runtime, channel, consumer, explicit `single_target` acceptance mode, `sol` capability, ordered
neutral perspectives (`synthesis`, `verification`), and the neutral turn intent. It contains no
provider, model, endpoint, credential, command, or host field. The committed example is
`config/builderops/model_inquiry_role_intent.example.json`.

`app/builderops/model_access_resolver.py` resolves that intent once through the exact Builder
provider census and host-secret contract. It selects provider, model, effective identity, endpoint,
and logical credential identifier from declared sources, verifies capabilities, and injects the
credential only at the transport boundary. The API adapter and the subscription bridge receive the
same resolved target; neither performs a second target selection.

The census binds Model Inquiry to the configured `sol` execution profile and declares the compatible
`codex_subscription` operational transport in every Builder channel. The model ID may therefore
change in configuration without changing this workflow, its perspectives, or its acceptance
semantics; an incompatible transport is rejected before execution. General capability routing and
any other Builder hard-coded model references remain governed by parent Issue #5177 and are outside
this BMI slice.

## Single-target execution

The runner creates a draft and a review turn for each neutral perspective. Both perspectives receive
the same immutable initial context and the same persisted input artifacts. If both explicitly accept
the same artifact hash, the runner writes a `single_target_acceptance` terminal receipt containing:

- `acceptance_mode: single_target`;
- `independence: false`;
- one effective adapter/provider/model identity and one target fingerprint;
- the shared context hash; and
- the synthesis artifact hash.

This outcome is deliberately distinct from `consensus`. It must never be inferred from equal target
fingerprints, a failed second adapter, or a fallback. A provider failure, malformed output, refusal,
missing credential, or persistence failure remains a typed terminal failure and cannot be promoted.

The operational subscription bridge is the declared `codex_subscription` transport for the current
Sol capability. It receives the resolver-selected model and never selects another provider/model.
Active v2 single-target execution does not use a second same-identity adapter as fallback; a
provider/command failure is terminal for that target. Legacy v1 records remain readable and
deterministic, but legacy execution is not reactivated through the permanent Sol path. The desktop
launcher invokes the host-local launcher once; it does not retry the inquiry.

## Credentials and host boundary

Credentials are resolved through `config/secrets/host_secret_contract.json` and the mode-0600 runtime
surface materialized by `app/ops/host_secret_bootstrap.py`. No adapter reads a caller-supplied key,
ambient credential environment variable, or credential value from durable inquiry state. Missing or
malformed credentials produce a sanitized logical-identifier diagnostic only.

The provider-API launcher remains a versioned dormant mechanism for an explicitly provisioned future
path. Operational desktop skills use the sanctioned subscription bridge and never invoke that
provider-API launcher. The subscription exception is Model Inquiry-only and cannot be used as CKM
semantic-association fallback.

## Host role-entrypoint lifecycle

The repository-owned installer and host launchers remain governed by their existing contracts. The
launcher supplies the resolved model to `scripts/model_inquiry_subscription_adapter.py`; the bridge
accepts neutral perspective names and has no role-specific provider/model branch. Host credentials,
subscription-session state, and launcher paths stay outside Git.
The dormant provider-API installer exposes only the neutral
`synthesis-model-inquiry-role` and `verification-model-inquiry-role` commands. Retired
provider-named command aliases are rejected and block a clean installer readback until an operator
removes the stale entrypoint explicitly; they are never mapped into the active target.

## Concretely

```bash
scripts/builderops_cli.sh builderops inquiry start \
  --question-file question.md \
  --workflow governed-model-inquiry \
  --acceptance-mode single_target --json
scripts/builderops_cli.sh builderops inquiry run <inquiry-id> --dry-run --json
scripts/builderops_cli.sh builderops inquiry run <inquiry-id> --max-rounds 5 --json
```

## Acceptance Criteria

- [x] Neutral perspectives receive the same immutable initial context and persist accepted input
  artifacts before synthesis. Verify:
  `tests/builderops/test_model_inquiry_runner.py::test_single_target_acceptance_is_truthful_and_receipted`.
- [x] A review turn can only consume persisted input artifacts and emits schema-valid output. Verify:
  `tests/builderops/test_model_inquiry_runner.py::test_review_turn_uses_persisted_inputs_and_validates_output`.
- [x] Every persisted provider turn retains its adapter request ID, nullable real provider request
  ID, request/input/context/output hashes, and adapter/provider/model identity. Verify:
  `tests/builderops/test_model_inquiry_trace.py::test_trace_includes_provider_request_id_and_output_hash`.
- [x] The runner durably terminates at acceptance, maximum rounds, provider refusal, malformed
  output, unavailable provider, provider error, or persistence failure. Verify:
  `tests/builderops/test_model_inquiry_runner.py::test_runner_records_all_terminal_conditions`.
- [x] The configured Sol capability is resolved once and shared by API and subscription adapters;
  inquiry code contains no concrete target selection. Verify:
  `tests/settings/test_provider_census.py::test_model_inquiry_profiles_bind_configured_capability`
  and `tests/builderops/test_model_inquiry_adapters.py::test_model_inquiry_has_no_hardcoded_target_selection`.

## Response contract

Provider output must be exactly one `builderops.model-turn-response.v1` JSON object. Extra or missing
fields fail validation. A single-target acceptance requires both neutral perspectives to explicitly
accept the same prior persisted artifact hash. Readiness and promotion receipts bind the terminal,
synthesis, readiness, and promotion hashes so a partial or substituted graph cannot be promoted.

Dry-run is deterministic and read-only: it performs no adapter call and creates no vault or receipt
file. Provider-enabled execution serializes one runner per inquiry, persists a valid turn before any
successor, and derives restart progress from deterministic turn IDs plus terminal receipts.

## How to Verify (Pre-Merge)

```bash
pytest -q tests/builderops/test_model_inquiry_runner.py
pytest -q tests/builderops/test_model_inquiry_adapters.py
pytest -q tests/builderops/test_model_inquiry_promotion.py
pytest -q tests/settings/test_provider_census.py
scripts/builderops_cli.sh builderops inquiry run <fixture-run> --dry-run --json
```
