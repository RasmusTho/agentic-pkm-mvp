State: Accepted (owner decision, 2026-07-27). Establishes credential and session resolution as part of the model abstraction and selects declared API keys as the default programmatic auth path. Changes no shipped runtime behavior by itself.
Doc role: Decision record (ADR)
Authority: Authoritative for model-provider credential and session resolution, the default programmatic auth path, and the single-source provider set. Extends `docs/adr/ADR-0063-shared-llm-contract-kernel.md`, which remains authoritative for the Product/Builder contract seam and the fallback vocabulary. ADR-0062 remains authoritative for Builder process/data/credential separation. `docs/LLM_ROUTING.md` remains authoritative for current Product routing.
Owner: Architecture spine / LLM boundary
Temporal class: Durable architecture decision; supersede through a later ADR.
Source of truth: Evidence and option analysis are in `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md`. The credential mechanism is owned by `docs/LOCAL_SECRET_PROVISIONING/`; the provider census and egress posture by `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md`.

# ADR-0064: Credential and session resolution is part of the model abstraction; declared API keys are the default programmatic auth path

**Date:** 2026-07-27
**Status:** Accepted (owner decision, 2026-07-27)

## Context

ADR-0063 ratified a shared neutral LLM Contract Kernel with separate Product and Builder execution
fabrics. It explicitly forbade the kernel from owning credentials, provider sessions, or host
processes (`ADR-0063:87-89`), and its evidence audit stated that a common credential plane "would
require a new ADR/SBS stewardship pass. None is proposed here"
(`docs/audits/LLM_RUNTIME_COORDINATION_2026-07-17.md:384-386`).

That gap is now the binding constraint. A `start-model-inquiry` run failed with
`final_state: provider_error`, `adapter_failure_class: command_exit_nonzero`, because
`codex login status` over a fresh non-interactive SSH cannot reach the macOS login keychain. The
same command inside the host's GUI-session tmux pane succeeds.

Read-only mapping of repository and host on 2026-07-27 established that this is not a single
provider's bug:

- Anthropic reaches a headless caller only through a hand-written TLS proxy in the GUI login session
  (`~/.local/lib/yggdrasil-claude-proxy/`, LaunchAgent `local.yggdrasil.claude-proxy`). No Codex
  analogue exists. The difference between the two providers' headless behavior is entirely that one
  received a bespoke bridge and the other did not, and neither bridge is in Git.
- Nine model-access mechanisms exist across Product and Builder that do not share provider selection,
  failure vocabulary, or credential resolution; twelve distinct credential paths exist across two
  substrates that share nothing.
- Three specifications each place model-provider credentials in another's out-of-scope: this ADR's
  predecessor excludes credentials, `docs/LOCAL_SECRET_PROVISIONING/README.md:105` excludes "runtime
  model-provider enablement", and `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` owns the
  provider census but was never decomposed into Issues. No surface owns the seam.
- The mechanisms needed already exist unfinished: the provider census is fully specified (R4-1) and
  undelivered; the Keychain credential contract is delivered for one non-model secret
  (`config/secrets/host_secret_contract.json`, HSP-01); `ModelTurnAdapter`
  (`app/builderops/model_inquiry_adapters.py:72-82`) is proven against two structurally different
  transports; `HttpModelAdapter` (`:175-278`) is fully implemented for both Anthropic and OpenAI and
  unexercised.

The owner separately stated that development of the whole system should be orchestrated from the CKM
(ruled in ADR-0057 A1, 2026-07-27: the acting party is a builder agent reading the map; the CKM has no
agency of its own). CKM's only
model path today resolves through the **Product** router (`app/builderops/ckm/semantic.py:32,116-136`)
and rejects a mock route only after Product routing may already have constructed policy-defined
fallback candidates.

## Decision

**Credential and session resolution is part of the model abstraction, not infrastructure around it.**
A provider-neutral **model access substrate** owns it, and **declared API keys are the default
programmatic auth path**.

### 1. What the substrate owns

- Provider and model resolution from a provider-free declared intent, against the census (§3).
- **Credential and session acquisition**: one contract, scoped by `(channel, consumer, provider)`,
  returning an authenticated channel. The caller never learns which backend served it.
- Execution transport behind one protocol. `ModelTurnAdapter` is promoted to that protocol rather
  than a third contract being designed.
- Failure classification in one closed vocabulary, extended with auth-specific classes
  (`credential_unavailable`, `session_expired`) that today collapse into `command_exit_nonzero`.
- Capability negotiation: constrained decoding, native tool calls, a system-prompt channel,
  embedding dimension.
- Provenance: provider, model, request id, effective identity, degraded state.

### 2. What the substrate does not own

