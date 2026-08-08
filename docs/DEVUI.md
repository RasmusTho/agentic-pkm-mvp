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
Last reviewed: 2026-08-08
Last verified against: `origin/main` `da85670ce0f9f1ba55eb7a5423967407a9c639ad`, ADR-0057,
ADR-0062, ADR-0064, ADR-0065, the CKM and BuilderOps Cockpit owner contracts, and the Deterministic
Delivery Orchestration specification.

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

devUI may render a derived chain or graph, but it does not persist a Delivery Knowledge Graph or
copy source lifecycle state. A new dashboard module, top-level mode, status, or durable entity is
out of scope unless it removes an owner reconstruction step that the three zones cannot answer.

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

1. **Overview** — the three zones: Now, Needs you, and Ready to try.
2. **Focus** — one selected item with its capability context, work chain, evidence, gaps, sources,
   and progressive technical detail.
3. **Command and receipt** — exact proposal/preview, lawful owner controls, live progress, terminal
   result, and reassessment, all attached to the same selected item.

Capabilities, work, evidence, and receipts are lenses within these views, not additional top-level
modes. Moving from overview to focus to command and receipt preserves the selected item,
goal, scope, evidence, and owner-facing state.

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
- DDO-01 through DDO-04 fast lane, contracts, plan compiler, reducer, and WorkerRuntime seam; and
- parts of the BuilderOps API/PostgreSQL control-plane development baseline.

Not delivered now: a composed versioned read contract; one devUI shell; request/preview/authenticated
approval in one owner experience; PostgreSQL authority cutover; full live run controls; receipt-to-
CKM reassessment in the unified surface; owner pilot and tried-by-owner acceptance; and ADR-0065
dispositions.

The target turns the current cockpits and Signboard from competing owner destinations into internal
providers: Direction B stays an exportable/static evidence fallback, BuilderOps Cockpit supplies
the work view, Signboard supplies dispatcher-owned operational evidence, and the planned delivery
console becomes devUI's authenticated decision/run mode behind a separate trust boundary. Their raw
routes may remain available for diagnostics and recovery, but devUI is the normal owner entry.

## Owner-experience acceptance criteria

- [ ] The first view answers Now, Needs you, and Ready to try without owner-side reconstruction.
- [ ] One selected item can be followed from overview to terminal receipt without product switching
      or recreating context.
- [ ] Normal owner use never requires choosing or navigating to Cockpit, CKM, or Signboard; their
      source identity remains available only as progressive provenance and diagnostic detail.
- [ ] Each item shows one owner-facing state, why it is shown, what happens next, and whether owner
      action is legal.
- [ ] Glance, understand, verify, and inspect reveal progressively deeper information about the
      same item without dropping evidence or forcing a product switch.
- [ ] Every claim names source, freshness, and whether it is confirmed, candidate, stale, unread,
      or unavailable.
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
- Implementation order: `docs/plans/DEVUI_IMPLEMENTATION.md`
