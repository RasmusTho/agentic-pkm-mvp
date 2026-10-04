State: Capability specification linked to parent Issue #5764; neutral contract slice #5765 is filed and not yet delivered. No TypeSafe runtime support or live provider acceptance is shipped. Owner authorization: user request on 2026-10-04 to use Jev in both Product and Builder paths, with TypeSafe skills available to Codex and Claude Code. The first bounded consumers are Product canvas intent classification and Builder CKM semantic association.
Doc role: Capability specification
Authority: Defines the target contract for bounded TypeSafe System One judgments in Yggdrasil. Product and Builder keep separate policy, adapters, credentials, and acceptance.
Owner: Capability subsystem; Product LLM Runtime/MARR and Builder System/CES are collaborators.
Temporal class: strategic
Source of truth: this specification, the linked owner documents, implementation, and live Issues/receipts
Last reviewed: 2026-10-04

# TypeSafe System One Judgments

## Purpose

Add a bounded way for Yggdrasil code to ask Jev typed semantic questions and receive `Choice`, `Score`, or `Noul` answers with probabilities and confidence. The capability may replace specific prompt-and-parse calls whose outputs are judgments over bounded choices or rubrics; it does not replace text generation or the LLMs that power Codex and Claude Code.

## Source Classification and Ownership

- Capability owner: Capability subsystem, per `docs/CAPABILITY_CONTRACT_MODEL.md`.
- Product collaborator: Product LLM Runtime and the Model Access Router, which own Product route policy and the Mac-executor boundary.
- Builder collaborator: Builder System / CES and CKM, which own Builder route policy and candidate-evidence writes.
- Integration collaborator: host-secret contracts and the relevant Mac Keychain/Linux BWS provisioning owners.
- Codex and Claude Code: their TypeSafe skills are authoring guidance. They do not change either coding agent's underlying LLM, and the skills do not grant direct API access or expose a key.

## Capability Contract

- **Inputs:** a bounded JSON state and a finite map of named typed questions. Callers own input minimization and must not include fields that are unnecessary to the judgment.
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

These pilots do not make TypeSafe the default chat/completion provider. Product and Builder must call through their own route and credential authority. The Product pilot uses the bounded TypeSafe operation on the MARR Mac executor; the Builder pilot uses a Builder-owned adapter and never imports Product policy or calls the Product executor.

## Data and Credential Boundary

- Product state and Builder state are sent to an external TypeSafe API only for an explicitly configured TypeSafe consumer. Callers minimize fields before dispatch; vault note bodies and unrelated user data are excluded from the initial pilot.
- Mac-executor credentials resolve through the existing host-local Keychain contract. Linux Builder credentials resolve through the declared host-secret/BWS contract.
- Do not grant Product and Builder the same resolver, identity, fallback policy, or credential consumer merely because both use Jev.
- The existing non-prod BWS project is readable by both dev and test reader tokens. A TypeSafe key must not be added there until the owner has selected either that cross-read exposure or a separately scoped project/credential arrangement that remains within the approved Bitwarden plan.
- Codex and Claude Code use the installed TypeSafe skill to author integrations. Their general agent processes receive no API key by default; API calls during tests use injected fakes. A deliberate live smoke call is a separate, explicit dev operation.
- TypeSafe's current public materials state input pricing of $42 per billion tokens and free output tokens; costs and credit terms must be checked against the account before live use. The specification does not authorize a plan upgrade.

## Cross-Task Invariants / Interaction Safety

1. The shared typed contract carries question and answer meaning only. Product and Builder each bind it to their own resolver, adapter, credentials, policy, and receipts.
2. Product's uncertainty or service-failure path remains `UNKNOWN`, preserving the existing human-first re-ask/confirmation behavior. TypeSafe cannot authorize APPLY.
3. Builder CKM supplies deterministic candidate IDs; an answer outside that candidate set is rejected. Provider failure, route mismatch, stale source snapshot, or low confidence produces zero new edges and no watermark advancement.
4. A stored credential is not evidence of a configured route. A configured route is not evidence of a successful call. Repository tests use fakes; live provider receipts are separately redacted and dev-scoped.
5. If the shared BWS project cannot provide the required credential boundary under the current plan, Builder TypeSafe remains unavailable rather than broadening access silently.
6. Codex/Claude skill installation is independent of app runtime configuration. An agent's use of the skill never changes the coding-agent model or grants the agent new tool authority.

