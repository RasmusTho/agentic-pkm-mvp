State: Accepted strategic target-state owner-function contract (2026-08-07). `devUI` is the working
owner-facing name. The CKM Development Overview and BuilderOps Cockpit are delivered as separate
read-only surfaces; the unified experience, authenticated approval path, live delivery controls,
and receipt loop described here are not yet delivered.
Doc role: Builder System owner-function and experience contract
Authority: Owns the accepted owner-experience goal and guardrails for what the Product Owner must be
able to see, decide, initiate, follow, and verify through devUI. Existing CKM, delivery,
authentication, execution, and GitHub mechanism contracts remain binding.
Owner: Builder System governance
Temporal class: Strategic target state with an explicit current-state section
Review cadence: Event-driven
Source of truth: This document owns the owner experience. Accepted ADRs and linked capability
specifications own the mechanisms; live GitHub, CI, dispatcher, and receipt evidence owns delivery
truth.
Last reviewed: 2026-08-12
Last verified against: `origin/main` `989a8d73d52b75c3a038ba1d3f93c78e03d98065`, including the
merged withdrawal receipt in PR #4751, the admitted direct-loopback Overview route in PR #4772,
and the ARO-03 contract and route-test-selection recovery in PR #4789; ADR-0057,
ADR-0062, ADR-0064, ADR-0065, the CKM and BuilderOps Cockpit owner contracts, the Deterministic
Delivery Orchestration specification, the merged Builder System process clarification in PR #4692,
the advisory Builder System devUI execution audit in PR #4689, and the merged Focus and Conversation
Port specification in PR #4699.

# devUI — the owner flow for Yggdrasil development

> Audience: the Product Owner directing Yggdrasil development. This document describes what the
> owner should be able to do. Queues, workers, leases, worktrees, and provider adapters are
> implementation detail, not the owner workflow.

`devUI` is a working name until a suitable Yggdrasil name is chosen. It describes an experience,
not a package, command, or route. The existing `make dev-ui` starts Companion UI and must not change
meaning because of this document.

## Core idea

devUI is where the Product Owner makes development and build decisions from one coherent picture.
The owner should not have to reconstruct the situation from documents, Issues, PRs, CI, agent
threads, and receipts.

devUI is the sole normal owner-facing umbrella for Builder System interaction. BuilderOps Cockpit,
CKM views, and Signboard are internal capability providers and transitional or diagnostic surfaces,
not products the owner must choose between. Their names, routes, stores, and source topologies must
not define primary navigation or split one owner journey across subsystem UIs.

Its primary success criterion is reduced cognitive load: the owner can keep directing the project
without first rebuilding an internal model of the delivery machinery.

The owner loop has four verbs:

```text
see → decide → act → verify
```

The internal systems may implement a longer chain:

```text
intent → capability → evidence and gaps → delivery request → preview
→ approval → delivery run → receipt → CKM reassessment
```

This is one experience, not merged authority. CKM only describes. The authenticated delivery
boundary approves exact scope. GitHub, CI, review, merge, and closure prove what happened.

### Intent and evidence continuity

Discovery and delivery are short, nested loops inside the owner flow, not sequential phases. New
evidence or a late change may return an item to its owning intent, assumption, decision,
specification, or acceptance criterion. The change remains legal when the owning source records what
was superseded and why, the consequence for active work is visible, and affected verification is
rerun. Routine reversible implementation choices remain in Issue, Git and PR evidence.

devUI should make the source-owned path from intent or need through normative decision, capability
or specification, Issue, PR/SHA proof, and optional owner validation progressively visible. It must
show an absent, stale, unlinked, unassessed, or unavailable edge honestly and must not create a
persistent intent store, infer correlation, or convert the Delivery Graph Projection into authority.
Verified delivery, **Ready to try**, tried by owner, and owner accepted are separate facts. See
`docs/audits/BUILDER_SYSTEM_INTENT_EVIDENCE_GOVERNANCE_2026-08-10.md`.

## Cognitive-load contract

The devUI home has three stable zones:

1. **Now** — what is moving, what is safely continuing, and what is blocked by the system.
2. **Needs you** — only decisions that genuinely require Product Owner authority.
3. **Ready to try** — delivered results whose evidence is complete enough for owner evaluation.

Every surfaced item answers, without opening another product:

- what it is and why it is shown;
- its single owner-facing state;
- what happens next;
- whether the owner can or must act;
- source freshness and any material uncertainty; and
- the result or receipt when one exists.

The default view hides Issues, PRs, SHAs, workers, leases, worktrees, provider sessions, and raw
source graphs. They remain available as progressive technical detail and source links. The owner
must not understand CKM, DDO, BuilderOps, dispatcher, GitHub, or CI as separate products to use the
core flow.

devUI may render a **Delivery Graph Projection**: a read-time, rebuildable composition of existing
authorities linked by typed references and receipts. It does not persist a Delivery Knowledge Graph,
copy source lifecycle state, or become a new authority store. A new dashboard module, top-level
mode, status, or durable entity is out of scope unless it removes an owner reconstruction step that
the three zones cannot answer.

