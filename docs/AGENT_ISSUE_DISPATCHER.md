State: MVP implementation shipped (#622 store, #623 queue/lease, #624 CLI); GitHub sync (#625) still open.
Doc role: Reference contract (development governance)
Authority: Authoritative contract for local Agent Issue Dispatcher MVP boundaries and behavior expectations.
Owner: Delivery governance / multi-agent coordination
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed (GitHub issue contracts + repo governance docs)
Last reviewed: 2026-04-25
Last verified against: #617, #621, #622, #623, #624, #561, AGENTS.md, docs/ARCHITECTURE.md, docs/development/GITHUB_GOVERNANCE_SETUP.md, .github/github-governance.yml

# Agent Issue Dispatcher (MVP Contract)

## Purpose

Define the first authoritative contract for a local Agent Issue Dispatcher MVP that helps multiple agents coordinate issue pickup and execution safely.

The dispatcher is an operational coordination layer, not a lifecycle replacement for GitHub.

## Current-State Honesty

- This document defines an MVP contract boundary only.
- Dispatcher storage (#622), queue/lease (#623), and CLI (#624) are shipped on main. GitHub sync (#625) is still open and not claimed as shipped here.
- Existing GitHub issue/PR/label/project governance in `AGENTS.md` and `docs/development/GITHUB_GOVERNANCE_SETUP.md` remains current truth today.

## Source-of-Truth Boundaries

| Surface | Role in MVP | Authority |
| --- | --- | --- |
| GitHub Issues / PRs / CI | Durable delivery lifecycle and merge truth | Hard authority |
| Local Dispatcher state | Fast operational coordination (queue, claims, leases, heartbeats, local progress) | Operational authority only |
| GitHub Project / external boards | Human-facing projection | Optional projection, not hot path |

Normative boundary:
- GitHub remains the durable development source of truth.
- Dispatcher owns local operational multi-agent coordination state.
- External boards (including GitHub Projects) are optional projections and must not be required in the agent hot path.

## Non-Goals (MVP)

- Replacing GitHub Issues/PRs/CI as durable truth.
- Requiring GitHub Projects in the hot path.
- Becoming a general workflow metadata platform.
- Requiring Postgres, Docker, FastAPI, Ollama, watcher, Obsidian, or iCloud.
- Implementing distributed multi-repo scheduling.
- Implementing web dashboard or MCP-first service mode.

## MVP Data Model (Contract Level)

## Task Record

Required fields:
- `task_id`: stable local identifier (string).
- `issue_number`: GitHub issue number (int).
- `title`: task title snapshot (string).
- `status`: local dispatcher status (enum, see below).
- `priority`: dispatcher-local sort key (enum/string).
- `source_anchor_refs`: list of source anchor references (list[string]).
- `claimed_by`: agent/execution identifier or null (string|null).
- `lease_id`: active lease identifier or null (string|null).
- `lease_expires_at`: lease expiry timestamp or null (RFC3339|null).
- `created_at`: record creation timestamp (RFC3339).
- `updated_at`: record update timestamp (RFC3339).

Optional fields:
- `linked_pr`: PR number/url if known (string|int|null).
- `blocked_reason`: explicit blocker reason when blocked (string|null).
- `last_heartbeat_at`: last lease heartbeat timestamp (RFC3339|null).
- `sync_state`: local GitHub sync metadata object (object|null).

## Lease Record

Required fields:
- `lease_id`: unique lease id (string).
- `resource`: claimed resource key (for MVP normally `issue:<number>`) (string).
- `holder`: execution/agent id (string).
- `ttl_seconds`: granted TTL (int).
- `acquired_at`: acquisition timestamp (RFC3339).
- `expires_at`: expiry timestamp (RFC3339).

Optional fields:
- `heartbeat_at`: last heartbeat timestamp (RFC3339|null).
- `released_at`: release timestamp (RFC3339|null).
- `release_reason`: release reason (`completed`, `blocked`, `manual`, `expired`, etc.) (string|null).

## Event Record

Required fields:
- `event_id`: unique event id (string).
- `timestamp`: event timestamp (RFC3339).
- `task_id`: related task id (string).
- `event_type`: contract event type (enum/string).
- `actor`: agent/execution id (string).

Optional fields:
- `lease_id`: related lease id (string|null).
- `payload`: compact event payload object (object|null).

Event types (minimum):
- `task.discovered`
- `task.claimed`
- `task.heartbeat`
- `task.updated`
- `task.blocked`
- `task.released`
- `task.completed`
- `task.linked_pr`
- `task.sync_observed`

## Sync-State Object (Optional in MVP)

When present, `sync_state` may include:
- `last_pull_at` (RFC3339)
- `source_version` (etag/hash/updated marker)
- `sync_result` (`ok`, `stale`, `conflict`, `error`)
- `sync_note` (string)

MVP must remain testable without GitHub API access; sync-state is optional and never required for core queue/lease behavior.

## Status Model and Transition Principles (MVP)

Minimum statuses:
- `ready`: eligible for next/claim.
- `claimed`: held by active lease.
- `in_progress`: active execution with valid lease.
- `blocked`: cannot proceed without explicit resolution.
- `completed`: terminal success.
- `released`: returned to queue or explicitly relinquished.

Transition principles:
- Only `ready` tasks are eligible for new claim.
- Claim must atomically establish lease ownership (`ready -> claimed`).
- Work starts under valid lease (`claimed -> in_progress`).
- Heartbeat/renewal must occur before expiry while work continues.
- Completion is terminal for the local task run (`in_progress -> completed`).
- Blocking is explicit and reasoned (`in_progress -> blocked`).
- Release is explicit and reasoned (`claimed|in_progress -> released`), then task may re-enter `ready` if policy allows.
- Expired lease must clear ownership and produce an observable release/expiry event.

## Lease / Claim Model (MVP)

Normative behavior:
- Lease is the concurrency primitive; claim without lease is invalid.
- Lease scope is minimal and deterministic (`issue:<number>` at minimum).
- TTL is mandatory.
- Renewal uses heartbeat by the current holder only.
- Release requires holder identity (or explicit operator override path in future work).
- Dispatcher must provide deterministic conflict response for double-claim attempts.

Design boundary:
- This extends the minimal shared lease boundary from #561 and `docs/development/GITHUB_GOVERNANCE_SETUP.md` but does not absorb #561's git-hygiene scope.

## Agent Interaction Contract (MVP Loop)

Canonical loop:
1. `next`: request next eligible task (`ready` only).
2. `claim`: create lease and claim ownership.
3. `work`: execute issue scope locally.
4. `heartbeat/update`: renew lease and persist status/progress.
5. `link_pr`: attach PR reference when opened.
6. `complete` or `block` or `release`: write terminal or transitional outcome.

Operational expectations:
- Agents must not mutate lifecycle truth in dispatcher in ways that conflict with GitHub issue/PR truth.
- Dispatcher outputs should be compact and actionable for CLI-driven agents.
- Failure to heartbeat before expiry makes the claim recoverable by others after lease expiry processing.

## Observability and Persistence Expectations (MVP)

MVP persistence/visibility shape:
- SQLite: canonical local operational store for tasks, leases, and current state.
- JSONL: append-only operational event/audit log for deterministic replay/inspection.

Contract expectations:
- Every state transition and lease action emits a JSONL event.
- SQLite current-state rows and JSONL event history must be correlation-friendly (`task_id`, `lease_id`, timestamps).
- JSONL log is append-only; do not treat it as the live lock primitive.
- SQLite is the lock/current-state authority; JSONL is the audit trail and debugging surface.

## Relationship to #617 and #561

- #617 is the parent dispatcher workstream and sequencing authority. This document satisfies #621 as the prerequisite contract before implementation issues proceed.
- #561 defines the minimal shared lease and git-hygiene guardrails. Dispatcher MVP reuses that lease-boundary intent but remains scoped to issue coordination, not janitor/preflight tooling.

## Future Extensions (Not MVP)

- GitHub pull-sync with richer conflict classification and reconciliation policies.
- Push/projection adapters for optional boards.
- Branch/worktree reservation policy integration.
- Multi-resource claims and lane-level scheduling policies.
- Service mode (API/MCP) once CLI-first local mode is stable and verified.
- Rich metrics/inspection commands and backlog-health diagnostics.

## Source Anchors

- #617
- #621
- #561
- `docs/development/GITHUB_GOVERNANCE_SETUP.md :: Shared operational lease boundary`
- `AGENTS.md :: GitHub delivery governance`
