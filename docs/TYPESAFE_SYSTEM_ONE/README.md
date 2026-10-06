State: Capability specification linked to parent Issue #5764; TSO-00/#5769 and TSO-01/#5765 are delivered, credential-binding slice #5770 has a repository implementation, and TSO-07/#5801 delivers the isolated MARR-only BWS binding and resolver. TSO-02/#5766, TSO-03/#5767, and TSO-04/#5768 add the bounded Product and Builder integrations; their live-call acceptance remains pending. Direct-agent TSO-06/#5778 is delivered as a separate local development tool. Owner direction on 2026-10-06 selects Bitwarden Secrets Manager for the MARR TypeSafe provider key. The first runtime consumers remain Product canvas intent classification and Builder CKM semantic association.
Doc role: Capability specification
Authority: Defines the target contract for bounded TypeSafe System One judgments in Yggdrasil. MARR owns one runtime provider key; Product and Builder keep separate caller policy, adapters, caller credentials, model profiles, and acceptance.
Owner: Capability subsystem; Product LLM Runtime/MARR, Builder System/CES, and Yggdrasil Platform and Operations are collaborators for the isolated BWS credential boundary.
Temporal class: strategic
Source of truth: this specification, the linked owner documents, implementation, and live Issues/receipts
Last reviewed: 2026-10-06

# TypeSafe System One Judgments

## Purpose

Add a bounded way for Yggdrasil code to ask Jev typed semantic questions and receive `Choice`, `Score`, or `Noul` answers with probabilities and confidence. The capability may replace specific prompt-and-parse calls whose outputs are judgments over bounded choices or rubrics; it does not replace text generation or the LLMs that power Codex and Claude Code.

## Source Classification and Ownership

- Capability owner: Capability subsystem, per `docs/CAPABILITY_CONTRACT_MODEL.md`.
- Product collaborator: Product LLM Runtime and the Model Access Router, which own Product route policy and the Mac-executor boundary.
- Builder collaborator: Builder System / CES and CKM, which own Builder route policy and candidate-evidence writes.
- Integration collaborators: host-secret contracts, the Mac Keychain provisioning owner for the MARR reader token, and the Bitwarden Secrets Manager owner for the isolated provider-key project.
- Codex and Claude Code: their TypeSafe skill remains authoring guidance. TSO-06 adds a separate local one-shot development command; it does not change either coding agent's underlying LLM or grant a runtime credential binding.

## Capability Contract

- **Inputs:** a bounded JSON state and finite named typed questions. Each consumer has a closed field allowlist, per-field byte ceilings, candidate-count limits, and a maximum serialized request size.
- **Outputs:** typed answers keyed to their input questions, including the relevant selection/score/probability/confidence data and provider/model provenance. No free-form rationale is promised by Jev; callers may derive explanatory text only from known inputs and returned values.
- **Authority:** read-only judgment or candidate proposal. A result does not authorize a write, routing change, issue transition, or confirmation.
- **Side effects:** one external inference request to TypeSafe; metered credits may be consumed. No retry after an ambiguous request outcome.
- **Failure behavior:** disabled, missing credential, timeout, invalid response, or low-confidence result maps to an explicit unavailable/unknown result. No silent provider fallback and no action-capable default.
- **Confidence:** probabilities and confidence are signals, not proof of correctness. Each consumer owns an evaluated threshold and its low-confidence behavior.
- **Provenance:** record provider, returned model identity, question IDs, input snapshot hash, request correlation ID, and non-secret usage data. Never record state text, API keys, authorization headers, raw provider errors, or prompts in logs/receipts.
- **Persistence:** the capability itself persists nothing. Existing consumers retain their current authority and persistence contracts.
- **Replacement:** disable the TypeSafe adapter and return to the consumer's explicit prior behavior; do not silently switch provider after a request begins.

## Initial Consumers

These are bounded pilots chosen from existing code that already asks for structured semantic output:

1. **Product canvas intent classification** — replace the current constrained JSON completion with typed choices for intent class and, where applicable, governance-action category. An unavailable or uncertain answer remains `UNKNOWN`; downstream confirmation and write guards remain unchanged.
2. **Builder CKM semantic association** — replace free-form proposal JSON with typed selection over a deterministic, supplied candidate set. New IDs cannot be invented by the judgment. Accepted output remains inferred candidate evidence, retains provenance/confidence floors, and requires the existing explicit confirmation receipt before becoming confirmed.

