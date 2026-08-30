State: Advisory architecture audit snapshot; no implementation or acceptance closure is authorized by this document
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis subordinate to `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`, live GitHub contracts, BuilderOps contracts, and `verification-and-closure`
Owner: Builder System governance
Temporal class: audit snapshot
Source snapshot: `origin/main` `c7c57300f2ec241778061078e7ad585454f0b880`, read 2026-08-30 UTC; live GitHub Issues #3288 and #5177 read 2026-08-30 UTC
Promotion handoff: none; accepted findings require a BuilderOps PromotionIntent before backlog or authority mutation

# BuilderOps Model Inquiry — permanent Sol and model-selection mechanism audit

## Charter and boundary

This audit answers whether BuilderOps Model Inquiry can accept one configured Sol target
permanently, and where hard-coded provider/model selection remains in the surrounding Builder
execution mechanism. It does not run a provider inquiry, change the current acceptance contract,
create an Issue, or close #3288. The broader routing owner is the open parent epic [#5177](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5177);
[#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288) remains the Model Inquiry validation hub.

The required product decision is interpreted as follows: a deliberately configured single-target
Sol run may be readiness- and promotion-eligible, with truthful loss of cross-target independence;
it must not be mislabeled as `consensus`, and it must not be treated as an operational fallback.

## Current-state map

| Surface | Evidence on `origin/main` | Finding |
|---|---|---|
| Model Inquiry roles | `app/builderops/model_inquiry_adapters.py:40,386-417` | The intent schema requires exactly `fable` and `gpt_codex`; role names are part of the runtime contract. |
| Provider/API resolution | `app/builderops/model_inquiry_adapters.py:435-452`; `app/builderops/model_access_resolver.py:552-649` | Provider/model identity is late-bound from census for the API path, but each role profile still names a concrete target and an independent-review group. |
| Operational subscription path | `app/builderops/model_inquiry_adapters.py:593-620`; `scripts/model_inquiry_subscription_adapter.py:34-71,140-146` | Fable/Anthropic and GPT/Codex/Sol are hard-coded in both adapter construction and the host bridge. |
| Inquiry workflow identity | `scripts/start_model_inquiry.py:38,130-164`; `docs/BUILDEROPS_MODEL_INQUIRY/PRE_TICKET_INQUIRY_RECORDS.md:27` | The workflow is permanently named `fable-gpt-architecture`, so the durable inquiry identity encodes a retired provider topology. |
| Turn prompts and persistence | `app/builderops/model_inquiry_contract.py:21-33`; `app/builderops/model_inquiry.py:1414-1500` | Prompt, draft/review graph, terminal validation, and max-round validation all require the two legacy role names. |
| Consensus classification | `app/builderops/model_inquiry_runner.py:212-250,771-779` | Equal effective targets are classified as `degraded_consensus`; the runner has no explicit deliberate single-target acceptance mode. |
| Promotion gate | `app/builderops/model_inquiry_promotion.py:301-352` | Promotion accepts only a `consensus` terminal and `issue_ready` evidence, therefore permanent single-target Sol cannot currently promote honestly. |
| Declared settings | `docs/settings/models/providers.yaml:112-143`; `tests/settings/test_provider_census.py:119-140` | Builder capability targets are late-bound through census, but Model Inquiry profiles directly encode Anthropic/Fable and OpenAI/Sol and test that exact pair. |
| Broader routing | `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:849-925`; `app/builderops/execution_routing.py:214-234,415-435` | The intended architecture already separates capability tier from provider/model binding; Phase 1 is only a bounded-fast shadow seam. |
| Residual code-level model pin | `app/dispatcher/verification_agent_loop.py:93-108` | A default argument still hard-codes `gpt-5.6-sol`; it should resolve a capability/profile, not a model ID. |
| Agent configuration | `.codex/agents/*.toml`; `config/agents.yaml` | Concrete model IDs exist as operational configuration. They are not all defects, but their ownership and override path must be made explicit under #5177 rather than duplicated in workflow code. |

## Ranked mechanism findings

| Rank | Finding | Disposition |
|---|---|---|
| F1 | Single-target Sol is not a first-class acceptance mode. Same-target execution is forced into degraded consensus and blocked from promotion. | Accepted for a bounded implementation child; preserve `consensus` for distinct effective targets. |
| F2 | Model Inquiry role and workflow vocabulary encodes Fable/GPT/Codex rather than inquiry perspectives. | Accepted; rename the durable contract to neutral perspectives, with a compatibility migration for existing records. |
| F3 | The operational subscription adapter is a second target-selection authority and hard-codes concrete provider/model IDs. | Accepted; resolve one configured target once and pass only the authorized target/role invocation to the bridge. |
| F4 | The census has concrete Model Inquiry target profiles and an independence group, while the intent surface claims provider-free configuration. | Accepted; separate target-selection profile/mode from provider-free inquiry intent and validate the selected profile through the census. |
| F5 | General Builder routing is partly centralized but still has a model-ID default in the verification loop and capability-class mapping in dispatch code. | Accepted by #5177 as mechanism follow-up; do not widen the #3288 implementation slice into a general routing rewrite. |
| F6 | Existing tests assert the retired two-provider pair, so a code-only Sol change would leave the contract and test authority contradictory. | Accepted; update tests, owner docs, receipt schema, and migration semantics together. |

## Research questions and answers

### RQ1 — What does “permanent Sol acceptance” mean without false independence?

It means an explicit configured acceptance profile such as `single_target`, resolved to the
configured `sol` capability, with the actual provider/model recorded in every turn and terminal
receipt. Two complementary perspectives may still run, but they share one effective target and
therefore cannot claim independent consensus. The terminal outcome should be distinct, for example
`single_target_acceptance`; promotion must check that explicit mode rather than infer it from
matching targets.

### RQ2 — Where should provider/model choice live?

The process-map contract already assigns capability-to-provider/model resolution to the model-access
substrate and launcher (`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:862-889`). Inquiry workflow,
role prompts, runner, and promotion should consume a capability/profile decision. The census/host
configuration should bind `sol` to its current concrete provider/model. No durable workflow should
contain `gpt-5.6-sol`, `claude-fable-5`, or provider-specific role branches.

### RQ3 — What must remain separate?

Acceptance mode, perspective role, capability tier, provider/model identity, target independence,
allocation/fallback state, and promotion outcome are separate dimensions. In particular, a same-
target run is not a provider outage fallback, and a Sol target is not evidence of independent
cross-provider review.

### RQ4 — Can this be implemented under existing ownership?

Yes, but not directly from the #5177 epic or the #3288 validation hub. The minimal implementation is
a child that owns the Model Inquiry profile/role/acceptance schema and its receipts, reconciled with
#5177's provider-agnostic routing contract. A separate #5177 follow-up should remove residual model
IDs from verification/dispatch code and make all capability mappings resolve through the shared
route/config seam.

## Invariant kernel

- **MUST MI-01 — New:** every inquiry declares one explicit acceptance mode; single-target mode is
  never inferred from provider failure or equal target fingerprints.
- **MUST MI-02 — New:** provider/model IDs are resolved from the declared capability/profile and
  recorded as effective identity; inquiry workflow and perspective roles contain no concrete model
  IDs or provider branches.
- **MUST MI-03 — Existing, extend:** `consensus` requires distinct effective targets; a deliberate
  single-target terminal uses a separate outcome and records `independence=false`.
- **MUST MI-04 — Existing, extend:** provider/API and subscription adapters use the same resolved
  target contract; the bridge cannot select a second target from a role name.
- **GATE MI-05 — New:** readiness and promotion accept single-target Sol only when the terminal,
  synthesis, readiness, trace, and promotion receipts all bind the same acceptance profile,
  target fingerprint, context hash, and actual provider/model identity.
- **GATE MI-06 — Existing, keep:** independent review, CI, exact-head verification, merge, owner
  writeback, and closure remain unchanged by capability or acceptance mode.
- **DOCTOR MI-07 — New:** static/config reconciliation reports concrete model IDs outside the
  provider/model configuration and flags legacy Fable/GPT workflow vocabulary after migration.

Minimal kernel: MI-01, MI-02, MI-03, MI-04, and MI-05. MI-06 protects delivery authority; MI-07
detects future drift.

## Reconciliation and SBS posture

This audit **conforms to** the Builder System and CES boundary and **extends** the existing model-
access and DDO-adjacent routing seams. It does not reshape the SBS, move Product LLM authority, or
create a second dispatcher, inquiry store, or verification authority. It extends #5177's accepted
owner model: capability policy remains provider-neutral while concrete model IDs remain configuration.

Existing #5177 Phase 0/1 artifacts are reused. No duplicate routing epic or parallel Model Inquiry
parent is proposed. #3288 must receive a contract/readback update only when the bounded child has
actually delivered the new acceptance mode.

## Open authority/dependency

The prior real launcher attempt on the configured host ended with exit `0`, empty stdout, and a
non-empty generic stderr diagnostic; its remote lock and staged question were intentionally retained
under the host-local inquiry skill's ambiguity rule. This audit does not retry it. A fresh Sol run
requires the contract implementation and host reconciliation first; it also requires the expressly
provided configured host/session access, without credentials being pasted into chat.
