State: Active and operational. MVP implementation complete and shipping in agent workflows (issue-to-code skill via dispatcher claim/heartbeat/complete).
Doc role: Reference contract (development governance)
Authority: Authoritative contract for local Agent Issue Dispatcher MVP boundaries and behavior expectations.
Owner: Delivery governance / multi-agent coordination
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed (GitHub issue contracts + repo governance docs)
Last reviewed: 2026-07-10
Last verified against: #617, #621, #622, #623, #624, #625, #637, #639, #640, #561, #3312, #3603, AGENTS.md, docs/ARCHITECTURE.md, docs/development/GITHUB_GOVERNANCE_SETUP.md, .github/github-governance.yml

# Agent Issue Dispatcher (MVP Contract)

## Purpose

Define the first authoritative contract for a local Agent Issue Dispatcher MVP that helps multiple agents coordinate issue pickup and execution safely.

The dispatcher is an operational coordination layer, not a lifecycle replacement for GitHub.

## Current-State Honesty

**MVP Implementation Status: SHIPPED ✅**

- Dispatcher runtime/storage foundation (#622), queue/lease lifecycle (#623), and agent-facing CLI (#624) are shipped.
- GitHub pull-sync boundary (#625) is shipped: `app/dispatcher/sync_github.py` provides the `PullSyncAdapter`, `GhCliIssueSource`, and `normalize_github_issue` normalisation function.
- Bootstrap-and-sync wiring (#637) is shipped: `python -m app.dispatcher pull --repo <owner/repo>` command, `make dispatcher-init` (init + pull), `make dispatcher-sync` (pull only), and missing-DB guard for CLI commands.
- Complete command (#642) is shipped: `python -m app.dispatcher complete <task_id> --agent <agent_id>` marks tasks finished and releases leases cleanly.
- Fallback policy (#639) is shipped: dispatcher loop, TTL, heartbeat cadence, and GitHub-label-only fallback are documented in `AGENTS.md` and `.codex/skills/issue-to-code/SKILL.md`.
- Dispatcher cleanup in verification-and-closure (#662) is shipped: ensures leases are released when issues are merged, partially delivered, or abandoned.

**Adoption Status: ACTIVE ✅**

- Agents are now wired to use the dispatcher as the hot-path claim primitive (issue-to-code skill).
- Dispatcher operates in shadow mode: agents call claim/heartbeat/complete while GitHub labels remain durable truth.
- Fallback to GitHub-label-only claim is always available when dispatcher is unavailable.
- Three adoption receipts verified and logged on parent feature issue (#636).
- Existing GitHub issue/PR/label/project governance in `AGENTS.md` and `docs/development/GITHUB_GOVERNANCE_SETUP.md` remains current truth today.

**Verification dispatch consumer: SHIPPED IN REPO (host enablement is separate)**

- `app.dispatcher.verification_dispatch` extends the same SQLite control plane with versioned,
  idempotent PR/head verification runs, one global active subscription slot, exact lease-token
  fencing, durable retry timestamps, attempts, receipts, and deduplicated Human Exception packets.
- Initial verification claims acquire the authoritative SQLite write lock before sampling both
  eligibility time and lease expiry. Token-authorized mutations use the same post-lock authority
  clock, so lock waits cannot create already-expired leases or revive expired coordinators.
- `app.dispatcher.verification_consumer` re-fetches live PR/check truth, requires a successful
  ChatGPT/keyring auth preflight, builds a minimal immutable context pack, and launches only the
  registered `verification_closer` adapter with its pinned model, reasoning, sandbox, and developer
  instructions. Streaming `codex exec --json --output-schema` events persist the thread identity
  immediately. The consumer independently reloads the canonical schema and applies both structural
  and semantic receipt validation to every launcher result before persisting attempts, review events,
  or closure evidence; injected or replacement launchers cannot bypass that trust boundary.
- Before process start, the launcher rejects output schemas outside the Codex Structured Outputs
  subset (including conditional composition and object fields that are not required). The provider
  schema keeps optional values explicitly nullable; local semantic validation still fail-closes a
  delivered receipt without two review events or a repair event without its finding identity.
- Artifact ingestion binds the untrusted request repository, artifact name, uploader workflow-run
  id, repository id, and `source_workflow` identity to authenticated GitHub metadata before
  dispatcher persistence or any target-PR read. The source workflow is fetched inside the already
  authenticated artifact repository and must match the claimed run id, name, attempt, head,
  pull-request event, completed/success state, and repository identities. Authenticated
  compressed-size metadata is checked before
  download; the production stream, ZIP member count, aggregate declared size, and request member are
  independently bounded before an in-memory request is accepted. A mismatch or oversized artifact
  fails closed before claim or model launch.
- Missing or pending checks and auth/rate limits enter time-bounded `backoff`; replay cannot launch
  before `retry_after`. Rate-limit classification requires either a structured `retry` receipt or the
  launcher's structured `failure_class=rate_limit`, derived once from a non-zero provider failure;
  only parsed provider fields such as status 429 or canonical failure codes can create that signal,
  while free-form, arbitrary, negated, or explicitly false terminal/stderr prose cannot select
  rate-limit backoff. Terminal completion
  additionally requires two fresh clean
  review receipts after the final durable repair attempt. Standard and strongest-capability repair
  budgets are persisted across restart.
- Completion never relies on coordinator receipt ids or review-event prose alone. The fresh exact-head
  GitHub read must contain a named, completed, successful `Unit tests (not pg)` check produced by
  the authoritative `github-actions` App; same-name checks from another or unidentified producer
  are ignored before latest-rerun selection. The required workflow job runs repo-wide `mypy app`
  before it can publish success. Missing, unnamed, skipped, neutral, pending, or failed
  required-check evidence cannot open closure.
- The schema-valid coordinator receipt carries ordered repair/review events into the same
  lease-fenced ledger as one atomic, deterministically identified batch. Exact receipt replay is a
  no-op, and a later invalid/conflicting event rolls back the whole batch. A semantic event-batch
  rejection becomes an exact-lease technical terminal receipt before any pending-check backoff, so
  invalid review or repair events cannot strand coordinator authority or consume a partial budget;
  a no-repair delivery still requires two distinct clean review sessions. Check eligibility selects the latest GitHub rerun per
  check name. Schema-v3 health, backup, and restore validation covers verification runs, attempts,
  exceptions, head-audit fields, and their write-critical keys. A deployed pre-head-rebinding v3
  backup may omit only the two additive current/verified-head columns: recovery preserves that
  artifact, and the first normal store open atomically backfills the current head from the immutable
  request head while retaining all prior audit rows. Missing older audit tables, columns, or unique
  keys still fail closed before migration. Both normal self-migration and explicit initialization
  validate the complete resulting verification schema inside the migration transaction before the
  v3 marker can be written or committed.
  If normal stale-head handling supersedes a chain before the repaired-head artifact arrives, only
  a later artifact with the same repository, PR, stage, and governing issue may reopen that exact
  chain on the new head. Reopening preserves immutable requested-head audit plus all attempts and
  2+2 budget, while clearing stale lease, session, context, retry, and terminal state. No other
  terminal status or supersession reason is reopenable, and a different-head artifact cannot route
  around that terminal chain by creating an empty run. Exact same-artifact replay is resolved
  globally before any canonical-chain decision. A stale-head reopen is allowed only when that row
  is the unambiguous terminal set; another terminal row fails closed without mutation. Further work
  requires a governed lifecycle decision rather than a budget reset. Any legacy database containing
  both an active chain and a terminal chain for the same authority is rejected before exact or active
  replay, so a newer empty run cannot hide older spent budget.
- The Codex process boundary drains bounded stderr concurrently and rejects non-zero exits or
  terminal error events even when stdout contained an otherwise valid receipt. A bounded rate-limit,
  usage-limit, quota, or credit-exhaustion signal on that non-zero path remains a lease-fenced backoff
  receipt with no repair-budget use or API-key fallback. Raw stderr, terminal event content, exception
  text, paths, and credentials are transient classification input only: durable attempts, terminal
  receipts, and `verification-status` retain only bounded outcome, return-code, failure-class,
  error-type, retry, and canonical UUID coordinator-session fields. A zero exit without both thread
  identity and one schema-valid final receipt also enters exact-lease technical backoff. A returned
  receipt that fails the consumer's canonical schema or semantic validation terminals technically
  before attempt, event, or closure persistence; malformed or missing coordinator output can never
  report delivery or retain an active claim. Every launch carries a
  launch-scoped process-tree tracker plus a high-entropy tag so bounded cleanup can remove observed
  descendants even after a `setsid` escape. Before a clean terminal receipt returns, the launcher
  removes residual private-group members and requires a host containment adapter to prove whole-tree
  cleanup; tracker/tag-only best-effort cleanup never claims that proof, so an otherwise valid receipt
  fails technically on an uncontained host.
- Heartbeat rejection or failure to persist the thread identity under the exact lease is immediate
  loss of coordinator authority: the consumer terminates the private Codex process group, escalates
  surviving descendants to a bounded group kill, reaps the direct child, performs tracked whole-tree
  cleanup, rejects any later stdout,
  and records one bounded backoff receipt without accepting a terminal result from the
  authority-lost process. The same technical authority-loss path applies when the direct Codex
  parent exits but a descendant keeps inherited stdout open beyond the bounded drain grace;
  heartbeat renewal cannot outlive the direct coordinator.
- Pre-launch eligibility and post-launch delivery truth are separate gates. Launch still requires an
  open current-head PR; a `delivered` receipt is accepted only when a fresh GitHub read proves the
  exact repository, PR, head, merged state, merge timestamp, merge commit, and green checks.
  A source or contract-parse failure during that post-launch read enters exact-lease bounded
  technical backoff while retaining the deterministic verification attempt and pending terminal
  receipt for safe resume/replay. A pending delivered receipt bypasses the ordinary open-only intake
  gate on retry, but can complete only through a fresh authenticated exact-head merged/check read.
  When that receipt proves a repaired head, replay requires its durable repair event and performs
  the same exact-lease/live-PR-fenced head rebind before applying events or terminal state; the
  requested-head audit stays immutable while current and verified heads converge on the merged
  receipt head. Its event batch remains exact-replay idempotent.
  Persisted pending receipts are untrusted replay input: the consumer reloads the canonical schema
  and reapplies structural and semantic validation before authentication, event application, or
  completion. Corrupt or schema-unverifiable replay data terminals technically with redacted
  diagnostics and cannot create review or closure evidence.
- Governing-Issue authority is live truth, not an artifact-only assertion. Every authority-bearing
  PR read must still contain exactly the request's explicit governing issue and every original
  supporting-issue reference. Later bounded repair references may extend that supporting evidence
  monotonically without becoming governing or closure authority; removing original evidence or
  changing the governing issue fails closed.
- Authentication does not extend an earlier live-truth read atomically. After auth and lease claim,
  the consumer re-fetches head, governing contract, and checks immediately before launch; drift
  supersedes the claimed run, while missing or non-green checks back off. Both are technical
  prelaunch outcomes and start no coordinator. A GitHub source or contract-parse exception during
  that claimed read also enters lease-fenced bounded backoff instead of stranding a live claim.
- A genuine coordinator `needs_human` verdict crosses the one durable Human Exception boundary:
  the consumer accepts only one of the four governed failure classes plus the complete canonical
  owner-decision packet, then records it head- and governing-issue-bound before terminal state.
  Replay returns the same deduplicated exception without a second packet or launch. Receipt,
  head, live-truth, invalid-verdict, and closure-proof failures remain technical failures and never
  select `needs_human` or create an exception packet.
- The immutable request head remains the run/idempotency audit identity. A repair receipt may advance
  the separate current head only under the exact active lease after a fresh GitHub read proves that
  exact live PR head; terminal delivery records the verified head only after two clean reviews on it.
  A later artifact for that repaired head reuses the same active repository/PR/governing-issue run
  instead of opening an empty verification chain, so redispatch cannot reset prior attempts or the
  PR-wide standard/escalated repair and fresh-review accounting. A mismatched head or governing
  authority fails closed instead of sharing the ledger.
  When the repaired head's checks are still pending, its repair event is persisted before bounded
  backoff so replay cannot bypass the 2+2 ledger; review events are rejected until checks are green.
  An exact same-session terminal receipt replay reuses its deterministic verification attempt, so
  already-deduplicated review events retain the same closure anchor. A changed receipt or session
  creates a new anchor and must earn fresh reviews.
- `verification-ingest` and `verification-status` are host-neutral dispatcher CLI surfaces. The
  Demerzel enable/disable/poll wrapper and service configuration remain host-local outside Git.
- GitHub Actions remains artifact-only. The consumer grants no mutation or merge authority beyond
  `.codex/skills/verification-and-closure/SKILL.md`.

## Source-of-Truth Boundaries

| Surface | Role in MVP | Authority |
| --- | --- | --- |
| GitHub Issues / PRs / CI | Durable delivery lifecycle and merge truth | Hard authority |
| Dispatcher SQLite | Volatile operational coordination (queue, claims, leases, heartbeats, local progress) | Operational authority only |
| external BuilderOps Vault | Durable BuilderOps Markdown artifacts plus shared advisory TTL claims; never SQLite or authoritative leases | BuilderOps artifact authority |
| GitHub Project / Signboard / external boards | Human-facing views | Optional projection, not hot path |

Normative boundary:
- GitHub remains the durable development source of truth.
- Dispatcher SQLite owns volatile operational multi-agent coordination state.
- The external BuilderOps Vault stores durable Markdown artifacts and non-exclusive TTL claim
  signals. Dispatcher SQLite remains local and owns authoritative leases; vault claims are advisory
  visibility only and never distributed locks.
- External boards (including GitHub Projects) are optional projections and must not be required in the agent hot path.

The logical Builder Control Plane boundary is defined in
`docs/development/BUILDER_CONTROL_PLANE.md`. It records observable control-mode and recovery
receipts only; it does not replace GitHub lifecycle truth or claim physical runtime enforcement.

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
- Heartbeat records current-holder activity before expiry and atomically renews the lease for its granted TTL.
- Completion is terminal for the local task run (`in_progress -> completed`).
- Blocking is explicit and reasoned (`in_progress -> blocked`).
- Release is explicit and reasoned (`claimed|in_progress -> released`), then task may re-enter `ready` if policy allows.
- Expired lease must clear ownership and produce an observable release/expiry event.

## Lease / Claim Model (MVP)

Normative behavior:
- Lease is the concurrency primitive; claim without lease is invalid.
- Lease scope is minimal and deterministic (`issue:<number>` at minimum).
- TTL is mandatory.
- Heartbeat requires the current holder and an unexpired lease, and atomically renews both the
  lease and task expiry for the granted TTL.
- Release requires holder identity (or explicit operator override path in future work).
- Dispatcher must provide deterministic conflict response for double-claim attempts.

### Lease recovery

Batch recovery through `reclaim_expired_leases` remains available. An agent that discovers an
expired current lease may instead make an explicit, claim-time recovery with
`dispatcher claim <task_id> --takeover-stale`. The dispatcher performs the stale-lease release,
new lease creation, task update, and `task.claimed` event insert in one SQLite transaction. It
marks the displaced lease with `release_reason="stale_takeover"`; it never displaces an unexpired
lease, even when the flag is supplied. A normal stale claim remains eligible in its `claimed`
status; legacy/reclaimed `ready` rows remain eligible too. A blocked task with an expired lease is
rejected without changing its task or lease state.

The new claim event remains the receipt. Its payload contains `ttl_minutes` and, for a takeover, a
`takeover` object with `previous_holder`, `previous_lease_id`, and `previous_expires_at`. Without
the opt-in flag, an expired lease remains a claim rejection and the error directs the agent to
`--takeover-stale`.

Design boundary:
- This extends the minimal shared lease boundary from #561 and `docs/development/GITHUB_GOVERNANCE_SETUP.md` but does not absorb #561's git-hygiene scope.

## Agent Interaction Contract (MVP Loop)

Canonical loop:
0. Run `scripts/issue_pickup_claim.sh --issue <N> --repo <owner/repo> --agent <agent_id> --session <session_id>`.
   The wrapper checks `status --json`, claims the exact repo-qualified `github-<owner>--<repo>-issue-<N>`
   task (matching the id `dispatcher pull` assigns; pass `--task-id` to override) when dispatcher-backed,
   verifies the active lease and holder, and only then removes `agent:ready`. Dispatcher database or
   singleton existence is availability evidence, not claim evidence. In degraded mode the wrapper
   posts a durable claimant-intent comment with identity and fallback reason before label removal.
1. `next`: optional queue discovery only; it does not replace exact-task pickup verification.
2. `claim`: performed by the pickup wrapper for the exact task. Default TTL: **90 minutes**.
3. `work`: execute issue scope locally.
4. `heartbeat/update` (every **~30 minutes** of active execution): record activity and renew the
   90-minute lease before its expiry.
5. `link_pr`: attach PR reference when opened.
6. `complete` or `block` or `release`: write terminal or transitional outcome.

Operational expectations:
- A `dispatcher-backed` pickup receipt must name the verified task id, lease id, holder, and evidence.
- Missing task/lease, ownership mismatch, or malformed claim output fails before GitHub label mutation.
- Agents must not mutate lifecycle truth in dispatcher in ways that conflict with GitHub issue/PR truth.
- Dispatcher outputs should be compact and actionable for CLI-driven agents.
- Failure to heartbeat before expiry makes the claim recoverable by others after lease expiry processing.
- Commands requiring a live DB (`next`, `claim`, `queue`, `pull`) exit 1 with `{"ok": false, "error": "dispatcher not initialised — run: make dispatcher-init"}` when the DB is missing.

## Dispatcher Singleton Preparation

`python -m app.dispatcher start --agent <agent_id> --json` is the local singleton preparation command
for agents that are explicitly operating in dispatcher-backed coordination mode.

`start` behavior:
- creates the dispatcher state directory and SQLite schema when absent;
- writes a bounded singleton coordination record under the dispatcher state directory;
- returns a no-op/status receipt when an active singleton record already exists;
- serializes concurrent starts with a local guard lock and returns an explicit error on contention;
- recovers stale singleton metadata without deleting dispatcher DB or event state.

The singleton record is operational coordination evidence only. It does not run a daemon, claim work,
heartbeat task leases, mutate GitHub labels or Project state, merge PRs, close issues, or replace
GitHub/PR lifecycle truth. `status --json` reports the DB/events paths, singleton state
(`missing`, `active`, or `stale`), `coordination_mode`, and `fallback_reason` so
`deliver-issue-set` and `issue-to-code` can decide whether to use dispatcher or fallback paths
without guessing.

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

## GitHub Sync Model

The dispatcher pulls issue state from GitHub in a narrow, read-only adapter boundary.

Pull-sync contract:
- The adapter reads GitHub issue fields and normalises them into local `TaskRecord` rows.
- No write-back: the adapter never writes labels, comments, or status back to GitHub in the MVP.
- GitHub Projects is not queried or mutated in the sync hot path.
- Sync state (`last_pull_at`, `sync_result`, `sync_note`, rate-limit metadata) is recorded locally as a `_sync_meta:<provider>` task row.
- Sync failures record an `error` state in sync metadata and leave all existing task rows untouched.

Implementation surface:
- `app/dispatcher/sync_github.py` — `GitHubIssueSource` protocol, `GhCliIssueSource` (concrete `gh`-CLI-backed implementation), `PullSyncAdapter`, `normalize_github_issue`, sync-state helpers.
- `GitHubIssueSource` is a mockable protocol; the adapter never imports `requests`, `httpx`, or a GitHub SDK.
- `GhCliIssueSource` uses the `gh` CLI to list open issues with `agent:ready` label; requires `gh` authentication at runtime but is fully mockable in tests.
- `python -m app.dispatcher pull --repo <owner/repo> --json` is the shipped CLI command for pull sync.
  `--repo` may be repeated (`--repo owner/a --repo owner/b`) to pull multiple repos into the same
  dispatcher store in one call; each repo's issues upsert independently and aggregate into one JSON
  receipt under `repos`. Task IDs are repo-qualified (`github-<owner>--<repo>-issue-<n>`) so the same
  issue number in two different repos never collides, and stale-ready reconciliation is scoped per
  repo so pulling one repo cannot reconcile another repo's tasks. `make dispatcher-init` and
  `make dispatcher-sync` pull both `RasmusTho/agentic-pkm-mvp` and `RasmusTho/bifrost` (the two live
  Yggdrasil-ecosystem repos with an active `agent:ready` backlog today); `app.ops.builderops_startup`
  defaults to the same pair (`DEFAULT_REPOS`) when the full-stack launcher doesn't override `--repo`.
- Tests in `tests/dispatcher/test_sync_github.py` use only mocked data; no live GitHub API access is required.

## Sync Failure Behavior

If the `GitHubIssueSource` raises during `list_issues`:
1. `PullSyncAdapter.pull` catches the exception.
2. `record_sync_failure` writes `sync_result=error` and `sync_note=<error message>` to the provider meta row.
3. The method returns an empty list.
4. Existing task rows in the store are unaffected.

Observable signals:
- Sync meta row (`_sync_meta:github`) carries `sync_result` and `sync_note` for last-attempt observability.
- `get_sync_meta(store, provider)` returns the raw metadata dict for CLI or diagnostic use.

## Optional Future Projections

The following are described as **optional projections only** and are not part of the dispatcher hot path.
The dispatcher SQLite store is the Builder System control plane for active queue, lease, heartbeat,
and lifecycle status. Projection surfaces render or repair that state; they do not replace it.

| Target | Type | Status |
| --- | --- | --- |
| Signboard Markdown board | Local generated projection | Implemented via `python -m app.dispatcher export-signboard <path>` |
| GitHub Projects board | Deprecated optional projection | Not in dispatcher hot path (see Source-of-Truth Boundaries) |
| Plane / Vikunja / Baserow | Optional external board | Not implemented — future scope only |
| Local Markdown/JSON dashboard | Optional local projection | Signboard export is the current Markdown projection |
| CLI sync-status command | Optional surface | Expressible via `get_sync_meta` in a future `disp sync-status` command |

External boards and GitHub Projects are projections only and must not become required for core queue/lease/claim behavior.
Agents must use dispatcher commands for work selection and mutation. Signboard files are generated
for human kanban inspection and should not be treated as authoritative input unless a future
two-way projection command explicitly validates and imports them.

## Operational Deployment

The dispatcher runs as a **central shared instance** on Demerzel (Mac mini) accessible to all agent machines via Tailscale.

**Central host:** `demerzel`
**Database path:** `~/workspace/runtime/dispatcher/dispatcher.sqlite3`
**Event log:** `~/workspace/runtime/dispatcher/events.jsonl`

### Setup on the central host (Demerzel)

```bash
cd ~/workspace
make dispatcher-init          # runs: python -m app.dispatcher init + pull
python -m app.dispatcher status --json   # verify db_exists: true
```

`make dispatcher-init` is the canonical first-time bootstrap: it initialises the schema and pulls open `agent:ready` issues from GitHub in one step. To re-sync issues without reinitialising:

```bash
make dispatcher-sync          # runs: python -m app.dispatcher pull --repo RasmusTho/agentic-pkm-mvp --repo RasmusTho/bifrost
```

### Setup on each agent machine

Dispatcher commands are worktree-portable by default. When `DISPATCHER_STATE_DIR`,
`DISPATCHER_DB_PATH`, and `DISPATCHER_EVENTS_PATH` are unset, the dispatcher resolves Git's primary
worktree from `git worktree list --porcelain` and uses that root's `runtime/dispatcher` directory as
the shared local state root. A command run from `/path/repo-3272` therefore reads and prepares
`/path/repo/runtime/dispatcher` instead of creating an isolated queue in the issue worktree.

Agents may still override paths explicitly with the `DISPATCHER_*` environment variables. Explicit
paths always win and are the right mechanism for a remote Demerzel-mounted state directory or a
test-only isolated state root.

From any linked issue worktree:

```bash
python -m app.dispatcher status --json
# db_exists true  -> coordination_mode=dispatcher-backed
# db_exists false -> coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing
python -m app.dispatcher start --agent <agent_id> --json   # prepare shared local state when authorised
```

`start` only prepares the local dispatcher schema and singleton coordination record. It does not
claim issues, remove labels, move Project status, open PRs, merge PRs, or close issues. GitHub
Issues, PRs, and CI remain lifecycle authority; dispatcher state remains operational queue/lease
evidence. If dispatcher state is missing or unavailable and the task does not explicitly authorise
preparation, use the GitHub-label-only fallback and preserve the pickup receipt fields
`coordination_mode` and `fallback_reason`.

### Dev/prod startup bootstrap

`make dev-start-full` runs `scripts/start_full_system.sh` with `PKM_ENVIRONMENT=dev`.
`make prod-start-full` runs the Midgård preflight wrapper and then `scripts/start_full_system.sh`
with `PKM_ENVIRONMENT=prod`. During both full-stack startup paths, `scripts/start_full_system.sh`
invokes `scripts/start_builderops_services.sh` before Compose services are started.

The bootstrap is idempotent and operational-only:
- it verifies dispatcher status and initializes the local dispatcher database when missing;
- it verifies BuilderOps Vault readiness through `scripts/builderops_cli.sh`, the supported
  standalone wrapper around the BuilderOps CLI;
- it attempts dispatcher GitHub pull-sync only when `gh` is installed, authenticated, and the core
  REST rate limit is above the startup safety threshold;
- if GitHub access is unavailable, unauthenticated, rate-limited, or sync fails, startup continues
  and records a degraded BuilderOps bootstrap reason instead of failing the runtime stack.

The structured receipt is written to `tmp/builderops_startup_status.json` and merged under
`builderops_bootstrap` in `tmp/startup_status.json`. The receipt is operational coordination state:
GitHub Issues/PRs/CI remain durable delivery truth, dispatcher state remains a local lease/queue
surface, and GitHub Project remains an optional projection.

GitHub Project v2 / GraphQL reconciliation stays out of dispatcher `next`, `claim`, `heartbeat`,
and `complete`. Low-frequency/batched projection repair is exposed separately through
`scripts/reconcile_builderops_project_status.sh`, which delegates to the existing project
reconciliation helper.

### Signboard projection

The dispatcher can export the active Builder Ops queue into a Signboard-compatible Markdown board.
`export-signboard` takes an optional directory argument. When omitted, it resolves a default path
from the existing active-vault-selection mechanism (`app.vault.manager.get_vault_manager`, the
same Option 2 selection state the companion UI uses) — no manually typed path is required:

```bash
python -m app.dispatcher export-signboard --json
# writes into <active vault>/BuilderOpsVault/agent-delivery

python -m app.dispatcher export-signboard ~/BuilderOpsVault/agent-delivery --json
# explicit path still supported when no vault is selected or a different
# location is wanted
```

If no vault is currently selected and no explicit path is given, the command fails loud with a
clear error instead of guessing a location.

The exporter writes one Markdown file per dispatcher task under status columns:

```text
Backlog/
Ready/
In Progress/
Review/
Blocked/
Done/
```

Canonical dispatcher statuses are mapped as follows:

| Dispatcher status | Signboard column |
| --- | --- |
| `backlog` | `Backlog` |
| `ready` | `Ready` |
| `claimed`, `in_progress` | `In Progress` |
| `review` | `Review` |
| `blocked` | `Blocked` |
| `completed`, `done` | `Done` |

Manual lifecycle changes should use dispatcher commands, for example:

```bash
python -m app.dispatcher move github-issue-123 --status review --agent codex --json
python -m app.dispatcher block github-issue-123 --reason "waiting for owner decision" --agent claude --json
python -m app.dispatcher export-signboard --json
```

The generated Markdown frontmatter is projection state only. Do not patch generated Signboard cards
as the source of a claim, heartbeat, or lifecycle transition.

Run `python -m app.dispatcher signboard-validate [path] --json` to lint the generated board without
changing either the board or dispatcher store. As with `export-signboard`, the path is optional and
defaults to the active vault's `BuilderOpsVault/agent-delivery` root. Validation exits nonzero for
malformed generated cards, duplicate generated cards, column/status drift, cards stale against the
dispatcher store, and unreadable generated-filename candidates; run `export-signboard` to repair
valid generated-card drift. Human-authored files are outside this lint's jurisdiction.

Each generated card carries a `## Notes` section the human may hand-edit directly in the vault.
Re-running `export-signboard` refreshes the generated frontmatter and body but splices any existing
`## Notes` content back in unchanged — it never blind-overwrites human-authored notes. The exporter
still only touches cards it generated (keyed by `generated_by: dispatcher.signboard`); unrelated
files are left alone. The Signboard projection has no write path for claim, lease, or lock state —
it remains a durable Markdown projection only, per the Source-of-Truth Boundaries above and
ADR-0010.

### Local visual Signboard

The FastAPI runtime also exposes a local visual board at `/signboard`. Its API reads only the
generated Markdown files beneath `SIGNBOARD_ROOT` (default:
`~/BuilderOpsVault/agent-delivery`) and renders the six exporter columns. A refresh explicitly
runs the normal exporter. Card moves are loopback/API-key protected and invoke dispatcher service
operations (`move`, `block`, or `complete`) before immediately re-exporting the projection; the UI
never writes card files or the SQLite database itself. `SIGNBOARD_ROOT` is operator configuration,
not request input, and card reads are containment-checked after symlink resolution.

`make dev-start-full` and the prod full-stack launcher refresh the board as part of their existing
BuilderOps dispatcher bootstrap. The launcher resolves `SIGNBOARD_ROOT` to an absolute host path
and forwards it into the API container, which has `/Users` mounted at the same path. On a Mac mini
develop stack, use the existing API port over Tailscale:
`http://<mac-mini-tailnet-name>:18001/signboard`. Remote refreshes and moves require the configured
`API_KEY`, entered into the Signboard session field and sent only as `X-API-Key`; it is not stored
in URLs or browser persistence. No separate Signboard process is started.

### Epic-runner lifecycle planning

`deliver-issue-set` coordinators may use the local dry-run lifecycle planner to preview common
claim, review-handoff, and terminal projection transitions:

```bash
python3 -m app.builderops builderops epic-run-state lifecycle-plan \
  --transition <claim|review|done> --issue-file <file> [--pr-file <file>] --json
```

The planner emits required reads, proposed explicit label/Project/PR writes, and verification reads.
It performs no GitHub writes, Project writes, dispatcher lease writes, run-state writes, or agent
spawns. GitHub Issues/PRs/CI remain the hard lifecycle authority; Project status remains a projection;
dispatcher and epic run-state remain operational coordination evidence only. Live mutations still
belong to the owning workflow skill (`issue-to-code`, `verification-and-closure`, or issue
maintenance) and must use explicit commands with verification.

When a PR is locally validated but GitHub Actions are still pending, coordinators may separate the
implementation handoff from terminal closure with a CI-monitor handoff record:

```bash
python3 -m app.builderops builderops epic-run-state ci-handoff record \
  --epic-issue-number <epic> --run-id <run> \
  --pr-file <pr.json> --checks-file <checks.json> \
  --validation-command "<command already run>" \
  --review-state <state> \
  --next-closure-action "<explicit next action>" --json

python3 -m app.builderops builderops epic-run-state ci-handoff resume-plan \
  --run-id <run> --pr-number <pr> \
  --pr-file <live-pr.json> --checks-file <live-checks.json> --json
```

The handoff captures PR number, head SHA, local validation commands, review state, pending check
summary, and the next closure action. `resume-plan` fails closed if the live PR head SHA differs
from the handoff SHA, blocks while CI is pending or red, and emits a closure-plan candidate only
after terminal green CI. It performs no merge, Project write, issue closure, dispatcher write, or
GitHub check mutation; closure still belongs to the explicit verification workflow after re-reading
live PR head/check/review truth.

Parent epic issues may also carry a compact delivery ledger rendered from verified child receipts,
local run-state projections, or read-only GitHub snapshots:

```bash
python3 -m app.builderops builderops epic-run-state ledger render \
  --epic-issue-number <epic> \
  --children-file <children.json> \
  --live-truth-file <optional-live-truth.json> --json
```

The ledger is coordination evidence for startup legibility only. It records child issue, PR,
head/merge SHA, CI state, blocker, and next action in a compact parent-safe block. When optional
live-truth input disagrees with a ledger entry, the helper emits `live_truth_conflict` warnings
instead of overwriting silently. Agents must resolve those warnings by re-reading live GitHub
Issues/PRs/CI; the ledger must never auto-close children, mark CI acceptable, or outrank receipt
comments and live GitHub state.

Before starting an epic delivery batch, coordinators may run the child readiness repair batch helper
against an explicit issue-state fixture:

```bash
python3 -m app.builderops builderops ready-repair-batch plan \
  --children-file <children.json> --json
```

The helper runs the strict readiness validator for each child, reports blocked children, and proposes
the exact `agent:ready` / Project `Ready` repairs for `ready_candidate` issues. Default mode is
dry-run/observe-only. Explicit `--apply` may execute only those validator-gated repairs and emits
verification reads for the changed issues; it does not claim work, start agents, merge PRs, or make
GitHub Project status authoritative over the Issue contract.

### SSH proxy setup for remote agents

Install a wrapper script that proxies dispatcher commands over SSH:

```bash
cat > ~/.local/bin/dispatcher << 'EOF'
#!/bin/zsh
ssh <user>@<server> "cd ~/workspace && PYTHONPATH=. .venv/bin/python -m app.dispatcher \"\$@\"" "$@"
EOF
chmod +x ~/.local/bin/dispatcher
```

Verify:

```bash
dispatcher queue --json
```

### Notes

- Requires Tailscale connectivity to `demerzel` and SSH key access.
- SQLite is the lock authority on Demerzel; all agents coordinate through the same database.
- No daemon or server process runs — each CLI invocation is a stateless SSH call against the central database.
- Service mode (HTTP API) is a future extension; the SSH wrapper is the current deployment model.

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
