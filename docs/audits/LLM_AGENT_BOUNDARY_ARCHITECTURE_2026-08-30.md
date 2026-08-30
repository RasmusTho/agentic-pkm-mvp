State: Advisory architecture-research snapshot, 2026-08-30. Evidence baseline: immutable `origin/main` at `3625c3276b71e7396cca39f7a2732ddd603a9b55`, retrieved at `2026-08-30T11:35:43Z`. No implementation, backlog Issue, credential, provider, or host mutation was performed.
Doc role: Reference (architecture audit snapshot)
Authority: Evidence-based architectural analysis only. Current Product behavior remains owned by `docs/LLM_ROUTING.md`, `docs/LLM.md`, `docs/ARCHITECTURE.md`, and code. Builder delivery authority remains owned by the Builder System process map, DDO contracts, dispatcher/verification contracts, GitHub, CI, and exact-head evidence. Accepted ADRs and owner decisions supersede this audit on disagreement.
Owner: CES / Product LLM / Builder System boundary
Temporal class: Point-in-time audit; refresh from a new immutable `origin/main` snapshot before treating implementation or lifecycle observations as current.

# LLM and agent invocation boundary architecture — 2026-08-30

## 1. Charter and method

This audit answers the bounded architecture question:

> How can all LLM and agent invocations be presented through one testable, provider/model-neutral
> boundary while Product and Builder retain separate policy, authority, credential, lifecycle, and
> receipt semantics?

The target posture keeps Codex as the only active Builder worker carrier. It does not assume or
activate another provider family. Existing compatibility and historical surfaces are inventoried so
they cannot be mistaken for active policy.

The pass used the following method:

- pinned and rechecked one exact `origin/main` SHA before synthesis;
- read the SBS operating model, target SBS, boundary register, Builder process map, Product routing
  docs, ADR-0063, ADR-0064, Model Inquiry/CKM/DDO owner docs, dispatcher/A2A docs, and relevant
  skills;
- inventoried actual call sites, transport seams, subprocess launchers, graph entrypoints, and
  test seams with file-and-line anchors;
- reconciled against live open Issues without creating or changing one; and
- classified each finding as accepted, deferred, or requiring an owner decision.

The current-source refresh and default-ref recheck were performed at `2026-08-30T11:35:43Z` and
returned `origin/main` SHA `3625c3276b71e7396cca39f7a2732ddd603a9b55`. The local audit branch was
rebased onto that SHA before this refresh; the audit-only commits do not claim to change the source
snapshot.

No bounded explorer briefs were dispatched. The work was coordinator-only: the source set was
already named, the repository is large but the independent explorer context would duplicate the
same owner-doc and exact-SHA loads, and the expected human-time saving did not exceed the TCD cost
of fan-out.

```yaml
tcd_plan:
  task_summary: "Map every effective LLM/agent invocation seam and define a provider-neutral boundary without changing runtime behavior."
  assumptions: "Codex remains the active Builder carrier; Product and Builder keep separate policy and authority; the audit is docs-only."
  complexity: very_high
  risk: high
  verification_difficulty: hard
  human_review_burden: high
  defect_blast_radius: high
  budget_pressure: medium
  execution_context: coordinator_only
  issue_local_helper_budget: 0
  context_cost:
    measurement: estimated
    input_tokens: unknown(not separately measured)
    agent_starts: 1
    context_pack_bytes: unknown(not separately measured)
    compactions: unknown(not separately measured)
  recommended_capability:
    workflow_or_skill: architecture-research
    model_family: configuration-resolved Codex capability
    reasoning_effort: high
    tools: git exact-SHA inspection, GitHub REST reads, repository search
    github_context_required: true
  cheapest_acceptable_path: Coordinator-only evidence synthesis from one pinned main snapshot; no explorer fan-out.
  escalation_triggers: Contradictory owner contracts, a source snapshot change, or an authority boundary that cannot be reconciled from existing records.
  deescalation_triggers: A bounded docs-only update with one owner surface and locally verifiable citations.
  review_gate: Docs ownership and current-state claim review, followed by docs guard and focused architecture/governance tests.
```

## 2. Research questions

RQ1. What are the actual Product, Builder, evaluation, orchestration, graph, script, and skill
invocation entrypoints, and which are transport calls versus agent/workflow calls?

RQ2. Which fields are neutral intent, resolved capability, provider/session provenance, authority,
policy, fallback decision, result, and durable receipt?

RQ3. Where do direct provider transports, prompt-only structured parsing, model selection, fallback,
credential acquisition, and lifecycle recovery duplicate or cross boundaries?

RQ4. Can the existing `llm_contract`, Model Access Substrate, and DDO Worker contracts compose one
boundary without making Product routing or Builder delivery a shared policy engine?

RQ5. What must be enforced at runtime (`MUST`), publication/CI (`GATE`), and read-only reconciliation
(`DOCTOR`) to keep provenance from becoming authority?

RQ6. How can the migration preserve current behavior, exact-head delivery evidence, Model Inquiry
lineage, Worker start-once identity, and security restrictions while concrete targets remain
configuration facts?

RQ7. Which apparent “all calls” are explicitly outside the model-turn substrate, especially
embeddings, reranking, tools, and non-model agent orchestration?

### 2.1 Evidence-backed resolutions

**RQ1 — resolved.** The effective entrypoints are not one function: Product fabric/constrained/
reasoning/planner/QA/reflection/domain callers, embedding/rerank/eval consumers, A2A and graph
execution, Builder Model Inquiry/CKM/design adapters, DDO workers, and the verification closer are
distinct surfaces. The inventory in §4 records their transport and authority owners. The direct
Product reflection exit and the Builder verification subprocess are the clearest duplicated seams
(`app/chat/reflection_conversation.py:271-285`; `app/dispatcher/verification_consumer.py:2697-2763`).

**RQ2 — resolved.** Intent is provider-free capability demand. Resolution is a runtime-owned choice
of adapter, target, capabilities, and logical credential/session identity. Provider/model/session/
thread/process values are provenance. Domain result and durable receipt are owner-specific. DDO makes
the distinction executable by binding run/plan/effect/Issue/head in the Worker authority chain and
placing carrier identity in an explicitly non-authoritative envelope
(`app/builderops/delivery_orchestration_contracts.py:3217-3389,3617-3665`).

