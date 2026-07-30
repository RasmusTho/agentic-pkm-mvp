State: Active validation specification under parent hub #4286. The serial MAS-01..06 implementation
chain is delivered; MAS-06 was delivered by PR #4419 for child issue #4292. Parent acceptance remains
separate. **Owner ruling 2026-07-30 (cost):** metered provider API keys are not provisioned; the
subscription-backed session remains the sanctioned operational auth for host-local model inquiry
(`docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner cost ruling on the
model-inquiry path`). MAS-01..05 stay delivered as merged code; the parent live-proof receipt
`provider_enabled_noninteractive_inquiry.v1` and the legacy-bridge retirement receipt are withdrawn
as acceptance gates. MAS-06 closed the authority leak through a Builder-owned, `fallback_forbidden`
path that fails closed while the declared metered credentials remain intentionally absent and never
substitutes the sanctioned Model Inquiry subscription session.
Doc role: Capability specification (feature-breakdown lane)
Authority: Owns the task decomposition, execution order, cross-task invariants, and acceptance path for the model access substrate. Subordinate to `docs/adr/ADR-0064-model-access-substrate.md` (the decision), `docs/adr/ADR-0063-shared-llm-contract-kernel.md` (contract seam and fallback vocabulary), ADR-0062 (Builder credential/process separation), `docs/LOCAL_SECRET_PROVISIONING/README.md` (host secret boundary and INV-HSP-1..4), and `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` (provider census and egress posture). Owner docs win on disagreement.
Owner: Architecture spine / LLM boundary
Temporal class: strategic
Review cadence: event-driven (task merge, ADR amendment, or a change in the CKM orchestration question)
Source of truth: this directory for task shape and acceptance; ADR-0064 for the decision; `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md` for the evidence baseline
Last reviewed: 2026-07-30

# Model Access Substrate

## Outcome

Model-provider **credential and session resolution is part of the model abstraction** rather than
infrastructure around it, and **declared API keys remain the default programmatic mechanism when a
metered path is authorized**. Under the 2026-07-30 owner cost ruling, host-local Model Inquiry keeps
its sanctioned subscription session while CKM is now off Product routing and fails closed when its
declared metered credential is unavailable. CKM now uses the Builder-owned resolver, declares
`fallback_forbidden`, and produces a visible zero-edge skip in that expected unavailable state. The
neutral seam enables later CI, scheduled-job, and verification-closer migrations; this Phase 1 does
not deliver those consumers. No active provider-backed CKM inference is claimed.

Three mechanisms existed unfinished, and this capability completed them rather than designing a
fourth:

