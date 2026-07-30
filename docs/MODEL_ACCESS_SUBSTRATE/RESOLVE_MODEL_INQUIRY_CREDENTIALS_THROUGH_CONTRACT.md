---
name: Resolve Model Inquiry Credentials Through Contract
description: Preserve the delivered declared-credential provider mechanism while the sanctioned host-local Model Inquiry path remains subscription-backed under the owner cost ruling.
task_id: MAS-05
source_anchor: docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration (step 4)
parent_capability: Model Access Substrate
prerequisites: [MAS-04]
depends_on: [PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL.md]
can_parallelize_with: []
---

State: Implemented. Delivered by repair PR #4392 (issue #4291, 2026-07-30) and repaired again by PR
#4410 (issue #4291, 2026-07-30), which bound the fixed host launcher to repo-owned
declared-credential lineage and rejected a discoverable-but-stale subscription launcher. **This is
the first task in the capability that changes runtime behaviour.** **Owner ruling 2026-07-30
(cost):** the live provider run and legacy-bridge retirement are withdrawn from parent validation —
metered provider API keys are not provisioned, the declared identifiers stay intentionally
unprovisioned, and the subscription-backed session remains the sanctioned operational auth on the
inquiry host (`docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner cost
ruling on the model-inquiry path`). The delivered code stays merged as the required mechanism for
any future metered path. The owner has declined credential provisioning, so it is not a pending
prerequisite.

# Resolve Model Inquiry Credentials Through Contract

## Purpose

This task historically addressed the reported failure with a versioned declared-credential
provider-API mechanism. A model inquiry run failed
with `final_state: provider_error` and `adapter_failure_class: command_exit_nonzero` because a
subscription CLI over a fresh non-interactive session cannot reach the login keychain of the configured
inquiry host, while the same command inside that host's GUI-session pane succeeds. ADR-0064 §4 rules
that declared API keys are the default programmatic auth path. ADR-0064's 2026-07-30 amendment is the
later and controlling operational ruling: metered keys remain intentionally unprovisioned and the
existing subscription session is sanctioned only for host-local Builder Model Inquiry. Therefore
the mechanism below is retained for a possible future metered path, not promoted as current host
authentication and not a parent-acceptance gate.

Model inquiry is chosen as the first beneficiary because it is the smaller, already-adapter-shaped
consumer: `HttpModelAdapter` (`app/builderops/model_inquiry_adapters.py:175-278`) is fully implemented
for both Anthropic and OpenAI, including credential scrubbing on output and on the returned request id,
and is unexercised. Switching to it is a configuration and resolution change, not a new transport.

## What this task does

1. Implement a Builder-owned `ModelAccessResolver` behind the neutral protocol. It accepts the two
   neutral role-profile requests as one `model-inquiry-independent-review` group with
   `(runtime="builder", channel, consumer)`, applies Builder policy, resolves exclusively through the
   exact MAS-01 role/tier mappings, verifies capabilities and distinct effective targets, and resolves
   credential identities through the host-secret contract. Provider/model are outputs, never caller
   fields.
2. Resolve each role adapter's credential through that resolver at descriptor-load time.
   `HttpModelAdapter` takes `api_key` as an injected field and reads no environment itself, so
   `load_adapter_descriptors` no longer accepts provider/model/`api_key_env` from inquiry caller
   configuration or ambient environment.
3. Preserve distinct installed provider-API entrypoints. The host installer owns the dormant
   `yggdrasil-model-inquiry-provider-api` launcher plus both role wrappers and pins their repo
   launcher/adapter content. It does not install, inspect, overwrite, or retire the sanctioned
   `yggdrasil-model-inquiry` subscription launcher. Both `xhigh` provider-API roles retain the
   extended 1200-second per-role request deadline.
4. Replace the provider-bearing `BUILDEROPS_INQUIRY_ADAPTERS_JSON` mechanism with a value-free
   inquiry-role intent configuration. The committed example contains the seven neutral intent fields,
   role independence requirement, channel/consumer references, and no provider, model, credential
   value, environment-variable name, host path, or host identifier.
