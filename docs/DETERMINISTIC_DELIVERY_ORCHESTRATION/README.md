State: Active target-state specification. Parent #4163 owns live validation state. DDO-01 #4164, DDO-02 #4165, and DDO-03 #4166 are delivered; DDO-04 #4167 is the next serial implementation slice after contract reconciliation; #4168–#4170 remain dependency-blocked.
Doc role: Builder System capability specification
Authority: Owns the bounded target, decomposition, cross-task invariants, verification path, and acceptance path for deterministic issue-set delivery. GitHub Issues own executable task state after filing.
Owner: Builder System governance
Temporal class: operational
Review cadence: event-driven
Source of truth: this directory for the capability contract; live GitHub, dispatcher, CI, PR, review, merge, and closure evidence for delivery truth
Last reviewed: 2026-07-28

# Deterministic Delivery Orchestration

## Capability boundary

This capability reduces coordination cost in Builder System issue-set delivery without creating a
new delivery authority or waiting for a complete CKM control surface.

It adds two progressively stronger paths:

1. an immediate fast lane for explicit sets of strictly ready, independent Issues using today's
   claim, worktree, worker, CI, review, merge, and closure primitives; and
2. a deterministic delivery reducer that compiles immutable plans, advances only allowed
   transitions, reuses the delivered BuilderOps transaction/outbox kernel, reconciles live
   authority after failure, and projects receipts back into CKM.

CKM remains a projection and initiation surface. GitHub Issues, exact PR heads, CI/check evidence,
review evidence, verified merge state, and explicit closure remain delivery authority. The static
CKM Direction B HTML remains non-mutating; it is not converted into a control plane.

The capability is Builder System work with a BuilderOps/GitHub boundary. It changes no
Product/Runtime behavior, user memory, Human Knowledge Artifact authority, or Product SBS contract.

## Prior work reused rather than duplicated

