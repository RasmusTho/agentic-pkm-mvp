State: Delivered specification for a capability that ships dormant and fail-closed. All six child implementation issues #4308–#4313 are closed with merged PRs (see each task doc's `github_issue:` frontmatter) and carry terminal delivery receipts on #4131. No design run can execute: no `builderops-design-run` credential grant exists on any channel, and no doc may describe design-agent runs as working, enabled, or proven end to end against a real provider. Parent validation hub #4131 governs acceptance and closure for this capability; GitHub owns its current open/closed state and labels, not this doc. The conditional acceptance receipt of 2026-08-01 authorized only the docs-only owner-doc promotion. `Capability acceptance` below is ticked only against a closure receipt naming this document; the hub's closure criterion is a separate post-promotion fresh independent audit, not a child slice and not the promotion PR.
Doc role: Capability specification
Authority: Owns the bounded CKM design-agent integration capability, cross-task invariants, task order, and acceptance path. Subordinate to ADR-0057, ADR-0064, the delivered CKM Direction B contract, and the BuilderOps authority boundary.
Owner: Builder System / CKM
Temporal class: active specification
Review cadence: event-driven
Source of truth: this directory for implementation-task shape; live GitHub for pickup and delivery state
Last reviewed: 2026-08-01

# CKM Design-Agent Integration Hub

## Capability boundary

This capability adds one provider-neutral design-run path around the delivered CKM cockpit without
turning the generated HTML into an execution surface.

The operator:

1. assembles a bounded, deterministic design brief from explicit CKM evidence references,
   constraints, a requested deliverable, and digest-bound attachment references;
2. selects exactly one registered design-agent adapter through a governed CLI/service boundary;
3. receives an explicit BuilderOps admission result before any provider call;
4. starts the exact hash-bound request only when admission and any required approval allow it; and
5. regenerates the existing CKM cockpit to inspect adapter availability, run state, receipts, and
   returned handoff references as non-authoritative projections.

The generated Direction B HTML remains inert: no form submission, provider call, polling, network,
storage, clipboard, approval, or execution path is added. Provider commands, credentials, retry
behavior, and host-specific paths remain behind Builder System adapters.

## Reuse boundary and external prerequisite

