State: Advisory architecture audit snapshot, 2026-07-17. Evidence baseline: `origin/main` at `0320859ff7bed12a927d576223f2def9de76ab16`. Subordinate to `docs/DOCS_INDEX.md`, current-state owner docs, and accepted ADRs. Accepted decision surface: `docs/adr/ADR-0063-shared-llm-contract-kernel.md` (owner decision 2026-07-17); no executable specification or implementation issues exist from this audit.
Doc role: Reference (architecture audit snapshot)
Authority: Evidence-based structural analysis only. Current Product behavior remains owned by `docs/LLM_ROUTING.md`, `docs/LLM.md`, and code; Builder authority remains owned by ADR-0010, ADR-0062, and BuilderOps specifications. Owner docs win on disagreement.
Owner: Architecture spine / Product LLM / BuilderOps governance boundary
Temporal class: Point-in-time audit; refresh rather than silently treating implementation or GitHub lifecycle claims as current.

# Product LLM Fabric and Builder LLM Capability Runtime coordination — 2026-07-17

## 1. Charter and research questions

This audit answers the mandatory architecture question:

> Should Builder Capability Runtime reuse Mimer's LLM Fabric, share a neutral contract kernel with
> it, or integrate only through an external adapter?

It also resolves:

- which current LLM concepts are Product-specific, neutral, duplicated, or absent on the Builder
  side;
- where current imports point across the wrong authority boundary;
- how fallback, registry, identity, failure, health, trace, and schema semantics remain compatible
  without becoming shared policy;
- which invariants and contract tests must gate a later implementation; and
- how to migrate incrementally without a simultaneous rewrite.

Three read-only evidence passes covered Product LLM runtime, Builder LLM/Model Inquiry runtime, and
architecture/governance/tests. Synthesis re-read the cited code and docs. Live GitHub reconciliation
used REST/search on 2026-07-17; no issue or PR was created or changed.

## 2. Current-state map

### 2.1 Mimer Product LLM Fabric

The Product surface is a real router/fabric, not only a client wrapper:

- `LLMTaskIntent` carries task kind, complexity, risk, budget, determinism, schema, latency, and
  strict-identity hints; `LLMRoute` carries provider, model, mode, reason, degraded status, and
  optional embedding identity (`app/components/llm/router.py:14-33`).
- `LLMRouter` loads Product settings and Product model descriptors, selects task policies, compiles
  primary/fallback candidates, applies environment/force overrides, and enforces embedding identity
  compatibility (`app/components/llm/router.py:88-160,195-378,430-580`).
- `ChatClient`, `get_chat_client`, and `get_embeddings_client` bind a route to Product chat and
  embedding implementations (`app/components/llm/fabric.py:11-50`).
- constrained completion owns a process-local schema registry, strict JSON Schema validation, and a
  typed `ConstrainedCompletionError` around Product provider calls
  (`app/components/llm/constrained.py:40-177`).
- `ReasoningFacade` adds Product reasoning taxonomy, provider calls, trace IDs, local telemetry, and
  best-effort audit integration (`app/components/reasoning/facade.py:39-67,190-227,231-385,
  504-620`). Component documentation marks this facade experimental/opt-in rather than part of the
  locked baseline (`docs/COMPONENTS.md:100-106`); Product still owns its semantics and evolution.
- Product routing policy is compiled from vault settings and may allow local/mock fallback for chat;
  embeddings have identity/reconciliation-specific rules (`docs/LLM_ROUTING.md:27-34,36-67,
  84-100,145-150`).

The Product model registry is a Product configuration surface. Its checked-in registry points to
Product model descriptors (`docs/settings/models/registry.yaml:1-26`), and its loader owns the
descriptor schema and allows a `MODEL_REGISTRY_PATH` override
(`app/components/settings/models_loader.py:11-75`).

### 2.2 Builder LLM execution today

There is no general Builder Capability Runtime or Builder Capability Registry on `main`. There are
two concrete Builder patterns:

