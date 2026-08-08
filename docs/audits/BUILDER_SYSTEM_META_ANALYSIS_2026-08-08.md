State: Advisory architecture audit snapshot, 2026-08-08. Repository baseline: `origin/main` at `1956594d1ff86ef4cabb13b3f3ffc6f52e7a1f8d`. Subordinate to current owner docs, accepted ADRs, and live GitHub contracts. No implementation, ADR, or Issue mutation is authorized by this audit.
Doc role: Reference (architecture audit)
Authority: Evidence-based Builder System analysis. Owner docs win on disagreement; this audit names gaps and recommendations but does not promote target-state intent into shipped truth.
Owner: Builder System governance
Temporal class: advisory snapshot
Review cadence: event-driven after owner decision, DDO/BuilderOps authority changes, or the next devUI design/implementation slice
Source of truth: `docs/DOCS_INDEX.md` for document routing; cited owner docs and live GitHub objects for the claims in this audit

# Builder System meta-analysis — development model, authority, and owner cockpit

## 1. Charter and method

This pass evaluates Builder System as one development-enabling system across intent, research,
design, docs-as-code, issue planning, agent execution, GitHub delivery, verification, release, and
learning. It does not compare Builder System to Claude Design as a product and does not recommend
copying another tool.

The analysis uses the live `origin/main`, the current Builder System owner model, the existing devUI
contract, the dispatcher contract, the current skill routing, prior BuilderOps/DDO audits, and live
GitHub issue state. The prior delivery-graph audit is treated as evidence, not as a new authority.

Research questions:

1. Is the end-to-end lifecycle complete and correctly ordered?
2. Does every semantic/state category have one normative authority?
3. What is missing between research/design and executable delivery?
4. Is a Delivery Knowledge Graph useful, or would it become a second authority?
5. How should Claude/Codex sessions communicate durably without chat becoming authority?
6. What is the smallest architecture that can support more capabilities, agents, and parallel work?

## 2. Executive verdict

Builder System is structurally mature but not yet cognitively unified. The missing piece is not another
agent, graph database, dashboard, or central orchestrator. The missing piece is a small **promotion
and traceability kernel** that makes the existing authority boundaries legible from owner intent to
accepted outcome.

The current architecture already has the correct broad separation:

- docs define intent, contracts, and owner boundaries;
- GitHub Issues are executable task contracts;
- dispatcher state coordinates claims and leases;
- agents execute bounded work in isolated worktrees;
- GitHub, Git, CI, review, merge, and closure remain delivery truth; and
- BuilderOps records operational learning and projections without becoming Product/Runtime truth
  (`docs/ARCHITECTURE.md:718-785`, `docs/architecture/SBS_OPERATING_MODEL.md:187-220`).

The system nevertheless has a discontinuity at the top and bottom of the delivery graph. The only
CI-enforced machine edge is PR → Issue; intention → need → capability → parent/child task edges are
absent or prose, and owner acceptance has no general receipt contract
(`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md:38-53,55-68,90-102`).

Therefore:

- keep the existing authority topology;
- build a read-time Delivery Trace projection only after its join keys are repaired;
- do not create a second graph authority or a parallel task/state system;
- add one explicit research/design-to-normative-promotion decision boundary;
- make owner acceptance distinct from merge, release, and terminal delivery; and
- use one stable context/handoff envelope for Claude, Codex, and other replaceable workers.

## 3. What is already strong

### 3.1 Boundary and authority doctrine

The design principles explicitly require boundary-first design, capability composition, separated
layers, narrow mutation authority, governance before autonomy, and contracts over implementations
(`docs/DESIGN_PRINCIPLES.md:53-104`). This is the correct foundation for a multi-agent Builder System.

The Builder System boundary is also explicit: it governs development-time work and must not be
confused with Product/Runtime semantics (`docs/ARCHITECTURE.md:718-785`; `docs/architecture/SBS_OPERATING_MODEL.md:68-93`).

### 3.2 Delivery truth is correctly externalized

The current model gives GitHub Issues canonical task-contract status, dispatcher SQLite claim/lease
coordination, and GitHub/PR/CI/merge/closure delivery truth. Project status and BuilderOps projections
are explicitly rebuildable or advisory (`docs/ARCHITECTURE.md:723-785`; `docs/architecture/SBS_OPERATING_MODEL.md:187-199`).

