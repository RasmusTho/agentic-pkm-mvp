State: Specification (design + bounded slices). Advisory until child issues are delivered. Enacts owner ruling R4 (audit §IX, 2026-07-05): the runtime SHOULD support paid models (OpenAI and/or Anthropic); Fable 5 is NOT a runtime option; local Ollama stays the default/free tier. Second pass (2026-07-05 owner ruling): cloud egress is an **evolving graduated policy on an owner-declared trajectory** (§4) — capability-first now, tightening toward local-first as local models mature — NOT a fixed allowlist.
Doc role: Specification (capability design: runtime model posture + Anthropic provider)
Authority: Owns the R4 design. Subordinate to `docs/LLM_ROUTING.md` (router/fabric contract), `docs/LLM.md`, ADR-0023 (embedding egress), and the #2109 no-cross-provider-route invariant. The chat-egress consent scope is an owner ADR this spec requests, not one it enacts.
Owner: Architecture / product (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed — code citations current; design is proposal
Last reviewed: 2026-07-05

# Runtime Model Posture & Anthropic Provider (R4)

Current reality: runtime chat cognition knows four providers — `_KNOWN_PROVIDERS = {"mock",
"ollama", "openai", "deepseek"}` (`app/components/llm/router.py:41`) — with the execution ladder in
`app/llm/adapter.py:40-94` (`mock`/`ollama`/`openai`/`deepseek`; `openai` and `deepseek` both speak
the chat-completions shape). The embeddings side separately allowlists `{"mock","ollama","openai",
"deepseek","deterministic","gemini"}` (`app/components/embeddings/legacy.py :: _SUPPORTED_EMBED_PROVIDERS`). The model registry
(`docs/settings/models/registry.yaml`) carries OpenAI chat descriptors but nothing Anthropic.
**Anthropic is absent from every layer**, and — more importantly — the provider allowlist is
maintained independently at N sites. R4 makes paid models a routable tier; this spec designs it so
that adding a provider is a one-census change and so the paid tier is structurally incapable of
becoming a default.

## 1. Posture contract

```
Model tiers (runtime)
  free/local   ollama          — floor tier; the system is fully functional here at EVERY posture stage
  paid/cloud   openai, anthropic — reachable per the DECLARED EGRESS POSTURE (§4): how freely depends
                                   on the current stage; how it resolves is always compiled + deterministic
  never        fable-class     — no registry descriptor, no route, no env override reaches it
Authorization is orthogonal: the executing model NEVER changes what an output may do.
A paid model's output is the same proposal/clarification class as a local model's.
```

- **Declared-posture paid routing (deterministic at every stage).** A paid provider may be the
  resolved route only through the compiled routing policy (`vault/@Settings/llm_routing.md` →
  `runtime/settings/llm_routing.yaml`) **as bounded by the declared egress-posture stage (§4)**.
  What changes across stages is the *eligibility default* — under `capability-first` (now) paid
  routing is broadly available for human-invoked task kinds; under `local-first` it shrinks to
  per-invocation opt-in — never the discipline: routing stays declarative, compiled, and
  deterministic, so tightening is a config change, not a rebuild. Invariant at every stage: the
  raw env-default path (`LLM_PROVIDER`), the no-policy fallback path, and the degraded-fallback
  path never resolve to a paid provider — fallback for paid primaries is `mode: local` (Ollama)
  or `mock`, never another paid provider (no paid-to-paid cascades; one bill ceiling, not two).
- **Always-on loops are structurally local — at every posture stage.** Task kinds originating from
  tick/watcher/ingest/index (`decide` on watcher panels, relevance evaluation, embedding,
  classification at ingest) are marked `paid_eligible: false` in the census (§2); the routing
  compiler **rejects** a policy that assigns a paid model to a non-eligible task kind — fail at
  compile, not at 3 a.m. This is a stage-invariant floor (§4): no posture stage, including
  `capability-first`, makes an always-on loop cloud-routable. Which *human/operator-invoked* kinds
  are paid-eligible is derived from the declared stage — broad under `capability-first`
  (`qa`, `synthesis`, `curation.*`, planner/next-action, explicit eval runs), narrowing as the
  posture tightens.
- **Fable exclusion is registry-shaped, not prose.** No `anthropic.chat.claude_fable_*` descriptor
  may exist; the census marks the family excluded; an invariant test asserts (a) the registry
  contains no fable-class model, (b) `LLM_FORCE_MODEL` with a fable-class name still refuses (the
  adapter validates the model against the provider's descriptor family for paid providers).
- **Existing invariants carry over untouched:** deterministic routing, `require_compatible_identity`
  for embeddings, and the #2109 rule that the router never emits a route whose model belongs to a
  provider that will not execute it (`docs/LLM_ROUTING.md:48`). Anthropic slots into the same
  candidate machinery (`_route_candidates`, `router.py:264-312`) — no new routing semantics.

## 2. Provider-surface census (the cross-cutting slice, first)

Adding `anthropic` naively means editing string sets in ≥5 places and missing a sixth. Per the
cross-cutting-decomposition rule, the invariant ("the set of providers is defined once") gets its
own mechanism before the provider lands:

- A single census artifact `docs/settings/models/providers.yaml`: provider id, kind coverage
  (chat/embedding), tier (`local|paid|test`), `paid_eligible_task_kinds` policy hook, env vars
  required (`ANTHROPIC_API_KEY`…), excluded model families.
- Code keeps its local frozensets (no runtime YAML dependency in hot paths) but a **static test**
  asserts every allowlist in the codebase equals the census projection:
  `router.py:41 _KNOWN_PROVIDERS`, `app/components/embeddings/legacy.py :: _SUPPORTED_EMBED_PROVIDERS`,
  the `adapter.py` ladder branches, the registry compiler's accepted providers, health-check
  provider probes (`docs/LLM_ROUTING.md :: How to debug routing`), and `docs/LLM.md`'s documented
  set. Drift fails CI with the site named.

## 3. Anthropic chat provider (the wiring)

- **Adapter:** new `anthropic` branch in the execution layer speaking the Messages API
  (`POST {ANTHROPIC_BASE|https://api.anthropic.com}/v1/messages`, `x-api-key` +
  `anthropic-version` headers; `system` extracted from the messages list — the one shape difference
  from the chat-completions ladder; `max_tokens` mandatory, sourced from `LLM_MAX_TOKENS` with a
  sane default). Fail-loud on missing `ANTHROPIC_API_KEY` exactly like the `openai` branch
  (`adapter.py:62`). Same `log_llm_call` tracing; no streaming in slice 1 (the fabric callers are
  non-streaming today).
- **Registry:** descriptors `anthropic.chat.claude_opus_4_8`, `anthropic.chat.claude_sonnet_4_6`
  (ids follow the existing `provider.kind.model` convention; exact model names pinned at
  implementation time against the live API — do not trust this spec's memory of model names).
  `status: active`, tier `paid` per census.
- **Router:** add to `_KNOWN_PROVIDERS` (via census); no logic change — policy targets and
  fallbacks already resolve through the registry (`_resolve_target_model_id`, `router.py:92-102`).
- **Health:** provider probe (auth'd cheap call or key-presence + base reachability) surfaced in
  `checks.llm_providers.providers`; a configured-but-unkeyed paid route reports degraded at startup
  (matching the "configured and startup-safe" check posture).
- **No Anthropic embeddings:** Anthropic serves chat only; census marks kind coverage accordingly
  (guards a config class of error the compiler can reject).

## 4. Egress posture — an evolving graduated policy (owner ruling, 2026-07-05)

**The owner's frame, honored as designed:** today local hardware runs only very basic models, so
paid cloud is what makes the system *useful*, and privacy is not the pressing concern yet. At some
point capable local models arrive and privacy will matter more than marginal capability. The egress
design must therefore be **a policy on a trajectory, not a fixed allowlist**: default toward
capability now, with the tightening lever pre-built so that moving toward local-only is an owner
config/policy change — never a rebuild — and with every cloud egress receipted from day one so the
privacy lever has the audit trail it needs the day the owner pulls it.

### 4.1 The declared posture (one artifact, owner-writable)

A single declarative surface — `egress_posture` in the provider census
(`docs/settings/models/providers.yaml`), mirrored to a human-writable settings note
(`@Settings/model-posture.md`, per the settings-as-writable-surface posture) — declares exactly one
**stage**. The routing compiler derives paid-eligibility defaults from the stage; per-task-kind
policy can always be *stricter* than the stage, never looser (stricter-boundary-wins, same
composition rule as admissibility).

| Stage | Paid routing for human/operator-invoked kinds | Vault-content egress | Who benefits |
|---|---|---|---|
| **`capability-first`** (declared NOW) | permitted by default; policy may prefer paid for hard kinds (`qa`, `synthesis`, `curation.*`, planner) | permitted with the invoked task's context, receipted per call | usefulness while local models are weak |
| **`balanced`** | paid only for task kinds *named* in policy; local preferred wherever eval evidence shows parity | permitted for named kinds only | cost + growing privacy weight |
| **`local-first`** (least-egress) | local default everywhere; paid requires per-invocation explicit opt-in (a visible "use cloud for this" act) | opt-in per invocation, receipted | privacy once local capability suffices |

### 4.2 Stage-invariant floor (never relaxed, at any stage)

1. **Always-on loops never egress.** Tick/watcher/ingest/index task kinds are `paid_eligible: false`
   structurally (§1) — cost *and* pollution rationale; no stage overrides it.
2. **Every cloud egress is receipted.** Each paid call records provider, model, task kind, invoking
   surface, and correlation id in the existing cognition-metadata surface
   (`cognition_metadata.provider/model`, `docs/PANEL_AGENT.md:140-148`) plus an egress ledger entry
   (derived, rebuildable). The human can always answer "what has left this machine, when, for
   what?" — this is the pre-built privacy lever; it must exist *before* privacy is pressing, or
   the trajectory has no evidence base.
3. **Local-only remains sufficient.** No feature may hard-depend on a paid route: paid unavailable
   (no key, budget breach, `local-first` stage) ⇒ the local route serves, degraded legibly where
   quality differs. The system is fully functional — if worse — at every stage.
4. **Budget circuit breaker:** per-day token/request ledger for paid routes (derived, rebuildable).
   Breach ⇒ paid routes resolve to their local fallback with `degraded: true,
   reason: "budget-exhausted"` + a loud health signal. Never queue-for-later, never silent.
   Ceiling value = owner decision 4; plumbing is config.
5. **No paid-to-paid fallback; Fable exclusion; deterministic compiled routing** — as §1.

### 4.3 Trajectory triggers (what moves the stage — owner-enacted, evidence-named)

A stage shift is always an owner edit of the declared stage (+ a posture-change receipt); the
system never shifts itself. The *named triggers* below are the review prompts, so the trajectory is
governed rather than drifting:

- **Local-capability trigger** (→ tighten): the SV/EN eval battery (G3-2 lineage, extended with the
  paid-eligible task kinds) shows a local model within an owner-set quality margin of the paid
  route on the kinds actually used. Re-run the battery when a materially better Ollama-servable
  model lands — the eval harness, not vibes, is the tightening evidence.
- **Sensitivity trigger** (→ tighten, possibly per-scope): the vault gains content the owner marks
  sensitive, or the owner's privacy priority changes. Note: per-scope posture (e.g. `private`
  scope local-only while `work` stays capability-first) is a natural extension — the scope
  prefilter already runs before context assembly, so scope-conditional egress is enforceable;
  flagged as a `balanced`-stage refinement, not built now.
- **Cost trigger** (→ tighten): sustained budget-breaker trips or spend trend the owner rejects.
- **Capability trigger** (→ loosen, `local-first` → `balanced` only with explicit owner intent):
  a new task kind exists that local models cannot serve usefully.

### 4.4 What ratifies this

The requested owner ADR (README owner decision 3) is reshaped by this ruling: instead of a fixed
task-kind allowlist, it ratifies (a) this graduated posture model and its stage-invariant floor,
(b) the initial declared stage = `capability-first`, and (c) the trigger list above as the review
contract. Precedent: ADR-0023 declared the embedding-egress posture; this is its chat sibling,
generalized to a trajectory. Until that ADR lands, implementation slices may build the mechanism
with the stage compiled to the conservative default (`local-first` semantics — empty paid
eligibility), so plumbing never front-runs the owner.

## 5. Slices

1. **R4-1 Provider-surface census.** Delivered by #4287: `providers.yaml` + static
   census-equality tests across the sites in §2 + docs pointer from `docs/LLM.md`.
   `Verify:` `tests/settings/test_provider_census.py::test_all_allowlists_match_census` (one test,
   parameterized per site). Deps: none. **Sonnet.**
2. **R4-2 Anthropic chat provider.** Adapter branch + registry descriptors + census row + health
   probe + `docs/LLM.md`/`docs/LLM_ROUTING.md` env-var documentation (bundled, not follow-up).
   `Verify:` `tests/llm/test_anthropic_adapter.py` (mocked transport: message-shape mapping, system
   extraction, missing-key fail-loud, max_tokens present),
   `tests/components/llm/test_router.py` extension for the new provider. Deps: R4-1. **Opus**
   (auth/provider surface).
3. **R4-3 Graduated egress-posture compiler + budget breaker.** The declared-stage artifact
   (census + settings-note mirror) → compiled paid-eligibility defaults per §4.1;
   stricter-boundary-wins composition with per-kind policy; stage-invariant floor enforcement
   (always-on rejection at compile; no-paid-on-default-path; no paid-to-paid); egress ledger +
   per-call egress receipts; budget ledger + degrade-to-local; posture-change receipts; health
   surfacing of current stage.
   `Verify:` `tests/components/llm/test_egress_posture.py` (each stage compiles to its documented
   eligibility set; per-kind policy can only tighten; stage change requires no code change —
   asserted by driving all three stages through config in one test; posture-change receipt
   emitted), `tests/components/llm/test_paid_tier_policy.py` (default path never paid; always-on
   kind + paid policy ⇒ compile error at every stage; breaker ⇒ local + degraded reason),
   `tests/invariants/test_model_posture_invariants.py`. Deps: R4-2; the posture ADR for the
   *declared* stage (plumbing lands with the conservative `local-first`-equivalent default first).
   **Opus** (routing/authority).
4. **R4-4 Fable-exclusion probe.** Registry scan + forced-override refusal test.
   `Verify:` `tests/invariants/test_model_posture_invariants.py::test_runtime_never_serves_fable`.
   Deps: R4-2. **Sonnet.**

## 6. Fitness invariants (registry candidates)

### paid_route_follows_declared_posture
- **Purpose:** No paid provider is the resolved route except through the compiled routing policy as
  bounded by the single declared egress-posture stage; env defaults, missing policy, and fallback
  paths resolve local/mock only at every stage; per-kind policy composes stricter-only with the
  stage.
- **Expected failure mode:** `LLM_PROVIDER=openai` (or a future default) silently making every task
  a billed cloud call; or a second, drifting posture declaration appearing somewhere else in config.
- **Test path:** `tests/invariants/test_model_posture_invariants.py::test_paid_follows_declared_posture`.

### cloud_egress_always_receipted
- **Purpose:** Every paid/cloud chat call produces an egress record (provider, model, task kind,
  invoking surface, correlation id) in the cognition-metadata surface and the egress ledger — at
  every posture stage, including `capability-first`. The privacy lever's evidence base exists
  before privacy is pressing.
- **Expected failure mode:** a new call site bypasses the ledger; months later the owner tightens
  the posture and cannot audit what historically left the machine.
- **Test path:** `tests/invariants/test_model_posture_invariants.py::test_cloud_egress_receipted`.

### posture_tightening_is_config_only
- **Purpose:** Moving the declared stage toward local-first (capability-first → balanced →
  local-first) requires only the declared-posture edit — no code change, no redeploy of new code —
  and takes effect at the next policy compile; a posture-change receipt is emitted.
- **Expected failure mode:** eligibility values hard-coded at call sites make tightening a
  refactor, so it never happens (the trajectory silently dies).
- **Test path:** `tests/invariants/test_model_posture_invariants.py::test_tightening_is_config_only`.

### local_only_remains_sufficient
- **Purpose:** With zero paid keys/eligibility (the `local-first` extreme), every runtime feature
  still functions on local routes, degraded legibly where quality differs; no feature hard-fails
  for lack of a paid provider.
- **Test path:** `tests/invariants/test_model_posture_invariants.py::test_local_only_sufficient`.

### paid_unreachable_from_always_on_tasks
- **Purpose:** Task kinds fired by tick/watcher/ingest cannot resolve to a paid provider even when a
  policy tries to assign one — the routing compiler rejects the assignment.
- **Expected failure mode:** a well-meaning settings edit routes the relevance tick to Opus and the
  always-on loop bills continuously.
- **Test path:** `tests/invariants/test_model_posture_invariants.py::test_paid_unreachable_always_on`.

### runtime_router_never_serves_fable
- **Purpose:** No registry descriptor, task policy, or force-override resolves a runtime route to a
  Fable-class model (R4: Fable is builder/design-time only and is not a runtime option).
- **Test path:** `tests/invariants/test_model_posture_invariants.py::test_runtime_never_serves_fable`.

### provider_surface_census_single_source
- **Purpose:** Every provider allowlist in the codebase equals the census projection; adding or
  removing a provider anywhere else fails CI naming the drifted site.
- **Test path:** `tests/settings/test_provider_census.py::test_all_allowlists_match_census`.

### paid_budget_breaker_fails_local_and_loud
- **Purpose:** Budget exhaustion degrades paid routes to their local fallback with a visible
  degraded reason and health signal — never a silent continue-billing and never a silent quality
  drop without signal.
- **Test path:** `tests/invariants/test_model_posture_invariants.py::test_budget_breaker_local_loud`.

## 7. Rejected alternatives

- **Anthropic via an OpenAI-compatible proxy/base-URL shim:** rejected — hides the provider identity
  from routing/receipts, breaks the census, and conflicts with the #2109 posture that provider
  strings mean the executor.
- **Per-call human approval for paid execution:** rejected — conflates cost control with authority
  (the #1881 ladder governs *effects*, not compute spend); the budget breaker + explicit policy +
  receipts is the proportional control.
- **A generic "cloud" tier flag on task intents:** rejected — tier lives on the model descriptor +
  census; intents stay provider-agnostic so routing remains deterministic and settings-driven.
- **A fixed egress allowlist (this spec's own first draft):** superseded by the 2026-07-05 owner
  ruling — a static allowlist encodes today's local-model weakness as permanent policy and makes
  every future tightening an ADR + code negotiation. The graduated posture keeps the same
  deterministic enforcement while making the trajectory a first-class, one-edit lever.
- **Automatic stage shifting (system tightens itself on eval evidence):** rejected — the posture is
  an owner value judgment (capability vs privacy vs cost); the system supplies evidence and review
  prompts, never enacts the shift (agents propose, human disposes — applied to policy itself).