1. **Model Inquiry's Builder-only adapter boundary.** It requires explicit Fable and GPT/Codex role
   adapters, distinct adapter IDs/runtime fingerprints, non-mock identities, structured output,
   provider request IDs, artifact hashes, terminal failure receipts, and no fallback
   (`app/builderops/model_inquiry_adapters.py:20-79,278-397`; `app/builderops/model_inquiry_runner.py:
   28-35,115-216,284-388`). The subscription launcher pins separate model roles and xhigh effort
   (`scripts/model_inquiry_subscription_adapter.py:14-53`).
2. **CKM semantic association's Product Fabric dependency.** A BuilderOps projection/inference
   component imports Product schema validation, `LLMTaskIntent`, and `get_chat_client`, uses the
   Product `classify` route, and only rejects mock after Product routing completes
   (`app/builderops/ckm/semantic.py:27-34,116-192`).

Model Inquiry documentation explicitly says why it does not reuse Product routing: Product returns
text without the required provider envelope and may choose mock fallback
(`docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md:20-32`). The same spec requires no provider
substitution and keeps credentials/subscription sessions/host paths outside Git
(`docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md:58-62,95-119`).

### 2.3 Existing enforcement

- The current high-level import test requires selected Product application layers to use Product
  Fabric instead of concrete Product provider modules, but it does not scan `app/builderops/` and
  therefore cannot express the future Product/Builder separation
  (`tests/architecture/test_import_rules.py:104-137`).
- Model Inquiry tests cover explicit role configuration, distinct runtime targets, strict response
  parsing, provider/request lineage, terminal failures, and no fallback (named in
  `docs/BUILDEROPS_MODEL_INQUIRY/README.md:94-110` and
  `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md:76-93`).
- CKM tests validate structured Product-Fabric response handling, but the test fixture deliberately
  constructs `FabricSemanticAssociator`; it does not test Builder credential or routing isolation
  (`tests/builderops/ckm/test_semantic.py:227-254`).

## 3. Ranked structural findings

### F1 — High: the authority boundary has two conflicting Builder patterns

Model Inquiry correctly treats Builder execution as separately configured and receipt-bearing, while
CKM reaches through Product routing. A future general Builder runtime built beside both patterns
would either duplicate semantics a third time or inherit Product policy accidentally.

### F2 — High: Product routing types mix neutral data with Product policy semantics

`LLMTaskIntent` and `LLMRoute` look reusable, but their meaning is supplied by Product task-policy
lookup, vault-compiled settings, environment precedence, Product provider names, Product fallback,
and embedding identity (`app/components/llm/router.py:145-160,195-378`; `docs/LLM_ROUTING.md:36-67`).
Direct type reuse would therefore imply more semantic sharing than the dataclass declarations show.

### F3 — High: fallback vocabulary is too weak for Builder independence claims

Product policy has `never`, `local`, `allowed`, and `skip`, and the router can append a mock fallback
when a non-mock chat primary has no explicit fallback target
(`app/settings/models.py:62-96`; `app/components/llm/router.py:307-378`). Model Inquiry forbids
fallback and requires distinct runtime targets. A shared boolean or Product fallback enum cannot
represent same-identity, compatible-identity, policy-selected, or human-decision-required behavior
without losing authority and provenance. The Product candidates are route-selection inputs, not a
generic failover loop after provider execution fails (`app/components/llm/router.py:471-500`;
`app/components/llm/fabric.py:15-36`), so even the word “fallback” must retain phase semantics.

### F4 — Medium: general validation and identity primitives are trapped in authority-specific modules

Strict schema registration/validation is neutral in behavior but physically lives under Product
`app.components.llm`; Builder Model Inquiry separately validates its own response contract. Provider,
model, request, hash, and trace fields likewise exist in both surfaces with no versioned shared shape
(`app/components/llm/constrained.py:60-107`; `app/builderops/model_inquiry_contract.py:176-225`;
`app/builderops/model_inquiry_runner.py:346-371`).

