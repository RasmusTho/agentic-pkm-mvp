State: Advisory design position, 2026-07-27. Evidence baseline: worktree `claude/reverent-kilby-ffb5fb` off `origin/main` at `ae37a7a49`, plus read-only inspection of the configured inquiry host. No implementation, no Issue, no PR is authorized by this document. It requests exactly one owner ruling (§7). Corrected 2026-07-27 after ratification: this document originally stated that HSP-02 was open. It was delivered on 2026-07-20 (#3846 / PR #4008); the error was inherited from a stale task-order row in `docs/LOCAL_SECRET_PROVISIONING/README.md`, corrected in the same change. Migration step 2 therefore extends a shipped mechanism and is independent of open parent #3843.
Doc role: Reference (architecture design position — pre-ADR)
Authority: Evidence-based analysis and a recommendation only. `docs/adr/ADR-0063-shared-llm-contract-kernel.md` remains authoritative for the Product/Builder contract seam; `docs/LLM_ROUTING.md` for current Product routing; ADR-0062 for Builder credential/process separation; `docs/LOCAL_SECRET_PROVISIONING/` for the host secret boundary. Owner docs win on disagreement.
Owner: Architecture spine / LLM boundary
Temporal class: Point-in-time design position; supersede by the ADR it requests.
Source of truth: Current behavior remains in code and the owner docs cited inline. This document adds no shipped claim.

# Model access substrate — design position

## The answer

**ADR-0063 already settled the seam. It deliberately did not settle credentials, and that is the
only part actually broken.** Its own audit says so in as many words: a "common credential plane …
would require a new ADR/SBS stewardship pass. None is proposed here"
(`docs/audits/LLM_RUNTIME_COORDINATION_2026-07-17.md:384-386`).

So the recommendation is **not** a new abstraction. It is:

1. **Add the missing layer** — a provider-neutral *credential and session resolution* contract —
   as ADR-0064 extending ADR-0063, not reopening it.
2. **Promote the seam that already works** — `ModelTurnAdapter`
   (`app/builderops/model_inquiry_adapters.py:72-82`), already proven against two structurally
   different transports (HTTP JSON and subprocess/stdin) — into the kernel as the execution-adapter
   contract, instead of designing a third one.
3. **Deliver the census that already exists on paper** — `providers.yaml`
   (`docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md:66-76`), fully specified,
   zero delivered — so "the set of providers is defined once" becomes a CI-enforced fact.

Everything else the owner asked about (intent without a provider name, TCD routing, failure policy)
is **already designed and unenforced**. The gap is delivery and ownership, not design.

One thing genuinely needs the owner: **what the default programmatic auth path is** (§7).

---

## 1. What the evidence changes about the stated premise

Three corrections, each material to the design.

**1.1 The Anthropic path is not broken — it has a bespoke bridge the Codex path lacks.**
The configured inquiry host runs `local.yggdrasil.claude-proxy` (loaded, PID present): a hand-written
`ThreadingHTTPServer` on `0.0.0.0:8743` under `~/.local/lib/yggdrasil-claude-proxy/`, TLS 1.2+ with
a pinned cert, bearer token from `~/.config/yggdrasil-claude-proxy/client-token`, a strict argv
allowlist, then `subprocess.run([~/.local/bin/claude, *argv])`. It runs in the **GUI login session**
via LaunchAgent, which is why an SSH child can reach Claude at all.

There is no Codex analogue. That is the entire difference between the two providers' headless
behavior. The failure is therefore not "keyring is the wrong posture" — it is **one provider
received a hand-built session bridge and the other did not, and neither bridge is in Git.**

This reframes the design: the missing layer is a **session broker**, and the proxy already *is* that
broker — built once, by hand, for one provider, outside version control. Generalizing it from one
provider to N is the work.

**1.2 The credential substrate already exists — with one non-model secret in it.**
`config/secrets/host_secret_contract.json` declares Keychain service `yggdrasil.host-secrets`,
account template `{channel}:{consumer}:{secret}`, channels `dev|test|prod`. Resolution is
`security find-generic-password` at `app/ops/host_secret_bootstrap.py:72-97`, fail-loud with a
value-free message, materialized as a mode-0600 temp env file. This is the only code in the
repository that treats a credential as a first-class, channel-scoped, contract-declared artifact.

The only declared secret is `heimdal.raw-store-key`. `app/ops/host_secret_contract.py:17-19`
hard-codes that allowlist, so adding a model provider is a code change, not a JSON edit. And
`docs/LOCAL_SECRET_PROVISIONING/README.md:105` writes *"runtime model-provider enablement"*
explicitly **out of scope**.

**1.3 Three specifications each push model credentials into another's out-of-scope.**

| Spec | Owns | Explicitly excludes |
|---|---|---|
| ADR-0063 (Accepted) | contract kernel, fallback vocabulary, mappers | credentials, provider sessions, host processes (`:87-89`) |
| LOCAL_SECRET_PROVISIONING (both children delivered; parent #3843 open for a receipt only) | Keychain substrate, channel isolation, fail-closed | runtime model-provider enablement (`:105`) |
| RUNTIME_MODEL_POSTURE (0 % delivered) | provider census, Anthropic provider, graduated egress posture | — but was never decomposed into Issues |

Model credentials fall between all three. Nobody owns the seam. That is the actual defect.

---

## 2. Current state

### 2.1 Nine model-access mechanisms that do not talk to each other

**Product runtime — six parallel abstractions plus three unrelated selectors.**

| # | Abstraction | Entry | Providers |
|---|---|---|---|
| A1 | LLM fabric (canonical) | `app/components/llm/fabric.py:39` → `router.py:133` → `app/services/llm.py:311` | mock, ollama, openai, deepseek |
| A2 | Constrained completion (on A1) | `app/components/llm/constrained.py:138` | inherits A1 |
| A3 | `ReasoningFacade` (router-backed) | `app/components/reasoning/facade.py:174` | inherits A1 |
| A4 | `ReasoningFacade` (**same class name, same factory name**, different class) | `app/reasoning/facade.py:135` | inherits A5 |
| A5 | Deliberation-agent provider | `app/reasoning/provider.py:134,186` | mock, ollama |
| A6 | Embedding stack (separate identity system) | `app/components/embeddings/legacy.py:257` → `app/llm/embeddings.py:377` | mock, ollama, gemini, deterministic |

Plus reranking (`app/retrieval/rerank/provider.py:187`), TTS (`app/tts/providers.py:40`), STT
(`app/media/transcribe.py:74`) — each with its own selector, sharing nothing. Plus one **dead**
full HTTP client, `app/llm/adapter.py`, with no importer anywhere in `app/`.

The A3/A4 collision is the sharpest hazard: six `app/agents/**` modules import
`get_reasoning_facade` from `app.components.reasoning`, while `app/chat/coauthoring_cognition.py:35`,
`app/chat/read_only_cognition.py:13`, and `app/api/routes/canvas.py:43` import the identically-named
symbol from `app.reasoning.facade`. Different classes, different methods, different routing.

**Builder — five non-communicating selection mechanisms.**

| # | Mechanism | Anchor | Enforced? |
|---|---|---|---|
| B1 | Prose TCD policy, two vendor ladders | `AGENTS.md:114-196` | No schema, no test. `tcd_plan`/`tcd_review` have zero hits in `schemas/`, `tests/`, `app/`, `scripts/` |
| B2 | Free-text model hints in Issue bodies | `.codex/skills/feature-breakdown/SKILL.md:244` | Explicitly non-binding; re-derived downstream |
| B3 | Hardcoded launcher constants | `app/dispatcher/verification_consumer.py:2325-2341`; `scripts/model_inquiry_subscription_adapter.py:16-17` | Exact string equality |
| B4 | `BUILDEROPS_INQUIRY_ADAPTERS_JSON` | `app/builderops/model_inquiry_adapters.py:22` | The only provider-neutral surface — **host-only, uncommitted** |
| B5 | Advisory tier recommender | `app/builderops/epic_run_context_budget.py:436-444` | The only executable routing function; **nothing consumes it** |

B3 is the clearest illustration of the problem the owner named. `verification_consumer.py:2325-2332`
reads `.codex/agents/verification-closer.toml`, then asserts exact equality against an inline dict
containing `"model": "gpt-5.6-terra"` — and then at `:2338-2341` builds `LaunchConfig` from the
**hardcoded literals, not the parsed TOML**. The TOML is a checksum of the Python constant, not its
source. The model id must be edited in two places, in lockstep, forever.

`scripts/model_inquiry_subscription_adapter.py:20-52` is the same pattern in argv form: an
`if role == "fable" / elif "gpt_codex"` with two entirely different command shapes, hardcoded
`claude-fable-5` / `gpt-5.6-sol`, and a genuine capability asymmetry handled by hand — the strict
schema prompt goes via `--system-prompt` for Claude but is prepended into the user prompt for Codex,
because `codex exec` has no system-prompt flag (`:76-77`).

Vocabulary is not normalized anywhere: skills say "Opus/xhigh-tier" and "Sonnet-tier"
(`architecture-research/SKILL.md:127,130`), `epic_run_context_budget.py` says `sol|terra|luna`,
`.codex/agents/*.toml` says concrete model ids. Nothing maps between them mechanically.

### 2.2 Twelve credential paths, two substrates that share nothing

| Provider family | Substrate | Headless? | Reboot? | Tool update? | In Git? |
|---|---|---|---|---|---|
| Anthropic (Builder) | `~/.claude/.credentials.json` (0600, **on disk, not Keychain**) behind the TLS proxy in the GUI session | Yes — that is the proxy's purpose | Only after GUI login | **Fragile** — `~/.local/bin/claude` is a version-pinned symlink to `versions/2.1.220`; a moved version dir breaks the proxy's `CLAUDE_PATH`, and the argv allowlist pins CLI flag names | No |
| OpenAI/Codex (Builder) | macOS login Keychain (`cli_auth_credentials_store = "keyring"`, no `auth.json`) | **No bridge exists** — this is the reported failure | Requires the login keychain unlocked | Robust — `codex` resolves through `packages/standalone/current` | No |
| OpenAI / DeepSeek / Gemini (Product) | plain process env | Yes where env is set | env-dependent | Stable | Values no; names yes |
| `heimdal.raw-store-key` | Keychain, contract-declared, channel-scoped | Same unlock caveat | Keychain persists | Stable | **Contract yes, value no** |

Failure semantics are already uniform in exactly one place and nowhere else: BuilderOps model turns
fail **closed** with receipts (`app/builderops/model_inquiry_runner.py:131-141`); embedding fallback
fails **silent** (`app/llm/fallback_orchestrator.py:41-42` returns `NO_KEY` and simply does not fall
back); CI fails **green** (`.github/workflows/ci-smoke.yaml:518-528` and
`.github/workflows/architecture-ci.yaml:110-118` both skip silently and report success).

No workflow references `ANTHROPIC_API_KEY`. CI never reaches Anthropic, and never reaches Codex
except through the host consumer.

---

## 3. The seam

### 3.1 What the substrate owns

- **Provider and model resolution** from a declared intent (§4) against the census.
- **Credential and session acquisition** — the new part. One contract, `resolve(channel, consumer,
  provider) -> authenticated channel`, with two backends: a declared secret (Keychain →
  process-local env, the HSP-01/02 mechanism) and a brokered subscription session (the generalized
  proxy). The caller never learns which.
- **Execution transport** behind one protocol — `ModelTurnAdapter`
  (`app/builderops/model_inquiry_adapters.py:72-82`): `adapter_id`, `provider`, `model`,
  `execute(request) -> AdapterResult`.
- **Failure classification** — one closed vocabulary. The seven-class Builder set
  (`model_inquiry_adapters.py:26-36`) with its double validation at the persistence boundary
  (`app/builderops/model_inquiry.py:2049-2068`) is the right starting shape; it needs auth-specific
  members (`credential_unavailable`, `session_expired`) that today collapse into
  `command_exit_nonzero` — which is exactly why the reported failure was uninformative.
- **Capability negotiation** — does this provider/model support constrained decoding, native tool
  calls, a system-prompt channel, embedding dimension N? Today these are discovered by breaking.
- **Provenance** — provider, model, request id, effective identity, degraded state.

### 3.2 What it deliberately does not own

- **Policy authority.** ADR-0063 holds: Product policy stays Product, Builder policy stays Builder.
  The substrate resolves; it never decides *whether* a task may use a paid provider — that is the
  egress posture (`RUNTIME_MODEL_POSTURE.md:96-134`).
- **Two registries.** Shared descriptor schema, separate mutable registries, no automatic sync
  (ADR-0063 `:118-130`).
- **The fallback decision.** It is contract data on the request, not substrate behavior (§6).
- **Prompts, task taxonomy, receipts, stores.** Unchanged owners.
- **Local, credential-free model paths.** TTS, STT, and reranking stay outside. They have no
  credential, no provider identity worth unifying, and a different lifecycle. Folding them in adds
  surface for nothing.

---

## 4. Expressing intent without naming a provider

The neutral intent shape **already exists on the Product side** and has no Builder equivalent.
`LLMTaskIntent` (`app/components/llm/router.py:14-33`) carries task kind, complexity, risk, budget,
determinism, schema requirement, and latency. The Builder side has hardcoded `role -> argv`.

The proposal is one intent shape used by both, resolved through the census:

```
intent = {
  capability_tier:   economy | standard | frontier      # neutral, vendor-free
  reasoning_effort:  minimal | low | medium | high | xhigh
  determinism_required: bool
  output_schema_ref: <schema id | null>                 # a capability requirement, not a hint
  independence:      none | distinct_effective_target   # for adversarial review
  fallback_requirement: <one of ADR-0063's five values>
  side_effect_class: <declared>
}
```

The census (`providers.yaml`) resolves `capability_tier -> (provider, model)` **at config time**,
per runtime, per channel. Nothing in code names a provider.

This maps onto `AGENTS.md :: Total Cost of Development` without changing the policy: the two ladders
in `AGENTS.md:136-140` and `:142-149` are already the same three rungs with different labels —
Haiku/Luna, Sonnet/Terra, Opus/Sol — and `AGENTS.md:142` already instructs agents to *"resolve the
tier to the current generation's model id at config time"*, which is precisely a census lookup
described in prose. `epic_run_context_budget.py:436-444` already computes exactly this and is
already validated against `{"luna","terra","sol"}` at `:268-269`. Three surfaces are independently
expressing one idea; the census is where it becomes one.

The gain is concrete: TCD stops being prose an agent must read and remember, and becomes a value
carried on the request, recorded in the receipt, and checkable. Model-name churn (`gpt-5.4` →
`gpt-5.6-sol`) becomes a census edit instead of a code search.

---

## 5. Credentials across laptop, host, channels, and CI

One contract, four bindings, no new machinery:

| Surface | Binding | Notes |
|---|---|---|
| Laptop (dev) | Keychain via `host_secret_contract.json`, channel `dev` | Mechanism already delivered end to end (HSP-01 contract + HSP-02 bootstrap). Needs the model-provider identifiers added and `host_secret_contract.py:17-19`'s hardcoded allowlist made data |
| Inquiry host | Same contract, channels `test`/`prod`, plus the **brokered session** backend for subscription paths | The proxy generalized: one local service, N providers, in Git, values still host-only |
| dev/test/prod channels | The contract's `channel` dimension — already isolated and tested (INV-HSP-2) | No new isolation model |
| CI | Declared secret backend only, via GitHub Actions secrets, resolved through the same contract | Subscription sessions are **structurally impossible** in CI. This is not a limitation to engineer around; it is the reason §7 exists |

The headless case that breaks today is fixed in one of two ways, depending on §7: a declared secret
(no session at all) or an explicit broker request to the GUI-session service (the proxy, generalized).
Both go through the same call. The caller does not branch.

**Fail-closed is inherited, not invented**: a missing or malformed secret prevents the process from
starting and names only the logical identifier (INV-HSP-1/3,
`docs/LOCAL_SECRET_PROVISIONING/README.md:70-78`). The current silent paths —
`fallback_orchestrator.py:41-42` and both CI workflows — become contract violations rather than
accepted behavior.

---

## 6. Provider failure: who decides

**Nobody decides today; five call sites each decide separately.** Fail-loud is enforced at
`app/services/llm.py:400-458` ("refusing to substitute a deterministic response") and then
re-softened independently at `app/agents/ask/utils.py:153-154` (bare `except Exception: return None`),
`app/components/reasoning/facade.py:493` (confidence < 0.7 → silent heuristic),
`app/retrieval/rerank/provider.py:161-162` (unreachable service → token-overlap scoring, silently,
inside ASK), `app/llm/embeddings.py:488-502` (failing note → zero vector in the index),
`app/chat/read_only_cognition.py:86-98` (canned plan). And the router itself silently appends a
`mock` fallback candidate at `router.py:368-377`, so a real provider outage can route to
deterministic mock text.

**No new vocabulary is needed.** ADR-0063 `:104-116` already fixed five values, and they are
sufficient:

| Requirement | Who declares it | Who selects within it | Owner involvement |
|---|---|---|---|
| `fallback_forbidden` | Builder model inquiry; CKM decisions | — | none |
| `fallback_same_identity` | transport retry | owning runtime | none |
| `fallback_compatible_identity` | embeddings (ADR-0023/0052 discipline) | Product policy | none |
| `fallback_policy_selected` | Product chat/reasoning | Product policy, bounded by egress stage | posture stage only |
| `human_decision_required` | reserved | — | per-decision |

**The rule: the caller declares the requirement, the owning runtime's policy selects within it, the
substrate never decides.** The owner's only involvement is the declared egress-posture stage
(`RUNTIME_MODEL_POSTURE.md:96-134`), which is one edit, not a per-call approval — and
`RUNTIME_MODEL_POSTURE.md:255-258` already rejected per-call human approval for the right reason:
it conflates cost control with authority.

The one change worth making beyond ADR-0063: **degrading must be visible.** Every one of the five
call sites above degrades without an operator signal. `degraded: true` plus a reason belongs on the
result, and the silent-degrade paths become defects.

---

## 7. The owner decision — RULED 2026-07-27

> **Owner ruling, 2026-07-27: Option A.** Declared API keys are the default programmatic auth path.
> Subscription CLI sessions remain for interactive human-driven work and must not be a dependency of
> any headless path. The brokered-session backend (Option B) stays a permitted second backend behind
> the same contract, to be built only if a specific provider forces it — it is not built now.
>
> Ratified in `docs/adr/ADR-0064-model-access-substrate.md`.

The analysis that produced the ruling follows.


**Problem.** Programmatic model access needs a credential that works with no human present — over
SSH, under launchd, in CI. Subscription sessions are designed for an interactive human at a GUI
login. Every attempt to make one headless has produced a bespoke, host-only bridge: one exists for
Anthropic (the TLS proxy), none for Codex, and that is exactly the reported failure. This is at
least the second keychain-over-SSH incident in this system.

The substrate supports both backends either way. The decision is **which one is the default for
programmatic access**, because that determines how much bridge machinery gets built and maintained.

### Option A — Declared API keys are the default; subscriptions stay interactive-only

Programmatic paths (model inquiry, verification closer, CKM, CI) resolve an API key through the
Keychain contract. Subscription CLIs remain for human-driven interactive work.

- The headless problem disappears rather than being bridged. No keychain-over-SSH, ever.
- CI can reach providers for the first time. The two silent-green workflows become real.
- A new provider costs a census row and a secret declaration — no new bridge.
- The TLS proxy and the version-pinned `claude` symlink dependency are deleted.
- **Cost: metered API billing on top of the x5 Codex and x5 Claude subscriptions already paid for.**
  Model inquiry runs both roles at `xhigh` over multiple adversarial rounds; if CKM orchestrates
  system-wide development, volume is not incidental. This is the real price.

### Option B — Generalize the proxy; brokered subscription sessions stay the default

One in-Git local broker service replaces the hand-built proxy, serving N providers from the GUI
login session.

- Zero marginal model cost. The subscriptions are already paid.
- The proxy's ~50-line argv allowlist stops being a second, uncommitted copy of
  `scripts/model_inquiry_subscription_adapter.py:20-52`.
- **CI still cannot reach any provider** — a GUI login session cannot exist there. The silent-green
  workflows stay silent-green.
- Every new provider needs broker support for its CLI's session model, and stays exposed to CLI
  flag and version-layout churn. The failure class the owner asked to stop patching survives, just
  in one place instead of several.

### Option C — Both, with the substrate choosing per consumer

Declared key where present, brokered session otherwise.

- Most capable; cheapest at the margin where subscriptions suffice; CI works where keys exist.
- Two backends to build, test, and keep honest, and a resolution-order rule to reason about
  whenever a call behaves unexpectedly. Highest machinery for a single-operator system.

### Recommendation — **A**, with B's broker built only if a specific provider forces it

Reasons, in order:

1. **TCD.** `AGENTS.md:122` puts human time at 100 USD/hour and budget pressure at medium-low. Two
   incidents of this class have already cost owner time. API spend that removes the class outright
   is cheap against that; the recurrence is the expensive term.
2. **CI is not optional if CKM orchestrates development.** An orchestrator whose model access
   cannot run in CI, and whose CI reports green when unconfigured, cannot be trusted to gate work.
   Option B cannot fix that.
3. **It matches where the code already is.** `HttpModelAdapter`
   (`model_inquiry_adapters.py:175-278`) is fully implemented for both Anthropic and OpenAI,
   including credential-leak scrubbing on output *and* on the returned request id (`:227-232`,
   `:271-277`). It is maintained and unexercised. Option A switches a config value; Option B builds
   a new service.
4. **Cost is bounded and measurable before committing.** The egress ledger and budget circuit
   breaker are already specified (`RUNTIME_MODEL_POSTURE.md:120-127`). Land those first and the
   spend question becomes an observation instead of a bet.

The honest counter: if metered spend at inquiry/orchestration volume turns out unacceptable, B is
the fallback and nothing in this design forecloses it — the broker becomes a second backend behind
the same contract. That is the argument for the substrate regardless of which default wins.

---

## 8. Migration

Additive throughout. Nothing changes behavior until step 4, and each step is independently
mergeable.

| # | Step | Touches | Exit |
|---|---|---|---|
| 1 | **Provider census** — `docs/settings/models/providers.yaml` + the static equality test across every allowlist site | new file, one test | `tests/settings/test_provider_census.py` green; `router.py:42`, `legacy.py:21`, `PROVIDER_REGISTRY`, health probes and docs all equal the census. R4-1, already specified |
| 2 | **Credential contract extension** — model-provider identifiers in `host_secret_contract.json`; `host_secret_contract.py:17-19`'s hardcoded allowlist becomes data | `app/ops/**`, `config/secrets/` | Existing INV-HSP-1/2/3 tests extended to a model secret. Extends the delivered HSP-01/HSP-02 mechanism; independent of open parent #3843 |
| 3 | **Adapter contract promotion** — `ModelTurnAdapter` moves into the neutral kernel; auth-specific failure classes added | `app/builderops/model_inquiry_adapters.py` and kernel | Existing `tests/builderops/test_model_inquiry_adapters.py` green through the new location |
| 4 | **First beneficiary: model inquiry** — `BUILDEROPS_INQUIRY_ADAPTERS_JSON` resolves through the credential contract | host config + launcher | A model inquiry completes over a fresh non-interactive SSH. This is the reported failure, fixed as a consequence rather than a patch |
| 5 | **CKM** — replace `FabricSemanticAssociator` with a Builder-side adapter | `app/builderops/ckm/semantic.py` | `tests/builderops/ckm/test_semantic.py` green plus a negative test that Product fallback cannot execute the Builder task. ADR-0063 M4 |
| 6 | **Verification closer** — model/effort resolve from the census instead of duplicated literals | `verification_consumer.py:2325-2341` | Adapter TOML becomes the source, not a checksum |
| 7 | **Product, opportunistically** | `app/components/llm/**` and callers | Census test blocks *new* drift from day one; existing sites migrate behind it |

**What stays put.** TTS, STT, reranking (local, credential-free). Product embedding identity and its
reconciliation discipline (ADR-0023/0052). Product task-kind taxonomy and `ReasoningFacade`
(ADR-0063 `:213`). The two registries stay two.

### 8.1 CKM's position in the order has moved — and the interim window must be named

> **SUPERSEDED 2026-07-27 by ADR-0057 A1 and ADR-0064 §8. Do not act on this subsection.** It was
> written while it was undecided whether CKM might orchestrate. The owner has since ruled that
> delivery may be orchestrated from the CKM by a builder agent. Three statements below are withdrawn:
> the interim condition "CKM does not orchestrate during the window", the conditional swap of
> migration steps 4 and 5, and the claim that orchestration needs its own future amendment (it has
> one). **The migration order does not swap — CKM stays at step 5.** The surviving reasoning is the
> importlinter visibility rule, which is not yet implemented and is scheduled into step 1. Read
> ADR-0064 §8 for the current text.

ADR-0063 sequenced CKM's migration as M4 transition debt, to happen *"only after the Builder runtime
and compatibility contract exist"* (`:179-180`). **That ordering was written when CKM was a small
peripheral consumer, and it is now backwards.** The owner's framing makes CKM the heaviest caller in
the Builder System, so the debt is no longer in a corner that can wait for a runtime to be built
around it — it sits on the main path.

Today CKM's only model path is `get_chat_client(LLMTaskIntent(task_kind="classify", …))` through the
**Product** router (`app/builderops/ckm/semantic.py:32,116-136`), rejecting `mock` only *after*
routing has already constructed policy-defined fallback candidates (`router.py:307-378`).
`importlinter.ini` does not catch it: `app.builderops` and `app.llm` are both in the same
layered-independence list, and `app.components.llm` is a different package from `app.llm`.

An orchestrator that can silently resolve to a mock route cannot be an orchestrator.

**Position: CKM migrates as early as its dependencies allow — step 5, not last.** It needs only
steps 2 and 3 (credential resolution and the adapter contract), not a complete Builder Capability
Runtime. It is placed after step 4 because model inquiry is the smaller, already-adapter-shaped
consumer that proves the substrate cheaply; that is a sequencing preference, not a dependency. If
CKM orchestration starts before step 4 lands, steps 4 and 5 swap.

**The interim window is accepted risk and must be stated, not discovered.** Through steps 1–4, CKM
continues to route Builder inference through Product policy and vault-compiled settings. That is
precisely the authority leakage ADR-0063 rejected Option A to prevent. Two conditions make it
tolerable, and both must hold:

1. **CKM does not orchestrate during the window.** If it does, the system's primary orchestrator is
   running on Product routing authority with a reachable mock fallback — that is not an acceptable
   steady state for any duration.
2. **The leak is visible.** Extend `importlinter.ini` in step 1 to fail on
   `app.builderops -> app.components.llm` with a single named, dated exemption for
   `ckm/semantic.py`. Cheap, and it converts an invisible violation into a countdown.

If condition 1 cannot hold — i.e. orchestration starts first — then CKM's migration is step 4 and
model inquiry follows it.

**Separate ruling, not now:** ADR-0057 locks CKM as **projection-only**, with inference entering as
`candidate` and requiring explicit human confirmation to become `confirmed` (`:8,47`). Orchestrating
development exceeds that scope. That needs its own ADR amendment — it is a consequence of the
owner's addition, not a question this document asks.

---

## 9. Honest cost

**Not worth building:** a single unified fabric across Product and Builder. ADR-0063 examined and
rejected it with a ten-criterion comparison
(`docs/audits/LLM_RUNTIME_COORDINATION_2026-07-17.md:174-185`), and nothing found today weakens that.
Consolidating the six Product abstractions as a program is also not worth it — high blast radius,
low failure rate. The A3/A4 name collision and the dead `app/llm/adapter.py` are cleanups, not a
program.

**Worth building:** steps 1–4. That is where every observed failure actually lives — the credential
substrate, the census, and the adapter seam. It is roughly one bounded capability, it is mostly
delivery of specifications that already exist and were never decomposed, and it retires two
recurring incident classes.

**Worth building because of CKM:** step 5. Without it, an orchestrator stands on the wrong side of
the authority boundary.

**The thing that makes this cheaper than it looks:** almost none of it is new design. The census is
specified (R4-1). The credential mechanism is delivered end to end (HSP-01 and HSP-02). The adapter protocol is
implemented and proven on two transports. The fallback vocabulary is ratified (ADR-0063). What is
missing is that no Issue was ever created for any of it.

---

## 10. Host opacity

**It should not persist — but the line is mechanism, not values.**

`config/secrets/host_secret_contract.json` already demonstrates the right split: the contract is in
Git, the values are in Keychain. Everything else on the host got the split wrong by omission.

Evidence that the current opacity has a cost:

- The proxy's argv allowlist is a second, uncommitted copy of the profile that
  `scripts/model_inquiry_subscription_adapter.py:20-52` already defines in Git. Two definitions of
  "the allowed Fable profile", one invisible to CI.
- The installed wrappers execute the adapter from `/Volumes/ColimaT7/workspace-root`, a checkout
  **98 commits behind `origin/main`**, while `~/.local/bin/yggdrasil-model-inquiry` `cd`s to a
  *different* checkout (`~/agentic-pkm-builderops`). Both adapter copies happen to match the pinned
  digest today; nothing keeps them matching.
- `~/.local/bin/yggdrasil-verification-dispatch` (25 KB) documents itself as *"never committed"* and
  imports from a pinned worktree at `~/worktrees/verification-dispatch-pr3620`. Its launchd job is
  currently **not loaded**.
- `BUILDEROPS_INQUIRY_ADAPTERS_JSON`, the only genuinely provider-neutral configuration surface in
  the Builder system, has **no committed instance anywhere** — not even an example.

Proposal: launcher and broker **mechanism** in Git (installed by
`scripts/install_model_inquiry_host.py`, which already does digest-pinned lineage checking);
**values, sessions, and host paths** stay out, exactly as today.

---

## 11. Defects found in passing

Not in scope; recorded so they are not rediscovered.

| # | Finding | Anchor |
|---|---|---|
| D1 | `read_only_cognition.plan()` fallback is **always** taken — it calls `run_reasoning(PLANNING, …)`, which has no PLANNING branch and always hits "mode planning not implemented". That surface has only ever emitted a canned 3-step plan | `app/chat/read_only_cognition.py:86-98`; `app/reasoning/provider.py:186-476` |
| D2 | Ingest stamps `openai/text-embedding-3-large` on every `index.embedding.requested` event — a model no adapter can serve | `app/ingest/api.py:14,140` |
| D3 | The OpenAI chat path silently discards the JSON Schema, downgrading to `{"type":"json_object"}`; the Ollama path honors it. Constrained decoding is provider-asymmetric at a seam that presents as uniform | `app/services/llm.py:282-290` |
| D4 | `panel-llm-e2e` reports green when its provider secret is absent (`ci-smoke.yaml:518-528`). The `architecture-ci.yaml:110-118` Codex gate is worse than a silent skip: that whole workflow is `workflow_dispatch`-only by its own header note, so the gate never runs automatically at all — and the step writes a credential into `$GITHUB_ENV` | `ci-smoke.yaml:518-528`; `.github/workflows/architecture-ci.yaml:1-12,108-117` |
| D5 | `config/agents.yaml` declares `merge.model: gpt-5.4` / `hygiene.model: gpt-5.4`. **No code reads it**; the name is a false friend for builder model config | `config/agents.yaml:6,15` |
| D6 | `_SUPPORTED_EMBED_PROVIDERS` accepts `openai`/`deepseek`, but `PROVIDER_REGISTRY` has no adapter for either → runtime `ValueError` | `app/components/embeddings/legacy.py:21`; `app/llm/embeddings.py:377,394` |
| D7 | `app/components/embeddings/base.py:11-24` documents OpenAI/Anthropic/Local implementations that do not exist and is unused by the runtime path | `app/components/embeddings/base.py` |
| D8 | Two distinct `ReasoningFacade` classes with the same class name and same factory name | `app/components/reasoning/facade.py` vs `app/reasoning/facade.py` |

---

## 12. Reconciliation with existing decisions

| Surface | Disposition |
|---|---|
| ADR-0063 | **Extended, not reopened.** Its kernel excluded credentials; its own audit named the gap and required a new ADR. Requested ADR-0064 fills exactly that. The owner's goal is *supported* by 0063 — a shared calling convention and vocabulary is what the kernel is for; what 0063 rejected (Option A) was making the Product router the Builder execution fabric, which nothing here proposes. |
| ADR-0063 `:179-180` (CKM sequencing) | **One deviation, stated.** That line sequences CKM's migration after a complete Builder runtime exists. §8.1 proposes migrating it earlier, on the grounds that the premise changed: it was written when CKM was peripheral. ADR-0064 must record this amendment explicitly rather than letting it pass as an implementation detail. |
| ADR-0062 | **Conforms.** Host-local model/subscription sessions remain the privileged Builder executor's (`:164-168`); the broker does not distribute credentials to laptops or Product Runtime. |
| ADR-0057 (CKM projection-only) | **Unchanged here.** CKM-as-orchestrator needs a separate amendment; this document treats CKM only as a consumer. |
| ADR-0023 / ADR-0052 (embedding egress) | **Untouched.** Embedding identity and reconciliation stay Product-owned; embeddings map to `fallback_compatible_identity`. |
| `docs/LOCAL_SECRET_PROVISIONING/` | **Extended.** Same mechanism, model-provider identifiers added. Both children are delivered, so this extends shipped code; it neither depends on nor closes open parent #3843. |
| `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` | **Delivery target.** R4-1 census becomes step 1. Its `capability-first` stage is the owner's egress ruling, unchanged. |
| `AGENTS.md :: Total Cost of Development` | **Unchanged as policy.** The census makes it resolvable instead of only readable. |

---

## 13. After the ruling

Nothing proceeds without §7. On a ruling:

1. `docs-authoring` lane: **ADR-0064** — model access substrate; credential/session resolution is
   part of the model abstraction. Extends ADR-0063.
2. `feature-breakdown`: convert steps 1–5 into bounded Issues with `Verify:` targets. Steps 1 and 2
   are largely re-decomposition of already-written specifications.
3. Only then does implementation begin.

No Issue and no PR should be created from this document before the ruling.
