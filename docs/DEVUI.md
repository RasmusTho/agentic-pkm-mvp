State: Proposed target-state owner-function contract, pending Product Owner acceptance. `devUI` is
the working owner-facing name. The CKM Development Overview and BuilderOps Cockpit are delivered as
separate read-only surfaces; the unified experience, authenticated approval path, live delivery
controls, and receipt loop described here are not yet delivered.
Doc role: Builder System owner-function and experience contract
Authority: Proposed owner contract for what the Product Owner must be able to understand, decide,
initiate, follow, and accept through devUI. It becomes canonical only after explicit owner
acceptance. Existing CKM, delivery, authentication, execution, and GitHub contracts remain binding.
Owner: Builder System governance
Temporal class: Strategic target state with an explicit current-state section
Review cadence: Event-driven
Source of truth: Accepted ADRs and linked capability specifications remain binding while this
contract is proposed. After acceptance, this document owns the experience; live GitHub, CI,
dispatcher, and receipt evidence continues to own delivery truth.
Last reviewed: 2026-08-06
Last verified against: `origin/main` `3f140bba2c677c37d81b7e166133e24e4e182845`, ADR-0057,
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

The proposed owner loop is:

```text
understand → choose → review proposal → approve the exact previewed delivery proposal
→ follow by exception → receive a receipt → try and reassess
```

In system terms:

```text
intent → capability → evidence and gaps → delivery request → preview
→ approval → delivery run → receipt → CKM reassessment
```

This is one experience, not merged authority. CKM only describes. The authenticated delivery
boundary approves exact scope. GitHub, CI, review, merge, and closure prove what happened.

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

The home view answers, in order:

1. What is moving now?
2. What needs attention?
3. What genuinely needs my decision?
4. What was delivered recently and is ready to try?

The first view uses owner language and freshness. A dead or unread source must never look like zero.

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

## One experience, separate internal responsibilities

| Owner experience | Internal responsibility |
| --- | --- |
| Shared navigation, context, and owner language | devUI shell |
| Capabilities, evidence, gaps, candidates, freshness | CKM; always derived and non-authoritative |
| Work in motion, delivered, flawed, forgotten | BuilderOps Cockpit read-time join and its sources |
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

## Information architecture

The detailed visual design must go through Yggdrasil design handoff before implementation. devUI has
five connected modes, not five products:

1. **Overview** — movement, attention, true owner decisions, and items ready to try.
2. **Capabilities** — system capability, evidence, gaps, change, and optional technical detail.
3. **Work** — the live chain across work in progress, delivered, flawed, and forgotten.
4. **Decision and run** — proposal, preview, exact approval, live progress, and typed controls.
5. **Receipts and learning** — terminal result, CKM reassessment, learning evidence, and future
   durable owner acceptance only if INV-DG-7 is approved.

Moving from a capability to proposal to run preserves capability, goal, scope, and evidence.

## Current state and target

Delivered now:

- CKM core, query/snapshot contracts, and generated Development Overview;
- static, inert CKM Cockpit Direction B;
- BuilderOps Cockpit `/cockpit` as a fresh, read-only work register;
- DDO-01 through DDO-04 fast lane, contracts, plan compiler, reducer, and WorkerRuntime seam; and
- parts of the BuilderOps API/PostgreSQL control-plane development baseline.

Not delivered now: a composed versioned read contract; one devUI shell; request/preview/authenticated
approval in one owner experience; PostgreSQL authority cutover; full live run controls; receipt-to-
CKM reassessment in the unified surface; owner acceptance; and ADR-0065 dispositions.

The target turns the current cockpits from competing owner products into sources: Direction B stays
an exportable/static evidence fallback, BuilderOps Cockpit supplies the work view, and the planned
delivery console becomes devUI's authenticated decision/run mode behind a separate trust boundary.

## Owner-experience acceptance criteria

- [ ] A capability can be followed from overview to terminal receipt without product switching or
      recreating context.
- [ ] Every claim names source, freshness, and whether it is confirmed, candidate, stale, unread,
      or unavailable.
- [ ] CKM score or model proposal cannot start or prioritize work alone.
- [ ] Preview is read-only; approval binds exact request, preview, and acceptance profile.
- [ ] Technical blocking never appears as an owner decision without explicit authority category.
- [ ] Active runs can reconnect without duplicate workers or effects.
- [ ] The surface degrades honestly to read-only when the action boundary is unavailable.
- [ ] Terminal receipts show actual outcome and update CKM only as derived evidence.
- [ ] Normal owner flow needs no technical identifier.
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