### Delivery Graph Projection boundary

The versioned devUI composition envelope declares when the view was composed and, for every provider
claim it uses, the source identity, source-specific snapshot or reference, watermark or
`captured_at`, completeness, and any typed refusal or withdrawal reason. It is rebuilt from CKM,
BuilderOps/DDO, GitHub, Git/worktree, CI, review, merge, dispatcher, and receipt evidence at read
time. A missing, stale, refused, or unlinked input remains visible as that source's condition; the
envelope must never replace it with an inferred link, zero, empty result, or durable cache.

The following existing authorities remain the minimal model. devUI links them; it does not normalize
them into a universal object hierarchy or a shared lifecycle state machine.

| Concern | Existing authority or contract |
| --- | --- |
| Meaning and scope | Owner docs, ADRs, task specifications, GitHub Issues, and `IssueScope` |
| Delivery proposal and approval | `DeliveryRequest`, `DeliveryPreview`, `ApprovalEvidence`, and `DeliveryInitiation.v2` |
| Execution | DDO plan/reducer, attempts, typed reducer effects, worker context/invocation/result contracts, BuilderOps journal/outbox |
| Result facts | GitHub/Git/CI/review/merge readback and typed receipts |
| Capability learning | CKM-derived/provenance-bound evidence and BuilderOps retrospective records |
| Owner view | This read-only, rebuildable composition envelope |

### Shared read-envelope validation

Before a provider adapter supplies an owner-facing claim to a devUI composition, it must prove a
shared read-envelope at its public boundary. The contract is provider-local and projection-only:
it validates what that provider can support for this read, without normalizing or taking ownership
of the provider's source facts.

- **Semantic shape.** The envelope identifies the provider and source, declares the claim or
  withdrawal it can support, and distinguishes fresh evidence, measured empty, missing, stale,
  unavailable, refused, and degraded states. A refusal or degradation is typed with a reason and
  affected claim; it is never converted to a healthy value, inferred link, zero, or empty result.
- **Serialization shape.** The public serialized envelope preserves the semantic state, source
  identity, source-specific snapshot/reference or watermark, `captured_at` freshness, completeness,
  and typed refusal/degraded detail needed by a consumer to render the claim honestly. Internal
  objects may have richer fields, but serialization must neither drop a material state nor invent a
  value absent from the source.
- **Authority preservation.** Provider identity, source references, and freshness/completeness
  metadata remain attributable to the provider's existing authority. Composition may join them at
  read time, but cannot upgrade provenance into authority or collapse independent source states
  into a devUI lifecycle.

Typed/dataclass/dictionary shape alone is insufficient evidence unless the public serialized
envelope and semantic states are covered by provider-boundary tests or equivalent fixtures. Those
checks must exercise both supported and refused/degraded material so composition can rely on the
rendered contract rather than an adapter's internal representation.

Provider envelope validation cannot create task, issue, lifecycle, priority, or source authority.
It creates no persistent devUI store, registry, cache, or control path; GitHub, CI, receipts,
Cockpit, CKM, Signboard, BuilderOps, and each provider's own source remain authoritative for their
respective facts.

Do not add general-purpose `OwnerIntent`, `CapabilityDeliveryIntent`, `DeliveryScope`,
`DeliveryApproval`, `ExternalEffect`, `EvidenceSnapshot`, `AgentSession`, or `WorkspaceLease`
objects for this experience. The listed contracts, source-specific snapshots, carrier envelopes, and
separate lease models already carry the necessary semantics. A future persistent owner-intent or
needs register requires a separate authority, privacy, and demonstrated-use decision; **Needs you**
is a projection zone, not such a register.

Delivery facts stay multidimensional rather than advancing through one devUI state. Required checks
green, merge, Issue closure, promotion or availability, **Ready to try**, owner tried, and owner
accepted are separately evidenced facts with separate owners. No earlier fact implies a later one;
in particular merge is not delivery, delivery is not promotion, and **Ready to try** is neither an
owner trial nor acceptance. Owner-tried and owner-accepted remain future typed receipts until their
governing authority exists.

Claude and Codex handoffs use the existing durable chain
`WorkerContextPack → WorkerInvocation → provider/session carrier → WorkerResultV2`
`(with StructuredWorkerResult) → Receipt`. Provider/session identifiers and model metadata are
provenance only. Resumption reads the BuilderOps journal, typed receipts, and live provider readback;
it never treats chat history as delivery authority.

### Decision-support and information-depth contract

Low cognitive load does not mean low information. devUI reduces the mental work of locating,
joining, and interpreting evidence; it does not remove evidence needed for a sound decision. The
surface therefore organizes each item around three situation-awareness questions:

1. **What is happening?** — the current owner-facing state and source freshness.
2. **What does it mean?** — why the item is shown, material uncertainty, and consequence for the
   goal or capability.