- Closed epic [#3229](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3229) delivered the
  dispatcher-backed epic-runner baseline: run-state, dispatch planning, lifecycle planning, bounded
  context packs, and compact receipts.
- Closed child [#3792](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3792) under BuilderOps
  control-plane parent [#3788](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3788) delivered
  the PostgreSQL transaction/outbox kernel. This capability adds a delivery reducer and adapters
  over that substrate; it does not build a second journal/outbox.
- [PR #4159](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4159) owns review-severity routing.
- [PR #4161](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4161) owns deterministic known-defect
  intake. This capability consumes those contracts and does not redefine their registry.
- BuilderOps model inquiry `inq_20260727T075022Z_55bcca22` is advisory provenance. This
  specification is self-sufficient and does not require machine-local inquiry access.

## Outcomes

### Immediate value

The next suitable bugfix set can run without a synthetic epic and without worker-to-worker
coordination:

- explicit issue-set scope;
- strict readiness and independence validation;
- maximum two workers during the budget-constrained pilot;
- one Issue, worktree, branch, and PR per worker;
- no worker communication unless an actual file, schema, migration, contract, or authority overlap
  is discovered;
- one compact terminal receipt per worker;
- coordinator intervention only for typed exceptions;
- P0/P1, protected-risk, false-green, malformed, and low-confidence review verdicts block;
- validated P2 is deferred through the governed known-defect path without a synchronous repair or
  re-review loop; and
- P3 remains informational.

### Full capability

- separate carrier-neutral `DeliveryRequest.v1`, `DeliveryPreview.v1`, and approved
  `DeliveryInitiation.v2` contracts;
- pure, read-only compilation into immutable `DeliveryPlan.v1`;
- deterministic reducer transitions;
- idempotent effects through existing BuilderOps fencing/outbox contracts;
- one provider-neutral worker context/invocation/result seam with durable correlation and
  reattachment;
- crash recovery through live-authority reconciliation;
- typed pause, resume, cancel, and supersede commands plus a separate active-run projection;
- additive `DeliveryReceipt.v2` with immutable acceptance-profile, supersession, TCD, exception,
  review, known-defect, and provenance evidence; and
- separate CKM drafting/approval/receipt projection without cockpit mutation.

## Architecture modules

| Module | Owns | Does not own | Primary reason to change |
| --- | --- | --- | --- |
| Fast-lane policy | Strict independent-set admission and no-coordination execution profile | Durable orchestration state | Operating policy and immediate TCD reduction |
| Delivery contracts | Request, preview, approved initiation, plan, reducer event/effect, worker-runtime, active-run, acceptance-profile, and receipt schemas | Persistence or external effects | Contract evolution |
| Plan compiler | Pure scope resolution, readiness checks, dependency waves, exclusions, and typed rejection | Claims, launches, GitHub writes | Planning rules |
| Delivery reducer | Allowed state transitions and next-effect decisions | Provider execution or authority mutation | State-machine policy |
| Effect adapters | Claim, worker correlation, CI/review wait, merge/closure calls | Deciding whether an effect is allowed | External integration |
| BuilderOps journal/outbox binding | Fencing, idempotency, effect durability, unknown-state reconciliation | GitHub delivery authority | Crash safety and concurrency |
| CKM bridge | Draft, preview, authenticated initiation handoff, and receipt projection | Delivery execution or static cockpit mutation | Operator overview and initiation |
| TCD/acceptance harness | Baseline, pilot metrics, fault tests, and capability acceptance | Runtime scheduling | Evidence and rollout |

The durable carrier for `DeliveryInitiation.v2` remains intentionally undecided. Builder System
governance owns that later semantic/governance gate. Revisit it only after the compiler, reducer,
BuilderOps reconciliation binding, and CKM bridge have supplied evidence that either the live
`PromotionIntent` semantics are sufficient or a distinct record has a lower total contract and
migration cost. Until then, canonical initiation bytes may be transported by a bounded approval
envelope but no transport or storage shape becomes contract authority.

## Deterministic, agentic, and owner decisions

| Decision | Owner |
| --- | --- |
| Strict contract validation, dependency waves, concurrency cap, claim eligibility, effect identity, retries, wait scheduling, severity routing from a valid structured verdict, closure eligibility, and receipt construction | Deterministic code |
| Implementation, novel failure diagnosis after deterministic classification is exhausted, and independent review producing a structured verdict | Bounded model worker |
| Scope or authority conflict, override of a blocking invariant, irreversible external policy, or a requested Product/Runtime boundary change | Owner |

The owner-facing language is deliberately narrower than the internal state machine:

- **AI can continue** means an explicit authority rule and every deterministic gate authorize the
  next bounded effect;
- **Needs your decision** means a named rule reserves the decision for the owner, or authority rules
  are missing, conflicting, or ambiguous; and
- **Blocked by evidence/system** means neither a model nor the owner can legitimately skip the
  missing proof or unavailable dependency.

The renderer does not infer which label applies.

## Cross-Task Invariants / Interaction Safety

- **INV-DDO-1 — authority remains external.** Neither CKM, a compiled plan, epic-run JSON, a local
  checkpoint, nor a BuilderOps projection can by itself authorize a GitHub or repo effect.
- **INV-DDO-2 — approved scope is immutable.** An effect requires an approved initiation, the
  immutable compiled plan, the expected run version, and current live authority matching the plan.
  Scope change creates a superseding initiation; it never mutates a running plan in place.
- **INV-DDO-3 — compiler purity.** Compilation performs no claim, label, Project, branch, worktree,
  worker, PR, CI, merge, closure, BuilderOps transition, or CKM write.
- **INV-DDO-4 — no synthetic epic.** An exact explicit issue set is valid scope. Parent closure is
  attempted only when a real governed parent relationship and its acceptance contract exist.
- **INV-DDO-5 — independence eliminates coordination.** Independent workers exchange no messages.
  A discovered overlap emits a typed exception and recomputes the wave; it does not start informal
  cross-worker coordination.
- **INV-DDO-6 — effects are idempotent and fenced.** Every external effect has a stable identity,
  expected-state guard, read-before-write check, durable worker/run correlation, and reconciliation
  path. Duplicate delivery events produce one logical effect. Every non-start causal event must
  resolve its referenced effect or structured result, including the same PR and exact head, before
  it can authorize a later effect; a known-defect write additionally binds the exact registry
  reference and finding hash so distinct P2 dispositions cannot collapse into one effect identity.
  Success/failure events must carry the effect-specific post-effect authority state: a claim
  requires an actual transition from a pre-state containing `agent:ready` to a post-state without
  it, closures must observe the Issue closed, and non-mutating or failed effects cannot silently
  change the guarded Issue state.
- **INV-DDO-6a — authority is resolved, not frozen.** The immutable plan input is the origin
  authority state, not the state every later event must repeat. Structured worker and review result
  events bind the *resolved current* authority for their Issue: the plan input advanced by the
  events that legitimately move it — a truthful post-effect readback or an observed authority
  change bound to the same run and plan. A truthful post-claim result is therefore valid without
  attaching a stale pre-claim snapshot. Resolution is fail-closed: with no such proven event the
  plan input remains the resolved state, and an authority state the event log does not prove is
  rejected. A subjectless causal event — run start, elapsed timer, or recorded exception — may
  cause an effect, but because it carries no authority of its own its effect must bind the resolved
  current authority rather than assert one.
- **INV-DDO-7 — exact-head evidence.** CI, review, merge eligibility, and closure evidence bind the
  exact current PR head. New commits invalidate prior evidence. Each check evidence entry also binds
  a distinct check-run authority identity, so one reused check run can never be replayed under
  several required check names and satisfy the required-check set as false-green merge evidence.
- **INV-DDO-8 — severity routing is fail-closed.** P0/P1, protected risk, false-green evidence,
  malformed verdicts, and low-confidence verdicts block. A valid P2 is recorded once and deferred
  without synchronous repair. It becomes executable work only through the governed Issue path.
- **INV-DDO-9 — degraded control plane is honest.** Direct repo-authorized work may continue when
  BuilderOps is unavailable, but orchestration-gated claims, promotions, executor merges, and
  durable delivery effects wait rather than fabricating state.
- **INV-DDO-10 — CKM is not execution.** CKM may draft and display a compiler preview, but only a
  separately authenticated approval boundary may hand the immutable payload to the reducer.
  Direction B static HTML remains script-bounded and non-mutating.
- **INV-DDO-11 — TCD gains cannot hide defects.** Coordination reduction is accepted only when
  duplicate effects, escaped P0/P1 defects, current-SHA gate failures, repair rounds, and human
  recovery do not regress.
- **INV-DDO-12 — owner docs change at acceptance.** Child merges add validation receipts to the
  parent hub. Current-state owner docs are promoted only after the full capability acceptance gate.
- **INV-DDO-13 — preview precedes approval.** `DeliveryRequest.v1` and its explicit live planning
  snapshot compile without approval or effects. `DeliveryInitiation.v2` approves the exact request
  and preview hashes; drift produces a new preview rather than mutating approval.
- **INV-DDO-14 — workers are provider-neutral at the semantic boundary.** The reducer emits one
  canonical `worker-context-pack.v1` and `worker-invocation.v1`. Codex, Claude, or another bounded
  carrier may implement the same port, but provider sessions, prose, and process exit codes never
  become delivery authority.
- **INV-DDO-15 — lifecycle control is typed and fenced.** Pause, resume, cancel, and supersede are
  authenticated, idempotent commands bound to run/version/effect state. Cancellation does not claim
  to undo an already committed external effect, and supersession is a terminal receipt state.
- **INV-DDO-16 — live run state is not CKM truth.** `DeliveryRunView.v1` is a derived operational
  projection over the reducer/journal. CKM receives terminal evidence and reevaluation signals; the
  static cockpit neither polls nor mutates the run.
- **INV-DDO-17 — acceptance meaning is immutable.** Every approved run binds one versioned
  `DeliveryAcceptanceProfile.v1`. Reducer terminality follows that profile, while lower-level Issue,
  PR, CI, review, merge, and closure facts remain explicit and unchanged.

### Partial-failure paths

- A fast-lane worker discovers overlap: no other worker is contacted; the affected issue is paused,
  the overlap is recorded, and the next wave is deterministically recomputed.
- A claim succeeds but worker launch is ambiguous: reconcile the lease and durable invocation
  correlation. An unknown-start invocation may be reattached or deterministically read back. The
  same invocation/idempotency key may start only once: `not_started` permits its first start;
  terminal readback returns the recorded result and never launches again. A retry after a terminal
  failure requires a new reducer-authorized effect and invocation identity within the repair budget.
- A provider returns malformed review output: classify it as blocking; do not infer a severity.
- A valid P2 registry write is unavailable: preserve the review evidence and stop the terminal
  delivery transition that requires a durable P2 disposition. Preserve the failed effect's exact
  logical outcome keys and a live readback of the exact registry authority without claiming the
  absent success artifact; a reconciled write must observe that authority as recorded. Never emit a
  false clean receipt.
- An external effect times out: mark it unknown, read live GitHub/dispatcher state, and reconcile
  before retrying.
- BuilderOps is unavailable: ordinary manual repo work may continue under existing skills, but the
  automated run does not fabricate journal state or execute gated effects.
- CKM is unavailable: the CLI/API initiation path remains usable; delivery does not depend on the
  cockpit renderer.
- A pause or cancel arrives during an in-flight effect: persist the command, finish reconciling the
  unknown/committed effect, then stop before the next unauthorized effect.
- A child merges while the parent remains incomplete: record a child receipt and keep the parent
  open; no full-capability owner-doc promotion occurs.

## Implementation tasks and execution order

1. [Run Independent Issues Through a Fast Lane](RUN_INDEPENDENT_ISSUE_FAST_LANE.md) ([#4164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4164)) — delivered.
2. [Define Carrier-Neutral Delivery Contracts](DEFINE_CARRIER_NEUTRAL_DELIVERY_CONTRACTS.md) ([#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165)) —
   delivered contract seam.
3. [Compile Immutable Delivery Plans](COMPILE_IMMUTABLE_DELIVERY_PLANS.md) ([#4166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4166)) — delivered by
   [PR #4226](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4226).
4. [Advance Delivery Runs Deterministically](ADVANCE_DELIVERY_RUNS_DETERMINISTICALLY.md) ([#4167](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4167)) — depends
   on the delivered tasks 1 and 3; next serial implementation slice after this reconciliation.
5. [Bind Delivery Effects to BuilderOps Reconciliation](BIND_DELIVERY_EFFECTS_TO_BUILDEROPS_RECONCILIATION.md)
   ([#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168)) — depends on task 4 and reuses #3792.
6. [Connect CKM Initiation and Delivery Receipts](CONNECT_CKM_INITIATION_AND_DELIVERY_RECEIPTS.md) ([#4169](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4169)) —
   depends on tasks 2 and 5.
7. [Validate TCD and Recovery](VALIDATE_TCD_AND_RECOVERY.md) ([#4170](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4170)) — final pilot, failure proof,
   acceptance, and owner-doc promotion.

DDO-01 through DDO-03 are delivered. After this reconciliation is merged, the live #4167 body is
aligned to its exact task specification and strict readiness validation passes, #4167 is the only
Issue eligible to become `agent:ready`. #4168–#4170 remain serially dependency-blocked.

## Architecture reconciliation after DDO-03

The evidence-backed audit
[`BUILDER_DELIVERY_AGENT_OS_2026-07-28.md`](../audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md)
resolves the seam between the delivered contracts/compiler and the remaining runtime:

1. planning uses request → preview → exact approval; it never fabricates approval to show a
   preview;
2. DDO-04 defines the immutable acceptance-profile schema, and its reducer owns legal transitions
   and emits typed effects but performs none;
3. one provider-neutral worker port binds canonical context, invocation, effect identity, provider
   session, heartbeat/reattachment, and structured result;
4. BuilderOps owns durable execution, fencing, unknown-state reconciliation, active-run projection,
   and receipts without replacing GitHub/dispatcher authority;
5. the static CKM cockpit stays inert; a separate authenticated console/CLI owns approval and typed
   lifecycle controls; and
6. no external agent operating system is adopted wholesale. A durable carrier such as DBOS may be
   evaluated only after DDO-05 through a bounded conformance proof showing replay-safe start,
   unknown-start recovery, fencing, cancellation, and no second effect authority.

`DeliveryInitiation.v1`, `StructuredWorkerResult`, `DeliveryReceipt.v1`, and the delivered compiler
remain readable history. DDO-04 may add compatible versioned contracts, including
`DeliveryReceipt.v2`, but it must not silently reinterpret existing v1 bytes.

### Per-child TCD capability routing

These are non-binding pickup hints. `issue-to-code` re-derives the route from live risk and artifact
scope.

| Task | Cheapest acceptable capability | Rationale |
| --- | --- | --- |
| DDO-01 | Codex Terra / high | Multi-file delivery-workflow change with bounded tests and moderate coordination-policy risk. |
| DDO-02 | Codex Sol / high | Architecture and versioned contract seam whose mistakes would multiply across every later module. |
| DDO-03 | Codex Terra / high | Pure compiler with clear inputs and property tests, but non-trivial dependency and refusal semantics. |
| DDO-04 | Codex Sol / high | Explicit state machine spanning claims, workers, CI, review, merge, and closure. |
| DDO-05 | Codex Sol / xhigh | Data, concurrency, crash recovery, fencing, and external-effect reconciliation. |
| DDO-06 | Codex Sol / high | Authenticated external boundary plus CKM authority separation and cross-system integration. |
| DDO-07 | Codex Sol / high | Cross-system acceptance, fault injection, and quality/TCD non-regression judgment. |

## Pilot defaults

- maximum parallel workers: 2;
- pilot issue-set size: 4–8 strictly ready independent bugfix Issues;
- unattended merge and closure: allowed only for the low-risk pilot profile after every existing
  exact-SHA CI, independent review, verified-merge, and closure gate passes;
- P2: deferred evidence through the governed known-defect path, no synchronous repair/re-review;
- coordinator model use: initial plan/dispatch plus typed exception handling only;
- no worker-to-worker coordination without evidenced overlap; and
- stronger capability reserved for contract/state-machine design and risk review; isolated
  mechanical slices use the balanced default capability.

## TCD measurement

Every pilot receipt records:

- coordinator model turns and estimated coordinator tokens;
- worker starts by role and model tier;
- human interventions;
- deterministic transitions versus model-decided exceptions;
- CI wait cycles and wall time;
- review/repair rounds;
- duplicate claim, worker, PR, merge, or closure attempts;
- known P2 dispositions;
- escaped P0/P1 defects or false-green evidence; and
- total lead time from approved plan to terminal receipt.

Evidence-derived minima fail closed: an explicitly human-authored worker, review, recovery effect,
receipt, or merge cannot coexist with a lower `human_interventions` count.

Targets:

- fast lane: 50–70% fewer coordinator turns than a comparable recent issue-set run;
- thin reducer: at least 80% of coordination transitions deterministic;
- full kernel: 90–95% of coordination transitions deterministic;
- zero duplicate external effects; and
- no regression in existing CI, review, exact-head, merge, or closure gates.

The percentage targets are hypotheses. Failure to meet them produces evidence and a bounded
follow-up decision; it does not justify weakening quality gates.

## Capability acceptance

- [ ] Tasks DDO-01 through DDO-07 are delivered with exact child receipts.
  Verify: child/PR/merge ledger on the parent feature Issue.
- [ ] One 4–8 Issue fast-lane pilot demonstrates the immediate-value profile without synthetic epic
  or worker-to-worker coordination.
  Verify: `DeliveryReceipt.v2` pilot artifact linked from the parent.
- [ ] Compiler and reducer invariants pass pure, property, and production-call-site tests.
  Verify: the test targets named by DDO-02 through DDO-05.
- [ ] Crash injection before effect, after external effect, and before receipt converges without
  duplicate workers, merges, or closures.
  Verify: `tests/builderops/test_delivery_orchestration_recovery.py`.
- [ ] CKM can draft and preview initiation, an authenticated boundary can start the same immutable
  payload, and a receipt projects back without giving CKM delivery authority.
  Verify: `tests/builderops/ckm/test_delivery_bridge.py`.
- [ ] Measured coordination reaches the staged targets without quality regression.
  Verify: acceptance report and TCD ledger attached to the parent.
- [ ] Current-state Builder System and CKM owner docs are promoted only after the preceding
  acceptance evidence is complete.
  Verify: final owner-doc PR and post-merge receipts linked from the parent.

## Verification and acceptance path

Each child resolves its own `Verify:` targets, current-head CI, and independent review. Each merged
child posts a compact receipt to the parent validation hub. DDO-07 runs the live pilot and
fault-injection acceptance suite, evaluates TCD against the recorded baseline, closes or creates
bounded residual work, and triggers owner-doc promotion only when the capability is accepted.

## Relationship to GitHub Issues

| Role | Issue | Live lifecycle on 2026-07-28 |
| --- | --- | --- |
| Parent validation hub | [#4163](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4163) | `agent:blocked`; never a pickup Issue |
| DDO-01 independent-Issue fast lane | [#4164](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4164) | delivered and closed |
| DDO-02 carrier-neutral contracts | [#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165) | delivered by [PR #4176](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4176) and closed |
| DDO-03 plan compiler | [#4166](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4166) | delivered by [PR #4226](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4226) |
| DDO-04 reducer | [#4167](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4167) | next serial slice; remains blocked until this reconciliation is on `main` and strict readiness passes |
| DDO-05 BuilderOps binding | [#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168) | blocked on #4167; timing reconciles with #3793 |
| DDO-06 CKM bridge | [#4169](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4169) | blocked on #4168 |
| DDO-07 acceptance | [#4170](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4170) | blocked on #4167–#4169 |

The live Issues own executable state. This directory owns the stable decomposition and interaction
contract. PR [#4162](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4162) is the initial
specification publication.

## Source docs

- `AGENTS.md :: Total Cost of Development`
- `AGENTS.md :: Parallel-agent execution`
- `.codex/skills/deliver-issue-set/SKILL.md`
- `.codex/skills/issue-to-code/SKILL.md`
- `.codex/skills/verification-and-closure/SKILL.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/development/BUILDER_CONTROL_PLANE.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md`
