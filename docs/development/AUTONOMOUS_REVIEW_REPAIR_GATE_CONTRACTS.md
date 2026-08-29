State: Builder System governance design contract. Defines target contracts; does not implement automation. Light-path deliveries (`AGENTS.md :: Proportional delivery`) do not run these gates; this contract's unconditional review/closure language binds the full path only.
Doc role: Governance design / process contract
Authority: Defines contract requirements for future review, repair, exception, and closure automation. Subordinate to `AGENTS.md`, `docs/architecture/SBS_OPERATING_MODEL.md`, `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`, `.codex/skills/verification-and-closure/SKILL.md`, `.codex/skills/pr-integration/SKILL.md`, and `.codex/skills/_shared/CI_WAIT_CONTRACT.md`.
Owner: Builder System governance
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-08-29
Last verified against: 2026-08-29 current main, issue #3211, issue #3224, issue #3225, issue #3814, issue #4028, `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`, `.codex/skills/issue-to-code/SKILL.md`, `.codex/skills/publish-pr/SKILL.md`, `.codex/skills/verification-and-closure/SKILL.md`, `.codex/skills/bug-to-issue/SKILL.md`, `.codex/skills/pr-integration/SKILL.md`, `.codex/skills/_shared/CI_WAIT_CONTRACT.md`

# Autonomous Review and Repair Gate Contracts

This document defines the target contracts for autonomous review, CI repair,
review-repair looping, Human Exception routing, and closure eligibility in the
Builder System. It is a design artifact only. It does not create GitHub Actions
mutation workflows, repair agents, PR branch patchers, merge automation, label
or Project automation, branch-protection changes, auto-merge changes, or
runtime/product behavior.

The contracts below are safe to use as design input for future implementation
issues. A future issue still needs its own acceptance criteria, explicit
mutation authority, branch guardrails, validation evidence, and rollback plan
before any automation can act on GitHub state or a PR branch.

## Scope

In scope:

- Machine review gate inputs, outputs, verdicts, required evidence, and
  actionable-finding criteria.
- CI repair gate inputs, first safe modes, future patch-branch prerequisites,
  bounded retry/backoff, and frontier-rescue stop conditions.
- Review repair loop routing, evidence-based convergence, and stop conditions.
- Human Exception packet schema, dedupe behavior, and escalation classes.
- Closure eligibility for future autonomous closure and merge-adjacent flows.

Out of scope:

- Implementing review agents, CI repair agents, or repair branches.
- Mutating GitHub Actions workflows, required checks, labels, Project fields,
  branch protection, auto-merge settings, or repository permissions.
- Broad SkillOpt rewrites, runtime changes, product behavior changes, database
  migrations, or production configuration changes.
- Closing, merging, or auto-approving PRs without the guardrails named below.

## Phase Vocabulary

Future automation must declare exactly which phase it is operating in.

| Phase | Meaning | Mutation authority |
| --- | --- | --- |
| Observe-only | Reads issue, PR, diff, CI, logs, and docs; writes no GitHub state. | None |
| Artifact-only | Writes local or generated evidence artifacts for a human or later PR. | Local artifacts only |
| Comment-only / proposal-only | Posts findings, repair plans, or exception packets without changing source branches. | Comments only, when explicitly allowed by the issue/skill |
| Patch-branch | Pushes narrowly scoped fixes to a non-protected PR branch under branch guardrails. | Future-only; requires prerequisites below |
| Autonomous-closure | Closes or merges after all closure and platform guardrails pass. | Future-only; blocked until closure prerequisites below exist |

The current contract for issue #3225 stops at design documentation. It does not
authorize patch-branch or autonomous-closure behavior.

## Machine Review Gate Contract

The machine review gate is a blocking quality and governance gate for a PR. It
can be implemented by an agent, script, or hybrid process, but its contract is
the same.

### Inputs

Required inputs:

- PR number, base branch, head branch, current head SHA, and changed-file list.
- Issue contract, including acceptance criteria, non-goals, constraints,
  required source docs, and `Verify:` markers.
- PR evidence pack from the implemented #3214 evidence-pack contract.
- Source docs named by the issue and by the touched owner-doc routing path.
- CI/check state for the current head SHA, including required checks and any
  governance checks.
