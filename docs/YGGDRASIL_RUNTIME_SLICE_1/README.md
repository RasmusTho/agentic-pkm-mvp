# Yggdrasil Runtime Vertical Slice 1 — Capture to Bounded Context

State: Specification directory — child issues filed, delivery not yet started. Parent feature issue:
**#2578** (live validation hub). Child issues: #2579 (ready) → #2580 → #2581 → #2582 → #2583 → #2584
→ #2585 → #2586 (blocked, sequential chain).

SBS classification: **Product / Runtime System.** This slice builds the first runtime spine of the
Product System. The OEF-facing fitness surface (invariant registry, eval corpus) is touched only to
record enforcement status — no Builder System / BuilderOps authority is created here.

## Purpose

Convert the *first narrow subset* of the Yggdrasil architecture contracts into executable runtime
behavior, and turn the supporting xfail invariant/eval skeletons into honestly passing tests. The
goal is not to build the system — it is to make the first architecture chain executable and prove the
spine end to end:

```
Capture → MetadataBundle → DRI segment → Retrieval prefilter → RCA result → ContextEnvelope
```

## Foundational design decision — corpus-backed slice, new `yggdrasil_runtime` package

The xfail skeletons (`tests/invariants/_helpers.py`, `tests/evals/_helpers.py`) import a **new
top-level package `yggdrasil_runtime`** and call exact entry points. They xfail *only* while that
package is absent; the moment it exists, their real assertions run. This slice therefore:

1. **Builds a clean `yggdrasil_runtime` package** implementing those exact entry points. It does
   **not** rewire the legacy `app/` capture/index/retrieval pipeline (that pipeline stays as-is; it
   is out of scope).
2. **Operates over the synthetic anti-contamination corpus** at `tests/evals/fixtures/` (the five
   scope groups: `work_project_alpha`, `work_project_beta`, `private_programming`,
   `rpg_worldbuilding`, `general_programming`). The corpus *is* the runtime store for this slice — no
   real vault, no durable mutation, no WriteGuard write path.
3. **Reuses `app/` primitives only where trivial** (e.g. an embedding/similarity helper) — never as a
   dependency that drags in the legacy data shapes.

This keeps the slice narrow, makes every xfail target reachable, and honors every non-goal below.

### Exact runtime contract the tests pin (do not drift from these signatures)

| Module | Entry point | Returns (attributes asserted by tests) |
| --- | --- | --- |
| `yggdrasil_runtime.capture` | `capture(text: str, principal_id: str)` | obj with `.metadata_bundle.scope_id`, `.metadata_bundle.source_role` |
| `yggdrasil_runtime.dri` | `derive_segment(artifact_id: str)` | segment with `.metadata_bundle.derived_from`, `.metadata_bundle.scope_id`, `.metadata_bundle.provenance_event_ids` (all on the embedded bundle — no top-level duplicates) |
| `yggdrasil_runtime.retrieval` | `retrieve(query: str, active_scope_id: str)` | result with `.candidate_items[]`, each `.metadata_bundle.scope_id`, `.metadata_bundle.evidence_role`, `.admissibility_status`, `.evidence_role_in_context` |
| `yggdrasil_runtime.cross_scope` | `evaluate(source_scope, target_scope, operation, flow)` | decision with `.allowed: bool`, `.evidence_role_in_target` (when allowed) |
| `yggdrasil_runtime.context` (new test) | `assemble_envelope(retrieval_result, *, active_workspace_id, active_scope_id, principal_id, user_intent)` | ContextEnvelope conforming to `schemas/context-envelope.schema.json` |

A shared `yggdrasil_runtime.metadata.MetadataBundle` type, conformant with
`schemas/metadata-bundle.schema.json`, underlies all of the above. No naked vectors/chunks.

## Runtime slice scope

Implement only the chain above, corpus-backed. Each stage produces objects carrying a MetadataBundle;
eligibility/scope policy precedes ranking; retrieval emits candidate evidence (never truth); the
ContextEnvelope is bounded context only (no raw vault/index access) and references — never replaces —
ContextBundle.

## Non-goals (explicitly excluded)

