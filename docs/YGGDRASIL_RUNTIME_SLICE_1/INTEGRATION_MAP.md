---
name: Runtime Slice 1 Integration Map
description: Authoritative module → entry-point → build/reuse map for the yggdrasil_runtime package, the corpus-as-runtime-store decision, and the test conversion plan for tasks 2–8
task_id: YRS1-01
source_anchor: docs/YGGDRASIL_RUNTIME_SLICE_1/README.md :: Foundational design decision
parent_capability: Yggdrasil Runtime Vertical Slice 1
---

# Runtime Slice 1 — Integration Map

State: Inventory complete (YRS1-01 / #2579). No behavior change. This map is the contract that keeps
the tasks 2–8 child PRs coherent: it pins the exact `yggdrasil_runtime` module shape, the
corpus-as-runtime-store decision, and which xfail each later task converts.

This map is subordinate to `docs/YGGDRASIL_RUNTIME_SLICE_1/README.md` (the capability spec). Where
the README and this file agree, the README wins; this file only adds implementation-level detail and
the legacy `app/` inventory the README does not carry.

## Foundational decision (confirmed)

- **Build a new top-level `yggdrasil_runtime` package.** The xfail skeletons import
  `yggdrasil_runtime.<module>` (see `tests/invariants/_helpers.py::FUTURE_RUNTIME_PACKAGE` and
  `tests/evals/_helpers.py::FUTURE_RUNTIME_PACKAGE`, both literally `"yggdrasil_runtime"`). The
  package does **not** exist today — confirmed by the 18 dynamic xfails in
  `pytest -q tests/invariants tests/evals` (all xfail via `require_future_runtime`, none via a static
  `@pytest.mark.xfail`).
- **Do not rewire the legacy `app/` pipeline.** It stays as-is and out of scope (see
  [Legacy `app/` inventory](#legacy-app-inventory)).
- **Reuse `app/` primitives only where trivial** (e.g. a cosine/similarity helper) and only as a pure
  function — never importing legacy data shapes (`ScoredNeighbor`, `ContextBundle`, ORM rows) into the
  runtime spine.

## Runtime store

**The synthetic anti-contamination corpus *is* the runtime store for this slice.** Source:
`tests/evals/fixtures/` with the five scope groups `work_project_alpha`, `work_project_beta`,
`private_programming`, `rpg_worldbuilding`, `general_programming`
(`tests/evals/_helpers.py::GROUPS`). No real vault, no DB, no durable mutation, no WriteGuard write
path.

- `yggdrasil_runtime.corpus` loads the fixtures and parses their flat `key: value` frontmatter,
  reusing the semantics of `tests/evals/_helpers.py::parse_frontmatter` / `load_corpus` /
  `load_group` (a runtime equivalent — the runtime package must not import from `tests/`). Required
  metadata keys per `tests/evals/_helpers.py::REQUIRED_META_KEYS`: `scope_id`, `sphere`,
  `source_role`, `authority_state`, `evidence_role`, `sensitivity`.
- `retrieve()` reads the five fixture groups through `corpus`, maps each doc to a
  `MetadataBundle`-carrying candidate, applies the scope/policy prefilter **before** any lexical
  ranking, then ranks the eligible set.

## Module map

Each `yggdrasil_runtime` module, its test-pinned entry point (verbatim from the skeletons), the
build/reuse decision, and the legacy `app/` reference (context only — not a dependency).

| Module | Entry point (pinned by tests) | Returns / asserts | Decision | Legacy `app/` reference (context only) |
| --- | --- | --- | --- | --- |
| `yggdrasil_runtime.metadata` | `MetadataBundle` dataclass/model | conforms to `schemas/metadata-bundle.schema.json`; fields incl. `object_id`, `object_type`, `scope_id`, `source_role`, `authority_state`, `evidence_role`, `sensitivity`, provenance, `derived_from` | **NEW** (shared type; Task 2 defines, tasks 3–6 import) | `app/context_bundles/schema.py` (Pydantic style precedent only) |
| `yggdrasil_runtime.corpus` | `load_corpus()` / `load_group(group)` runtime equivalent | `MetadataBundle`-carrying docs from `tests/evals/fixtures/` | **NEW** (mirrors `tests/evals/_helpers.py` semantics; no `tests/` import) | `app/index/ingest_md.py` (frontmatter ingest precedent) |
| `yggdrasil_runtime.capture` | `capture(text: str, principal_id: str)` | obj `.metadata_bundle.scope_id`, `.metadata_bundle.source_role` | **NEW** | `app/capture/writer.py::generate_notes` (no bundle today) |
| `yggdrasil_runtime.dri` | `derive_segment(artifact_id: str)` | segment `.metadata_bundle.derived_from`, `.metadata_bundle.scope_id`, `.metadata_bundle.provenance_event_ids` (all on the embedded bundle) | **NEW** | `app/index/ingest_md.py`, `app/store/vector_index.py` (naked rep today) |
| `yggdrasil_runtime.cross_scope` | `evaluate(source_scope, target_scope, operation, flow)` | decision `.allowed: bool`, `.evidence_role_in_target` (when allowed) | **NEW** | `app/governance/*` (CrossScopeFlow not modeled today) |
| `yggdrasil_runtime.retrieval` | `retrieve(query: str, active_scope_id: str)` | result `.candidate_items[]`, each `.metadata_bundle.scope_id/.evidence_role`, `.admissibility_status`, `.evidence_role_in_context` | **NEW** (Task 4 prefilter+rank; Task 5 candidate semantics — co-owned) | `app/components/retrieval.py::search`, `app/store/vector_index.py::VectorIndex.search_by_text` (rank-only, no scope prefilter) |
| `yggdrasil_runtime.context` | `assemble_envelope(retrieval_result, *, active_workspace_id, active_scope_id, principal_id, user_intent)` | ContextEnvelope conforming to `schemas/context-envelope.schema.json` | **NEW** | `app/context_bundles/schema.py::ContextBundle` (referenced, **never replaced**) |

**Reuse-trivially candidate:** a cosine/lexical similarity helper. `app/store/vector_index.py::VectorIndex._cosine`
is a pure function precedent; the slice prefers a simple deterministic **lexical** score after
prefilter (README: no embeddings/vector DB sophistication), so a tiny local scorer is acceptable
rather than importing the legacy class.

**Do NOT create these submodules** (their xfails must stay xfail — future slices):
`yggdrasil_runtime.authority`, `.storage`, `.execution`, `.memory`, `.agent`, `.scope`, `.sync`,
`.projection`, `.observability`. Because `require_future_runtime` xfails only when the *exact* target
module (or an ancestor) is missing, leaving these absent keeps their skeletons honestly xfail even
after the package root exists.

## Test conversion plan

Baseline (pre-slice): `pytest -q tests/invariants tests/evals` → **27 passed, 18 xfailed**. The
xfails are dynamic (`require_future_runtime`), so each auto-flips to a real pass the instant its
module exists — there are no static markers to strip.

Targeted conversions (8 invariants / 9 test functions) and the static invariants each task must keep
green:

| Task / Issue | Module(s) created | Xfail test(s) auto-converted | Static invariants kept green |
| --- | --- | --- | --- |
| #2580 capture | `metadata`, `capture` (+ `corpus`) | `test_metadata_bundle.py::test_capture_stamps_scope` | `metadata_bundle_required`, `store_no_naked_vectors` |
| #2581 dri | `dri` | `test_metadata_bundle.py::test_provenance_survives_derivation` | `store_no_naked_vectors` |
| #2582 retrieval prefilter | `retrieval`, `cross_scope` | `test_cross_scope_flow.py::test_retrieve_scope_prefilter`, `::test_similarity_is_not_permission`, `::test_cross_scope_only_via_flow`; `test_general_knowledge_crosses_clean.py::test_general_knowledge_crosses_clean`; `test_private_not_in_work_results.py::test_private_not_in_work_results`. **Import-gate:** creating `retrieval.py` also auto-enables #2583's `test_retrieval_full_evidence_monotonicity_runtime` + `test_rpg_not_confused_with_software`, so #2582 must give each candidate a non-upgrading `evidence_role_in_context` (default = intrinsic) to keep them green | `retrieve_scope_prefilter` (`scope_policy_prefiltered`) |
| #2583 RetrievalResult | `retrieval` (enrich) | *keeps green* (auto-enabled at #2582): `test_rpg_not_confused_with_software`; `test_retrieval_full_evidence_monotonicity_runtime` — #2583 adds explicit downgrades/denied-list/schema conformance without regressing | `retrieval_candidate_identity_single_source`, `denied_scope_does_not_leak_identity`, schema part of `retrieval_cannot_upgrade_intrinsic_non_evidence` |
| #2584 ContextEnvelope | `context` | (no existing xfail — adds a **new** runtime assembly test) | `context_envelope_has_no_raw_vault_or_index_access`, `context_bundle_is_not_context_envelope` |
| #2585 xfail honesty gate | none (adds `tests/invariants/test_invariant_residue.py`) | confirms the 8 above pass; asserts residual xfail set unchanged | all of the above |
| #2586 docs writeback | none | — | registry + matrix reflect runtime enforcement |

**Deliberately left xfail (future slices) — must stay xfail:** `promote_requires_governance`,
`authority_transition_required_for_durable_mutation`, `execution_cannot_authorize_itself`,
`parent_aggregation_not_sibling_sharing`, `sync_preserves_boundaries`, `projection_not_evidence`,
`observability_not_policy`, `storage_write_is_not_authority_transition`, `propose_when_uncertain`
(9 test functions). Expected post-slice split: 9 dynamic xfails convert → **~36 passed, 9 xfailed**
(plus the new #2584 envelope test and #2585 residue tests).

## Cross-task object-model invariants

(Restated from README "Cross-Task Invariants" — the load-bearing ones for keeping PRs coherent.)

- **Single MetadataBundle type.** One `yggdrasil_runtime.metadata.MetadataBundle`. Task 2 defines it;
  tasks 3–6 import, never redefine.
- **Prefilter-before-ranking is monotone under enrichment.** Task 5 may only narrow/annotate, never
  widen, Task 4's eligible set; `scope_policy_prefiltered` stays `true` end to end.
- **Identity flows one way and never leaks.** Denied/cross-scope material stays content-free through
  RetrievalResult and ContextEnvelope (no `scope_id`/`object_id`/content/provenance in
  `denied_scopes`); `requires_confirmation`/`escalated` candidates surface content-free, never
  silently dropped.
- **Envelope composes, never replaces, the bundle.** ContextEnvelope references ContextBundle ids
  with `non_authority: true`.
- **Evidence role orthogonal and non-upgrading** from capture → derivation → retrieval context →
  envelope (may downgrade, never upgrade toward `evidence`).

## Legacy `app/` inventory

Out of scope for this slice — recorded so the boundary is explicit and the gap is not mistaken for
slice work.

- **Capture:** `app/capture/writer.py::generate_notes(bundle)` writes note artifacts; it does not
  emit a MetadataBundle and does not stamp scope/source/authority/evidence at capture time.
- **Index / ingest:** `app/index/ingest_md.py`, `app/indexer/`, `app/ingest/` parse and embed notes.
- **Naked-vector gap:** `app/store/vector_index.py` exposes `VectorIndex.search_by_text/​similar`
  returning `ScoredNeighbor` (a `uuid` + cosine score) — a naked vector representation with no
  attached MetadataBundle. `app/components/retrieval.py::search`/`embed_query`/`embed_docs` rank by
  embedding similarity with no scope/policy prefilter contract. This is exactly the "similarity is
  not permission" gap the new package addresses for the corpus; **the legacy path is deliberately
  left unchanged.**
- **Unbounded-context gap:** the existing RCA bundle `app/context_bundles/schema.py::ContextBundle`
  (with `construction.py` / `runtime_registry.py`) is the object the new ContextEnvelope **references
  and must not replace**. Legacy context loading (`app/context_loader.py`, `app/services/note_context.py`)
  can reach store/index directly; the new ContextEnvelope must carry bounded context only (no raw
  vault/index access).

A full re-wire of the legacy pipeline onto `yggdrasil_runtime` is a **future** decision, explicitly
not part of slice 1.
