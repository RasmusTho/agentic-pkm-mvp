State: Development reference. Governance proportionality contract.
Doc role: Governance contract
Authority: Defines how much governance machinery each risk tier requires. Skills and CI reference this contract instead of carrying uniform requirements.
Owner: Builder-agent governance
Temporal class: durable

# Governance Proportionality

This repository is intentionally single-operator. Every gate, receipt, and report section is paid for twice: once by an agent burning context to produce it, once by one human reading it. The governing goal is cost-effectiveness — keep the safety properties (fail-closed promotion, truthful lifecycle state, delivery traceability) while cutting per-change overhead for low-risk work.

Proportionality applies to *reporting and PR-body machinery* **and to delivery-chain depth** — the independent review gate, merge mechanics, and repair budgets (`AGENTS.md :: Proportional delivery`). It never applies to authoritative lifecycle truth: Issue labels, Issue/PR state, CI, and merge evidence must stay truthful at every tier. Project Status is optional projection repair.

## Risk tiers

Three tiers. When in doubt, classify up. A PR that mixes tiers takes the highest tier it touches.

### Tier 1 — low risk

**Classification:** docs-only changes; skill/governance text under `.codex/skills/**`, `AGENTS.md`, and `.github` governance surfaces; comment-level fixes. No product/runtime behavior, contracts, or shipped reality change.

**Deterministic CI classifier:** the PR body carries `- [x] Docs authoring lane` or `- [x] Governance lane`. The existing lane checkboxes double as the tier declaration — no new labels, tokens, or attestation mechanisms.

**Required machinery:**

- lane classifier in the PR body (the checkbox above)
- truthful authoritative lifecycle state (labels, Issue/PR state, CI) — mandatory at every tier
- `## BuilderOps Routing` may be omitted entirely when nothing was routed: **absence means "none"**. A present-but-unfilled section (template placeholders) still fails CI — claiming the section means filling it.
- output format: a short human summary (2–4 sentences) plus a receipt line; no multi-section report
- validation: lightweight docs/governance checks appropriate to the touched surfaces; no full code/test smoke by default
- delivery depth: light path — declare `Final-Review-Rounds: 0` and merge plainly on green required checks; no independent review round, no verified-merge ceremony; approved bounded multi-Issue work uses the same native merge

### Tier 2 — standard

**Classification:** bounded code slices, tests, owner-doc writeback — the everyday implementation lane.

**Required machinery (the current contract):**

- exactly one `Governing-Issue: #<id>` plus at least one closing-keyword line for fully delivered
  work (the identities match in the normal single-Issue case)
- `## BuilderOps Routing` section with concrete `Records/projections/receipts:` and `Reason:` lines
- every Acceptance Criterion's `Verify:` target resolved before merge
- standard receipts (delivery receipt, post-merge owner-doc check)
- repo-standard validation gates (`ruff check app tests` and the relevant test suites when `app/` or `tests/` changed)
- delivery depth: native merge with current-head checks and self-verified coverage. An explicit
  independent review uses `Final-Review-Rounds: 1` without requiring body neutralization or a phase
  ledger. Approved multi-Issue work validates every closing child and keeps an unclosed parent open.

### Tier 3 — high risk

**Classification:** migrations, release channels, prod mutations, `stable` pointer moves, Core Runtime <-> Agentic Lab boundary moves.

**Required machinery:** one independent current-head review (`Final-Review-Rounds: 1`) and checks
covering the actual risk. P0/P1 repairs require a fresh clean review. Native PR merge is separate
from release authority: promotion plans, channel isolation, operator acknowledgment and live
verification still apply when deploying. Dispatched executors, already-started authenticated merge
attempts, and contracts explicitly requiring independent closure retain the fenced full path.
Native delivery with a nonempty closing set requires the repository's live default branch as
the PR base, because GitHub closing keywords do not close Issues on other branches. Route such
non-default-base deliveries to the full path before merge, with explicit authenticated closure.