3. **What happens next?** — the next legal transition, who owns it, and the consequence of waiting.

Information is disclosed in a fixed depth rather than split across products:

1. **Glance** — state, why now, next step, and whether owner action is legal.
2. **Understand** — capability context, dependencies, uncertainty, expected result, and material
   limitations.
3. **Verify** — evidence groups, freshness, receipts, and source-level provenance.
4. **Inspect** — Issues, PRs, SHAs, workers, leases, raw graphs, logs, and exact technical fields.

Moving deeper must not replace, summarize away, or reclassify the underlying evidence. It reveals
the same selected item's evidence with more precision. This is progressive disclosure without
information loss.

The following decision-science rules are binding presentation constraints:

- **Needs you is a high-precision signal.** False owner escalations create alert fatigue and train
  the owner to ignore the surface. An item enters this zone only with a named owner authority
  category; missing or ambiguous technical evidence remains a system block in **Now**.
- **Decision support is organized around the owner's goal, not subsystem topology.** CKM,
  BuilderOps, DDO, agents, and GitHub appear as evidence sources, never as the primary navigation.
- **The selected context stays spatially and semantically stable.** Cockpit, detail, command, run,
  and receipt preserve the same subject, goal, scope, and evidence frame so the owner does not have
  to remember or mentally rejoin them.
- **Quantified claims retain their denominator and limitations.** Prefer concrete forms such as
  “3 of 8 required checks remain” over an unexplained score or percentage. Aggregate maturity,
  confidence, risk, or priority numbers never replace their components.
- **Automation confidence is item-specific and evidenced.** Show freshness, completeness,
  disagreement, and limitations for the actual recommendation; do not use one global “AI
  confidence” indicator as a substitute for evidence.
- **A genuine owner decision is presented as one decision.** Show the recommendation, viable
  alternatives, consequence of each, consequence of waiting, and the exact evidence and scope the
  action will bind. Routine agent choices and technical recovery are not offered as owner options.

## Scope

### In scope

devUI is the Product Owner's entry point to:

- see capabilities and their evidence;
- see work in progress, delivered, flawed, and forgotten;
- understand freshness, uncertainty, missing sources, and conflicting claims;
- choose a capability, problem, or bounded Issue set;
- review a proposal with scope, exclusions, risk, cost, and acceptance meaning;
- approve the exact preview through an authenticated boundary;
- see the active run, its next legal step, and meaningful stops;
- pause, resume, cancel, or supersede a run when delivery policy permits it; and
- receive a terminal receipt and see how it changes capability evidence.

### Out of scope

devUI is not:

- Product Runtime or a normal end-user Yggdrasil surface;
- a new source of truth for capabilities, Issues, PRs, CI, or delivery;
- a task, queue, lease, worker, merge, or closure system;
- permission for CKM scores, findings, or model proposals to select work automatically;
- a replacement for GitHub, repository contracts, branch protection, CI, or verification;
- a place that automatically turns technical uncertainty into an owner decision;
- a browser-local store for durable decisions; or
- required for the underlying CLI/API delivery path to work.

### Conditional future scope

Durable owner dispositions such as `done`, `ignore`, and `never_show_again` may later appear in the
same experience, but only after ADR-0065's cutover, privacy, retention, API, and UI decisions. They
are not delivery-run states and are not part of the first devUI acceptance.

## Owner functions

### Orient the whole system

The home view uses the three stable zones from the cognitive-load contract. Technical attention that
an agent or deterministic rule can handle remains in **Now**; it must not inflate **Needs you**. The
first view uses owner language and freshness. A dead or unread source must never look like zero.

### Orient the Product/Runtime SoI evidence

Overview may include the target **SoI Evidence View v0** lens defined in
`docs/DEVUI_SOI_EVIDENCE_VIEW/README.md`. It lets the owner inspect a named Product/Runtime SoI
scope through a source-owned evidence vector from intent through owner outcome. It is complete only
relative to an owner-declared denominator and does not claim whole-Yggdrasil ecosystem coverage.

This is neither a Focus subject nor Builder System Control. Product/Runtime SoI and Builder System
Control are separate roots that share source-state presentation semantics but not identity,
denominator, authority, maturity semantics, or command scope. Unknown, missing, stale,
unavailable, refused, and measured-empty material remains explicit. The lens must never create a
new graph, task, lifecycle, registry, score, writer, or owner-acceptance inference.

### Understand a capability

For each capability, devUI shows what the system should do, what is confirmed or only candidate,
the relevant specs/code/tests/receipts, evidence gaps, current work, and what “delivered” means in
that context.

CKM maturity may help orientation only with its components, citations, limitations, and freshness.
An aggregate never sets scope by itself; sources must remain reviewable and pass the applicable
measurement-quality gate.

### Review work without becoming the agents' project manager

Work appears as a comprehensible chain from intent to terminal receipt. The owner sees the current
state, why it is waiting, and the next legal transition. Internal identifiers appear only on demand.
Normal use never requires a query string, file path, Issue identifier, or other free technical key.

