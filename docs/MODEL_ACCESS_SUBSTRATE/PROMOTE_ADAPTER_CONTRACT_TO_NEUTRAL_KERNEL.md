---
name: Promote Adapter Contract To Neutral Kernel
description: Deliver neutral model intent, resolution, capability, adapter, result, failure, fallback, schema, and provenance contracts both runtimes may import.
task_id: MAS-04
source_anchor: docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration (step 3)
parent_capability: Model Access Substrate
prerequisites: [MAS-03]
depends_on: [EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md]
can_parallelize_with: []
---

State: Implemented. Delivered by PR #4360 (issue #4290, 2026-07-29). Establishes the ADR-0063
kernel in code for the first time; ADR-0063 deliberately chose no package path.

# Promote Adapter Contract To Neutral Kernel

## Purpose

ADR-0063 ratified a neutral LLM Contract Kernel in 2026-07 and nothing was ever built: no kernel module
exists, and its five fallback requirement values live only in ADR prose. ADR-0064 §1 resolves the
question of what goes in it first — `ModelTurnAdapter` is **promoted** to the execution-transport
protocol rather than a third contract being designed, because it is already proven against two
structurally different transports (HTTP JSON and subprocess-over-stdin).

This task creates the kernel with exactly the contracts that MAS-05 and MAS-06 consume, and adds the
two auth-specific failure classes whose absence is why the reported failure was uninformative:
`credential_unavailable` and `session_expired` today collapse into `command_exit_nonzero`.

## The package path decision

ADR-0063 `:185-186` explicitly declines to choose a package path, and ADR-0064 does not supply one. The
capability specification chooses top-level **`llm_contract/`**, with an `__init__.py` that re-exports
only neutral names.

The first implementation attempt placed the leaf at `app/llm_contract/`. Fresh-process proof showed
that this path is not neutral: Python executes `app/__init__.py` before any `app.*` child, and that
initializer imports `app.config.llm` and calls `ensure_provider()`. With
`LLM_PROVIDER_ENFORCE=1` and no `LLM_PROVIDER`, `import app.llm_contract` therefore fails before the
kernel loads. Making the parent initializer inert would change Product runtime behavior and is outside
this task. A top-level package avoids that parent-package side effect while remaining importable by
both runtimes.

`app/ports/` was also considered and rejected: `app/ports/__init__.py` already re-exports
`FilesystemVaultAdapter`, which imports `app.services.inbox` and `app.knowledge.write_ops`. Importing
anything from `app.ports` therefore executes that chain, which would make `app.builderops` depend on
Product execution — the exact authority direction this capability exists to correct. Any alternative
path must satisfy the same three constraints: importable by both `app.builderops` and
`app.components.llm` without violating ADR-0013's direction, no transitive import of either runtime's
policy or execution modules, and registered in `importlinter.ini` `source_modules`.

## What this task does

1. Create top-level `llm_contract/` containing, and containing only:
   - immutable `ModelAccessIntent` with exactly `capability_tier`, `reasoning_effort`,
     `determinism_required`, `output_schema_ref`, `independence`, `fallback_requirement`, and
     `side_effect_class`; it contains no provider, model, credential, endpoint, or adapter id;
   - `ModelResolutionRequest`, which combines an intent with a neutral `role_profile` and
     `resolution_group_id`, plus a batch `resolve_group(...)` protocol. When any request declares
     `independence=distinct_effective_target`, the resolved batch must contain distinct
     `(provider, model, effective_identity)` tuples. Role profiles select Builder policy rows; they
     do not contain provider/model choices;
   - `ModelCapabilityRequirements` and `ModelCapabilities` for structured output, native tools,
     system-prompt channel, determinism, and embedding dimension where relevant;
   - a `ModelAccessResolver` protocol whose singular input is
     `(ModelResolutionRequest, runtime, channel, consumer)` and whose grouped input is
     `(requests, runtime, channel, consumer)`. Its validated `ResolvedModelAccess` output carries
     provider/model/adapter/effective identity, capabilities, credential identity reference,
     degradation state/reason, resolution-group provenance, and no credential value. The neutral
     package defines the contract but owns no registry, policy, credential, or provider;
   - the `ModelTurnAdapter` protocol and its `AdapterResult` shape, moved from
     `app/builderops/model_inquiry_adapters.py:72-82`;
   - the closed failure-class vocabulary, moved from `:26-36`, **extended** with
     `credential_unavailable` and `session_expired`;
   - the five ADR-0063 fallback requirement values — `fallback_forbidden`,
     `fallback_same_identity`, `fallback_compatible_identity`, `fallback_policy_selected`,
     `human_decision_required` — as code for the first time, with no sixth value;
   - the schema-reference and schema-validation contract, so a Builder consumer can validate a
     structured response without importing `app.components.llm.constrained`. ADR-0063 `:81` places
     input/output schema references and schema validation in the kernel.
