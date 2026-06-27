State: Canonical Yggdrasil invariant test registry. Docs-only control document for the architecture-foundation backlog (#2533–#2552); names the architecture fitness rules (invariants) that future runtime implementation must satisfy, and maps each to its principle, boundaries, contract/schema, ADR, fixture, enforcement posture, and eventual test path. Does not claim shipped runtime behavior.
Doc role: Testing / fitness registry (architecture fitness rules)
Authority: Owns the canonical list of named architecture invariants (fitness probes) for the Yggdrasil foundation. For each invariant it answers: which doctrine principle it protects, which control boundaries own it, which contract/schema (if any) already expresses it, how it fails when violated, how it is currently enforced, and which test will eventually pin it. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/functional-ontology.md`, `docs/architecture/semantic-dimensions.md`, `docs/architecture/cross-scope-flow.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, and the per-invariant contracts under `docs/architecture/`. It does not set policy: OEF observes and evaluates; GOV owns normative policy and authority decisions.
Owner: OEF — Observability, Evaluation & Fitness (registry); CES practice (rule lifecycle)
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (invariant → probe mapping); subordinate to the doctrine, ontology, semantic dimensions, contracts, and boundary charters it maps
Last reviewed: 2026-06-27
Last verified against: docs/architecture/traceability-matrix.md, docs/foundation/00-yggdrasil-doctrine.md, docs/architecture/semantic-dimensions.md, docs/architecture/cross-scope-flow.md, docs/architecture/metadata-bundle.md, docs/architecture/context-envelope.md, docs/architecture/memory-model.md, docs/architecture/authority-transition-flow.md, docs/architecture/retrieval-contract.md, docs/boundaries/README.md, schemas/README.md

# Yggdrasil Invariant Test Registry

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Registry issue: [#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550) ·
Eval corpus: [#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551) ·
Test skeletons: [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552)

The doctrine and the [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) are only useful if
they become **executable fitness criteria**. This registry is the canonical list of named architecture
invariants — the probes that future implementation must satisfy and that make hidden boundary collapse
visible. It turns the [traceability matrix](../architecture/traceability-matrix.md) principle rows into
named, testable obligations, captures the cross-field invariants the [schemas](../../schemas/README.md)
could not express declaratively, and points each one at the fixture and test that will eventually pin
it.

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md), the
[traceability matrix](../architecture/traceability-matrix.md), the
[semantic dimensions](../architecture/semantic-dimensions.md), and the per-contract docs under
[`docs/architecture/`](../architecture/). The anti-contamination fixtures that several invariants
require are in [`tests/evals/fixtures/`](../../tests/evals/fixtures/README.md); the initial test
skeletons are under [`tests/invariants/`](../../tests/invariants/) and
[`tests/evals/`](../../tests/evals/).

> **This registry is not policy.** It is an OEF fitness surface: it makes drift *visible*. GOV owns
> normative policy and authority decisions; OEF reveals *that* an invariant held or broke and never
> closes the loop itself ([OEF charter](../boundaries/OEF.md)). An invariant here describes what the
> architecture must never silently do — not a new approval gate.

## How to read an entry

Each invariant carries:

- **Purpose** — the failure it exists to prevent, in one line.
- **Protected principle** — the [traceability-matrix](../architecture/traceability-matrix.md) row(s)
  and doctrine commitment it defends.
- **Affected boundaries** — the Level 2 control boundaries that own or must honour it.
- **Required fixture / data** — what data a test needs (a schema, a fixture group, a synthetic object).
- **Expected failure mode** — what a violation looks like in practice (the thing the probe catches).
- **Current enforcement** — one or more of the categories below.
- **Eventual test path** — where the probe lives or will live (`TBD` if no skeleton exists yet).
- **Related docs / contracts / ADRs** — the canonical sources.
- **Related issues** — the backlog items that own the work.

### Enforcement categories

| Category | Meaning |
| --- | --- |
| `doc_only` | Stated normatively in a doc/charter; no machine check yet. |
| `schema_enforced` | A JSON schema under [`schemas/`](../../schemas/README.md) structurally enforces it (fully or in part). |
| `static_test` | A non-runtime test asserts it against a current artifact (schema, fixture, doc) and **passes today**. |
| `xfail_runtime_skeleton` | A test exists but is `xfail` (strict) because the runtime path it asserts is not implemented. |
| `future_runtime` | No runtime and no skeleton yet; the probe is named here for when the slice lands. |

An invariant may be partly `schema_enforced` *and* carry an `xfail_runtime_skeleton` — the schema
blocks the structurally-expressible part, the skeleton holds the cross-field or runtime part. The
[schemas/README §Known JSON Schema limits](../../schemas/README.md) lists exactly which checks are
declarative-schema-impossible and therefore live here as the source of truth.

## Registry

### capture_stamps_scope

- **Purpose:** Every captured object is stamped with a scope (and the rest of its metadata bundle) at
  capture time — nothing enters the system scope-less.
- **Protected principle:** matrix #2 (scope is frame/audience/policy/provenance); doctrine — capture is
  the first point at which meaning is fixed.
- **Affected boundaries:** HIX, WSP, SIP, HKA.
- **Required fixture / data:** a future capture runtime; the [metadata-bundle schema](../architecture/metadata-bundle.md).
- **Expected failure mode:** a captured artifact without `scope_id`/`source_role` reaches storage, so
  later scope/policy decisions have nothing to act on.
- **Current enforcement:** `schema_enforced` (a bundle without `scope_id` fails validation) + `future_runtime` (capture path).
- **Eventual test path:** `tests/invariants/test_metadata_bundle.py::test_capture_stamps_scope` (xfail).
- **Related docs / contracts / ADRs:** [metadata-bundle](../architecture/metadata-bundle.md); ADR-0027, ADR-0038.
- **Related issues:** #2544, #2550, #2552; runtime: first vertical slice (Capture).

### metadata_bundle_required

- **Purpose:** Every usable object carries the required semantic/provenance envelope; there is no usable
  object without identity, scope, the three role dimensions, and provenance.
- **Protected principle:** matrix #2, #3, #12; doctrine — meaning must be preserved across the system.
- **Affected boundaries:** SIP, HKA, PDM, DRI, RCA.
- **Required fixture / data:** [`schemas/metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json).
- **Expected failure mode:** an object validates while missing `object_id`/`scope_id`/`source_role`/
  `authority_state`/`evidence_role`/provenance — meaning silently lost downstream.
- **Current enforcement:** `schema_enforced` + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_metadata_bundle.py::test_metadata_bundle_required`.
- **Related docs / contracts / ADRs:** [metadata-bundle](../architecture/metadata-bundle.md); ADR-0038.
- **Related issues:** #2544, #2550, #2552.

### store_no_naked_vectors

- **Purpose:** There is no shape for a "naked vector" — a stored chunk/embedding without scope, roles,
  and provenance. Storage carries the bundle; it never strips it.
- **Protected principle:** matrix #12 (storage preserves but does not define meaning), #16.
- **Affected boundaries:** PDM, DRI, SIP.
- **Required fixture / data:** [`schemas/metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json), [`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json).
- **Expected failure mode:** a vector row persisted with only `content` + embedding and no metadata
  bundle, so retrieval cannot reason about scope/authority/evidence.
- **Current enforcement:** `schema_enforced` + `static_test` (passes today — the bundle requires the
  semantic+provenance fields; the candidate schema requires a bundle per item).
- **Eventual test path:** `tests/invariants/test_metadata_bundle.py::test_store_no_naked_vectors`.
- **Related docs / contracts / ADRs:** [metadata-bundle](../architecture/metadata-bundle.md) §4; ADR-0032, ADR-0038.
- **Related issues:** #2544, #2548, #2550, #2552.

### provenance_survives_derivation

- **Purpose:** Derived/rebuildable representations (segments, projections, retrieval results, context
  items) preserve `derived_from` and the original provenance/scope/role metadata.
- **Protected principle:** matrix #3, #16; doctrine — provenance carries justification.
- **Affected boundaries:** DRI, SIP, PDM, RCA.
- **Required fixture / data:** the metadata-bundle schema (conditional `derived_from`); a future DRI
  derivation runtime.
- **Expected failure mode:** a segment/projection drops its lineage, so a derived view becomes the only
  copy of meaning (a misclassified DRI record).
- **Current enforcement:** `schema_enforced` (derived types require `derived_from`) + `xfail_runtime_skeleton` (derivation runtime).
- **Eventual test path:** `tests/invariants/test_metadata_bundle.py::test_provenance_survives_derivation` (xfail).
- **Related docs / contracts / ADRs:** [metadata-bundle](../architecture/metadata-bundle.md), [semantic-dimensions](../architecture/semantic-dimensions.md); ADR-0018, ADR-0024, ADR-0033.
- **Related issues:** #2544, #2550, #2552.

### retrieve_scope_prefilter

- **Purpose:** Scope/policy eligibility is applied **before** ranking; out-of-scope and suppressed
  material is excluded before any vector/similarity step and ranking never reintroduces it.
- **Protected principle:** matrix #1, #7; [RCA charter](../boundaries/RCA.md).
- **Affected boundaries:** RCA, GOV, WSP.
- **Required fixture / data:** [`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) (`scope_policy_prefiltered`); a future retrieval runtime + the [eval corpus](../../tests/evals/fixtures/README.md).
- **Expected failure mode:** the ranker sees candidates from a denied scope and merely sorts them lower
  rather than excluding them, so out-of-scope material can surface on a high similarity score.
- **Current enforcement:** `schema_enforced` (the flag is pinned `true` in data) + `xfail_runtime_skeleton` (prefilter behaviour).
- **Eventual test path:** `tests/invariants/test_cross_scope_flow.py::test_retrieve_scope_prefilter` (xfail).
- **Related docs / contracts / ADRs:** [retrieval-contract](../architecture/retrieval-contract.md) §3; ADR-0024, ADR-0039.
- **Related issues:** #2548, #2550, #2551, #2552.

### similarity_not_permission

- **Purpose:** Embedding/keyword similarity may surface a candidate but never grants the right to
  retrieve across a boundary, cite, import, remember, mutate, or execute. Ranking does not create a flow.
- **Protected principle:** matrix #1 (the headline invariant); doctrine §"similarity is not permission".
- **Affected boundaries:** RCA, GOV, WSP.
- **Required fixture / data:** the [anti-contamination corpus](../../tests/evals/fixtures/README.md) (deliberately overlapping vocabulary) + a future retrieval runtime.
- **Expected failure mode:** Project Beta material is admitted into a Project Alpha answer purely because
  the embeddings were close, with no `CrossScopeFlow`.
- **Current enforcement:** `doc_only`/`schema_enforced` in part (ranking signals inform order only) + `xfail_runtime_skeleton` (admission behaviour).
- **Eventual test path:** `tests/invariants/test_cross_scope_flow.py::test_similarity_is_not_permission` (xfail).
- **Related docs / contracts / ADRs:** [cross-scope-flow](../architecture/cross-scope-flow.md), [retrieval-contract](../architecture/retrieval-contract.md); ADR-0028, ADR-0039.
- **Related issues:** #2539, #2548, #2550, #2551, #2552.

### cross_scope_only_via_flow

- **Purpose:** Material moves or is used across a scope boundary **only** through a typed, directional,
  operation-specific `CrossScopeFlow` — never implicitly, never bidirectionally by default.
- **Protected principle:** matrix #1, #6 (typed flow replaces any `general_knowledge` bypass); doctrine.
- **Affected boundaries:** GOV, RCA, WSP.
- **Required fixture / data:** the eval corpus (sibling work projects, private, RPG, general) + a future
  cross-scope enforcement runtime.
- **Expected failure mode:** a cross-scope use proceeds without a flow grant, or a single grant is
  treated as covering every operation (retrieve ⇒ cite ⇒ import ⇒ mutate).
- **Current enforcement:** `schema_enforced` in part (flow guardrails carried on results/envelopes) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_cross_scope_flow.py::test_cross_scope_only_via_flow` (xfail); `tests/evals/test_general_knowledge_crosses_clean.py::test_general_knowledge_crosses_clean` (xfail).
- **Related docs / contracts / ADRs:** [cross-scope-flow](../architecture/cross-scope-flow.md); ADR-0028.
- **Related issues:** #2539, #2550, #2551, #2552.

### rpg_not_confused_with_software

- **Purpose:** RPG/worldbuilding material (systems, factions, simulation rules, agents, classes) is
  never confused with real-world software/system-design material; it is fiction/analogy, not evidence.
- **Protected principle:** matrix #1, #5 (orthogonal roles); doctrine — fiction is never real-world evidence.
- **Affected boundaries:** RCA, GOV, SIP, WSP.
- **Required fixture / data:** [`tests/evals/fixtures/rpg_worldbuilding/`](../../tests/evals/fixtures/README.md) vs `work_project_*`/`general_programming/` + a future retrieval runtime.
- **Expected failure mode:** an RPG "state machine"/"authority" note is retrieved and cited as real-world
  software guidance because the vocabulary overlaps.
- **Current enforcement:** `static_test` (fixtures are distinctly scoped/roled — passes today) + `xfail_runtime_skeleton` (retrieval discrimination).
- **Eventual test path:** `tests/evals/test_rpg_not_confused_with_software.py::test_rpg_not_confused_with_software` (xfail).
- **Related docs / contracts / ADRs:** [semantic-dimensions](../architecture/semantic-dimensions.md) §4, [cross-scope-flow](../architecture/cross-scope-flow.md); ADR-0029.
- **Related issues:** #2551, #2550, #2552.

### private_not_in_work_results

- **Purpose:** Private learning/programming notes do not leak into work context unless a governed
  promotion/redaction/`CrossScopeFlow` exists; private → work is denied by default.
- **Protected principle:** matrix #1, #2 (scope is an audience/policy boundary); doctrine.
- **Affected boundaries:** WSP, GOV, RCA.
- **Required fixture / data:** [`tests/evals/fixtures/private_programming/`](../../tests/evals/fixtures/README.md) vs `work_project_*` + a future retrieval runtime.
- **Expected failure mode:** a useful private technique surfaces inside a work answer with no flow,
  redaction, or confirmation.
- **Current enforcement:** `static_test` (fixtures denied-by-default scoped — passes today) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/evals/test_private_not_in_work_results.py::test_private_not_in_work_results` (xfail).
- **Related docs / contracts / ADRs:** [cross-scope-flow](../architecture/cross-scope-flow.md) §4; ADR-0028.
- **Related issues:** #2551, #2550, #2552.

### remember_not_canonical

- **Purpose:** Letting machine memory retain cross-scope material (the `remember` operation) never confers
  canonical authority; remembered material stays noncanonical until governed promotion.
- **Protected principle:** matrix #4; doctrine §memory is reconstructive and noncanonical.
- **Affected boundaries:** MEM, GOV, HKA.
- **Required fixture / data:** [`schemas/memory-item.schema.json`](../../schemas/memory-item.schema.json).
- **Expected failure mode:** material crossing under a `remember` grant is treated as accepted/canonical
  in the target scope.
- **Current enforcement:** `schema_enforced` (memory `authority_state` is a `const noncanonical`) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_agent_memory.py::test_remember_not_canonical`.
- **Related docs / contracts / ADRs:** [memory-model](../architecture/memory-model.md), [cross-scope-flow](../architecture/cross-scope-flow.md) §2; ADR-0025, ADR-0030.
- **Related issues:** #2546, #2550, #2552.

### promote_requires_governance

- **Purpose:** Memory promotion into durable human knowledge requires a governed authority transition
  (MEM requests; GOV decides; HKA materialises a separate canonical artifact) with a receipt.
- **Protected principle:** matrix #4, #9, #15; doctrine §governed promotion.
- **Affected boundaries:** MEM, GOV, HKA.
- **Required fixture / data:** [`schemas/memory-item.schema.json`](../../schemas/memory-item.schema.json), [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json); a future promotion runtime.
- **Expected failure mode:** a memory item is promoted to canonical without an `AuthorityTransition` /
  `AuthorityReceipt`, or the memory record itself is flipped to canonical.
- **Current enforcement:** `schema_enforced` in part (transition requires token+receipt; memory cannot
  hold canonical authority) + `xfail_runtime_skeleton` (promotion path).
- **Eventual test path:** `tests/invariants/test_authority_transition.py::test_promote_requires_governance` (xfail).
- **Related docs / contracts / ADRs:** [memory-model](../architecture/memory-model.md) §5, [authority-transition-flow](../architecture/authority-transition-flow.md); ADR-0017, ADR-0019, ADR-0031.
- **Related issues:** #2546, #2547, #2550, #2552.

### projection_not_evidence

- **Purpose:** A projection/dashboard/summary is not evidence by default; it holds `non_evidence` unless
  promoted through a provenance-backed authority receipt.
- **Protected principle:** matrix #8; doctrine §projection is not evidence.
- **Affected boundaries:** DRI, OEF, GOV.
- **Required fixture / data:** [`schemas/metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json) (projection conditional); a future projection runtime.
- **Expected failure mode:** a summary view is cited as primary evidence simply because it appeared in a
  dashboard.
- **Current enforcement:** `schema_enforced` (projection defaults non-evidence; evidence needs `authority_receipt_ref`) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_projection_not_evidence.py::test_projection_not_evidence` (xfail).
- **Related docs / contracts / ADRs:** [metadata-bundle](../architecture/metadata-bundle.md) §3, [context-envelope](../architecture/context-envelope.md); ADR-0018, ADR-0022, ADR-0033, ADR-0037.
- **Related issues:** #2544, #2545, #2550, #2552.

### authority_transition_required_for_durable_mutation

- **Purpose:** Durable human knowledge changes **only** through an `AuthorityTransition`; nothing mutates
  accepted knowledge by a side path.
- **Protected principle:** matrix #9, #15; doctrine §durable change is governed.
- **Affected boundaries:** GOV, HKA.
- **Required fixture / data:** [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json); a future governed-write runtime (WriteGuard / GovernedWriteProtocol).
- **Expected failure mode:** an artifact's accepted/canonical content changes without a transition,
  decision token, or receipt.
- **Current enforcement:** `schema_enforced` in part (approved/canonical transitions require token+receipt) + `xfail_runtime_skeleton` (mutation path).
- **Eventual test path:** `tests/invariants/test_authority_transition.py::test_authority_transition_required_for_durable_mutation` (xfail).
- **Related docs / contracts / ADRs:** [authority-transition-flow](../architecture/authority-transition-flow.md), [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md); ADR-0017, ADR-0019, ADR-0031.
- **Related issues:** #2547, #2550, #2552.

### execution_cannot_authorize_itself

- **Purpose:** Execution consumes authorization; it never mints it. A side effect cannot become its own
  permission.
- **Protected principle:** matrix #10; doctrine §execution cannot self-authorize.
- **Affected boundaries:** CAO, GOV, EXE.
- **Required fixture / data:** [`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json) (`execution_policy.requires_authorization`), [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json); a future EXE/GOV runtime.
- **Expected failure mode:** an `ExecutionEffect` proceeds (or grants authority) without a prior GOV
  grant/receipt.
- **Current enforcement:** `schema_enforced` in part (`requires_authorization` pinned `true`) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_authority_transition.py::test_execution_cannot_authorize_itself` (xfail).
- **Related docs / contracts / ADRs:** [authority-transition-flow](../architecture/authority-transition-flow.md) §4, [EXE charter](../boundaries/EXE.md), [EXECUTION_REQUEST](../contracts/EXECUTION_REQUEST.md); ADR-0019, ADR-0031.
- **Related issues:** #2547, #2550, #2552.

### parent_aggregation_not_sibling_sharing

- **Purpose:** A configured parent/master aggregation is allowed only as declared; it does **not** imply
  sibling sharing. Descendant and sibling scopes stay isolated unless their own flow exists.
- **Protected principle:** matrix #11; doctrine §parent aggregation is not sibling sharing.
- **Affected boundaries:** SFC, GOV, WSP.
- **Required fixture / data:** the eval corpus (sibling work projects Alpha/Beta) + a future scope/sync runtime.
- **Expected failure mode:** Project Alpha reaches Project Beta material because both roll up to the same
  parent, with no Alpha→Beta flow.
- **Current enforcement:** `doc_only` + `static_test` (fixtures keep siblings isolated) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_cross_scope_flow.py::test_parent_aggregation_not_sibling_sharing` (xfail).
- **Related docs / contracts / ADRs:** [cross-scope-flow](../architecture/cross-scope-flow.md) §4; ADR-0034.
- **Related issues:** #2539, #2551, #2550, #2552.

### sync_preserves_boundaries

- **Purpose:** Replication preserves scope/authority boundaries; sync never promotes, rescopes, or
  resolves a semantic conflict by last-writer-wins. A conflict that changes semantic authority is a
  governed transition.
- **Protected principle:** matrix #14; doctrine §sync preserves boundaries.
- **Affected boundaries:** WSP, SFC, GOV.
- **Required fixture / data:** [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json) (`sync_conflict_resolution`); a future SFC runtime.
- **Expected failure mode:** a replica merge silently changes an object's scope or authority state, or a
  conflict is auto-resolved without GOV.
- **Current enforcement:** `schema_enforced` in part (conflict resolution that changes authority requires a transition) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_cross_scope_flow.py::test_sync_preserves_boundaries` (xfail).
- **Related docs / contracts / ADRs:** [authority-transition-flow](../architecture/authority-transition-flow.md) §4, [semantic-dimensions](../architecture/semantic-dimensions.md) (`sync_state`); ADR-0034.
- **Related issues:** #2538, #2547, #2550, #2552.

### observability_not_policy

- **Purpose:** Observability reveals and evaluates; it never decides or mutates. Metrics/eval/drift
  results surface for a GOV decision and never silently steer behavior. An audit trace is not an
  `AuthorityReceipt`.
- **Protected principle:** matrix #13; doctrine §observability is not policy.
- **Affected boundaries:** OEF, GOV.
- **Required fixture / data:** the [OEF charter](../boundaries/OEF.md); a future observability runtime.
- **Expected failure mode:** a drift detector auto-updates policy/memory/ranking, or an audit trace is
  treated as a governance receipt.
- **Current enforcement:** `doc_only` (OEF charter) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_projection_not_evidence.py::test_observability_not_policy` (xfail).
- **Related docs / contracts / ADRs:** [OEF charter](../boundaries/OEF.md); ADR-0022, ADR-0035.
- **Related issues:** #2543, #2550, #2552.

## Schema-batch deferred invariants

The [schemas/contracts batch](../../schemas/README.md) explicitly deferred a set of cross-field and
runtime invariants to this registry because declarative JSON Schema cannot fully express them. They are
captured here with the structurally-enforced part marked `schema_enforced` and the residual part marked
`xfail_runtime_skeleton` or `future_runtime`.

### context_envelope_has_no_raw_vault_or_index_access

- **Purpose:** A `ContextEnvelope` grants bounded context only — there is no field that grants raw vault
  or raw index access; agents reason/propose within the envelope.
- **Protected principle:** matrix #17; doctrine §agents receive bounded context; [CAO charter](../boundaries/CAO.md).
- **Affected boundaries:** CAO, RCA, WSP, GOV.
- **Required fixture / data:** [`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json).
- **Expected failure mode:** an envelope carries a `vault_root`/raw-index handle, or `access_mode` is not
  pinned to `bounded_context_only`.
- **Current enforcement:** `schema_enforced` (`access_mode` const; no raw-access property) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_context_envelope.py::test_context_envelope_has_no_raw_vault_or_index_access`.
- **Related docs / contracts / ADRs:** [context-envelope](../architecture/context-envelope.md) §3; ADR-0037.
- **Related issues:** #2545, #2550, #2552.

### denied_scope_does_not_leak_identity

- **Purpose:** Denied/escalated cross-scope material is recorded content-free — no denied `scope_id`,
  `object_id`, or provenance — because revealing that a specific scope exists is itself cross-boundary
  disclosure. Identifiers for accountability live only behind an `audit_ref`.
- **Protected principle:** matrix #1, #2; doctrine §denied is not hidden context.
- **Affected boundaries:** RCA, GOV, WSP.
- **Required fixture / data:** [`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json) (`denied_scopes`), [`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) (`denied_or_escalated_candidates`).
- **Expected failure mode:** a denied entry carries the denied scope's id/content, so the existence of a
  hidden scope leaks to the agent.
- **Current enforcement:** `schema_enforced` (denied entries are closed objects without id/content) + `static_test` (passes today); full runtime non-leak: `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_context_envelope.py::test_denied_scope_does_not_leak_identity`.
- **Related docs / contracts / ADRs:** [context-envelope](../architecture/context-envelope.md) §3, [retrieval-contract](../architecture/retrieval-contract.md) §3; ADR-0037, ADR-0039.
- **Related issues:** #2545, #2548, #2550, #2552.

### retrieval_candidate_identity_single_source

- **Purpose:** A retrieval candidate's identity/metadata has a single source of truth — its embedded
  metadata bundle (`object_id` from the bundle) — with no parallel top-level identity field to drift.
- **Protected principle:** matrix #3, #7; doctrine §identity/provenance must not drift.
- **Affected boundaries:** RCA, SIP.
- **Required fixture / data:** [`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json).
- **Expected failure mode:** a candidate carries both a bundle and a separate `object_id`, letting the
  two disagree.
- **Current enforcement:** `schema_enforced` (single bundle, no sibling id) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_retrieval_result.py::test_retrieval_candidate_identity_single_source`.
- **Related docs / contracts / ADRs:** [retrieval-contract](../architecture/retrieval-contract.md) §1; ADR-0039.
- **Related issues:** #2548, #2550, #2552.

### retrieval_cannot_upgrade_intrinsic_non_evidence

- **Purpose:** `evidence_role_in_context` may be **downgraded** from the candidate's intrinsic
  `evidence_role` but never **upgraded**. A memory item / un-promoted projection / background/analogy
  candidate can never be admitted as real-world `evidence`.
- **Protected principle:** matrix #1, #5, #8; doctrine §retrieval cannot launder standing.
- **Affected boundaries:** RCA, GOV, SIP.
- **Required fixture / data:** [`schemas/retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json); a future retrieval runtime (for full ordinal "in-context ≤ intrinsic").
- **Expected failure mode:** a candidate whose bundle says `analogy`/`background` is surfaced with
  `evidence_role_in_context: evidence`.
- **Current enforcement:** `schema_enforced` (the dangerous non-evidence→`evidence` upgrade is blocked
  structurally) + `future_runtime`/`xfail_runtime_skeleton` (the general ordinal ≤ comparison is a
  cross-field rule).
- **Eventual test path:** `tests/invariants/test_retrieval_result.py::test_retrieval_cannot_upgrade_intrinsic_non_evidence` (schema part passes); full monotonicity: `tests/invariants/test_retrieval_result.py::test_retrieval_full_evidence_monotonicity_runtime` (xfail).
- **Related docs / contracts / ADRs:** [retrieval-contract](../architecture/retrieval-contract.md) §1, [schemas/README §Known JSON Schema limits](../../schemas/README.md); ADR-0039.
- **Related issues:** #2548, #2550, #2552.

### memory_item_authority_is_noncanonical

- **Purpose:** A memory item's `authority_state` is fixed to `noncanonical` and its `source_role` to
  `agent_memory`; a memory can never validate as draft/proposed/accepted/canonical or as human/shared
  source material.
- **Protected principle:** matrix #4, #5; doctrine §agent memory is noncanonical by default.
- **Affected boundaries:** MEM, GOV, HKA.
- **Required fixture / data:** [`schemas/memory-item.schema.json`](../../schemas/memory-item.schema.json).
- **Expected failure mode:** a memory item validates with `authority_state: accepted`, or with a
  human `source_role`, so it can pass an authority/source filter as if canonical or human-authored.
- **Current enforcement:** `schema_enforced` (`const`) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_agent_memory.py::test_memory_item_authority_is_noncanonical`.
- **Related docs / contracts / ADRs:** [memory-model](../architecture/memory-model.md) §3; ADR-0025, ADR-0026, ADR-0030.
- **Related issues:** #2546, #2550, #2552.

### memory_item_cannot_be_real_world_evidence

- **Purpose:** A memory item's `evidence_role` is restricted to the non-authoritative roles
  (`background`/`reference`/`analogy`/`inspiration`/`non_evidence`); it can never hold real-world
  `evidence`. To become evidence it must be promoted into an HKA artifact (after which it is no longer a
  memory).
- **Protected principle:** matrix #4; doctrine §memory is not factual evidence.
- **Affected boundaries:** MEM, GOV, HKA.
- **Required fixture / data:** [`schemas/memory-item.schema.json`](../../schemas/memory-item.schema.json).
- **Expected failure mode:** a memory item validates with `evidence_role: evidence`, so a recalled note
  is cited as fact.
- **Current enforcement:** `schema_enforced` (evidence excluded) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_agent_memory.py::test_memory_item_cannot_be_real_world_evidence`.
- **Related docs / contracts / ADRs:** [memory-model](../architecture/memory-model.md) §3–4; ADR-0030.
- **Related issues:** #2546, #2550, #2552.

### authority_transition_requires_decision_token_and_receipt

- **Purpose:** Any transition that grants accepted/canonical authority (or changes authority out of
  canonical) must carry both the pre-mutation `decision_token_ref` and the post-mutation
  `authority_receipt_id` — including the approval-exempt path — mirroring the GovernedWriteProtocol.
- **Protected principle:** matrix #9; doctrine §governed write is tokened and receipted.
- **Affected boundaries:** GOV, HKA.
- **Required fixture / data:** [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json).
- **Expected failure mode:** an approved/canonical transition is recorded with no decision token or
  receipt, bypassing governed-write enforcement.
- **Current enforcement:** `schema_enforced` (conditional `allOf`/`if`–`then`) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_authority_transition.py::test_authority_transition_requires_decision_token_and_receipt`.
- **Related docs / contracts / ADRs:** [authority-transition-flow](../architecture/authority-transition-flow.md) §5, [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md); ADR-0019, ADR-0031.
- **Related issues:** #2547, #2550, #2552.

### authority_transition_state_is_consistent

- **Purpose:** A transition's state cannot self-contradict: `approval_required` and `approval_state` stay
  consistent, and a non-grant state (`pending`/`rejected`/`withdrawn`) carries no grant artifacts
  (`approved_authority_state`, `approved_by`, `decision_token_ref`, `authority_receipt_id`).
- **Protected principle:** matrix #9; doctrine §authority state is coherent.
- **Affected boundaries:** GOV.
- **Required fixture / data:** [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json).
- **Expected failure mode:** a transition is simultaneously `rejected` and granting authority, or claims
  approval is both required and not required.
- **Current enforcement:** `schema_enforced` (consistency constraints) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_authority_transition.py::test_authority_transition_state_is_consistent`.
- **Related docs / contracts / ADRs:** [authority-transition-flow](../architecture/authority-transition-flow.md) §5; ADR-0031.
- **Related issues:** #2547, #2550, #2552.

### context_bundle_is_not_context_envelope

- **Purpose:** The RCA `ContextBundle` (candidate-evidence package) and the `ContextEnvelope` (bounded
  agent operating context) are distinct contracts; the envelope composes bundles by id and marks them
  `non_authority`, and never replaces or erases the bundle concept.
- **Protected principle:** matrix #7, #8; doctrine §do not collapse evidence packaging into operating context.
- **Affected boundaries:** RCA, CAO, GOV.
- **Required fixture / data:** [`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json), [`docs/contracts/CONTEXT_BUNDLE.md`](../contracts/CONTEXT_BUNDLE.md).
- **Expected failure mode:** a composed bundle is treated as authority, or the two concepts are merged
  into one shape.
- **Current enforcement:** `schema_enforced` (`context_bundles[].non_authority: true`, distinct contracts) + `static_test` (passes today).
- **Eventual test path:** `tests/invariants/test_context_envelope.py::test_context_bundle_is_not_context_envelope`.
- **Related docs / contracts / ADRs:** [context-envelope](../architecture/context-envelope.md) §1, [CONTEXT_BUNDLE](../contracts/CONTEXT_BUNDLE.md); ADR-0037.
- **Related issues:** #2545, #2550, #2552.

### storage_write_is_not_authority_transition

- **Purpose:** Persisting bytes (PDM) is not changing standing. A storage write must never be mistaken
  for, or substitute for, an `AuthorityTransition`.
- **Protected principle:** matrix #9, #12; doctrine §persistence ≠ authority.
- **Affected boundaries:** PDM, GOV, HKA.
- **Required fixture / data:** [authority-transition-flow](../architecture/authority-transition-flow.md) (rule §4.2); a future PDM/GOV runtime.
- **Expected failure mode:** writing a row flips an object's `authority_state` with no transition,
  decision token, or receipt.
- **Current enforcement:** `doc_only` + `xfail_runtime_skeleton` (storage vs authority runtime).
- **Eventual test path:** `tests/invariants/test_authority_transition.py::test_storage_write_is_not_authority_transition` (xfail).
- **Related docs / contracts / ADRs:** [authority-transition-flow](../architecture/authority-transition-flow.md) §4, [PDM charter](../boundaries/PDM.md); ADR-0016, ADR-0032.
- **Related issues:** #2547, #2550, #2552.

## Coverage map (invariant → principle → test)

| Invariant | Matrix principle(s) | Primary boundary | Enforcement | Test path |
| --- | --- | --- | --- | --- |
| capture_stamps_scope | #2 | WSP/SIP | schema + future runtime | `tests/invariants/test_metadata_bundle.py` (xfail) |
| metadata_bundle_required | #2,#3,#12 | SIP | schema + static | `tests/invariants/test_metadata_bundle.py` |
| store_no_naked_vectors | #12,#16 | PDM/DRI | schema + static | `tests/invariants/test_metadata_bundle.py` |
| provenance_survives_derivation | #3,#16 | DRI/SIP | schema + xfail | `tests/invariants/test_metadata_bundle.py` (xfail) |
| retrieve_scope_prefilter | #1,#7 | RCA | schema + xfail | `tests/invariants/test_cross_scope_flow.py` (xfail) |
| similarity_not_permission | #1 | RCA/GOV | doc + xfail | `tests/invariants/test_cross_scope_flow.py` (xfail) |
| cross_scope_only_via_flow | #1,#6 | GOV/RCA | schema + xfail | `tests/invariants/test_cross_scope_flow.py`, `tests/evals/test_general_knowledge_crosses_clean.py` (xfail) |
| rpg_not_confused_with_software | #1,#5 | RCA/SIP | static + xfail | `tests/evals/test_rpg_not_confused_with_software.py` (xfail) |
| private_not_in_work_results | #1,#2 | WSP/GOV | static + xfail | `tests/evals/test_private_not_in_work_results.py` (xfail) |
| remember_not_canonical | #4 | MEM/GOV | schema + static | `tests/invariants/test_agent_memory.py` |
| promote_requires_governance | #4,#9,#15 | MEM/GOV/HKA | schema + xfail | `tests/invariants/test_authority_transition.py` (xfail) |
| projection_not_evidence | #8 | DRI/OEF/GOV | schema + xfail | `tests/invariants/test_projection_not_evidence.py` (xfail) |
| authority_transition_required_for_durable_mutation | #9,#15 | GOV/HKA | schema + xfail | `tests/invariants/test_authority_transition.py` (xfail) |
| execution_cannot_authorize_itself | #10 | CAO/GOV/EXE | schema + xfail | `tests/invariants/test_authority_transition.py` (xfail) |
| parent_aggregation_not_sibling_sharing | #11 | SFC/WSP | doc + static + xfail | `tests/invariants/test_cross_scope_flow.py` (xfail) |
| sync_preserves_boundaries | #14 | SFC/WSP/GOV | schema + xfail | `tests/invariants/test_cross_scope_flow.py` (xfail) |
| observability_not_policy | #13 | OEF/GOV | doc + xfail | `tests/invariants/test_projection_not_evidence.py` (xfail) |
| context_envelope_has_no_raw_vault_or_index_access | #17 | CAO/RCA | schema + static | `tests/invariants/test_context_envelope.py` |
| denied_scope_does_not_leak_identity | #1,#2 | RCA/GOV | schema + static | `tests/invariants/test_context_envelope.py` |
| retrieval_candidate_identity_single_source | #3,#7 | RCA/SIP | schema + static | `tests/invariants/test_retrieval_result.py` |
| retrieval_cannot_upgrade_intrinsic_non_evidence | #1,#5,#8 | RCA/GOV | schema + future runtime | `tests/invariants/test_retrieval_result.py` (+ xfail) |
| memory_item_authority_is_noncanonical | #4,#5 | MEM/GOV | schema + static | `tests/invariants/test_agent_memory.py` |
| memory_item_cannot_be_real_world_evidence | #4 | MEM/GOV | schema + static | `tests/invariants/test_agent_memory.py` |
| authority_transition_requires_decision_token_and_receipt | #9 | GOV/HKA | schema + static | `tests/invariants/test_authority_transition.py` |
| authority_transition_state_is_consistent | #9 | GOV | schema + static | `tests/invariants/test_authority_transition.py` |
| context_bundle_is_not_context_envelope | #7,#8 | RCA/CAO | schema + static | `tests/invariants/test_context_envelope.py` |
| storage_write_is_not_authority_transition | #9,#12 | PDM/GOV | doc + xfail | `tests/invariants/test_authority_transition.py` (xfail) |

## Related documents

- [Traceability matrix](../architecture/traceability-matrix.md) — principle → contract → **this registry** → test → issue
- [Anti-contamination eval fixtures](../../tests/evals/fixtures/README.md) — the corpus several invariants require (#2551)
- [Schemas README](../../schemas/README.md) — which checks are declarative-schema-impossible and deferred here
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) · [Boundary charters](../boundaries/README.md) · [ADR index](../adr/INDEX.md)
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) · [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md)
