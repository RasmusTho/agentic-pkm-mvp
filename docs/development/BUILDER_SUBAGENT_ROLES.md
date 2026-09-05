State: Development reference. Builder System governance; not Product/Runtime truth. Not an auto-loaded instruction file.
# Builder Subagent Roles

Shared, human-readable role map for active Codex specialist subagents working on this repository. It
exists so subagent roles are explicit and discoverable without duplicating workflow contracts.
Historical Claude compatibility is retained only as provenance; it is not an active Builder route.

## Purpose

Subagents are **execution roles**, not workflow contracts. Repo-local skills under `.codex/skills/**`
remain the canonical workflow contracts. A subagent role chooses *who* runs a job and with what
posture; the skill defines *how* the job is done. A role never replaces, overrides, or restates a
skill.

## Authority model

- `AGENTS.md` is the canonical builder-agent entrypoint. Every coordinator and worker reads it first.
- `.codex/skills/**` own the workflow contracts. They are canonical; subagents load them, they do not
  inline them.
- `.codex/agents/*.toml` are Codex-specific execution-role adapters. `.codex/config.toml` carries
  Codex agent settings (fan-out limits). Both are Builder System governance surfaces, classified in
  `docs/architecture/SBS_OPERATING_MODEL.md` — not Product/Runtime truth and not runtime/system-agent
  semantics.
- Codex does **not** auto-discover this repo's `.codex/skills/**` (its native skill discovery path is
  `.agents/skills`). Every adapter must therefore name and load the skill files it depends on
  explicitly. Do not rely on implicit skill discovery.
- The active Builder worker carrier is Codex. `CLAUDE.md` and any Claude-specific role material are
  compatibility/provenance surfaces only; native `.claude/agents/**` adapters and Claude/Anthropic
  authentication are not part of current Builder operation.
- `.codex/agents/` also contains the legacy `docs-guardian.yaml` definition. MAS-03 removed its
  optional credential-gated invocation from `.github/workflows/architecture-ci.yaml`; the retained
  file is not a live CI integration or a specialist delivery role in this map.

## Classification

Builder System governance. Not Product/Runtime implementation. Primary SBS Impact:
`Builder System / CES boundary`. Subagent handoffs and failures are Builder learning inputs only — they
never become runtime/user memory without an explicit Product authority path.

## Operability note

