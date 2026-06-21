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

Every question above is answered by following the [classification procedure](#3-how-new-work-is-classified-against-sbs) and reading the source-of-truth docs it points to. No answer depends on memory.

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
| Issue lifecycle | this doc §6 + `.github/ISSUE_TEMPLATE/task.yml` + `.github/github-governance.yml` | Required sections and labels are enforced by governance config. |
| PR lifecycle | this doc §7 + `.github/pull_request_template.md` | SBS impact block and owner-doc writeback checklist live in the template. |
| Review-gate fallback policy | this doc §11 | What to do when a required automated review gate is unavailable. |

This matrix is the **source-of-truth verification matrix** required for SBS operationalization. If a new SBS concern appears, add a row here naming exactly one owner doc.

## 3. How new work is classified against SBS

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
6. **Decide owner-doc impact.** See §8. → *whether owner docs must be updated*.
7. **Decide transition-debt impact.** See §9. Every slice either reduces a debt item, adds a bounded one, or states it does not affect debt. → *whether transition debt must be recorded*.
8. **Decide fitness-rule impact.** See §10. Identify which existing rules apply to the boundary you touched and whether the change strengthens, weakens, or is neutral to enforcement. → *which fitness rules apply*.

The result of steps 1–8 is the SBS impact block. For issues it is the `SBS Impact` section of `.github/ISSUE_TEMPLATE/task.yml`; for PRs it is the `## SBS Impact` section of `.github/pull_request_template.md`.

### Subsystem quick reference

Fourteen Level-2 control-boundary subsystems plus the CES stewardship practice (full definitions in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`):

`HIX` human interaction & intent · `WSP` workspace, scope & principal context (ActiveContextSet, not a scalar active vault) · `HKA` human knowledge & artifact substrate · `SIP` semantic identity & provenance · `GOV` governance, policy, authority & receipts · `EBF` external boundary fabric · `PDM` persistence & data management · `DRI` derived representation & indexing · `RCA` retrieval & context assembly · `MEM` machine memory & learning · `CAO` cognitive capability & agent orchestration · `EXE` capability execution & automation · `SFC` synchronization, federation & consensus · `OEF` observability, evaluation & fitness · `CES` contract & evolution stewardship (practice, not runtime).

## 4. Definition of Ready (SBS-relevant issues)

An SBS-relevant issue is Ready (`agent:ready`, Status=Ready) only when its `SBS Impact` block resolves all of the following. Use "none"/"unaffected" explicitly rather than leaving a field blank.

- **Primary SBS owner** named (one subsystem).
- **Secondary subsystem(s)** named or marked none.
- **Durable vs rebuildable** classification stated for any record the work creates or changes.
- **Authority-bearing write** classification stated (authority-bearing / mechanical / derived / none).
- **Contract impact** stated: which `docs/contracts/*.md` apply, and whether any is new or changed.
- **Owner-doc impact** stated (none / will-update-in-PR / follow-up-issue).
- **Transition-debt impact** stated (reduces #… / adds bounded debt / no effect).
- **Verification plan** present: each acceptance criterion carries a resolvable `Verify:` target (test pointer, doc writeback anchor, roadmap diff, or runtime receipt), per the issue template.

An issue that cannot resolve these is `agent:needs-human`, not Ready.

## 5. Definition of Done (SBS-relevant PRs)

An SBS-relevant PR is Done only when:

- **Contract** is updated or explicitly recorded as unaffected.
- **Owner-doc impact** is handled per §8 (no change implied / updated in this PR / follow-up issue created and linked) — the PR template owner-doc checklist is filled.
- **Transition debt** is recorded or resolved: the relevant row in `docs/architecture/SBS_TRANSITION_DEBT.md` is added, updated (containment/status), or the PR states no debt effect.
- **Fitness rule** impact is handled: an applicable rule in `docs/architecture/SBS_FITNESS_RULES.md` is updated, or a follow-up issue is created to add/strengthen one, or the PR states no fitness effect.
- **Validation evidence** is recorded in the PR (lane-appropriate checks per the template; see §11 if a required gate is unavailable).
- **Delivery receipt** is posted on the linked issue/PR (the merge/closure note that records what landed; see the `verification-and-closure` practice).
- **Status/roadmap impact** is handled when the change moves a tracked item: update `docs/architecture/SBS_ROADMAP.md` phase status and the `docs/ROADMAP.md` SBS initiative entry when applicable.

## 6. Issue lifecycle expectations

- SBS-relevant work uses `.github/ISSUE_TEMPLATE/task.yml`. The `SBS Impact` section is a required section per `.github/github-governance.yml`.
- Issues carry `agent:ready` only when the Definition of Ready (§4) holds; otherwise `agent:needs-human` or `agent:blocked`.
- Project Status is a projection of issue/PR truth (governance config): opened → Backlog; ready → Ready; PR open → Review; merged/closed → Done. Do not hand-edit Status to mask issue state.
- Larger SBS work hangs off the tracking issue `#2337` (Operationalize Target SBS) and the delivery parent `#2355`. New initiative-level SBS work should reference the relevant `docs/architecture/SBS_ROADMAP.md` phase.

## 7. PR lifecycle expectations

- Every PR fills the `## SBS Impact` block in `.github/pull_request_template.md`, including the owner-doc writeback checklist.
- Choose the correct lane (implementation / docs-authoring / governance). Operating-model, register, template, and policy changes are docs-authoring or governance lane.
- Run lane-appropriate validation and paste evidence. For implementation lane touching shared/hot-path code, run the full `not pg` suite, not targeted tests only.
- A required review gate must actually pass before merge. If it cannot run, apply the review-gate fallback policy (§11). Never record a gate as passed when it did not run.
- On merge, post the delivery receipt and apply owner-doc writeback (§8) and roadmap/debt/fitness writeback (§5).

## 8. Owner-doc writeback rule

When a change alters behavior, a contract, or turns a tracked backlog item into shipped reality, the corresponding **owner doc** must be brought back into truth. Owner docs include `docs/ARCHITECTURE.md`, `docs/STATUS.md`, subsystem owner docs, the relevant `docs/contracts/*.md`, and the SBS registers.

Resolve owner-doc impact to exactly one of:

1. **No owner-doc change implied** — the change is internal and changes no documented behavior or contract.
2. **Owner-doc updated in this PR** — preferred; bundle the doc update with the implementation so truth never lags (consistent with the repo's owner-doc-bundling practice and the `post-merge-owner-doc` skill).
3. **Owner-doc follow-up issue created and linked** — only when the writeback is genuinely separable; the issue must be created (not merely described) and linked in the PR.

A comment, a placeholder marker, or a "to update later" note is **not** an acceptable resolution — it recreates the same drift the rule exists to prevent. The PR template encodes these three options as a checklist; exactly one must be checked.

## 9. Transition debt lifecycle

`docs/architecture/SBS_TRANSITION_DEBT.md` is the register of known and likely deviations from the target SBS.

- **Recording:** every target-state slice either (a) reduces an existing debt row, (b) adds a bounded new debt row, or (c) states it does not affect SBS transition debt. This is the register rule.
- **Columns:** debt; violated target boundary; current location; risk; severity; containment; desired end state; owner; follow-up issue; fitness rule; status. New rows fill all columns; use `to verify` for any column not confirmed by code/doc inspection.
- **`to verify` discipline:** do not assert that a debt is confirmed in code unless it was inspected. A plausible-but-unverified deviation is recorded with status `to verify` and current location `to verify`.
- **Closing:** a debt row moves to `resolved` only when the violated boundary is actually enforced (contract adopted on the path *and* a fitness rule or test prevents regression), with the resolving PR/issue linked.

## 10. Fitness rule lifecycle

`docs/architecture/SBS_FITNESS_RULES.md` owns the rules and the prioritized rule roadmap (P0/P1/P2). Each rule has an enforcement posture:

- **Manual review now** — applied during architecture/PR review and issue breakdown.
- **CI check later** — mechanically enforceable once the boundary has stable code shape; tracked as a follow-up.
- **CI check now** — a matching test/lint exists in the repo (e.g. `tests/architecture/test_sbs_fitness_rules.py`).
- **Blocking invariant** — violation should block merge or require a new ADR.

Lifecycle:

- A new boundary or contract should add or update a fitness rule and set its posture honestly. A rule is only "CI check now" if a real test enforces it; otherwise it is "manual review now" or "CI check later".
- Promoting a rule from manual to CI is itself SBS work: file an issue, add the test under `tests/architecture/`, and update the rule's posture and the prioritized roadmap.
- Enforcement infrastructure (the fitness tests themselves) is in-scope for review and must fail loud; a check that cannot fail is not enforcement.

## 11. Review-gate fallback policy

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

## 12. Relationship to roadmap and status

- **Strategic sequencing** of the SBS initiative lives in `docs/ROADMAP.md` (the SBS operationalization initiative entry under Baselines) and is expanded into phase intent/status in `docs/architecture/SBS_ROADMAP.md`. This operating model owns *process*, not sequencing — it points to the roadmap, it does not duplicate it.
- **Shipped reality** is owned by `docs/STATUS.md` and `docs/ARCHITECTURE.md`. Classifying or readying work against the SBS never updates status; only delivery does, via owner-doc writeback (§8).
- **High-churn execution movement** (active issue, blocker, last movement) lives in BuilderOps operational records, not in this doc.

## 13. Non-goals

- Do not instantiate fourteen physical modules/services/packages to satisfy the SBS.
- Do not rewrite owner docs or registers to present target-state as shipped behavior.
- Do not add review gates beyond those named here, or convert classification into an approval bureaucracy.
- Do not duplicate the decomposition, the roadmap, or contract content into this doc — link to the owners in §2.
- Do not treat SBS classification as proof that a subsystem exists in code; it is a routing and review aid only.
- Do not claim a review gate passed when it did not (§11).

## Discoverability

This doc is reachable from `docs/DOCS_INDEX.md` (Agent quick routing, Critical Authority Boundaries, and the Core SoT per-file rows), `docs/READING_PATHS.md` (target-architecture, major-change, and agent-SBS reading paths), `docs/ROADMAP.md` (SBS initiative entry), and `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` (operational references).
