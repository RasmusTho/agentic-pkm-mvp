---
name: Resolve Model Inquiry Credentials Through Contract
description: Make BuilderOps Model Inquiry the first beneficiary of the substrate — adapters resolve declared credentials through the host secret contract, and no headless entrypoint depends on an interactive subscription session.
task_id: MAS-05
source_anchor: docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration (step 4)
parent_capability: Model Access Substrate
prerequisites: [MAS-03, MAS-04]
depends_on: [EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md, PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL.md]
can_parallelize_with: [REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER.md]
---

State: Authored task specification (future-state; child issue not yet filed). **This is the first task
in the capability that changes runtime behaviour.**

# Resolve Model Inquiry Credentials Through Contract

## Purpose

This is the reported failure, fixed as a consequence rather than patched. A model inquiry run failed
with `final_state: provider_error` and `adapter_failure_class: command_exit_nonzero` because a
subscription CLI over a fresh non-interactive session cannot reach the login keychain of the configured
inquiry host, while the same command inside that host's GUI-session pane succeeds. ADR-0064 §4 rules
that declared API keys are the default programmatic auth path and that subscription CLI sessions **must
not be a dependency of any headless path**.

Model inquiry is chosen as the first beneficiary because it is the smaller, already-adapter-shaped
consumer: `HttpModelAdapter` (`app/builderops/model_inquiry_adapters.py:175-278`) is fully implemented
for both Anthropic and OpenAI, including credential scrubbing on output and on the returned request id,
and is unexercised. Switching to it is a configuration and resolution change, not a new transport.

## What this task does

1. Resolve each role adapter's credential through the host secret contract at descriptor-load time.
   `HttpModelAdapter` takes `api_key` as an injected field and reads no environment itself, so the
   change is confined to where descriptors are built — `load_adapter_descriptors` in
   `app/builderops/model_inquiry_adapters.py` — which now asks
   `app/ops/host_secret_bootstrap.py` for the declared identifier for `(channel, consumer, provider)`
   instead of taking a key from the descriptor JSON or ambient environment.
2. Make the installed headless entrypoints use provider-API adapters.
   `scripts/install_model_inquiry_host.py:33-36` currently pins
   `RoleSpec("fable", "fable-subscription-cli", "claude")` and
   `RoleSpec("gpt_codex", "codex-subscription-cli", "codex")` — two subscription CLIs as the only
   installable headless roles. Headless role installation must no longer require a subscription
   session.
3. Commit an **example** `BUILDEROPS_INQUIRY_ADAPTERS_JSON` instance. It is today the only genuinely
   provider-neutral configuration surface in the Builder system and has no committed instance anywhere,
   not even an example. Per ADR-0064 §7 the mechanism is in Git; the example carries no credential
   value, no host path, and no host identifier.
4. Emit the real failure class. A declared credential that is absent or unusable produces
   `credential_unavailable`, and an expired session on a still-permitted interactive path produces
   `session_expired`, instead of both collapsing into `command_exit_nonzero`.
5. Keep `scripts/model_inquiry_subscription_adapter.py` for interactive, human-driven use. It must
   remain unreachable from any headless entrypoint.

## Concretely

```
# on the configured inquiry host, over a fresh non-interactive session:
$ ssh <configured inquiry host> 'yggdrasil-model-inquiry --inquiry <id> --json'
{"final_state": "completed", "rounds": 2, "roles": {
   "fable":     {"provider": "anthropic", "provider_request_id": "req_...", "adapter_id": "fable-primary"},
   "gpt_codex": {"provider": "openai",    "provider_request_id": "resp_...", "adapter_id": "codex-primary"}}}

# with the declared credential absent from the Keychain:
$ ssh <configured inquiry host> 'yggdrasil-model-inquiry --inquiry <id> --json'
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

It also unblocks CI reaching a provider for the first time, which is the argument that decided
ADR-0064's option analysis.

## Acceptance criteria

- [ ] Role adapter credentials are resolved through the host secret contract, and no role adapter reads
      a provider key from the descriptor JSON or from ambient process environment.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_role_credentials_resolve_through_the_host_secret_contract`
- [ ] No installed headless entrypoint requires an interactive subscription session, asserted where the
      installer actually builds its role entrypoints.
      Verify: `tests/governance/test_model_inquiry_host_install.py::test_headless_entrypoints_do_not_require_subscription_session`
      — the test drives `scripts/install_model_inquiry_host.py`'s installation path and asserts the
      produced role entrypoints resolve credentials rather than a CLI session.
