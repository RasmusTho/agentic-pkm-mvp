State: Advisory Phase 0 architecture audit; no execution-routing implementation is authorized
Doc role: Point-in-time current-state audit and implementation-planning input for Issue #5178 / epic #5177
Authority: Advisory evidence subordinate to `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`, live GitHub contracts, executable skills, DDO contracts, dispatcher authority, and verification-and-closure
Owner: Builder System governance
Temporal class: audit snapshot
Source snapshot: `origin/main` `ddb2ff40cfb612636ca47912a091cc7c9f818585`, re-read 2026-08-29T13:37:22Z, plus live GitHub readback on 2026-08-29
Promotion handoff: BuilderOps `prom_20260829133839_3fc3c495`, accepted receipt `receipt_20260829133914_c47a1ff5`; the PR remains the authority-mutation gate

# Builder Execution Routing — Phase 0 Audit And Target Design

## 1. Current-state execution-routing map

This audit executes the bounded contract in [Issue #5178](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5178), child of [epic #5177](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5177). It tests the epic hypothesis against current repository evidence; it does not implement Phase 1, change the TCD ladder, start a new orchestration system, or authorize future children.

The Phase 0 contract prohibited parallel orchestration. One Sol/high synthesis worker therefore read
the subsystem boundaries sequentially at one immutable main snapshot; no helper was used and no
cross-SHA evidence was mixed.

The present route is distributed:

| Stage | Current mechanism | Current status |
|---|---|---|
| Intake and eligibility | GitHub Issue contract, strict `agent:ready`, `issue-to-code`, dispatcher pull/claim | Deterministic contract checks plus governed agent judgment |
| Issue-set shaping | `deliver-issue-set`, feature-breakdown, TCD launch policy | Agentic selection under deterministic caps and lifecycle rules |
| Plan and context | `app/builderops/epic_dispatch.py` | Deterministic plan shape; agent-reviewed bounded context pack |
| Model class | `_model_class_for(risk)` and `_TCD_CODEX_ROUTE` | Hard-coded Luna/low, Terra/medium, Sol/high mapping; no Spark or attempt-aware resolution |
| Invocation | `CodexIssueSessionLauncher` and agent adapters | Configured adapter or hard-coded Codex model/reasoning invocation |
| Task/lease state | dispatcher task and lease records | Deterministic coordination; GitHub remains lifecycle truth |
| Resume evidence | `epic_run_state.py` | Compact evidence only; no mutation or launch authority |
| Worker semantics | DDO `WorkerContextPack`, `WorkerInvocation`, `WorkerCarrierEnvelope`, `WorkerResultV2` | Provider-neutral, hash-bound target contracts already delivered in repo |
| Provider/model access | Builder model-access resolver plus `providers.yaml` | Provider-free intent resolution exists for named Builder paths, not general delivery routing |
| Verification | `verification-and-closure` and verification consumer | Exact-head, issue-contract, CI/review/merge/closure authority independent of worker model |
| Learning | BuilderOps `LearningSignal`, delivery feedback loop, TCD metrics | Durable improvement input; no automatic policy mutation |

Anchors: `app/builderops/epic_dispatch.py:59-63,217-225,262-403,679-775`; `app/builderops/epic_run_state.py:18-63,100-129,382-454`; `app/builderops/delivery_orchestration_contracts.py:2308-2354,3217-3519,3642-3734`; `docs/AGENT_ISSUE_DISPATCHER.md:13-36,52-78`; `.codex/agents/*.toml`.

Completed #3229 supplied dispatcher-backed epic planning, bounded context packs, run-state and launch-policy evidence. Completed #3279 supplied throughput/coordination improvements. Newer DDO, BuilderOps control-plane, model-access substrate, exact-head verification, and adapter work supersede any assumption that either epic created one canonical capability resolver or that dispatcher SQLite should become one.

Ranked weaknesses use systemic impact (blast radius multiplied by silence of failure):

| Rank | Finding | Evidence | Disposition |
|---|---|---|---|
| F1 | Model policy is split between TCD prose, adapters and a launcher map, so consumers can diverge silently | `AGENTS.md :: Total Cost of Development`; `.codex/agents/*.toml`; `epic_dispatch.py:59-63,217-225` | Accepted: consolidate under one target contract |
| F2 | No typed route, allocation, fallback, escalation or attempt decision exists | `epic_dispatch.py:679-775`; `epic_run_state.py:18-63` | Accepted: exact Phase 1 gap |
| F3 | DDO already has the correct authority/context/invocation carrier seam, but routing is not bound to it | `delivery_orchestration_contracts.py:3217-3519` | Accepted: extend; do not fork |
| F4 | Current TCD/receipt data cannot compare expected TCD by capability and accepted delivery | `delivery_orchestration_contracts.py:2308-2354`; `epic_run_context_budget.py:436-495` | Accepted: later additive receipt work |
| F5 | No supported Spark allocation observation exists | `_TCD_CODEX_ROUTE`; `providers.yaml:71-86,112-118` | Deferred dependency: unknown must fall back to Luna |

## 2. Authority and ownership map

The smallest canonical owner is the Builder System process architecture, with a versioned execution-routing decision contract implemented beside DDO's plan/compiler contracts. It owns policy semantics, not every consuming mechanism.

- `AGENTS.md :: Total Cost of Development` owns proportional optimization principles and the current model/reasoning ladder.
- The execution-routing contract owns work/capability/allocation semantics and route authorization.
- Dispatcher/control plane owns tasks, claims, leases, concurrency, retries, legal transitions, and fenced effects—not model policy.
- DDO owns provider-neutral worker context, invocation identity, result, acceptance, and receipt semantics.
- Model-access/config owns late binding from a capability tier to a declared provider, model, reasoning profile, endpoint, and credential identity.
- BuilderOps owns durable observations, attempt records, receipts, and learning—not GitHub truth or route authorization.
- Epic run-state is a compact resume/reconciliation index only.
- Skills collect workflow inputs and invoke the contract; they must not each carry a commercial/model ladder.
- Verification-and-closure remains the sole merge/closure gate.

This resolves the ownership question without adding a second control plane. The normative target contract is now in `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md :: Execution Routing target contract`; this audit remains advisory evidence.

## 3. Deterministic-versus-cognitive orchestration map

| Deterministic Builder policy/state | Bounded LLM proposal/cognition |
|---|---|
| Dependency graph and eligibility | Work-class proposal |
| Task, claim, lease, worktree and exact-head identities | Decomposition proposal |
| Legal transitions, concurrency and execution budgets | Relevant-context selection |
| Protected-surface and Human Exception classifiers | Capability recommendation |
| Retry counters, attempt lineage, fallback state | Result summarization |
| Route-schema and capability-adequacy validation | Failure-classification proposal |
| Verification-profile preservation | Next-action recommendation |
| Receipt identity, persistence and replay | Explanation of ambiguity |

The governing principle is: **an LLM proposes orchestration decisions; deterministic Builder policy authorizes them**. A Luna coordinator is therefore viable only as a bounded proposal producer attached to the existing plan/run identity. It cannot claim work, mutate lifecycle, start a worker, waive a gate, or attest delivery.

## 4. Reuse and gap matrix

| Mechanism | Classification | Disposition |
|---|---|---|
| GitHub Issue/PR/CI authority | `reuse unchanged` | Routing consumes exact authority references only |
| Dispatcher tasks, claims, leases, caps | `reuse unchanged` | Keep coordination deterministic and model-neutral |
| Verification-and-closure | `reuse unchanged` | Preserve current-head and closure gates verbatim |
| DDO worker context/invocation/result chain | `extend` | Add route-decision/attempt references without changing effect authority |
| DDO TCD metrics and receipts | `extend` | Add execution economics and transition observations |
| Epic run-state | `extend` | Index compact route decisions/attempt outcomes; remain evidence-only |
| `epic_dispatch` TCD decision and launcher | `consolidate` | Replace hard-coded mapping with the canonical resolver/config adapter |
| Agent adapter model defaults | `consolidate` | Retain safe defaults; cease treating them as routing policy |
| TCD model ladder in `AGENTS.md` | `reuse unchanged` for Phase 0 | Change only after accepted-delivery evidence |
| Builder model-access resolver/census | `extend` | Add Builder delivery profiles after policy chooses a tier |
| Provider/model IDs in skills | `supersede` | Skills call capability policy, never encode commercial inventory |
| Product Context Bundles | `reuse unchanged` in Product only | Explicitly reject as Builder worker-packet substrate |
| Route request/decision/attempt schemas | `missing` | Create in Phase 1 under DDO-adjacent Builder ownership |
| Supported Spark allocation observation | `missing` | Accept explicit/fresh observation; unknown safely falls back |
| Luna coordinator proposal schema | `missing` | Add later after deterministic resolver can validate it |
| Accepted-delivery comparative dataset | `missing` | Gather in shadow/canary runs before policy promotion |

## 5. Recommended target architecture

The tested hypothesis is accepted with one correction: the “Builder Control Plane” is not a new component. It is the existing GitHub + dispatcher/control-plane + DDO + BuilderOps composition. Execution Routing is one pure policy seam inside it.

```text
live Issue/plan authority + deterministic state + observations
                         |
            optional bounded coordinator proposal
                         |
          versioned ExecutionRoute resolver
                         |
      capability tier + immutable RouteDecision
                         |
 model-access/config adapter -> provider/model/reasoning
                         |
       existing DDO worker invocation and result
                         |
            unchanged verification and closure
                         |
             attempt + accepted-delivery receipt
```

The resolver takes authority ref, policy version, work class, risk, ambiguity, protected surfaces, allocation observations, prior attempt outcomes, verification profile, and execution budget. It returns a selected capability tier/reasoning class, decision kind/reason, preserved references, limits, and stop/escalation conditions. It performs no external effect.

Provider and model identifiers stay out of policy inputs and skills. The execution adapter resolves the authorized tier through repo/host configuration at invocation time and records the actual carrier observation.

### Research-question resolutions

1. **Canonical ownership:** Builder System process architecture owns the policy; a DDO-adjacent pure
   resolver implements it; dispatcher, BuilderOps, run-state, skills, context construction, and
   launchers consume only their bounded parts.
2. **Cheap coordinator:** yes, as a proposal-only Luna role on the existing run identity, with
   deterministic validation before any effect.
3. **Spark opportunity:** only a supported explicit, fresh allocation observation may select it;
   missing or unknown state selects Luna.
4. **Capability resolution:** resolve provider-neutral work/risk/ambiguity/allocation/attempt inputs
   to a capability tier, then late-bind tier to provider/model configuration.
5. **Fallback versus escalation:** fallback is capacity-driven within an adequate work class;
   escalation is evidence-driven capability increase. Record both on the attempt lineage.
6. **Context preservation:** keep the hash-bound DDO worker pack stable; bind route/attempt refs in
   a new invocation/attempt identity outside the pack, and never copy the epic or transcript.
7. **Verification invariance:** the route references but cannot mutate the verification profile;
   verification independently re-reads live current-head authority.

## 6. Work-class and capability model

| Work class | Normal policy candidate | Important gates |
|---|---|---|
| `deterministic` | No LLM worker | Fail closed if the operation cannot be fully specified/validated |
| `bounded_fast` | Spark only with explicit bonus availability; otherwise Luna | Small bounded goal, adequate capability, unchanged Verify profile |
| `general_delivery` | Luna candidate in shadow/comparison; current Terra default remains | Promote Luna only on accepted-delivery economics and quality |
| `complex_delivery` | Terra, with evidence-based Sol escalation | Ambiguity, cross-system reasoning, repeated inadequate attempts |
| `frontier_high_risk` | Sol | Protected surfaces, high merge risk, security/data/concurrency/authority semantics |

Capability tier is distinct from allocation class. `spark`, `luna`, `terra`, and `sol` are policy capabilities; `bonus_available`, `economically_unavailable`, and `unknown` are scoped observations. Current model IDs are adapter configuration, not stable architecture.

## 7. Luna coordinator design

The existing dispatcher/run-state architecture can support a Luna coordinator without another orchestrator if Luna only emits a proposal.

- **Inputs:** exact Issue/plan/run refs, normalized dependency/eligibility summary, policy version, allowed work classes/capabilities, compact prior-attempt results, context-source candidates, limits, and verification profile.
- **Bounded context:** authority, goal, relevant source/test refs, constraints, known findings, previous attempt result, Verify targets, and stop/escalation conditions. No whole epic or transcript.
- **Output:** versioned proposal with classification, decomposition/context refs, capability recommendation, reason codes, uncertainty, and next action.
- **Validation:** deterministic schema, authority/ref/hash, eligibility, cap, protected-surface, capability-adequacy, context-budget, and verification-profile checks.
- **Lifecycle:** proposal -> validate -> accept/reject -> authorize route -> invoke. Proposal alone has no effect.
- **Recovery:** reuse run/proposal idempotency identity; reject stale authority; retry within deterministic limits; preserve attempt history.
- **Boundary:** no claim, GitHub mutation, worker start, gate waiver, merge, closure, or policy change.

The configured `issue_set_coordinator` already uses Luna/low for bounded coordination, but that adapter is evidence of a viable carrier—not the canonical contract and not proof that Luna should yet replace Terra for general delivery.

## 8. Spark opportunity and Luna fallback design

No repository-supported Spark allocation or quota mechanism exists. The current launcher map omits Spark, and the provider census does not declare a Spark Builder delivery profile. The optional helper experiment was therefore not run: selecting Spark would have invented the mechanism under audit.

Phase 1 should accept only a typed, scoped, timestamped allocation observation from a supported configuration/operator/provider surface:

- `bonus_available`: Spark may be preferred for adequate `bounded_fast` work;
- `economically_unavailable`: use Luna; or
- `unknown`: use Luna safely.

Observation freshness and provenance are mandatory; absence is `unknown`. Do not poll undocumented quota surfaces, scrape UI, infer availability from marketing, or put allocation state in skills. A Spark launch failure classified as allocation/capacity produces one recorded fallback to Luna under the same route lineage. Spark is never required for pickup or delivery.

## 9. Fallback versus escalation contract

`fallback` preserves work class and required capability while changing to another adequate carrier/tier because the preferred allocation is unavailable. Example: Spark unavailable -> Luna.

`escalation` increases required reasoning capability because evidence shows the current tier is inadequate or risk/ambiguity increased. Example: Luna exposes cross-system concurrency semantics -> Sol.

Each transition records from/to tier, transition kind, stable reason code, triggering observation/attempt, attempt lineage, preserved context/verification hashes, and policy version. Allocation exhaustion must never masquerade as capability failure; an inadequate result must never masquerade as commercial fallback. Run-state may index the transition, but the durable execution attempt/receipt is the evidence source.

## 10. Minimal context, run-state, and receipt changes

Extend rather than replace the DDO chain:

1. Add `ExecutionRouteRequest`, `ExecutionRouteDecision`, `ExecutionAttemptObservation`, and canonical refs/hashes.
2. Keep `WorkerContextPack` byte-stable across fallback. The route decision references its context-pack
   hash, while `WorkerInvocation` or an additive attempt envelope binds the route decision, stable
   context pack, and authorizing reducer effect. Each fallback receives a new invocation/attempt
   identity without changing the context hash, Verify targets, or effect authority.
3. Add actual capability/provider/model/reasoning and transition/attempt observations to the carrier/result/receipt layer, never to delivery authority.
4. Add compact `routing_decisions` and attempt summaries to epic run-state for resume; keep it evidence-only and excluded from worker context.
5. Keep one bounded worker packet: authority, goal, refs, constraints, findings, prior result, verification, and stop conditions.

The Product `ContextBundle` remains a Bridge/Assembly artifact and must not be conflated with the Builder DDO `WorkerContextPack`. The latter already supplies the required hash-bound semantic seam.

Verification invariance is structural: the route decision references a pre-existing verification profile and cannot edit it; the worker invocation binds the same Issue, plan, effect and context hashes; the carrier envelope is explicitly non-authoritative; verification independently re-reads live current-head authority. Spark or Luna can therefore change execution capability but cannot reduce tests, review, exact-head CI, branch protection, merge authorization, Human Exception rules, owner-doc/writeback, or closure readback.

## 11. Measurement plan

The target measure is **expected TCD per accepted delivery**. Begin in shadow mode, then bounded canaries, before any default-policy change.

Minimum attempt/delivery data: work class; coordinator tier; requested and actual capability; actual provider/model/reasoning; allocation class/provenance/freshness; fallback/escalation and reason; attempts; latency; verification result; independent-review findings; CI result; rework; human steering; and post-merge repair/regression. Bind final comparison to accepted current-head delivery, not invocation success.

Compare Luna and Terra within matched work classes and risk bands. Promote Luna only if accepted-delivery quality remains sufficiently close while expected TCD improves. Spark utilization and cheapest individual invocation are explicitly invalid optimization targets.

## 12. Major risks and rejected alternatives

| Risk or alternative | Disposition |
|---|---|
| Duplicate policy in AGENTS, skills, dispatcher and BuilderOps | Reject; one contract owner, many consumers |
| New “routing orchestrator” service | Reject; extend existing DDO/control-plane seams |
| Dispatcher SQLite as model-policy authority | Reject; dispatcher owns coordination, and newer control-plane work is migrating durable effects |
| BuilderOps observations authorizing routes | Reject; evidence cannot become policy by persistence |
| Fake Spark quota oracle or UI scraping | Reject; explicit/fresh observation or safe Luna fallback |
| Spark as a required fast lane | Reject; it is opportunistic capacity only |
| Coordinator directly executing its proposal | Reject; deterministic authorization must intervene |
| Whole transcript/epic copied to workers | Reject; bounded hash-addressed context |
| Product Context Bundle reused for worker routing | Reject; wrong authority and artifact class |
| Model benchmark claim changes TCD ladder | Reject; require accepted-delivery evidence |
| Capability choice weakens verification | Protected invariant violation; fail closed |

Invariant kernel for later implementation:

- **MUST ER-01 — New:** one versioned policy owner; provider/model IDs remain adapter configuration.
- **GATE ER-02 — Exists, keep and extend:** route decisions cannot change the verification profile
  or effect authority. DDO and verification already enforce the underlying authority boundary.
- **MUST ER-03 — New:** fallback and escalation are distinct, reasoned, receipted transitions.
- **GATE ER-04 — New:** Spark unknown/unavailable falls back to Luna and never blocks delivery.
- **MUST ER-05 — Exists, keep and extend:** context and attempt lineage remain bounded, hash-bound,
  and continuous in the existing DDO worker chain.
- **GATE ER-06 — Partial today:** coordinator output is proposal-only until deterministic validation;
  epic planning is effect-free, but no route-proposal schema exists.
- **DOCTOR ER-07 — New:** configuration exposes supported capability mappings and observation
  freshness without claiming quota truth.

This extends the accepted Builder System decomposition and DDO carrier-neutral boundary; it does not reshape the SBS or centralize Product/runtime model policy.

### SBS reconciliation

The target **conforms to** the single governed Builder System L0 root and the Builder enabling-system
boundary in `docs/architecture/SBS_OPERATING_MODEL.md`. It **extends** the existing DDO worker-runtime
and cross-cutting TCD process with one policy seam. It does not reshape `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`,
move Product LLM authority, or create a CES/ADR-class structural decision.

## 13. Exact recommended Phase 1 vertical slice

Create one bounded Issue for a **shadow-first `bounded_fast` execution preflight on the existing `deliver-issue-set` -> `epic_dispatch` -> `issue-to-code` worker path**:

1. implement provider-neutral route request/decision/attempt contracts and a pure deterministic resolver;
2. consume exact Issue eligibility, risk/protected-surface inputs, immutable Verify targets, prior attempts, and an injected explicit allocation observation;
3. select Spark only for adequate `bounded_fast` work with fresh `bonus_available`; otherwise select Luna;
4. keep the same DDO context/authority/verification hashes through fallback while creating a new
   invocation/attempt identity for the fallback carrier;
5. resolve tier -> model/reasoning through configuration rather than `_TCD_CODEX_ROUTE`;
6. emit a routing decision/attempt receipt and shadow comparison;
7. make no Luna->Terra->Sol automatic escalation, no general-delivery default change, no skill-wide rewrite, and no merge/closure change.

This is narrower than a general issue-to-code router but exercises the real issue-to-code worker launch seam. It proves the policy boundary and Spark->Luna fallback without making Spark a dependency. Phase 0 does not implement it.

## 14. Proposed later child decomposition

Do not create these children mechanically; create each only after the preceding evidence is accepted.

1. **Phase 1 — bounded-fast route contracts and canary:** the exact slice above.
2. **Coordinator proposals:** Luna proposal schema, deterministic validator, retry/recovery, and context selection on the existing run identity.
3. **General-delivery experiment:** matched Luna/Terra shadow and canary cohorts with accepted-delivery economics; owner decision on default promotion.
4. **Attempt/receipt durability:** DDO/BuilderOps routing transition records, epic run-state index, recovery and projection.
5. **Capability escalation:** evidence-based Luna->Terra->Sol policy, protected-surface rules, and failure taxonomy.
6. **Policy reevaluation:** learning-retrospective input, periodic TCD evaluation, and governed policy-version promotion.

No unresolved owner decision blocks Phase 1. The later Luna-versus-Terra default remains an empirical owner-policy decision after evidence; supported Spark allocation provenance remains a prerequisite for selecting Spark rather than falling back to Luna.
