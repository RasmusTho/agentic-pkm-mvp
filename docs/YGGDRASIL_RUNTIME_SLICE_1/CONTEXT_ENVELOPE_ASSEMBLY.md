---
name: ContextEnvelope Assembly
description: Assemble a bounded ContextEnvelope from a RetrievalResult — no raw vault/index access; references but does not replace ContextBundle
task_id: YRS1-06
source_anchor: docs/architecture/context-envelope.md :: bounded operating context
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: [YRS1-05]
depends_on: [RETRIEVAL_RESULT_CANDIDATE_SEMANTICS.md]
can_parallelize_with: []
---

# ContextEnvelope Assembly

## Purpose

Close the chain: assemble the bounded ContextEnvelope a consumer (CAO/agent) receives — carrying only
bounded context, never raw vault/index access — from the RetrievalResult and any composed
ContextBundles.

## What This Task Does

- Adds `yggdrasil_runtime/context.py` with
  `assemble_envelope(retrieval_result, *, active_workspace_id, active_scope_id, principal_id, user_intent)`
  returning a ContextEnvelope conforming to `schemas/context-envelope.schema.json`.
- The envelope carries `access_mode="bounded_context_only"`, `allowed_capabilities`, `denied_scopes`
  (derived from the RetrievalResult's content-free denied list — no identity leak), the required
  `citation_policy`/`memory_policy`/`mutation_policy`/`execution_policy` constants,
  `escalation_conditions`, `retrieved_items`, and `context_bundles` references marked
  `non_authority: true`.
- The envelope **references** ContextBundle ids; it does not inline or replace a bundle's authority.
- No `vault_id`, `vault_root`, `raw_index`, or any raw-access field is present.

## Concretely

```python
from yggdrasil_runtime import retrieval, context
r = retrieval.retrieve(query="state machine", active_scope_id="scope:work/project-alpha")
env = context.assemble_envelope(
    r, active_workspace_id="ws-1", active_scope_id="scope:work/project-alpha",
    principal_id="p-1", user_intent="orient on the state machine",
)
assert env.access_mode == "bounded_context_only"
assert all(b.non_authority is True for b in env.context_bundles)
# denied_scopes carry no object_id/scope_id/content/provenance
```

## Why This Matters

The ContextEnvelope is the boundary the agent sees. If it carried raw vault/index access, the agent
could bypass every prefilter and policy decision upstream. If it replaced ContextBundle, candidate
evidence would silently become authority. If denied scopes leaked identity, "this scope exists" is
itself a cross-boundary disclosure. The envelope is where bounded-context discipline is made real.

## Acceptance Criteria

- [ ] `assemble_envelope(...)` returns a ContextEnvelope that validates against
  `schemas/context-envelope.schema.json` with `access_mode == "bounded_context_only"`.
  - Verify: `tests/invariants/test_context_envelope_runtime.py::test_assembled_envelope_validates_and_is_bounded`
- [ ] The envelope contains no raw vault/index field; `context_envelope_has_no_raw_vault_or_index_access`
  stays green against the runtime-built envelope.
  - Verify: `tests/invariants/test_context_envelope.py::test_context_envelope_has_no_raw_vault_or_index_access` (kept green) +
    `tests/invariants/test_context_envelope_runtime.py::test_runtime_envelope_has_no_raw_access`
- [ ] Composed bundles are referenced with `non_authority: true`; the envelope does not replace a
  ContextBundle.
  - Verify: `tests/invariants/test_context_envelope.py::test_context_bundle_is_not_context_envelope` (kept green) +
    `tests/invariants/test_context_envelope_runtime.py::test_envelope_references_bundle_as_non_authority`
- [ ] `denied_scopes` derived from the RetrievalResult leak no object/scope identity or content.
  - Verify: `tests/invariants/test_context_envelope_runtime.py::test_runtime_denied_scopes_are_content_free`

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants/test_context_envelope.py tests/invariants/test_context_envelope_runtime.py`.
- Confirm the full chain runs: `capture → derive_segment → retrieve → assemble_envelope` without raw
  store access in the envelope.

## Out of Scope

- CAO reasoning/orchestration over the envelope (`propose_when_uncertain` left xfail).
- Allowed-capability execution, mutation, memory promotion (policies are present as constants only;
  their runtime is out of scope).

## Restart / Durability Posture

The envelope is assembled per request from in-memory inputs; nothing persists. Not a durable
user-facing surface.

## Related Docs

- `docs/architecture/context-envelope.md`, `docs/contracts/CONTEXT_BUNDLE.md`
- `schemas/context-envelope.schema.json`
- Boundaries: RCA, CAO, GOV

## Related GitHub Issues

One issue, `agent:ready` once YRS1-05 merges. Do not start before RetrievalResult basics exist.
