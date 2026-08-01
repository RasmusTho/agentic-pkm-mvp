---
name: Runtime Scope Prefilter and Envelope
description: Promote scope-prefilter-before-ranking, content-free denials, evidence-role clamp, and ContextEnvelope assembly from mimer_runtime into the live app/ retrieval path
task_id: KERNEL-10
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-A5, CW-4"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-05]
depends_on: [RETRIEVAL_READS_DURABLE_INDEX.md]
can_parallelize_with: []
---

# Runtime Scope Prefilter and Envelope

## Purpose

`mimer_runtime/` (test-only, corpus-backed, excluded from the wheel) already implements the
admissibility kernel: scope/policy prefilter **before** ranking (`retrieval.py::retrieve`,
`eligible_candidates`), content-free `ScopeDenial` records, an evidence-role clamp that never lets
in-context role exceed the intrinsic role (`retrieval.py::_clamp_in_context`), and
`ContextEnvelope` assembly validating `schemas/context-envelope.schema.json`
(`context.py::assemble_envelope`). The **live** `app/` path has none of this: `app/retrieval/hybrid.py::hybrid_search`
(approx. line 221) ranks over an in-memory store, callers (`app/api/routes/ask.py`,
`app/activation/ask_synthesis.py::build_retrieval_candidates`) consume raw ranked dicts, and there
is no envelope, no content-free denial, no in-context role clamp (audit **I-A5**, **CW-4**).

Reconciliation: #2022/#2025 (admissibility-governed activation gate) are **delivered and closed**;
the "Slice #2025" pointer in `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` (lines 1, 201) is
stale numbering. This task is the remaining gap: promote prefilter + envelope semantics into `app/`
retrieval so agents consume a bounded `ContextEnvelope`, not raw index access.

## What This Task Does

- Apply scope/policy eligibility **before** ranking in the live retrieval entrypoint
  (`app/retrieval/hybrid.py::hybrid_search`): ineligible material is excluded from the candidate set
  prior to scoring, mirroring `mimer_runtime/retrieval.py::eligible_candidates`.
- Record excluded-but-relevant material as **content-free** denials (denial class + scope only, no
  body/snippet), matching `ScopeDenial` — never a silent drop.
- Clamp `evidence_role_in_context` so it never upgrades above the item's intrinsic evidence role
  (port `_clamp_in_context`).
- Assemble a `ContextEnvelope` (validated against `schemas/context-envelope.schema.json`, no
  raw-access/storage fields) at the ASK/chat consumption seam so `app/api/routes/ask.py` and
  `app/activation/ask_synthesis.py::build_retrieval_candidates` receive an envelope, not raw dicts.
- Convert the three runtime eval skeletons (`tests/evals/test_general_knowledge_crosses_clean.py`,
  `test_rpg_not_confused_with_software.py`, `test_private_not_in_work_results.py`) to exercise the
  `app/` path. Today they gate on `require_future_runtime(...)` (`tests/evals/_helpers.py`, line 122),
  which xfails while the `mimer_runtime` module is absent. "Runs against app runtime" means: add an
  `app/`-backed adapter/fixture presenting the same corpus through the live retrieval entrypoint, and
  repoint the skeletons at it (drop the xfail). This does NOT relocate `mimer_runtime` into `app/`.

## Activation in Production

Delivering the mechanism is not the same as running it. Between #2772 and #2921 the prefilter was
correct and mutation-verified in tests yet **dormant in the default running product**:
`ASK_DOMAIN_SCOPE` was read by `app/retrieval/hybrid.py::_resolve_domain_scope` and set by no
production code anywhere, so `scope` resolved to `None`, `_partition_by_scope` admitted every
document, and I-A5 ("private not in work results") was enforced only where a test set the
environment variable by hand.

**The activation mechanism is a per-request active-scope binding threaded through the production
ASK path.** One value is resolved once per turn and reused everywhere:

`app/api/routes/ask.py::AskRequest.scope` (or the matching `scope` form field on `/api/ask/voice`)
→ `app/agents/ask/graph.py::run_ask_graph(active_scope=...)` → `AgentState.active_scope` →
`app/retrieval/capability.py::retrieve` via `RetrievalRequest.scope` →
`app/retrieval/hybrid.py::scoped_hybrid_search(scope=...)` → `_partition_by_scope`.

The same `AgentState.active_scope` also feeds the recall node and the envelope's `active_scope_id`,
so the scope the prefilter filtered on and the scope the envelope declares cannot diverge within a
turn. `RetrievalRequest.scope` was previously diagnostic-only metadata; it is now load-bearing.

### Source of truth for the active scope

**Chosen: the request context.** The caller states the active scope for the turn; the process-level
`ASK_DOMAIN_SCOPE` remains the default when the request binds none.

The two alternatives were rejected on evidence, not preference:

- **`ActiveContextSet` / WSP.** `docs/boundaries/WSP.md` is the documented authority for effective
  scope, and WSP does have running code — `app/vault/active_context.py::ActiveContextResolver`. But
  that resolver returns `scope` with status `unknown` and the explicit reason "Scope is not resolved
  by the current active-vault runtime." Binding retrieval to it today would leave the prefilter
  exactly as dormant as before. WSP remains the intended long-term authority; when its resolver
  starts returning a known scope it should take precedence over the request binding, and that
  precedence rule is the follow-up, not this slice.
- **Deriving scope from the active vault/workspace selection.** This is available today and would
  have activated the prefilter without any API change — and it is precisely the `activeVault
  collapse` failure mode `docs/boundaries/WSP.md` names: scope reduced to a scalar vault/folder/
  device pointer. Scope is frame/audience/policy context, not a folder.