These pilots do not make TypeSafe the default chat/completion provider. Product and Builder use their own route policy, caller authorization, caller credentials, and owner-controlled model profiles. Both call the bounded MARR System One operation; Builder uses its own adapter without importing Product policy. Only the MARR Mac server resolves the runtime TypeSafe provider key.

## Data and Credential Boundary

- **Product request allowlist:** `intent_text` only, at most 2,000 UTF-8 bytes. Do not include `current_body`, note titles, vault paths, prior conversation, prompts, or other canvas state. Maximum serialized request: 4 KiB.
- **Builder request allowlist:** at most 8 candidate records, each containing an opaque candidate ID, an enumerated artifact kind, and a CKM-curated provenance excerpt of at most 500 UTF-8 bytes; at most 8 capability records, each containing an opaque ID and a name/definition summary capped at 500 UTF-8 bytes total. Exclude raw source refs, repository text, file contents, prompts, full artifact records, and unrelated capabilities. Maximum serialized request: 12 KiB.
- Both adapters reject disallowed fields and requests above their byte limits before dispatch. Tests cover payload allowlists, oversize rejection, and receipt redaction.
- The merged repository resolves `typesafe.api-key` only from one `dev/typesafe.api-key` item in the isolated `marr-dev` BWS project. The only runtime reader is a dedicated read-only `marr-server-dev-reader` account on the existing MARR dev server. That project contains no other secret. The reader is separate from `non-prod-reader`, `prod-reader`, and the admin account; the existing admin writer can read pre-state and write only through the designated controller. Product, Builder, Linux channel VMs, test, prod, Codex, and Claude receive neither the active MARR key nor its reader token.
- The MARR reader token remains a host-local bootstrap credential in macOS Keychain and is available only to the MARR server path. It is not an admin token and is never passed to Product or Builder. TSO-07 must fail closed before dispatch for an unknown or unpinned profile, unavailable reader token, wrong project, or missing provider key; it never falls back to the old Keychain provider-key entry.
- Product and Builder retain separate caller policy, caller credentials, profile ownership, fallback behavior, and receipts. Neither resolves or receives the server-owned provider key.
- The existing Linux topology remains two channel projects and three machine accounts, with `non-prod-reader` shared by ygg-dev and ygg-test. TSO-07 adds exactly one TypeSafe-only project and one read-only MARR account; it must not widen either Linux reader. The resulting three-project/four-account target requires verified Bitwarden entitlement. No subscription or paid-plan change is authorized; if the current entitlement cannot support the isolated pair, keep live setup blocked and request that decision.
- The #5667 sole-admin-writer and credential-restriction qualification remains required before any live BWS permission mutation. Repository implementation and fake-backed tests do not claim live BWS setup or qualification.
- Before any live runtime use, require owner confirmation of rotation after the earlier exposure, a scoped MARR dev host binding, explicit one-call authorization, synthetic input, and a redacted receipt. Runtime routes stay off until the separate Product and Builder acceptance receipts are approved.
- The separate TSO-06/#5778 direct-agent record reports that on 2026-10-04, a `typesafe.api-key` item was readable from the local development host through the shared `non-prod` reader. TSO-06 is outside this Product/Builder acceptance scope. Its legacy item must not be updated with the active MARR key; any removal or permission cleanup remains behind the #5667 writer gate. The isolated `marr-dev` project and its reader token are unavailable to that helper and to Linux readers.
- TSO-06's `jev-direct` command and installed skills are a separate local development tool and do not satisfy either Product or Builder acceptance. No live TSO-06 call is required for this capability. Any caller fallback is permitted only after a definitive pre-send failure; an outcome that may have been sent ends that attempt without retry or fallback.
- TypeSafe's current public materials state input pricing of $42 per billion tokens and free output tokens; costs and credit terms must be checked against the account before live use. The specification does not authorize a plan upgrade.

## Cross-Task Invariants / Interaction Safety

