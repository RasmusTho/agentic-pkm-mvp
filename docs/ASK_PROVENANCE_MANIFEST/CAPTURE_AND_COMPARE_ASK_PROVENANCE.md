---
name: Capture And Compare ASK Provenance
description: Add a local, feature-flagged shadow manifest and authorization-safe replay comparison for ASK executions.
task_id: APM-01
source_anchor: docs/ASK_PROVENANCE_MANIFEST/README.md :: First delivery
parent_capability: ASK Provenance Manifest
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Capture And Compare ASK Provenance

## Purpose

Record the actual evidence and authorization identities available from a grounded ASK execution without changing what ASK does, then compare two records without exposing evidence outside the current caller's scope.

## What This Task Does

Add an append-only `ask_provenance_manifest.v1` in restricted local runtime state behind a disabled-by-default flag. The manifest hashes the final answer and records ordered admitted evidence, actual normalized scope, available retrieval/synthesis identities, and explicit `unavailable` fields. A read-only comparator classifies `reproducible`, `source_drift`, `index_drift`, `scope_mismatch`, or `indeterminate` only when the recorded evidence supports that label.

## Concretely

Capture runs after synthesis and has a bounded time budget. Replay runs under current authentication and policy, not a restored historical context. Scope mismatch halts evidence comparison and emits only safe mismatch metadata. Retention is local, bounded, observable, and outside the vault/index.

## Why This Matters

The future Lens must not turn citation lists into misleading causal claims or leak material that has since become inaccessible.

## Acceptance Criteria

- [ ] Flag-on and flag-off ASK responses have identical text, status, result order, and vault/index write behavior. Verify: `tests/agent_memory/test_ask_provenance_manifest.py::test_shadow_capture_preserves_ask_response_and_side_effects`.
- [ ] Each valid manifest contains answer hash, actual scope snapshot, ordered admitted evidence, and explicit unavailable-field reasons; it contains no raw query, answer, body, excerpt, or credential. Verify: `tests/agent_memory/test_ask_provenance_manifest.py::test_manifest_is_minimal_and_privacy_safe`.
- [ ] A changed canonical source hash yields `source_drift`; missing canonical index identity yields `indeterminate`, not `index_drift`. Verify: `tests/agent_memory/test_ask_provenance_manifest.py::test_comparison_classifies_only_supported_drift`.
- [ ] Scope, principal, authorization-context, or policy mismatch suppresses side-specific evidence details. Verify: `tests/agent_memory/test_ask_provenance_manifest.py::test_scope_mismatch_redacts_evidence_details`.
- [ ] Capture/storage failure leaves ASK successful and writes no malformed comparable manifest. Verify: `tests/agent_memory/test_ask_provenance_manifest.py::test_capture_failure_isolated_from_ask`.
- [ ] Retention removes expired manifests deterministically and does not synchronize them to vault or index surfaces. Verify: `tests/agent_memory/test_ask_provenance_manifest.py::test_manifest_retention_is_local_and_bounded`.

## How to Verify (Pre-Merge)

- `pytest -q tests/agent_memory/test_ask_provenance_manifest.py`
- `pytest -q tests/agent_memory/test_ask_synthesis_gate.py tests/retrieval/test_retrieval_durable_equivalence.py`
- Run the focused latency-parity fixture named by `tests/agent_memory/test_ask_provenance_manifest.py::test_shadow_capture_respects_latency_budget`.

## Out of Scope

No Lens UI, API expansion, raw audit log, remote export, span-level citation support, historical authorization replay, retrieval/ranking change, or semantic/causal answer diff.

## Related Docs

- `docs/ASK_PROVENANCE_MANIFEST/README.md`
- `docs/RETRIEVAL.md`

## Related GitHub Issues

Create one bounded implementation issue after this specification is merged. TCD hint: Sol / high reasoning for boundary design and review; Terra / high reasoning is appropriate for the bounded implementation once the contract is accepted.