Codex project-scoped custom agents under `.codex/agents/**` are supported by the documented schema, but
current Codex releases have an open defect ([openai/codex#26408](https://github.com/openai/codex/issues/26408))
where project-scoped agents are advertised yet fail to spawn (`agent type is currently not available`).
Until that is fixed upstream, these adapters are governed-but-dormant: treat them as the canonical role
definitions, and run them globally (`~/.codex/agents/`) only as a deliberate, machine-local workaround.
Do not depend on repo-scoped spawning in automation yet.

## Role inventory

Five execution roles. Each maps to exactly one canonical skill and stays in its lane.

| Role (`name`) | Adapter file | Job | Canonical skill |
|---|---|---|---|
| `issue_set_coordinator` | `.codex/agents/issue-set-coordinator.toml` | Top-level/root execution role for issue-set planning and dispatch: readiness tables, pickup order, fan-out rationale, receipt reconciliation. Do not insert it as an extra subagent beneath a parent that already coordinates the same set. Coordinates only; does not implement. Defaults to Luna / low for deterministic intake and dispatch; judgment routes through the canonical TCD policy. | `.codex/skills/deliver-issue-set/SKILL.md` |
| `slice_implementer` | `.codex/agents/slice-implementer.toml` | Implement exactly one bounded, strictly validated `agent:ready` issue end to end; Project Status is optional projection. | `.codex/skills/issue-to-code/SKILL.md` |
| `issue_local_helper` | `.codex/agents/issue-local-helper.toml` | Answer one bounded read-only evidence, test-design, log-analysis, or fresh-review question for an issue owner; no writes or lifecycle authority. | `.codex/skills/issue-to-code/SKILL.md :: Issue Context Ownership And Bounded Delegation` |
| `backlog_contract_maintainer` | `.codex/agents/backlog-contract-maintainer.toml` | Repair stale, malformed, duplicate, or drifted Issue/PR/label state plus optional Project projection. | `.codex/skills/issue-maintenance-change-control/SKILL.md` |
| `verification_closer` | `.codex/agents/verification-closer.toml` | Verify a PR against its governing contract, check CI/review state, and close delivery. | `.codex/skills/verification-and-closure/SKILL.md` |

The host-local verification dispatch consumer may launch or resume the coordinator session for this
adapter, but it does not broaden the adapter's authority. Every independent review and re-review is
a fresh session; only the coordinator may resume its recorded session after restart. Repair attempts
use evidence-based convergence across the whole PR: the ledger retains every monotonic round, TCD
selects capability, every substantive repair receives a fresh independent review, and the loop stops
only on documented non-progress, technical impasse, scope expansion, or authority conflict rather
than a fixed attempt count.

## Skill-to-role routing matrix

| Task shape | Canonical skill | Role |
|---|---|---|
| Epic / parent feature / lane / ready-issue-set planning and dispatch | `deliver-issue-set` | `issue_set_coordinator` |
| One bounded slice issue → code → PR | `issue-to-code` | `slice_implementer` |
| One bounded issue-local read-only question | `issue-to-code` delegation contract | `issue_local_helper` |
| Issue/PR/label lifecycle correction or optional Project projection repair | `issue-maintenance-change-control` | `backlog_contract_maintainer` |
| Verify delivered slice, merge, close the loop | `verification-and-closure` | `verification_closer` |

If a task does not match a role, do not invent one: run the matching skill directly per `AGENTS.md`.

## Bounded loop policy

- Subagent loops are **verifier-driven repair loops only** — a worker produces, a verifier checks, the
  worker repairs against named findings.
- Codex counts the root session as depth 0. For issue sets the supported topology is root
  `issue_set_coordinator`(0) → `slice_implementer`(1) → optional issue-local helper(2).
  `.codex/config.toml` sets `[agents] max_depth = 2`, permitting one bounded helper layer while
  refusing depth 3. The helper uses the `issue_local_helper` read-only adapter, cannot perform lifecycle/publication/merge
  effects, and cannot spawn again. Native in-process width is bounded by `max_threads = 3` per
  primary session. The serial subprocess bridge creates fresh primary sessions instead, so its
  repository scheduling cap is modeled separately as two usable non-root slots with recovery/review
  reserve; it must not be described as sharing the native pool.
- No generic looping agent. Loops terminate on a concrete verification verdict, not on a turn budget.

## Handoff receipt

Every worker receives a minimal context pack and returns a `subagent_handoff_receipt` so the coordinator
can act without hidden chat context. The pack and receipt schema remain carrier-neutral for historical
records and future capability resolution, while current worker invocation is Codex-only.

Fresh context and concurrent scheduling are separate decisions. Every independent non-trivial Issue
gets a fresh `slice_implementer` context even in a serial queue. Only deterministic or explicitly
`inline-local-cheaper` work remains in the root coordinator. Raw worker transcripts and logs remain
issue-local; the coordinator consumes durable refs and the compact receipt.

Before a worker returns a terminal handoff receipt, goes idle, or otherwise stops, it must run the
central `.codex/skills/klart/SKILL.md` closeout gate. The gate may route remaining work through the
owning workflow skill or produce a truthful handoff, but its recommendation does not change the
handoff contract: `final_state` remains only `blocked | needs-human | handoff`; a worker must never
self-attest `done`.

Apply `.codex/skills/README.md :: Workflow continuation` at every role boundary. A helper returns
evidence to its active caller; an issue owner executes the next skill through verified closure.
Publication-only, pending-CI, and queued-verification receipts are intermediate progress, not
terminal delivery handoffs. The coordinator resumes premature returns and follows any fenced host
executor through reconciled effects. Only documented stop-loss, explicit user scope restriction,
or an authenticated active successor transfer permits the originating issue session to stop early.
These rules preserve the receipt enum and the lifecycle transfer protocol below.

A `subagent_handoff_receipt` reports work to a coordinator; it does not by itself transfer Issue
lifecycle authority. Replacing the sole writer or lifecycle owner requires a durable
`lifecycle_handoff_receipt.v1` on the governing Issue or PR. It records the Issue, current lifecycle
owner and session, named successor, branch and base, sole writable worktree, unpublished candidate
head (or `none`), changed files, current validation and current review/receipt evidence with head or
time binding, blockers, residual risk, and exactly one next authorized action.

For a dispatcher-backed handoff, the current owner first releases the exact dispatcher task with
`python3 -m app.dispatcher release <task-id> --agent <current-agent> --json` and re-reads the task
as unleased (`claimed_by: null`, `lease_id: null`) and ready or blocked. Only then may the Issue
return to `agent:ready`; the named successor runs the normal
`scripts/issue_pickup_claim.sh` dispatcher-backed pickup for the same task and re-reads task id,
Issue number, status, holder, lease id/resource, future expiry, and `released_at: null`. A
label-only fallback authenticates only its fallback receipt and never fabricates a dispatcher lease.
After the dispatcher release → successor claim/readback sequence, the current owner releases its
active worktree registration and re-reads it as non-active. The named successor then registers the
sole receipt-named worktree (or receipt-named replacement), re-reads its owner, branch, and
generation, and immediately compares the registered worktree's branch, base, candidate HEAD, and
changed-file set with the receipt. A changed candidate requires a new handoff receipt and fresh
validation before acknowledgment. Only after this dispatcher release → successor claim/readback →
worktree release → successor registration/readback → candidate revalidation sequence may the
successor post its acknowledgment. A connector-only transfer may instead authenticate
`writable_worktree: none`, but must not fabricate a local registration. If any release, claim,
registration, readback, or acknowledgment fails, authority does not transfer; Neither side may
publish, merge, or close in that intermediate state.

The acknowledgment fences the former lifecycle owner into a read-only role: the former owner may
supply evidence but may no longer edit, push, publish, merge, close, or mutate lifecycle state.
Contradictory owners, writable worktrees, candidate heads, or review evidence fail closed; newer
blocking review evidence supersedes an older publish or closure recommendation. Coordination resumes
only after the current owner or the normal maintenance/owner authority path reconciles one owner, one
current candidate head, and one next authorized action.

```yaml
lifecycle_handoff_receipt.v1:
  issue:                        # governing Issue number
  current_lifecycle_owner:      # agent + session currently holding lifecycle authority
  successor:                    # agent + session proposed to receive authority
  branch:                       # publication branch
  base:                         # base ref/SHA used by the candidate
  writable_worktree:            # sole absolute writable worktree, or none for connector-only work
  unpublished_candidate_head:   # exact commit SHA or none
  changed_files:                # bounded intended file set
  current_validation:           # commands/results bound to the candidate head
  current_review_receipt_evidence: # review/receipt refs plus observed time or head binding
  blockers:                     # active blockers or none
  residual_risk:                # remaining risk
  next_authorized_action:       # exactly one action
  successor_acknowledgment:     # absent until release/register/readback makes transfer effective
```

The dry-run helper for generating these packets is:

`python3 -m app.builderops builderops epic-run-state dispatch-plan --epic-issue-number <N> --run-id <safe-id> --candidates-file <file> --json`

It does not claim issues, mutate GitHub/Project/PR state, reserve branches/worktrees, touch dispatcher
leases, or spawn agents. Workers still self-claim through `issue-to-code` before editing.

## Executable serial dispatch

For a small ready Issue set, save the dry-run output and run:

`python3 -m app.builderops builderops epic-run-state dispatch-sessions --plan-file <frozen-plan.json> --repo-root <repo> --json`

This transitional local command validates the complete frozen plan before execution, then runs each
selected Issue through its governed delivery chain in deterministic order. Every Issue uses a new Codex session;
the command never resumes or reuses another Issue's session, and it stops before later Issues when
one session fails or returns `blocked`, `needs-human`, or `handoff`. The transitional bridge never
accepts a worker's self-reported terminal `done`: only verification-and-closure's live GitHub/Git/CI
readback may establish completed delivery. Each candidate must name an
explicit absolute worktree path; the worker creates or enters that dedicated worktree and
self-claims through `issue-to-code`. The coordinator does not preclaim, mutate GitHub lifecycle
state, merge, or close; the issue agent loads `publish-pr` and `verification-and-closure` at those
workflow boundaries and remains the sole lifecycle owner.

The command is intentionally Codex-only and serial. It is the simplest executable bridge from the
existing context-pack planner, not a second durable orchestrator. DDO-04's provider-neutral
`WorkerRuntimePort` must replace or absorb it before provider-neutral lifecycle control, reattachment,
retry, or crash recovery is claimed.

```yaml
subagent_handoff_receipt:
  role:                 # e.g. slice_implementer
  task:                 # issue/PR/lane identifier
  skill_loaded:         # .codex/skills/<name>/SKILL.md
  branch:               # working branch
  worktree:             # absolute worktree path
  actions:              # what was done
  ac_verdicts:          # AC-by-AC result where applicable
  lifecycle_mutations:  # GitHub state changes performed
  validation:           # commands run + results
  owner_doc_result:     # writeback path/anchor or "none"
  residual_risk:        # remaining risk / blockers
  final_state:          # blocked | needs-human | handoff (never self-attested done)
  next_step:            # single recommended next action
  context_cost:         # canonical AGENTS.md measurement or named proxy/unknown reason
```

## Historical Claude compatibility

The former Claude role route is preserved only so historical handoffs, audits, and compatibility
documents remain interpretable. It is not an active Builder carrier. Do not launch Claude, read
Anthropic credentials, or add `.claude/agents/**` adapters from this role map; any future carrier
requires a separately governed contract and current authority readback.