### Use a contextual command surface

Commands are attached to the selected capability, problem, delivery proposal, or active run. devUI
does not require a global command language or a second task system. A short owner-authored outcome
may seed a proposal, but it cannot bypass evidence selection, exact preview, authentication, or
delivery policy.

The command surface shows one primary next action, or explains why no owner action is legal. Work
that AI can safely continue is not turned into an owner button. Authority-bearing commands use
outcome language, remain visibly separate from links and read-only analysis, and return a receipt.

### Review and approve an exact proposal

A proposal answers: goal, affected capability or bounded work, evidence, included and excluded
scope, dependencies, risk/cost/uncertainty, delivery meaning, and consequences of waiting.

This belongs to the planned DDO-06 `DeliveryRequest.v1` and `DeliveryPreview.v1` path. These are
specified target contracts, not delivered building blocks. devUI must not introduce a parallel
intention type.

Approval binds the exact request, preview, current source freshness, and acceptance profile. If any
of these change, a new preview and approval are required. A devUI button is never authority itself:
it calls the separately authenticated control boundary and receives a traceable receipt.

### Follow by exception and receive results

Normal work proceeds without owner monitoring. devUI returns attention only for a true owner
decision, an unexpected terminal stop, a consumed policy/budget, or a receipt ready to read or try.

A terminal receipt shows outcome, changed version, evidence, passed/missing verification, delivery
meaning, remaining risks, and CKM reassessment. “Merged” and “ready for you to try” are not always
the same. A durable “tried by you” receipt remains a separate future decision (INV-DG-7).

## Owner language and source states

| Owner language | Meaning |
| --- | --- |
| **AI can continue** | An explicit rule and all deterministic gates allow the next bounded step. |
| **Your decision is needed** | A named canonical Human Exception category reserves the decision for the owner. |
| **Blocked by evidence or system** | Required evidence, a dependency, conflicting/ambiguous technical authority, or safe recovery is missing. |

Exhausted retries or a difficult technical error are not, by themselves, owner decisions. DDO-04
currently routes `authority_conflict` and Issue-contract drift to `owner_decision`; DDO-06 must bind
each case to a canonical Human Exception or reclassify it before devUI can render owner language.

| Source state | Owner presentation | Decision consequence |
| --- | --- | --- |
| Fresh and evidenced | Claim, source, timestamp, limitation | Can support a proposal if other gates pass |
| Stale or last-good | Dated prior CKM snapshot with warning | Orientation only; cannot carry freshness-dependent preview/approval |
| Unavailable, unread, unsupported, refused | Source could not support its claim | Dependent claim is withdrawn; never rendered as zero/empty |
| Missing, unassessed, absent, unlinked | Known gap or missing relation | Visible gap; a required gap blocks but is not automatically an owner decision |
| Fresh empty or measured-zero | Dated positive result from a readable source | Can render empty/zero only with its watermark |
| Degraded model access | Reason and affected analysis | No hidden model/provider fallback or fabricated analysis |

The facade is not one atomic cross-system snapshot. Each source retains its own snapshot identity,
`captured_at`, and watermarks. Excessive skew, freshness mismatch, or authority mismatch blocks
preview/approval. Last-good applies only to a source that owns a dated snapshot, primarily CKM;
devUI must not create a durable cache over BuilderOps Cockpit live reads.

## One owner experience, internal capability providers

| Owner experience | Internal responsibility |
| --- | --- |
| The complete owner-facing shell, navigation, context, and language | devUI |
| Capabilities, evidence, gaps, candidates, freshness | CKM; always derived and non-authoritative |
| Work in motion, delivered, flawed, forgotten | BuilderOps Cockpit read-time join and its sources; internal provider, not owner destination |
| Queue, claim, lease, and activity evidence | Dispatcher and Signboard data contracts; Signboard UI remains operational/diagnostic, not owner navigation |
| Proposal and exact preview | DDO request and plan compiler |
| Approval, initiation request, typed lifecycle-command admission | Separately authenticated action boundary within devUI |
| Legal transitions and next effect | DDO reducer |
| Journal, fencing, idempotency, reconciliation, run view, outbox/effect adapters, receipts | BuilderOps control plane |
| Issue, PR, SHA, CI, review, merge, closure truth | GitHub, Git/worktree, dispatcher, verification chain |
| Model/provider/reasoning and honest degradation | Model Access Substrate, ADR-0064 |
| Future owner dispositions | ADR-0065 API and receipt boundary after its gates |

The CKM view and authenticated action region may share a shell without sharing authority. If the
action API is unavailable, reading stays available and clearly read-only. If CKM is stale or down,
active delivery does not change lifecycle. A UI failure must never create, repeat, or assume an
external effect.

