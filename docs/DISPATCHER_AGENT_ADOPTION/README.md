---
name: Dispatcher Agent Adoption
description: Specification for wiring the local Agent Issue Dispatcher into agent pickup workflow
doc_role: Specification directory
authority: Canonical specification for dispatcher adoption — wiring, fallback policy, and agent workflow integration
temporal_class: operational
review_cadence: event-driven
source_of_truth: mixed (code + AGENTS.md + issue-to-code skill)
last_reviewed: 2026-07-02
last_verified_against: docs/AGENT_ISSUE_DISPATCHER.md, app/dispatcher/cli.py, AGENTS.md, .codex/skills/issue-to-code/SKILL.md
---

# Dispatcher Agent Adoption — Specification

State: Implemented. Delivered by #637/#642/#639/#640 (parent #636, closed); see `docs/AGENT_ISSUE_DISPATCHER.md` for the live MVP + adoption contract.

## Purpose

The local Agent Issue Dispatcher MVP is complete (all child issues #621–#625 merged). The dispatcher CLI exists and all primitives (init, queue, next, claim, heartbeat, release, block, events, pull-sync) are implemented. This specification defined the post-MVP adoption work to make agents actually use it; that work is now delivered.

Delivered: `AGENTS.md` and `.codex/skills/issue-to-code/SKILL.md` both call the dispatcher (claim/heartbeat/complete) with an explicit GitHub-label-only fallback when the dispatcher is unavailable — see `docs/AGENT_ISSUE_DISPATCHER.md` §"Adoption Status".

## Capability boundary

Agents use the dispatcher as the hot-path claim primitive for picking up and executing GitHub Issues. GitHub Issues remain the durable source of truth. The dispatcher owns local operational coordination state: queue ordering, lease exclusivity, heartbeat liveness, and event audit trail. If the dispatcher is unavailable, agents fall back to GitHub-label-only claim.

## Implementation tasks

In dependency order:

1. [BOOTSTRAP_AND_SYNC_WIRING](BOOTSTRAP_AND_SYNC_WIRING.md) — `make dispatcher-init`, `make dispatcher-sync`, and a CLI guard when DB is missing; adds `dispatcher pull` command
2. [COMPLETE_COMMAND](COMPLETE_COMMAND.md) — adds `dispatcher complete` as a clean terminal signal for agents
3. [FALLBACK_POLICY](FALLBACK_POLICY.md) — documents the fallback contract in AGENTS.md and the issue-to-code skill
4. [AGENT_WORKFLOW_INTEGRATION](AGENT_WORKFLOW_INTEGRATION.md) — wires claim/heartbeat/complete into issue-to-code skill (shadow mode first, then dispatcher-first)

Tasks 1–2 can proceed in parallel. Task 3 can proceed after task 1 (needs the status command to be reliable). Task 4 depends on 1–3.

## Execution order

```
BOOTSTRAP_AND_SYNC_WIRING  ─┐
COMPLETE_COMMAND            ─┤─→ FALLBACK_POLICY ─→ AGENT_WORKFLOW_INTEGRATION
```

## Acceptance criteria

- [x] `make dispatcher-init` initialises the DB and runs a pull-sync against open `agent:ready` issues.
  Verify: `Makefile` targets `dispatcher-init`/`dispatcher-sync` (line ~356); shipped via #637 per `docs/AGENT_ISSUE_DISPATCHER.md`.
- [x] `make dispatcher-sync` re-syncs the queue without reinitialising.
  Verify: `Makefile` target `dispatcher-sync`; shipped via #637 per `docs/AGENT_ISSUE_DISPATCHER.md`.
- [x] `python -m app.dispatcher status --json` returns `db_exists: true` or a clear error if not initialised.
  Verify: `app/dispatcher/cli.py :: _cmd_status` (`db_exists` field); referenced live in `.codex/skills/issue-to-code/SKILL.md`.
- [x] `python -m app.dispatcher complete <task_id> --agent <id>` marks the task completed and emits `task.completed`.
  Verify: `app/dispatcher/cli.py :: _cmd_complete`; shipped as #642 per `docs/AGENT_ISSUE_DISPATCHER.md`.
- [x] `AGENTS.md` contains a Dispatcher policy section describing the agent loop, TTL, heartbeat cadence, and fallback rule.
  Verify: `AGENTS.md` §"Dispatcher policy" (line ~328).
- [x] `issue-to-code/SKILL.md` includes dispatcher claim/heartbeat/complete steps with explicit fallback path.
  Verify: `.codex/skills/issue-to-code/SKILL.md` dispatcher-first flow (claim/heartbeat/complete/fallback), lines ~135-157.
- [x] An agent running issue-to-code calls `dispatcher claim` before starting work when the dispatcher is available.
  Verify: three adoption receipts verified and logged on parent feature issue #636 per `docs/AGENT_ISSUE_DISPATCHER.md` §"Adoption Status".

## Validation / acceptance path

Acceptance met:
1. All four tasks merged with their per-task acceptance criteria green.
2. Three consecutive issue-to-code deliveries where the dispatcher claim/heartbeat/complete loop was called (adoption evidence logged on parent feature issue #636).
3. Owner doc (`docs/AGENT_ISSUE_DISPATCHER.md`) updated to reflect dispatcher as active ("MVP Implementation Status: SHIPPED", "Adoption Status: ACTIVE").

## Source anchors

- `docs/AGENT_ISSUE_DISPATCHER.md` — dispatcher MVP contract
- `app/dispatcher/cli.py` — CLI implementation
- `app/dispatcher/sync_github.py` — pull-sync adapter
- `AGENTS.md :: GitHub delivery governance`
- `.codex/skills/issue-to-code/SKILL.md`
- Parent feature issue: #617 (closed — dispatcher MVP complete; this workstream is post-MVP adoption)