**RQ3 — resolved.** Duplication is present in Product direct HTTP, reflection, prompt-only structured
parsing, planner fallback, embedding fallback, Model Inquiry role launch, verification adapter
validation, and role configuration. The high-risk crossings are fallback selection inside callers,
concrete target selection outside a census, and any use of carrier identity as delivery state
(`app/services/llm.py:78-312`; `app/components/reasoning/facade.py:272-385`; `scripts/model_inquiry_subscription_adapter.py:34-71`).

**RQ4 — resolved.** Yes, but only as a neutral kernel plus separate Product/Builder resolvers and
adapters. `llm_contract` is already a leaf contract surface; ADR-0063 and ADR-0064 explicitly reject
sharing policy, registries, credentials, sessions, fallback decisions, stores, or health receipts
(`llm_contract/__init__.py:1-205`; `docs/adr/ADR-0063-shared-llm-contract-kernel.md:70-100`; `docs/adr/ADR-0064-model-access-substrate.md:60-78`).

**RQ5 — resolved.** Runtime MUSTs protect request/result truth and secrets; GATEs protect census,
adapter, mapper, and Worker-contract conformance; DOCTORs reconcile direct calls, stale references,
attempt receipts, and provenance/authority misuse. The §7 table records which are already local,
violated in current paths, or new; it does not claim the proposed kernel is shipped.

**RQ6 — resolved.** The least-risk path is additive: freeze the census, adapt one Product exit at a
time, preserve domain-specific fallback/results, keep Builder resolver/receipt authority separate,
then add the Worker mapper and migrate eval/scripts last. Resume must remain bound to semantic input
hash and current authority readback; a repair attempt gets a new authorized identity. Existing Model
Inquiry and DDO contracts provide the strongest compatibility precedents
(`app/builderops/model_inquiry_runner.py:797-850`; `app/builderops/delivery_orchestration_contracts.py:3304-3358`).

**RQ7 — resolved.** Embeddings remain Product identity/reconciliation work; reranking remains outside
the model-access substrate; A2A, graph, tool, and DDO calls are agent/workflow contracts, not model
turns. They may consume the model boundary through an explicit mapper but must retain their own
authority, effects, receipts, and retry semantics (`app/llm/fallback_orchestrator.py:50-110`; `app/retrieval/rerank/provider.py:52-203`; `docs/ORCHESTRATOR_A2A_ROUTING/README.md:24-46`).

## 3. Authority and SBS reconciliation

The SBS operating model keeps Product/Runtime, Builder System, and Yggdrasil Platform/Operations as
distinct systems. Product CAO/EBF owns cognitive capability and external model boundaries; Builder
owns development-time execution, adapters, receipts, and delivery control. The target SBS names EBF
for providers/adapters, CAO for agents/orchestration, GOV for authority/receipts, EXE for authorized
effects, OEF for observation, and CES for contract/version stewardship.

This audit therefore:

- **conforms** to the existing Product/Builder split and to the DDO rule that a worker carrier is
  provenance, never delivery authority (`docs/architecture/SBS_OPERATING_MODEL.md:366-370`; `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:613-621`);
- **extends** CES with a cross-runtime, versioned compatibility vocabulary and mapper discipline,
  as already selected by ADR-0063 and ADR-0064;
- **does not reshape** the Product SBS into a global model service, and does not make the neutral
  kernel a runtime subsystem or store; and
- **does not authorize** a physical package split, service, provider activation, new Issue, or
  replacement of dispatcher/DDO/verification authority.

The core architectural guardrail is the SBS provider-leak failure mode: provider model names,
embedding fields, vendor taxonomies, or session state must not become HKA/SIP/GOV meaning or
authority (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1871-1884`). Agent runtime likewise cannot own policy,
retrieval truth, memory promotion, or tool side effects (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1886-1899`).

## 4. Current invocation inventory

The table distinguishes an invocation *entrypoint* from the lower-level transport it eventually
uses. “Receipt” means a durable or contract-shaped evidence object, not merely a log line.