1. The shared typed contract carries question and answer meaning only. Product and Builder retain their own resolver/adapter, caller credentials, owner profiles, policy, and receipts while MARR owns provider transport and the runtime key.
2. Product's uncertainty or service-failure path remains `UNKNOWN`, preserving the existing human-first re-ask/confirmation behavior. TypeSafe cannot authorize APPLY.
3. Builder CKM supplies deterministic candidate IDs; an answer outside that candidate set is rejected. Provider failure, route mismatch, stale source snapshot, or low confidence produces zero new edges and no watermark advancement.
4. A stored credential is not evidence of a configured route. A configured route is not evidence of a successful call. Repository tests use fakes; live provider receipts are separately redacted and dev-scoped.
5. The active MARR TypeSafe provider key is stored only in the isolated `marr-dev` project; runtime resolution is granted only to the dedicated MARR read-only account. The existing admin writer can access the item only through the designated controller. Linux channel readers, Product, Builder, Codex, Claude, `non-prod-reader`, and `prod-reader` cannot access that project. The earlier shared `non-prod` item is legacy and cannot be refreshed with the active MARR key. Missing or unauthorized MARR binding makes the operation unavailable without broadening access or falling back.
6. Codex/Claude skill installation is independent of app runtime configuration. TSO-06's local tool provides one bounded development judgment; it never changes the coding-agent model, returns the raw key, or configures Product, Builder, MARR, VM, or production routes.

## Implementation Tasks