## Evidence reuse and stop rule

Collect evidence once per relevant candidate/input set and consume it across implementation,
publication and closure. A stage transition, a new agent, or a request for a summary is not an
invalidation event. Resolve `Suggested Validation` from existing applicable results before running
commands. Preserve the command, outcome, tested candidate, environment and artifact link in the
existing PR Validation section or CI artifact; do not introduce another schema or ledger.

Rerun only evidence affected by changed code, tests, dependencies, configuration, fixtures,
contract/ACs, selection or execution environment. Required GitHub checks remain current-head; the
base-drift rule below is the only cross-head local reuse exception. Missing or ambiguous dependency
information requires the affected check, not a fabricated pass. Live deployment/health evidence
remains bound to its environment and observation time.

Each additional check must name the unresolved failure mode and the delivery decision its result
can change. Stop validating when AC coverage, relevant CI, required review and authority are
satisfied. Do not add a full suite, second clean review, per-AC fresh test, or post-merge doc re-audit
solely for reassurance. Existing tests may cover multiple ACs. Bug fixes should reproduce the
regression where practical; behavior-preserving refactors may retain passing coverage.

Keep successful output to the result and artifact link. Read failed-node details first, complete
logs only for diagnosis. Reuse the PR's validation summary in the delivery receipt; do not copy
structured artifacts or repeated AC tables into comments and chat. Executor protocol receipts stay
in their required durable location until that consumer contract is separately changed.

## Implementation and evaluation

The 2026-09-19 simplification replaces routine full-path merge with native session-owned delivery,
separates review depth from merge mechanics, reuses validation and owner-doc assessments, and drops
unrelated product gates from text-only CI. The existing selector remains the single source for
check selection; contract coverage stays conservative for unclassified docs. No new queue, evidence
registry, or runtime executor authority is added.

Use the next 20 accepted deliveries as a bounded evaluation, from existing CI and session records:
compare tokens per accepted change, validation reruns, control calls, and post-merge defects with a
like-for-like prior sample. Report unavailable token data as unknown. A 50% routine-token reduction
is a hypothesis, not a shipped result or an acceptance blocker. Any new permanent check must replace
an existing check or name a review date; retain protections that demonstrate unique failure detection.

## Delivery budgets and stop-loss

Every delivery carries a default budget of **2 CI-repair rounds per failure mechanism** (the separate
P0/P1 review-repair loop uses evidence-based convergence owned by `verification-and-closure`, not a
numeric attempt budget). When
the budget is spent, stop grinding: ship the smallest passing subset of the change, or hand the
work back with a one-paragraph stop report and a `LearningSignal` naming the artifact that made it
expensive. A handback requires the stop-loss assessment below; budget exhaustion first triggers
the applicable shrink/replan or capability-escalation path, not automatic abandonment. Budgets are
never rebound to a new mechanism key to reset accounting. Light (Tier 1/2)
deliveries run without sub-agent fan-out. Repeated failure on a bounded change is evidence the
solution is too big — shrink the solution before escalating capability.

For every Builder workflow, a stop-loss permits suspending unfinished work only when continued
execution is unsafe, unauthorized, or demonstrably non-convergent after the applicable bounded
diagnosis, repair, and capability-escalation process. It includes an unresolved authority/scope
boundary, required operator acknowledgment not yet given, or indispensable infrastructure still
unavailable after authorized recovery. Explicit user stop or limited scope is separately sufficient;
do not describe a completed analysis-only task as blocked delivery.

Ordinary CI/review waits, queue acceptance, first failures, repairable conflicts, missing optional
projection, and publication success are not stop-loss. A missing executor manifest requires diagnosis
and authorized recovery, not automatic credential provisioning or bypass. Preserve separate P0/P1
convergence rules; never merge a partial contract or waive verification to avoid leaving a PR open.