- [ ] A declared credential that is absent or malformed produces `credential_unavailable`, fails the
      run closed, names only the logical identifier, and does not fall back to a subscription CLI, to
      ambient environment, or to any other provider.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_absent_credential_fails_closed_as_credential_unavailable`
- [ ] The two roles still require distinct `adapter_id` values and distinct runtime-target
      fingerprints, and a configuration that collapses them is refused.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_provider_enabled_roles_require_distinct_non_mock_attestation` (existing, unmodified)
- [ ] A mock, fake, or deterministic identity is still refused as a provider-enabled role, and dry-run
      still performs no adapter call and creates no vault or receipt file.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_dry_run_performs_no_adapter_call_and_writes_nothing`
- [ ] No credential value appears in any receipt, trace, error message, or returned request id.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_local_command_adapter_is_bounded_and_secret_safe` (existing, unmodified)
      Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_never_contains_credential_material`
- [ ] A committed example `BUILDEROPS_INQUIRY_ADAPTERS_JSON` exists, is value-free and host-identifier-free,
      and validates against the descriptor loader.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_committed_example_adapter_config_is_valid_and_value_free`
- [ ] A model inquiry completes over a fresh non-interactive session on the configured inquiry host,
      with a provider-returned request id in the persisted turn receipt for both roles.
      Verify: redacted operator receipt posted to the parent feature issue, compared against the
      `command_exit_nonzero` failure recorded in `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: Context`
- [ ] The hand-built per-provider TLS bridge and its version-pinned CLI symlink dependency are retired
      on the configured inquiry host.
      Verify: redacted operator receipt posted to the parent feature issue confirming the bridge's
      launch agent is unloaded and its directory removed
- [ ] `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md` describes credential resolution through the
      contract rather than through a machine-local environment value.
      Verify: doc writeback at `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md :: What This Task Does`

## How to verify (pre-merge)

- `pytest -q tests/builderops/test_model_inquiry_adapters.py tests/builderops/test_model_inquiry_runner.py tests/builderops/test_model_inquiry_trace.py tests/builderops/test_model_inquiry_resume.py`
- `pytest -q tests/governance/test_model_inquiry_host_install.py tests/governance/test_start_model_inquiry_skill.py tests/architecture/test_agent_skill_entrypoints.py`
- `pytest -q -m "not pg"` — full unit lane; hot-path and auth-surface work
- `python3 scripts/public_seam_lint.py --mode gate` — the example config and any new docs must carry no
  host identifier
- `python3 scripts/docs_guard.py`
- Operator, on the configured inquiry host: a fresh non-interactive session runs one real inquiry to
  completion; both operator receipts above are captured redacted and posted to the parent issue.

## Cross-task invariants preserved

INV-MAS-2 (credentials only through the contract) is exercised for the first time here. INV-MAS-3 — the
auth failure classes are emitted and must survive the persistence-boundary re-validation. INV-MAS-4 —
role independence must hold with both roles now on HTTP transports. INV-MAS-5 — no cross-provider
fallback, no mock as provider, no silent degradation. Seam A is closed here on the model-inquiry side:
a declared identifier with no host value fails closed rather than reverting to the old path.

INV-MAS-6 no longer applies from this task onward; this is the intended first behaviour change.

## Out of scope

CKM's migration, which is MAS-06 and is independent of this task. The verification closer's duplicated
model literals at `app/dispatcher/verification_consumer.py:2325-2341`, which is migration step 6. The
brokered-session backend, which ADR-0064 permits but does not build. Provisioning credential values,
which is an owner action. Changing the response or consensus contract, the round limits, or the
independent-review requirements. The provider-free intent shape — callers still name their adapter
after this task.

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
Its `Context` must name the original `provider_error` / `command_exit_nonzero` failure as the acceptance
target, and must state that the two operator receipts are part of acceptance and cannot be discharged by
tests. It stays `agent:blocked` until MAS-03 and MAS-04 merge.

TCD capability recommendation for the implementing agent: **Opus / xhigh reasoning** — auth,
external-API, and host-launcher work that carries the capability's first behaviour change and an
operator-verified receipt; a wrong direction here is expensive and partly host-visible
(`AGENTS.md :: Total Cost of Development`). Non-binding; `issue-to-code` re-derives it.