| Surface / entrypoint | Current path and authority | Provenance / receipt | Fallback, error, resume, security semantics |
| --- | --- | --- | --- |
| Product chat fabric | `get_chat_client` resolves Product `LLMTaskIntent` to `LLMRoute`, then `ChatClient.chat` calls the legacy service (`app/components/llm/fabric.py:11-52`; `app/services/llm.py:315-495`). Product settings/router policy is authoritative for Product routing. | Route carries provider/model/mode/reason/degraded; `log_llm_call` is trace telemetry, not a delivery receipt (`app/components/llm/fabric.py:11-38`; `app/services/llm.py:484-495`). | Product precedence and task fallback are defined in `docs/LLM_ROUTING.md:36-67`. Transport branches remain direct provider HTTP in `app/services/llm.py:78-312`; unsupported/empty responses fail loud, while mock is an explicit Product mode. No cross-runtime resume identity is present. |
| Product constrained completion | `constrained_completion` validates a registered local schema, calls an injected/default Product client, parses and validates the response (`app/components/llm/constrained.py:60-177`). | Schema ref and typed `ConstrainedCompletionError`; no universal provider request/attempt receipt. Injection is a strong test seam. | Empty, non-JSON, schema-invalid, and provider failures are rejected. Callers choose semantics: unknown classification, extraction failure, no-link/contradiction, or attribution failure (`app/components/llm/intent_classifier.py:165`; `app/knowledge_acquisition/extractors/claims_extractor.py:59`; `app/standing_questions/evidence_matching.py:329`; `app/heimdal/attribution_stage.py:306`). |
| Product `ReasoningFacade` | `app/components/reasoning/facade.py` claims one reasoning entrypoint but independently implements chat, prompt-JSON structured output, tool-use prompt conventions, taxonomy, heuristic fallbacks, and a router/client call (`app/components/reasoning/facade.py:231-385,477-544`). Panel, pilot, reviewer, classifier, hygiene, and set-evaluator agents call this facade. | Process-local telemetry contains provider/model/latency/chars; audit logging is best effort and catches errors (`app/components/reasoning/facade.py:143-164,568-628`). No durable model-turn receipt. | Structured/tool-use paths parse JSON but do not share the strict constrained validator. Classification/planning/decision handlers can return heuristic/raw-text fallbacks (`app/components/reasoning/facade.py:477-500`). No common invocation or restart lineage. |
| Product legacy reasoning | `app/reasoning/provider.py` resolves a Product route and calls `ChatClient`, while `app/reasoning/facade.py` provides an injectable provider facade (`app/reasoning/provider.py:80-187`; `app/reasoning/facade.py:135-265`). | `ReasoningRun` carries route and failure state, but not the common model access receipt. | Claims/review/ranking failures become typed failed runs or empty/parse outcomes; mode-specific behavior is separate from the component facade (`app/reasoning/provider.py:233-430`). |
| Planner | `LLMPlanner.plan` uses Product `get_chat_client`, requests a schema, then calls constrained completion; invalid output falls back to `MockPlanner` (`app/planner/provider.py:240-361`). | Planner audit event and result contain plan state; model access remains Product route telemetry. | Explicit planner fallback is a Product policy seam, not neutral substrate behavior. It must remain visible when mapped. |
| QA agent | `_call_llm` gets a Product chat client and returns raw text; deterministic self-check follows (`app/agents/qa/agent.py:39-81`). | QA result carries sources/checks/quality; no model-turn receipt. | Model error is a direct failure; deterministic self-check is not a model fallback. |
| Reflection conversation | `ReflectionConversationService` uses an injected function, but production `_call_reflection_llm` directly calls `app.services.llm.call_llm`, bypassing the documented Product fabric (`app/chat/reflection_conversation.py:115-187,271-285`). | Durable conversation artifact/session writes are governed by the conversation service; the model call itself has only trace/log semantics. | Start failure or empty output creates no session; submit persists owner input before cognition and then persists the agent follow-up. This is a safe artifact ordering, but the transport seam is duplicated. |
| Knowledge, standing-question, and Heimdal callers | Eight bounded callers use the constrained-completion port with injected test completions (for example `app/knowledge_acquisition/extractors/summary_extractor.py:125`; `app/standing_questions/answer_refresh.py:448`). | Domain artifacts/events own their respective authority; schema/ref/error is local. | Each caller has deliberately different fail-closed semantics. A future mapper must preserve those domain outcomes instead of collapsing them into “LLM unavailable.” |
| Product embeddings | `get_embeddings_client` is the fabric entrypoint, while the legacy embedding registry and HTTP adapters remain in `app/llm/embeddings.py:21-23,169-198,350-460`. | Embedding identity, dimension, normalization, and reconcile metadata are Product/DRI authority, not generic chat receipts. | `app/llm/fallback_orchestrator.py:50-110` selects a dimension-compatible fallback and marks mixed identity for reconciliation. This cannot be made a generic text-model fallback. |
| Product reranking | Local deterministic and HTTP reranker paths live under `app/retrieval/rerank/provider.py:52-203`. | Retrieval result and candidate evidence own authority; the HTTP path has no common model-turn receipt. | HTTP failure falls back to a local cross-encoder path. ADR-0064 explicitly keeps reranking outside the model-access substrate. |
| Evaluation model path | Opt-in DeepEval/OpenAI-compatible construction is in `app/eval/llm_client.py:18-71`. | Evaluation configuration and eval artifacts own evidence; no Product route or Builder receipt. | Configuration can skip or fail; evaluation is not runtime capability authorization. It is a separate adapter consumer that should eventually use the same neutral capability vocabulary, not Product delivery policy. |
| A2A `agent_call` | `MockPlanExecutor._execute_agent_call` resolves agent configuration, checks permissions, emits request/response/error events, and calls an in-process handler (`app/orchestrator/executor.py:103-177`; `app/orchestrator/agents.py:17-49`). | A2A request/response/error events carry trace/correlation; orchestrator plan/step events own workflow authority (`docs/ORCHESTRATOR_A2A_ROUTING/README.md:24-46`). | Unsupported target and handler error fail explicitly. No remote transport or long-running SLA is shipped. Agent request is not automatically an LLM request. |
| V1/V2 orchestration runtimes | `runtime.py` admits a plan and executes steps; `v2_runtime.py` schedules dependency-safe parallel work with checkpoints, retries, deadlines, and resume (`app/orchestrator/runtime.py:76-205`; `app/orchestrator/v2_runtime.py:147-223,532-620`). | Plan/step events, checkpoints, and A2A events are orchestration evidence. | Resume is plan/checkpoint/step based; retry and compensation are explicit orchestration policy. Provider/session state cannot advance the plan without a structured handler result. |
| LangGraph agent entrypoints | Ask, panel, pilot, planner, and per-agent graph wrappers call `compiled.invoke(...)` (for example `app/agents/ask/graph.py:595`; `app/agents/panel_agent/graph.py:610`; `app/agents/pilot_agent/graph.py:58`). | Graph state/results are domain workflow evidence. | These are agent invocation entrypoints, not model transports. Their downstream model calls currently split across reasoning, Product fabric, planner, and injected functions. |
| Builder Model Inquiry | CLI/start launcher, `ModelInquiryRunner`, explicit role adapters, and durable inquiry service form an artifact-first execution path (`app/builderops/model_inquiry_runner.py:54-190`; `scripts/start_model_inquiry.py:103-210`). | Question, context, request hashes, turn artifacts, provider attempt receipts, terminal/readiness/synthesis/promotion receipts are durable and lineage-bound (`app/builderops/model_inquiry_runner.py:570-688`). | Adapter failures are typed and sanitized; accepted turns persist before successors; terminal runs replay; current/legacy request lineage is checked (`app/builderops/model_inquiry_runner.py:797-850`). Security includes bounded subprocesses, no shell, minimal env, output caps, process-tree cleanup, and credential-value redaction (`app/builderops/model_inquiry_adapters.py:153-341`). |
| Builder Model Inquiry host launcher | The subscription bridge constructs role-specific external commands in `scripts/model_inquiry_subscription_adapter.py:38-71`. | Session/role/adapter identity is provenance; the runner owns durable inquiry authority. | Timeout and expired-session exit codes are distinct; malformed/empty output fails. The current source still contains role-specific concrete target literals at `scripts/model_inquiry_subscription_adapter.py:34-35`, and a non-Codex compatibility role. This is an observed current-vs-request divergence, not an authorization to run or modify that route. |
| Builder CKM semantic association | CKM now submits provider-free intent to `BuilderModelAccessResolver`, resolves declared census capability, and constructs `HttpModelAdapter` (`app/builderops/ckm/semantic.py:184-275`). | CKM proposal/evidence edge is projection/candidate evidence; provider/model is retained as provenance. | `fallback_forbidden`, no mock/degraded route, missing credential, invalid response, and adapter failure produce zero edges or typed unavailable outcomes (`app/builderops/ckm/semantic.py:223-337`). CKM has no delivery authority. |
| Builder design-agent registry | Domain design IDs map to provider-free role profiles; resolver selects a target and an already-constructed `ModelTurnAdapter` (`app/builderops/design_agent_adapters.py:99-132,216-330`). | Sanitized availability descriptors and adapter identity are provenance; design-run contracts own the artifact. | Exact selection, no implicit fallback, interactive-only unavailability, identity mismatch, and absent headless adapter are explicit (`app/builderops/design_agent_adapters.py:150-281`). Some domain identifiers remain compatibility/provenance and are not evidence that a route is active. |
| Builder worker dispatch/DDO | `WorkerContextPack` and `WorkerInvocation` bind run/plan/effect/Issue/head/context hash and start-once identity; a carrier executes and returns `WorkerResultV2` (`app/builderops/delivery_orchestration_contracts.py:3217-3389`). | `WorkerCarrierEnvelope` contains opaque carrier/provider/model/session/usage/provenance IDs and is explicitly never delivery authority; `validate_worker_authority_chain` resolves the exact chain (`app/builderops/delivery_orchestration_contracts.py:3364-3389,3617-3665`). | Same invocation cannot start twice; terminal runtime observations bind a result; pause/resume/supersession remain reducer/GOV decisions. Current main explicitly declares the active Builder carrier Codex-only; compatibility/provider fields remain provenance (`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:613-621`). |
| Builder verification closer | `CodexExecLauncher` reads a role adapter, launches a contained `codex exec`, streams strict receipts, heartbeats authority, kills residual process trees, and rejects missing containment/thread/schema identity (`app/dispatcher/verification_consumer.py:2697-2763,2846-2885,3068-3415`). | Verification receipt/thread identity is operational provenance; GitHub PR/CI/review/merge remain delivery authority. | Rate limit, authority loss, execution, containment, missing thread, and invalid receipt are distinct failures. Resume is explicit session/verification recovery, not provider fallback. The launcher currently validates a concrete adapter contract in code (`app/dispatcher/verification_consumer.py:2721-2743`), creating a duplicated selection seam. |
| Skills and agent TOML adapters | Skills route work and TCD; `.codex/agents/*.toml` select execution roles and effort. `deliver-issue-set` and process-map target contract say concrete model IDs belong in configuration/census, not workflow contracts (`.codex/skills/README.md:64-128`; `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:849-875`). | Skill/agent selection is workflow provenance; Issue/branch/PR/CI/review receipts remain authority. | No skill may silently alter lifecycle/verification authority. Existing role config literals are an inventory item for config-time resolution, not a reason to embed IDs in the new kernel. |