Binding is not authorization. WSP supplies context and never grants access, so a bound scope can
only narrow what retrieval admits. Cross-scope admission stays a governed `CrossScopeFlow` decision
(#2314), and excluded-but-relevant material still surfaces as a content-free `ScopeDenial`.

### Fail-safe posture and what stayed unchanged

- **The unscoped default is unchanged.** No bound scope and no `ASK_DOMAIN_SCOPE` still means every
  document is eligible. This slice activates a binding channel; it does not flip the default from
  admit-all to deny-all.
- **`ASK_DOMAIN_SCOPE` stays supported** as the process-level default, so `tests/evals/_app_adapter.py`,
  `tests/boundaries/test_domain_separation_defaults.py`, and `app/eval/golden.py` (which deliberately
  *clears* it so a leaked scope cannot prefilter the deterministic gate) keep their current
  semantics without edits.
- **The evidence-role clamp never upgrades.** `evidence_role_in_context` now survives the
  `RetrievalHit` capability boundary (`from_hybrid` / `to_hybrid_dict`) instead of being dropped and
  silently re-defaulted to the intrinsic role at the envelope. The seam re-clamps against the hit's
  own intrinsic role, and the envelope clamps again; both are non-upgrading, so carrying the value
  can only preserve a downgrade, never manufacture an upgrade.
- **Entrypoints that do not bind a scope are unchanged**, and still resolve the ambient default:
  `app/agents/qa/agent.py`, `app/components/retrieval.py`, `app/api/routes/search.py`,
  `app/api/routes/context_bundles.py`, `app/curation/contradiction.py`, `app/expansion/connect.py`,
  and `app/retrieval/production_bundle.py`.

## Concretely

```bash
pytest -q tests/evals/test_general_knowledge_crosses_clean.py \
          tests/evals/test_rpg_not_confused_with_software.py \
          tests/evals/test_private_not_in_work_results.py     # pass un-xfailed against app path
pytest -q tests/retrieval/test_scope_prefilter_before_rank.py
```

## Why This Matters

While enforcement lives only in a test-only package, the runtime speaks untyped dicts and every new
consumer widens the formal-model/implementation split (CW-4). Bounded context is the substrate the
governance chain assumes: without it, an agent can read raw index rows across scopes and denials
vanish silently — the exact contamination the corpus (#2551) exists to catch.

## Acceptance Criteria

- [ ] Scope/policy eligibility is applied before ranking in the live entrypoint; ineligible material
      never enters the scored candidate set.
      Verify: `tests/retrieval/test_scope_prefilter_before_rank.py::test_prefilter_precedes_ranking` — the test drives `app.retrieval.hybrid.hybrid_search` (production entrypoint) and asserts prefilter runs before scoring.
- [ ] Excluded relevant material is recorded as a content-free denial (class + scope, no body).
      Verify: `tests/retrieval/test_scope_prefilter_before_rank.py::test_denials_are_content_free`
- [ ] `evidence_role_in_context` never exceeds the intrinsic evidence role.
      Verify: `tests/retrieval/test_scope_prefilter_before_rank.py::test_in_context_role_clamped`
- [ ] The ASK/chat consumption path receives a schema-valid `ContextEnvelope`, not raw dicts;
      the envelope carries no raw-access/storage field.
      Verify: `tests/retrieval/test_envelope_consumption.py::test_ask_consumes_envelope` — asserts the envelope is assembled and validated at the production seam consumed by `app.api.routes.ask` / `app.activation.ask_synthesis.build_retrieval_candidates`.
- [ ] The three eval skeletons pass un-xfailed against the app runtime path.
      Verify: `tests/evals/test_general_knowledge_crosses_clean.py`, `tests/evals/test_rpg_not_confused_with_software.py`, `tests/evals/test_private_not_in_work_results.py`

## How to Verify (Pre-Merge)

1. `pytest -q tests/retrieval/test_scope_prefilter_before_rank.py tests/retrieval/test_envelope_consumption.py tests/evals/`.
2. Full `pytest -q -m "not pg"` + `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m uat_integrated_runtime`
   (retrieval hot path).
3. `ruff check app tests`.
4. Update the stale "Slice #2025" pointer in `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`
   (lines 1, 201–203) to name this task as the `app/`-enforcement delivery.

## Out of Scope

- Lexical mirror + hybrid fusion (stays with #2314 W4-RET-01's other half).
- Any change to `mimer_runtime/` semantics — this task consumes them as the reference.
- The durable-index read path itself (KERNEL-05 delivers it; this task layers on top).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: I-A5, CW-4`
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` (predicate; stale #2025 pointer corrected here)
- `schemas/context-envelope.schema.json`, `docs/testing/invariant-tests.md` (invariants 5/6/18/19/21)
- `mimer_runtime/retrieval.py`, `mimer_runtime/context.py` (reference implementation)

## Related GitHub Issues

This is the largest task in the capability and **MAY split into 2–3 issues** at filing/delivery
time. Natural split lines: (1) **scope prefilter + content-free denials + role clamp** in
`hybrid_search`; (2) **ContextEnvelope assembly + consumption** at the ASK/chat seam; (3) **eval
conversion** of the three skeletons to the app path. Splitting keeps each issue's enforcement AC
bound to one production entrypoint. TCD hint: Opus / xhigh effort (cross-cutting architecture:
retrieval hot path + consumption seam + eval rewire). Escalate on any new store generation surprise.
