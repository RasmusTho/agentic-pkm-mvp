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
- `.codex/agents/` also contains the legacy `docs-guardian.yaml` CI-invoked automation agent
  (`codex run docs-guardian` in `.github/workflows/architecture-ci.yaml`). It predates the TOML
  execution-role adapters and uses a different schema; it is a separate, narrower CI-repair agent, not
  a specialist delivery role in this map.

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

Four initial execution roles. Each maps to exactly one canonical skill and stays in its lane.

| Role (`name`) | Adapter file | Job | Canonical skill |
|---|---|---|---|
| `issue_set_coordinator` | `.codex/agents/issue-set-coordinator.toml` | Plan and dispatch an issue-set: readiness tables, pickup order, fan-out rationale, receipt reconciliation. Coordinates only; does not implement. | `.codex/skills/deliver-issue-set/SKILL.md` |
| `slice_implementer` | `.codex/agents/slice-implementer.toml` | Implement exactly one bounded `Ready` + `agent:ready` issue end to end. | `.codex/skills/issue-to-code/SKILL.md` |
| `backlog_contract_maintainer` | `.codex/agents/backlog-contract-maintainer.toml` | Repair stale, malformed, duplicate, or drifted Issue/PR/Project state. | `.codex/skills/issue-maintenance-change-control/SKILL.md` |
| `verification_closer` | `.codex/agents/verification-closer.toml` | Verify a PR against its governing contract, check CI/review state, and close delivery. | `.codex/skills/verification-and-closure/SKILL.md` |

## Skill-to-role routing matrix

| Task shape | Canonical skill | Role |
|---|---|---|
| Epic / parent feature / lane / ready-issue-set planning and dispatch | `deliver-issue-set` | `issue_set_coordinator` |
| One bounded slice issue → code → PR | `issue-to-code` | `slice_implementer` |
| Issue/PR/label/Project lifecycle correction or drift repair | `issue-maintenance-change-control` | `backlog_contract_maintainer` |
| Verify delivered slice, merge, close the loop | `verification-and-closure` | `verification_closer` |

If a task does not match a role, do not invent one: run the matching skill directly per `AGENTS.md`.

## Bounded loop policy

- Subagent loops are **verifier-driven repair loops only** — a worker produces, a verifier checks, the
  worker repairs against named findings.
- No recursive fan-out: a worker does not spawn workers. Fan-out depth is capped in `.codex/config.toml`
  (`[agents] max_depth = 1`) and width by `max_threads = 3`.
- No generic looping agent. Loops terminate on a concrete verification verdict, not on a turn budget.

## Handoff receipt

Every worker returns a `subagent_handoff_receipt` so the coordinator can act without hidden chat
context.

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
```

## Claude compatibility

- Use the role names above as prompt-level execution roles for Claude Code subagents.
- Route Claude through `AGENTS.md`, `CLAUDE.md`, and this doc. Do not treat `.codex/agents/*.toml` as
  Claude authority — Claude project subagents use `.claude/agents/**` (Markdown + YAML frontmatter), a
  different format.
- Do not add `.claude/agents/**` adapters here. Maintaining two parallel role systems raises
  coordination and rework cost; introduce native Claude adapters only if Claude usage shows enough
  human-time savings to offset the duplication, as a separate decision.
