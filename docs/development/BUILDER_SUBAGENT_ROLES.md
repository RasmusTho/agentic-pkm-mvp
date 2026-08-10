State: Development reference. Builder System governance; not Product/Runtime truth. Not an auto-loaded instruction file.
# Builder Subagent Roles

Shared, human-readable role map for Codex and Claude Code specialist subagents working on this
repository. It exists so subagent roles are explicit and discoverable without duplicating workflow
contracts.

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
- Claude Code does not consume Codex TOML as authority. Claude should use this role map together with
  `AGENTS.md` and the skills. Native `.claude/agents/**` adapters are intentionally **not** added; see
  Claude compatibility below.
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
are accounted across the whole PR as two standard attempts followed by at most two
strongest-capability attempts.

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

Every worker receives a minimal runtime-neutral context pack and returns a `subagent_handoff_receipt`
so the coordinator can act without hidden chat context. Codex and Claude use the same pack and receipt
schema; differences such as runtime/model hints belong in the invocation metadata, not in duplicate
workflow contracts.

Fresh context and concurrent scheduling are separate decisions. Every independent non-trivial Issue
gets a fresh `slice_implementer` context even in a serial queue. Only deterministic or explicitly
`inline-local-cheaper` work remains in the root coordinator. Raw worker transcripts and logs remain
issue-local; the coordinator consumes durable refs and the compact receipt.

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
one session fails or returns `blocked`, `needs-human`, or a non-terminal `handoff`. Only `done` counts
as completed delivery. Each candidate must name an
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
  final_state:          # done | blocked | needs-human | handoff
  next_step:            # single recommended next action
  context_cost:         # canonical AGENTS.md measurement or named proxy/unknown reason
```

## Claude compatibility

- Use the role names above as prompt-level execution roles for Claude Code subagents.
- Route Claude through `AGENTS.md`, `CLAUDE.md`, and this doc. Do not treat `.codex/agents/*.toml` as
  Claude authority — Claude project subagents use `.claude/agents/**` (Markdown + YAML frontmatter), a
  different format.
- Do not add `.claude/agents/**` adapters here. Maintaining two parallel role systems raises
  coordination and rework cost; introduce native Claude adapters only if Claude usage shows enough
  human-time savings to offset the duplication, as a separate decision.