- Existing review comments, unresolved threads, and prior machine review
  receipts.
- Local diff and, when needed, file/line context for changed files.

Optional inputs:

- Prior delivery receipts, dispatcher claim receipts, risk-tier receipts, and
  owner-doc writeback receipts.
- Related parent issue context, epic context, or Project status when explicitly
  referenced by the issue contract.

### Outputs

The review gate must emit one of these outputs:

- `pass`: no P0/P1 finding remains for the current head SHA and all P2/P3
  findings have their required dispositions.
- `blocking`: at least one P0/P1 finding blocks closure or merge.
- `inconclusive`: the gate cannot complete with enough evidence to pass or
  block.

The output must include:

- Review receipt with PR number, head SHA, base branch, review round, timestamp,
  reviewer identity/tool identity, and verdict.
- Evidence summary covering checks, changed files, issue acceptance criteria,
  and required docs consulted.
- For each finding: severity, path and line when applicable, triggering
  contract/rule, impact, expected fix or proof, blocking status, disposition,
  and any deferred-defect Issue reference.
- Explicit statement when no owner-doc writeback is implied.

### Pass and Blocking Verdicts

A `pass` verdict is valid only when:

- The reviewed head SHA matches the current PR head.
- Required CI and governance checks are current and successful.
- Every issue acceptance criterion and `Verify:` marker has evidence.
- No unresolved P0/P1 review thread or machine finding remains.
- Every P2 finding has durable defect evidence and a linked deferred disposition;
  P3 findings are recorded as informational when useful.
- No forbidden mutation or out-of-scope behavior is present in the diff.

A `blocking` verdict is required when any condition below is present; each such
condition is a P0/P1 finding:

- A P0/P1 finding shows that the diff violates the issue contract, source docs, required skills, or
  repository safety constraints.
- Required validation is missing, stale, or tied to a different head SHA.
- The PR introduces unapproved runtime/product behavior, GitHub-state mutation,
  branch-protection changes, or automation outside issue scope.
- A required owner-doc writeback is missing or contradicts shipped reality.
- The review cannot tie evidence to the current head SHA for closure-critical
  checks.

An `inconclusive` verdict is required when required context is unavailable and
the missing context could change the result. Inconclusive review is not a pass.
It routes through the escalation classifier: use bounded evidence recovery or
`blocked_technical` when the missing context is technical, and Human Exception
only when resolving it needs an explicit `needs_owner` authority category.

### Actionable Finding Criteria

A finding is actionable only when it is:

- Reproducible or directly evidenced from the PR, issue, CI, or source docs.
- Scoped to the PR or to a required closure condition for the PR.
- Tied to a contract, safety rule, regression, missing validation, or
  acceptance criterion.
- Specific enough to fix or disprove, with expected proof.
- Not merely a style preference, unsupported speculation, future enhancement, or
  unrelated backlog item.

Non-actionable observations may be reported as suggestions, but they must not
block closure.

### Severity Routing

Actionable does not mean blocking. Every finding must receive exactly one
severity and one disposition:

| Severity | Meaning | Required disposition |
| --- | --- | --- |
| `P0` | Critical correctness or safety defect with immediate severe impact. | Block merge; repair and independently re-review. |
| `P1` | Material correctness, contract, or safety defect. | Block merge; repair and independently re-review. |
| `P2` | Real defect accepted for this PR and deferred to bounded follow-up. | Leave the PR code unchanged for the finding; create or update durable defect evidence through `.codex/skills/bug-to-issue/SKILL.md`; mark the finding deferred and reply on the original review finding/thread with the Issue reference; allow merge without another review round. |
| `P3` | Informational advice, style guidance, or non-defect suggestion. | Record when useful; no merge block, defect intake, repair, or re-review. |

There is no valid `blocking P2`. A finding involving any of the following is
protected and must be P0 or P1: data loss or corruption; source, vault, or
authority integrity; secrets, authentication, or authorization; migration
durability; concurrency or multi-writer safety; irreversible or external
effects without required authority; false-green CI, receipts, merge, or closure
evidence; or a failed governing acceptance criterion, `Verify:` target,
contract, or closure gate. If available evidence cannot distinguish a protected
failure from a true P2, the result is `inconclusive`, not a downgraded finding.