2. Keep `app/builderops/model_inquiry_adapters.py` at its current module path, re-exporting the moved
   names, so every existing importer and the existing test file keep working.
3. Extend the persistence-boundary re-validation
   (`app/builderops/model_inquiry.py:1977-2068`, `_validate_adapter_failure_diagnostic` at `:2050`) to
   read the kernel vocabulary rather than a second copy of the member list. **Both validations stay**
   — the adapter classifies, the persistence boundary independently re-validates. What is unified is
   the vocabulary, not the validation.
4. Register `llm_contract` in `importlinter.ini` `source_modules` and add an architecture test that
   the kernel imports nothing from `app.builderops`, `app.components`, `app.services`, `app.llm`, or
   any store.

## Concretely

```python
from llm_contract import (
    ADAPTER_FAILURE_CLASSES,
    FALLBACK_REQUIREMENTS,
    AdapterResult,
    ModelAccessIntent,
    ModelAccessResolver,
    ModelTurnAdapter,
)

assert "credential_unavailable" in ADAPTER_FAILURE_CLASSES
assert "session_expired" in ADAPTER_FAILURE_CLASSES
assert len(FALLBACK_REQUIREMENTS) == 5
```

```
$ pytest -q tests/builderops/test_model_inquiry_adapters.py
# ... passed, with no assertion changed

$ lint-imports --config importlinter.ini
# ... llm_contract carries no import into either runtime
```

## Why this matters

Two later tasks need one execution protocol and one failure vocabulary that neither runtime owns. If
the protocol stays inside `app/builderops/`, CKM's migration would have to import a BuilderOps module
to get a contract, and Product could never adopt it without importing Builder — reproducing the
authority-direction problem one layer up.

The two new failure classes are the concrete reason this capability exists. A `start-model-inquiry` run
failed with `adapter_failure_class: command_exit_nonzero` when the real cause was that a non-interactive
session could not reach the credential store. A closed vocabulary that cannot say
`credential_unavailable` makes the next occurrence equally uninformative.

## Acceptance criteria

- [ ] Top-level `llm_contract/` exists and imports nothing from `app.builderops`, `app.components`,
      `app.services`, `app.llm`, or any runtime store, transitively. A fresh-process import loads no
      `app` module and causes no environment mutation, network egress, or filesystem artifact.
      Verify: `tests/architecture/test_llm_contract_kernel.py::test_kernel_imports_no_runtime_module`
- [ ] `ModelTurnAdapter`, `AdapterResult`, the failure vocabulary, the five fallback requirement values,
      provider-free intent, capability requirements, resolver/result contracts, and schema-validation
      contract are importable from the kernel, and the five fallback values are exactly ADR-0063's
      five with no sixth.
      Verify: `tests/architecture/test_llm_contract_kernel.py::test_kernel_exposes_exactly_the_adr0063_contracts`
- [ ] `ModelAccessIntent` accepts exactly ADR-0064's seven provider-free fields and rejects provider,
      model, credential, endpoint, or adapter identifiers.
      Verify: `tests/model_access/test_contracts.py::test_model_access_intent_is_provider_free_and_closed`
- [ ] A resolution result cannot claim a provider/model whose capabilities fail the declared
      requirements, and degradation is always explicit with a reason.
      Verify: `tests/model_access/test_contracts.py::test_resolved_access_validates_capabilities_and_visible_degradation`
- [ ] Group resolution enforces `distinct_effective_target` across neutral role profiles and rejects
      a colliding pair before any adapter call.
      Verify: `tests/model_access/test_contracts.py::test_group_resolution_enforces_distinct_effective_targets`