## Implementation Tasks

GitHub parent validation hub: [Issue #5764](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5764). This specification is the stable intent; task Issues are the implementation contracts and the parent remains open for end-to-end acceptance.

1. [Publish the capability specification](PUBLISH_CAPABILITY_SPECIFICATION.md) — TSO-00; [Issue #5769](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5769); publish the issue map and owner boundaries.
2. [Define the typed System One contract](DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md) — TSO-01; [Issue #5765](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5765); provider-neutral request/response contract and validators.
3. [Add TypeSafe to the Mac Model Access Router](ADD_TYPESAFE_TO_MAC_EXECUTOR.md) — TSO-02; [Issue #5766](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5766); bounded Product-side operation and Keychain credential binding.
4. [Use Jev for Product canvas intent classification](MIGRATE_PRODUCT_INTENT_CLASSIFIER.md) — TSO-03; [Issue #5767](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5767); preserve `UNKNOWN`, confirmation, and write-guard behavior.
5. [Use Jev for Builder CKM association](MIGRATE_BUILDER_CKM_ASSOCIATION.md) — TSO-04; [Issue #5768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5768); deterministic candidate selection, Builder-owned route, and dev BWS credential boundary.

## Capability Acceptance

- [ ] The typed judgment contract has strict bounded schemas and distinct `Choice`, `Score`, and `Noul` result shapes. Verify: `tests/llm_contract/test_system_one_judgment.py::test_judgment_contract_round_trips_typed_answers`.
- [ ] The MARR Product operation dispatches exactly once to TypeSafe, rejects unsupported route/capability requests before inference, and never logs state or credentials. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_executor_dispatches_one_bounded_system_one_request`.
- [ ] Product intent classification maps unavailable/uncertain answers to `UNKNOWN` and does not bypass confirmation or write guards. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_uncertain_judgment_remains_unknown_without_authorizing_write`.
- [ ] Builder CKM only selects supplied candidates; degraded, stale, or below-floor answers write zero edges. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_invalid_or_low_confidence_choice_writes_zero_edges`.
- [ ] Codex and Claude skill setup remains authoring guidance and does not configure either runtime key or replace either coding-agent model. Verify: doc writeback at `docs/TYPESAFE_SYSTEM_ONE/README.md :: Data and Credential Boundary`.
- [ ] A redacted dev-only live receipt records exact provider/model, call outcome, usage, and sanitized input hash without prompts, state text, credentials, endpoint, or host identity. Verify: runtime receipt: `typesafe.system_one.dev_acceptance.v1`.
- [ ] Product and Builder owner docs report supported behavior only after the corresponding code and live acceptance receipts. Verify: doc writeback at `docs/MODEL_ACCESS_ROUTER/README.md :: Current State and Boundary` and `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does`.

## Validation and Acceptance Path

Each child proves its named contract with deterministic tests and posts a concise receipt to the parent validation Issue. Live TypeSafe calls are not part of ordinary PR tests. The parent remains open until the Bitwarden/key scope decision is resolved, both dev consumers have separate route and credential proofs, the two consumer pilots satisfy their current owner contracts, and the dev-only receipt passes secret/data redaction checks. Product release and production activation remain under the existing release-channel/operator gates.

## Out of Scope

- Replacing Codex or Claude Code's coding model, streaming, tool use, or code-generation behavior.
- Generic text completion through Jev, shadow inference, automatic provider fallback, or changing default model routes.
- Product/Builder policy or credential unification.
- Sending vault note bodies or broad repository context to TypeSafe.
- Automatic confirmation, mutation, issue lifecycle changes, or direct writes based on Jev output.
- BWS plan upgrades, production credential provisioning, production deployment, or changing a live release channel.
