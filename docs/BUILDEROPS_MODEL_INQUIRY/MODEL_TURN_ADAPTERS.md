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

Define one structured response contract and adapter boundary. Resolve both role adapters through the
declared Model Access substrate, run independent drafts before cross-review, limit adversarial
rounds, and persist provider request IDs and output hashes.

The implementation uses a BuilderOps-only adapter boundary; it does not reuse Product/Runtime LLM
routing because that surface returns text without the required provider envelope and may select a
mock fallback. Since MAS-05 (ADR-0064), **the caller declares intent and resolves nothing itself**:

- The caller supplies `BUILDEROPS_INQUIRY_ROLE_INTENT_JSON`, a value-free document carrying the seven
  neutral intent fields per role, the role independence requirement, and channel/consumer references.
  It carries no provider, model, endpoint, credential value, environment-variable name, or host
  identifier. The committed example is
  `config/builderops/model_inquiry_role_intent.example.json`.
- The Builder resolver (`app/builderops/model_access_resolver.py`) applies Builder policy, selects
  provider, model, effective identity, and API endpoint from the exact declared provider census
  (`docs/settings/models/providers.yaml`), verifies the census-required capabilities, and verifies
  distinct effective targets for the `model-inquiry-independent-review` group through the neutral
  kernel before any model call.
- The resolver enforces every neutral intent field for this capability: the census-selected
  `frontier` tier, exact `xhigh` reasoning effort, non-deterministic execution, the
  `builderops.model-turn-response.v1` output schema, distinct-effective-target independence,
  forbidden fallback, and advisory-review-only side effects. Unsupported intent is refused before
  adapter creation. The provider adapter carries that validated intent forward and sends explicit
  `xhigh` effort in both provider request shapes.
- **Credentials are resolved through the host secret contract, not through a machine-local
  environment value.** The resolver maps each role to its declared logical identifier
  (`anthropic.api-key`, `gpt_codex` → `openai.api-key`) via
  `config/secrets/host_secret_contract.json`, and reads the value only from the mode-0600 runtime
  surface that `app/ops/host_secret_bootstrap.py` materializes. No role adapter reads a provider key
  from adapter configuration or from ambient process environment.
- The fixed desktop launcher and installed role wrappers invoke
  `run_with_host_secrets(channel="dev", consumer="builderops-model-inquiry", ...)` before the
  provider path starts. The consumer accepts only an absolute, owner-owned, single-link regular file
  with exact mode `0600`, opened without following its final path component.
- A declared credential that is absent or malformed produces the typed `credential_unavailable`
  failure class, fails the run closed before any adapter call, names only the logical identifier, and
  never falls back to a subscription CLI, ambient environment, or another provider. An expired
  session on the still-permitted interactive command path produces `session_expired`. Neither
  collapses into `command_exit_nonzero`.

Role identity remains attested: each role resolves to a distinct `adapter_id` and a distinct
runtime-target fingerprint, and a mock, fake, or deterministic identity is refused as a
provider-enabled role. This is declared policy, not proof that a remote model is genuinely Fable;
parent acceptance must retain provider-returned request evidence. The shared vault stores only
sanitized identity, request IDs, hashes, structured output, and classified receipts.

`scripts/model_inquiry_subscription_adapter.py` remains for interactive, human-driven use. Its
versioned profile uses explicit `xhigh` reasoning effort for Fable and GPT/Codex, a 1200-second inner
command deadline, and a 1500-second host adapter deadline. It is not reachable from any headless
entrypoint: the inquiry-role intent surface cannot select a command transport, and the host installer
does not install it.

## Host role-entrypoint lifecycle

The repository owns the two stable headless command names: `fable-model-inquiry-role` and
`codex-model-inquiry-role`. Run `scripts/install_model_inquiry_host.py install` to create owner-only
executable wrappers in an explicit host bin directory. Each wrapper binds exactly one role to the
versioned `scripts/model_inquiry_role_adapter.py` through the host-secret bootstrap, which resolves a
declared credential rather than an interactive session; an exact reinstall is a no-op, while a
symlink, unsafe directory, or unrelated existing command fails closed without overwriting it.

The companion `check` operation is read-only. It reports only whether both installed entrypoints
match the adapter digest committed into the installer in its own operator-authoritative checkout
and Python interpreter, whether the launch `PATH` resolves both names to those exact files, and
whether the host launcher command is discoverable. It probes no provider CLI, because no headless
entrypoint depends on one. Host-time validation does not invoke Git; an adapter change and its
installer digest update are one repo change. The check does not run either provider, inspect
subscription state, reveal paths, or create inquiry artifacts.

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

Local commands on the interactive path receive canonical JSON on stdin with `shell=False`, an
explicit environment allowlist, a timeout, and an incremental output ceiling. Stderr is discarded
rather than persisted. On a failure, receipts may retain only the allowlisted adapter ID, diagnostic
class, the numeric exit code when present, and — for `credential_unavailable` — the declared logical
credential identifier. HTTP and command adapters reject output containing a configured credential
value. Raw provider errors, headers, argv, inherited environment, and credential values never enter
receipts or trace.

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
