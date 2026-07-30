State: Filed as validation hub #4286 on 2026-07-29. Children #4287–#4292 formed the strict serial
execution chain and are delivered; MAS-06 was delivered by PR #4419 for issue #4292. GitHub holds
the live acceptance ledger; this file is its repo-governed contract. **Owner ruling 2026-07-30
(cost):** the two live receipts below
(`provider_enabled_noninteractive_inquiry.v1`, legacy-bridge retirement) are withdrawn as acceptance
gates — metered provider API keys are not provisioned and the subscription-backed session remains
the sanctioned operational auth for host-local model inquiry. The delivered CKM path uses the
neutral mechanism, fails closed with zero inferred edges while credentials are absent, and never
reuses the Model Inquiry subscription session
(`docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner cost ruling on the
model-inquiry path`). Parent acceptance is repo-verifiable under the re-scoped criteria below.
Doc role: Parent feature issue contract (live validation hub #4286)
Authority: Owns the capability-level validation-hub contract and the acceptance ledger. Subordinate to
`docs/MODEL_ACCESS_SUBSTRATE/README.md` for task shape and to `docs/adr/ADR-0064-model-access-substrate.md`
for the decision.
Owner: Architecture spine / LLM boundary
Temporal class: active delivery contract
Review cadence: event-driven (filing, each child merge, capability acceptance)
Source of truth: `docs/MODEL_ACCESS_SUBSTRATE/README.md`
Last reviewed: 2026-07-30

# Parent feature issue — Model Access Substrate (steps 1-5)

Live issue: [#4286](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4286),
`feature: model access substrate — Phase 1 declared headless model access`.

Live labels: `type:feature`, `agent:blocked`, `prio:high`. The parent is a validation hub, never a
pickup issue.

---

## Context

`docs/adr/ADR-0064-model-access-substrate.md` was accepted by owner decision on 2026-07-27 and merged as
PR #4180. It rules that credential and session resolution is part of the model abstraction, and that
declared API keys are the default programmatic auth path — subscription CLI sessions become
interactive-only and must not be a dependency of any headless path. Its acceptance authorizes
specification and backlog decomposition, not implementation. The 2026-07-30 owner-cost amendment
suspends that headless-session prohibition only for host-local Model Inquiry; no other Builder
consumer inherits the exception.

`docs/MODEL_ACCESS_SUBSTRATE/README.md` is that decomposition, covering **migration steps 1-5** of
`docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md` §8. Steps 6 and 7 are out of scope.

The triggering evidence is one concrete failure: a model inquiry run over a fresh non-interactive
session ended in `final_state: provider_error`, `adapter_failure_class: command_exit_nonzero`, because a
subscription CLI cannot reach the login keychain of the configured inquiry host without a GUI session.
Read-only mapping established that this is not one provider's bug — nine model-access mechanisms and
twelve credential paths exist across Product, Builder, and host, and three specifications each place
model-provider credentials in another's out-of-scope.

## Scope

The outcome, not one PR: the provider set and metered credential mechanism are defined once, the
sanctioned host-local Model Inquiry subscription exception stays explicit, and CKM stops resolving
Builder inference through Product routing policy. With metered credentials intentionally absent,
CKM fails closed instead of claiming an authenticated inference channel.

Six bounded tasks, specified in `docs/MODEL_ACCESS_SUBSTRATE/`. This issue is their validation hub and
is never picked up directly.

## Source Anchors

- `docs/adr/ADR-0064-model-access-substrate.md :: Decision`
- `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration`
- `docs/adr/ADR-0063-shared-llm-contract-kernel.md :: Fallback is contract data, not discovery behavior`
- `docs/LOCAL_SECRET_PROVISIONING/README.md :: Cross-task invariants`
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md :: 2. Provider-surface census`
- `docs/MODEL_ACCESS_SUBSTRATE/README.md :: Cross-task invariants / interaction safety`

## SBS Impact

- Primary subsystem: Builder System / CES boundary
- Secondary subsystem(s): Product/Runtime LLM provider surfaces (census sites only); shared host secret boundary
- Write class: authority-bearing (credential resolution and cross-runtime contract authority)
- Authority impact: CES gains stewardship of the credential contract's versioning alongside the ADR-0063
  compatibility mappers. Product CAO/EBF ownership, embedding identity, and reconciliation discipline
  are unchanged.

## Constraints

The nine fixed constraints in `docs/MODEL_ACCESS_SUBSTRATE/README.md :: Fixed constraints` and the
verification-stage CKM posture apply to every child. The order did not swap.

## Acceptance Criteria

These are the capability-level criteria. Per-task criteria live in the task specifications.

- [ ] Every provider allowlist in the repository equals its census projection, and a deliberately
      drifted site fails CI naming the site.
      Verify: `tests/settings/test_provider_census.py::test_all_allowlists_match_census`
- [ ] A model-provider credential is declared, channel-scoped, and resolvable through the host secret
      contract, and a missing value fails the consumer closed while naming only the logical identifier.
      Verify: `tests/ops/test_host_secret_contract.py::test_model_provider_identifiers_are_declared_data`
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_model_provider_secret_fails_consumer_closed`
- [ ] The repo-owned `yggdrasil-model-inquiry-provider-api` launcher remains content/lineage
      verified and fail-closed, while the sanctioned `yggdrasil-model-inquiry` host subscription
      launcher is confined to Model Inquiry and is not a CKM fallback.
      Verify: `tests/governance/test_model_inquiry_host_install.py::test_check_rejects_conflicting_command_at_provider_api_name`
- [ ] The production inquiry caller submits provider-free intent and resolves provider/model through
      the Builder runtime/channel census mapping after capability checks.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_production_inquiry_resolves_provider_free_intent_through_builder_census`
- [ ] The two neutral inquiry roles resolve as one independent group to distinct effective targets,
      and a colliding mapping is refused before provider execution.
      Verify: `tests/builderops/test_model_inquiry_runner.py::test_production_inquiry_resolves_distinct_effective_targets_for_role_group`
- [ ] CKM resolves its semantic-association model through a Builder-side adapter, and a Product policy
      fallback cannot execute the Builder task.
      Verify: `tests/builderops/ckm/test_semantic.py::test_product_fallback_cannot_execute_builder_task`
- [ ] No `app.builderops -> app.components.llm` import remains, and the `importlinter` contract passes
      with zero exemptions.
      Verify: `tests/architecture/test_import_boundary.py::test_builder_does_not_import_product_llm_without_exemption`
- [ ] No CI workflow step reports success while its declared model-provider credential is absent.
      Verify: `tests/ops/test_ci_smoke_workflow.py::test_no_workflow_step_is_green_on_absent_provider_secret`
- [ ] Owner docs describe the delivered mechanism rather than the pre-ADR-0064 exclusions.
      Verify: `doc writeback at docs/LLM.md :: Providers (Current)`
      Verify: `doc writeback at docs/LOCAL_SECRET_PROVISIONING/README.md :: Out of scope`
      Verify: `doc writeback at docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md :: 5. Slices`

## Implementation Tasks

Specification directory: `docs/MODEL_ACCESS_SUBSTRATE/`

| Order | Task specification | ID | Prerequisite |
| --- | --- | --- | --- |
| 1 | `DEFINE_PROVIDER_CENSUS.md` | MAS-01 | — |
| 2 | `MAKE_BUILDER_TO_PRODUCT_LLM_DEPENDENCY_VISIBLE.md` | MAS-02 | MAS-01 |
| 3 | `EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md` | MAS-03 | MAS-02 |
| 4 | `PROMOTE_ADAPTER_CONTRACT_TO_NEUTRAL_KERNEL.md` | MAS-04 | MAS-03 |
| 5 | `RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT.md` | MAS-05 | MAS-04 |
| 6 | `REPLACE_CKM_PRODUCT_ROUTING_WITH_BUILDER_ADAPTER.md` | MAS-06 | delivered MAS-05 mechanism + ADR-0064 owner-cost amendment |

The serial chain is delivered through MAS-06 implementation PR #4419 for issue #4292. MAS-06
follows the delivered MAS-05 mechanism, launcher-lineage repairs, owner-cost amendment, and
re-scoped live Issue contract. No live provider receipt or bridge retirement is required.

## Verification Path

Task-level proof surfaces are the named tests in each specification's `Acceptance Criteria`, executed by
its `How to Verify (Pre-Merge)` section. Every child runs the full `not pg` unit lane, because every
child touches a hot path, a credential surface, or an architecture gate. `lint-imports --config
importlinter.ini` is a proof surface for MAS-02, MAS-04, and MAS-06.

## Validation / Acceptance Path

Each merged child posts one short validation receipt here before the next child is picked up.
MAS-06 was delivered by PR #4419 for issue #4292 with exact-head CI, two fresh independent final
reviews, and an explicit merged-child validation receipt. The provider-enabled inquiry and
bridge-retirement receipts are withdrawn by the 2026-07-30 owner cost ruling. Parent acceptance
uses the repo-verifiable child criteria, including MAS-06's Product-import removal and fail-closed
zero-edge behavior. No real provider inquiry is requested, and no receipt may contain a credential
value or a host identifier.

Owner-doc promotion triggers only after every acceptance criterion above is satisfied: one PR updating
`docs/LLM.md` and the capability owner docs named by the child specs. `docs/SECURITY.md` remains owned
by #3843 and is not touched here. Until then owner docs stay stable while evidence accumulates.

On closure, three local surfaces are reconciled together: this file's header and state, the capability
`README.md` state line, and the `README.md` relationship-to-GitHub-issues section.

## Out of Scope

Migration steps 6 and 7. Consolidating the six Product-side LLM abstractions. R4-2, R4-3, and R4-4. The
brokered-session backend. CKM dispatch, mutation, ranking, or gating authority. Closing #3843 or
discharging its two remaining acceptance gates.

## Suggested Validation

- `pytest -q -m "not pg"`
- `pytest -q tests/settings/test_provider_census.py tests/ops/test_host_secret_contract.py tests/ops/test_host_secret_bootstrap.py tests/ops/test_ci_smoke_workflow.py`
- `pytest -q tests/builderops tests/architecture tests/governance/test_model_inquiry_host_install.py`
- `lint-imports --config importlinter.ini`
- `python3 scripts/docs_guard.py && python3 scripts/public_seam_lint.py --mode gate`
- No real provider inquiry, credential provisioning, or subscription-bridge retirement is requested
  under the 2026-07-30 owner-cost ruling.

## Source Docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md`
- `docs/adr/ADR-0064-model-access-substrate.md`, `docs/adr/ADR-0063-shared-llm-contract-kernel.md`, `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`, `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md`, `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md`

## Applies learning (optional)

The decomposition applies the cross-cutting-decomposition rule that a mechanism holding one invariant
across N sites gets its own slice before the consumers arrive — which is why the census and the
credential contract precede every beneficiary, and why the interim import leak is given a gate of its
own rather than a bullet inside another task.