### F5 — Medium: health and telemetry cannot currently be compared without conflation

Product health reports default routes, effective policy, provider health, and embedding-index
compatibility (`docs/LLM_ROUTING.md:132-143`). Builder Model Inquiry reports terminal receipts and
sanitized adapter failures, while ADR-0062's target Builder control plane owns separate `/healthz`,
`/readyz`, credential state, and executor heartbeat
(`app/builderops/model_inquiry_adapters.py:408-420`;
`docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md:30-44`). A common display state
is useful; a common receipt or health authority would be false.

### F6 — Medium: the existing facade rule is Product-only and incomplete even for today's code

The import test scans selected high-level directories, not all provider-call sites. Product legacy
modules remain below the Fabric seam, and Builder adapter/provider calls intentionally live outside
it. A future global rule that simply says “all LLM calls use Product Fabric” would make the intended
Builder separation impossible (`tests/architecture/test_import_rules.py:104-137`).

### F7 — Medium: Product's own advertised single seam has current divergences

The coordination contract must not freeze current Product inconsistencies into the neutral kernel:

- `app/chat/reflection_conversation.py:12-19,278-285` calls `app.services.llm.call_llm` directly even
  though `docs/LLM_ROUTING.md:7-9` says Product Fabric is the sole high-level entrypoint; the import
  test does not scan `app/chat` (`tests/architecture/test_import_rules.py:106-124`).
- router construction catches every settings-bundle exception and proceeds without compiled policy,
  while the owner doc describes routing as deterministic and single-source
  (`app/components/llm/router.py:133-160`; `docs/LLM_ROUTING.md:18-20,36-43`).
- strict `constrained_completion` rejects invalid/empty/non-object output, while
  `ReasoningFacade.structured` performs prompt-only JSON parsing and leaves schema validation to the
  caller (`app/components/llm/constrained.py:138-177`;
  `app/components/reasoning/facade.py:272-324`).
- chat provider routing, embedding provider registry, and provider-health reporting use different
  provider sets/dispatch structures (`app/components/llm/router.py:42-60`;
  `app/llm/embeddings.py:372-381`; `app/cli/health.py:190-222,314-335`).

These are evidence for migration gates, not findings this docs-only pass repairs. Current owner docs
and shipped tests remain authoritative until bounded follow-up work reconciles them.

## 4. Mandatory decision and option assessment

**Recommendation: share a neutral LLM Contract Kernel; retain separate Product and Builder execution
fabrics; use explicit mappers or external adapters only at cross-runtime boundaries.** Do not reuse
Mimer Product LLM Fabric as Builder Capability Runtime.

| Criterion | Reuse Product Fabric | Shared neutral kernel + separate runtimes | External adapter only |
| --- | --- | --- | --- |
| Authority boundaries | Poor: Product policy becomes Builder input | Strong: shared semantics, separate authority | Strong at process seam |
| Governance | Poor: one owner surface carries conflicting policies | Strong: CES versions kernel; each runtime owns policy | Medium: every adapter recreates mapping policy |
| Local-first | Medium: Product local routes available, but wrong config authority | Strong: each runtime chooses its own local/remote posture | Strong, with transport dependency |
| Testability | Medium: fewer components but hidden policy coupling | Strong: pure contracts/mappers plus runtime tests | Medium: contract tests repeat per adapter |
| Credential isolation | Poor for subscription/Builder credentials | Strong by construction | Strong by process boundary |
| Observability | Poor: Product and Builder states appear unified | Strong: common vocabulary, separate receipts | Medium: aggregation is adapter-specific |
| Failure semantics | Poor: Product fallback and text errors do not cover Builder receipts | Strong: common taxonomy, runtime-specific details | Medium: translation drift risk |
| Portability | Poor: Builder depends on Mimer vault/runtime modules | Strong: kernel is neutral, runtimes portable | Strong for remote clients, weaker semantic reuse |
| Operational complexity | Low initially, high when exceptions accumulate | Medium and explicit | Medium-high with per-adapter duplication |
| Parallel abstraction risk | Hidden divergence inside one overloaded fabric | Lowest | High: semantics remain duplicated |