machine memory runtime; memory promotion; durable mutation; AuthorityTransition runtime; WriteGuard
runtime beyond references/stubs; sync/federation; external tool execution; broad agent orchestration;
full policy engine; production UI overhaul; real cross-vault automation beyond test fixtures;
embeddings/reranking sophistication beyond what is already available and trivial. Parent-scope
aggregation (`yggdrasil_runtime.scope`) and replica sync (`yggdrasil_runtime.sync`) are **not** built
here — their xfails stay xfail.

## Source-of-truth docs

- `docs/foundation/yggdrasil-architecture-context-packet.md`
- `docs/foundation/00-yggdrasil-doctrine.md`
- `docs/architecture/traceability-matrix.md`, `functional-ontology.md`, `semantic-dimensions.md`,
  `cross-scope-flow.md`, `metadata-bundle.md`, `context-envelope.md`, `retrieval-contract.md`
- `docs/boundaries/README.md` + `HKA.md`, `SIP.md`, `PDM.md`, `GOV.md`, `RCA.md`, `CAO.md`, `WSP.md`,
  `OEF.md`
- `schemas/metadata-bundle.schema.json`, `schemas/context-envelope.schema.json`,
  `schemas/retrieval-result.schema.json`, `schemas/_defs.schema.json`
- `docs/testing/invariant-tests.md`, `tests/invariants/`, `tests/evals/`

## Architecture boundaries owned per stage

- **Capture/MetadataBundle** — WSP (active scope binding), SIP (provenance/semantic identity), HKA
  (artifact identity), PDM (persistence mechanics, in-memory here).
- **DRI segment** — DRI (derived/rebuildable representation), SIP (provenance continuity), PDM.
- **Retrieval prefilter** — GOV (admissibility/prefilter policy, CrossScopeFlow), RCA (retrieval),
  WSP (active scope/principal).
- **RetrievalResult** — RCA (candidate packaging), SIP (candidate identity single source), GOV
  (evidence-role admissibility, no upgrade).
- **ContextEnvelope** — RCA (context packaging), CAO (bounded-context consumer), GOV (policies,
  denied scopes, escalation).
- **Invariant/eval visibility** — OEF (records enforcement status; never sets policy).

## Invariants this epic turns green

Runtime-skeleton xfails this slice flips to passing (auto-flip once the module exists, then real
assertions run):

| Invariant | Test | Delivered by |
| --- | --- | --- |
| `capture_stamps_scope` | `tests/invariants/test_metadata_bundle.py::test_capture_stamps_scope` | CAPTURE_EMITS_METADATA_BUNDLE |
| `provenance_survives_derivation` | `tests/invariants/test_metadata_bundle.py::test_provenance_survives_derivation` | DRI_SEGMENT_CARRIES_PROVENANCE |
| `retrieve_scope_prefilter` | `tests/invariants/test_cross_scope_flow.py::test_retrieve_scope_prefilter` | RETRIEVAL_PREFILTER_BEFORE_RANKING |
| `similarity_not_permission` | `tests/invariants/test_cross_scope_flow.py::test_similarity_is_not_permission` | RETRIEVAL_PREFILTER_BEFORE_RANKING |
| `cross_scope_only_via_flow` | `tests/invariants/test_cross_scope_flow.py::test_cross_scope_only_via_flow` + `tests/evals/test_general_knowledge_crosses_clean.py::test_general_knowledge_crosses_clean` | RETRIEVAL_PREFILTER_BEFORE_RANKING |
| `private_not_in_work_results` | `tests/evals/test_private_not_in_work_results.py::test_private_not_in_work_results` | RETRIEVAL_PREFILTER_BEFORE_RANKING |
| `rpg_not_confused_with_software` | `tests/evals/test_rpg_not_confused_with_software.py::test_rpg_not_confused_with_software` | RETRIEVAL_RESULT_CANDIDATE_SEMANTICS |
| `retrieval_cannot_upgrade_intrinsic_non_evidence` (runtime monotonicity) | `tests/invariants/test_retrieval_result.py::test_retrieval_full_evidence_monotonicity_runtime` | RETRIEVAL_RESULT_CANDIDATE_SEMANTICS |

Already static/schema-green — this slice must keep them green by making the runtime objects conform
(not regress): `metadata_bundle_required`, `store_no_naked_vectors`,
`retrieval_candidate_identity_single_source`, `context_envelope_has_no_raw_vault_or_index_access`,
`denied_scope_does_not_leak_identity`, `context_bundle_is_not_context_envelope`, and the schema part
of `retrieval_cannot_upgrade_intrinsic_non_evidence`. CONTEXT_ENVELOPE_ASSEMBLY adds a **new** runtime
assembly test exercising these against a runtime-built envelope.