5. Emit the real failure class. A declared credential that is absent or unusable produces
   `credential_unavailable`, and an expired session on a still-permitted interactive path produces
   `session_expired`, instead of both collapsing into `command_exit_nonzero`. The canonical launcher
   must preserve that typed outcome even when host bootstrap fails before the runner starts: it
   hands the runner only the declared logical credential identifier, with no credential bindings,
   so the durable terminal receipt is written before any adapter or fallback path can run. The
   dormant provider-API launcher returns that complete JSON receipt with exit status 1 for direct
   mechanism callers. Operational desktop skills do not invoke that launcher; they use the
   sanctioned subscription launcher and treat every nonzero result as ambiguous.
6. Keep `scripts/model_inquiry_subscription_adapter.py` as the sanctioned operational auth path for
   host-local Builder Model Inquiry. It remains unreachable from the dormant provider-API launcher
   and from CKM.

## Concretely

The commands below document the dormant mechanism's contract shape. They are not the current
operational path or an instruction to provision credentials or run a provider under the owner-cost
ruling.

```
# on the configured inquiry host, over a fresh non-interactive session:
$ ssh <configured inquiry host> 'yggdrasil-model-inquiry-provider-api --inquiry <id> --json'
{"final_state": "completed", "rounds": 2, "roles": {
   "fable":     {"provider": "anthropic", "provider_request_id": "req_...", "adapter_id": "fable-primary"},
   "gpt_codex": {"provider": "openai",    "provider_request_id": "resp_...", "adapter_id": "codex-primary"}}}

# with the declared credential absent from the Keychain:
$ ssh <configured inquiry host> 'yggdrasil-model-inquiry-provider-api --inquiry <id> --json'
{"final_state": "provider_error", "adapter_failure_class": "credential_unavailable",
 "detail": "openai.api-key"}
$ echo $?
1
```

The second case is the point. It fails closed, names only the logical identifier, and does not fall
back to the subscription CLI.

## Why this matters

This is at least the second keychain-over-a-non-interactive-session incident in this system, and the
first one was patched by hand-building a TLS bridge in a GUI login session for one provider — a bridge
that is not in version control, whose argv allowlist is a second uncommitted copy of a profile already
defined in Git, and whose `CLAUDE_PATH` points at a version-pinned symlink that a routine tool update
breaks. Patching the second provider the same way would double that surface. Resolving both through one
declared-credential contract removes the failure class instead of relocating it.

It does not establish current provider reachability. Under the owner-cost ruling, parent acceptance
is repo-verifiable and the dormant mechanism's expected current result is
`credential_unavailable`; no provider run, bridge-retirement proof, or credential provisioning is
required.

## Acceptance criteria

- [ ] Role adapter credentials are resolved through the host secret contract, and no role adapter reads
      a provider key from the descriptor JSON or from ambient process environment.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_role_credentials_resolve_through_the_host_secret_contract`
- [ ] The production Model Inquiry call site submits only provider-free intent and the Builder
      resolver selects provider/model from the census runtime/channel mapping after capability checks.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_production_inquiry_resolves_provider_free_intent_through_builder_census`
- [ ] The production two-role call resolves the neutral `fable` and `gpt_codex` role profiles as one
      independent group with distinct effective targets; a colliding policy mapping fails before any
      model call.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_production_inquiry_resolves_distinct_effective_targets_for_role_group`
- [ ] No installed provider-API entrypoint requires or occupies the sanctioned subscription
      launcher's identity, asserted where the installer builds its distinct dormant entrypoints.
      Verify: `tests/governance/test_model_inquiry_host_install.py::test_headless_entrypoints_do_not_require_subscription_session`
      — the test drives `scripts/install_model_inquiry_host.py`'s installation path and asserts the
      produced role entrypoints resolve credentials rather than a CLI session.
- [ ] Production provider-API adapters retain the extended `xhigh` per-role request deadline.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_production_http_adapters_use_extended_xhigh_deadline`
- [ ] A declared credential that is absent or malformed produces `credential_unavailable`, fails the
      run closed, names only the logical identifier, and does not fall back to a subscription CLI, to
      ambient environment, or to any other provider.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_absent_credential_fails_closed_as_credential_unavailable`
      Verify: `tests/governance/test_start_model_inquiry_skill.py::test_launcher_fails_closed_on_an_absent_declared_credential`
- [ ] The two roles still require distinct `adapter_id` values and distinct runtime-target
      fingerprints, and a configuration that collapses them is refused.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_provider_enabled_roles_require_distinct_non_mock_attestation`