Only P0/P1 findings enter repair/re-review, mechanism convergence, repeated
repair accounting, or low-convergence assessment. Ordinary P2/P3 observations
consume no repair attempts and cannot trigger mechanism convergence or low-convergence assessment.
This routing does not
relax independent review, current-head-SHA CI, issue acceptance/`Verify:`
evidence, authority checks, verified-merge controls, or closure gates.

### Dispatcher Receipt Compatibility

The implemented `verification_closer_receipt` and `VerificationAgentLoop`
contracts represent only `blocking` and `clean` review events. They do not
losslessly represent P2 severity, deferred disposition, and the bound defect
Issue. Consequently:

- A P2-bearing review must not be encoded as `clean` or accepted as a
  dispatcher `delivered` receipt.
- An arbitrary Issue reference in `receipt_ids` is not sufficient evidence;
  the current validator does not bind it to a finding or disposition.
- A dispatcher run that encounters a P2 must stop before terminal delivery with
  `inconclusive` / `blocked_technical` and hand off to the live-evidence closure
  path in `verification-and-closure`; it must not manufacture a clean event.
- The live-evidence path must re-read the current PR head, original GitHub
  finding/thread, bug-intake Issue, and reply/disposition reference immediately
  before merge. Its delivery receipt records all four identities. Missing or
  contradictory evidence is a protected P1 false-green closure defect.
- Once that live evidence is complete, the P2 permits merge without a repair or
  another review round. Dispatcher-native delivery for P2-bearing reviews
  remains unavailable until its schema, validator, ledger, and behavioral tests
  validate the complete disposition.

This compatibility rule preserves autonomous closure through the existing
GitHub evidence path without falsely claiming that the current executable
dispatcher receipt can carry P2 semantics.

## CI Repair Gate Contract

The CI repair gate analyzes failing checks and proposes or performs repair only
within its declared phase. It is separate from the review gate: a green CI state
does not imply review pass, and review pass does not override failing CI.

### Inputs

Required inputs come from the implemented #3213 CI context-pack shape:

- PR number, check run, workflow/job identifiers, failing command, and failing
  log excerpts.
- Base SHA, head SHA, merge-base SHA, branch name, and changed-file list.
- Failure classification: likely caused by PR, likely pre-existing, flaky,
  infrastructure/tooling, or unknown.
- Existing retry history, repair attempts, and prior failure mechanisms.
- Environment/tooling notes needed to reproduce the failure locally.
- Relevant issue constraints, source docs, and validation commands.

### First Safe Modes

The first implementation modes must be non-mutating:

- Observe-only: classify failure and collect evidence.
- Artifact-only: generate local or attached repair packet.
- Comment-only / proposal-only: post a bounded repair plan, suspected cause, and
  validation command without editing the PR branch.

These modes may recommend a fix, but they must not push code, update workflows,
change Project state, alter labels, or retry unboundedly.

### Future Patch-Branch Prerequisites

Patch-branch mode is future-only and must not exist before all prerequisites are
met:

- Branch-protection and branch-guardrail evidence from #3215, including clear
  rules for protected branches, required checks, stale SHA handling, and safe
  branch targets.
- PR evidence pack from the implemented #3214 evidence-pack contract tying the
  repair to the current head SHA.
- Explicit issue or owner authorization for mutation-bearing repair.
- Current branch-truth preflight proving the worktree, branch, and expected PR
  branch match.
- Narrow, low-risk fix classification with no production configuration,
  secrets, migrations, broad refactors, or owner-doc authority changes unless
  the issue explicitly authorizes them.
- Local validation command and expected proof before push.
- Convergence evidence and the non-progress stop condition declared before the first patch.
- PR comment receipt after every patch attempt, including SHA, files changed,
  command evidence, and remaining risk.

If any prerequisite is missing, the gate may only observe, produce artifacts, or
propose a repair.

### Retry and Frontier-Rescue Boundaries

Retry budget:

- One CI rerun is allowed for a suspected flake when logs support a flaky or
  infrastructure classification and the governing workflow allows reruns.
- Repair may continue only when its receipt shows measurable progress: the failure narrows or
  clears, the mechanism changes with evidence, validation coverage improves, or diagnostic
  uncertainty decreases.