The decision is Accepted in ADR-0063. Acceptance settles the boundary but does not make this audit an
implementation contract; `feature-breakdown` must produce executable specifications and Issues first.

## 5. Concept decision matrix

`extract` below means “extract a neutral contract/validation primitive after ADR acceptance,” not
“move the current Product implementation wholesale.” `map` always means an explicit, versioned,
fail-loud mapper.

| Existing concept | Disposition | Rationale |
| --- | --- | --- |
| `LLMTaskIntent` | `map`, then selectively `extract` | The fields are partly neutral, but `task_kind` and policy resolution are Product-owned. Preserve the Product type; extract only authority-neutral intent fields and map explicitly to `CapabilityRequest`. |
| `LLMRoute` | `map` | Provider/model/mode are portable; reason, degraded state, embedding identity, and policy source have Product semantics. Map through a neutral resolution/provenance envelope; do not make it Builder's native route. |
| Provider/model identity | `extract` | A neutral identity and provenance shape removes duplicate strings/hashes while preserving source registry, version, runtime, and effective target. |
| Routing reason/degraded status | `extract` vocabulary + `map` receipts | Shared display vocabulary is useful; Product route state and Builder attempt/receipt state remain separate authorities. |
| Product task-kind taxonomy | `keep separate` | `ask`, `plan`, `embed`, reasoning, eval, and Product classification are Product policy keys. Builder review, inquiry, repair, verification, and role kinds have different governance and side effects. |
| Model registry | `extract` descriptor schema; `keep separate` registries | Shared shape, separate authority/version/write path. No automatic two-way sync. |
| Compiled Product routing policy | `keep separate` | It is derived from Product vault settings and owns Product fallback/embedding policy. Builder must not read it implicitly. |
| `ChatClient` | `reuse` inside Product; `keep separate` in Builder | It returns Product text through Product `call_llm` and lacks Builder provider-request/receipt semantics. Builder adapters need their own result envelope. |
| `get_chat_client` | `reuse` inside Product; `deprecate` direct Builder use | Canonical Product entrypoint. CKM's direct Builder import becomes migration debt after a Builder runtime exists. |
| `get_embeddings_client` | `reuse` inside Product; `keep separate` in Builder | Embedding identity and reconciliation are Product-owned. A future Builder embedding capability must declare its own authority and identity need. |
| Schema registry | `extract` | JSON Schema registration, versioning, collision refusal, and payload validation are neutral and side-effect-free. Runtime-specific schema ownership remains explicit. |
| Constrained completion | `extract` validation core + `map` execution result | Provider execution/fallback stays runtime-specific; strict parse/validate and typed invalid-output semantics can be shared. |
| Typed provider failures | `extract` common taxonomy + `map` details | Product timeout and Builder adapter diagnostics differ, but both need stable unavailable/timeout/refused/invalid/rate-limited/auth/persistence classes without leaking secrets. |
| Health reporting | `extract` vocabulary + `keep separate` receipts | Aggregate status may compare `healthy/degraded/unavailable/misconfigured`; Product and Builder health endpoints, causes, and receipts must not be merged. |
| Trace ID and telemetry | `extract` reference shapes; `keep separate` stores | Preserve trace/request/artifact/receipt linkage. Product telemetry and BuilderOps lineage have different retention and authority. |
| `ReasoningFacade` | `keep separate` | It is Product cognition with Product task taxonomy, telemetry, audit, and fallback behavior; it is not a general Builder execution facade. |
| Builder Model Inquiry adapter protocol | `reuse` as Builder baseline; later `map` behind Capability Runtime | It already enforces the strongest Builder-specific role/identity/failure constraints. Evolve behind the Builder boundary instead of replacing it. |
| CKM `FabricSemanticAssociator` | `deprecate` after replacement | It is the current wrong-direction Builder-to-Product policy dependency. Keep it until a tested Builder capability adapter exists; do not delete it speculatively. |

