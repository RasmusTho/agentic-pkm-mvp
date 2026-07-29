---
name: Replace CKM Product Routing With Builder Adapter
description: Replace FabricSemanticAssociator with a Builder-side adapter so CKM stops resolving Builder inference through Product routing policy, prove Product fallback cannot execute the Builder task, and remove the interim importlinter exemption.
task_id: MAS-06
source_anchor: docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration (step 5)
parent_capability: Model Access Substrate
prerequisites: [MAS-05]
depends_on: [RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT.md]
can_parallelize_with: []
---

State: Authored task specification (child issue #4292, filed 2026-07-29). Closes the interim window
opened by MAS-02. It follows accepted MAS-05 parent validation; the order does not swap.

# Replace CKM Product Routing With Builder Adapter

## Purpose

CKM's only model path today resolves through the **Product** router.
`app/builderops/ckm/semantic.py` constructs
`get_chat_client(LLMTaskIntent(task_kind="classify", ...))` and rejects a `mock` route only *after*
Product routing may already have constructed policy-defined fallback candidates, including the `mock`
candidate the router appends. That is the authority leakage ADR-0063 rejected its Option A to prevent,
and `importlinter.ini` did not catch it because `app.builderops` and `app.components` sit on the same
side of the only existing contract.

ADR-0064 §8 **amends ADR-0063's sequencing**: CKM migrates after Model Inquiry proves the substrate,
requiring credential resolution and the neutral intent/resolver/adapter contracts — not a complete
Builder Capability Runtime.

## Position in the order

The amended ADR-0064 §8 keeps Model Inquiry first and CKM migration at step 5. This issue remains
blocked until `model_access_substrate.provider_enabled_noninteractive_inquiry.v1` is accepted on the
parent. A builder agent may read CKM evidence during the window; CKM itself remains projection-only.

## What this task does

1. Add a Builder-side associator implementing the existing `SemanticAssociator` protocol
   (`app/builderops/ckm/semantic.py:104`) on top of the MAS-05 Builder resolver and kernel
   `ModelTurnAdapter`. It submits provider-free `ModelAccessIntent`, declares
   `fallback_forbidden`, and receives provider/model/capability/credential provenance only as a
   resolved result.
2. Remove `FabricSemanticAssociator` and both Product imports from `app/builderops/ckm/semantic.py`:
   `app.components.llm.fabric` (`LLMTaskIntent`, `get_chat_client`) and `app.components.llm.constrained`
   (`ConstrainedCompletionError`, `register_schema`, `validate_payload`). The schema-reference and
   validation contract promoted by MAS-04 replaces the second import; `SEMANTIC_SCHEMA_REF` and the
   `builderops.ckm.semantic-association.v1` schema keep their current identity.
3. Remove the interim exemption from `importlinter.ini` **in the same change** that removes the last
   import, so the contract is never made to pass by widening and never fails on main in between.
4. Preserve every existing CKM semantic behaviour: candidate-only inferred edges, the confidence floor,
   confirmation-receipt integrity across rebuild, skip-on-unavailable, and the structured-output failure
   mapping. A degraded result is skipped with a visible reason and writes zero edges. The existing
   tests in `tests/builderops/ckm/test_semantic.py` are the regression contract.
5. Update `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md` so it describes a
   Builder-side model path rather than the routed Product chat fabric.

## Concretely

```
$ lint-imports --config importlinter.ini
Builder System must not import the Product LLM fabric KEPT
# ... and importlinter.ini now carries no ignore_imports for this contract

$ grep -rn "app.components.llm" app/builderops/
# (no output)

$ pytest -q tests/builderops/ckm/test_semantic.py
# ... 13 existing tests passed, plus the new negative test
```

```
# with only a Product policy route reachable and no declared Builder credential:
$ builderops ckm associate --json
{"status": "skipped", "reason": "semantic provider unavailable", "proposals": 0}
# never: a proposal produced by a Product-policy-selected route
```

## Why this matters

The owner's framing makes CKM the heaviest model caller in the Builder System. While it routes through
Product policy, every CKM inference is governed by vault-compiled Product settings, Product fallback
candidates, and Product registry authority — none of which the Builder System owns or should. The
`mock` rejection in the current code is a check after the fact: the route has already been selected by
the time it runs, and a Product policy edit could change what CKM executes without any Builder-side
change.

This is also what ends the interim window. Every day the exemption exists is a day the accepted risk is
live; this task is the only thing that removes it.

## Acceptance criteria

- [ ] CKM semantic association resolves its model through the kernel adapter with a contract-resolved
      credential, and `FabricSemanticAssociator` no longer exists.
      Verify: `tests/builderops/ckm/test_semantic.py::test_semantic_association_resolves_through_builder_adapter`
- [ ] The production CKM call site submits no provider/model and resolves exclusively through the
      Builder runtime/channel census mapping.
      Verify: `tests/builderops/ckm/test_semantic.py::test_semantic_production_call_uses_provider_free_builder_resolver`
- [ ] A Product policy fallback cannot execute the Builder semantic-association task, asserted on the
      production association path rather than on the guard in isolation.
      Verify: `tests/builderops/ckm/test_semantic.py::test_product_fallback_cannot_execute_builder_task`
      — the test drives the real association entry point with a Product route configured and asserts no
      Product client is constructed and no proposal is produced.
- [ ] The request declares `fallback_forbidden`, and no other fallback requirement value is accepted for
      this task.
      Verify: `tests/builderops/ckm/test_semantic.py::test_semantic_request_declares_fallback_forbidden`
- [ ] A mock, fake, or deterministic identity is refused **before** any route is selected, not after.
      Verify: `tests/builderops/ckm/test_semantic.py::test_mock_identity_is_refused_before_route_selection`
- [ ] An absent or unusable declared credential makes association skip cleanly, with a visible reason,
      and never silently produces proposals from another path.
      Verify: `tests/builderops/ckm/test_semantic.py::test_llm_unavailable_skips_cleanly`
      Verify: `tests/builderops/ckm/test_semantic.py::test_credential_unavailable_skips_with_visible_reason`
- [ ] A non-mock degraded result is visible and writes zero semantic edges.
      Verify: `tests/builderops/ckm/test_semantic.py::test_degraded_builder_route_writes_zero_edges_with_visible_reason`
- [ ] No `app.builderops` module imports `app.components.llm`, and the `importlinter` contract passes
      with **zero** exemptions.
      Verify: `tests/architecture/test_import_boundary.py::test_builder_does_not_import_product_llm_without_exemption`
      — the same test MAS-02 introduced, now asserting the exemption list is empty.
- [ ] Every existing CKM semantic behaviour is preserved: candidate labelling, confidence floor,
      confirmation-receipt integrity across rebuild, tombstoning, and demotion on material change.
      Verify: `tests/builderops/ckm/test_semantic.py::test_existing_semantic_contract_regression_suite`
- [ ] INV-CKM-1 (provenance everywhere) still holds: every inferred edge records the provider and model
      that produced it, now sourced from the Builder adapter.
      Verify: `tests/builderops/ckm/test_semantic.py::test_inferred_edges_fenced_via_store_write_path`
- [ ] The interim window is recorded as closed.
      Verify: `doc writeback at docs/architecture/SBS_TRANSITION_DEBT.md :: model access substrate interim window`
- [ ] The CKM specification describes a Builder-side model path.
      Verify: `doc writeback at docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does`

## How to verify (pre-merge)

- `pytest -q tests/builderops/ckm/`
- `pytest -q tests/architecture/test_import_boundary.py`
- `lint-imports --config importlinter.ini` — must report KEPT with no `ignore_imports` entry
- `pytest -q -m "not pg"` — full unit lane
- `python3 scripts/docs_guard.py`
- Negative check performed by hand and reverted: reintroduce one `app.components.llm` import into any
  `app/builderops/` module and confirm the contract reports BROKEN.

## Cross-task invariants preserved

INV-MAS-2 (credentials only through the contract), INV-MAS-3 (one vocabulary, two validators),
INV-MAS-1 (provider-free intent), INV-MAS-5 (no silent substitution — this is the task where "no mock route" becomes structural rather
than a post-hoc check), and INV-MAS-7, which this task discharges by removing the only exemption. Seam C
is closed here: exemption removal and import removal are one atomic change. Seam D closes only when
the production import and exemption disappear together.

## Out of scope

CKM dispatch, mutation, ranking, gating, prioritization, or decision authority. Changing the CKM
object model, maturity engine, projections, or any other CKM surface. Deterministic linkers, migration
steps 6 and 7, and Product routing remain unchanged.

## Related docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md :: Interim CKM posture`, Seams C and D
- `docs/adr/ADR-0064-model-access-substrate.md :: 8. CKM sequencing — amends ADR-0063`
- `docs/adr/ADR-0063-shared-llm-contract-kernel.md :: Separate runtime authority`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md` — projection-only lock, candidate lifecycle
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants / Interaction Safety` — INV-CKM-1, INV-CKM-3
- `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md`
- `app/builderops/ckm/semantic.py`, `tests/builderops/ckm/test_semantic.py`

## Related GitHub issues

One issue. Title shape
`[Model Access Substrate] replace-ckm-product-routing-with-builder-adapter: end the interim authority leak`.
Its `Context` must state that amended ADR-0064 §8 keeps this after the accepted MAS-05 receipt, that
the task removes the MAS-02 exemption, and that CKM remains projection-only. It stays
`agent:blocked` until the parent records
`model_access_substrate.provider_enabled_noninteractive_inquiry.v1`.

TCD capability recommendation for the implementing agent: **Opus / high reasoning** — authority-boundary
work with a negative-proof requirement and a thirteen-test regression contract; the defect mode is a
silent Product route surviving the refactor (`AGENTS.md :: Total Cost of Development`). Non-binding;
`issue-to-code` re-derives it.
