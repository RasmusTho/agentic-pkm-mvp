State: Operating model for the target SBS; governance/process surface, not a shipped-runtime claim. The target SBS itself remains target-state per `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`.
Doc role: Operating model / process control surface
Authority: Owns how the target SBS is used operationally — how work is classified, what Ready and Done mean for SBS-relevant work, how issues and PRs move, how owner-doc writeback, transition debt, and fitness rules are kept truthful, and what to do when a required review gate is unavailable. Subordinate to `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` on the decomposition itself and to `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` on contract-first adoption sequencing.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: this doc for SBS operating process; mixed for everything it points to
Last reviewed: 2026-06-21
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/architecture/SBS_OPERATIONALIZATION_PLAN.md, docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md, docs/architecture/SBS_BOUNDARY_REGISTER.md, docs/architecture/SBS_TRANSITION_DEBT.md, docs/architecture/SBS_FITNESS_RULES.md, .github/ISSUE_TEMPLATE/task.yml, .github/pull_request_template.md, .github/github-governance.yml

# SBS Operating Model

This document makes the target System Breakdown Structure (SBS) **operationally self-sustaining**. It is the doc a future agent or maintainer reads to use the SBS without this conversation, without tribal memory, and without re-deriving the architecture.

The SBS is operationally self-sustaining when a future contributor can start from the repository alone, pick up a new issue, and correctly determine:

- which SBS subsystem owns the work;
- which contracts apply;
- which boundaries must not be violated;
- whether a write is authority-bearing;
- whether a record is durable or rebuildable;
- whether owner docs must be updated;
- whether transition debt must be recorded;
- which fitness rules apply.

