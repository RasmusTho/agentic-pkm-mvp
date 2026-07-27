---
name: Make Builder-To-Product LLM Dependency Visible
description: Fail importlinter on app.builderops importing app.components.llm, with exactly one named and dated exemption, so the accepted interim authority leak becomes a countdown instead of an invisible violation.
task_id: MAS-02
source_anchor: docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8.1 CKM's position in the order has moved — and the interim window must be named
parent_capability: Model Access Substrate
prerequisites: []
depends_on: []
can_parallelize_with: [DEFINE_PROVIDER_CENSUS.md, EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md, PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL.md]
---

State: Authored task specification (future-state; child issue not yet filed). Delivers condition 2 of
ADR-0064 §8's interim CKM window.

# Make Builder-To-Product LLM Dependency Visible

## Purpose

ADR-0064 §8 accepts, for a bounded window, that CKM keeps routing Builder inference through Product
policy — the exact authority leakage ADR-0063 rejected Option A to prevent. That acceptance is
conditional, and one of its two conditions is that the leak must be **visible**. Today it is not:
`importlinter.ini` carries a single `interaction-protected` contract in which `app.builderops` and
`app.components` sit on the same `source_modules` side, so the import is structurally invisible to the
gate that exists to catch exactly this class of thing.

This task converts an invisible violation into a countdown with a date on it.

## What this task does

1. Add a new `[importlinter:contract:...]` block of `type = forbidden` with
   `source_modules = app.builderops` and `forbidden_modules = app.components.llm`. The existing
   `interaction-protected` contract's shape is the model; this is a second contract, not an edit to the
   first.
2. Add exactly one `ignore_imports` exemption covering `app/builderops/ckm/semantic.py`'s imports of
   `app.components.llm.fabric` and `app.components.llm.constrained`. The exemption carries the name of
   the migration task that removes it (`MAS-06`) and the date it was granted, as an inline comment
   directly above the `ignore_imports` key. `ignore_imports` is currently unused anywhere in this
   repository, so this establishes the convention.
3. Add an architecture test asserting the exemption is single, named, and dated, and asserting the
   contract is actually evaluated by the gate that runs in CI rather than merely present in the file.
4. Correct the stale header comment in `importlinter.ini` lines 6-7, which still claims the gate runs
   non-blocking. It runs blocking in two places:
   `.github/workflows/import-linter.yaml:36-37` and `.github/workflows/ci-smoke.yaml:811-814`.
5. Record the interim window, its two conditions, and its removal task in
   `docs/architecture/SBS_TRANSITION_DEBT.md` so the debt is registered where transition debt lives
   rather than only in an audit snapshot.

## Concretely

```ini
[importlinter:contract:builder-llm-authority]
name = Builder System must not import the Product LLM fabric
type = forbidden
source_modules =
    app.builderops
forbidden_modules =
    app.components.llm
# INTERIM EXEMPTION — granted 2026-07-27 under ADR-0064 §8; removed by MAS-06
# (docs/MODEL_ACCESS_SUBSTRATE/REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER.md).
# Exactly one exemption is permitted; a second one is a test failure, not a config choice.
ignore_imports =
    app.builderops.ckm.semantic -> app.components.llm.fabric
    app.builderops.ckm.semantic -> app.components.llm.constrained
```

```
$ lint-imports --config importlinter.ini
Builder System must not import the Product LLM fabric KEPT

# after adding any second app.components.llm import inside app/builderops/:
$ lint-imports --config importlinter.ini
Builder System must not import the Product LLM fabric BROKEN
  app.builderops.<new module> -> app.components.llm.<...>
```

## Why this matters

ADR-0064 accepted a known authority leak on the explicit understanding that it would be countable. If
this contract does not land, the interim window has no end condition, nothing prevents a second Builder
module from acquiring the same dependency while the window is open, and the removal in MAS-06 has no
gate proving it actually happened. An accepted risk that nobody can observe is an unaccepted risk.

The exemption is also the countdown itself: `MAS-06` closes by deleting it, and the same test that
forbids a second exemption forbids widening the contract to make an import pass.

## Acceptance criteria

- [ ] `importlinter` fails when any `app.builderops` module other than the exempted one imports
      `app.components.llm`, and the failure is produced by the gate that runs in CI rather than by a
      test-local invocation of the linter.
      Verify: `tests/architecture/test_import_boundary.py::test_builder_does_not_import_product_llm_without_exemption`
      — the test asserts the new contract is present in the config consumed by
      `.github/workflows/ci-smoke.yaml:814` and `.github/workflows/import-linter.yaml:37`, and that a
      synthetic second import inside `app.builderops` breaks the contract.
- [ ] Exactly one exemption exists, it names `MAS-06` as its removal task, and it carries a date.
      Verify: `tests/architecture/test_import_boundary.py::test_interim_exemption_is_single_named_and_dated`
- [ ] The existing `interaction-protected` contract and its `source_modules` coverage assertion are
      unchanged and still pass.
      Verify: `tests/architecture/test_import_boundary.py` (existing coverage assertions, unmodified)
- [ ] `importlinter.ini`'s header no longer claims the gate is non-blocking.
      Verify: doc writeback at `importlinter.ini` header comment lines 6-7
- [ ] The interim window, both ADR-0064 §8 conditions, and the removal task are registered as
      transition debt.
      Verify: doc writeback at `docs/architecture/SBS_TRANSITION_DEBT.md :: model access substrate interim window`

## How to verify (pre-merge)

- `pip install import-linter==2.11 && lint-imports --config importlinter.ini`
- `pytest -q tests/architecture/test_import_boundary.py`
- `pytest -q -m "not pg"`
- Negative check performed by hand and reverted: add `from app.components.llm.fabric import
  get_chat_client` to any `app/builderops/` module other than `ckm/semantic.py` and confirm
  `lint-imports` reports the contract BROKEN naming that module.
- `python3 scripts/docs_guard.py`

## Cross-task invariants preserved

INV-MAS-7 (the leak is visible, single, and time-boxed) is established by this task. INV-MAS-6
(additive) holds — no runtime code changes. Seam C is opened here and closed by MAS-06: the exemption
must not be removed before the last import is.

## Out of scope

Removing the CKM imports themselves, which is MAS-06. Any other import-boundary contract; ADR-0013's
fuller per-layer contracts remain the documented refinement they already are. Changing which workflows
run the linter. Deciding whether CKM may orchestrate, which needs an ADR-0057 amendment.

## Related docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md :: Interim CKM conditions`
- `docs/adr/ADR-0064-model-access-substrate.md :: 8. CKM sequencing — amends ADR-0063`
- `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8.1`
- `docs/adr/ADR-0013-code-dependency-direction.md` — governs `importlinter.ini`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md` — the projection-only lock that condition 1 rests on
- `importlinter.ini`, `tests/architecture/test_import_boundary.py`

## Related GitHub issues

One issue. Title shape
`[Model Access Substrate] make-builder-to-product-llm-dependency-visible: name the interim authority leak`.
It must state that it delivers condition 2 of ADR-0064 §8 and that MAS-06 removes the exemption it
creates.

TCD capability recommendation for the implementing agent: **Sonnet / medium reasoning** — one config
contract, one exemption convention, one architecture test; the shape is already established by the
existing `interaction-protected` contract and the failure is loud and local
(`AGENTS.md :: Total Cost of Development`). Non-binding; `issue-to-code` re-derives it.