This is better than making a cockpit, chat transcript, or local agent database authoritative.

### 3.3 The workflow has most operational stages

The process map already identifies intent, docs/spec authority, contract, dispatch, execution,
verification, closure, continuous improvement, and exception layers
(`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:27-41`). The skills cover docs governance,
architecture research, design handoff, issue intake, implementation, publication, verification,
release, and learning. The chain is not missing a large number of named tools; it is missing a few
explicit crossings between them.

### 3.4 The devUI boundary is appropriately conservative

The accepted devUI contract makes CKM and BuilderOps read models lenses rather than authority, keeps
the action boundary separately authenticated, preserves GitHub/CI/closure truth, and requires the
Yggdrasil design handoff before visual implementation (`docs/DEVUI.md:219-275,277-317`). Its plan
also explicitly forbids a new graph store, task system, or parallel control plane
(`docs/plans/DEVUI_IMPLEMENTATION.md:20-34`).

## 4. End-to-end lifecycle assessment

The proposed lifecycle in the meta-prompt is directionally right, but it needs branching and explicit
promotion gates. Not every idea becomes an Issue, not every merge is a release, and not every delivery
produces an owner-usage acceptance.

| Stage | Current authority and evidence | Assessment | Required clarification |
|---|---|---|---|
| Intent | Human intent, owner docs, decisions, and Issue contracts; intent is described in the process map (`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:27-32`) | Present, but no stable Builder-side intent object | Keep intent in the owner/product plane until its authority and privacy semantics are decided; do not invent a BuilderOps intent store. |
| Research | Architecture-research audits, model inquiry, research docs, and source anchors | Present as specialist paths | Add an explicit disposition: accepted input, rejected, deferred, or needs owner decision. A research document alone must not authorize work. |
| Design | Yggdrasil handoff and local owner/spec docs; design output is Builder material, not Product truth (`docs/architecture/SBS_OPERATING_MODEL.md:201`) | Present, but the promotion seam is implicit | Require a handoff/promotion reference from accepted design intent to the owner doc or specification that implementation will use. |
| Normative documentation | Owner docs, ADRs, specs, plans, and `DOCS_INDEX` roles (`docs/DESIGN_PRINCIPLES.md:154-191`) | Strong role separation | Preserve one owner per claim; do not turn an audit or UI projection into normative authority. |
| Issue generation | GitHub Issue is the canonical executable task contract, with `Verify:` targets (`docs/ARCHITECTURE.md:742-754`; `.codex/skills/docs-to-issue/SKILL.md:30-59`) | Strong for implementation slices | Make the spec-task → Issue join a filing-time invariant everywhere, not only in the best-formed directories. |
| Claim and dispatch | `agent:ready`, dispatcher task IDs, leases, heartbeats, and isolated worktrees (`docs/AGENT_ISSUE_DISPATCHER.md:132-180,442-567`) | Operationally clear | Keep this as coordination state, not semantic task truth. |
| Implementation | `issue-to-code`, skills, agents, local validation, PR publication | Strong and bounded | Standardize the worker context/invocation/result envelope as DDO becomes executable; do not use chat as the handoff. |
| Verification | PR head, CI checks, review threads, exact Issue set, merge/closure receipts | Strong in the middle of the graph | Verification records must remain joinable to Issue/task without depending only on PR-body parsing. |
| Release/promotion | Release-channel plans, test/prod promotion, verification and rollback receipts | Present as a separate workflow | Treat release as conditional: a repo delivery can stop at merge, test verification, or production verification according to an immutable acceptance profile. |
| Owner acceptance/usage | Only a narrow production receipt example exists; the general graph has no owner-acceptance receipt (`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md:90-97`) | Missing | Define later, separately from delivery and merge. “Ready to try” is not “tried by owner.” |
| Learning | BuilderOps `LearningSignal`, retrospectives, issues, PromotionIntent, and docs/skill updates (`docs/architecture/SBS_OPERATING_MODEL.md:272-313`) | Present, but trigger-based | Capture only concrete divergence or reusable evidence; do not create a learning record for every normal delivery. |