## 6. Compatibility contract

### 6.1 Required neutral fields

The kernel contract needs, at minimum:

- request/intent ID, task/capability kind, deadline, determinism requirement, input schema ref, output
  schema ref, and side-effect class;
- provider, model, adapter/runtime target, mode, source registry, registry version, policy authority,
  and requested/effective identity;
- fallback requirement, fallback decision, original/effective identity, decision reason, and degraded
  state;
- typed failure class plus secret-safe runtime detail;
- trace ID, provider request ID, artifact refs/hashes, and runtime-specific receipt refs; and
- health state plus runtime/authority owner.

Credentials, raw headers/errors, provider sessions, Product vault paths/settings, Builder host paths,
and stores are explicitly excluded.

### 6.2 Mapper preservation rules

Every mapper must preserve provider, model, registry provenance, trace, failure class, fallback
requirement/decision, degraded state, deadline, determinism, schema refs, and side-effect class. It
must not:

- change Product or Builder authority;
- turn capability discovery into authorization;
- weaken `fallback_forbidden`;
- present mock/dry-run output as provider execution;
- collapse two Builder roles onto one effective target while retaining an “independent” claim; or
- merge Product and Builder health receipts.

An unknown enum/version/value is a typed mapping failure, never a default.

### 6.3 Fallback model

| Requirement | Allowed behavior | Required provenance |
| --- | --- | --- |
| `fallback_forbidden` | No alternative provider/model/target | failed requested identity and explicit no-fallback outcome |
| `fallback_same_identity` | Retry/transport change only; effective identity identical | transport change, identity equality proof, reason |
| `fallback_compatible_identity` | Explicit compatibility predicate passes | original/effective identity, predicate/version, reconciliation need |
| `fallback_policy_selected` | Owning runtime policy selects a declared alternative | policy authority/version, selected candidate, degraded state |
| `human_decision_required` | Stop before alternative execution | decision request/receipt ref and unavailable state |

Product embedding fallback maps to `fallback_compatible_identity` only when its embedding identity and
reconciliation contract is satisfied. Builder Model Inquiry maps to `fallback_forbidden` for both
independent roles.

## 7. Invariant kernel

| ID | Class | Invariant | Current enforcement |
| --- | --- | --- | --- |
| LLM-COORD-01 | MUST | Product and Builder policy/registry/credential authority is non-transitive. | Partial: ADR-0062 and Model Inquiry separation; violated by CKM Product Fabric import. |
| LLM-COORD-02 | MUST | Product Runtime cannot obtain Builder credentials/subscription sessions; Builder Runtime cannot obtain Product vault credentials/settings implicitly. | Partial: Model Inquiry host boundary and ADR-0062; no general runtime gate. |
| LLM-COORD-03 | MUST | Every fallback requirement and decision is explicit and provenance-bearing; discovery never authorizes substitution. | Partial: Product route reason/degraded and Builder no-fallback; no shared contract. |
| LLM-COORD-04 | GATE | An independent Builder review names distinct effective runtime targets or fails without an independence receipt. | Exists for Model Inquiry adapter descriptors; not generalized. |
| LLM-COORD-05 | GATE | Product and Builder registries cannot mutate each other; imports are directional/versioned. | New; Builder registry does not yet exist. |
| LLM-COORD-06 | MUST | Mappers preserve identity, trace, failure, fallback, degraded state, and side-effect classification or fail loud. | New. |
| LLM-COORD-07 | MUST | Every schema-constrained result is validated after provider execution on both runtime surfaces. | Exists separately; shared semantic parity not enforced. |
| LLM-COORD-08 | DOCTOR | Product and Builder health are comparable in vocabulary but retain separate owner/receipt/trace provenance. | New; current surfaces are separate but not mapped. |
| LLM-COORD-09 | GATE | Direct provider calls occur only inside the owning runtime's approved adapters/facades. | Partial Product import test; no Builder/runtime-wide rule. |
| LLM-COORD-10 | MUST | Mock, dry-run, and test routes can never be reported as real provider execution. | Partial Model Inquiry non-mock rule; Product mock route is intentionally real-as-mock but lacks shared provenance vocabulary. |