### 4.1 Entry-point conclusions

There is not one current invocation seam. There are four layers:

1. **Model-turn transports:** Product HTTP/mock paths, Builder command/HTTP adapters, eval client,
   and the verification closer's external Codex process.
2. **Cognition facades:** Product constrained completion, reasoning, planner, QA, reflection,
   extractors, and agent graphs.
3. **Agent/workflow execution:** A2A handlers, V1/V2 orchestration, LangGraph, DDO workers, and
   verification lifecycle.
4. **Authority and evidence:** Product artifacts/events, BuilderOps inquiry receipts, DDO authority
   chain, GitHub/CI/review/merge, and host containment.

The common boundary must normalize layer 1 without absorbing layers 2–4. It must offer an explicit
bridge into layer 3 while leaving authority and receipts with their owners.

## 5. Duplicated seams and ranked findings

### F1 — High: “single Product fabric” is an owner-doc contract with multiple physical exits

The Product routing contract says fabric is the only high-level entrypoint, but reflection calls the
legacy service directly, Product legacy transports remain physically callable, and reasoning/planner/
QA have separate result/fallback behavior (`docs/LLM_ROUTING.md:7-9`; `app/chat/reflection_conversation.py:271-285`; `app/services/llm.py:315-495`). The import/test guard is not a complete repository-wide transport census.

Disposition: **accepted finding**. Follow-up is a bounded Product migration sequence, not a global
rewrite.

### F2 — High: Product and Builder already have the correct neutral kernel shape, but different policy runtimes

`llm_contract` is a leaf package with immutable contracts, failure vocabulary, capability
requirements, resolution, and adapter protocols (`llm_contract/__init__.py:1-205`). Builder resolver
and Model Inquiry use it without importing Product policy (`app/builderops/model_access_resolver.py:1-182`; `tests/architecture/test_llm_contract_kernel.py:22-149`). Product `LLMTaskIntent`/`LLMRoute` and Builder role/resolution requests remain policy-specific.

Disposition: **accepted direction**, already ratified by ADR-0063 and ADR-0064. Do not create a
second kernel or move Product routing wholesale into Builder.

### F3 — High: authority/provenance can be confused at the Worker-to-model seam

DDO has unusually strong separation: Worker invocation binds the reducer-authorized semantic input,
while carrier/provider/model/session/usage are opaque provenance. A future model boundary must not
let an effective model identity, session, process exit, or thread select Issue scope, advance a
reducer, prove acceptance, or close a PR. `WorkerResultV2` is the correct bridge shape: one authority
chain plus one carrier envelope, with carrier-independent conformance (`app/builderops/delivery_orchestration_contracts.py:3364-3540`).

Disposition: **accepted finding**. Treat the Worker contracts as a consumer/bridge contract, not as
the LLM kernel itself.

### F4 — High: fallback is duplicated policy and must not be implemented by the substrate

Product route candidates, embedding identity fallback, planner mock fallback, Model Inquiry
operational candidate fallback, and design exact-selection failure are different policies. ADR-0063
already defines five fallback requirements; ADR-0064 says the caller declares the requirement, the
owning runtime selects within it, and the substrate never decides (`docs/adr/ADR-0063-shared-llm-contract-kernel.md:102-116`; `docs/adr/ADR-0064-model-access-substrate.md:141-148`).

Disposition: **accepted rule**. New adapters may execute only a resolved candidate; they must not
invent a fallback ladder.

### F5 — Medium: structured output has two incompatible validation seams

`constrained_completion` validates schema before and after the call, while `ReasoningFacade.structured`
and tool-use parse JSON in prompts and leave validation to callers (`app/components/llm/constrained.py:138-177`; `app/components/reasoning/facade.py:272-385`). Model Inquiry has its own strict response parser and durable artifact validation.

Disposition: **accepted finding**. Extract or reuse a neutral validation primitive only after a
contract-first slice; do not weaken any existing domain validator.

### F6 — Medium: concrete provider/model/generation selection is repeated in code and configuration