The correct sequence is therefore a state machine with exits, not a mandatory linear conveyor:

```text
Intent
  └─ research → disposition
       ├─ discard / defer / owner decision
       └─ accepted design → normative doc/spec
             └─ bounded Issue → claim → implementation → PR
                   └─ verify → merge/closure receipt
                         ├─ optional promotion → channel receipt
                         ├─ optional owner acceptance → usage receipt
                         └─ divergence → BuilderOps learning / bounded follow-up
```

## 5. System-of-record model

The meta-prompt's “one normative source for every information category” is correct only if
“category” is defined narrowly. A single system of record for the entire delivery graph would be
wrong. The current architecture intentionally distributes authority by category.

| Information category | Normative authority | Derived/read surfaces | Must not become authority |
|---|---|---|---|
| Product intent, needs, and normative human decisions | Product owner docs, ADRs, and the owner-controlled plane | Builder context packs and cockpit explanations | BuilderOps, CKM, chat, or GitHub labels |
| Builder workflow policy | `AGENTS.md`, `.codex/skills/**`, SBS operating model, governance docs | Agent adapters, process map, PR/Issue validators | A model session or an uncommitted prompt |
| Capability meaning and acceptance intent | Capability owner doc, ADR, or specification directory | CKM capability/evidence projection | CKM score or dashboard card |
| Specification shape and implementation intent | Specification/task docs | GitHub Issue body and PR context | A generated Issue summary that drops source anchors |
| Executable task contract and lifecycle | GitHub Issue state, labels, body, and comments | Project, dispatcher task, CKM links | Project status or a BuilderOps projection |
| Claim/lease/heartbeat state | Dispatcher SQLite and worktree/branch leases | Signboard and cockpit | GitHub label alone or chat reservation |
| Code and review state | Git, PR, CI, review threads, merge commit | Verification/CKM/BuilderOps receipts | Local session summary |
| Durable Builder operational state | BuilderOps records and receipts | Generated projections and learning summaries | Product/runtime memory or owner docs without promotion |
| Release-channel state | Release refs, channel manifests, promotion and health receipts | devUI result view | A green PR check or a local image |
| Owner acceptance/usage | A future explicit acceptance receipt | devUI “tried by owner” projection | Merge, “ready to try,” or chat confirmation |

The governing rule should be: **one authority per semantic or lifecycle category, explicit references
between categories, and projections that never silently promote themselves.** This is stronger and
more truthful than “one database” or “one graph.”

## 6. Main weaknesses and contradictions

### F1 — The lifecycle has no explicit research/design promotion boundary

Research, design handoff, docs authoring, and issue generation are individually defined, but the
system does not expose one canonical record saying: “this research/design result was accepted as the
source for this normative doc/spec.” The existing process map calls docs/spec authority a layer and
Issues a contract layer, but leaves the crossing implicit (`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:27-35`).

Consequence: agents can start from a plausible design artifact or conversation and skip the precise
moment where owner intent becomes normative scope.

Recommendation: add a small promotion reference/receipt, not a new graph store. It should name the
source artifact, disposition, accepted target doc/spec, owner/authority class, and date. It can be a
BuilderOps `PromotionIntent` until accepted; the accepted repo doc/spec remains the authority.

### F2 — The middle of the graph is machine-joinable; the ends are not

The delivery graph audit found that PR ↔ Issue is the only CI-enforced machine edge, while parent/child
edges are prose, task-doc `github_issue:` is often empty, needs have no stable IDs, and owner
acceptance has no general receipt (`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md:38-102,129-148`).

Consequence: a cockpit can render the delivery middle, but cannot honestly answer where an Issue came
from, whether all children are represented, or whether the owner actually accepted the result.

Recommendation: repair the existing join keys in dependency order. Do not introduce a universal graph
authority.

### F3 — “Everything is traceable” is an aspiration, not current truth

The current system has strong traceability from Issue → PR → SHA → CI/review → merge/closure, but not
from intention → need → capability → specification → Issue, nor from release → owner usage. The audit
explicitly records those missing edges (`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md:129-158`).

The correct UI behavior is to show “not linked,” “not assessed,” or “not yet accepted,” never to fill
the gap with an inferred edge.

### F4 — The SoT doctrine can be misread as a single central authority