The minimal correctness kernel is LLM-COORD-01 through LLM-COORD-07. LLM-COORD-08 through 10 are
defense-in-depth/operability gates. These target invariants must be added to
`docs/testing/invariant-tests.md` only alongside executable enforcement; this audit does not claim
they are shipped.

## 8. Contract-test plan

After ADR acceptance, the eventual specification must name tests with these acceptance targets:

| Contract | Suggested `Verify:` target |
| --- | --- |
| No direct Product LLM calls outside Product facade/adapters | `tests/architecture/test_llm_runtime_boundaries.py::test_product_provider_calls_stay_behind_product_fabric` |
| Builder cannot bypass Capability Runtime | `tests/architecture/test_llm_runtime_boundaries.py::test_builder_model_calls_stay_behind_builder_capability_runtime` |
| Product cannot import Builder credentials/sessions | `tests/architecture/test_llm_runtime_boundaries.py::test_product_runtime_has_no_builder_session_dependency` |
| Shared types have identical serialized semantics | `tests/contracts/test_llm_contract_kernel.py::test_contract_round_trip_is_version_stable` |
| Mappers preserve identity/trace/failure | `tests/contracts/test_llm_contract_mappers.py::test_mappers_preserve_provenance_and_failure` |
| Product fallback cannot enter fallback-forbidden Builder task | `tests/contracts/test_llm_contract_mappers.py::test_product_fallback_cannot_weaken_builder_requirement` |
| Builder registry cannot overwrite Product registry | `tests/architecture/test_llm_registry_authority.py::test_registry_writes_are_authority_local` |
| Schema-constrained output validates on both surfaces | `tests/contracts/test_llm_schema_validation.py::test_both_runtimes_validate_after_execution` |
| Health/degraded states stay separate | `tests/contracts/test_llm_health_mapping.py::test_health_mapping_preserves_runtime_and_receipt_owner` |
| Mock/dry-run never appears as provider execution | `tests/contracts/test_llm_provenance.py::test_non_provider_execution_is_explicit` |
| Builder role independence survives resolution | `tests/builderops/test_capability_role_resolution.py::test_independent_roles_require_distinct_effective_targets` |

These names are proposed verification contracts, not evidence that the files or runtime exist today.

## 9. Stepwise migration with exit criteria

ADR-0063 is Accepted. No implementation step is executable until the work is decomposed through
`feature-breakdown` into strictly valid Issue contracts.

### M0 — Ratify boundary and freeze vocabulary (decision completed)

- ADR-0063 was accepted by the owner on 2026-07-17; version-1 neutral fields and fallback values now
  belong to the specification step.
- Exit achieved for the decision: the accepted ADR receipt names Product/Builder/kernel authority
  without claiming implementation.
- Verify: accepted ADR state and owner receipt link in `docs/adr/ADR-0063-shared-llm-contract-kernel.md`.

### M1 — Introduce contract tests and pure neutral schemas

- Add side-effect-free identity, provenance, failure, health, fallback, trace/receipt-ref, and schema
  validation contracts; no router/client changes.
- Exit: version/round-trip/mapping-negative tests pass; kernel imports no Product or Builder runtime.
- Verify: `tests/contracts/test_llm_contract_kernel.py` plus an import-boundary test.

### M2 — Adapt Product types without changing Product behavior

- Add Product-to-kernel projections around `LLMTaskIntent`, `LLMRoute`, failures, health, and model
  descriptors; retain existing Product APIs.
- Exit: current Product routing/fabric tests are unchanged-green and mapper preservation tests pass.
- Verify: existing `tests/components/llm/` suite plus Product mapper tests.

### M3 — Put a Builder capability boundary around existing Model Inquiry adapters