GitHub parent validation hub: [Issue #5764](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5764). This specification is the stable intent; task Issues are the implementation contracts and the parent remains open for end-to-end acceptance.

1. [Publish the capability specification](PUBLISH_CAPABILITY_SPECIFICATION.md) — TSO-00; [Issue #5769](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5769); publish the issue map and owner boundaries.
2. [Define the typed System One contract](DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md) — TSO-01; [Issue #5765](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5765) is the task authority; provider-neutral request/response contract and validators.
3. [Define TypeSafe credential consumer bindings](DEFINE_TYPESAFE_CREDENTIAL_BINDINGS.md) — TSO-05; [Issue #5770](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5770); this delivered slice established the logical MARR-only grant through Keychain; TSO-07 supersedes the provider-key source with isolated BWS.
4. [Use Bitwarden for the MARR TypeSafe provider key](USE_BWS_FOR_TYPESAFE_SERVER_KEY.md) — TSO-07 / [Issue #5801](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5801), delivered as a repository-only binding and resolver. The isolated BWS project and dedicated read-only MARR account remain subject to live qualification gates; the BWS bootstrap token stays in the MARR host Keychain.
5. [Add TypeSafe to the Mac Model Access Router](ADD_TYPESAFE_TO_MAC_EXECUTOR.md) — TSO-02; [Issue #5766](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5766); bounded MARR server operation with separate Product and Builder caller policies.
6. [Use Jev for Product canvas intent classification](MIGRATE_PRODUCT_INTENT_CLASSIFIER.md) — TSO-03; [Issue #5767](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5767); preserve `UNKNOWN`, confirmation, and write-guard behavior.
7. [Use Jev for Builder CKM association](MIGRATE_BUILDER_CKM_ASSOCIATION.md) — TSO-04; [Issue #5768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5768); deterministic candidate selection and Builder-owned caller policy/credentials; the provider key stays on MARR.
8. [Enable direct Jev calls for Codex and Claude](ENABLE_DIRECT_AGENT_JEV_CALLS.md) — TSO-06; [Issue #5778](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5778); separately delivered local development command, outside this Product/Builder acceptance scope.

## Capability Acceptance

- [ ] The typed judgment contract has strict bounded schemas and distinct `Choice`, `Score`, and `Noul` result shapes. Verify: `tests/llm_contract/test_system_one_judgment.py::test_judgment_contract_round_trips_typed_answers`.
- [ ] The MARR Product operation dispatches exactly once to TypeSafe, rejects unsupported route/capability requests before inference, and never logs state or credentials. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_executor_dispatches_one_bounded_system_one_request`.
- [ ] Product intent classification maps unavailable/uncertain answers to `UNKNOWN` and does not bypass confirmation or write guards. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_uncertain_judgment_remains_unknown_without_authorizing_write`.
- [ ] Builder CKM only selects supplied candidates; degraded, stale, or below-floor answers write zero edges. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_unavailable_or_stale_judgment_writes_zero_edges` and `tests/builderops/ckm/test_semantic_typesafe.py::test_choice_is_limited_to_supplied_candidates`.
- [ ] Product dev receipt records provider/model, outcome, confidence bucket, usage, and input size/hash without prompts, state text, answer values, credentials, endpoint, or host identity. Verify: runtime receipt: `typesafe.system_one.product_dev_acceptance.v1`.
- [ ] Builder dev receipt records provider/model, outcome, confidence bucket, usage, and input size/hash without prompts, state text, answer values, credentials, endpoint, or host identity. Verify: runtime receipt: `typesafe.system_one.builder_dev_acceptance.v1`.
- [ ] Product and Builder owner docs report supported behavior only after the corresponding code and live acceptance receipts. Verify: doc writeback at `docs/MODEL_ACCESS_ROUTER/README.md :: Current State and Boundary` and `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does`.
- [ ] The MARR provider key resolves only from the dedicated BWS project through the read-only MARR account; its Keychain-held reader token and returned key stay on the MARR server path, and unknown or missing bindings fail before dispatch. Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_bws_binding_is_marr_only`.
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_typesafe_bws_lookup_uses_isolated_project_and_keychain_reader_token`
  - Verify: `tests/ops/test_host_secret_bootstrap.py::test_typesafe_bws_lookup_fails_closed_before_provider_dispatch`

## Validation and Acceptance Path

The owner selected learning through ordinary use when production is operational on 2026-10-05.
No separate benchmark or judgment-quality evaluation campaign is an adoption prerequisite. Use
existing task receipts for useful answer origin, reviewed rationale, and non-secret usage; do not
retain request state or run shadow comparisons. Ordinary repository checks and the consumer
acceptance/release gates below remain part of their owning workflows.

Each in-scope child proves its named contract with deterministic tests and posts a concise receipt to the parent validation Issue. Live TypeSafe calls are not part of ordinary PR tests. TSO-06 is already delivered as a separate local development tool; its direct-agent smoke is outside this Product/Builder acceptance and is not required for this parent. The parent remains open until the isolated MARR BWS project/account and host binding pass their live qualification gates, both dev callers have separate policy, caller credential, and model-profile proofs, the two consumer pilots satisfy their current owner contracts, and the Product and Builder dev-only receipts pass secret/data redaction checks. Product release and production activation remain under the existing release-channel/operator gates.

### TypeSafe development host acceptance

The Product Mac-executor route and Builder CKM route each remain disabled/unavailable until their own post-merge dev acceptance passes using synthetic data, separate caller credentials, and the provider key resolved only by the MARR server from its isolated BWS project. Host installation, live BWS permission changes, and each single live call require the applicable owner/operator gates. Validate separate receipts: `typesafe.system_one.product_dev_acceptance.v1` and `typesafe.system_one.builder_dev_acceptance.v1`. Each receipt contains only schema version, consumer ID, exact provider/model IDs, question IDs, outcome class, confidence bucket, input byte count, input SHA-256, random correlation ID, and non-secret usage counters. It contains no prompt, state text, answer value, API endpoint, host identity, credential, or raw provider error. One authorized real TypeSafe call through MARR per caller is required; no retries or fallback after a request may have been sent. The receipt is reviewed before enabling the corresponding dev route. No test/prod credential or rollout follows from dev acceptance.

## Out of Scope

- Replacing Codex or Claude Code's coding model, streaming, tool use, or code-generation behavior.
- Generic text completion through Jev, shadow inference, automatic provider fallback, or changing default model routes.
- Product/Builder caller-policy, caller-credential, or model-profile unification.
- Separate direct-agent Jev calls from Codex or Claude; the already-delivered TSO-06 tool is outside this capability's acceptance.
- Sending vault note bodies or broad repository context to TypeSafe.
- Automatic confirmation, mutation, issue lifecycle changes, or direct writes based on Jev output.
- BWS plan upgrades, production credential provisioning, production deployment, or changing a live release channel.