Every question above is answered by following the [Builder System classification procedure](#3-builder-system-boundary-and-work-classification) and [SBS impact procedure](#4-how-new-work-is-classified-against-sbs), then reading the source-of-truth docs they point to. No answer depends on memory.

## What the SBS is not

- **Not a physical module map.** The fourteen Level-2 subsystems plus CES practice are *control boundaries*, not a demand to create fourteen packages, services, owner docs, or deployment units. Physical separation is opportunistic and evidence-driven (ADR-0016, `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` adoption principle).
- **Not a shipped-runtime description.** The decomposition is target-state. `docs/ARCHITECTURE.md` and `docs/STATUS.md` own what actually ships today. Classifying work against an SBS subsystem never asserts that the subsystem exists as code.
- **Not a new approval bureaucracy.** Classification is a routing and review aid. It adds a lightweight impact block to issues and PRs; it does not add gates beyond the ones named here.
- **Not authority over product intent.** `docs/PROJECT_KERNEL.md` and `docs/COGNITIVE_PROSTHESIS_CHARTER.md` remain authoritative on intent.

## 1. Purpose

- Turn the target SBS from a strategy document into repeatable repository practice.
- Give every SBS-relevant change a uniform way to declare impact, route review, and record consequences.
- Keep the registers that make the SBS honest — boundary register, transition debt, fitness rules — current as a *byproduct of normal work* rather than as a separate audit.
- Make the answer to "can a future agent operate the SBS alone?" be **yes**, and keep it yes.

## 2. Source-of-truth model

The SBS is described across several docs, each with a single owner. Do not duplicate content between them; link.

| Concern | Source of truth | Notes |
|---|---|---|
| Target SBS decomposition | `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` | The fourteen Level-2 subsystems, eight macro-domains, dependency rules, forbidden dependencies. |
| Current runtime architecture | `docs/ARCHITECTURE.md` | What actually ships. Wins on present-tense behavior. |
| Current system-of-systems spine | `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` | The current eight-subsystem bridge between today's runtime and the target SBS. |
| SBS operationalization (adoption sequencing) | `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` | Contract-first / module-lazy adoption, slice sequencing, contract ownership. |
| SBS operating model (this doc) | `docs/architecture/SBS_OPERATING_MODEL.md` | How SBS work is classified, readied, done, reviewed, and recorded. |
| SBS roadmap / initiative phases | `docs/architecture/SBS_ROADMAP.md` | Phase intent, status, blockers; linked from `docs/ROADMAP.md`. |
| Current-to-target mapping | `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` | Which target owner a current area maps to, for impact classification. |
| Boundary register | `docs/architecture/SBS_BOUNDARY_REGISTER.md` | Charter/contract/enforcement/physical-module maturity per subsystem. |
| Transition debt | `docs/architecture/SBS_TRANSITION_DEBT.md` | Known and likely deviations from target, with containment and follow-up. |
| Fitness rules | `docs/architecture/SBS_FITNESS_RULES.md` | Architecture fitness rules, enforcement posture, and the prioritized rule roadmap. |
| Critical contracts | `docs/contracts/*.md` | ActiveContextSet, GovernedWriteProtocol, ArtifactContract, StorePort, ContextBundle, MemoryRecord, ExecutionRequest, ReplicationEnvelope, CapabilityContract, WorkflowContract. |
| Durable architecture decisions | `docs/adr/ADR-0015` … `ADR-0019` | Authority-first SBS, contract-first/module-lazy, HKA/GOV survivability, provenance split, governed writes. |
| Issue lifecycle | this doc §7 + `.github/ISSUE_TEMPLATE/task.yml` + `.github/github-governance.yml` | Required sections and labels are enforced by governance config. |
| PR lifecycle | this doc §8 + `.github/pull_request_template.md` | SBS impact block and owner-doc writeback checklist live in the template. |
| Review-gate fallback policy | this doc §12 | What to do when a required automated review gate is unavailable. |
| Builder System boundary, authority model, and artifact map | this doc §3 | Defines the continuous-development enabling system, its relationship to the Product/Runtime SBS and CES, how builder agents classify Product, Builder, and boundary work, and the owner/authority/writeback map for Builder System artifacts and workflows. |
| Builder Learning and TCD governance loop | this doc §3 | Defines the allowed inputs, durable destinations, TCD signals, and promotion path for builder learning without contaminating Product/Runtime memory. |

This matrix is the **source-of-truth verification matrix** required for SBS operationalization. If a new SBS concern appears, add a row here naming exactly one owner doc.

## 3. Builder System Boundary And Work Classification

Yggdrasil has two related but distinct systems:

- **Product/Runtime System** - the human-first cognitive platform described by `docs/PROJECT_KERNEL.md`,
  `docs/COGNITIVE_PROSTHESIS_CHARTER.md`, current runtime owner docs, and the target SBS in
  `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`.
- **Builder System** - the continuous-development enabling system that builds, verifies, releases,
  governs, and learns from changes to the Product/Runtime System.

The Builder System includes builder agents, repo-local skills, issue creation and delivery workflows,
PR governance, CI and architecture fitness, release/UAT/promotion workflows, owner-doc writeback,
delivery receipts, BuilderOps Vault records and projections, TCD governance, and builder-learning
feedback loops. It also includes external model, tool, GitHub, CI, and connector dependencies when
they are used to produce or verify repo-governed changes.

The Builder System is **not** a Product/Runtime SBS subsystem. It is an enabling system around the
Product/Runtime System. Classifying work as Builder System work does not claim shipped runtime
behavior and does not make repo-local skills runtime CAO/MEM capabilities.

CES remains the Product SBS contract-stewardship practice: it owns subsystem charters, interface
versioning, compatibility, ADRs, dependency rules, and deprecation discipline. CES does not carry the
entire Builder System. The Builder System may use CES-governed artifacts, and it may update CES
practice surfaces through repo-governed PRs, but release workflows, issue pickup, skill execution,
BuilderOps records, TCD routing, and delivery receipts are Builder System concerns unless they also
change Product/Runtime contracts.

### Classification Procedure

Run this procedure before non-trivial issue creation, implementation, docs/governance work, or
verification:

1. **Product/Runtime System work** changes product behavior, runtime code, user-facing semantics,
   Product SBS contracts, durable human knowledge authority, machine memory, retrieval, execution,
   sync, persistence, or current shipped architecture. Route it through the Product owner docs,
   `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`, relevant `docs/contracts/*.md`, and the SBS
   impact procedure below.
2. **Builder System work** changes development-time machinery: `AGENTS.md`, `.codex/skills/**`,
   issue/PR templates, GitHub governance config, CI/fitness rails, release/promotion skills,
   BuilderOps object/projection docs, delivery receipts, worklogs, learning/retrospective workflows,
   TCD policy, or agent workflow docs. Route it through this Builder System model, the repo-local
   skill index, and the development workflow docs.
3. **Boundary work** changes how Builder System machinery affects Product/Runtime truth, for example
   owner-doc writeback, issue/PR classification, release promotion, architecture fitness enforcement,
   Product SBS contract updates, or BuilderOps promotion into GitHub/repo artifacts. Route it through
   both sides: this Builder System model and the relevant Product/Runtime owner docs.

If the classification is still unclear, choose the stricter boundary route and name both owner surfaces
in the Issue/PR. Do not treat Builder System records, projections, skills, prompts, or delivery
learning as runtime/user memory or Human Knowledge Artifacts unless a Product/Runtime authority path
explicitly promotes them.

### Builder-Agent Authority Model

Builder agents and repo-local skills may change repo-governed artifacts only through the repo's normal
authority path:

- bounded GitHub Issue or explicit direct-repair contract;
- isolated worktree/branch for active edits;
- PR with lane classification, validation evidence, BuilderOps routing outcome where required, and
  owner-doc writeback resolution;
- CI, architecture fitness, Codex review, and verification gates required by the lane and risk tier;
- delivery receipt on the governing Issue/PR and parent validation hub when applicable.

Builder agents may create or update BuilderOps operational records for builder worklogs, learning
signals, docs freshness, roadmap execution movement, promotion intents, and receipts when the workflow
requires those records. BuilderOps records and generated projections are not Product/Runtime truth and
do not mutate runtime/user memory. Crossing from BuilderOps into repo docs, GitHub Issues, PRs,
runtime behavior, or Product SBS contracts requires the explicit promotion or PR path named by the
relevant workflow.

Runtime/user memory separation is strict: failed prompts, quota/context failures, issue decomposition
problems, PR feedback, high-TCD deliveries, and workflow learnings are Builder System learning inputs.
They may become skill updates, issue updates, transition debt, fitness rules, roadmap changes,
BuilderOps records, or repo-doc PRs. They must not silently become HKA/MEM/user memory, runtime
instructions, or product semantics without Product System authority review.

### Builder System SBS Impact Guidance

For Builder System issues and PRs, fill `SBS Impact` as follows:

- Primary subsystem: use `Builder System / CES boundary` when the work changes builder workflow,
  repo governance, skill behavior, or development authority. This value is valid for Builder System
  work even though it is not a Product/Runtime SBS subsystem.
- Secondary subsystem(s): name Product SBS subsystems only when their contracts, owner docs, runtime
  behavior, release state, or fitness rules are read or changed.
- Write class: normally `governance/docs/process`; use a more specific Product write class only when
  Product artifacts or runtime behavior change.
- Authority impact: state which builder authority path is changed or consumed, and whether any
  Product/Runtime authority is affected.
- Memory impact: state that builder learning is separate from runtime/user memory unless the work
  explicitly changes a Product MEM/HKA contract.
- Owner-doc impact: update this operating model for Builder System boundary changes; update Product
  owner docs only when Product truth changes.
- Transition debt and fitness rule impact: record unresolved Builder/Product misclassification or
  CES-overload risk as transition debt or a candidate fitness rule when the PR discovers it.

### Builder System Artifact And Workflow Map

This map is the owner location for Builder System artifact/workflow classification. It inventories
the durable and derived surfaces that builder agents use to create, verify, release, govern, and
learn from Product/Runtime System changes. Product/Runtime owner docs still win for product behavior,
runtime contracts, and shipped truth; this map only classifies the builder-side surface and the
allowed route for changing it.

| Category | Included artifacts/workflows | Owner | Authority level | Durability | Allowed write path | Writeback / receipt expectation | Relationship to Product/Runtime SBS | Verification target |
|---|---|---|---|---|---|---|---|---|
| Repo-local skill contracts | `.codex/skills/**`, including shared contracts in `.codex/skills/_shared/**` | Builder System governance, routed by `.codex/skills/README.md` and `AGENTS.md` | Normative builder workflow instructions; not runtime CAO/MEM capability contracts | Durable repo-governed artifacts | Governance-lane PR or issue-backed implementation PR when a skill change is part of delivered work; no silent local-only edits | PR validation, skill consistency checks when applicable, BuilderOps routing outcome for Tier 2+ work, and delivery receipt on the governing issue/PR | Consumes Product/Runtime owner docs and SBS classifications, but remains outside the Product/Runtime SBS unless it changes Product contracts | `python3 scripts/lint_skills_consistency.py` for skill-surface changes; PR diff review against `.codex/skills/README.md` |
| Builder-agent entrypoint policy | `AGENTS.md`, `.codex/AGENTS.md` if present, builder-agent instruction governance docs | Builder System governance | Normative agent authority and routing policy | Durable repo-governed artifacts | Governance-lane PR or bounded issue-backed PR | PR receipt plus owner-doc writeback resolution; capture BuilderOps `LearningSignal` only when the change responds to a delivery divergence | Shapes how agents work on Product SBS artifacts; does not define runtime/system-agent behavior | Architecture/governance tests that cover touched policy plus manual check that runtime docs are not being rewritten as builder instructions |
| Issue intake and lifecycle controls | `.github/ISSUE_TEMPLATE/task.yml`, issue labels, Project Status rules, issue pickup claim scripts, issue maintenance workflow | Builder System governance with GitHub Project as lifecycle projection | Governance-bearing shared signal for executable work | Durable GitHub state plus durable repo templates; Project status is a projection | Explicit `gh`/GraphQL mutations for live labels/status; template/config changes via PR | Claim, block, ready, and closure comments or receipts; Project state verified after mutation | SBS Impact blocks route Product/Runtime work and Builder work; GitHub state is not Product runtime truth | `gh issue view --json labels,projectItems`; template/config tests where applicable |
| PR governance and publication workflow | `.github/pull_request_template.md`, `.github/github-governance.yml`, PR hot path/escalation docs, `publish-pr`, `pr-integration`, review-gate fallback | Builder System governance | Normative merge/review/publication contract for repo-governed changes | Durable repo templates/config plus durable GitHub PR state | PR template/config/docs changes via PR; PR state via explicit `gh`/GraphQL commands | PR body must carry lane, SBS Impact, validation, BuilderOps routing where required, owner-doc writeback resolution, and final delivery receipt | Governs how Product/Runtime changes become accepted repo truth; does not itself ship runtime behavior | Governance tests for PR-body rules; PR review/CI/Codex verdict before merge |
| CI, architecture fitness, and validation rails | `.github/workflows/**`, `tests/architecture/**`, `tests/governance/**`, `importlinter.ini`, docs guard scripts, validation commands in workflow docs | OEF for fitness posture, Builder System governance for delivery use, CES practice for SBS rule lifecycle | Enforceable or manual-review governance depending on rule posture | Durable repo-governed code/config; CI results are ephemeral evidence attached to PRs | Implementation, docs-authoring, or governance PR depending on touched surface; rule posture changes follow §11 | CI/check output recorded in PR; fitness-rule status updated only when real enforcement exists | Verifies Product SBS boundaries and Builder workflow contracts; OEF observes/blocks but does not mutate runtime policy | `pytest -q tests/architecture` and targeted governance tests for touched rules |
| Release, UAT, promotion, and rollback workflows | `docs/RELEASE_CHANNELS/**`, `docs/ENVIRONMENTS.md`, promotion skills (`prepare-promotion`, `promote-to-test`, `promote-test-to-prod`, `execute-promotion`, `verify-promotion`, `rollback-promotion`), UAT/runbook docs | Release-channel owner docs plus Builder System governance for operator skills | Boundary workflow authority over code refs, channel verification, and operator receipts; Product runtime semantics remain owned by runtime docs | Durable specs/skills/receipts; runtime health results are operational evidence | Release-channel docs/skills change via PR; actual promotion/rollback through operator-acknowledged release-channel workflow | Promotion plans, verification receipts, rollback receipts, and PR/issue receipts as required by the release skill | Affects Product deployment state and environment/channel safety; not a Product SBS subsystem and not a runtime capability by itself | Release-channel skill validation, channel preflights, health/smoke receipts, and links to `docs/RELEASE_CHANNELS/README.md` |
| Prompt, workflow, and development docs | `docs/development/**`, `docs/READING_PATHS.md`, builder workflow sections in `docs/DOCS_INDEX.md`, prompt/workflow docs referenced by repo-local skills | Builder System governance; `docs/DOCS_INDEX.md` owns role routing | Normative or reference guidance depending on each doc's role header | Durable repo-governed docs | Docs-authoring or governance PR; issue-backed PR when changing an executable workflow contract | PR receipt and docs-index/read-path writeback when discovery changes | Guides builder work over Product/Runtime docs without becoming runtime/system-agent instruction | `pytest -q tests/architecture` when docs index coverage applies; manual role-boundary review |
| Delivery receipts and closure comments | Issue comments, PR comments, parent validation receipts, closure receipts, post-merge owner-doc receipts | Governing workflow skill (`verification-and-closure`, `post-merge-owner-doc`, parent closure docs) | Delivery evidence and lifecycle truth; not semantic Product/Runtime authority unless promoted through owner docs | Durable GitHub records; high-churn operational summaries may also be represented as BuilderOps records | Explicit `gh issue comment` / `gh pr comment` by the responsible workflow; no repo-doc edits solely for transient operational state | Receipt names PR, merge SHA, validation, lifecycle mutations, owner-doc result, and remaining blockers | Evidence that Product/Runtime or Builder work passed its delivery contract; does not itself change runtime behavior | `gh issue view` / `gh pr view` comments plus Project/label verification |
| Roadmap, project, and projection surfaces | GitHub Project, issue dependency comments, `docs/ROADMAP.md`, `docs/architecture/SBS_ROADMAP.md`, BuilderOps roadmap/docs-freshness projections | Roadmap owner docs for stable strategic truth; BuilderOps for high-churn operational movement; GitHub Project for lifecycle projection | Mixed: owner docs are strategic authority; Project/projections are operational projections | Owner docs durable; Project/projections durable but derived or high-churn | Stable roadmap changes via PR; Project updates through explicit GraphQL/`gh`; BuilderOps projections regenerated from BuilderOps records, not hand-edited as authority | Movement receipts on issues/PRs; owner-doc writeback only when stable truth changes | Routes Product SBS initiatives and Builder System delivery without replacing Product owner docs or shipped status docs | Project item status query; roadmap diff review; projection source-record check when BuilderOps is involved |
| TCD and cost-control workflows | `AGENTS.md :: Total Cost of Development`, `deliver-issue-set`, planning/review TCD blocks, capability routing decisions | Builder System governance | Normative builder optimization policy | Durable repo-governed policy plus ephemeral per-delivery decisions recorded in plans/receipts | Governance PR for policy/skill changes; per-delivery use recorded in issue/PR comments or PR body | TCD plan/review blocks when required by the active skill; learning routed only on real divergence | Optimizes development work around Product/Runtime changes; not runtime MEM/CAO learning | Presence of required TCD block in planning/review output; PR/issue receipt for applied routing |
| Recovery and failure workflows | Quota/context/subagent failure handling, branch/worktree preflight, git hygiene, dispatcher fallback, review-gate fallback, blocked/needs-human transitions | Builder System governance | Normative safety and coordination policy for builder execution | Durable workflow docs/scripts plus durable GitHub blocker receipts; transient terminal state is not authority | Workflow/script changes via governance PR; live recovery state via explicit labels, Project status, and comments | Blocker or recovery receipt names the failed gate, fallback used, timestamp, and next action; BuilderOps learning only for upstream divergence | Prevents builder failures from corrupting Product/Runtime repo truth; recovery material must not become runtime/user memory | Preflight output, `gh issue view --json labels,projectItems`, recovery comment, and relevant workflow test when a script changes |

Classification gaps found while applying this map must not be hidden in prose. If a category cannot
be assigned an owner, authority level, durability, write path, receipt expectation, Product/Runtime
relationship, or verification target, record it as bounded transition debt in
`docs/architecture/SBS_TRANSITION_DEBT.md` or split it into a follow-up issue before marking the work
Done.

### Builder Learning And TCD Governance Loop

Builder learning is a Builder System concern. It is the governed feedback loop that improves builder
instructions, skills, issue contracts, CI/fitness rails, release/UAT workflows, and TCD routing from
delivery evidence. It is not Product/Runtime memory, not user memory, not a Human Knowledge Artifact,
and not Product MEM/HKA authority unless a Product System owner path explicitly promotes it through a
bounded issue/PR and owner-doc writeback.

Builder learning inputs include:

- failed, insufficient, or ambiguous prompts;
- quota, context-window, tool, connector, and sub-agent failures;
- issue decomposition errors, malformed Verify targets, stale source anchors, and readiness drift;
- rework, repeated RCA patterns, review findings, failed or reverted PRs, and failed gates;
- flaky or missing CI/fitness rules, owner-doc drift, release/UAT failure patterns, and promotion or
  rollback receipts;
- high human-time cost, high model/tool cost, high coordination cost, repeated context reloads, and
  other TCD signals.

TCD inputs use `AGENTS.md :: Total Cost of Development` as the single policy source. Builder System
records and delivery receipts may reference the observed TCD factors: human time, model/tool cost,
reasoning/context cost, parallelization and coordination cost, rework, defect risk, delay, failed
gates, quota/context failures, and review/verification depth. Per-delivery TCD decisions are evidence;
only a repo-governed PR changes the TCD policy itself.

Allowed learning destinations:

| Destination | Authority | Durability | Write path | Use when |
|---|---|---|---|---|
| Issue or PR comment / delivery receipt | Lifecycle evidence, not Product semantic truth | Durable GitHub record | Explicit `gh issue comment` / `gh pr comment` by the responsible workflow | Recording observed delivery evidence, blockers, validation, TCD rationale, or parent validation receipts. |
| BuilderOps `LearningSignal` | Builder operational learning signal | Durable BuilderOps record; projections are derived | `capture-learning` or the owning workflow, with source refs | A concrete divergence names an upstream artifact that may need repair. |
| BuilderOps `PromotionIntent` | Reviewed staging request for crossing authority classes | Durable BuilderOps record | BuilderOps CLI or owning workflow before repo/Product promotion, or before GitHub Issue creation when the source is already a `PromotionIntent` | Learning material should become a PR/branch proposal, owner-doc or skill/AGENTS writeback, generated projection, Product/Runtime authority proposal, or a GitHub Issue proposed from PromotionIntent review. A bounded `LearningSignal` may still create a GitHub Issue through `learning-to-issue` without first creating a `PromotionIntent`. |
| BuilderOps `BuilderOpsReceipt` or generated projection | Processing ledger or derived review view | Receipt is durable; projection is rebuildable | BuilderOps CLI, then regenerate projections from source records | Retrospective completion, supersession, discard, or projection for review. |
| Repo-local skill update | Normative Builder System workflow instruction | Durable repo-governed artifact | Bounded issue or direct-repair PR, with validation and owner-doc receipt | Learning changes how future agents should classify, execute, verify, or recover. |
| Builder owner docs / development docs | Normative or reference Builder System governance | Durable repo-governed docs | Docs/governance PR with SBS Impact and validation | Learning changes boundary model, workflow policy, or durable process truth. |
| Transition debt row | Known or likely gap in the target operating model | Durable register entry | PR updating `docs/architecture/SBS_TRANSITION_DEBT.md` or follow-up issue | A learning sink, metric, or workflow gap is real but not resolved in the current slice. |
| Fitness-rule backlog or rule update | OEF/CES review or enforcement policy | Durable register entry; CI only when implemented | PR updating `docs/architecture/SBS_FITNESS_RULES.md`; issue/test for CI promotion | Learning reveals a repeatable failure mode that should become manual or mechanical review. |
| Roadmap / SBS roadmap update | Strategic or initiative-level truth | Durable owner doc | Owner-doc PR when stable strategy changes | Learning changes sequencing, phase status, or accepted initiative direction. |
| Prompt templates or agent-entry policy | Builder prompt/routing instruction | Durable repo-governed artifact | PR updating the prompt/policy owner surface | Learning changes how future builder context should be assembled or constrained. |
| Product/Runtime owner docs, HKA, MEM, or runtime behavior | Product System authority only | Product-owned durable truth | Product/Runtime issue/PR path with owner-doc writeback and applicable contracts | Only when the change is explicitly Product work; never as silent builder-learning promotion. |

Learning-to-change path:

1. **Observe.** A workflow records a divergence, cost signal, failed gate, drift, or repeated pattern
   in the smallest truthful surface: PR/issue receipt for ordinary evidence, BuilderOps
   `LearningSignal` for upstream repair signals, or a blocker receipt when work cannot proceed.
2. **Classify.** The owner skill classifies the signal as Product/Runtime, Builder System, or
   boundary work. Product effects require Product owner docs and SBS impact; Builder effects use this
   Builder System model; boundary effects name both.
3. **Route.** Keep raw/high-churn material in BuilderOps or comments. A concrete, bounded
   `LearningSignal` may become a GitHub Issue through `learning-to-issue` when it names an upstream
   artifact and has resolvable `Verify:` targets. Before crossing BuilderOps material into
   PR/branch proposals, owner-doc or skill/AGENTS writeback, generated projections, or
   Product/Runtime authority proposals, create or consume a BuilderOps `PromotionIntent` that names
   the target surface. Promote repo-governed artifacts only by PR.
4. **Change.** Apply the smallest governed change: skill edit, owner-doc edit, issue/template repair,
   fitness rule, transition debt row, roadmap update, prompt/policy update, or Product issue/PR when
   Product authority is genuinely required.
5. **Verify and close.** Validation must prove the destination changed and did not contaminate
   runtime/user memory. Delivery receipts name the PR, merge SHA, checks, Codex/review outcome,
   lifecycle state, BuilderOps routing, and any remaining debt.

Runtime/user memory contamination is a blocking failure mode. Failed prompts, quota/context failures,
delivery receipts, BuilderOps records, TCD rationales, review comments, and skill retrospectives must
not become HKA/MEM/user memory, runtime instructions, retrieval context, or product semantics unless
the change goes through the Product System authority path for that owner surface. If a Builder
learning item appears useful for Product behavior, file or update a Product/Runtime issue with the
relevant owner docs and `SBS Impact`; do not write it directly into runtime memory or Product truth.

## 4. How new work is classified against SBS

Run this procedure for any non-trivial change. It produces the SBS impact block used in the issue and PR templates and answers the self-sustaining questions above. Each step names where its answer comes from.

1. **Find the area in the current-to-target mapping.** Open `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`, match your change to a current area, and read its target owner(s). → *which subsystem owns the work* (primary = the control boundary that owns the semantics being changed; secondary = subsystems whose contracts you read or touch).
2. **Pull the applicable contracts.** For each owning subsystem, the boundary register (`docs/architecture/SBS_BOUNDARY_REGISTER.md`) names whether a contract exists and where. Read the relevant `docs/contracts/*.md`. → *which contracts apply*.
3. **Check forbidden dependencies.** `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` Part 4 lists the forbidden-dependency table (e.g. RCA writes HKA, MEM writes HKA without GOV, CAO calls tools without EXE/GOV, EBF provider concepts in HKA/SIP/GOV). → *which boundaries must not be violated*.
4. **Classify the write.** Decide the write class:
   - **authority-bearing durable write** — changes accepted human knowledge, governance receipts, policy, or accountable state → requires a governed-write path (DecisionToken + AuthorityReceipt; ADR-0019, `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`).
   - **mechanical durable write** — durable but not authority-bearing (e.g. PDM-owned store rows) → must go through a StorePort, not private store construction.
   - **derived/rebuildable write** — embeddings, indexes, projections (DRI) → must be rebuildable from source anchors; never the only copy of meaning.
   - **ephemeral/none** — no durable effect.
   → *whether a write is authority-bearing* and *whether a record is durable or rebuildable*.
5. **Classify persistence vs derivation.** A record is **durable** when losing it loses human meaning or accountability (HKA/GOV/MEM-owned). It is **rebuildable** when it can be regenerated from durable sources (DRI/PDM projections). If a "derived" record is the only source of meaning, it is misclassified — reclassify to HKA/GOV/MEM (fitness rule "No DRI record that is non-rebuildable unless reclassified").
6. **Decide owner-doc impact.** See §9. → *whether owner docs must be updated*.
7. **Decide transition-debt impact.** See §10. Every slice either reduces a debt item, adds a bounded one, or states it does not affect debt. → *whether transition debt must be recorded*.
8. **Decide fitness-rule impact.** See §11. Identify which existing rules apply to the boundary you touched and whether the change strengthens, weakens, or is neutral to enforcement. → *which fitness rules apply*.

The result of steps 1–8 is the SBS impact block. For issues it is the `SBS Impact` section of `.github/ISSUE_TEMPLATE/task.yml`; for PRs it is the `## SBS Impact` section of `.github/pull_request_template.md`.

### Subsystem quick reference

Fourteen Level-2 control-boundary subsystems plus the CES stewardship practice (full definitions in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`):

`HIX` human interaction & intent · `WSP` workspace, scope & principal context (ActiveContextSet, not a scalar active vault) · `HKA` human knowledge & artifact substrate · `SIP` semantic identity & provenance · `GOV` governance, policy, authority & receipts · `EBF` external boundary fabric · `PDM` persistence & data management · `DRI` derived representation & indexing · `RCA` retrieval & context assembly · `MEM` machine memory & learning · `CAO` cognitive capability & agent orchestration · `EXE` capability execution & automation · `SFC` synchronization, federation & consensus · `OEF` observability, evaluation & fitness · `CES` contract & evolution stewardship (practice, not runtime).

## 5. Definition of Ready (SBS-relevant issues)

An SBS-relevant issue is Ready (`agent:ready`, Status=Ready) only when its `SBS Impact` block resolves all of the following. Use "none"/"unaffected" explicitly rather than leaving a field blank.

- **Primary SBS owner** named (one subsystem), or `Builder System / CES boundary` for Builder System
  work that does not change a Product/Runtime SBS subsystem.
- **Secondary subsystem(s)** named or marked none.
- **Durable vs rebuildable** classification stated for any record the work creates or changes.
- **Authority-bearing write** classification stated (authority-bearing / mechanical / derived / none).
- **Contract impact** stated: which `docs/contracts/*.md` apply, and whether any is new or changed.
- **Owner-doc impact** stated (none / will-update-in-PR / follow-up-issue).
- **Transition-debt impact** stated (reduces #… / adds bounded debt / no effect).
- **Verification plan** present: each acceptance criterion carries a resolvable `Verify:` target (test pointer, doc writeback anchor, roadmap diff, or runtime receipt), per the issue template.

An issue that cannot resolve these is `agent:needs-human`, not Ready.

## 6. Definition of Done (SBS-relevant PRs)

An SBS-relevant PR is Done only when:

- **Contract** is updated or explicitly recorded as unaffected.
- **Owner-doc impact** is handled per §9 (no change implied / updated in this PR / follow-up issue created and linked) — the PR template owner-doc checklist is filled.
- **Transition debt** is recorded or resolved: the relevant row in `docs/architecture/SBS_TRANSITION_DEBT.md` is added, updated (containment/status), or the PR states no debt effect.
- **Fitness rule** impact is handled: an applicable rule in `docs/architecture/SBS_FITNESS_RULES.md` is updated, or a follow-up issue is created to add/strengthen one, or the PR states no fitness effect.
- **Validation evidence** is recorded in the PR (lane-appropriate checks per the template; see §12 if a required gate is unavailable).
- **Delivery receipt** is posted on the linked issue/PR (the merge/closure note that records what landed; see the `verification-and-closure` practice).
- **Status/roadmap impact** is handled when the change moves a tracked item: update `docs/architecture/SBS_ROADMAP.md` phase status and the `docs/ROADMAP.md` SBS initiative entry when applicable.

## 7. Issue lifecycle expectations

- SBS-relevant work uses `.github/ISSUE_TEMPLATE/task.yml`. The `SBS Impact` section is a required section per `.github/github-governance.yml`.
- Issues carry `agent:ready` only when the Definition of Ready (§5) holds; otherwise `agent:needs-human` or `agent:blocked`.
- Project Status is a projection of issue/PR truth (governance config): opened → Backlog; ready → Ready; PR open → Review; merged/closed → Done. Do not hand-edit Status to mask issue state.
- Larger SBS work hangs off the tracking issue `#2337` (Operationalize Target SBS) and the delivery parent `#2355`. New initiative-level SBS work should reference the relevant `docs/architecture/SBS_ROADMAP.md` phase.

## 8. PR lifecycle expectations

- Every PR fills the `## SBS Impact` block in `.github/pull_request_template.md`, including the owner-doc writeback checklist.
- Choose the correct lane (implementation / docs-authoring / governance). Operating-model, register, template, and policy changes are docs-authoring or governance lane.
- Run lane-appropriate validation and paste evidence. For implementation lane touching shared/hot-path code, run the full `not pg` suite, not targeted tests only.
- A required review gate must actually pass before merge. If it cannot run, apply the review-gate fallback policy (§12). Never record a gate as passed when it did not run.
- On merge, post the delivery receipt and apply owner-doc writeback (§9) and roadmap/debt/fitness writeback (§6).

## 9. Owner-doc writeback rule

When a change alters behavior, a contract, or turns a tracked backlog item into shipped reality, the corresponding **owner doc** must be brought back into truth. Owner docs include `docs/ARCHITECTURE.md`, `docs/STATUS.md`, subsystem owner docs, the relevant `docs/contracts/*.md`, and the SBS registers.

Resolve owner-doc impact to exactly one of:

1. **No owner-doc change implied** — the change is internal and changes no documented behavior or contract.
2. **Owner-doc updated in this PR** — preferred; bundle the doc update with the implementation so truth never lags (consistent with the repo's owner-doc-bundling practice and the `post-merge-owner-doc` skill).
3. **Owner-doc follow-up issue created and linked** — only when the writeback is genuinely separable; the issue must be created (not merely described) and linked in the PR.

A comment, a placeholder marker, or a "to update later" note is **not** an acceptable resolution — it recreates the same drift the rule exists to prevent. The PR template encodes these three options as a checklist; exactly one must be checked.

## 10. Transition debt lifecycle

`docs/architecture/SBS_TRANSITION_DEBT.md` is the register of known and likely deviations from the target SBS.

- **Recording:** every target-state slice either (a) reduces an existing debt row, (b) adds a bounded new debt row, or (c) states it does not affect SBS transition debt. This is the register rule.
- **Columns:** debt; violated target boundary; current location; risk; severity; containment; desired end state; owner; follow-up issue; fitness rule; status. New rows fill all columns; use `to verify` for any column not confirmed by code/doc inspection.
- **`to verify` discipline:** do not assert that a debt is confirmed in code unless it was inspected. A plausible-but-unverified deviation is recorded with status `to verify` and current location `to verify`.
- **Closing:** a debt row moves to `resolved` only when the violated boundary is actually enforced (contract adopted on the path *and* a fitness rule or test prevents regression), with the resolving PR/issue linked.

## 11. Fitness rule lifecycle

`docs/architecture/SBS_FITNESS_RULES.md` owns the rules and the prioritized rule roadmap (P0/P1/P2). Each rule has an enforcement posture:

- **Manual review now** — applied during architecture/PR review and issue breakdown.
- **CI check later** — mechanically enforceable once the boundary has stable code shape; tracked as a follow-up.
- **CI check now** — a matching test/lint exists in the repo (e.g. `tests/architecture/test_sbs_fitness_rules.py`).
- **Blocking invariant** — violation should block merge or require a new ADR.

Lifecycle:

- A new boundary or contract should add or update a fitness rule and set its posture honestly. A rule is only "CI check now" if a real test enforces it; otherwise it is "manual review now" or "CI check later".
- Promoting a rule from manual to CI is itself SBS work: file an issue, add the test under `tests/architecture/`, and update the rule's posture and the prioritized roadmap.
- Enforcement infrastructure (the fitness tests themselves) is in-scope for review and must fail loud; a check that cannot fail is not enforcement.

## 12. Review-gate fallback policy

This policy covers the scenario observed during `#2363` / PR `#2376`, where the Codex review gate could not run because usage limits were exhausted. It applies to **any** required automated review gate that becomes unavailable.

When a required automated review gate is unavailable:

1. **Do not claim the review passed.** Absence of a review is not an approval. (Note: Codex frequently signals approval via a 👍/+1 *reaction* on the PR rather than a review comment — check `/issues/<pr>/reactions` before concluding the gate did not run.)
2. **Mark the issue `agent:needs-human`** (repo-equivalent) so it leaves the autonomous-ready queue.
3. **Record a blocker receipt** on the issue/PR: which gate, why it was unavailable, and the timestamp.
4. **Do not merge** unless one of:
   - the review gate later succeeds; or
   - a human maintainer explicitly authorizes a scoped override for that PR; or
   - an approved alternate reviewer path is used.
5. **A human override is recorded** in the issue/PR and is **not generalized** beyond the specific PR. The next PR starts from the same gate requirement.

An unprotected `main` branch does **not** waive this gate: "autonomous merge" means running the full skill chain including the review wait, not bypassing it because branch protection is off.

## 13. Relationship to roadmap and status

- **Strategic sequencing** of the SBS initiative lives in `docs/ROADMAP.md` (the SBS operationalization initiative entry under Baselines) and is expanded into phase intent/status in `docs/architecture/SBS_ROADMAP.md`. This operating model owns *process*, not sequencing — it points to the roadmap, it does not duplicate it.
- **Shipped reality** is owned by `docs/STATUS.md` and `docs/ARCHITECTURE.md`. Classifying or readying work against the SBS never updates status; only delivery does, via owner-doc writeback (§9).
- **High-churn execution movement** (active issue, blocker, last movement) lives in BuilderOps operational records, not in this doc.

## 14. Non-goals

- Do not instantiate fourteen physical modules/services/packages to satisfy the SBS.
- Do not rewrite owner docs or registers to present target-state as shipped behavior.
- Do not add review gates beyond those named here, or convert classification into an approval bureaucracy.
- Do not duplicate the decomposition, the roadmap, or contract content into this doc — link to the owners in §2.
- Do not treat SBS classification as proof that a subsystem exists in code; it is a routing and review aid only.
- Do not claim a review gate passed when it did not (§12).

## Discoverability

This doc is reachable from `docs/DOCS_INDEX.md` (Agent quick routing, Critical Authority Boundaries, and the Core SoT per-file rows), `docs/READING_PATHS.md` (target-architecture, major-change, and agent-SBS reading paths), `docs/ROADMAP.md` (SBS initiative entry), and `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` (operational references).
