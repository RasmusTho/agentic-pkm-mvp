---
name: Gate Cross-Scope Fusion
description: Split-per-scope by default; a fused episode spanning scopes exists only via an explicit CrossScopeFlow decision + receipt — the engine's most likely leak, closed by design
task_id: ERE-08
source_anchor: docs/adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md :: Decision §5 (cross-scope fusion is a gated CrossScopeFlow)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-04, ERE-05]
depends_on: [TWO_STREAM_SEGMENTATION_CORE.md, ASSIGN_EPISODE_REF_TO_ARTIFACTS.md]
can_parallelize_with: [Emit Closure and Derive Decay, Respect Human Re-cut]
---

# Gate Cross-Scope Fusion

## Purpose

Fusion correlates signals across scopes: a fused episode can reveal that a private-scope location coincided with a work-scope note — an inference no single stream exposed. ADR-0054 §5 makes this a first-class constraint: a cross-scope episode is itself a CrossScopeFlow event, gated and receipted, never silently constructed. This task turns the constraint into enforced runtime behavior and resolves RQ-E4 with the conservative default.

## What This Task Does

1. **Default posture: split-per-scope** (RQ-E4 resolved conservatively, no new authority needed). Signals are partitioned by `scope_binding` before fusion; a lived situation spanning work+private yields **two sibling proposed episodes**, one per scope, cross-linked only by a scope-neutral `causation`/sibling marker that carries **no content** from the other scope (existence-of-a-sibling is the maximum leak, and it is directionless).
2. **Gated merge**: constructing a single fused episode across scopes requires `mimer_runtime/cross_scope.py::evaluate(source_scope, target_scope, operation, flow)` to allow a dedicated `episode_fuse` operation under an explicit flow — absence of a flow is denial ("similarity is not permission"). An allowed fuse records a receipt; the fused note carries the flow reference.
3. **Assignment discipline**: ERE-05 bindings never cross scopes — an artifact in scope A is never bound to an episode of scope B without an evaluated flow admitting it (per-operation, most-conservative evidence role, per the CrossScopeFlow contract).
4. **Surfacing discipline**: retrieval/CRE consumption of episode context (ERE-06) inherits the existing denial class (`cross_scope_no_flow`) — a closed private episode never influences work-scope ranking, and vice versa.
5. **Receipted denials are silent-but-audited**: denied fuse candidates are dropped with an audit log line (no notification spam), consistent with proportional governance.

## Concretely

```
# Fixture: voice memo (scope=private) overlapping vault edits (scope=work)
$ python -m app.cli episodes tick --json
{"proposed": ["ep-a (work)", "ep-b (private)"], "fusions_denied": 1}
# With an explicit CrossScopeFlow allowing episode_fuse work→private: one fused note + receipt
```

## Why This Matters

This is the most likely place the engine leaks. Scope boundaries survive every other subsystem precisely because crossing is explicit; an engine that quietly manufactures cross-scope situation models would launder private context into work retrieval — a boundary violation that no downstream gate could undo, because the fused *episode itself* is the leak.

## Acceptance Criteria

- [ ] AC1 (enforcement): with no flow, mixed-scope fixture signals produce split per-scope episodes and **no** fused note — asserted on the production fusion path, `evaluate(..., flow=None)` denial honored at the call site. Verify: `tests/invariants/test_cross_scope_flow.py::test_episode_fusion_denied_without_flow`
- [ ] AC2: the sibling cross-link carries no cross-scope content (no title, protagonists, places, or derived_from ids from the other scope). Verify: `tests/episodes/test_cross_scope_fusion.py::test_sibling_link_carries_no_foreign_scope_content`
- [ ] AC3: an explicit flow allowing `episode_fuse` yields exactly one fused episode + a recorded receipt referencing the flow. Verify: `tests/episodes/test_cross_scope_fusion.py::test_explicit_flow_admits_fusion_with_receipt`
- [ ] AC4 (enforcement): assignment never binds an artifact across scopes without an evaluated flow (production assignment path). Verify: `tests/episodes/test_cross_scope_fusion.py::test_assignment_never_crosses_scope_unflowed`
- [ ] AC5: closed-episode decay signals do not cross scopes in retrieval (denial class honored in the ERE-06 derivation). Verify: `tests/episodes/test_cross_scope_fusion.py::test_closure_decay_does_not_cross_scope`
- [ ] AC6: denied fusions are audit-logged, not notified. Verify: `tests/episodes/test_cross_scope_fusion.py::test_denied_fusion_audited_silently`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_cross_scope_fusion.py tests/invariants/test_cross_scope_flow.py
pytest -q -m "not pg"          # full suite: scope discipline is hot-path shared state
```

## Out of Scope

Authoring any actual CrossScopeFlow grants (operator/GOV concern); relaxing the split-default (future owner decision — the gate makes relaxation safe later); third-party consent semantics (Heimdal's side of the seam).

## Related Docs

- `docs/architecture/cross-scope-flow.md` + [ADR-0028](../adr/ADR-0028-cross-scope-flow-replaces-general-knowledge-boolean.md) ("similarity is not permission")
- `mimer_runtime/cross_scope.py::evaluate`, `mimer_runtime/retrieval.py` (denial class `cross_scope_no_flow`)
- [ADR-0054](../adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) §5; research doc §Privacy seam

## Related GitHub Issues

One issue: `[Episode Resolution Engine] cross-scope-gate: split-per-scope default + flow-gated fusion`. Blocked until ERE-04/05 merge. TCD note: privacy-boundary blast radius — route high.