This separation is an implementation and authority concern, not an owner mental model. devUI
composes the providers into one subject-centred experience and translates their technical states
into the shared owner language above. Provider identity remains reachable under **Inspect** for
provenance, repair, and diagnostics, but normal use never requires opening a CKM, Cockpit, or
Signboard product. A provider failure degrades only the claims it owns and remains visible in the
same devUI context; it does not redirect the owner to another subsystem.

## Information architecture

The detailed visual design must go through Yggdrasil design handoff before implementation. devUI has
three connected owner views, not separate capability, work, agent, Cockpit, CKM, Signboard, and
receipt products:

1. **Overview** — the three zones: Now, Needs you, and Ready to try, including the optional
   read-only SoI Evidence View lens over a named Product/Runtime SoI scope.
2. **Focus** — one selected item with its capability context, work chain, evidence, gaps, sources,
   and progressive technical detail.
3. **Command and receipt** — exact proposal/preview, lawful owner controls, live progress, terminal
   result, and reassessment, all attached to the same selected item.

Capabilities, work, evidence, and receipts are lenses within these views, not additional top-level
modes. Moving from overview to focus to command and receipt preserves the selected item,
goal, scope, evidence, and owner-facing state.

### DEVUI-OVERVIEW-BOUNDARY — server-declared read model

The first usable devUI increment is a server-declared, read-only Overview projection. It is a pure
adapter over `devui.composition.v1`, not a source reader or a browser classification layer. Its
contract version is `devui-overview-view.v1` and its output is rebuilt per request:

```yaml
contract_version: devui-overview-view.v1
authority: projection_only
composed_at: RFC3339
trust_frame:
  provider_states: [SourceState.v1]
  limitations: [Limitation.v1]
now: [OverviewItem.v1]
needs_you: [OverviewItem.v1]
ready_to_try: [OverviewItem.v1]
root_references: [TypedRootReference.v1]
soi_evidence_lens: SoIEvidenceReference.v1 | null
limitations: [Limitation.v1]
```

`OverviewItem.v1` carries one typed subject reference, a server-declared zone, a source-backed
reason for that placement, independent source freshness/completeness/cardinality/linkage/refusal
or withdrawal evidence, and typed navigation references only. It does not copy a Focus payload, a
SoI payload, a delivery run, or a Builder System Control payload into a shared object.

The three zones have strict eligibility:

- **Needs you** requires an explicit named owner-authority category and its governing source
  reference. The only eligible categories are `irreversible_external_effect`,
  `security_privacy_cost_commitment`, `production_release_operator_action`, and
  `contradictory_source_authority`. Missing, unknown, stale, unread, unavailable, refused,
  unsupported, or unlinked authority evidence withdraws the classification; it is not an empty
  decision list or a technical decision.
- **Ready to try** requires a receipt-backed ready-to-try fact. Delivery, merge, Issue closure,
  availability, ready-to-try, owner trial, and owner acceptance remain independent facts; none is
  inferred from another.
- **Now** presents the remaining server-declared read situation without promoting technical blocks
  into owner decisions or treating degraded input as zero/empty.

The composer performs no source reads, I/O, network access, cache lookup, persistence, task/graph
or session operation, mutation, or browser-state classification. It preserves producer-exact
withdrawals and each evidence axis through composition. Inferred correlations are refused. Focus,
Product/Runtime SoI Evidence, delivery execution, and Builder System Control are separate roots:
links are typed navigation references, never joins or inherited state. A failed or unsupported root
withdraws only the dependent reference and leaves the remaining read view usable.

The optional `soi_evidence_lens` is a reference to the delivered bounded SoI Evidence View v0 proof;
it retains that proof's explicit Product/Runtime denominator and current/target claim horizons. It
does not classify Overview items or become a maturity, priority, or lifecycle authority.

This contract is a nonvisual prerequisite. A local GET-only route may expose it after its own
bounded implementation proof. A visual shell remains separately gated by the governed Yggdrasil
design handoff; neither a browser nor a shell may reclassify the server result or add durable
selection state.

The pure composer is implemented in `app/builderops/devui_overview.py`. It accepts only the
composition envelope, explicit producer evidence, and typed root references; without actionable
producer evidence it reports the affected **Needs you** or **Ready to try** classification as
withdrawn. This does not deliver producer enrichment or a visual shell; the admitted local GET
route rebuilds the composition and passes no candidates to this composer.

#### ARO-01 source-authority resolution (2026-08-10)

The owner authorized continued work only when explicit source-backed facts improve decision quality
with low cognitive load. The live source audit for Stage A found no existing serialized producer
contract that satisfies the Overview boundary for either zone:

| Overview fact | Current canonical source/field | Decision | Consequence |
| --- | --- | --- | --- |
| **Needs you** owner authority | None. The dispatcher Human Exception packet exposes only the coarse `failure_class`; it does not serialize one of the four Overview categories with a stable subject and governing-source reference. | No current owner is admitted. | The zone remains withdrawn; `agent:needs-human`, technical state, merge, done, closure, and generic terminal receipts are not substitutes. |
| **Ready to try** | None. No existing producer or receipt contract owns an explicit `ready_to_try` fact with subject linkage, availability, and freshness. | No current owner is admitted. | The zone remains withdrawn; delivery, merge, closure, availability, owner trial, and owner acceptance remain independent facts. |

