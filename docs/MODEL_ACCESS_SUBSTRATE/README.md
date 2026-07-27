State: Specification directory (design + bounded tasks). Authored 2026-07-27 from accepted ADR-0064; no child issue is filed and no implementation is authorized by this directory alone. Decomposes migration steps 1-5 only.
Doc role: Capability specification (feature-breakdown lane)
Authority: Owns the task decomposition, execution order, cross-task invariants, and acceptance path for the model access substrate. Subordinate to `docs/adr/ADR-0064-model-access-substrate.md` (the decision), `docs/adr/ADR-0063-shared-llm-contract-kernel.md` (contract seam and fallback vocabulary), ADR-0062 (Builder credential/process separation), `docs/LOCAL_SECRET_PROVISIONING/README.md` (host secret boundary and INV-HSP-1..4), and `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` (provider census and egress posture). Owner docs win on disagreement.
Owner: Architecture spine / LLM boundary
Temporal class: strategic
Review cadence: event-driven (task merge, ADR amendment, or a change in the CKM orchestration question)
Source of truth: this directory for task shape and acceptance; ADR-0064 for the decision; `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md` for the evidence baseline
Last reviewed: 2026-07-27

# Model Access Substrate

## Outcome

Model-provider **credential and session resolution becomes part of the model abstraction** rather than
infrastructure around it, and **declared API keys become the default programmatic auth path**. When
this capability is accepted, a headless caller — model inquiry, CKM, CI, a scheduled job — obtains an
authenticated model channel through one contract, without a human at a GUI login, without a
per-provider hand-built bridge, and without any code naming a provider.

Three mechanisms already exist unfinished, and this capability finishes them rather than designing a
fourth:

