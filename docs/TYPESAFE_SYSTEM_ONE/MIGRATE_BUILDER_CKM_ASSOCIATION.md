---
name: Use Jev for Builder CKM Semantic Association
description: Select CKM associations from a deterministic candidate set using typed Jev judgments.
task_id: TSO-04
github_issue: 5768
source_anchor: docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-01]
depends_on: [DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md]
can_parallelize_with: [TSO-03 after TSO-02]
---

# Use Jev for Builder CKM Semantic Association

## Purpose

CKM currently asks a general model to generate free-form proposal JSON. Jev can select among deterministic candidate IDs, reducing JSON parsing and preventing invented candidate identifiers while keeping CKM non-authoritative.

## What This Task Does

- Build a deterministic bounded candidate list from the existing CKM artifact and capability registry before calling Jev.
- Use the Builder-owned resolver/adapter path and `fallback_forbidden`; the production Builder call site does not name a provider or import Product MARR policy.
- Use a Choice with an explicit no-match option. Reject answers outside the submitted candidate set.
- Preserve inferred/candidate provenance, the existing confidence floor, stable edge identity, snapshot revalidation, watermark transaction, explicit `confirm-edge` receipt, and visible zero-edge skip on unavailable/degraded results.
- Resolve the credential through a dedicated Builder CKM consumer binding. Keep it dev-only unless a separate release-channel acceptance authorizes wider use.

## Concretely

Jev returns one candidate ID (or no-match) with its probability/confidence. The CKM layer maps that result to the existing proposal schema using source IDs and deterministic provenance text. Any stale candidate snapshot or unusable answer writes zero edges and leaves the watermark unchanged.

## Why This Matters

Free-form JSON can invent IDs or output fields. Restricting the judgment to known candidates reduces that failure mode without granting CKM ranking, decision, dispatch, or confirmation authority.

## Acceptance Criteria

- [ ] The production CKM path uses the Builder-owned typed judgment adapter with provider-free intent and `fallback_forbidden`. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_production_call_uses_builder_judgment_resolver`.
- [ ] The request contains only deterministic candidate IDs and bounded artifact/capability fields; answers outside the candidate set are rejected. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_choice_is_limited_to_supplied_candidates`.
- [ ] Missing credentials, degraded route, low confidence, or stale input writes zero edges and leaves the semantic watermark unchanged. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_unavailable_or_stale_judgment_writes_zero_edges`.
- [ ] Candidate lifecycle, confidence-floor, confirmation-receipt, and rebuild behavior remain enforced through the production store path. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_existing_candidate_confirmation_and_rebuild_contract`.
- [ ] CKM documentation reports the TypeSafe path as dev-scoped and does not present inferred proposals as confirmed truth. Verify: doc writeback at `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/ckm/test_semantic_typesafe.py tests/builderops/ckm/test_semantic.py`
- `pytest -q tests/ops/test_host_secret_contract.py::test_typesafe_key_is_builder_ckm_dev_only`
- `lint-imports --config importlinter.ini`
- `git diff --check`

## Out of Scope

- Capability invention, confirmation or auto-apply, Product routing, Model Inquiry subscription reuse, test/prod credentials, or full repository text transmission.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md`
- `docs/MODEL_ACCESS_SUBSTRATE/README.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md`