This is a source-ownership result, not a new devUI authority. The existing GitHub → Cockpit →
`devui.composition.v1` chain may transport these facts only after a separately governed source
contract exists; it may not manufacture them or persist a replacement. Because no current source
was admitted, ARO-02 was superseded: there are no authorized facts for the producer chain to
enrich. Until a separately governed source contract exists, producers and the composer must
preserve the explicit withdrawal state.

#### ARO dependency/status truth

ARO-02 / [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743) is superseded by the
accepted no-source decision: there is no producer enrichment to implement until a separately
governed source contract exists. ARO-03 / [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744)
therefore exposes the existing `devui-overview-view.v1` composer through the admitted local GET
route without candidates. It preserves the composer's `classification_withdrawn` limitations for
both **Needs you** and **Ready to try**, rather than fabricating facts or measured-empty claims.

### DEVUI-FCP-BOUNDARY — Focus and Conversation Port

The first Focus slice is subject-centred. Its subject is exactly one stable GitHub Issue or one
capability reference whose owning document gives it a stable identity. Focus does not accept a
provider session, transcript, worker, PR, free-form search result, or CKM-only capability identity
as its primary subject.

Focus presents, in this order:

1. owner intent and why this subject is in view;
2. the governing source and any subordinate source references;
3. current evidence and explicit gaps;
4. delivery or inquiry receipts that are actually linked to the subject;
5. material risks and limitations;
6. the next legal step, its governing workflow, and who may take it; and
7. execution observations only when an owning source supplies an explicit correlation.

An execution observation never becomes work or delivery truth because its provider, timestamp,
repository, branch text, or prose resembles the selected subject. An observation without an exact
governed correlation whose authority identity matches the selected subject is rendered as
**unlinked** or omitted from the default Focus view. The same subject-authority check applies to
linked receipts. devUI does not infer or persist that link.

The **Conversation Port** is a contextual region of Focus, not an agent or session browser. It
creates a bounded, hash-addressed `ConversationContextPack.v1` and opens or exports that pack to an
external Codex or Claude interaction. The provider may reason over the pack and return a
disposition, decision brief, plan, inquiry recommendation, governed workflow route, or no-action
result. Provider turns, transcripts, session identifiers, usage, and model metadata remain
provenance. They do not authorize work, delivery, repository mutation, or a durable disposition.

Before any durable consequence, the conversation must yield a `TypedCommandProposal.v1` bound to
the exact context-pack hash. The proposal names exact inputs, source references, destination
workflow, expected side effects and explicit non-effects, approval rule, freshness expiry, expected
receipt, and one confirmation pair: **Start/Hold** for initiating a workflow or **Apply/Hold** for
applying an already governed change. Changed inputs, sources, destination, or freshness invalidate
the preview. Conversation prose is never an executable command.

The first and only command admitted by this slice is **Start Model Inquiry**. Its preview routes the
exact question artifact through `.codex/skills/start-model-inquiry/SKILL.md`, uses **Start/Hold**,
and expects the existing artifact-first terminal response fields: `inquiry_id`, `final_state`,
`terminal_receipt_id`, and `human_readable_report`. It creates no GitHub Issue, repository change,
delivery run, CKM claim, or provider-session authority. An ambiguous launch outcome is shown as
ambiguous, preserves the governed lock/staged-question recovery posture, and is never retried by
devUI.

The local-only devUI read admission is not action authentication. **Start** remains unavailable
until the separately authenticated action boundary binds the owner principal to the exact proposal.
The destination must also persist a proposal-scoped operation key in the existing Model Inquiry
artifacts and return the prior inquiry/receipt or an honest active/ambiguous readback on replay;
single-flight locking alone is not refresh-safe idempotency. This adds no devUI task store.

This slice does not deliver an embedded chat runtime, transcript store, provider-session discovery,
global session view, direct GitHub or repository mutation, generic command language, or parallel
task store. The external provider interaction can be unavailable or unsupported without degrading
the read-only Focus view.

### DEVUI-BSC-BOUNDARY — Builder System Control lens

**Builder System Control** is a separate control-oriented lens for the Builder System itself. It is
not a tab, evidence group, or command region inside a capability/Issue Focus canvas. Entering it
replaces the subject context with an explicit Builder System scope and a distinct header; returning
to Focus restores the prior subject without carrying control-lens claims into that subject.

The lens orients the owner to:

- governing documents, their role, authority, owner, lifecycle, and freshness;
- skills as versioned workflow adapters whose contracts bind their inputs, outputs, triggers, and
  authority limits;
- MCPs, connectors, scripts, and CLIs as bounded capabilities owned by workflows, never policy
  owners;