- the **provider census** is fully specified as R4-1 and zero percent delivered;
- the **credential contract** is delivered (HSP-01 #3845 / PR #3888, HSP-02 #3846 / PR #4008) for one
  non-model secret and explicitly excludes model providers;
- the **adapter protocol** `ModelTurnAdapter` is implemented and proven against two structurally
  different transports, inside a BuilderOps-only module.

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

## Interim CKM conditions (ADR-0064 §8, audit §8.1)

Through this migration window CKM continues to route Builder inference through Product policy — the
authority leakage ADR-0063 rejected Option A to prevent. ADR-0064 accepts that risk on **two
conditions, both of which must hold**:

1. **CKM does not orchestrate during the window.** ADR-0057 locks CKM projection-only, with inference
   entering as `candidate` and requiring explicit human confirmation. Whether CKM may orchestrate at
   all is not decided by ADR-0064 and needs its own ADR-0057 amendment.
2. **The leak is visible.** `MAKE_BUILDER_TO_PRODUCT_LLM_DEPENDENCY_VISIBLE` converts the invisible
   `app.builderops -> app.components.llm` import into a failing `importlinter` contract with a single
   named, dated exemption. `REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER` removes the exemption.

**If condition 1 cannot hold, the order swaps**: CKM's migration precedes model inquiry. This is
expressible without editing any task specification, because
`RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT` and
`REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER` declare each other in `can_parallelize_with` and
share an identical prerequisite set. The stated order is a sequencing *preference* — model inquiry is
the smaller, already-adapter-shaped consumer that proves the substrate cheaply — not a dependency.

**Live trip-wire.** Open issue [#4169](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4169)
("ckm: connect governed delivery initiation and receipt projection") and open issue
[#4131](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4131) ("Add CKM design-agent integration
hub") are the nearest live work to condition 1. If either begins to initiate delivery rather than
project it, the swap trigger has fired and
`REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER` is promoted ahead of
`RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT`.

## Task order

| Order | Task | ID | Prerequisite | Outcome |
| --- | --- | --- | --- | --- |
| 1 | [Define provider census](DEFINE_PROVIDER_CENSUS.md) | MAS-01 | — | `docs/settings/models/providers.yaml` is the single provider set; a static test asserts every allowlist equals its census projection and names the drifted site. Delivers R4-1. |
| 2 | [Make builder-to-product LLM dependency visible](MAKE_BUILDER_TO_PRODUCT_LLM_DEPENDENCY_VISIBLE.md) | MAS-02 | — | `importlinter` fails on `app.builderops -> app.components.llm` with exactly one named, dated exemption for `app/builderops/ckm/semantic.py`. Converts an invisible violation into a countdown. |
| 3 | [Extend credential contract to model providers](EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md) | MAS-03 | — | Model-provider identifiers join `config/secrets/host_secret_contract.json`; the hardcoded channel/consumer/secret allowlist becomes data; the two green-on-absent CI paths stop reporting success. |
| 4 | [Promote adapter contract to neutral kernel](PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL.md) | MAS-04 | — | `ModelTurnAdapter`, the closed failure vocabulary plus `credential_unavailable`/`session_expired`, the five fallback requirement values, and schema-reference validation live in a neutral package both runtimes may import. |
| 5 | [Resolve model inquiry credentials through contract](RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT.md) | MAS-05 | MAS-03, MAS-04 | First beneficiary. A model inquiry completes over a fresh non-interactive session on the configured inquiry host; no headless path depends on an interactive subscription session. |
| 6 | [Replace CKM product routing with builder adapter](REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER.md) | MAS-06 | MAS-03, MAS-04 | `FabricSemanticAssociator` is replaced by a Builder-side adapter; Product fallback cannot execute the Builder task; the MAS-02 exemption is removed. |

Flat order: **MAS-01 → MAS-02 → MAS-03 → MAS-04 → MAS-05 → MAS-06.**

Parallelism: MAS-01, MAS-02, MAS-03, and MAS-04 are mutually independent and may run concurrently in
isolated worktrees. MAS-05 and MAS-06 are mutually independent once their shared prerequisites land;
their listed order is the preference, and the swap trigger is above.

```
MAS-01 ─┐
MAS-02 ─┤
MAS-03 ─┼──┬── MAS-05  (default first)
MAS-04 ─┘  └── MAS-06  (swaps ahead of MAS-05 if CKM orchestration starts)
```

**Merge-order note (not a dependency):** MAS-02 and MAS-04 both edit `importlinter.ini` — MAS-02 adds a
contract, MAS-04 adds the new neutral package to `source_modules`. Whichever merges second rebases onto
the other rather than resolving by overwrite.

## Cross-task invariants / interaction safety

These hold *across* task boundaries. Each task names the ones it must preserve.

- **INV-MAS-1 — one provider set.** Every provider allowlist in the repository equals its declared
  census projection. Where a site legitimately diverges today, the divergence is a **declared, dated,
  issue-linked** census entry — never a silent difference and never a relaxed assertion. Adding a
  provider is a census row plus a secret declaration; it is never a new bridge.
- **INV-MAS-2 — credentials resolve only through the contract.** Every model-provider credential
  consumer — host launcher, model inquiry, CKM, CI — obtains its value through
  `app/ops/host_secret_contract.py` and `app/ops/host_secret_bootstrap.py`. INV-HSP-1..4 are inherited
  unchanged. No consumer reads a provider key from ambient process environment as its primary path.
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
- **INV-MAS-7 — the interim leak is visible, single, and time-boxed.** At most one
  `app.builderops -> app.components.llm` exemption exists at any time; it carries a name and a date;
  it is removed by MAS-06. A second exemption may not be added, and the contract may not be widened to
  make an import pass.

### Partial-failure paths between tasks

Each task is locally correct and can still lose truth in the seam. These are the seams and their
invariants.

- **Seam A — declaration lands before the value exists (MAS-03 → MAS-05/MAS-06).** MAS-03 may declare
  `openai.api-key` / `anthropic.api-key` for a Builder consumer before any host holds the value. The
  hazard is a consumer that finds no Keychain value and quietly reverts to the old subscription-session
  path, restoring exactly the failure this capability exists to remove. **Invariant:** a declared
  identifier whose value is absent or malformed fails the consuming process **closed** at startup,
  names only the logical identifier, and never falls back to ambient environment or to an interactive
  session. Verified inside each consuming task, not only in the contract task.
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
- **Seam D — the swap happens while CKM is still on Product routing (MAS-06 before MAS-05).** If the
  order swaps because orchestration is starting, condition 1 must still hold until MAS-06 actually
  merges. **Invariant:** while any `app.builderops -> app.components.llm` exemption exists, no CKM code
  path initiates delivery, dispatch, or any write outside a projection; ADR-0057's projection-only lock
  is the governing statement and remains unamended.
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
- [ ] No headless entrypoint depends on an interactive subscription CLI session.
      Verify: `tests/governance/test_model_inquiry_host_install.py::test_headless_entrypoints_do_not_require_subscription_session`
- [ ] A model inquiry completes over a fresh non-interactive session on the configured inquiry host,
      with a provider-returned request id in the persisted turn receipt.
      Verify: redacted operator receipt posted to the parent feature issue, compared against the
      `final_state: provider_error` / `adapter_failure_class: command_exit_nonzero` failure recorded in
      `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: Context`
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

Each child PR proves its named tests and posts a receipt on the parent feature issue. Two pieces of
evidence cannot live in a test and belong on the parent as redacted operator receipts:

1. a model inquiry completing over a fresh non-interactive session on the configured inquiry host
   (the reported failure, fixed as a consequence rather than patched); and
2. retirement of the hand-built per-provider TLS bridge and its version-pinned CLI symlink dependency
   on that host, which is host state and not repository state.

Acceptance is those two receipts plus the capability criteria above. Owner-doc promotion is a single
PR that updates `docs/SECURITY.md` and `docs/LLM.md` to describe the delivered mechanism without values
or host identifiers; it opens only after acceptance, not per task.

## Backlog reconciliation (2026-07-27)

Reconciled against live GitHub before this directory was authored. Findings that change the
decomposition:

- **#3843 `feature: local Keychain secret provisioning` — open, `agent:blocked`.** Both its children are
  **delivered**: HSP-01 is #3845 / PR #3888, and **HSP-02 is #3846 / PR #4008, closed 2026-07-20**.
  #3843 remains open only for two acceptance gates — a redacted dev-channel deploy receipt and the
  `docs/SECURITY.md` owner-doc promotion. **`docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md:72` and
  `docs/LOCAL_SECRET_PROVISIONING/README.md :: Task order` both still describe HSP-02 as open; they are
  stale relative to GitHub.** Migration step 2's "HSP-02 bootstrap lands" clause is therefore already
  satisfied.
- **Decision: MAS-03 is a sibling extension, not a child of #3843 and not a re-filing of HSP-02.** It
  extends the *same delivered mechanism* with model-provider identifiers and turns the hardcoded
  channel/consumer/secret allowlist into data. It has no prerequisite inside #3843 because both HSP
  children are merged. Filing anything named "HSP-02" would duplicate closed #3846. MAS-03 carries the
  `docs/LOCAL_SECRET_PROVISIONING/README.md` writeback that corrects the stale task-order row and
  removes the now-superseded "runtime model-provider enablement" exclusion at `:105`.
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
  not a duplicate. Open CKM issues #4131 and #4169 are the condition-1 trip-wire described above.
- **No open issue implements ADR-0064 steps 1-5.** PR #4180 ratified the ADR and is merged. Nothing in
  this directory duplicates existing backlog state.

## Where ADR-0064 under-determines the design

Four choices were made here that the ADR leaves open. Each is recorded so a later reviewer can
re-decide it deliberately rather than discover it.

1. **The neutral kernel has no package path.** ADR-0063 explicitly declines to choose one
   (`:185-186`), ADR-0064 says only that `ModelTurnAdapter` is "promoted to that protocol", and no
   kernel module exists in code today — the five fallback values live only in ADR prose.
   `PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL` chooses **`app/llm_contract/`**: a new package with no
   existing baggage, importable by both runtimes without dragging a heavy `__init__` behind it.
   Reusing `app/ports/` was rejected because `app/ports/__init__.py` already re-exports a vault adapter
   that imports `app.services` and `app.knowledge`, so importing anything from `app.ports` would make
   `app.builderops` depend on Product execution.
2. **"Repaired" is not defined for the two green-on-absent CI paths.** ADR-0064 requires repair but not
   a mechanism. `EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS` rules that each path is either made
   fail-closed on an absent declared credential, or removed — **never left green on absent** — and that
   the choice is recorded per workflow with its reason.
3. **The census equality test cannot pass on day one against a truthful census.** Live sites already
   disagree: `app/components/embeddings/legacy.py :: _SUPPORTED_EMBED_PROVIDERS` accepts `openai` and
   `deepseek` that `app/llm/embeddings.py :: PROVIDER_REGISTRY` has no adapter for, and `gemini` is a
   documented selection value with no registered adapter. `DEFINE_PROVIDER_CENSUS` resolves this with a
   **declared-divergence** mechanism — each divergence carries a name, a date, and a linked issue, and
   an undeclared divergence fails — rather than by correcting the sites, because ADR-0064 states the
   census test blocks *new* drift while existing sites migrate opportunistically.
4. **Steps 1-5 never deliver the provider-free intent shape.** ADR-0064 §3 and audit §4 specify
   `capability_tier`, `reasoning_effort`, `determinism_required`, `output_schema_ref`, `independence`,
   `fallback_requirement`, and `side_effect_class` as the caller-facing intent, but no migration step
   delivers it, and the tier vocabularies (`Haiku|Sonnet|Opus`, `luna|terra|sol`,
   `economy|standard|frontier`) remain unmapped. This capability therefore delivers the *substrate*
   without the neutral intent; callers still name their adapter. That is a real gap between the ADR's
   §3 and its §8, and it is named here rather than silently absorbed. Closing it needs its own
   breakdown after step 6.

## Out of scope

Migration step 6 (verification closer census resolution) and step 7 (opportunistic Product migration).
Consolidating the six Product-side LLM abstractions as a program — ADR-0064 explicitly withholds that
authorization. The `ReasoningFacade` name collision (`app/components/reasoning/facade.py` versus
`app/reasoning/facade.py`) and the unimported `app/llm/adapter.py`, which are cleanups and not part of
this capability except where the census test happens to touch them. The brokered-session backend, which
ADR-0064 permits but does not build. R4-2, R4-3, and R4-4. Local credential-free model paths — TTS,
STT, and reranking — which have no provider credential and a different lifecycle. Whether CKM may
orchestrate at all, which requires an ADR-0057 amendment. Cloud secret managers, key rotation, and
cross-host credential sharing.

## Relationship to GitHub issues

No issue is filed for this capability. This directory is authored specification held behind a review
gate; [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) is a pre-filing draft, not a live hub. When
issues are created, each child references its task specification as
`Implements MODEL_ACCESS_SUBSTRATE/{TASK_FILE}`, and the parent becomes the validation hub carrying the
capability acceptance criteria above.

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