The current tree contains provider dispatch ladders and model defaults in Product transport/config
(`app/services/llm.py:14-29,44-98,246-247`; `app/llm/adapter.py:14-109`), role/target selection in
the Model Inquiry launcher (`scripts/model_inquiry_subscription_adapter.py:34-71`), and concrete
verification-adapter validation (`app/dispatcher/verification_consumer.py:2721-2743`). Existing
`.codex/agents/*.toml` also carries execution-role model configuration. These are separate kinds of
selection, but they are not one census-backed resolution path.

Disposition: **accepted inventory item**. No new artifact repeats any concrete model ID. The active
Builder carrier policy is explicit in current main and covered by its Codex-only governance test;
Model Inquiry target semantics remain separately governed by open #5203.

### F7 — Medium: “agent invocation” is wider than “model invocation”

A2A `agent_call`, graph `.invoke`, orchestrator step execution, DDO worker launch, and verification
closer may call a model, a deterministic handler, a tool, or another process. Treating every agent
call as an LLM turn would leak tool/effect/policy semantics into the model kernel and obscure where
authority is actually held.

Disposition: **accepted boundary clarification**. Use a model-turn adapter beneath agent/runtime
contracts, and an explicit runtime-owned mapper above it.

### F8 — Medium: active Codex-only policy does not erase historical/compatibility surfaces

Current main explicitly declares the active Builder worker carrier Codex-only and rejects unsupported
runtime targets/hints. Open #5203 separately changes Model Inquiry from its historical two-role
arrangement to a configured single-target mode. The current source still contains the older
role-specific subscription bridge and non-Codex compatibility language, which are not evidence that
another active carrier should be authenticated or invoked.

Disposition: **accepted current-state clarification**, not a new audit Issue. Keep the active policy
and compatibility classification separate; preserve #5203 as the existing Model Inquiry owner route.

## 6. Desired boundary

The target is a small, versioned, provider-neutral model-turn boundary with four explicit stages:

```text
caller-owned intent
        |
        v
runtime-owned policy + capability resolver
        |
        v
resolved access (target, adapter, capabilities, credential/session identity)
        |
        v
adapter execute(request) -> normalized result | typed failure
        |
        +--> runtime mapper -> domain result / receipt
        +--> Worker mapper  -> WorkerResultV2 carrier envelope
```

### 6.1 Kernel contract

The minimal kernel should own only immutable, side-effect-free contracts and validation:

- provider-free capability intent: tier, reasoning/effort, determinism, output schema reference,
  independence, fallback requirement, side-effect class, deadline, and request identity;
- resolved access: provider/model/effective identity, adapter identity, capability attestation,
  runtime/channel/consumer scope, and logical credential reference (never a secret value);
- adapter protocol: bounded request execution returning response text/structured payload, provider
  request identity where available, and normalized typed failure;
- closed failure vocabulary including unavailable, timeout, empty/oversize output, auth/session,
  unexpected adapter failure, and secret-safe diagnostics;
- schema validation and canonical hashing primitives; and
- provenance references sufficient to connect a result to request, adapter, runtime, trace, and
  domain receipt without making those references authority.

The current `llm_contract` package is the closest shipped kernel and already covers most of this
shape (`llm_contract/__init__.py:28-205,248-335`). The proposal is to evolve it contract-first, not
to create a parallel `AgentLLM`, `ProviderGateway`, or global runtime service.

### 6.2 Explicit non-ownership

The kernel must not own Product settings, Builder policy, mutable registries, fallback selection,
prompts, task taxonomy, credentials, sessions, host processes, stores, telemetry retention,
dispatcher leases, DDO reducer transitions, GitHub lifecycle, tool effects, memory promotion,
retrieval truth, or human acceptance. This is the exact separation already selected in ADR-0063
(`docs/adr/ADR-0063-shared-llm-contract-kernel.md:75-100`) and ADR-0064
(`docs/adr/ADR-0064-model-access-substrate.md:60-78`).

### 6.3 Capability-resolution model

Callers submit a provider-free intent. A runtime-scoped resolver performs, in order:

1. authenticate the caller/runtime/consumer scope and validate the intent;
2. load the runtime/channel census and policy-owned role profile;
3. resolve a concrete configured target and adapter;
4. attest required capabilities and target independence where requested;
5. acquire a credential/session through the owning secret contract;
6. execute exactly the resolved adapter; and
7. return a normalized result or typed failure to the owning runtime.

Capability discovery does not authorize fallback, delivery, mutation, or promotion. A Codex-only
active profile is a resolver/census policy fact, not a hardcoded kernel assumption. A future adapter
can implement the same port if a separately governed profile, credential contract, and tests exist.

### 6.4 Mapper rules

Every Product↔kernel, Builder↔kernel, and worker↔kernel mapper must be total per contract version and
fail closed on unknown values. It must preserve intent, selected/effective identity, adapter/runtime
identity, capability attestation, failure class, fallback requirement/decision, degraded state,
deadline, determinism, schema, side-effect class, trace/request identity, and receipt references.

It must never:

- turn provider/session/model provenance into Issue, plan, reducer, merge, closure, or human authority;
- convert capability discovery into authorization;
- weaken `fallback_forbidden` or manufacture a fallback candidate;
- present mock, dry-run, test, or unavailable output as provider execution;
- claim independent review when effective targets are equal; or
- merge Product and Builder health/receipt authorities.

## 7. Invariant kernel

The following is a proposed research kernel, not current universal enforcement. It must extend the
existing invariant registry vocabulary in `docs/testing/invariant-tests.md`; it must not create a
second registry. `MUST` means runtime fail-loud, `GATE` means CI/publication block, and `DOCTOR` means
read-only reconciliation.