- policy and source coverage, freshness, drift, exceptions, measured-empty observations, and
  unknowns; and
- explicitly evidenced deviations between intended governance and observed delivery routes.

The lens may link to a stable Focus subject or route the owner to an existing governed workflow. A
later slice may present typed command proposals, but each proposal must still cross the workflow's
existing approval and receipt boundary. The lens does not decide policy, advance workflows, persist
tasks, reconcile source truth, invent correlations, or become a source of truth. It is a
read-time/rebuildable orientation and deviation projection over existing owner documents,
BuilderOps records, live delivery evidence, and bounded capability declarations.

Focus and Builder System Control therefore share presentation primitives and evidence-state
semantics, but not primary identity, navigation state, authority, correlation, or command scope:

| Concern | Focus + Conversation Port | Builder System Control |
| --- | --- | --- |
| Primary identity | One stable Issue or capability | One explicit Builder System governance scope |
| Owner question | What does this subject mean, and what is its next legal step? | Is the Builder System governed and operating as intended? |
| Evidence | Subject-governing and explicitly correlated sources only | Governance sources, capability declarations, coverage, and route observations |
| Conversation | External reasoning over one hash-bound subject pack | Not part of the first slice |
| First command | Start Model Inquiry through the existing skill | None |
| Prohibited authority | Work/session/task/delivery authority | Policy/workflow/task/source-of-truth authority |

The Focus-side boundary lives in `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`. The detailed
control-lens source, state, coverage, deviation, interaction, and sequencing contracts live in
`docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md`. Both are target specifications; neither reference
claims that the Builder System Control runtime or UI is delivered.

### Visual composition hypothesis (pre-handoff)

The following is a candidate composition brief for the governed Yggdrasil design handoff, not an
accepted visual contract. The binding contract is the information behavior: preserve the selected
subject and goal, expose situation → meaning → next step, keep evidence and provenance reachable,
and make authority-bearing actions visually distinct. The handoff may revise geometry, proportions,
components, typography, motion, or responsive treatment while preserving those behaviors. No visual
implementation may treat this sketch as final before the handoff receipt exists.