Model Access Substrate Phase 1 is governed by parent
[#4286](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4286) and its serial children
#4287–#4292. CDH-01 may define design-run domain contracts independently, but CDH-02 and every later
execution slice remain blocked until #4286 closes with its repo-verifiable Phase 1 acceptance ledger
plus the delivered neutral intent/resolver/adapter contracts. Under ADR-0064's 2026-07-30 owner-cost
ruling, that acceptance does not require provider-enabled inquiry, bridge retirement, metered
credential provisioning, or active provider-backed inference. A child merge SHA without the
parent's terminal validation is insufficient.

After acceptance, this capability reuses:

- canonical JSON and hash conventions from `app/builderops/model_inquiry_contract.py`;
- provider-free grouped intent/resolution, capability negotiation, `ModelTurnAdapter`, sanitized
  result/provenance, and the closed failure vocabulary from top-level `llm_contract/` and the
  Builder-owned resolver delivered by #4286;
- immutable/no-overwrite artifact and validated-trace patterns from
  `app/builderops/model_inquiry.py`;
- the generic `BuilderOpsReceipt` envelope and idempotency conventions from
  `app/builderops/models.py`.

It does not reuse `ModelInquiryRunner`, inquiry roles, the two-model inquiry launcher, inquiry
readiness, or inquiry-specific start/trace/resume semantics. Design runs add domain envelopes and
receipt semantics above the shared model-access substrate; they do not add a credential resolver,
provider transport, or competing failure vocabulary.

## Authority boundary

- CKM owns bounded brief assembly and read-only cockpit projection.
- Builder System owns adapter discovery and provider execution.
- BuilderOps owns admission, approval evidence, durable design-run records, and receipts.
- A returned design remains supporting Builder material. Promotion to an Issue, PR, owner doc,
  design handoff archive, or discard requires the normal governed boundary.
- Selecting an adapter is not approval.
- The repo-governed `config/builderops/design_run_policy.json` serialized as a
  `DesignRunPolicyProfile` is the only policy source for this capability. It declares allowed
  deliverable kinds, context/attachment bounds, whether operator approval is required, and the
  Yggdrasil receipt requirement for visual work. Its canonical hash is part of admission.
- The local single-operator BuilderOps CLI is the approval producer. It derives the approving
  principal from the authenticated local OS account, refuses caller-supplied actor identity, and
  writes immutable exact-hash approval or revocation evidence before start.
- Neither CKM nor the generated cockpit can rank providers, choose automatically, retry across
  providers, or mutate GitHub, repo docs, Product/Runtime state, or human knowledge.

## Operator surfaces

- `builderops design-run ...` (exact command grammar is owned by CDH-04) is the authenticated
  selection, admission, start, status, and result surface.
- `ckm overview --cockpit` remains a generated local projection. It may show a read-only adapter
  list that helps the operator choose a CLI argument, but it never performs the choice or start.
- No sibling dashboard, hosted service, Companion UI surface, or Product/Runtime UI is introduced.

## Cross-Task Invariants / Interaction Safety

- **INV-CDH-1 — projection is not execution.** Cockpit HTML receives only immutable projection
  DTOs. It never receives an adapter, store handle, policy evaluator, credential, or command.
- **INV-CDH-2 — exact request admission.** Admission binds the canonical request hash, brief hash,
  adapter identity, policy identity/version/hash, source refs, and evaluation time. Unknown, stale,
  denied, pending, or mismatched admission causes zero provider calls.
- **INV-CDH-3 — approval cannot expand scope.** When approval is required, immutable approval
  evidence binds the same exact request/admission hashes. Approval cannot alter the brief, adapter,
  requested deliverable, or evidence set.
- **INV-CDH-4 — explicit bounded context.** Briefs contain only explicit source and attachment
  references with immutable digests. Whole-repo, whole-vault, implicit cwd, ambient chat history,
  and unbounded discovery are forbidden.
- **INV-CDH-5 — one provider, no fallback.** A run targets one registered adapter. Unavailable,
  denied, malformed, timed-out, or failed execution never falls through to another provider.
- **INV-CDH-5A — one model-access substrate.** Design-agent domain adapters declare provider-free
  model intent and execute through ADR-0064's promoted `ModelTurnAdapter` substrate. They do not own
  credentials, sessions, HTTP/subprocess transport, provider resolution, or a second failure
  vocabulary. A subscription-only interactive route is never advertised as headless availability.
- **INV-CDH-6 — append-only causal evidence.** Accepted start and every later transition,
  refusal, failure, and result has one `BuilderOpsReceipt` linked to the previous receipt ID and
  hash. Status is derived from the validated chain, not mutable presentation state.
- **INV-CDH-7 — secret-safe adapter boundary.** CKM and durable records contain sanitized adapter
  identity and failure detail only. Credentials, subscription material, raw stderr, host-local
  launcher paths, and provider command construction never cross into CKM.
- **INV-CDH-8 — handoff non-authority.** Handoff references preserve provider identity, source
  refs, content digest, limitations, timestamps, and receipt lineage and are always labeled as
  unaccepted Builder material.
- **INV-CDH-9 — deterministic projections.** Identical explicit generation time, CKM batch,
  adapter descriptors, and validated design-run projection produce byte-identical cockpit HTML.
  CKM and design-run projection digests remain distinct.
- **INV-CDH-10 — Direction B remains inert and accessible.** The existing single script stays
  filtering-only. No new script, form, button, textarea, polling, network, or storage capability is
  added. JavaScript-off and print contain all projected evidence.
- **INV-CDH-11 — visual generation is Yggdrasil-gated.** A typed visual-handoff deliverable requires
  an exact, current Yggdrasil gate receipt in the brief and admission: live system name/ID,
  selection-or-attachment mechanism, repo token source, matching live/repo token SHA-256, parity
  pass, and referenced previews. Missing, stale, or drifted parity causes zero provider calls.
  Explicitly typed non-visual deliverables are exempt.

### Partial-failure paths

- Contracts merge but adapters do not: no provider is registered and no run can start.
- Adapters are registered but admission is absent: availability can be inspected; provider
  invocation remains impossible.
- Admission allows but durable start persistence fails: no provider call occurs.
- Approval is revoked, stale, foreign, or hash-mismatched: start refuses before any provider call.
- A visual request lacks a current matching Yggdrasil receipt: admission refuses before any
  provider call; non-visual requests remain separately typed and do not inherit a false receipt.
- Provider call begins but terminal persistence fails: the run is visibly incomplete/failed; no
  success or handoff claim is projected and no fallback runs.
- A receipt chain is missing, cyclic, tampered, or references a foreign run: status projection
  refuses the entire affected run instead of showing partial success.
- A returned handoff is missing or digest-invalid: the terminal result is a typed refusal/failure;
  the cockpit never links or previews the unverified artifact.
- Cockpit capture fails after prior output exists: no new partial output is eligible; the previous
  artifact remains distinguishable by its generation identity.
- JavaScript is blocked or the page is printed: all adapters, states, receipts, refusals, and
  handoff metadata remain visible because they are server-rendered.
- Yggdrasil design-system parity or handoff validation fails: CDH-05 remains blocked while CDH-01
  through CDH-04 may still deliver their non-visual contracts and CLI path.

## Implementation tasks and order

1. [Define Design-Run Contracts](DEFINE_DESIGN_RUN_CONTRACTS.md) — neutral DTOs, validation, and
   canonical hashes.
2. [Register Design-Agent Adapters](REGISTER_DESIGN_AGENT_ADAPTERS.md) — after accepted #4286,
   exact supported design agents above the single ADR-0064 model-access transport.
3. [Govern Design-Run Lifecycle](GOVERN_DESIGN_RUN_LIFECYCLE.md) — admission, approval, immutable
   run/event artifacts, and causal receipts.
4. [Expose Design-Run CLI](EXPOSE_DESIGN_RUN_CLI.md) — actual operator selection/start/status/result
   path outside generated HTML.
5. [Project Design Runs in the Cockpit](PROJECT_DESIGN_RUNS_IN_COCKPIT.md) — Yggdrasil-gated
   read-only availability/status/handoff projection.
6. [Validate the Design Hub End to End](VALIDATE_DESIGN_HUB_END_TO_END.md) — production-path
   provider/refusal coverage, final deterministic/print proof, and conditional parent-acceptance
   handoff.

The chain is serial because later slices consume the exact contracts and receipt semantics of the
earlier slices. CDH-05 may begin only after the Yggdrasil design-handoff gate passes.

## Capability acceptance

Registered design agents are partitioned into **headless-registered** routes (`codex`, `fable`) and
**interactive-only** routes (`claude-design-via-claude-code`). The partition follows from
INV-CDH-5A rather than exempting anything from it: an interactive-only route is hard-refused as
`interactive_subscription_only` inside `DesignAgentAdapterRegistry` before any adapter lookup, so
requiring a governed *success* for it would require the invariant to be broken. The two buckets must
stay exhaustive and disjoint over `DESIGN_AGENT_IDS` — see `HEADLESS_CAPABLE_AGENT_IDS` and
`INTERACTIVE_ONLY_AGENT_IDS` in `tests/builderops/test_design_hub_acceptance.py` — so a newly
registered adapter lands on exactly one side and cannot escape the matrix by appearing in neither.

This narrows what a success proves; it does not narrow the fail-closed guarantee. Every registered
route that is not proven by a governed success must instead be proven by an exact,
zero-provider-call, no-fallback refusal, and the shipped production posture grants no
`builderops-design-run` secret, so the dormant registry must refuse every route including the
headless-registered ones.

- [ ] All six task Issues are closed with exact PR/SHA/Verify receipts on parent #4131.
  Verify: `runtime receipt: ckm_design_hub.child_ledger.v1`
- [ ] The production path proves one governed success per headless-registered adapter, an exact
  zero-provider-call `interactive_subscription_only` refusal for every interactive-only registered
  adapter, and distinct unknown, unavailable, denied, pending, malformed, timed-out, and failed
  states with no fallback.
  Verify: `tests/builderops/test_design_hub_acceptance.py::test_design_hub_production_matrix_is_fail_closed`
- [ ] Cockpit output remains projection-only, deterministic, JavaScript-off complete, printable,
  and incapable of starting a run.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_design_hub_projection_preserves_direction_b_authority`
- [ ] The final cockpit visual has a passing Yggdrasil Design Handoff receipt with matching live
  and repo token SHA-256.
  Verify: `runtime receipt: ckm_design_hub.yggdrasil_handoff.v1`
- [ ] A conditional independent parent audit authorizes owner-doc promotion only after all child
  evidence passes; the subsequent docs PR updates the exact CKM and Builder System owners, and a
  fresh terminal audit verifies that merged diff before closure.
  Verify: `runtime receipt: ckm_design_hub.terminal_acceptance.v1`

## Explicitly out of scope

- Provider ranking, recommendation, benchmarking, automatic selection, fallback, or cost
  optimization.
- A live or hosted cockpit, Companion UI integration, multi-user service, or Product/Runtime UI.
- Direct Issue/PR creation, merge, owner-doc editing, deployment, promotion, or Product/Runtime
  mutation from CKM, adapters, or design output.
- Replacing native Codex, Claude Design/Claude Code, or Fable authentication/session mechanisms.
- General-purpose model inquiry behavior owned by #3288.
- Deterministic delivery orchestration owned by #4163/#4169.

## Relationship to GitHub

- Parent validation hub: #4131. It remains blocked and is never a direct pickup Issue.
- Child Issues are created only after this specification is merged and their live bodies pass
  strict readiness and Source Anchor validation.
- External prerequisite: #4286 terminal repo-verifiable Phase 1 acceptance. #4131 depends on that
  parent validation rather than inferring acceptance from #3288 labels. Withdrawn provider/bridge
  receipts, metered credentials, and active provider-backed inference are not prerequisites.

## Source docs

- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/adr/ADR-0064-model-access-substrate.md`
- `docs/MODEL_ACCESS_SUBSTRATE/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/DESIGN_PRINCIPLES.md`
- `.codex/skills/yggdrasil-design-handoff/SKILL.md`
