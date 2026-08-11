State: Canonical Mimer invariant test registry. Docs-only control document for the architecture-foundation backlog (#2533–#2552); names the architecture fitness rules (invariants) that future runtime implementation must satisfy, and maps each to its principle, boundaries, contract/schema, ADR, fixture, enforcement posture, and eventual test path. Does not claim shipped runtime behavior.
Doc role: Testing / fitness registry (architecture fitness rules)
Authority: Owns the canonical list of named architecture invariants (fitness probes) for the Mimer foundation. For each invariant it answers: which doctrine principle it protects, which control boundaries own it, which contract/schema (if any) already expresses it, how it fails when violated, how it is currently enforced, and which test will eventually pin it. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/functional-ontology.md`, `docs/architecture/semantic-dimensions.md`, `docs/architecture/cross-scope-flow.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, and the per-invariant contracts under `docs/architecture/`. It does not set policy: OEF observes and evaluates; GOV owns normative policy and authority decisions.
Owner: OEF — Observability, Evaluation & Fitness (registry); CES practice (rule lifecycle)
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (invariant → probe mapping); subordinate to the doctrine, ontology, semantic dimensions, contracts, and boundary charters it maps
Last reviewed: 2026-07-11
Last verified against: docs/architecture/traceability-matrix.md, docs/foundation/00-yggdrasil-doctrine.md, docs/architecture/semantic-dimensions.md, docs/architecture/cross-scope-flow.md, docs/architecture/metadata-bundle.md, docs/architecture/context-envelope.md, docs/architecture/memory-model.md, docs/architecture/authority-transition-flow.md, docs/architecture/retrieval-contract.md, docs/boundaries/README.md, schemas/README.md

# Mimer Invariant Test Registry

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
| `runtime_test` | A test exercises the runtime path (the `mimer_runtime` slice) and **passes today** — the former `xfail_runtime_skeleton` now runs its real assertions. |

An invariant may be partly `schema_enforced` *and* carry an `xfail_runtime_skeleton` — the schema
blocks the structurally-expressible part, the skeleton holds the cross-field or runtime part. The
[schemas/README §Known JSON Schema limits](../../schemas/README.md) lists exactly which checks are
declarative-schema-impossible and therefore live here as the source of truth.

## Registry

### one_vault_settings_location

- **Purpose:** Every vault-backed settings producer and consumer uses `<vault>/settings/` as the
  single canonical root; retired locations remain bounded compatibility inputs and can never become
  a second source of truth.
- **Protected principle:** SET-2 canonical settings location; canonical settings shadow matching
  legacy files, values are never merged, and fresh initialization creates no retired settings root.
- **Affected boundaries:** WSP, HKA vault layout, GOV migration/write safety, Builder System CI.
- **Required fixture / data:** canonical and legacy settings trees plus the production-path census in
  `tests/architecture/test_settings_single_location.py`.
- **Expected failure mode:** a producer creates or a consumer reads a new settings location outside
  `<vault>/settings/`, or canonical and legacy values are merged into dual truth.
- **Current enforcement:** `static_test` plus runtime migration/resolution tests — the architecture
  census blocks new locations, and canonical/compatibility behavior is exercised by the settings
  canonical-location suite.
- **Runtime test path:** `tests/architecture/test_settings_single_location.py::test_no_new_settings_paths`;
  `tests/settings/test_canonical_location.py`.
- **Related docs / contracts / ADRs:** `docs/SETTINGS.md`;
  `docs/SETTINGS_SPINE/CANONICALIZE_SETTINGS_LOCATION.md`.
- **Related issues:** #3156, #3161.

### inv_ef1_public_private_seam

- **Purpose:** The public repository carries no secret-shaped values, and every retained personal binding has an owned, per-artifact INV-EF1 register row rather than an unreviewed baseline exception.
- **Protected principle:** INV-EF1 public/private operator-invariance (`docs/architecture/ecosystem-federation.md` § Public/private invariant).
- **Affected boundaries:** CES / Builder System public seam; GitHub Actions CI.
- **Required fixture / data:** `scripts/public_seam_patterns.json` and `docs/architecture/inv-ef1-register.json`.
- **Expected failure mode:** A PR adds a secret-shaped value, or adds an operator-bound identifier without an owned register row.
- **Current enforcement:** `static_test` — GATE scans changed content in PR CI; DOCTOR reconciles stale register rows, uncovered drift, and pending migrations across the tracked tree.
- **Eventual test path:** `tests/scripts/test_public_seam_lint.py`.
- **Related docs / contracts / ADRs:** `docs/adr/ADR-0046-inv-ef1-public-private-seam.md`; `docs/architecture/SBS_TRANSITION_DEBT.md`.
- **Related issues:** #2892.

### capture_stamps_scope

- **Purpose:** Every captured object is stamped with a scope (and the rest of its metadata bundle) at
  capture time — nothing enters the system scope-less.
- **Protected principle:** matrix #2 (scope is frame/audience/policy/provenance); doctrine — capture is
  the first point at which meaning is fixed.
- **Affected boundaries:** HIX, WSP, SIP, HKA.
- **Required fixture / data:** a future capture runtime; the [metadata-bundle schema](../architecture/metadata-bundle.md).
- **Expected failure mode:** a captured artifact without `scope_id`/`source_role` reaches storage, so
  later scope/policy decisions have nothing to act on.
- **Current enforcement:** `schema_enforced` (a bundle without `scope_id` fails validation) + `runtime_test` (capture path, `mimer_runtime.capture`).
- **Runtime test path:** `tests/invariants/test_metadata_bundle.py::test_capture_stamps_scope` (runtime — passes).
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
- **Current enforcement:** `schema_enforced` (derived types require `derived_from`) + `runtime_test` (derivation runtime, `mimer_runtime.dri`).
- **Runtime test path:** `tests/invariants/test_metadata_bundle.py::test_provenance_survives_derivation` (runtime — passes).
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
- **Current enforcement:** `schema_enforced` (the flag is pinned `true` in data) + `runtime_test` (prefilter behaviour, `mimer_runtime.retrieval`).
- **Runtime test path:** `tests/invariants/test_cross_scope_flow.py::test_retrieve_scope_prefilter` (runtime — passes).
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
- **Current enforcement:** `doc_only`/`schema_enforced` in part (ranking signals inform order only) + `runtime_test` (admission behaviour, `mimer_runtime.retrieval`).
- **Runtime test path:** `tests/invariants/test_cross_scope_flow.py::test_similarity_is_not_permission` (runtime — passes).
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
- **Current enforcement:** `schema_enforced` in part (flow guardrails carried on results/envelopes) + `runtime_test` (`mimer_runtime.retrieval`/`cross_scope`).
- **Runtime test path:** `tests/invariants/test_cross_scope_flow.py::test_cross_scope_only_via_flow` (runtime — passes); `tests/evals/test_general_knowledge_crosses_clean.py::test_general_knowledge_crosses_clean` (runtime — passes).
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
- **Current enforcement:** `static_test` (fixtures are distinctly scoped/roled — passes today) + `runtime_test` (retrieval discrimination, `mimer_runtime.retrieval`).
- **Runtime test path:** `tests/evals/test_rpg_not_confused_with_software.py::test_rpg_not_confused_with_software` (runtime — passes).
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
- **Current enforcement:** `static_test` (fixtures denied-by-default scoped — passes today) + `runtime_test` (`mimer_runtime.retrieval`).
- **Runtime test path:** `tests/evals/test_private_not_in_work_results.py::test_private_not_in_work_results` (runtime — passes).
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
- **Expected failure mode:** an `ExecutionEffect` proceeds (or grants authority) without a prior bound
  GOV grant (`DecisionToken`); the post-effect `AuthorityReceipt` is accountability only and never an
  acceptable authorization artifact. See `orchestrator_effect_requires_prevalidated_decision_token`.
- **Current enforcement:** `schema_enforced` in part (`requires_authorization` pinned `true`) + `xfail_runtime_skeleton`.
- **Eventual test path:** `tests/invariants/test_authority_transition.py::test_execution_cannot_authorize_itself` (xfail).
- **Related docs / contracts / ADRs:** [authority-transition-flow](../architecture/authority-transition-flow.md) §4, [EXE charter](../boundaries/EXE.md), [EXECUTION_REQUEST](../contracts/EXECUTION_REQUEST.md); ADR-0019, ADR-0031.
- **Related issues:** #2547, #2550, #2552.

## Governed knowledge effect spine invariants

These target-state probes define the production-call-site commitments for the logical effect chain.
They do not claim that the transitional runtime paths already enforce the whole contract. Runtime
slices promote a row from `future_runtime` only when the named production seam is exercised without
mocking away GOV, the state owner/EXE effect, receipt persistence, or recovery state.

### authority_bearing_producers_use_one_governed_effect_chain

- **Purpose:** Every authority-bearing producer family enters the same ordered GOV → state owner/EXE
  → receipt chain; no producer-specific side door authorizes or acknowledges a durable effect.
- **Protected principle:** matrix #9, #10, #13, #15; GovernedWriteProtocol invariants.
- **Affected boundaries:** HIX, CAO, GOV, HKA, MEM, EXE, SIP, DRI, OEF; Heimdal/external intake at the candidate seam.
- **Required fixture / data:** the producer inventory in
  `docs/GOVERNED_KNOWLEDGE_EFFECT_SPINE/DEFINE_EFFECT_SPINE_CONTRACTS.md`; production API,
  orchestrator, eval-capture, state-owner, and EXE call sites with a real receipt sink.
- **Expected failure mode:** a producer treats WriteGuard, persistence, an HTTP response, outbox event,
  execution result, cursor, or OEF trace as authorization/accountability and bypasses a stage.
- **Current enforcement:** `doc_only` / `future_runtime`.
- **Eventual test path:**
  `tests/invariants/test_governed_effect_spine.py::test_authority_bearing_producers_use_production_governed_chain`.
- **Related docs / contracts / ADRs:** [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md),
  [effect-spine inventory](../GOVERNED_KNOWLEDGE_EFFECT_SPINE/DEFINE_EFFECT_SPINE_CONTRACTS.md),
  [functional ontology](../architecture/functional-ontology.md); ADR-0019.
- **Related issues:** #3554; parent #3553.

### orchestrator_effect_requires_prevalidated_decision_token

- **Purpose:** A CAO/orchestrator real-tool effect reaches EXE only with a valid, bound DecisionToken;
  execution never self-authorizes.
- **Protected principle:** matrix #10; `execution_cannot_authorize_itself`.
- **Affected boundaries:** CAO, GOV, EXE.
- **Required fixture / data:** the production real-tool gate and vault-append execution seam
  (`app/orchestrator/executor.py::_run_vault_append` or its governed successor), a real EXE request,
  and a denying/mismatched-token case.
- **Expected failure mode:** the real tool runs with `decision_token=None`, a mismatched token, or a
  token invented by the orchestrator/EXE path.
- **Current enforcement:** `future_runtime`; the current transitional ExecutionRequest permits a
  missing token and therefore is not proof.
- **Eventual test path:**
  `tests/invariants/test_governed_effect_spine.py::test_orchestrator_real_tool_requires_prevalidated_decision_token`.
- **Related docs / contracts / ADRs:** [EXECUTION_REQUEST](../contracts/EXECUTION_REQUEST.md),
  [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md); ADR-0019.
- **Related issues:** #3554; parent #3553.

### eval_capture_cannot_self_promote_or_bypass_receipt

- **Purpose:** Eval-capture may create a candidate, but only an explicit human disposition through
  the governed production write seam changes its authority-bearing review state, with a durable
  AuthorityReceipt after mutation.
- **Protected principle:** matrix #9, #13; `observability_not_policy`.
- **Affected boundaries:** OEF, GOV, HKA.
- **Required fixture / data:** production dead-letter/UNKNOWN candidate call sites plus
  `app/eval/failure_capture.py::promote_draft` / `reject_draft`, a human actor, real write seam, and
  durable receipt sink.
- **Expected failure mode:** an OEF finding makes itself golden/promoted, WriteGuard alone stands in
  for authorization, or disposition succeeds without an AuthorityReceipt.
- **Current enforcement:** `future_runtime`; current drafting/disposition is WriteGuard-gated but does
  not implement the complete DecisionToken/AuthorityReceipt chain.
- **Eventual test path:**
  `tests/invariants/test_governed_effect_spine.py::test_eval_capture_disposition_uses_production_governed_chain`.
- **Related docs / contracts / ADRs:** [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md),
  [effect-spine inventory](../GOVERNED_KNOWLEDGE_EFFECT_SPINE/DEFINE_EFFECT_SPINE_CONTRACTS.md); ADR-0019.
- **Related issues:** #3554; parent #3553.

### governed_effect_partial_failure_reconciles_without_duplicate_mutation

- **Purpose:** Mutation-success/receipt-failure and receipt-success/notification-failure remain
  distinguishable and recover idempotently without replaying a completed mutation.
- **Protected principle:** matrix #9, #13, #15; GovernedWriteProtocol partial-failure states.
- **Affected boundaries:** GOV, state-owning subsystem or EXE, OEF.
- **Required fixture / data:** production governed write/effect path, stable operation/effect id,
  durable receipt sink and outbox, with fault injection at both stage boundaries.
- **Expected failure mode:** an uncertain applied mutation is blind-retried, a duplicate effect is
  produced, notification is mistaken for accountability, or success is acknowledged without a
  durable AuthorityReceipt.
- **Current enforcement:** `future_runtime`.
- **Eventual test path:**
  `tests/invariants/test_governed_effect_spine.py::test_partial_failure_reconciles_without_duplicate_mutation`.
- **Related docs / contracts / ADRs:** [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md),
  [effect-spine inventory](../GOVERNED_KNOWLEDGE_EFFECT_SPINE/DEFINE_EFFECT_SPINE_CONTRACTS.md); ADR-0019.
- **Related issues:** #3554; parent #3553.

### source_correction_repairs_derived_effects_idempotently

- **Purpose:** A source/provenance correction preserves historical receipts while suppressing or
  rebuilding every affected derived representation before it is served as current.
- **Protected principle:** matrix #3, #13, #16; doctrine — provenance survives derivation.
- **Affected boundaries:** SIP, DRI, RCA, GOV, OEF.
- **Required fixture / data:** a receipted durable source, multiple derived rows, the production
  correction-to-index/retrieval path, and repeated repair delivery.
- **Expected failure mode:** corrected source leaves stale derived state live, repair changes or
  deletes the original AuthorityReceipt, or replay produces divergent projection state.
- **Current enforcement:** `future_runtime`.
- **Eventual test path:**
  `tests/invariants/test_governed_effect_spine.py::test_source_correction_repairs_derived_effects_idempotently`.
- **Related docs / contracts / ADRs:** [metadata-bundle](../architecture/metadata-bundle.md),
  [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md),
  [effect-spine inventory](../GOVERNED_KNOWLEDGE_EFFECT_SPINE/DEFINE_EFFECT_SPINE_CONTRACTS.md); ADR-0018, ADR-0019.
- **Related issues:** #3554; parent #3553.

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

### propose_when_uncertain

- **Purpose:** When the agent is uncertain it proposes/confirms/escalates rather than silently acting.
  Uncertainty surfaces as a proposal or an escalation condition, never a silent durable effect.
- **Protected principle:** matrix #17; doctrine §propose/confirm/escalate.
- **Affected boundaries:** CAO, GOV, HIX.
- **Required fixture / data:** [`schemas/context-envelope.schema.json`](../../schemas/context-envelope.schema.json) (`escalation_conditions`); a future CAO/agent runtime.
- **Expected failure mode:** an agent takes a silent durable action on an ambiguous request instead of
  proposing or escalating.
- **Current enforcement:** `doc_only` (envelope carries escalation conditions; proposals are noncanonical) + `xfail_runtime_skeleton` (agent behaviour).
- **Eventual test path:** `tests/invariants/test_context_envelope.py::test_propose_when_uncertain` (xfail).
- **Related docs / contracts / ADRs:** [context-envelope](../architecture/context-envelope.md), [doctrine](../foundation/00-yggdrasil-doctrine.md); ADR-0026.
- **Related issues:** #2545, #2550, #2552.

### standards_are_adapters

- **Purpose:** External standards are adapters at the boundary; they do not redefine the ontology or
  the `source_role`/`authority_state`/`evidence_role` value families.
- **Protected principle:** matrix #18; doctrine §2.7 (standards are adapters).
- **Affected boundaries:** EBF, SIP, GOV, CES.
- **Required fixture / data:** [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json) (the value families standards must not redefine).
- **Expected failure mode:** an imported external standard silently redefines or collapses a role value
  family, so the ontology is bent to the standard instead of the standard adapting to the ontology.
- **Current enforcement:** `doc_only` (CES stewardship review; no runtime to test). No skeleton — this
  is a review-time invariant, not an executable probe yet.
- **Eventual test path:** `TBD` — CES stewardship review; promote to a static/CI check only if a
  mechanical shape emerges.
- **Related docs / contracts / ADRs:** [doctrine](../foundation/00-yggdrasil-doctrine.md) §2.7, [functional-ontology](../architecture/functional-ontology.md); ADR-0036.
- **Related issues:** #2549, #2550.

## Integration seam invariants (2026-07-05 whole-system pass)

Extracted by the live integration audit
[`docs/audits/MIMER_WHOLE_SYSTEM_INTEGRATION_2026-07-05.md`](../audits/MIMER_WHOLE_SYSTEM_INTEGRATION_2026-07-05.md)
from observed seam failures on the running dev channel. These pin the *composition* of the chain
`note → watcher → ingest → embed → index → retrieval → synthesis → surface → receipt`, not any single
component. Minimal kernel: `retrieval_serves_durable_truth_fresh` + `watcher_deletions_reconcile` +
`watcher_blindness_is_visible` (what enters the vault becomes retrievable; what leaves stops being
retrievable; a blind ingester says so).

### watcher_blindness_is_visible

- **Purpose:** A running watcher whose scope matched zero files, or whose scope's static prefix
  directory is missing under the bound vault, surfaces that in its heartbeat (`scope_status`) instead
  of reporting healthy while ingesting nothing.
- **Protected principle:** fail loud, never paper over; a component that observes nothing must say so.
- **Affected boundaries:** watcher/ingest pipeline, OEF health surfaces.
- **Expected failure mode:** vault layout drifts from configured scope; watcher ticks "healthy"
  forever; no note ever reaches ingest; nothing signals it (observed live 2026-07-05, gap G1).
- **Current enforcement:** `runtime_test` — delivered by #2988 / PR #3007.
- **Runtime test path:** `tests/watcher/test_scope_zero_match_signal.py` (passes).
- **Related docs / contracts / ADRs:** [OBSERVABILITY](../OBSERVABILITY.md) (heartbeat `scope_status`); audit G1.
- **Related issues:** #2988.

### watcher_idles_not_crashes_on_unusable_vault

- **Purpose:** Enable-off due to vault status (idle/uninitialized, #2005 contract) idles the watcher
  process; only an explicit `WATCHER_ENABLE≠1` may exit, and error text names the actual cause.
- **Protected principle:** truthful failure attribution; idle contract (#2005).
- **Affected boundaries:** watcher CLI, channel operability.
- **Expected failure mode:** container crash-loop with a misleading env-var error on an uninitialized
  vault (observed live on `pkm-test-watcher-1`, gap G6).
- **Current enforcement:** `runtime_test` — delivered by #2992 / PR #3001.
- **Runtime test path:** `tests/watcher/test_cli_idle_vs_disabled.py` (passes).
- **Related issues:** #2992.

### watcher_deletions_reconcile

- **Purpose:** A filesystem deletion observed by the watcher eventually purges the object's derived
  rows (tombstone path); vault reality and the durable index converge.
- **Protected principle:** the vault filesystem is the source of truth; derived stores follow it in
  both directions.
- **Affected boundaries:** watcher/ingest, durable index, retrieval spine.
- **Expected failure mode:** deleted/renamed notes persist as retrieval candidates indefinitely
  (observed live: ask sources dominated by ghosts of deleted files, gap G4).
- **Current enforcement:** in delivery — #2990 / PR #3008.
- **Eventual test path:** `tests/watcher/test_watcher_deletion_reconciliation.py`.
- **Related issues:** #2990.

### retrieval_serves_durable_truth_fresh

- **Purpose:** Every retrieval-serving substrate is a cache of the durable index with an explicit
  generation/freshness contract; a row upserted to `store_vector_index` becomes retrievable without a
  process restart (bounded staleness).
- **Protected principle:** KERNEL-05 (serving substrates hold no independent truth), extended with
  freshness.
- **Affected boundaries:** retrieval spine (DRI/RCA).
- **Expected failure mode:** fresh notes invisible to ask until API restart (observed live, gap G2).
- **Current enforcement:** `runtime_test` — delivered by #2981 / PR #3003.
- **Runtime test path:** `tests/invariants/test_retrieval_spine_invariants.py::test_retrieval_serves_durable_truth_fresh` (passes).
- **Related issues:** #2981, #2980.

### no_legacy_read_surfaces

- **Purpose:** No API read surface consumes the legacy `objects`/`objects_embeddings` tables, and no
  retrieval endpoint silently falls back to query-independent results on failure.
- **Protected principle:** single canonical store generation (KERNEL-03/04 read-side); fail loud.
- **Affected boundaries:** API surface, retrieval spine.
- **Expected failure mode:** an endpoint returns identical plausible-looking results for any query
  while its real substrate is empty (observed live on `/search`, gap G3).
- **Current enforcement:** `runtime_test` — delivered by #2989 / PR #3009.
- **Runtime test path:** `tests/api/test_search_canonical_substrate.py` (passes).
- **Related issues:** #2989; dual-writer remainder #2901.

### health_liveness_is_truthful

- **Purpose:** `/api/health` watcher/worker liveness verdicts reflect actual cross-container process
  state — heartbeat paths are structurally reachable by the reader, and stale files never report ok.
- **Protected principle:** honest health signals (#2597); a health surface that cannot see its
  subjects is worse than none.
- **Affected boundaries:** OEF health, deployment topology.
- **Expected failure mode:** permanent "not running (no heartbeat)" false negatives training operators
  to ignore health (observed live, gap G5).
- **Current enforcement:** `runtime_test` (integrated-runtime UAT, `RUN_INTEGRATED_RUNTIME_UAT=1`) —
  delivered by #2991 / PR #3004.
- **Runtime test path:** `tests/invariants/test_health_heartbeat_visibility.py` (passes).
- **Related issues:** #2991, #2597.

### embedding_completes_or_fails_loud_per_object

- **Purpose:** An object whose text exceeds the embedding provider's real input tolerance is chunked
  adaptively until it embeds (mean-pooled) or fails loud at a floor size; content-dependent provider
  5xx must not permanently dead-letter a note on a char-budget guess.
- **Protected principle:** every vault note is retrievable; provider limits are the runtime's problem,
  not the note's.
- **Affected boundaries:** embedding/index pipeline (SIP), retrieval spine.
- **Expected failure mode:** token-dense chunks crash the provider inside the char budget; the note
  dead-letters; `embedding_index` pins at `rebuild_required` (observed live, gap G10).
- **Current enforcement:** open — #3045.
- **Eventual test path:** `tests/llm/test_embed_adaptive_chunking.py`.
- **Related issues:** #3045, #2110 (char-budget predecessor).

### receipt_surfaces_writable_on_fresh_runtime

- **Purpose:** Receipt append paths (ask-synthesis and successors) are writable by the runtime user on
  a freshly created container; receipt-before-answer stays fail-loud, but the environment may not make
  failure the default state.
- **Protected principle:** receipts are load-bearing; an undeployable receipt surface takes the chat
  surface down with it.
- **Affected boundaries:** deployment topology, activation receipts.
- **Expected failure mode:** image bakes root-owned `runtime/`; service runs uid 501; every `/api/ask`
  500s after every deploy until a manual chown (observed live, gap G11).
- **Current enforcement:** open — #3047.
- **Eventual test path:** `tests/invariants/test_receipt_surface_writable.py`.
- **Related issues:** #3047, #2968 (fail-loud posture, preserved).

### connect_proposals_candidate_only

- **Purpose:** `connect.*` classes map to propose-track by construction (no configuration can move
  them); connect evidence enters downstream context clamped to `background` at most; no connect
  output applies a link without the governed acceptance path (the checkbox).
- **Protected principle:** agents propose, human disposes — Cognitive Expansion's moat.
- **Affected boundaries:** Curation finding pipeline (G2), retrieval spine (consumer), Panel proposal
  surface.
- **Expected failure mode:** a `connect.*` class is added to `MECHANICAL_ALLOWLIST` (silently moves a
  relationship-surfacing finding onto the auto-fix track), or a connect finding's supporting material
  is cited as `evidence` rather than `background` in a downstream context.
- **Current enforcement:** live — `app/curation/findings.py` (`CONNECT_FINDING_CLASSES` asserted
  disjoint from `MECHANICAL_ALLOWLIST` at import time), `app/expansion/connect.py`.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_connect_candidate_only`,
  `tests/expansion/test_connect_findings.py`.
- **Related issues:** #2994 (EXP-1), #2980 (parent).

### declined_findings_not_reproposed

- **Purpose:** A declined finding/draft id is suppressed on later passes until its content basis
  changes; suppression is visible in pass receipts; the ledger itself is never admitted as context.
- **Protected principle:** agents propose, human disposes; a "no" must be remembered without
  becoming knowledge — Cognitive Expansion's moat (mirrors the doctrine's refusal to let the system
  silently infer "the human dislikes X", `docs/EMERGENT_FEATURES_MODEL.md`'s "agent learns my
  workflow" example).
- **Affected boundaries:** Cognitive Expansion (Connect, later Create/E8), Curation finding pipeline
  (G2, consults the same ledger), retrieval/context-assembly spine (must never reach it).
- **Expected failure mode:** a proposal-emitting pass re-emits a finding the human already declined
  every rerun until accepted (proposal-flood); or the ledger is wired into a retrieval/context path,
  turning suppression state into an input to cognition.
- **Current enforcement:** live — `app/proposals/declined_ledger.py` (`DeclinedLedger`, keyed on the
  content-derived `finding_id`; delete-safe; WriteGuard-gated write path only), wired as
  `app/expansion/connect.py`'s `DeclinedLedgerPort` default (replacing the EXP-1 no-op stub).
- **Test path:** `tests/proposals/test_declined_ledger.py` (declined ⇒ suppressed + receipted;
  content-basis change ⇒ new finding_id, re-proposable; ledger deleted/corrupt ⇒ no error, re-
  proposable; `test_ledger_never_enters_context` — static import-graph + runtime field check),
  `tests/invariants/test_expansion_invariants.py::test_declined_not_reproposed`.
- **Related issues:** #2995 (EXP-2), #2994 (EXP-1, consultation point), #2980 (parent).

### create_never_autowrites_canonical

- **Purpose:** No synthesis output reaches a canonical vault location without a human acceptance
  receipt; the staging area (`_system/drafts/`, owner decision E1's recommended default) is the only
  machine-writable destination for Create output, and staging is not canonical.
- **Protected principle:** agents propose, human disposes — the field-differentiating moat.
- **Affected boundaries:** Cognitive Expansion (Create), Knowledge compilation (draft contract),
  WriteGuard.
- **Expected failure mode:** a "helpful" slice writes the overview directly to the topic folder, or
  acceptance is inferred from anything other than the human's checkbox.
- **Current enforcement:** live, both halves. (create side) `app/expansion/create.py::run_create_pass`
  only ever writes under the resolved system dir's `drafts` subfolder, gated by the named
  `expansion.create.stage_write` WriteGuard action; there is no body-edit or canonical-location write
  path in that module. (acceptance side) `app/expansion/accept.py::accept_draft` is the ONLY path to a
  canonical note and materializes only a draft whose in-draft acceptance checkbox a human has checked
  (`DraftNotAcceptedError` otherwise); the canonical write is gated by the named
  `expansion.create.accept_materialize` WriteGuard action and the decision token is minted from the
  checkbox, never by the executor itself.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_create_never_autowrites_canonical`,
  `tests/expansion/test_accept_promotion.py::test_unchecked_draft_is_never_materialized`.
- **Related issues:** #2996 (EXP-3), #2997 (EXP-4, governed acceptance — the only path to canonical),
  #2980 (parent).

### synthesis_carries_source_provenance

- **Purpose:** Every synthesized draft and every accepted note carries resolvable SourceRefs
  (per-section and note-level); citation-validation failure blocks the proposal loudly; provenance
  survives acceptance permanently.
- **Protected principle:** synthesis without traceable sources is unaccountable machine text — the
  charter's "loss of provenance" failure mode, refused at construction.
- **Affected boundaries:** Cognitive Expansion (Create), Knowledge compilation
  (`proposal_builders`/`CompilationDraft`/`SourceRef`).
- **Expected failure mode:** unsourced narrative ships; or sources are pruned at acceptance and the
  note becomes untraceable machine text.
- **Current enforcement:** live, both halves. (create side) `app/expansion/create.py::_validate_citations`
  blocks a draft (`UnresolvableCitationError`) when a cited source does not resolve or a quoted span
  does not exist verbatim in its source text; validation runs before any draft/context is built, never
  after a silent prune. (acceptance side) `app/expansion/accept.py::accept_draft` preserves `sources`
  and `derived_by: synthesis` verbatim into the canonical note (never pruned, never upgraded to an
  evidence role), and re-validates citations at acceptance time — a cited source that no longer
  resolves blocks materialization loudly (`UnresolvableCitationError`).
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_synthesis_carries_source_provenance`,
  `tests/invariants/test_expansion_invariants.py::test_accepted_note_keeps_provenance`,
  `tests/expansion/test_create_draft_lifecycle.py`, `tests/expansion/test_accept_promotion.py`.
- **Related issues:** #2996 (EXP-3), #2997 (EXP-4), #2980 (parent).

### staged_drafts_invisible_to_retrieval

- **Purpose:** Staging-area content is never indexed as knowledge and never retrievable into any
  context; unaccepted machine text cannot compound into future syntheses.
- **Protected principle:** the anti-laundering keystone — mirrors "panel content is not indexed as
  knowledge" (`docs/PANEL_AGENT.md:175`).
- **Affected boundaries:** Ingest pipeline (`app.ingest.vault_alpha`), watcher, retrieval spine
  (consumer side — never reachable).
- **Expected failure mode:** silent self-amplification — drafts citing drafts.
- **Current enforcement:** live — `app/ingest/vault_alpha.py`'s candidate-selection walk excludes the
  Create staging subfolder (`_UNINDEXED_SYSTEM_SUBFOLDERS`, extending the pre-existing
  `_system/companions` exclusion) at both the initial candidate scan and the resumable ingest loop;
  `app/watcher/vault_watcher.py` already skips the entire `_system` tree unconditionally.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_drafts_invisible_to_retrieval`,
  `tests/expansion/test_create_draft_lifecycle.py::test_staged_draft_not_indexed_by_vault_alpha_ingest`.
- **Related issues:** #2996 (EXP-3), #2980 (parent).

### expansion_requires_activation_record

- **Purpose:** Connect/Create passes run only under a green activation-gate record; a regressed
  precondition yields blocked-with-reason, never a silent run (no third "activate anyway" path).
- **Protected principle:** the Expansion Activation Gate is the dormant→active flip's sole
  deterministic authority; no capability may self-activate.
- **Affected boundaries:** Cognitive Expansion (Connect, Create), `app.activation.gate`,
  `app.activation.expansion_records`.
- **Expected failure mode:** a capability runs its cognition/write path despite a regressed
  admissibility/loop-precondition/observability input, because a call site bypassed the gate.
- **Current enforcement:** live — `app/expansion/create.py::run_create_pass` evaluates
  `evaluate_create_activation` first and returns a non-activatable `CreatePassReport` (never raises,
  never runs cognition or writes) when any gate input is blocked. EXP-6 (#2998) adds one named
  activation-gate record per capability contract (`app/activation/expansion_records.py`:
  `connection_proposal` for Connect, `synthesis_note_proposal` for Create), each with its own
  durable jsonl receipt (`runtime/activation/expansion_gate_receipts.jsonl`) — a regressed precondition
  on either record yields `blocked-with-reason`, never a silent run.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_create_requires_activation_record`,
  `tests/invariants/test_expansion_invariants.py::test_requires_activation_record`,
  `tests/activation/test_expansion_gate_records.py`.
- **Related issues:** #2996 (EXP-3), #2998 (EXP-6, activation records + status ladder), #2980 (parent).
- **Related issues:** #2996 (EXP-3), #2980 (parent).

### curation_citations_resolve

- **Purpose:** Every contradiction finding carries >=2 in-vault source references that resolve at
  materialization time; unresolvable evidence voids the finding (no uncited "trust me" callouts).
- **Protected principle:** a surfaced tension must be traceable to real, resolvable material — never
  adjudicated, never asserted without a citable basis.
- **Affected boundaries:** Curation finding pipeline (G2), Cognitive Expansion (sibling pass, shares
  EXP-1's harness shape and EXP-2's declined-proposal ledger), retrieval spine (consumer only).
- **Expected failure mode:** a contradiction finding materializes with a dangling/nonexistent source
  link, or a candidate whose citation fails to resolve is silently dropped without any trace instead
  of failing loudly.
- **Current enforcement:** live — `app/curation/contradiction.py::run_contradiction_pass` resolves
  both sides' source links against the vault filesystem before a `CurationFinding` is ever
  constructed; an unresolvable citation raises `UnresolvableContradictionCitationError` (blocked
  loudly, never silently emitted, never silently dropped without trace). The class
  (`contradiction.claim_conflict`) was already a member of the closed `FindingClass` enum
  (`app/curation/findings.py`, added by E1 #2986) and resolves to `FindingTrack.PROPOSE`
  unconditionally via `track_for_class` — this slice reuses that class rather than minting a new one.
  Materialization is delegated entirely to the existing propose-only writer
  (`app.curation.proposal_writer.write_curation_proposals`); the pass itself never writes a
  `[!contradiction]` callout — that callout is a body edit that only ever rides the confirmed
  checkbox action (`semantic_curation_never_autowrites`'s sibling guarantee, enforced here by
  `tests/curation/test_semantic_never_autowrites.py`). A declined contradiction finding is suppressed
  on rerun via the shared `app.proposals.declined_ledger.DeclinedLedger`, identically to every other
  proposal-emitting pass.
- **Test path:** `tests/invariants/test_curation_invariants.py::test_citations_resolve`,
  `tests/curation/test_contradiction_citations_resolve.py` (including
  `test_declined_contradiction_suppressed`), `tests/curation/test_semantic_never_autowrites.py`.
- **Related issues:** #2999 (G2-4), #2980 (parent).

## Schema-batch deferred invariants

### mirrors_declare_and_check_drift

- **Purpose:** Any retained descriptive mirror of a runtime value is generated
  from its canonical source or removed; an executable static check detects a
  stale legacy prompt mirror.
- **Current enforcement:** `static_test` —
  `tests/architecture/test_prompt_mirror_drift.py::test_mirrors_are_generated_or_absent`.
- **Related issues:** #3164 (SET-6).

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
  structurally) + `runtime_test` (the full ordinal ≤ comparison now runs over `mimer_runtime.retrieval`).
- **Runtime test path:** `tests/invariants/test_retrieval_result.py::test_retrieval_cannot_upgrade_intrinsic_non_evidence` (schema part passes); full monotonicity: `tests/invariants/test_retrieval_result.py::test_retrieval_full_evidence_monotonicity_runtime` (runtime — passes).
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

### observation_episode_binding_survives

- **Purpose:** An observation's `episode_ref` (the lived situation it originated in) and the referenced
  Episode's closure state are preserved through every derivation — segment, projection, retrieval,
  context assembly — just as `scope_binding` and provenance are.
- **Protected principle:** matrix #3, #16 (provenance/context survives derivation); doctrine — an
  artifact's lived context is part of what it means.
- **Affected boundaries:** SIP, DRI, RCA, HKA.
- **Required fixture / data:** the `episode_ref` dimension
  ([semantic-dimensions](../architecture/semantic-dimensions.md)); the metadata bundle schema
  (`schemas/metadata-bundle.schema.json`); [ADR-0051](../adr/ADR-0051-episode-as-ontological-primitive.md).
- **Expected failure mode:** a segment/projection/retrieval result drops `episode_ref`, so an
  observation can no longer be traced to the situation that produced it and closure-driven decay
  cannot apply.
- **Current enforcement:** `schema_enforced` (`episode_ref` is a required bundle field; the
  derived-types `allOf` conditional requires it alongside `derived_from`) + `runtime_test` (derivation
  runtime, `mimer_runtime.dri.derive_segment` propagates the source's binding — unbound, pending, or
  bound). Scope: the field-threading and derivation-survival half of this invariant was enforced by
  #3178 / ERE-03; real episode-id assignment (`app.episodes.assignment.compute_assignments`, #3180 /
  ERE-05) now feeds a real computed decision through the same production derivation path
  (`test_observation_episode_binding_survives__ere05_end_to_end`) as an additional end-to-end case.
  Episode-closure-driven relevance decay (the Event Horizon model, ADR-0058) and retrieval
  consumption of `episode_ref` remain `future_runtime` — that lands in ERE-06.
- **Runtime test path:** `tests/invariants/test_episode_binding.py::test_observation_episode_binding_survives` (runtime — passes).
- **Related docs / contracts / ADRs:** [semantic-dimensions](../architecture/semantic-dimensions.md) (`episode_ref`), [functional-ontology](../architecture/functional-ontology.md) (`Episode`), [metadata-bundle](../architecture/metadata-bundle.md) §1/§3/§4; ADR-0051, ADR-0029, ADR-0058.
- **Related issues:** #3178 (ERE-03), #3180 (ERE-05, end-to-end case); grounded in [EPISODE_AS_ONTOLOGICAL_PRIMITIVE](../research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md).

## Vault multi-writer consistency invariants (ADR-0055)

### stale_write_rejected_for_rewritten_notes

- **Purpose:** A writer to a rewritten-class vault note (human prose, `_heimdal/**` control notes,
  companion notes) that supplies the raw-byte version it read must not silently overwrite a version
  that changed since that read; an initially stale proposal is detected and staged as a conflict
  artifact, never dropped.
- **Protected principle:** the vault is canonical human-authored store; a collision must be loud, not silent.
- **Affected boundaries:** WSP, HKA.
- **Required fixture / data:** the authoritative note-class table, the public
  `expected_version` request path, and the descriptor-anchored filesystem adapter exercised by
  `tests/invariants/test_vault_multiwriter.py`.
- **Expected failure mode:** an opted-in writer races another writer and either silently replaces the
  newer canonical bytes, loses its own proposal, or acknowledges a non-canonical outcome as success.
- **Current enforcement:** `runtime_test` — enforcement is intentionally opt-in during the progressive
  migration decided on 2026-07-13. A versionless rewritten write still writes and reports its
  `note_class`; #3570 tracks migration of those remaining callers. When `expected_version` is supplied,
  a matching write uses the atomic rewritten-note seam, while an initially stale proposal leaves the
  canonical note unchanged and is durably staged with writer provenance. Receiptless post-linearization
  races fail without a success acknowledgement and retain scanner-inert recovery evidence.
- **Runtime test path:**
  `tests/invariants/test_vault_multiwriter.py::test_rewritten_write_enforces_only_on_opt_in_expected_version_at_filesystem_seam`,
  `tests/invariants/test_vault_multiwriter.py::test_rewritten_write_uses_atomic_replace_at_filesystem_seam`,
  `tests/invariants/test_vault_multiwriter.py::test_stale_rewritten_write_stages_conflict_artifact_at_filesystem_seam`.
- **Related docs / contracts / ADRs:** ADR-0055, ADR-0053 (superseded); `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2/§7 (INV-VW1).
- **Related issues:** #3132, #3450, #3451; progressive caller migration #3570 remains open.

### write_guard_asserted_at_every_write_seam

- **Purpose:** Every vault write seam — including `append_note_relative`, not just `write_note_relative` —
  asserts `WriteGuard` before writing.
- **Protected principle:** a single write-health gate governs all vault mutation; no seam is exempt.
- **Affected boundaries:** WSP.
- **Required fixture / data:** `app/knowledge/write_ops.py::write_note_relative`,
  `app/knowledge/write_ops.py::append_note_relative`, and controlled healthy/safe-mode `WriteGuard`
  states.
- **Expected failure mode:** `append_note_relative` writes to the vault while the runtime is in an
  unhealthy/safe-mode state, because it is not asserted like its `write_note_relative` sibling.
- **Current enforcement:** `gate` + `runtime_test` — both relative write seams assert `WriteGuard`
  before resolving the knowledge port. `append_note_relative` rejects a safe-mode guard before any
  port resolution and permits a healthy guarded append; this enforcement is independent of the
  stale-detection mechanism above.
- **Runtime test path:**
  `tests/knowledge/test_write_ops.py::test_append_note_relative_rejects_unhealthy_write_guard`,
  `tests/knowledge/test_write_ops.py::test_append_note_relative_allows_healthy_write_guard`.
- **Related docs / contracts / ADRs:** ADR-0055; `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2/§7 (INV-VW2).
- **Related issues:** #3129, #3114, #3020.

### icloud_conflict_artifacts_never_silently_ingested

- **Purpose:** iCloud conflicted-copy files (`* (conflicted copy).md` and similar) are detected and
  quarantined by the watcher/ingest scan, never ingested as ordinary notes.
- **Protected principle:** a detected storage-layer conflict must be surfaced, not silently absorbed into
  the knowledge graph as duplicate content.
- **Affected boundaries:** SIP, WSP.
- **Required fixture / data:** the shared conflict-artifact classifier and the production vault
  Markdown iterator, exercised with both synthetic iCloud and runtime-staged sibling names.
- **Expected failure mode:** `Note (conflicted copy).md` is ingested as a distinct ordinary note, doubling
  content and confusing search/graph results.
- **Current enforcement:** `runtime_test` — the production iterator classifies both iCloud conflicted
  copies and runtime-staged conflict artifacts before ordinary watcher/ingest/index parsing, preserves
  them on disk, and emits a bounded quarantine receipt. Normal Markdown siblings remain visible.
- **Runtime test path:**
  `tests/watcher/test_vault_conflict_quarantine.py::test_conflicted_copy_is_not_yielded_as_ordinary_note`,
  `tests/watcher/test_vault_conflict_quarantine.py::test_staged_conflict_artifact_is_not_yielded_as_ordinary_note`,
  `tests/watcher/test_vault_conflict_quarantine.py::test_quarantine_preserves_normal_sibling_note`,
  `tests/watcher/test_vault_conflict_quarantine.py::test_quarantine_does_not_delete_conflict_artifact`.
- **Related docs / contracts / ADRs:** ADR-0055; `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2/§7 (INV-VW3).
- **Related issues:** #3132, #3450, #3452.

## Coverage map (invariant → principle → test)

| Invariant | Matrix principle(s) | Primary boundary | Enforcement | Test path |
| --- | --- | --- | --- | --- |
| capture_stamps_scope | #2 | WSP/SIP | schema + runtime | `tests/invariants/test_metadata_bundle.py` |
| metadata_bundle_required | #2,#3,#12 | SIP | schema + static | `tests/invariants/test_metadata_bundle.py` |
| store_no_naked_vectors | #12,#16 | PDM/DRI | schema + static | `tests/invariants/test_metadata_bundle.py` |
| provenance_survives_derivation | #3,#16 | DRI/SIP | schema + runtime | `tests/invariants/test_metadata_bundle.py` |
| retrieve_scope_prefilter | #1,#7 | RCA | schema + runtime | `tests/invariants/test_cross_scope_flow.py` |
| similarity_not_permission | #1 | RCA/GOV | doc + runtime | `tests/invariants/test_cross_scope_flow.py` |
| cross_scope_only_via_flow | #1,#6 | GOV/RCA | schema + runtime | `tests/invariants/test_cross_scope_flow.py`, `tests/evals/test_general_knowledge_crosses_clean.py` |
| rpg_not_confused_with_software | #1,#5 | RCA/SIP | static + runtime | `tests/evals/test_rpg_not_confused_with_software.py` |
| private_not_in_work_results | #1,#2 | WSP/GOV | static + runtime | `tests/evals/test_private_not_in_work_results.py` |
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
| retrieval_cannot_upgrade_intrinsic_non_evidence | #1,#5,#8 | RCA/GOV | schema + runtime | `tests/invariants/test_retrieval_result.py` |
| memory_item_authority_is_noncanonical | #4,#5 | MEM/GOV | schema + static | `tests/invariants/test_agent_memory.py` |
| memory_item_cannot_be_real_world_evidence | #4 | MEM/GOV | schema + static | `tests/invariants/test_agent_memory.py` |
| authority_transition_requires_decision_token_and_receipt | #9 | GOV/HKA | schema + static | `tests/invariants/test_authority_transition.py` |
| authority_transition_state_is_consistent | #9 | GOV | schema + static | `tests/invariants/test_authority_transition.py` |
| context_bundle_is_not_context_envelope | #7,#8 | RCA/CAO | schema + static | `tests/invariants/test_context_envelope.py` |
| storage_write_is_not_authority_transition | #9,#12 | PDM/GOV | doc + xfail | `tests/invariants/test_authority_transition.py` (xfail) |
| observation_episode_binding_survives | #3,#16 | SIP/DRI/RCA | schema + runtime | `tests/invariants/test_episode_binding.py` |
| propose_when_uncertain | #17 | CAO/GOV/HIX | doc + xfail | `tests/invariants/test_context_envelope.py` (xfail) |
| standards_are_adapters | #18 | EBF/SIP/CES | doc_only | `TBD` (CES review) |
| connect_proposals_candidate_only | #9 | GOV/RCA | static + runtime | `tests/invariants/test_expansion_invariants.py`, `tests/expansion/test_connect_findings.py` |
| declined_findings_not_reproposed | #9 | GOV/RCA | static + runtime | `tests/proposals/test_declined_ledger.py`, `tests/invariants/test_expansion_invariants.py` |
| create_never_autowrites_canonical | #9 | GOV/RCA | static + runtime | `tests/invariants/test_expansion_invariants.py`, `tests/expansion/test_create_draft_lifecycle.py` |
| synthesis_carries_source_provenance | #4,#9 | GOV/RCA | static + runtime | `tests/invariants/test_expansion_invariants.py`, `tests/expansion/test_create_draft_lifecycle.py` |
| staged_drafts_invisible_to_retrieval | #1,#9 | RCA/GOV | static + runtime | `tests/invariants/test_expansion_invariants.py`, `tests/expansion/test_create_draft_lifecycle.py` |
| expansion_requires_activation_record | #9 | GOV | static + runtime | `tests/invariants/test_expansion_invariants.py`, `tests/activation/test_expansion_gate_records.py` |
| curation_citations_resolve | #3,#9 | GOV/RCA | static + runtime | `tests/invariants/test_curation_invariants.py`, `tests/curation/test_contradiction_citations_resolve.py` |
| stale_write_rejected_for_rewritten_notes (INV-VW1) | vault canonical + fail-loud | WSP/HKA | runtime (opt-in expected-version seam) | `tests/invariants/test_vault_multiwriter.py::test_rewritten_write_enforces_only_on_opt_in_expected_version_at_filesystem_seam`, `tests/invariants/test_vault_multiwriter.py::test_stale_rewritten_write_stages_conflict_artifact_at_filesystem_seam` |
| write_guard_asserted_at_every_write_seam (INV-VW2) | vault canonical + fail-loud | WSP | gate + runtime | `tests/knowledge/test_write_ops.py::test_append_note_relative_rejects_unhealthy_write_guard`, `tests/knowledge/test_write_ops.py::test_append_note_relative_allows_healthy_write_guard` |
| icloud_conflict_artifacts_never_silently_ingested (INV-VW3) | vault canonical + fail-loud | SIP/WSP | runtime | `tests/watcher/test_vault_conflict_quarantine.py` |

## Heimdal invariants (HEIM-1..14) — sibling registry

The Heimdal constituent (Epic #3019, ADR-0049) keeps its own fitness-invariant registry rather than
duplicating entries here: **`docs/HEIMDAL/FABLE_COMPANION.md` §8** is canonical for HEIM-1..14 —
purpose, protected principle, affected boundaries, and declared enforcement level
(`schema_enforced` / `static_test` / `future_runtime` / `xfail_runtime_skeleton`) per invariant. This
registry's enforcement-category vocabulary (above) is shared verbatim; only the invariant list itself
is Heimdal-owned to avoid two registries drifting on the same rows.

§8 reserves `tests/invariants/test_heimdal_*.py` as each invariant's eventual test home (none of those
files exist yet). The interim skeleton landing (#3033, Epic A slice A13) lives at
[`tests/heimdal/test_invariants_heim.py`](../../tests/heimdal/test_invariants_heim.py): one skeleton
per HEIM-1..14, each xfail (honestly, via a Heimdal-local `require_future_heimdal_runtime` guard mirroring
[`tests/invariants/_helpers.py::require_future_runtime`](../../tests/invariants/_helpers.py)) or, where
Heimdal slices A3/A5/A6 already discharge the invariant for real (HEIM-3, HEIM-8, HEIM-9), calling the
real production path directly so a regression would fail the test rather than silently re-xfail.

## Settings Spine invariants (SET-1..7)

The Settings Spine (feature #3156, Option B ruling) consolidates five settings substrates into two
scopes and one spine. Each SET invariant below is a fitness rule the spine must satisfy; they are
added as their child slices land.

### settings_take_effect_or_fail_loud

- **Purpose:** Vault-authored settings take effect in running services at startup and on edit, or a
  degraded state is surfaced loudly on the health contract — a service never silently runs on pydantic
  code defaults while a vault with settings sources is selected.
- **Protected principle:** SET-1 (settings take effect or fail loud); closes audit F1, the same
  silent-false-green class the correctness kernel targeted.
- **Affected boundaries:** WSP (settings resolution); DRI (bundle is a rebuildable projection); OEF
  (health signal).
- **Required fixture / data:** a settings source dir (`compiler.VAULT`) with a source `.md` overriding
  a default; a redirected runtime projection dir; an invalid-YAML source for the degrade case.
- **Expected failure mode:** a deployed container ignores the vault and serves hardcoded defaults with
  nothing signalling it (audit F1); or an invalid edit silently falls back to code defaults.
- **Current enforcement:** `runtime_test` — delivered by #3159 (SETTINGS-01). The production ingestion
  entrypoint (`app/settings/ingestion.py::ingest_settings`) is driven directly, and the degraded state
  is asserted from the production reload call site.
- **Eventual test path:** `tests/settings/test_ingestion_startup.py` (passes today).
- **Related docs / contracts:** `docs/SETTINGS_SPINE/WIRE_SETTINGS_INGESTION.md`,
  `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F1`, `docs/OBSERVABILITY.md` (health
  `settings` field).
- **Related issues:** #3159; parent #3156.

### single_default_registry

- **Purpose:** Every behavior-shaping environment default is declared exactly once; no call site
  re-inlines a literal default (`os.getenv("KEY", "literal")`) for a registered key, so two components
  can never silently disagree about one knob.
- **Protected principle:** SET-4 (one declaration per behavior-shaping default); prevents the
  five-substrate split-truth divergence from regrowing at new call sites.
- **Affected boundaries:** WSP (settings resolution).
- **Required fixture / data:** the registry `app/settings/env_defaults.py::ENV_DEFAULTS`; a synthetic
  offending source file for the negative case.
- **Expected failure mode:** the same env knob resolves to different defaults at different call sites
  (audit F3: `LLM_TIMEOUT` → 12s/60s/120s; `WATCHER_ENABLE` → "0"/"1") with nobody having decided the
  value.
- **Current enforcement:** `static_test` — delivered by #3160 (SETTINGS-02).
- **Eventual test path:** `tests/architecture/test_single_default_registry.py` (passes today).
- **Related docs / contracts:** `docs/SETTINGS_SPINE/SINGLE_DEFAULT_REGISTRY.md`,
  `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3`.
- **Related issues:** #3160; parent #3156.

### every_settings_write_receipted

- **Purpose:** Every settings writer emits a durable, actor-tagged, key-scoped receipt after a
  successful mutation; receipt observation never authorizes or gates the mutation.
- **Protected principle:** SET-3 (every settings write is receipted); closes audit F5 without adding
  an approval loop.
- **Affected boundaries:** GOV (receipt accountability), WSP (settings writers), OEF (queryable
  observability).
- **Required fixture / data:** compiler auto-heal source, watcher `settings/local.md` delta,
  pre-vault app-local store, and the durable settings-receipt query projection.
- **Expected failure mode:** a writer mutates settings with no durable evidence, or a receipt-sink
  failure blocks an otherwise valid settings write.
- **Current enforcement:** `runtime_test` — delivered by #3162 (SETTINGS-04); production compiler,
  watcher, settings-service, and app-local call sites use the shared best-effort dual-sink seam.
- **Runtime test path:** `tests/vault/test_settings_receipt_durable.py`,
  `tests/watcher/test_settings_delta_receipts.py` (pass today).
- **Related docs / contracts:** `docs/SETTINGS_SPINE/RECEIPT_EVERY_SETTINGS_WRITE.md`,
  `docs/EVENTS.md :: settings.write.receipt`,
  `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F5`.
- **Related issues:** #3162; parent #3156.

## Related documents

- [Traceability matrix](../architecture/traceability-matrix.md) — principle → contract → **this registry** → test → issue
- [Anti-contamination eval fixtures](../../tests/evals/fixtures/README.md) — the corpus several invariants require (#2551)
- [Schemas README](../../schemas/README.md) — which checks are declarative-schema-impossible and deferred here
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) · [Boundary charters](../boundaries/README.md) · [ADR index](../adr/INDEX.md)
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) · [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md)