The candidate cockpit is asymmetric rather than three equal dashboard columns. **Now** is the wide
situation field because it carries the system model. **Needs you** is a compact, high-salience
decision rail. **Ready to try** is a compact result rail below it. A calm trust frame spans the top
and states when the picture was assembled, which sources are degraded, and which claims have been
withdrawn. Source health must not compete visually with actual owner decisions.

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Trust frame · when this picture was assembled · material blind spots │
├───────────────────────────────────────────────┬──────────────────────┤
│ NOW — primary situation field                 │ NEEDS YOU            │
│ what is moving · blocked by system · next     │ one decision at a time│
│                                               ├──────────────────────┤
│ stable work/capability rows                   │ READY TO TRY         │
│                                               │ result · how · limits │
└───────────────────────────────────────────────┴──────────────────────┘
```

In the candidate interaction, selecting any row opens one focus canvas inside the same shell. The
selected subject remains named in a persistent context header. The main region explains situation,
meaning, and next step; an adjacent evidence region exposes capability evidence, work chain,
receipts, provenance, and then technical detail. This avoids making the owner alternate between a
summary screen, a decision screen, and a source screen to understand one choice.

The contextual command region occupies one stable place in the focus canvas and changes role
without changing context: no lawful owner action → proposal/preview → exact approval → live run and
legal controls → terminal receipt and try guidance. Read-only analysis and source links remain
visually distinct from authority-bearing actions.

The candidate narrow-layout behavior stacks the same regions and keeps the same names, item
identity, information depth, and evidence order. Narrow mode must not collapse into a technically
different product or require a horizontal delivery graph.

## Current state and target

Delivered now:

- CKM core, query/snapshot contracts, and generated Development Overview;
- static, inert CKM Cockpit Direction B;
- BuilderOps Cockpit `/cockpit` as a fresh, read-only work register;
- `devui.composition.v1` at GET `/api/devui/composition`, a per-request projection that preserves
  independent Cockpit and CKM authority, snapshots, completeness, and typed refusals without
  persistence or mutation;
- `FocusView.v1` / `focus-view.v1`, a pure subject-centred projection with explicit correlation,
  delivered by #4694 / PR #4703;
- admitted local GET `/api/devui/focus` for one stable governed GitHub Issue, rebuilding the
  delivered `focus-view.v1` projection per request without a root-payload join, persistence,
  command, cache, session, or browser UI, implemented by #4768 / PR #4771;
- `conversation-context-pack.v1` and its non-authoritative external disposition composer, delivered
  by #4696 / PR #4704; and
- the bounded, read-only SoI Evidence View v0 proof composer and immutable fixtures, delivered by
  #4710 / PR #4711;
- the pure `devui-overview-view.v1` server-side composer, which preserves missing producer
  classification as an explicit withdrawal rather than an empty owner or ready list;
- admitted local GET `/api/devui/overview`, rebuilding live composition and invoking the delivered
  Overview composer without candidates, delivered by #4744 / PR #4772;
- DDO-01 through DDO-04 fast lane, contracts, plan compiler, reducer, and WorkerRuntime seam; and
- parts of the BuilderOps API/PostgreSQL control-plane development baseline.

Not delivered now: one devUI shell; request/preview/authenticated approval in one owner experience;
PostgreSQL authority cutover; full live run controls; receipt-to-CKM reassessment in the unified
surface; Focus browser UI, capability-subject route, and Overview-to-Focus
navigation; provider conversation runtime; authenticated command preview/Start/Hold;
the Builder System Control lens; visual shell; owner pilot and tried-by-owner acceptance; and
ADR-0065 dispositions.

The target turns the current cockpits and Signboard from competing owner destinations into internal
providers: Direction B stays an exportable/static evidence fallback, BuilderOps Cockpit supplies
the work view, Signboard supplies dispatcher-owned operational evidence, and the planned delivery
console becomes devUI's authenticated decision/run mode behind a separate trust boundary. Their raw
routes may remain available for diagnostics and recovery, but devUI is the normal owner entry.

## Owner-experience acceptance criteria

- [ ] The first view answers Now, Needs you, and Ready to try without owner-side reconstruction.
- [ ] One selected item can be followed from overview to terminal receipt without product switching
      or recreating context.
- [ ] Focus is bound to one stable Issue or capability and shows intent, governing source,
      evidence, receipts, risks, next legal step, and only explicitly correlated execution
      observations.
- [ ] The Conversation Port exports a scoped hash-bound context pack externally without creating a
      transcript store, task store, inferred work link, or global session view.
- [ ] A durable consequence requires a fresh typed proposal with exact inputs, sources,
      destination, side effects, approval rule, expiry, expected receipt, and Start/Hold or
      Apply/Hold.
- [ ] Start Model Inquiry uses only the existing artifact-first workflow, produces its existing
      terminal receipt or an honest ambiguous outcome, and performs no GitHub/repository mutation.
- [ ] Builder System Control is a separate governance lens and cannot become a policy engine,
      workflow engine, task system, capability policy owner, or source of truth.
- [ ] The SoI Evidence View, when delivered, is a read-only Overview lens over an explicit
      Product/Runtime SoI denominator; it preserves typed source ownership, current/target horizon,
      independent source states, and evidence-vector components without a scalar maturity authority.
- [ ] Normal owner use never requires choosing or navigating to Cockpit, CKM, or Signboard; their
      source identity remains available only as progressive provenance and diagnostic detail.
- [ ] Each item shows one owner-facing state, why it is shown, what happens next, and whether owner
      action is legal.
- [ ] Glance, understand, verify, and inspect reveal progressively deeper information about the
      same item without dropping evidence or forcing a product switch.
- [ ] Every claim names source, freshness, and whether it is confirmed, candidate, stale, unread,
      or unavailable.
- [ ] When owner intent, a governing decision, or an acceptance criterion changes, the selected
      context shows the superseded source, consequence for active work, and which exact verification
      or owner-validation evidence was invalidated or rerun; absent linkage remains explicit.
- [ ] CKM score or model proposal cannot start or prioritize work alone.
- [ ] Preview is read-only; approval binds exact request, preview, and acceptance profile.
- [ ] Technical blocking never appears as an owner decision without explicit authority category.
- [ ] A true owner-decision view presents one decision, a recommendation, viable alternatives,
      consequences, consequence of waiting, and the exact evidence/scope the action binds.
- [ ] Quantified summaries preserve counts or denominators and cannot replace source components
      with an unexplained aggregate score.
- [ ] Active runs can reconnect without duplicate workers or effects.
- [ ] The surface degrades honestly to read-only when the action boundary is unavailable.
- [ ] Terminal receipts show actual outcome and update CKM only as derived evidence.
- [ ] Normal owner flow needs no technical identifier.
- [ ] No persisted graph, parallel intent object, or second task/state system is introduced for the
      owner experience.
- [ ] The visual surface has passed Yggdrasil design handoff and desktop, narrow/200%, keyboard,
      degraded, and many-at-once validation.

## Mechanism owners and related documents

- CKM decision: `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- CKM foundation and measurement limits: `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md` and
  `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- Static CKM surface: `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- Live work register: `docs/BUILDEROPS_COCKPIT/README.md`
- Builder System process: `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- Delivery orchestration: `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- BuilderOps control plane: `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md` and
  `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- Model access: `docs/adr/ADR-0064-model-access-substrate.md`
- Temporal intention authority: `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- Evidence synthesis: `docs/audits/DEVUI_ARCHITECTURE_2026-08-06.md`
- Intent–evidence governance synthesis:
  `docs/audits/BUILDER_SYSTEM_INTENT_EVIDENCE_GOVERNANCE_2026-08-10.md`
- Implementation order: `docs/plans/DEVUI_IMPLEMENTATION.md`
