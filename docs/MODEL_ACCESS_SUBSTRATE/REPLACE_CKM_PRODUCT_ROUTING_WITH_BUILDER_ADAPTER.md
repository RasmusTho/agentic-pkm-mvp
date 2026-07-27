---
name: Replace CKM Product Routing With Builder Adapter
description: Replace FabricSemanticAssociator with a Builder-side adapter so CKM stops resolving Builder inference through Product routing policy, prove Product fallback cannot execute the Builder task, and remove the interim importlinter exemption.
task_id: MAS-06
source_anchor: docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration (step 5)
parent_capability: Model Access Substrate
prerequisites: [MAS-03, MAS-04]
depends_on: [EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md, PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL.md]
can_parallelize_with: [RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT.md]
---

State: Authored task specification (future-state; child issue not yet filed). Closes the interim window
opened by MAS-02. Its position relative to MAS-05 is a preference, not a dependency — see the swap
condition below.

# Replace CKM Product Routing With Builder Adapter

## Purpose

CKM's only model path today resolves through the **Product** router.
`app/builderops/ckm/semantic.py` constructs
`get_chat_client(LLMTaskIntent(task_kind="classify", ...))` and rejects a `mock` route only *after*
Product routing may already have constructed policy-defined fallback candidates, including the `mock`
candidate the router appends. That is the authority leakage ADR-0063 rejected its Option A to prevent,
and `importlinter.ini` did not catch it because `app.builderops` and `app.components` sit on the same
side of the only existing contract.

ADR-0064 §8 **amends ADR-0063's sequencing**: CKM migrates as early as its dependencies allow, requiring
only credential resolution and the adapter contract — not a complete Builder Capability Runtime. An
orchestrator that can silently resolve to a mock route cannot be an orchestrator.

## Position in the order, and the swap

MAS-05 and MAS-06 share an identical prerequisite set and declare each other in
`can_parallelize_with`. The stated preference is MAS-05 first, because model inquiry is the smaller,
already-adapter-shaped consumer that proves the substrate cheaply.

**The swap trigger is condition 1 of ADR-0064 §8**: if CKM orchestration must begin before MAS-05
lands, this task is promoted ahead of it. No specification edit is needed to express that. While the
window is open — that is, while any `app.builderops -> app.components.llm` exemption exists — CKM must
not orchestrate; ADR-0057's projection-only lock is the governing statement and remains unamended by
this capability.

## What this task does

1. Add a Builder-side associator implementing the existing `SemanticAssociator` protocol
   (`app/builderops/ckm/semantic.py:104`) on top of the kernel `ModelTurnAdapter`, with its credential
   resolved through the host secret contract and its request declaring
   `fallback_forbidden`.
2. Remove `FabricSemanticAssociator` and both Product imports from `app/builderops/ckm/semantic.py`:
   `app.components.llm.fabric` (`LLMTaskIntent`, `get_chat_client`) and `app.components.llm.constrained`
   (`ConstrainedCompletionError`, `register_schema`, `validate_payload`). The schema-reference and
   validation contract promoted by MAS-04 replaces the second import; `SEMANTIC_SCHEMA_REF` and the
   `builderops.ckm.semantic-association.v1` schema keep their current identity.
3. Remove the interim exemption from `importlinter.ini` **in the same change** that removes the last
   import, so the contract is never made to pass by widening and never fails on main in between.
4. Preserve every existing CKM semantic behaviour: candidate-only inferred edges, the confidence floor,
   confirmation-receipt integrity across rebuild, skip-on-unavailable, and the structured-output failure
   mapping. The thirteen tests in `tests/builderops/ckm/test_semantic.py` are the regression contract.
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
      Verify: `tests/builderops/ckm/test_semantic.py::test_llm_unavailable_skips_cleanly` (existing, unmodified)
      Verify: `tests/builderops/ckm/test_semantic.py::test_credential_unavailable_skips_with_visible_reason`
- [ ] No `app.builderops` module imports `app.components.llm`, and the `importlinter` contract passes
      with **zero** exemptions.
      Verify: `tests/architecture/test_import_boundary.py::test_builder_does_not_import_product_llm_without_exemption`
      — the same test MAS-02 introduced, now asserting the exemption list is empty.
- [ ] Every existing CKM semantic behaviour is preserved: candidate labelling, confidence floor,
      confirmation-receipt integrity across rebuild, tombstoning, and demotion on material change.
      Verify: `tests/builderops/ckm/test_semantic.py` (all thirteen existing tests, unmodified)
- [ ] INV-CKM-1 (provenance everywhere) still holds: every inferred edge records the provider and model
      that produced it, now sourced from the Builder adapter.
      Verify: `tests/builderops/ckm/test_semantic.py::test_inferred_edges_fenced_via_store_write_path` (existing, unmodified)
- [ ] The interim window is recorded as closed.
      Verify: doc writeback at `docs/architecture/SBS_TRANSITION_DEBT.md :: model access substrate interim window`
- [ ] The CKM specification describes a Builder-side model path.
      Verify: doc writeback at `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does`

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
INV-MAS-5 (no silent substitution — this is the task where "no mock route" becomes structural rather
than a post-hoc check), and INV-MAS-7, which this task discharges by removing the only exemption. Seam C
is closed here: exemption removal and import removal are one atomic change. Seam D holds until this task
merges: while the exemption exists, no CKM path may initiate delivery.

## Out of scope

Whether CKM may orchestrate at all. ADR-0057 locks CKM projection-only with a candidate lifecycle and
human confirmation; orchestration exceeds that scope and requires its own ADR amendment, which this task
neither requests nor presumes. Changing the CKM object model, the maturity engine, projections, or any
other CKM surface. The deterministic linkers, which need no model. Migration steps 6 and 7. Any change to
Product routing, which keeps its current behaviour for its own callers.

## Related docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md :: Interim CKM conditions`, Seams C and D
- `docs/adr/ADR-0064-model-access-substrate.md :: 8. CKM sequencing — amends ADR-0063`
- `docs/adr/ADR-0063-shared-llm-contract-kernel.md :: Separate runtime authority`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md` — projection-only lock, candidate lifecycle
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants / Interaction Safety` — INV-CKM-1, INV-CKM-3
- `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md`
- `app/builderops/ckm/semantic.py`, `tests/builderops/ckm/test_semantic.py`

## Related GitHub issues

One issue. Title shape
`[Model Access Substrate] replace-ckm-product-routing-with-builder-adapter: end the interim authority leak`.
Its `Context` must state that ADR-0064 §8 amends ADR-0063's CKM sequencing, that this task removes the
exemption MAS-02 created, that its order relative to MAS-05 is a preference with a named swap trigger,
and that it does not decide whether CKM may orchestrate. It stays `agent:blocked` until MAS-03 and
MAS-04 merge.

TCD capability recommendation for the implementing agent: **Opus / high reasoning** — authority-boundary
work with a negative-proof requirement and a thirteen-test regression contract; the defect mode is a
silent Product route surviving the refactor (`AGENTS.md :: Total Cost of Development`). Non-binding;
`issue-to-code` re-derives it.