Before stopping, record the exact step and artifact/PR head, failed gate and evidence, attempts and
remaining budget, why no safe authorized continuation exists, preserved work/owner, and one next
recovery action in the existing task/Issue/PR receipt. Reuse `blocker_action.v1` when its lifecycle
applies and the existing lifecycle handoff receipt for an actual owner transfer; add no new schema.
Technical stop-loss alone does not create `agent:needs-human`. Invoke `owner-decision-brief` only for
a genuine owner decision. Once the condition clears, `resume-work` continues the suspended chain.

## Post-validation base-drift evidence reuse

Branch freshness does not make byte-identical validation evidence false. When `origin/main`
advances after expensive local validation but before the first push, rebase as required by the
branch-truth gate and carry that evidence forward only when every condition below is proven:

- the rebased delivery patch has the same stable patch ID as the validated patch;
- every delivery-owned file blob is byte-identical to the validated patch;
- the incoming base commits do not overlap delivery-owned paths and a changed-surface review finds
  no semantic effect on dependencies, contracts, runtime configuration, schemas, migrations,
  generated inputs, test selection, CI/build tooling, or the validation command itself;
- no repair, scope change, conflict resolution, or delivery-owned edit occurred during the rebase;
- the rebased head passes the bounded `Verify:` targets and cheap integration/contract checks that
  can detect interaction with the incoming base; and
- the publication receipt records the validated SHA, rebased SHA, stable patch ID, incoming commit
  range, overlap result, checks rerun, and the expensive validation carried forward.

Any unresolved relevance question fails closed and reruns the affected validation. A code,
dependency, configuration, schema, migration, test-selection, CI/build-tooling, or contract change
that can affect the delivery is relevant even when filenames do not overlap.

This rule replaces unconditional full-suite repetition for irrelevant base-only SHA changes. It
does not carry forward GitHub CI, live-environment proof, mergeability, or a required final review:
those remain bound to the current PR head. It also never carries evidence across a repair commit,
scope change, conflict resolution, or changed delivery blob.

## Right-size default

The default solution is the most boring one that satisfies the acceptance criteria. A new gate,
receipt, ledger, registry, config surface, abstraction layer, or enterprise-grade pattern (high
availability, multi-tenancy, pluggable providers, defense-in-depth beyond the single-operator
trust model) requires an explicit demand in the governing contract — never default posture. "A
simpler mechanism satisfies the contract" is a valid blocking review finding at any tier. A new
permanent governance mechanism must name what it replaces or carry an explicit review-by date.
Product-side scale posture is owned by `docs/DESIGN_PRINCIPLES.md`.

## What proportionality never relaxes

- Lifecycle truth: labels and Issue/PR state stay accurate at every tier; Project projection repair is optional and cold-path.
- The fail-closed release-channel promotion chain.
- `Verify:` targets on issue-backed acceptance criteria.
- Branch-truth gates at the publication boundary.
- Required CI checks green on the current head SHA before any merge, at every tier.
- Required independent reviews run on the current head SHA; only eligible pre-publication expensive
  validation may use the base-drift evidence-reuse rule above.

## CI enforcement

`.github/workflows/issue-pr-governance.yml` (`pr-contract` job) implements the Tier 1 relaxation deterministically: when the PR body carries a docs-authoring or governance lane checkbox, a missing `## BuilderOps Routing` section is treated as "none"; for all other PRs the section remains required with concrete values. The same job accepts `Final-Review-Rounds: 0` (light path), `1` (one independent review), or `2` (backward-compatible authenticated declaration for already-started deliveries); the value's delivery-depth meaning is defined by this contract, not by CI. New deliveries never select `2` from risk or convergence classification.

## Output formats

The everyday skills (`publish-pr`, `issue-to-code`, `verification-and-closure`, `deliver-issue-set`, `issue-maintenance-change-control`) lead their reports with a **Summary for the human** — 2–4 sentences covering what was done, what remains, and what needs a decision — before any receipt blocks, and include further sections only when they have content.