- Define Builder Capability Registry/Request/Resolution/Result over the current explicit adapters;
  retain role, receipt, restart, host-session, and no-fallback semantics.
- Exit: current Model Inquiry acceptance tests pass through the Builder boundary; no Product settings,
  registry, client, or credentials are imported.
- Verify: existing `tests/builderops/test_model_inquiry_*` plus Builder boundary tests.

### M4 — Migrate CKM through an explicit Builder adapter

- Replace `FabricSemanticAssociator`'s direct Product Fabric dependency with an explicitly governed
  Builder capability or, if CKM is reclassified, document and test the boundary decision first.
- Exit: CKM structured-output and candidate-authority behavior are unchanged; Product policy/mock
  fallback cannot execute the Builder task.
- Verify: `tests/builderops/ckm/test_semantic.py` plus a negative Product-fallback leakage test.

### M5 — Enforce facade, registry, credential, and health boundaries

- Expand architecture tests to scan both runtimes with separate allowlists; add health/registry
  isolation and mock-honesty checks; deprecate superseded duplicate validators/types only after all
  callers migrate.
- Exit: no unapproved direct imports/calls, no cross-registry writes, no credential dependency, and
  no deprecated call sites.
- Verify: the contract-test plan in §8 and a repository-wide import census.

Each step is independently mergeable and behavior-preserving until its own explicit authority change.
No big-bang rewrite, registry merge, or automatic two-way synchronization is permitted.

## 10. Reconciliation with existing work

| Surface | Disposition |
| --- | --- |
| `docs/LLM_ROUTING.md` and Product Fabric | Preserve as current Product authority; do not broaden it into Builder policy. |
| Parent #3288 / `docs/BUILDEROPS_MODEL_INQUIRY/` | Reuse delivered Builder adapter, role, receipt, and no-fallback semantics; parent acceptance remains its own lifecycle. |
| Parent #3788 / `docs/BUILDEROPS_CONTROL_PLANE/` | Extend only after ADR acceptance; the control plane remains Builder process/data/credential/health authority. |
| Issue #3690 | Retains post-cutover owner-doc enactment; do not mix speculative LLM-kernel shipped claims into it. |
| Closed #3144 / CKM semantic association | Preserve delivered behavior; record the direct Product Fabric import as migration debt rather than reopening the merged slice. |
| Open #3429 / Product model cards | Product registry work only; it does not create Builder registry authority. |

The 2026-07-17 GitHub search found no pre-existing issue or PR that owned the neutral-kernel decision
or the full Product/Builder LLM compatibility seam. Accepted ADR-0063 completes M0. Before filing
the remaining M1-M5 tasks, `feature-breakdown` must reconcile live backlog again so it does not
duplicate work created after this audit.

## 11. SBS reconciliation

- **Conforms:** the analysis preserves `SBS_OPERATING_MODEL §3`'s Product/Runtime vs Builder System
  split and ADR-0062's Product/Builder process/data/credential boundary.
- **Extends:** CES would steward one neutral compatibility contract and mapper versions across the
  Product CAO/EBF and Builder enabling-system boundary.
- **Does not reshape the Product SBS:** the accepted kernel is a shared contract surface, not a new
  Product subsystem, provider host, policy owner, or runtime store.
- **Potential later reshape trigger:** a separately deployed shared service, common credential plane,
  global mutable registry, or source-repository extraction would require a new ADR/SBS stewardship
  pass. None is proposed here.

## 12. Resolution

The mandatory architecture answer is:

> **Share a neutral LLM Contract Kernel. Keep Mimer Product LLM Fabric and Builder LLM Capability
> Runtime separate in policy, registry, credentials, provider sessions, fallback, health receipts,
> stores, and execution. Integrate only through explicit, semantics-preserving mappers or external
> adapters.**

This resolves and ratifies the design question but does not authorize direct implementation. The
migration must now be decomposed through `feature-breakdown` before any bounded Issue can become
executable.