- Repetition without new evidence is a capability-escalation and bounded-replan trigger. It is
  never progress merely because the attempt has a new ordinal. A finding remains bound to its
  original mechanism and domain, and P2/P3 observations never enter repair accounting.

Frontier-rescue stop conditions:

- The strongest feasible bounded diagnosis repeats the same failure mechanism without new evidence
  or measurable progress.
- The cause remains unknown after a bounded focused investigation and the next safe diagnostic step
  cannot be named.
- The proposed repair expands scope beyond the issue contract.
- Repair would touch protected branches, workflows, secrets, migrations,
  production configuration, or high-risk runtime behavior without explicit
  authorization.

When a stop condition triggers, classify it through [Escalation classifier](#escalation-classifier).
Only an explicit authority category may route to Human Exception; safe technical
stops remain blocked while their bounded recovery path proceeds autonomously.

## Mechanism Convergence Gate

The implementation, governance, and direct-repair lanes must explicitly record that TCD risk
classification was completed even when no high-risk surface applies. Omitting the risk-surface
argument is not evidence of a low-risk classification. Governance that changes executable stateful
or concurrency enforcement is not exempt. Once any high-risk surface is declared, no lane may bypass
this gate; only a clean convergence review permits expensive proof to begin.

This is the cheap design/correctness gate that precedes expensive proof for high-risk stateful work.
It applies to auth, security, data, migrations, concurrency, external APIs, credential durability,
and explicit state machines. It is enacted by `issue-to-code`, `publish-pr`, and
`verification-and-closure`; it does not replace current-SHA CI or the final independent review gate.

Trigger it:

- before the first expensive local validation for a high-risk stateful slice;
- after one review round reports two or more blocking P0/P1 findings in the same mechanism; or
- when a later review round finds an adjacent P0/P1 blocker in a mechanism already repaired.

P2/P3 findings never trigger mechanism convergence or contribute to its
low-convergence threshold.

The implementation agent must stop point-fixing and build one convergence packet containing:

- the stable mechanism/domain key and invariant being protected;
- valid, terminal, indeterminate, and compensated states;
- allowed transitions and every writer that can perform them;
- durability/crash ordering at each externally visible or authority-changing boundary;
- producers, consumers, cleanup, retry, restart, and recovery paths;
- lock ownership/order plus stale-observation and queued-consumer races;
- all prior findings and attempted fixes bound to the same mechanism key; and
- a test matrix mapping each invariant, transition, crash point, and race to focused proof.

### Dormant-capability proof placement

For a dormant capability, the slice that makes storage, schema, or sealing changes proves only
those durability and sealing obligations. Proof that the capability can execute through an
activation path belongs to the bounded slice that activates that path, where its production
entrypoints and focused verification can be named. A convergence packet must not import a
far-future activation proof merely because it can hypothesize one; if activation is required for
the current slice, it is current scope and must be explicitly enumerated in the governing Issue.

### Stateful fallback boundary matrix

For a high-risk stateful fallback mechanism, the convergence packet must also contain **one
executable boundary matrix** before a reviewer can record a clean convergence receipt. This is not
a second convergence gate and does not apply to low-risk ordinary work: use it when the mechanism
selects or resumes a stateful fallback after an outcome that can affect authority, identity,
durability, or terminality.

The matrix is executable only when each row names the entrypoint and outcome being exercised, the
expected state/receipt transition, and the focused proof that runs that row. It must cover these
axes as applicable to the mechanism:

The required axes are production entrypoints, eligible versus terminal failure classes, effective
provider/model identity, current and legacy success/failure resume lineage, and adjacent
authority-isolation paths.

When `scripts/review_before_ci_gate.py` prepares such work, it must receive both
`--stateful-fallback` and `--stateful-fallback-matrix-complete`; the gate otherwise remains
required and cannot hand off to expensive validation or CI. Those flags attest that the packet
contains the matrix; the governing issue, packet, focused proof, current-SHA CI, and final
independent review remain the evidence and merge authorities.

| Axis | Required boundary question |
| --- | --- |
| Production entrypoints | Which production entrypoints can start the mechanism, and which are test-only or forbidden from selecting fallback? |
| Failure classification | Which failure classes are fallback-eligible versus terminal, including authentication, refusal, unsafe output, persistence, and unexpected-failure classes where they exist? |
| Effective identity | Which effective provider/model identity (or equivalent selected target) is recorded before and after each eligible fallback? |
| Resume lineage | How do current and legacy success/failure receipts resume, skip, retry, or terminate without replaying a completed or terminal attempt? |
| Authority isolation | Which adjacent paths must remain unable to borrow the fallback, credentials, identity, receipt, or authority of this mechanism? |

The Model Inquiry adapter chain is a motivating example: its production entrypoint, declared
subscription targets, fallback-eligible and terminal outcomes, persisted attempt lineage, and
non-CKM consumer boundary all need one matrix rather than separate point fixes. The same matrix
shape applies to any comparable stateful fallback mechanism; it does not authorize Model Inquiry,
Product/Runtime, credential, or artifact mutation outside the governing issue.

A fresh independent reviewer at the strongest capability justified by `AGENTS.md :: Total Cost of
Development` reviews the packet and local publishable SHA before another expensive validation. Any
blocker returns to focused repair and packet review. Only a clean convergence review permits the
sequence `affected-surface validation -> publication -> current-SHA CI -> final clean review gate`
to resume. The validation scope comes from the governing contract and affected subsystem; high-risk
classification alone does not expand it to a repo-wide full suite.
Creating the packet or changing reviewer capability never resets the existing per-mechanism repair
history or binding.

If `origin/main` advances after a clean convergence review or expensive validation, an eligible
base-only rebase may reuse that evidence under
`GOVERNANCE_PROPORTIONALITY.md :: Post-validation base-drift evidence reuse`. This is not a repair
round and does not reset a budget. Any changed delivery blob, conflict resolution, scope change, or
relevant base change returns to convergence/affected-surface validation. Current-head CI and the
final independent review gate are never carried forward.

### Low-convergence receipt

Record the triggering review round, mechanism key, packet location or concise receipt, reviewer
capability, verdict, and the expensive validation/CI cycles avoided or repeated. This is delivery evidence, not
a new owner-doc authority surface.

## PR-Level Scope Revalidation Gate

After two rejected independent review rounds on one PR, the production review/publication gate
fails closed before another expensive proof or publication cycle. This count is PR-level: changing a
mechanism identifier, reviewer, model, branch, or head SHA does not reset it. The gate composes with
and does not replace the existing per-mechanism repair accounting or the Mechanism Convergence Gate.
Only a formal GitHub `CHANGES_REQUESTED` review by an author other than the PR author creates a
rejected round. Approval text, repair/status conversation, severity-like prose, and comments outside
such a rejected review cannot create or reset a round. Each counted round binds its exact reviewed
head, reviewer, review-body digest, protected inline-finding digests, and the canonical
`Governing-Contract-SHA256` recorded in that review. Before the two-round threshold, one legacy
rejected review may omit the marker because scope revalidation is not yet active; a marker that is
present must still be unique. Once two rejected rounds exist, every counted round requires exactly
one marker, so incomplete lineage fails closed. Protected inline findings use a line-leading P0/P1 severity token, with ordinary Markdown
heading, ordered/unordered list, bold, bracketed, and `Severity:` wrappers accepted. Severity-like
prose elsewhere is not a finding.

An authenticated receipt bound to the current PR number, head SHA, contract authority, and a canonical
SHA-256 contract identity must select exactly one outcome: `continue_unchanged`, `split`,
or `expanded_contract`. The local JSON is only a canonical working copy: the same receipt object must
exist in a PR conversation comment beginning `<!-- pr-scope-revalidation-receipt:v1 -->`, authored
by a GitHub `OWNER`, `MEMBER`, or `COLLABORATOR`; duplicate JSON keys are malformed and fail closed.
Distinct trusted receipts for the same PR/candidate/Issue identity are conflicting authority and fail
closed; byte-identical duplicates are idempotent.
The executable gate
fetches the current PR, complete paginated review summaries, inline review comments, PR conversation,
and, for issue-backed work, the governing Issue itself. Issue-free docs, governance, and direct-repair
PRs instead authenticate one complete lane/direct-repair contract in the live PR body, require its
canonical classification to match the publication invocation lane, and reject ordinary or
neutralized Issue authority plus unsupported line separators and indented lane markers. Lane and
Direct Repair classification use the explicit ECMAScript whitespace set: Python-only C0/U+0085
forms are not whitespace, while hosted-valid U+FEFF is. The shared BuilderOps section twin applies
the same mapping to bullet spacing and JavaScript `trim()`-equivalent concrete values. They may continue unchanged or split after revalidation,
but scope expansion first requires promotion to an authenticated governing Issue. The gate binds the
repository/base identity, exact candidate and live heads, contract digest, rejected-round IDs,
protected finding IDs, and the content digest of that rejected-review history. Caller-supplied history, actors, URLs,
labels, or finding subsets are never evidence. Omitted,
foreign, stale, malformed, or partial evidence fails closed. The executable gate issues publication
authority only against the canonical `origin/main...HEAD` selectors; workflow-risk analysis may use
alternate selectors only when it is not issuing publication authority. Publication invokes the gate
with an explicit `new` or `existing` mode, and scope revalidation is valid only in `existing` mode.
`existing` derives a unique open PR whose base repository
and ref match the publication base and whose head repository and ref match the authenticated current
branch, then requires the supplied PR identity and scope
revalidation inputs to match it. `new` authenticates that the branch has no open PR and an omitted
mode is rejected whenever the current branch already has an open PR. Before an existing PR is
updated, the local candidate must either strictly descend from the authenticated live PR head or be
a rebased candidate with the same stable patch identity and changed-path blob identities relative to
the canonical publication base. The candidate must contain the current canonical publication base
before either proof can authorize it, and must still differ from the live head. `continue_unchanged`
permits only governing-contract blockers and PR-introduced regressions. Every `split` receipt must
name a positive, non-governing `follow_up_issue`; the executable gate fetches it and requires an
existing, bounded canonical Issue contract before it routes affected work there. `expanded_contract`
requires the current live governing-Issue digest to differ from at least one rejected round and an
exact `expanded_from_rounds` lineage entry (round, reviewed head, prior contract digest) for every
authenticated rejected round before repair continues. An arbitrary well-formed digest is rejected.
The bounded follow-up contract must durably name its source governing Issue and PR plus each routed
finding (`Source-Governing-Issue`, `Source-PR`, and `Routed-Finding` markers); generic ready-Issue
shape is insufficient, and `split` requires at least one classified adjacent/pre-existing finding
whose follow-up identity matches that route. The evaluator closes its snapshot by re-reading every PR, Issue, review,
comment, and follow-up payload used for authority and fails if any changed during collection.
For an existing PR before push, the receipt binds the local candidate head separately from the
authenticated live PR head; Git ancestry or the byte-identical rebase proof must bind the candidate
to that live delivery.
This permits the gate to run before publication without treating the necessarily unpushed candidate
as if it were already the live PR head.

Classify every protected finding derived from each rejected round exactly once as one of:

- `governing_contract_blocker`;
- `pr_introduced_regression`;
- `security_authority_scope_expansion`; or
- `adjacent_pre_existing`.

An `adjacent_pre_existing` finding must name a bounded follow-up Issue and cannot expand the current
PR. A `security_authority_scope_expansion` finding requires `expanded_contract`; no receipt may use a
new mechanism name, reviewer identity, or head change to evade this rule. The executable evaluator
is `scripts/review_before_ci_gate.py`; `issue-to-code`, `publish-pr`, and
`verification-and-closure` route here rather than duplicating its rules.

## Review Repair Loop

The review repair loop connects blocking P0/P1 findings back to implementation.

Severity-visible handoff (#4267): the handoff that starts this loop must make each finding's
severity explicit to the implementing agent before repair starts, not leave it to the agent's own
judgement. Concretely, the finding set handed to the implementing agent (packet, receipt, or
message) must carry, per finding, the `severity` and `disposition` fields the gate already emits
under `Outputs`; a handoff that strips or omits severity is malformed and must be regenerated
before repair. The implementing agent's first act on receipt is to partition the findings by
severity and repair only the P0/P1 subset. Fixing a P2 or P3 finding instead of applying its
required disposition (defer-with-defect-evidence for P2, record-only for P3) is itself a defect in
this loop: flag it — as a review finding on the repair receipt or a `LearningSignal` via
`capture-learning` naming this contract — rather than letting it pass silently. This adds no
review round and does not change the P2/P3 exclusion below; it makes the exclusion checkable at
the moment of handoff.

Required loop:

1. Review gate emits blocking P0/P1 findings with actionable criteria, carrying each finding's
   explicit severity and disposition into the handoff per the severity-visible handoff rule above.
2. Implementation agent confirms the per-finding severities, then fixes only the scoped P0/P1
   findings on the PR branch.
3. Agent reruns the validation required by the issue and by the finding.
4. Agent posts or records a repair receipt with changed files, validation
   evidence, and unresolved risk.
5. Review gate reruns against the new current head SHA.

Convergence policy:

- There is no global numeric repair-attempt budget. Continue only while each repair receipt and
  fresh re-review demonstrate measurable progress.
- A repeated blocking finding or a round without progress triggers TCD-based capability escalation
  and a bounded replan with the complete prior evidence; it does not trigger an owner interruption
  by count. A strongest-capability repair uses the configured strongest capability with high or
  xhigh reasoning.
- P2/P3 findings do not enter this loop, consume attempts, trigger capability
  escalation, or require another review round.
- One clean independent final review on the current head SHA is sufficient for every full-path PR,
  including declared high-risk runtime work and work that triggered the low-convergence circuit
  breaker. A P0/P1 fix invalidates the prior review authority and requires one new clean independent
  review on the repaired current head SHA; no path requires two consecutive clean final reviews.
- Cosmetic or receipt-only corrections are not substantive progress.

Stop conditions:

- The blocking finding is not specific enough to fix or disprove.
- The fix requires scope expansion not authorized by the issue.
- Required source docs or authority boundaries conflict.
- Required validation cannot run.
- The PR branch drifts, the head SHA changes unexpectedly, or branch truth
  cannot be proven.
- The repair would mutate GitHub state, protected branches, workflows, labels,
  Project fields, or runtime/product behavior outside issue scope.

Stopping is not failure. It is the safe transition to the escalation classifier:
continue with stronger autonomous diagnosis or a bounded recovery slice when
safe, and enter Human Exception routing only if an explicit authority category
blocks that recovery.

## Human Exception Router

Human Exception is the path for decisions that need owner judgment or unsafe
authority expansion. It must be sparse, deduplicated, and evidence-backed.

## Escalation Classifier

Every terminal or retryable stop is classified before any label, owner packet, or
repair counter is updated. A retry counter alone must never select
`needs_owner`.

| Route | Use when | Autonomous next action |
| --- | --- | --- |
| `auto_repair` | The failure is repo-local, reversible, inside the issue's declared scope, and has a deterministic validation target. | Create or continue the bounded repair path, then run fresh validation/review. |
| `auto_backoff` | Authentication, rate limit, or an external tool is temporarily unavailable and no mutation has occurred. | Retain the request, record a receipt, and retry with bounded backoff. |
| `blocked_technical` | The system failed closed, a dependency is unavailable, or the cause needs stronger diagnosis; no authority is missing. | Keep the affected service/merge path disabled or blocked, collect evidence, and create a linked bounded recovery slice when needed. |
| `needs_owner` | Continuing needs an unapproved irreversible/external effect, a security/privacy/cost commitment, a production/release operator action, or resolution of contradictory source authority. | Emit one deduplicated Human Exception packet while preserving all CI/review/merge gates. |

Repair history applies only to blocking failures and is partitioned by stable failure
mechanism and failure domain. The closed domains are review/code correctness,
static-quality, lease/concurrency, and deployment/model-schema compatibility. A
failure in one domain or mechanism does not establish non-convergence in another.
Multiple blocking findings may bind to the same mechanism, but one finding may
never rebind to reset accounting. P2/P3 findings create no repair attempt. Repeatedly
identical blocking findings without new evidence still hit a circuit breaker: it triggers stronger
autonomous diagnosis and a bounded replan, not an owner interruption, unless
that replan crosses a `needs_owner` authority category. Attempt count by itself
does not create a Human Exception.

Deployment/model-schema compatibility is a control-plane concern. It must be
checked in a non-mutating preflight before a dispatcher claim or pilot; a
mismatch is `blocked_technical`, leaves the host disabled, and must not consume
or alter the PR's review/code repair history.

### Packet Schema

Each packet must include:

- `failure_class`: one of the escalation classes below.
- `original_intent`: issue/PR goal and the requested outcome.
- `current_state`: branch, PR, issue, head SHA, checks, labels/Project state
  when relevant, and the latest verdict.
- `tried_actions`: commands, reviews, repair attempts, retries, or receipts
  already produced.
- `evidence`: links, logs, file paths, line references, check names, and source
  docs consulted.
- `why_unsafe`: the exact authority, safety, scope, or evidence gap that blocks
  autonomous continuation.
- `options`: two or three unique objects, each with a stable `id`, plain-language `label`, and the
  concrete `consequence` of choosing it.
- `no_action_option`: the id of the explicit do-nothing choice.
- `recommended_option`: the id of exactly one offered choice.
- `recommendation_rationale`: why that offered choice is recommended for the stated evidence.
- `consequence_of_doing_nothing`: what remains blocked or at risk.

### Dedupe and No-Spam Rules

- Maintain one open packet per issue/PR/failure-class/current-head-SHA
  combination.
- Update the existing packet or comment when new evidence belongs to the same
  failure, instead of opening a duplicate.
- Do not escalate routine review findings, expected CI failures with a bounded
  repair path, or backlog improvements outside the PR scope.
- Re-escalate only when the head SHA, failure class, owner decision space, or
  safety posture materially changes.

### Escalation Classes

- `safety-critical`: continuing could corrupt source truth, mutate protected
  state, leak secrets, bypass guardrails, or create unbounded automation.
- `authority-critical`: required authority is unclear, conflicting, missing, or
  broader than the issue/skill permits.
- `intent-critical`: the requested behavior conflicts with owner intent,
  product/runtime boundaries, or the issue's non-goals.
- `autonomous-failure-critical`: the autonomous loop cannot demonstrate further
  progress or classify the failure after bounded diagnosis, or cannot prove
  branch/head truth **and** a safe recovery would require one of the explicit
  `needs_owner` authority categories above.

## Closure Eligibility

Autonomous closure is future-only. No autonomous merge or closure may happen
before all required guardrails exist and are verified.

Closure prerequisites:

- #3214 evidence-pack contract is implemented and available for the PR.
- #3215 branch-protection and branch-guardrail contract is implemented and
  enforced for protected branches and PR branches.
- The PR head SHA is current and all required checks are green for that SHA.
- Machine review gate passes for the current head SHA.
- All issue acceptance criteria and `Verify:` markers have evidence.
- Required owner-doc writeback is complete, or a no-owner-doc-change receipt is
  present and justified.
- No unresolved blocking P0/P1 human review thread, P0/P1 machine finding, CI failure, or
  Human Exception packet remains.
- Every P2 review finding has a durable defect Issue reference and deferred
  reply/disposition; P3 findings remain informational.
- BuilderOps routing and delivery receipts are current when the issue contract
  requires them.

Forbidden before guardrails:

- Autonomous merge.
- Autonomous issue closure.
- Auto-approval of review findings.
- Label or Project state mutation as a side effect of CI repair or review.
- Branch protection, required-check, workflow, or auto-merge mutation.

The `verification-and-closure` skill remains the governing closure behavior
until these future contracts are implemented by separate issues.

## Traceability

Primary issue anchors:

- #3211: autonomous review and repair planning context.
- #3224: Builder System process-map parent context.
- #3225: this design task and acceptance contract.

Source docs and skills:

- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `.codex/skills/verification-and-closure/SKILL.md`
- `.codex/skills/pr-integration/SKILL.md`
- `.codex/skills/_shared/CI_WAIT_CONTRACT.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/development/DEV_WORKFLOW.md`
- `docs/development/AGENT_OPERATING_PROTOCOL.md`
- `docs/development/GOVERNANCE_PROPORTIONALITY.md`

This document is intentionally narrower than the process map. The process map
names the Builder System lanes and target automation surfaces; this contract
defines the minimum gate behavior those future surfaces must satisfy before
they can safely mutate branches, PRs, issues, or closure state.