The repo's actual model is distributed by category: GitHub owns delivery truth, dispatcher owns active
coordination, BuilderOps owns builder-operational records, and CKM is projection-only
(`docs/ARCHITECTURE.md:723-735`; `docs/architecture/SBS_OPERATING_MODEL.md:187-220`). A new central Delivery
Knowledge Graph would contradict this boundary if it stored canonical lifecycle state.

The graph may be a useful **read-time join projection**, but it must not own status, task scope,
leases, acceptance, or merge truth.

### F5 — Human approval is narrower than “important decision”

The meta-prompt says human approval is needed at important decisions. The current Builder policy is
more precise: agents act by default; escalation is reserved for irreversible, external-facing, or
genuinely owner-reserved authority decisions (`AGENTS.md :: Agency default`; `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:16-25`).

Recommendation: say “human approval at owner-reserved authority boundaries,” not “important decisions.”
Otherwise routine technical choices become unnecessary cognitive load.

### F6 — Git is the common substrate, not the complete system of record

Git is authoritative for repo-governed code, docs, ADRs, skills, and generated projections, but GitHub
owns issue/PR lifecycle and CI evidence, dispatcher owns active leases, and release channels own
promotion state (`docs/ARCHITECTURE.md:723-740`; `docs/architecture/SBS_OPERATING_MODEL.md:187-199`).

Recommendation: call Git the common durable artifact substrate, not the single platform for all
coordination and lifecycle state.

### F7 — Agent communication is durable in principle but not yet one coherent envelope

The current skills provide issue contracts, worktree/branch truth, PRs, receipts, and BuilderOps
records. The prior Builder delivery audit identifies the missing provider-neutral context pack,
invocation, and result seam and its required bindings (`docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md:315-388`).

Until that seam is complete, Claude/Codex sessions should communicate through the existing Issue/PR/
BuilderOps/dispatcher boundaries and explicit handoff artifacts. Chat may explain or route, but it must
not authorize work, close an Issue, or become the only copy of a decision.

## 7. Skills assessment

The current skill catalog is broad enough to cover the main lifecycle. Adding one skill per phase would
increase routing cost and create competing process descriptions. The important distinction is between
canonical workflow entrypoints and specialist mechanisms.

| Area | Current posture | Finding |
|---|---|---|
| Discovery / intent | Process map, owner docs, human flows, issue intake | Needs a clearer disposition and promotion handoff; not necessarily a new skill |
| Research | `architecture-research`, `start-model-inquiry`, advisory audits | Good specialist coverage; keep evidence-only reports and explicit open RQs |
| Design | `yggdrasil-design-handoff`, Builder design-run contracts | Correct fail-closed boundary; accepted design must point to normative local docs |
| Docs | `docs-governance`, `docs-authoring`, temporal governance | Strong; avoid duplicating role maps in new prompts |
| Issue intake | `docs-to-issue`, `feature-breakdown`, issue readiness | Strong; repair machine joins rather than adding a graph skill |
| Code | `issue-to-code`, dispatcher, isolated worktrees | Strong bounded execution path |
| Verification | `verification-and-closure`, review gates, CI wait contracts | Strong middle-of-graph authority; owner-acceptance remains separate |
| Release | staged promotion/rollback skills | Correctly separated from merge; keep optional by acceptance profile |
| Learning | `capture-learning`, retrospective, learning-to-issue | Correct category boundary; trigger only on concrete divergence |
| Routing/meta | AGENTS, skill README, process map, TCD | The most implicit area: model choice, context assembly, and research-to-delivery promotion are distributed across prose |

The recommended skill change is therefore small: document one canonical **Builder System lifecycle
route and promotion receipt shape** in the existing routing surfaces. Do not create `wayfinder`,
`requirement-grilling`, or a generic “orchestrator” merely because an earlier audit suggested them;
promote those only if repeated work demonstrates a measurable routing failure
(`docs/audits/BUILDER_SYSTEM_SKILL_REVIEW_2026-07-09.md:53-205`).

## 8. DevUI implications

The devUI should be the owner-facing read model and command shell over existing authorities, not a
new Builder System database.

Its minimal cognitive model is:

```text
Trust frame
  ├─ NOW: what is moving, blocked, or next
  ├─ NEEDS YOU: only owner-reserved decisions
  └─ READY TO TRY: accepted results with limits

One selected subject → situation → meaning → next step → evidence → action/receipt
```

The UI must surface provenance and missing joins without exposing subsystem topology. It should show
which source produced each claim, each source's freshness/watermark, and whether a relationship is
confirmed, inferred, stale, unavailable, or absent. This is consistent with the devUI acceptance
criteria (`docs/DEVUI.md:338-360`) and the graph audit's heterogeneous freshness finding
(`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md:111-119,181-188`).

The UI must not:

- infer that a capability is delivered because a PR merged;
- infer that an owner tried a result because it is “ready to try”;
- use CKM score, model confidence, or a dashboard rank to authorize work;
- hide missing parent/child or source links;
- store a local durable task state; or
- expose a second global command language.

Stage A remains the correct next product slice: read-only composition of CKM and BuilderOps views,
after the Yggdrasil design handoff. Stage B and C must remain behind their existing DDO/BuilderOps
mechanism gates (`docs/plans/DEVUI_IMPLEMENTATION.md:64-160`).

## 9. Minimal Delivery Trace data model

Call this a **Delivery Trace projection**, not a Delivery Knowledge Graph authority. It is a read-time
join over existing sources. It should initially be materialized as a rebuildable view or response
envelope, not a new durable graph database.

### 9.1 Entities

| Entity | Owner/source | Minimum identity |
|---|---|---|
| `IntentRef` | Owner/product plane or committed research/design input | source URI, content digest, authority class, disposition |
| `NeedRef` | Product-owned human-flow/need contract when IDs exist | stable need ID, source URI, scope |
| `CapabilityRef` | Capability owner docs/spec/ADR; CKM mirrors it | capability key, boundary ref, source digest |
| `SpecTaskRef` | Committed specification/task document | task ID, spec path, source anchor, dependency refs |
| `IssueRef` | GitHub | repository, issue number, current state/labels, body digest |
| `ClaimRef` | Dispatcher/worktree lease | task ID, lease identity, worktree, branch, heartbeat |
| `DeliveryRef` | DDO/BuilderOps when active; GitHub delivery when complete | request/plan/run/effect IDs, acceptance profile |
| `CodeRef` | Git/PR/GitHub | PR number, branch, head SHA, merge SHA, changed files |
| `EvidenceRef` | CI, review threads, verification receipts | check/run ID, conclusion, review thread refs, captured timestamp |
| `PromotionRef` | Release-channel workflow | target channel, candidate SHA, promotion receipt |
| `AcceptanceRef` | Future explicit owner-acceptance contract | acceptance ID, subject, observed result, date, limitations |
| `LearningRef` | BuilderOps | LearningSignal/retrospective/PromotionIntent/receipt ID |

`IntentRef`, `NeedRef`, and `AcceptanceRef` are intentionally not invented as BuilderOps authority
objects by this audit. Their ownership must be resolved in the relevant Product/owner plane first.

### 9.2 Relationships

```text
IntentRef ──disposition──> CapabilityRef ──defines──> SpecTaskRef
NeedRef ──motivates──────────────┘              │
                                                └─filed_as──> IssueRef
IssueRef ──claimed_by──> ClaimRef
IssueRef ──delivered_by──> CodeRef ──verified_by──> EvidenceRef
CodeRef/EvidenceRef ──may_promote──> PromotionRef
EvidenceRef/PromotionRef ──may_be_accepted──> AcceptanceRef
Any concrete divergence ──may_emit──> LearningRef
```

Every relationship must carry `source_ref`, `captured_at`, and `relationship_status`:
`confirmed`, `candidate`, `stale`, `unavailable`, or `absent`. A projection must not turn an absent
edge into a guessed edge.

### 9.3 Cross-plane join keys

The minimal join kernel should reuse existing identifiers:

- `repository` + `issue_number` for GitHub task identity;
- `task_id` for dispatcher identity, implemented once rather than in two scripts;
- `spec_path` + `task_id` + `github_issue` for spec-to-Issue identity;
- `pr_number` + `head_sha` for PR and verification identity;
- `run_id` / `effect_id` / `invocation_id` for durable delivery execution;
- `merge_sha` + acceptance profile for delivery/promotion identity; and
- source snapshot/watermark/digest for CKM and cross-source freshness.