| ID | Category | Status | Invariant | Current evidence / enforcement gap |
| --- | --- | --- | --- | --- |
| LLM-BOUNDARY-01 | MUST | Exists — keep | Caller intent contains no provider, model, endpoint, credential value, host path, or session handle. | Builder `ModelAccessIntent` and Product `LLMTaskIntent` requests are provider-free (`app/builderops/model_inquiry_adapters.py:355-432`; `llm_contract/__init__.py:70-79`; `app/components/llm/router.py:15-22`). Product/eval settings still expose runtime transport selection (`app/services/llm.py:315-364`; `app/eval/llm_client.py:18-71`), which is inventory for LLM-BOUNDARY-11 rather than a caller-intent violation. |
| LLM-BOUNDARY-02 | MUST | Violated today | Only an adapter executes provider HTTP, provider SDK, or model-process transport; direct call sites fail the boundary review. | Product legacy HTTP and reflection direct call are present (`app/services/llm.py:78-312`; `app/chat/reflection_conversation.py:271-285`). |
| LLM-BOUNDARY-03 | MUST | Violated today | Resolution is immutable and records selected/effective identity, adapter, capabilities, runtime/channel/consumer scope, and degraded state. | Builder `ResolvedModelAccess` records the request, selected/effective identity, adapter, capabilities, credential reference, and degradation (`llm_contract/__init__.py:101-123`), but `runtime`/`channel`/`consumer` are resolver arguments and are not retained in that resolved value (`app/builderops/model_access_resolver.py:125-182`). Product `LLMRoute` remains a separate policy object (`app/components/llm/fabric.py:41-73`); a future mapper must retain needed scope at a handoff. |
| LLM-BOUNDARY-04 | MUST | Violated today | A typed failure or empty/invalid result cannot be normalized as successful cognition. | Strong in constrained completion (`app/components/llm/constrained.py:138-177`) and Model Inquiry (`app/builderops/model_inquiry_runner.py:570-688`); reasoning/planner/QA fallback paths differ (`app/components/reasoning/facade.py:477-500`; `app/planner/provider.py:296-305`). |
| LLM-BOUNDARY-05 | MUST | Exists — keep | Fallback executes only when an owning runtime has declared and selected the allowed fallback requirement; substrate never chooses. | ADR-0063/0064 define this (`docs/adr/ADR-0063-shared-llm-contract-kernel.md:102-116`; `docs/adr/ADR-0064-model-access-substrate.md:141-148`); domain fallbacks remain separate. |
| LLM-BOUNDARY-06 | MUST | Exists — keep | Credential values, raw auth headers, provider error bodies, and secret-bearing environment values never enter prompts, artifacts, logs, or receipts. | Builder redaction/minimal-env tests pass in the inspected suite (`tests/builderops/test_model_inquiry_adapters.py:67-147`); Product transport/logging remains incomplete (`app/services/llm.py:484-495`). |
| LLM-BOUNDARY-07 | MUST | Exists — keep | A model/session/thread/process identity cannot advance Product authority, DDO reducer state, Issue/PR lifecycle, merge, closure, or human acceptance. | DDO WorkerResultV2 and chain validator enforce the distinction (`app/builderops/delivery_orchestration_contracts.py:3364-3389,3617-3665`); broader mapper coverage is incomplete. |
| LLM-BOUNDARY-08 | MUST | Exists — keep | Resume reuses the same semantic input and start-once identity only after current authority/readback validation; a new repair attempt gets a new authorized identity. | Model Inquiry lineage and DDO idempotency provide local enforcement (`app/builderops/model_inquiry_runner.py:797-850`; `app/builderops/delivery_orchestration_contracts.py:3304-3358`); Product/eval lack a universal rule. |
| LLM-BOUNDARY-09 | MUST | Violated today | Structured output is validated against a named local schema before domain acceptance; prompt-only JSON is not sufficient. | Constrained completion and Model Inquiry validate; `ReasoningFacade.structured/tool_use` parse without the same validator (`app/components/reasoning/facade.py:272-385`). |
| LLM-BOUNDARY-10 | MUST | Exists — keep | A model result remains candidate cognition/provenance until its domain owner admits it; it cannot directly mutate durable human knowledge or governance state. | DDO authority and Product domain boundaries support this (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1292-1306`; `app/builderops/delivery_orchestration_contracts.py:3617-3665`); every new mapper still needs a test. |
| LLM-BOUNDARY-11 | GATE | Violated today | Provider/model allowlists equal the declared census projection; no new workflow, skill, script, or adapter literal selects a concrete target outside configuration. | ADR-0064 names the equality test (`docs/adr/ADR-0064-model-access-substrate.md:134-139`); Product/launcher/verification drift candidates are anchored at `app/llm/adapter.py:14`; `scripts/model_inquiry_subscription_adapter.py:34-71`; `app/dispatcher/verification_consumer.py:2721-2743`. |
| LLM-BOUNDARY-12 | GATE | New | Static transport census proves every effective provider/process call is behind an approved adapter, with explicit exemptions only for legacy migration and never for active Builder paths. | Existing import tests are partial (`tests/architecture/test_llm_contract_kernel.py:22-149`); no complete cross-surface census gate is present. |
| LLM-BOUNDARY-13 | GATE | New | Every mapper has contract tests for identity, failure, fallback, degradation, schema, receipt linkage, and unknown-version failure. | Builder kernel/adapter tests exist (`tests/architecture/test_llm_contract_kernel.py:107-149`; `tests/builderops/test_model_inquiry_adapters.py:67-147`); cross-runtime mapper tests are absent. |
| LLM-BOUNDARY-14 | GATE | Exists — keep | Worker adapters preserve `WorkerContextPack`/`WorkerInvocation` authority and return `WorkerResultV2`; carrier variation cannot change conformance or delivery authority. | DDO contract and tests are named in #4167 (`app/builderops/delivery_orchestration_contracts.py:3217-3389`; `tests/builderops/test_delivery_orchestration_contracts.py`). |
| LLM-BOUNDARY-15 | GATE | Exists — keep | Active Builder carrier policy is resolved once by the governed dispatcher/capability contract; skills and prompts do not add provider/model ladders. | Current main declares `ACTIVE_WORKER_RUNTIME = "codex"`, rejects unsupported runtime targets/hints, and has a Codex-only governance test (`app/builderops/epic_dispatch.py:86-86,295-295,1102-1106,1402-1408`; `tests/governance/test_codex_only_builder_runtime.py:12-23`). |
| LLM-BOUNDARY-16 | DOCTOR | New | Reconcile invocation census against adapter registry, provider census, and owner-doc declared entrypoints; report missing, duplicate, direct, or unreachable seams. | No single doctor spans Product, Builder, eval, scripts, and graph entrypoints; the existing kernel test is deliberately narrower (`tests/architecture/test_llm_contract_kernel.py:22-103`). |
| LLM-BOUNDARY-17 | DOCTOR | Violated today | Reconcile every terminal model/worker attempt to its request hash, effective identity, failure/fallback state, domain receipt, and current authority chain. | Model Inquiry and DDO provide local reconciliation (`app/builderops/model_inquiry_runner.py:570-688`; `app/builderops/delivery_orchestration_contracts.py:3462-3540`); Product telemetry/eval lack a common doctor. |
| LLM-BOUNDARY-18 | DOCTOR | Exists — keep | Detect provenance fields being consumed as authority inputs, including model/session/thread/process identifiers used to select scope or lifecycle. | DDO validator is a strong local guard (`app/builderops/delivery_orchestration_contracts.py:3617-3665`); cross-system data-flow detection is absent. |
| LLM-BOUNDARY-19 | DOCTOR | New | Detect stale compatibility wording and classify non-active provider/role references as current, historical, compatibility-only, design provenance, or separately governed. | #5203/#5205 are the current owner routes; current main still contains transition language (`scripts/model_inquiry_subscription_adapter.py:34-71`; `docs/BUILDEROPS_MODEL_INQUIRY/MODEL_TURN_ADAPTERS.md:12-15`). |

## 8. Compatibility and migration strategy

Migration should be additive and seam-by-seam:

1. **Freeze and census.** Record all current call sites and direct transports, preserve current owner
   docs, and add a static doctor/gate that reports rather than silently rewrites legacy paths.
2. **Kernel contract.** Keep `llm_contract` leaf-only. Add only neutral fields or versioned validators
   needed by an identified consumer; extend `docs/testing/invariant-tests.md` rather than forking it.
3. **Product bridge.** Adapt Product `ChatClient`/legacy service behind the neutral adapter port,
   retaining `LLMTaskIntent`, `LLMRoute`, settings precedence, Product fallback, embedding identity,
   and current public compatibility functions. Migrate reflection first because it is a documented
   direct exit; then migrate reasoning/planner/QA/domain callers independently.
4. **Structured result convergence.** Reuse the neutral schema/failure primitives beneath domain
   validators. Preserve each caller's current domain outcome: unknown, no-link, extraction failure,
   planner fallback, attribution failure, or hard error.
5. **Builder bridge.** Keep Model Inquiry, CKM, and design-agent adapters on Builder-owned resolver
   and secret/receipt paths. Do not route them through Product settings or Product health. Preserve
   the Codex-only carrier policy now present in main, and complete the single-target Model Inquiry
   transition through existing #5203 without duplicating either owner route.
6. **Worker bridge.** Define one mapper from a reducer-authorized `WorkerInvocation` to a model-turn
   request, and one mapper from the normalized result to `WorkerResultV2`. Keep carrier envelope
   fields opaque and preserve the full authority chain.
7. **Verification/eval/scripts.** Move concrete role/model selection from code validation and role
   launchers to the appropriate declared resolver/census. Keep verification, CI, review, merge,
   Model Inquiry, and eval receipts as separate authorities.
8. **Retire only with proof.** Remove a legacy seam only after the doctor shows zero active callers,
   a focused replacement test passes, current docs are updated, and the owning workflow has a
   truthful migration/rollback receipt.

This sequencing avoids a “unified facade” that silently changes fallback, receipt, or authority
behavior. It also allows a future adapter to be added by a census/profile/secret contract and
adapter tests without changing skills or domain contracts.

## 9. Test strategy

The eventual implementation specification should require these layers:

| Layer | Proof target |
| --- | --- |
| Kernel unit | Frozen contracts, canonical hashes, enum/version rejection, schema locality, no `app` import, no network/credential side effect (`tests/architecture/test_llm_contract_kernel.py:22-149`). |
| Adapter contract | Every adapter returns normalized success/failure; timeout, auth/session, empty/oversize, malformed output, process cleanup, request identity, and secret redaction are deterministic (`tests/builderops/test_model_inquiry_adapters.py:67-229`). |
| Resolver/census | Provider-free intent, exact role/profile, capability attestation, target independence, credential contract, allowlist/census equality, no ambient override. |
| Product call-site | Reflection, reasoning, planner, QA, constrained callers, embeddings, and eval use the approved port or have an explicit owner-approved exception; existing domain fallback semantics remain unchanged. |
| Mapper contract | Product and Builder mappers preserve authority/provenance/failure/fallback/degradation/schema/side-effect fields and fail closed on unknown versions. |
| Worker contract | Exact pack/invocation/result authority chain, one start-once identity, carrier variation, terminal observation, pause/resume/supersession, and no advancement from text/process/session alone (`tests/builderops/test_delivery_orchestration_contracts.py`). |
| Orchestration/A2A | Agent calls remain distinguishable from model turns; permission, trace/correlation, handler error, retry, compensation, checkpoint, and remote-transport non-goals remain intact (`tests/orchestrator/*`). |
| Static doctor/gate | AST/import/transport census, literal-selection scan, skill/prompt/config scan, provider census reconciliation, and current-vs-historical compatibility classification. |
| Fault/restart | Provider unavailable, credential unavailable, session expired, adapter timeout, receipt persistence failure, process crash, heartbeat loss, stale head, duplicate retry, and unknown external effect all produce truthful typed states. |
| Security | No secret values in requests/logs/receipts, bounded output, minimal environment, shell-free process invocation, containment, egress restrictions, and no unauthenticated provider/session path. |
| Exact-head delivery | Any implementation PR must use current-SHA CI, required review/verification, and owner-doc writeback gates. Local tests cannot claim live provider, browser, host, or UAT capability. |

## 10. Risks and open questions

- **Boundary inflation:** “all LLM and agent calls” can create a god-core. Mitigation: model-turn
  adapter below domain/worker contracts; tools, effects, orchestration, and authority remain separate.
- **Fallback drift:** a common `fallback` boolean would erase Product embedding compatibility,
  planner behavior, Model Inquiry independence, and DDO retry meaning. Use the existing five-value
  vocabulary and runtime-owned decisions.
- **Provenance laundering:** a valid provider request ID or thread identity may look authoritative.
  DDO's opaque carrier envelope and exact chain validator are the precedent.
- **False Codex-only claim:** current main now explicitly declares the active Builder carrier
  Codex-only, but transition/compatibility surfaces remain and do not become active policy merely by
  containing historical provider or role references. The audit does not infer closure of related
  Issues from the source commit.
- **Census fragmentation:** Product registry, embedding registry, Builder provider census, role TOML,
  launcher code, and eval config have different scopes. A single physical registry would transfer
  authority; a shared descriptor shape plus separate registries is safer.
- **Receipt multiplication:** adding a model receipt to every domain result could make telemetry a
  second authority. Store stable references and leave retention/acceptance to the owner.
- **Credential scope:** the neutral contract may carry logical credential identity but never value;
  host-local session exceptions remain explicit and separately governed.
- **Migration shadow traffic:** dual execution would risk cost, nondeterminism, and duplicate effects.
  Prefer injected adapters and replayable fixtures before any live comparison.

Owner decisions still needed only if existing routes do not settle them. Their disposition is explicit:

1. **Deferred to the ADR-0063/64 implementation specification:** whether a future Product/Builder
   mapper should expose one shared receipt-reference vocabulary or only shared failure/schema
   primitives. No implementation choice is made here.
2. **Deferred to Product LLM owner review:** which Product legacy transport is retired first after
   the reflection bridge. `docs/LLM_ROUTING.md` and Product code remain authoritative until a
   bounded migration slice is accepted.
3. **Requires an owner decision at the OEF/Builder boundary:** whether eval belongs in the same
   capability census or remains a separate OEF-owned consumer. Until decided, eval stays separate
   and no common-census claim is made.

## 11. Explicit non-goals

This audit does not:

- implement or refactor the kernel, adapters, routers, facades, launchers, or worker runtime;
- authenticate, inspect, modify, or invoke a non-Codex service or subscription session;
- introduce a new provider, model family, credential path, host, SDK, or external API;
- copy concrete model IDs into a new skill, script, prompt, or audit artifact;
- make Product and Builder share mutable settings, registries, credentials, sessions, health, stores,
  or fallback policy;
- merge chat, embedding, reranking, TTS, STT, tool, and agent semantics into one transport;
- replace dispatcher, A2A, LangGraph, DDO, verification/closure, GitHub, CI, or exact-head authority;
- make CKM, retrieval, evaluation, telemetry, a model session, or a dashboard authoritative;
- claim that the desired boundary, live provider capability, or owner acceptance is shipped. The
  current active Builder carrier Codex-only policy is explicit in main, but that does not prove the
  desired neutral boundary is delivered; or
- create a GitHub Issue or directly turn this audit into implementation scope.

## 12. Existing-work reconciliation and disposition

The audit found existing, active authority rather than a missing backlog container:

| Existing authority | Reconciliation | Disposition |
| --- | --- | --- |
| ADR-0063 shared neutral kernel | Directly answers the Product/Builder boundary and mapper question. | **Accepted / superseding direction:** use it as the architectural baseline. |
| ADR-0064 Model Access Substrate | Owns provider-free resolution, credential/session acquisition, capability negotiation, typed failures, and visible degradation. | **Accepted / constraint:** substrate resolves and executes; runtime policy decides. |
| DDO worker contracts / #4167 | Already binds Worker authority separately from carrier provenance and gives the correct worker bridge. | **Accepted / reuse:** no second worker invocation contract. |
| #5177 Execution Routing | Owns Builder capability selection/TCD routing and explicitly keeps concrete identities out of workflow contracts. | **Accepted / coordinate:** general routing remains there. |
| #5203 Model Inquiry single-target | Owns current Model Inquiry role/target/receipt transition. | **Existing owner route:** do not duplicate or mutate from this audit. |
| #5205 active Builder carrier Codex-only | Former owner route for active carrier policy and current-vs-historical compatibility wording; the corresponding Codex-only policy is now present in main. | **Accepted / current main:** preserve the closed Issue as lifecycle evidence; do not duplicate its policy. |
| Product routing/embedding owner docs | Own current runtime semantics, precedence, identity, and fallback. | **Preserve:** migrate through compatibility adapters and domain tests. |
| `docs/testing/invariant-tests.md` | Existing invariant registry, though its current enforcement labels predate the MUST/GATE/DOCTOR research vocabulary. | **Deferred implementation detail:** extend the registry when a governed slice is accepted; do not fork it now. |

### 12.1 Live authority and overlap snapshot

Read back at `2026-08-30T11:35:43Z`, against `origin/main` SHA
`3625c3276b71e7396cca39f7a2732ddd603a9b55`:

| Object | Live state | Authority meaning | Disposition for this audit |
| --- | --- | --- | --- |
| PR #5201 | Open, dirty; head `236f862480c461f97432257a68b8c7d321cb9ea2` | Earlier/narrower Model Inquiry routing audit and its `DOCS_INDEX` mutation. | Preserve as collision authority; do not duplicate or expand it. |
| PR #5202 | Open, dirty; head `be9b190f0b14c8b3b91097ad79f8217f9398b31f` | Unrelated DevUI docs-authoring change that also mutates `DOCS_INDEX`. | Preserve scope; its shared index mutation blocks a parallel docs PR. |
| Issue #5177 | Open, `agent:blocked` epic | General Builder execution-routing owner. | Coordinate; no new routing epic or Issue. |
| Issue #5203 | Open, `agent:in-progress` | Model Inquiry single-target semantics. | Existing owner route; no duplicate role/target contract. |
| Issue #5205 | Closed | Active Builder carrier Codex-only policy; now reflected in current main. | Preserve lifecycle truth; no duplicate carrier mutation. |

The local audit branch has no PR. Both overlapping PRs remain open, so publication remains fail-closed
until the shared `DOCS_INDEX.md` overlap is resolved and the audit remains demonstrably
non-duplicative against #5201. This table is
an observation, not a lifecycle mutation or a claim that any listed PR/Issue is complete.

No new PromotionIntent was created because this pass produced supporting architecture evidence and
the existing owner decisions/issues already cover the immediate transitions. If the owner accepts a
new implementation handoff, the exact next step is:

1. create a BuilderOps `PromotionIntent` through the existing promotion gateway, referencing this
   audit, ADR-0063, ADR-0064, DDO worker contracts, and the selected existing owner surface;
2. obtain the resulting receipt and use `feature-breakdown` only if the accepted change crosses into
   a new normative specification; and
3. create bounded child Issues from that accepted specification, each with exact source anchors,
   `Verify:` targets, and the current Product/Builder authority classification.

That handoff must not be inferred from this audit, and it must not create a parallel “unified LLM
agent” backlog stream.

## 13. Final answer

The durable answer is a **neutral model-access kernel plus separate runtime-owned resolvers and
adapters**, with an explicit Worker mapper above it:

`provider-free intent -> Product/Builder resolver -> configured adapter -> typed result/failure -> owning-domain receipt`,

and, for Builder delivery:

`WorkerInvocation authority chain + model carrier provenance -> WorkerResultV2`.

This reduces duplicated contract seams while preserving the boundaries that matter: Product policy,
Builder policy, credential/session ownership, fallback decisions, domain acceptance, delivery
authority, and exact-head evidence remain separate. Codex-only active operation is a governed
profile decision in the existing Builder routes, not a provider assumption embedded in the kernel.