- the **provider census** was specified as R4-1 and is delivered through MAS-01;
- the existing **credential contract** baseline (HSP-01 #3845 / PR #3888, HSP-02 #3846 / PR #4008)
  was extended to model-provider identifiers through MAS-03; and
- the **adapter protocol** `ModelTurnAdapter`, already proven against two structurally different
  transports in a BuilderOps-only module, was promoted to the neutral kernel and consumed through
  the Builder-owned resolver.

**Work classification (SBS operating model):** boundary work. `DEFINE_PROVIDER_CENSUS` and
`EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS` touch Product/Runtime provider surfaces and the shared
host boundary; `PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL` establishes a contract surface both
runtimes depend on; `MAKE_BUILDER_TO_PRODUCT_LLM_DEPENDENCY_VISIBLE`,
`RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT`, and
`REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER` are Builder System work. No task claims new
Product/Runtime user-facing behaviour.

## Scope boundary

This directory decomposes **migration steps 1-5** of `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md`
§8. Step 6 (verification closer resolving model/effort from the census instead of the duplicated
literals at `app/dispatcher/verification_consumer.py:2325-2341`) and step 7 (opportunistic Product
migration) are **out of scope** and are not specified here. The census equality test delivered by
`DEFINE_PROVIDER_CENSUS` is what makes step 7 unnecessary as a program: it blocks new drift from day
one, and existing Product sites migrate behind it.

## Fixed constraints

Every task inherits these. A task specification that breaks one is wrong.

1. **No silent cross-provider fallback.** `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md:135`
   places it out of scope for the adapter boundary and nothing here reopens it.
2. **No mock, fake, deterministic, or dry-run route may be presented as provider execution.**
   `app/builderops/model_inquiry_adapters.py:329-331` marks such a role unavailable; the guard must
   survive every relocation in this capability.
3. **Distinct adapter id and distinct runtime-target fingerprint per independent role.**
   `app/builderops/model_inquiry_adapters.py:332-349`. Role independence is a correctness property of
   adversarial review, not an implementation detail of the current module.
4. **The closed failure vocabulary keeps its double validation.**
   `app/builderops/model_inquiry_adapters.py:26-36` classifies at the adapter;
   `app/builderops/model_inquiry.py:1977-2068` re-validates independently at the persistence boundary.
   Both validations stay. What must never drift is the *vocabulary they validate against*.
5. **ADR-0063's five fallback requirement values are reused unchanged** — `fallback_forbidden`,
   `fallback_same_identity`, `fallback_compatible_identity`, `fallback_policy_selected`,
   `human_decision_required` (`docs/adr/ADR-0063-shared-llm-contract-kernel.md:106-110`). No task may
   introduce a sixth value or a parallel vocabulary.
6. **Credential invariants INV-HSP-1..4 are inherited** (`docs/LOCAL_SECRET_PROVISIONING/README.md:70-78`):
   value non-disclosure, channel isolation, consumer minimization, and fail-closed on a missing or
   malformed secret. Extending the contract to model providers does not weaken any of them.
7. **Steps 1-3 are behaviour-preserving and additive.** `DEFINE_PROVIDER_CENSUS`,
   `MAKE_BUILDER_TO_PRODUCT_LLM_DEPENDENCY_VISIBLE`,
   `EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS`, and
   `PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL` change no runtime behaviour. The first behaviour change
   is `RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT`.
8. **Degradation is visible.** ADR-0064 §6: a degraded result carries `degraded: true` and a reason.
   A path that degrades without an operator-visible signal is a defect, not accepted behaviour.
9. **Mechanism in Git, values host-local.** ADR-0064 §7. Launcher, adapter, census, and contract are
   version-controlled; credential values, provider sessions, and host paths are not.

## Delivered CKM posture (MAS-06 / ADR-0064 §8)

MAS-06 is delivered by PR #4419 for issue #4292. CKM semantic association no longer routes through
Product policy:

- the order did **not** swap; Model Inquiry remained the first beneficiary and CKM migration remained
  migration step 5;
- a builder agent may use the CKM projection as evidence when orchestrating work, but CKM itself
  remains projection-only and has no dispatch, ranking, gating, mutation, or decision authority;
- CKM submits provider-free intent through the Builder-owned resolver with `fallback_forbidden`;
  Product policy, Model Inquiry's subscription session, mock identities, and degraded Builder routes
  cannot execute the task;
- the intentionally unprovisioned metered credential produces a visible zero-edge skip, so no active
  provider-backed CKM inference is claimed; and
- the Product imports and single MAS-02 transition exemption were removed together.

#4169 belongs to the separate deterministic-delivery capability and is not part of this breakdown.
#4131 consumes the accepted Phase 1 receipt for its design-agent adapter slice; it does not broaden
this substrate's authority.

## Task order

| Order | Task | ID | Prerequisite | Outcome |
| --- | --- | --- | --- | --- |
| 1 | [Define provider census](DEFINE_PROVIDER_CENSUS.md) | MAS-01 | — | `docs/settings/models/providers.yaml` is the single typed provider set, including capability declarations and per-runtime/channel tier resolution; static tests name drifted projections. |
| 2 | [Make builder-to-product LLM dependency visible](MAKE_BUILDER_TO_PRODUCT_LLM_DEPENDENCY_VISIBLE.md) | MAS-02 | MAS-01 | Made `app.builderops -> app.components.llm` fail `importlinter` except for exactly one named, dated CKM semantic exemption; MAS-06 removed that exemption with the final Product import. |
| 3 | [Extend credential contract to model providers](EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md) | MAS-03 | MAS-02 | Exact value-free model-key declarations join the existing contract; CI green-on-absent paths are removed. |
| 4 | [Promote adapter contract to neutral kernel](PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL.md) | MAS-04 | MAS-03 | Neutral intent, resolution, capability, adapter/result, failure, fallback, and provenance contracts become importable by both runtimes. |
| 5 | [Resolve model inquiry credentials through contract](RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT.md) | MAS-05 | MAS-04 | Delivers the Builder resolver, declared-credential mechanism, typed failure path, and repo-owned launcher lineage; the operational host remains on its sanctioned subscription session under the later owner ruling. |
| 6 | [Replace CKM product routing with builder adapter](REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER.md) | MAS-06 | delivered MAS-05 mechanism + ADR-0064 owner-cost amendment | Delivered by PR #4419 / issue #4292: CKM semantic association consumes the Builder resolver; Product and subscription fallback cannot execute the task, absent metered credentials produce a visible zero-edge skip, and the transition exemption is removed. |

Flat order: **MAS-01 → MAS-02 → MAS-03 → MAS-04 → MAS-05 → MAS-06.**

No tasks parallelize. The credential, contract, external-provider, and evidence-graph seams make a
serial chain cheaper to verify than coordinating overlapping allowlist, import-boundary, and launcher
changes.

## Cross-task invariants / interaction safety

These hold *across* task boundaries. Each task names the ones it must preserve.

- **INV-MAS-1 — one provider set and provider-free intent.** Every provider allowlist in the repository equals its declared
  census projection. Where a site legitimately diverges today, the divergence is a **declared, dated,
  issue-linked** census entry — never a silent difference and never a relaxed assertion. Adding a
  provider is a census row plus a secret declaration; it is never a new bridge. Callers declare
  capability tier, reasoning effort, determinism, schema reference, independence, fallback
  requirement, and side-effect class; the owning runtime/channel resolver selects provider/model.
- **INV-MAS-2 — metered credentials resolve only through the contract.** Every consumer of a raw
  model-provider API key — CKM, CI, or a future metered Model Inquiry path — obtains its value through
  `app/ops/host_secret_contract.py` and `app/ops/host_secret_bootstrap.py`. INV-HSP-1..4 are inherited
  unchanged. No consumer reads a provider key from ambient process environment as its primary path.
  ADR-0064's 2026-07-30 amendment permits the existing subscription session only for host-local
  Model Inquiry; that exception is not a credential source or fallback for CKM.
- **INV-MAS-3 — one failure vocabulary, two validators.** The adapter-side classification and the
  independent persistence-boundary re-validation both remain. They read one vocabulary source, so a
  member added in one place cannot be missing in the other.
- **INV-MAS-4 — role independence survives relocation.** After every move in this capability, two
  independent roles still require distinct `adapter_id` values and distinct runtime-target
  fingerprints, asserted where the descriptors are actually loaded, not on a copy of the guard.
- **INV-MAS-5 — no silent substitution.** No cross-provider fallback, no mock identity presented as a
  provider, no dry-run presented as execution, and no degradation without `degraded: true` plus a
  reason.
- **INV-MAS-6 — additive until the first beneficiary.** MAS-01 through MAS-04 leave observable runtime
  behaviour unchanged. Any behaviour change discovered in those four is a defect in the task, not a
  licensed consequence.
- **INV-MAS-7 — the interim leak was visible, single, and time-boxed.** MAS-02 introduced exactly one
  named, dated `app.builderops -> app.components.llm` exemption; MAS-06 removed it with the final
  Product import. A second exemption may not be added, and the contract may not be widened to make an
  import pass.

### Partial-failure paths between tasks

Each task is locally correct and can still lose truth in the seam. These are the seams and their
invariants.

- **Seam A — declaration lands while the value is intentionally absent (MAS-03 → MAS-05/MAS-06).**
  The owner ruling leaves `openai.api-key` / `anthropic.api-key` unprovisioned. The hazard is a
  consumer that treats this expected state as permission to select Product policy, an ambient value,
  or the sanctioned Model Inquiry subscription session. **Invariant:** CKM and every metered path fail
  **closed**, name only the logical identifier, and emit a visible zero-edge/unavailable outcome.
  The subscription exception is confined to host-local Model Inquiry and is never a CKM fallback.
- **Seam B — vocabulary added at the adapter but not at persistence (MAS-04 → MAS-05).** If
  `credential_unavailable` is emitted by an adapter but rejected by the persistence-boundary
  validator, a real authentication failure is recorded as a persistence failure and the diagnostic that
  motivated this whole capability is lost a second time. **Invariant:** the two validators share one
  vocabulary source; adding a member is a single edit, proven end-to-end.
- **Seam C — exemption removed before the last import (MAS-02 → MAS-06).** The exemption may only be
  removed in the same change that removes the last `app.components.llm` import from `app.builderops`.
  Removing it earlier reddens main; removing it later leaves a contract that passes for the wrong
  reason. **Invariant:** exemption removal and import removal are atomic, and the contract is never
  made to pass by widening `ignore_imports` or moving a module out of `source_modules`.
- **Seam D — resolved by MAS-06 (MAS-05 → MAS-06, PR #4419 / issue #4292).** The withdrawn
  provider-enabled receipt was not an entry gate. CKM now uses the delivered neutral
  resolver/adapter mechanism, treats the intentionally absent metered credential as unavailable,
  writes zero inferred edges, and never reuses Model Inquiry's subscription session. The CKM
  semantic transition exemption was removed atomically with the production Product import.
- **Seam E — census declared, site not yet migrated (MAS-01 → everything).** A census projection that
  disagrees with a live site must fail, not be quietly widened. **Invariant:** the equality test's only
  escape hatch is a declared divergence entry carrying a linked issue number and a date; an entry
  without both is a test failure.

## Capability acceptance criteria

The capability is accepted when all of the following are true. Each is proven once, at capability level;
the per-task criteria live in the task files.

- [ ] Every provider allowlist in the repository equals its census projection, and a deliberately
      drifted site fails CI naming the site.
      Verify: `tests/settings/test_provider_census.py::test_all_allowlists_match_census`
- [ ] A model-provider credential is declared, channel-scoped, and resolvable through the host secret
      contract, and a missing value fails the consumer closed while naming only the logical identifier.
      Verify: `tests/ops/test_host_secret_contract.py::test_model_provider_identifiers_are_declared_data`
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_model_provider_secret_fails_consumer_closed`
- [ ] The repo-owned metered launcher and role entrypoints remain content/lineage verified and fail
      closed without declared credentials; the operational host's sanctioned subscription launcher
      is documented as a Model Inquiry-only owner exception, not accepted as CKM execution.
      Verify: `tests/governance/test_model_inquiry_host_install.py::test_check_rejects_discoverable_stale_subscription_launcher`
      Verify: `docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner cost ruling on the model-inquiry path`
- [ ] CKM resolves its semantic-association model through a Builder-side adapter, and a Product policy
      fallback cannot execute the Builder task.
      Verify: `tests/builderops/ckm/test_semantic.py::test_product_fallback_cannot_execute_builder_task`
- [ ] No `app.builderops -> app.components.llm` import remains, and the `importlinter` contract passes
      with zero exemptions.
      Verify: `tests/architecture/test_import_boundary.py::test_builder_does_not_import_product_llm_without_exemption`
- [ ] No CI workflow step reports success while its declared model-provider credential is absent.
      Verify: `tests/ops/test_ci_smoke_workflow.py::test_no_workflow_step_is_green_on_absent_provider_secret`
- [ ] `docs/LLM.md`, `docs/LOCAL_SECRET_PROVISIONING/README.md`, and
      `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` describe the delivered mechanism rather
      than the pre-ADR-0064 exclusions.
      Verify: doc writeback at `docs/LLM.md :: Providers (Current)`, at
      `docs/LOCAL_SECRET_PROVISIONING/README.md :: Out of scope`, and at
      `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md :: 5. Slices`

## Validation and acceptance

Each child PR proves its named tests and posts a receipt on the parent feature issue. The
provider-enabled inquiry and legacy-bridge-retirement receipts were withdrawn by the 2026-07-30 owner
cost ruling and are not acceptance gates. Phase 1 acceptance is repo-verifiable: the delivered
mechanism and failure contracts plus MAS-06's removal of the Product authority leak, zero-exemption
import boundary, and fail-closed zero-edge behavior while metered credentials are absent.
Post-acceptance owner-doc promotion updates `docs/LLM.md` and the already-named local capability
owner docs; it does not touch `docs/SECURITY.md`, whose promotion remains owned by #3843.

## Backlog reconciliation (2026-07-27)

Reconciled against live GitHub before this directory was authored. Findings that change the
decomposition:

- **#3843 `feature: local Keychain secret provisioning` — open, `agent:blocked`.** Both its children are
  **delivered**: HSP-01 is #3845 / PR #3888, and **HSP-02 is #3846 / PR #4008, closed 2026-07-20**.
  #3843 remains open only for two acceptance gates — a redacted dev-channel deploy receipt and the
  `docs/SECURITY.md` owner-doc promotion. The dated audit once described HSP-02 as open; PR #4190
  corrected the live `docs/LOCAL_SECRET_PROVISIONING/README.md` task row. Migration step 2's
  "HSP-02 bootstrap lands" clause is satisfied.
- **Decision: MAS-03 is a sibling extension, not a child of #3843 and not a re-filing of HSP-02.** It
  extends the *same delivered mechanism* with model-provider identifiers and turns the hardcoded
  channel/consumer/secret allowlist into data. It has no prerequisite inside #3843 because both HSP
  children are merged. Filing anything named "HSP-02" would duplicate closed #3846. MAS-03 carries
  only the new model-provider scope writeback; the HSP-02 task-order correction is already delivered.
- **R4-1..R4-4 were never filed as issues** — confirmed by search and by repository grep. MAS-01 **is**
  R4-1: it reuses R4-1's specification and its `Verify:` target
  `tests/settings/test_provider_census.py::test_all_allowlists_match_census` rather than inventing a
  new one. R4-2 (Anthropic chat provider), R4-3 (egress-posture compiler and budget breaker), and R4-4
  (Fable-exclusion probe) stay unfiled and out of scope here; MAS-01 must not absorb them.
- **Defects D1, D2, and D6 from the audit's §11 are already filed** — #4177 with PR #4184 (PLANNING
  reasoning mode), #4178 with PR #4183 (phantom embedding identity), and #4181
  (`Settings.embed_model` defaults to an unservable model). MAS-01 links #4178 and #4181 as the issues
  backing its declared census divergences instead of filing new ones.
- **The CKM MVP backlog is fully delivered** — parent #3138 closed, children #3139-#3148 closed;
  `FabricSemanticAssociator` was built under #3144. Nothing is filed for its replacement, so MAS-06 is
  not a duplicate. #4131 is a downstream consumer; #4169 belongs to a separate delivery capability.
- **No open issue implements ADR-0064 steps 1-5.** PR #4180 ratified the ADR and is merged. Nothing in
  this directory duplicates existing backlog state.

## Resolved design choices

Four choices were made here that the ADR leaves open. Each is recorded so a later reviewer can
re-decide it deliberately rather than discover it.

1. **The neutral kernel has no package path.** ADR-0063 explicitly declines to choose one
   (`:185-186`), ADR-0064 says only that `ModelTurnAdapter` is "promoted to that protocol", and no
   kernel module exists in code today — the five fallback values live only in ADR prose.
   `PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL` chooses top-level **`llm_contract/`**: a new package with no
   existing baggage, importable by both runtimes without dragging a heavy `__init__` behind it.
   Reusing `app/ports/` was rejected because `app/ports/__init__.py` already re-exports a vault adapter
   that imports `app.services` and `app.knowledge`, so importing anything from `app.ports` would make
   `app.builderops` depend on Product execution.
2. **"Repaired" is not defined for the two green-on-absent CI paths.** ADR-0064 requires repair but not
   a mechanism. `EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS` selects the smallest honest Phase 1
   answer: remove both optional checks. A future live-provider CI path needs its own declared
   credential backend and explicit egress/cost contract.
3. **The census equality test cannot pass on day one against a truthful census.** Live sites already
   disagree: `app/components/embeddings/legacy.py :: _SUPPORTED_EMBED_PROVIDERS` accepts `openai` and
   `deepseek` that `app/llm/embeddings.py :: PROVIDER_REGISTRY` has no adapter for, and `gemini` is a
   documented selection value with no registered adapter. `DEFINE_PROVIDER_CENSUS` resolves this with a
   **declared-divergence** mechanism — each divergence carries a name, a date, and a linked issue, and
   an undeclared divergence fails — rather than by correcting the sites, because ADR-0064 states the
   census test blocks *new* drift while existing sites migrate opportunistically.
4. **The provider-free intent and resolver ship in Phase 1.** ADR-0064 §3's seven intent fields,
   capability negotiation, and per-runtime/channel resolution are required for the word
   "substrate" to be truthful. MAS-01 provides the census mapping and capability declarations,
   MAS-04 provides neutral contracts, and MAS-05 proves the Builder production resolver from the
   Model Inquiry call site. Product and Builder policy remain separate.

## Out of scope

Migration step 6 (verification closer census resolution) and step 7 (opportunistic Product migration).
Consolidating the six Product-side LLM abstractions as a program — ADR-0064 explicitly withholds that
authorization. The `ReasoningFacade` name collision (`app/components/reasoning/facade.py` versus
`app/reasoning/facade.py`) and the unimported `app/llm/adapter.py`, which are cleanups and not part of
this capability except where the census test happens to touch them. The brokered-session backend, which
ADR-0064 permits but does not build. R4-2, R4-3, and R4-4. Local credential-free model paths — TTS,
STT, and reranking — which have no provider credential and a different lifecycle. CKM dispatch,
mutation, automatic ranking, or gating authority. Cloud secret managers, key rotation, and cross-host
credential sharing.

## Relationship to GitHub issues

Parent [#4286](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4286) is the live validation hub.
The strict serial children are
[#4287](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4287) MAS-01 →
[#4288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4288) MAS-02 →
[#4289](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4289) MAS-03 →
[#4290](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4290) MAS-04 →
[#4291](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4291) MAS-05 →
[#4292](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4292) MAS-06.
Each merged child posts current-SHA evidence to #4286 before the next child becomes ready.

## Related sources

- `docs/adr/ADR-0064-model-access-substrate.md` — the accepted decision
- `docs/adr/ADR-0063-shared-llm-contract-kernel.md` — contract seam, fallback vocabulary, registry authority
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md` — Builder credential/process separation
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md` — CKM projection-only lock
- `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md` — evidence baseline, migration table §8, interim window §8.1
- `docs/LOCAL_SECRET_PROVISIONING/README.md` — host secret boundary, INV-HSP-1..4
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` — provider census §2, slices §5, egress posture §4
- `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md` — adapter boundary and response contract
- `docs/LLM_ROUTING.md`, `docs/LLM.md` — current Product routing and documented provider set
- `docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work Classification`