These requirements are directly grounded in the existing graph audit's join table and invariant
kernel (`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md:129-148,190-203`).

### 9.4 Provenance envelope

Every projected claim should carry:

```yaml
source_ref: "github:pull:4667"
source_kind: "github_pr"
source_version: "head_sha-or-snapshot-id"
captured_at: "timestamp"
content_digest: "optional-digest"
authority_class: "delivery|coordination|builder-ops|product|projection"
relationship_status: "confirmed|candidate|stale|unavailable|absent"
derived_from: ["other-source-ref"]
limitations: ["missing-parent-edge"]
```

This is a projection envelope, not a new semantic metadata model. It should reuse existing metadata,
snapshot, receipt, and provenance contracts where a source already has one.

## 10. Durable Claude/Codex communication

The durable communication pattern should be:

1. **Issue** — scope, constraints, source anchors, acceptance criteria, and `Verify:` targets.
2. **Dispatcher/lease** — active ownership and worktree identity.
3. **Context pack** — exact docs, Issue, base SHA, branch/worktree, allowed effects, stop conditions,
   and validation targets.
4. **Worker invocation** — provider/model/reasoning/session identity, idempotency key, and heartbeat.
5. **PR** — code/docs result and review surface.
6. **Receipt** — validation, exact head/merge, owner-doc result, residual risk, and next legal step.
7. **BuilderOps learning** — only when a concrete divergence justifies an upstream change.

The context-pack/invocation/result shape is already specified as the direction for a provider-neutral
worker seam (`docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md:315-388`). It should be adopted when
the DDO work reaches that contract, not rebuilt as an independent Claude/Codex chat bus.

Chat is useful for live orientation and human explanation. It is not a durable authority because it
does not provide a stable task contract, exact head binding, lease identity, review/CI readback, or
replay-safe closure. Any material decision from chat must be promoted to the appropriate existing
surface.

## 11. Minimal invariant kernel

The following is the smallest useful kernel for the meta-architecture. It extends existing registries
and contracts; it does not create a competing invariant registry.

| ID | Category | Invariant | Enforcement posture |
|---|---|---|---|
| BST-01 | MUST | A projection, chat transcript, worker session, CKM score, or BuilderOps record cannot grant Product/Runtime or GitHub effect authority. | Existing doctrine; retain and test at action boundaries. |
| BST-02 | MUST | Every projected claim names one source owner, source version/freshness, and relationship status. | New read-model doctor; no new authority. |
| BST-03 | GATE | A filed specification task carries its GitHub Issue identity, and parent/child edges are machine-parseable. | Partly existing; extend `feature-breakdown`/readiness validation. |
| BST-04 | MUST | One task identity derivation exists; dispatcher, claim scripts, and projections cannot silently disagree. | Violated today per `INV-DG-2`; consolidate implementation. |
| BST-05 | GATE | PR/verification/merge evidence binds repository, Issue set, PR, exact head SHA, and acceptance profile. | Middle spine largely exists; preserve exact-head gates. |
| BST-06 | MUST | Research/design material cannot authorize implementation until its disposition and normative target are explicit. | New promotion boundary; initially doc/receipt enforced. |
| BST-07 | MUST | Merge, release, and owner acceptance are distinct terminal meanings. | Delivery profiles exist; general owner acceptance remains future. |
| BST-08 | DOCTOR | A joined cockpit view reports per-source last successful read and missing/partial edges honestly. | New read-time reconciliation over existing watermarks. |
| BST-09 | MUST | Free text, including chat or model output, never drives a reducer or external effect. | Existing DDO target invariant; retain. |

Minimal kernel: **BST-01, BST-02, BST-04, BST-05, and BST-08**. BST-03, BST-06, and BST-07 are
the next traceability expansion. Everything else is defense in depth.

## 12. Alternatives

### A — Read-time Delivery Trace over existing authorities — recommended

Repair existing IDs and structured edges, then compose a rebuildable projection for devUI. Lowest
authority risk, reuses CKM/BuilderOps/GitHub/dispatcher, and directly improves owner visibility.