Policy authority (Product policy stays Product, Builder policy stays Builder — ADR-0063 unchanged);
the two mutable registries; the fallback *decision*; prompts, task taxonomy, receipts, and stores.
Local credential-free model paths — TTS, STT, reranking — stay outside: they have no credential, no
provider identity worth unifying, and a different lifecycle.

### 3. Provider-free intent

Callers declare capability tier, reasoning effort, determinism requirement, output schema reference,
role-independence requirement, fallback requirement, and side-effect class. No code names a provider.
The census resolves `capability_tier -> (provider, model)` at config time, per runtime and channel.

`AGENTS.md :: Total Cost of Development` is unchanged as policy. Its two vendor ladders are already
the same three rungs with different labels, and `AGENTS.md:142` already instructs agents to resolve a
tier to the current generation's model id at config time. The census makes that resolvable rather
than only readable.

### 4. Declared API keys are the default programmatic auth path

Every headless path — model inquiry, the verification closer, CKM, CI — resolves a declared secret
through the Keychain contract in `docs/LOCAL_SECRET_PROVISIONING/`, extended with model-provider
identifiers. Subscription CLI sessions remain for interactive human-driven work and **must not be a
dependency of any headless path**.

A brokered-session backend remains permitted behind the same contract, to be built only if a specific
provider forces it. It is not built now, and the existing hand-built proxy is retired rather than
generalized.

The credential contract's existing invariants are inherited unchanged: value non-disclosure, channel
isolation, consumer minimization, and fail-closed on a missing or malformed secret
(`docs/LOCAL_SECRET_PROVISIONING/README.md:70-78`).

### 5. One provider set

`docs/settings/models/providers.yaml` is the single source for the set of providers. Code retains
local frozensets for hot paths; a static test asserts every allowlist equals the census projection
and fails CI naming the drifted site. Adding a provider is a census row plus a secret declaration —
never a new bridge.

### 6. Fallback and degradation

ADR-0063's five fallback requirement values are reused unchanged; no new vocabulary is introduced.
The caller declares the requirement, the owning runtime's policy selects within it, and the substrate
never decides. The owner's only involvement is the declared egress-posture stage.

One addition: **degradation must be visible.** A degraded result carries `degraded: true` and a
reason. Silent degrade paths become defects rather than accepted behavior.

### 7. Mechanism in Git, values host-local

Launcher and adapter mechanism is version-controlled and installed by the repository's own installer.
Credential values, provider sessions, and host paths stay outside Git, exactly as today.
`config/secrets/host_secret_contract.json` is the model: contract tracked, values in Keychain.

### 8. CKM sequencing — amends ADR-0063

ADR-0063 `:179-180` sequences CKM's migration to happen only after a complete Builder runtime exists.
That line was written when CKM was a peripheral consumer. **It is amended:** CKM migrates as early as
its dependencies allow, requiring only credential resolution and the adapter contract.

Through the migration window CKM continues to route Builder inference through Product policy — the
authority leakage ADR-0063 rejected Option A to prevent.

**Amended 2026-07-27, superseding this section's original interim conditions.** When this ADR was
accepted, whether CKM might orchestrate was undecided, so tolerability was made conditional on CKM
not orchestrating during the window, with a migration-order swap if it did. The owner has since
ruled (ADR-0057 A1) that delivery may be orchestrated from the CKM by a builder agent. Both the
original condition and the conditional swap are therefore withdrawn, and the tolerability argument is
restated on the correct grounds:

- **The order does not swap.** The CKM migration stays at step 5 of the migration table in
  `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration` (that table is current; only its
  §8.1 narrative is superseded). Orchestration selects work from
  gap detection, which consumes `confirmed` material only (`app/builderops/ckm/gaps.py`), so an
  orchestrator is not fed unconfirmed inference. The mock route is separately and already handled:
  it is rejected before any provider call and the run writes zero edges
  (`app/builderops/ckm/semantic.py`; `tests/builderops/ckm/test_semantic.py::test_llm_unavailable_skips_cleanly`).
- **What the leak actually risks is the evidence graph, not the orchestrator — and specifically the
  non-mock degraded route.** Product policy may silently resolve a degraded fallback
  (`app/components/llm/router.py` sets `degraded=True`); `semantic.py` never inspects
  `route.degraded`, and the persisted edge records provider and model but not the degraded state.
  That is the genuine data-integrity defect, and step 5 closes it.
- **The visibility condition does not yet exist and is therefore scheduled, not relied upon.** The
  `app.builderops -> app.components.llm` importlinter contract is **not implemented**: `importlinter.ini`
  lists `app.builderops` only as a member of a layered-independence contract, and `app.components.llm`
  is a different package from `app.llm`. Adding it — with a single named, dated exemption for
  `ckm/semantic.py` — is part of migration step 1. Until it lands, the leak is real and invisible,
  and this ADR does not pretend otherwise.