- [ ] A mock, fake, or deterministic identity is still refused as a provider-enabled role, and dry-run
      still performs no adapter call and creates no vault or receipt file.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_dry_run_performs_no_adapter_call_and_writes_nothing`
- [ ] No credential value appears in any receipt, trace, error message, or returned request id.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_local_command_adapter_is_bounded_and_secret_safe`
      Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_never_contains_credential_material`
- [ ] A committed inquiry-role intent example is value-free, provider-free, model-free, and
      host-identifier-free, and validates through the production resolver path.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_committed_inquiry_intent_config_is_provider_free_and_value_free`
- [x] ADR-0064's owner-cost amendment withdraws the provider-enabled inquiry, bridge-retirement, and
      credential-provisioning evidence from parent acceptance; this task creates no replacement
      provider or owner receipt.
      Verify: `docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner cost ruling on the model-inquiry path`
- [ ] `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md` describes credential resolution through the
      contract rather than through a machine-local environment value.
      Verify: `doc writeback at docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md :: What This Task Does`

## How to verify (pre-merge)

- `pytest -q tests/builderops/test_model_inquiry_adapters.py tests/builderops/test_model_inquiry_runner.py tests/builderops/test_model_inquiry_trace.py tests/builderops/test_model_inquiry_resume.py`
- `pytest -q tests/governance/test_model_inquiry_host_install.py tests/governance/test_start_model_inquiry_skill.py tests/architecture/test_agent_skill_entrypoints.py`
- `pytest -q -m "not pg"` — full unit lane; hot-path and auth-surface work
- `python3 scripts/public_seam_lint.py --mode gate` — the example config and any new docs must carry no
  host identifier
- `python3 scripts/docs_guard.py`
- Parent validation uses repository evidence under the amended ADR. Do not run a provider, provision
  a metered credential, retire the sanctioned subscription bridge, or create a replacement receipt.

## Cross-task invariants preserved

INV-MAS-2 (credentials only through the contract) is exercised for the first time here. INV-MAS-3 — the
auth failure classes are emitted and must survive the persistence-boundary re-validation. INV-MAS-4 —
role independence must hold with both roles now on HTTP transports. INV-MAS-5 — no cross-provider
fallback, no mock as provider, no silent degradation. Seam A is closed here on the model-inquiry side:
a declared identifier with no host value fails closed rather than reverting to the old path.

INV-MAS-6 no longer applies from this task onward; this is the intended first behaviour change.

## Out of scope

CKM's migration, which is MAS-06 and follows the delivered MAS-05 mechanism rather than a live
provider receipt. The verification closer's duplicated
model literals at `app/dispatcher/verification_consumer.py:2325-2341`, which is migration step 6. The
brokered-session backend, which ADR-0064 permits but does not build. Provisioning credential values,
which the owner has explicitly declined. Changing the response or consensus contract, the round limits, or the
independent-review requirements. Product resolver migration.

## Related docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md` — capability contract, Seam A
- `docs/adr/ADR-0064-model-access-substrate.md :: 4. Declared API keys are the default programmatic auth path`, `:: 7. Mechanism in Git, values host-local`
- `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md` — adapter boundary, attestation, response contract
- `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 10. Host opacity`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md` — host-local sessions remain the privileged Builder executor's
- `scripts/install_model_inquiry_host.py`, `scripts/model_inquiry_subscription_adapter.py`, `app/builderops/model_inquiry_adapters.py`

## Related GitHub issues

One issue. Title shape
`[Model Access Substrate] resolve-model-inquiry-credentials-through-contract: first beneficiary`.
Its `Context` records the original `provider_error` / `command_exit_nonzero` failure as historical
mechanism context. The 2026-07-30 owner ruling withdraws the live provider run,
credential-provisioning, and legacy-bridge retirement from parent acceptance.

TCD capability recommendation for the implementing agent: **Opus / xhigh reasoning** — auth,
external-API, and host-launcher work that carries the capability's first behaviour change and
mechanism contract; a wrong direction here is expensive and partly host-visible
(`AGENTS.md :: Total Cost of Development`). Non-binding; `issue-to-code` re-derives it.