- [ ] `credential_unavailable` and `session_expired` are members of the closed vocabulary.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_auth_failure_classes_are_in_the_closed_vocabulary`
- [ ] A turn classified `credential_unavailable` at the adapter is accepted by the independent
      persistence-boundary re-validation without a second vocabulary edit, and both validations still
      run on the production path.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_auth_failure_class_survives_persistence_revalidation`
      — the test drives a real runner turn through `_validate_provider_attempt_receipt`, not the
      validator in isolation.
- [ ] A failure class that is **not** in the vocabulary is still rejected at both the adapter and the
      persistence boundary.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_unknown_failure_class_is_rejected_at_both_validators`
- [ ] The mock/fake/deterministic identity guard and the distinct-adapter-id plus
      distinct-runtime-target-fingerprint guards still fire from the descriptor-loading call site after
      the move.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_provider_enabled_roles_require_distinct_non_mock_attestation`
- [ ] The existing adapter test file passes with at most import-path edits and no assertion changes.
      Verify: `tests/builderops/test_model_inquiry_adapters.py::test_existing_adapter_contract_regression_suite`
- [ ] `llm_contract` is covered by `importlinter.ini` `source_modules`.
      Verify: `tests/architecture/test_import_boundary.py::test_llm_contract_kernel_is_covered_by_import_boundary`
- [ ] ADR-0063's kernel is recorded as existing in code, with the chosen package path and the rejected
      alternative.
      Verify: `doc writeback at docs/COMPONENTS.md :: llm_contract`

## How to verify (pre-merge)

- `pytest -q tests/model_access/test_contracts.py tests/builderops/test_model_inquiry_adapters.py tests/builderops/test_model_inquiry_runner.py tests/builderops/test_model_inquiry_trace.py`
- `pytest -q tests/architecture`
- `pytest -q -m "not pg"` — full unit lane; this relocates a hot-path contract
- `lint-imports --config importlinter.ini`
- `python3 scripts/docs_guard.py`

## Cross-task invariants preserved

INV-MAS-3 (one vocabulary, two validators) is established here. INV-MAS-4 (role independence survives
relocation) is the reason the guard assertions must run from the descriptor-loading call site rather
than a copy. INV-MAS-5 (no silent substitution) and INV-MAS-6 (additive) hold: this task adds
vocabulary members and a package, and moves code behind re-exports. Seam B is opened and closed here —
the vocabulary must have one source before MAS-05 emits an auth class.

## Out of scope

Concrete resolver implementation and policy. ADR-0063's compatibility mappers. The two registries,
which stay two. Any credential handling — the kernel owns no credential, per ADR-0063
`:87-89`; resolution stays in `app/ops/`. Changing any adapter's behaviour, transport, or retry policy.
Product adoption of the protocol, which is migration step 7. Changes to `app/__init__.py` or Product
provider enforcement.

## Related docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md` — capability contract, Seam B, under-determination 1
- `docs/adr/ADR-0063-shared-llm-contract-kernel.md :: Shared LLM Contract Kernel`, `:: Fallback is contract data, not discovery behavior`
- `docs/adr/ADR-0064-model-access-substrate.md :: 1. What the substrate owns`, `:: 6. Fallback and degradation`
- `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md :: Response And Consensus Contract`
- `app/builderops/model_inquiry_adapters.py`, `app/builderops/model_inquiry.py`
- `docs/adr/ADR-0013-code-dependency-direction.md`, `docs/adr/ADR-0016-contract-first-module-lazy-sbs.md` (contract-first, module-lazy extraction)

## Related GitHub issues

One issue. Title shape
`[Model Access Substrate] promote-adapter-contract-to-neutral-kernel: one execution protocol, one failure vocabulary`.
Its `Context` must state that no kernel module exists today, that the package path is a decision this
capability made because ADR-0063 declined to, and that `app/ports/` was rejected for a stated reason.

TCD capability recommendation for the implementing agent: **Opus / high reasoning** — architecture and
a cross-runtime contract boundary with a package-path decision and a closed-vocabulary invariant; defect
blast radius spans both later tasks (`AGENTS.md :: Total Cost of Development`). Non-binding;
`issue-to-code` re-derives it.