Whether delivery may be orchestrated *from* the CKM is decided in ADR-0057 A1, not here. The CKM
itself never orchestrates under any reading: the acting party is a builder agent that reads it.

## Options considered

### A. Declared API keys as the default — selected

The headless problem is removed rather than bridged. CI can reach providers for the first time. A new
provider costs a census row. The TLS proxy and its version-pinned CLI symlink dependency are retired.
Cost: metered API billing on top of existing subscriptions, at inquiry and orchestration volume.

### B. Generalize the proxy into a brokered-session service — rejected as the default

Zero marginal model cost, and it would collapse the proxy's uncommitted argv allowlist into the
definition already in Git. But a GUI login session cannot exist in CI, so CI remains unable to reach
any provider and the two silently-green workflows stay silently green. Every new provider needs broker
support for its CLI's session model and stays exposed to CLI flag and version-layout churn — the
failure class this ADR exists to end would survive, relocated rather than removed.

### C. Both backends, substrate chooses — rejected as the initial build

Most capable and cheapest at the margin, but two backends to build, test, and keep honest plus a
resolution-order rule to reason about on every surprising call. Disproportionate machinery for a
single-operator system. Option A's contract does not foreclose it: B becomes a second backend if
needed.

## Consequences

- Acceptance authorizes specification and backlog decomposition, not direct implementation. Work must
  pass through `feature-breakdown` and the Issue-first lane. No Issue becomes `agent:ready` merely
  because this ADR is Accepted.
- Current Product routing and Builder Model Inquiry behavior are unchanged until their own migration
  steps. Steps 1-3 of the migration are purely additive.
- `docs/LOCAL_SECRET_PROVISIONING/` is extended, not superseded: model-provider identifiers join the
  contract, and its hardcoded consumer allowlist becomes data. Both HSP children are already
  delivered (#3845/PR #3888 and #3846/PR #4008), so this extends a shipped mechanism rather than
  waiting on one. It neither depends on nor closes parent issue #3843, which remains open for a
  redacted dev-deploy receipt and the `docs/SECURITY.md` promotion; the model-provider identifiers
  do, however, change what that promotion must say.
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` becomes a delivery target. Its R4-1
  census is the first step. Its `capability-first` egress stage is unchanged and remains the owner's
  ruling.
- Metered spend becomes an observable rather than a bet: the egress ledger and budget circuit breaker
  specified at `RUNTIME_MODEL_POSTURE.md:131,138` are prerequisites for volume growth, not follow-ups.
- Two CI provider paths become contract violations under §6 and must be repaired as part of the
  credential work. `.github/workflows/ci-smoke.yaml:518-528` reports green when its provider secret
  is absent. `.github/workflows/architecture-ci.yaml:108-117` is worse: that workflow is
  `workflow_dispatch`-only, so its gate never runs automatically at all, and the step writes a
  credential into `$GITHUB_ENV`. "Repaired" means fail-closed or removed — never green-on-absent.
- Consolidating the six Product-side abstractions is explicitly **not** authorized as a program. The
  census test blocks new drift; existing sites migrate opportunistically.
- Architecture tests must eventually enforce: census equality across every allowlist, credential
  resolution through the contract only, no headless dependency on a subscription session, adapter use
  over direct provider calls, and visible degradation.

## SBS reconciliation

- **Conforms:** Product and Builder remain distinct systems; ADR-0062's rule that Product Runtime owns
  no Builder process, data, credential, or route is preserved, and host-local sessions remain the
  privileged Builder executor's.
- **Extends:** ADR-0063's kernel gains an adjacent, separately-owned credential and session resolution
  contract. The kernel itself still owns no credential.
- **Reshapes:** this is the "common credential plane" that `LLM_RUNTIME_COORDINATION_2026-07-17.md:384`
  named as requiring a new ADR/SBS pass. CES gains stewardship of the credential contract's versioning
  alongside the compatibility mappers.
- **Does not reshape Product SBS:** Product CAO/EBF ownership, embedding identity, and reconciliation
  discipline (ADR-0023/ADR-0052) are unchanged.
- **Future reshape trigger:** a separately deployed credential service, a cloud secret manager, or
  cross-host credential sharing would require a new decision. None is proposed here.

## Owner decision receipt

The owner ratified **Option A — declared API keys as the default programmatic auth path, subscription
sessions interactive-only, brokered sessions permitted but not built** on 2026-07-27. The selected
architectural answer is:

> Credential and session resolution is part of the model abstraction. Every headless path resolves a
> declared secret through the host secret contract; no headless path depends on an interactive
> subscription session. The provider set is defined once in the census, callers never name a provider,
> and the brokered-session backend remains available behind the same contract without being built.

Private deliberation is intentionally not republished. This receipt ratifies the decision; the audit
backlog remains advisory until `feature-breakdown` creates executable specifications and strictly
valid Issues.