### B — New graph database as a canonical Delivery Knowledge Graph — reject

It would duplicate Issue, dispatcher, BuilderOps, CKM, and release state; create write ordering and
reconciliation problems; and violate the existing no-parallel-authority devUI rule
(`docs/plans/DEVUI_IMPLEMENTATION.md:20-34`). A graph database may become a later technical index
only if a measured read-time join problem justifies it and its non-authority status is explicit.

### C — Central Builder System orchestrator owning all lifecycle state — defer/reject as default

The DDO/BuilderOps direction already provides bounded orchestration while preserving GitHub delivery
authority. A central product would increase coordination and failure blast radius before the existing
mechanism chain is complete. Continue the existing DDO reconciliation instead
(`docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md:593-608`).

### D — More skills and more UI modes — reject for now

The skill catalog already covers the main routes. Additional phase-specific skills or top-level UI
views would increase routing and cognitive load without fixing the missing join/promotion contracts.

## 13. Prioritized change plan

### P0 — Accept the architecture boundary

1. Treat this audit as advisory only.
2. Do not create a graph store, central task system, or chat authority.
3. Treat `docs/DEVUI.md`'s geometry as a design hypothesis until the Yggdrasil handoff is accepted.
4. Continue Stage A as a read-only composition of existing CKM and BuilderOps views.

### P1 — Repair the existing traceability kernel

Reconcile with existing work; do not create a parallel epic:

1. Consolidate `task_id` derivation (`INV-DG-2`).
2. Make parent/child Issue edges machine-parseable and enumerable (`INV-DG-3`, `INV-DG-4`).
3. Enforce and backfill `github_issue:` in filed task specifications (`INV-DG-5`).
4. Expose per-source last-successful-read/freshness in the read-time join (`INV-DG-6`).
5. Keep the work aligned with DDO parent #4163 and children #4167–#4170, and with the existing
   BuilderOps/devUI work rather than filing a new architecture epic
   (`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md:213-225`; current open issues include
   #4163, #4168, #4169, and #4170).

### P2 — Add the promotion boundary

Draft one ADR only after the owner accepts the boundary question: “what does it mean for research or
design material to become normative Builder/System delivery intent?” The ADR should define the
promotion record/receipt, not a graph schema. Then update the smallest existing owner docs and routing
skill to use it.

### P3 — Define owner acceptance separately

Generalize the narrow acceptance receipt only when a real owner-try workflow is ready. Bind it to a
capability, accepted SHA/profile, observed use, limitations, and date. Do not let “ready to try” or
merge act as a proxy.

### P4 — Implement the read-only cockpit

After Yggdrasil handoff, implement only the Stage A shell, composition envelope, provenance/freshness
display, selected-context navigation, and honest degradation. No command API, new durable graph, or
local authority.

## 14. SBS reconciliation

This audit **conforms** to the existing Builder System boundary and the current SBS decomposition. It
does not propose a new SBS subsystem or move authority between Product/Runtime, BuilderOps, CKM,
GitHub, or dispatcher. The Delivery Trace is a projection concern across existing boundaries, not a
new authority-bearing subsystem. Any intention/need artifact that belongs to Product/owner memory must
be routed through its existing owner and ADR process; this audit does not assign it to BuilderOps.

## 15. Reconciled backlog and explicit non-actions

The major executable work is already represented by DDO and BuilderOps issues, especially #4163 and
#4167–#4170, plus the existing devUI/CKM work. The audit creates no new Issue, parent hub, capability
specification directory, or migration plan. Later issue conversion should use `docs-to-issue` or
`feature-breakdown` only after the owner accepts a bounded promotion or traceability slice and after a
live duplicate search.

## 16. Recommendation

Adopt **one Builder System lifecycle map, one promotion boundary, and one read-time Delivery Trace
projection over existing authorities**. Do not adopt a Delivery Knowledge Graph as a second source of
truth.

The next architectural artifact should be a narrowly scoped ADR for the research/design → normative
intent boundary. The next product artifact should be the Yggdrasil-validated, read-only Stage A
cockpit. The next implementation governance work should repair the already identified join-key gaps.

That sequence improves the owner's overview while preserving the system's strongest property: agents
can accelerate delivery without becoming the owners of meaning, authority, or truth.