Deliberately **left xfail** (future slices — these are the actual runtime-skeleton xfails that stay
xfail, the set #2585's residue guard asserts unchanged): `promote_requires_governance`,
`authority_transition_required_for_durable_mutation`, `execution_cannot_authorize_itself`,
`parent_aggregation_not_sibling_sharing`, `sync_preserves_boundaries`, `projection_not_evidence`,
`observability_not_policy`, `storage_write_is_not_authority_transition`, `propose_when_uncertain`.

Note: `remember_not_canonical` (`tests/invariants/test_agent_memory.py::test_remember_not_canonical`)
is **already static/schema-green today** (it does not use `require_future_runtime`), so it is *not* a
residual runtime xfail — the future memory-promotion runtime xfail is `promote_requires_governance`.
#2585's `test_expected_xfail_set_is_unchanged` must list only the runtime-skeleton xfails above and
must not expect `remember_not_canonical` to be xfail.

## Implementation tasks (execution order)

The order is one flat chain — do not start a task before its predecessor's contract exists.

1. [RUNTIME_INVENTORY_AND_INTEGRATION_MAP](RUNTIME_INVENTORY_AND_INTEGRATION_MAP.md) — inventory; no behavior change.
2. [CAPTURE_EMITS_METADATA_BUNDLE](CAPTURE_EMITS_METADATA_BUNDLE.md) — `capture()` + shared MetadataBundle.
3. [DRI_SEGMENT_CARRIES_PROVENANCE](DRI_SEGMENT_CARRIES_PROVENANCE.md) — `derive_segment()`, no naked representation.
4. [RETRIEVAL_PREFILTER_BEFORE_RANKING](RETRIEVAL_PREFILTER_BEFORE_RANKING.md) — eligibility prefilter + `cross_scope.evaluate()`.
5. [RETRIEVAL_RESULT_CANDIDATE_SEMANTICS](RETRIEVAL_RESULT_CANDIDATE_SEMANTICS.md) — full RetrievalResult contract.
6. [CONTEXT_ENVELOPE_ASSEMBLY](CONTEXT_ENVELOPE_ASSEMBLY.md) — bounded ContextEnvelope from RetrievalResult.
7. [CONVERT_INVARIANT_XFAILS_TO_PASSING](CONVERT_INVARIANT_XFAILS_TO_PASSING.md) — green suite, residual xfails explicit.
8. [DOCUMENTATION_WRITEBACK_AND_TRACEABILITY](DOCUMENTATION_WRITEBACK_AND_TRACEABILITY.md) — registry + matrix writeback; parent closure.

## Cross-Task Invariants / Interaction Safety

Tasks 2–6 share the `yggdrasil_runtime` package and a single data spine; tasks 4 and 5 co-own the
same `retrieve()` function. The following invariants must hold *across* tasks:

- **Single MetadataBundle type.** Tasks 2–6 all use one
  `yggdrasil_runtime.metadata.MetadataBundle`. A second, divergent bundle shape anywhere breaks
  `store_no_naked_vectors` and candidate-identity single-source. Task 2 defines it; later tasks
  import it, never redefine it.
- **Prefilter-before-ranking is monotone under enrichment.** Task 4 establishes that the candidate
  set is scope/policy-eligible *before* ranking. Task 5 enriches each candidate's
  `admissibility_status`, `evidence_role_in_context`, and the denied/escalated list — but must never
  re-admit a candidate Task 4's prefilter excluded. Enrichment may only *narrow* or *annotate*, never
  *widen*, the eligible set. `scope_policy_prefiltered` stays `true` end to end.
- **Identity flows one way and never leaks.** A denied/cross-scope candidate excluded at the
  prefilter (Task 4) must remain content-free through RetrievalResult (Task 5) and ContextEnvelope
  (Task 6): no `scope_id`, `object_id`, content, or provenance for denied material crosses into the
  envelope's `denied_scopes`. The partial-failure path to guard: a candidate that becomes
  `requires_confirmation` or `escalated` mid-pipeline must still surface content-free in the denied
  list, not be dropped silently (silent drop reads as "nothing was withheld" — a trust failure).
- **Envelope composes, never replaces, the bundle.** Task 6's ContextEnvelope references
  ContextBundle ids with `non_authority: true`; it must not inline a bundle's authority or restate it
  as a new source of truth. `context_bundle_is_not_context_envelope` must stay green.
- **Evidence role is orthogonal and non-upgrading across the whole chain.** `source_role`,
  `authority_state`, and `evidence_role` set at capture (Task 2) and inherited at derivation (Task 3)
  may be *downgraded* in retrieval context (Task 5) but never upgraded toward `evidence`. This holds
  transitively from capture through envelope.

If any of these cannot be stated for a proposed implementation, the slice boundaries are wrong —
re-cut before proceeding.

## Acceptance criteria (capability-level)

- [ ] `yggdrasil_runtime` package exists with `capture`, `dri`, `retrieval`, `cross_scope`,
  `context`, and `metadata` modules implementing the pinned signatures.
  - Verify: `pytest -q tests/invariants tests/evals`
- [ ] All eight targeted invariants — **nine xfail test nodes** (`cross_scope_only_via_flow` covers
  both `tests/invariants/test_cross_scope_flow.py::test_cross_scope_only_via_flow` and
  `tests/evals/test_general_knowledge_crosses_clean.py::test_general_knowledge_crosses_clean`) — pass;
  all nine deliberately-left xfail test nodes remain xfail.
  - Verify: `pytest -q tests/invariants tests/evals -rxX` shows the expected split (baseline
    27 passed / 18 xfailed → 9 nodes flip, leaving 9 xfailed). #2585's residue guard asserts the
    expected nodes explicitly so a partially-converted target cannot pass while one node stays xfail.
- [ ] No naked vectors/chunks; every runtime object validates against its schema.
  - Verify: `tests/invariants/test_metadata_bundle.py::test_store_no_naked_vectors` (kept green) +
    new runtime conformance tests.
- [ ] `docs/testing/invariant-tests.md` and `docs/architecture/traceability-matrix.md` reflect the
  new runtime enforcement status.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: Coverage map` **and** the converted
    invariants' per-entry Registry fields (`Current enforcement` / `Eventual test path`), plus
    `docs/architecture/traceability-matrix.md` rows **1–7 and row 16**
    (`provenance_survives_derivation`). See DOCUMENTATION_WRITEBACK_AND_TRACEABILITY (#2586) for the
    full writeback scope — the epic must not close while any of those surfaces remain stale.

## Relationship to GitHub issues

The specification is the source of truth for *what to build*. GitHub issues track *what to pick up
next*. The parent epic **#2578** is the live validation hub; eight child issues map 1:1 to the task
files above and are delivered in order. Each delivered child posts a validation receipt to the parent
before the next is picked up; the final child (#2586) closes the parent.

| Task file | Issue | Status |
| --- | --- | --- |
| RUNTIME_INVENTORY_AND_INTEGRATION_MAP | #2579 | agent:ready |
| CAPTURE_EMITS_METADATA_BUNDLE | #2580 | agent:blocked |
| DRI_SEGMENT_CARRIES_PROVENANCE | #2581 | agent:blocked |
| RETRIEVAL_PREFILTER_BEFORE_RANKING | #2582 | agent:blocked |
| RETRIEVAL_RESULT_CANDIDATE_SEMANTICS | #2583 | agent:blocked |
| CONTEXT_ENVELOPE_ASSEMBLY | #2584 | agent:blocked |
| CONVERT_INVARIANT_XFAILS_TO_PASSING | #2585 | agent:blocked |
| DOCUMENTATION_WRITEBACK_AND_TRACEABILITY | #2586 | agent:blocked |

## Verification path

Per-task: each child PR turns its named xfail(s) green (or adds its named new test) and keeps all
static invariants green. Capability-level: a single `pytest -q tests/invariants tests/evals` run with
the expected xfail residue is the acceptance surface.

## Validation / acceptance path

Post-merge evidence lives in the parent epic body/comments (per-child validation receipts linking the
PR + green run). Owner-doc promotion trigger: once the full chain is green and the registry/matrix are
updated (Task 8), the parent epic closes and the architecture context packet's "first runtime vertical
slice" status line is promoted in the same PR.
