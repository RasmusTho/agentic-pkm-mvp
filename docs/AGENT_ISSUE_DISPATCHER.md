State: Active and operational. MVP implementation complete and shipping in agent workflows (issue-to-code skill via dispatcher claim/heartbeat/complete).
Doc role: Reference contract (development governance)
Authority: Authoritative contract for local Agent Issue Dispatcher MVP boundaries and behavior expectations.
Owner: Delivery governance / multi-agent coordination
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed (GitHub issue contracts + repo governance docs)
Last reviewed: 2026-08-12
Last verified against: #3603 BCP-05 migration branch, #3814, `app/dispatcher/verification_api.py`, `app/dispatcher/verification_merge.py`, `app/dispatcher/verification_consumer.py`, `app/builderops/control_plane/{client,service,store}.py`, `AGENTS.md`, and `.codex/skills/verification-and-closure/SKILL.md`

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

**Verification dispatch consumer: API MIGRATION SHIPPED IN REPO (installed-main pilot pending)**

- `python -m app.dispatcher.cli verification-cycle` is the installed-main composition root for one
  dry-run-safe API-backed run or durable recovery. It wires the existing BuilderOps client/outbox,
  verification ledger, GitHub truth, ChatGPT/keyring auth preflight, Codex launcher, protected-repo
  authority, exact host credential resolver, merge executor, and `HostFencedVerificationCycle`.
  It never constructs dispatcher SQLite. Installed `main` executes the composition, while the
  reviewer receives a digest-bound immutable patch for the exact PR head; neither fact makes the
  still-pending Demerzel receipt true.

- The artifact-only producer, ledger, and host-local consumer authenticate the same `CI Smoke`
  pull-request source workflow at `.github/workflows/ci-smoke.yaml`; a retired `CI` identity or
  mismatched path is rejected before verification work can start.

- `app.dispatcher.verification_api.BuilderOpsVerificationLedger` is the production durable port:
  runs are BuilderOps tasks, review/repair/verification events are BuilderOps attempts, and every
  model or merge effect first commits a task/receipt/outbox intent through the authenticated API.
  Claims, heartbeats, retry state, terminal receipts, and restart recovery use the same PostgreSQL
  authority epoch and fencing tokens. The adapter has no SQLite/PostgreSQL/filesystem store access
  and fails closed when either API or privileged outbox execution is unavailable.
- `app.dispatcher.verification_dispatch.VerificationDispatchLedger` and dispatcher schema v6 remain
  as the delivered #3620 compatibility/import and test baseline until BCP-06 retires legacy
  producers. They are not selected by `verification-ingest` or `verification-status`; the detailed
  SQLite lifecycle paragraphs below document that preserved legacy behavior and migration evidence,
  not the new production authority port. Its compatibility marker remains `SCHEMA_VERSION = 6`.
- `app.dispatcher.verification_merge.VerificationMergeExecutor` re-resolves the protected base,
  repository delivery-manifest blob/hash, exact PR head, required gates, and host credential
  generation after the durable intent and before a GitHub-enforced conditional/merge-queue effect.
  In the API-backed lane the closer has uncredentialed GitHub/git mutation configuration and may
  emit only a distinct `verified` receipt; the exact run/repo/PR/head, issue sets, review anchor,
  final-round count, and repair-budget projection are committed as `builderops_merge_ready.v1`.
  The host executor is the only merge authority. It keeps raw credentials host-local, binds its
  operation in task metadata, and records exact-head GitHub readback or crash recovery through
  outbox reconciliation before success or retry.
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
  delivered receipt without a review event or a repair/blocking-review event without its stable
  finding, closed failure-domain, and mechanism identity.
- Artifact ingestion independently authenticates both producer runs before download, dispatcher
  persistence, or any target-PR read. The artifact uploader run must be the completed/successful
  `Verification Dispatch Request` workflow at its canonical path, with matching listing run id,
  attempt, event, head, repository, and head-repository identities. The separately cited source CI
  workflow is fetched inside that authenticated repository and must match the claimed run id, name,
  attempt, PR head, pull-request event, completed/success state, and repository identities. Branch
  refs are collaborator-controlled display text, not dispatch identity; the producer, ledger request,
  and coordinator context omit them. Authenticated
  compressed-size metadata is checked before
  download; the production stream, ZIP member count, aggregate declared size, and request member are
  independently bounded before an in-memory request is accepted. A mismatch or oversized artifact
  fails closed before claim or model launch. Invalid, legacy, or malformed candidates are isolated
  within the bounded artifact listing so one retained artifact cannot suppress a later valid request;
  an invalid-only poll remains a fail-loud rejection, while GitHub API and artifact-download
  transport failures still propagate and stop the poll.
- The authenticated request is projected onto the exact recursive v1 field allowlist before its
  idempotency identity is used or any JSON reaches SQLite; unknown top-level or nested fields are
  rejected rather than copied. The auth preflight and coordinator subprocess inherit only the
  minimal non-secret host environment needed to locate Codex and its ChatGPT/keyring login. Producer
  authentication alone is historical evidence and never authorizes a head takeover. Before ingestion,
  the consumer pairs an authenticated artifact with a bounded fresh PR observation containing only
  repository, PR number, head, lifecycle flags, and the resolved governing/supporting issue identities;
  the raw PR body is not carried into the ledger. Before that network read, the consumer captures a
  bounded SHA-256 token over the complete canonical chain rows and their attempt/exception authority.
  A different-head takeover recomputes and compares that token only after `BEGIN IMMEDIATE`; any
  intervening head, status, lease, session, terminal, attempt, exception, or cumulative-authority
  transition rejects the delayed observation without mutation. GitHub network I/O is never held
  inside the SQLite write transaction. If the observation and canonical token both prove the incoming
  repaired head is the exact open, unmerged, non-draft live PR head while the prior head's coordinator
  row still has an expired running lease, ingestion atomically requeues that same run on the new head, clears
  stale lease/session/terminal state, and retains every existing attempt and its repair-budget
  policy. An unauthenticated artifact, a missing or mismatched live
  observation, a live lease, mismatched governing authority, removal/replacement of prior supporting
  issues in either the incoming request or live PR, or an ambiguous terminal chain fails closed without
  changing the run. Freshly observed repaired heads may extend the supporting-issue set monotonically
  as new findings become linked to the same PR. Each accepted extension is committed atomically with
  the new current head in a separate cumulative authority field; the original request remains
  immutable audit evidence, and every later active or stale-superseded takeover must contain the full
  durable cumulative set and independently re-prove it against fresh live PR truth. Initial intake
  mismatches keep their existing explicit supersession behavior. After a valid takeover becomes
  terminal, restart and replay of the authenticated exact current-head identity returns the same
  terminal canonical run without changing the immutable original request/idempotency audit or creating
  another chain; governing or cumulative-authority drift still fails closed. The live observation
  becomes mutation authority only for a different-head takeover. An authenticated current-head
  replay through a new idempotency identity, whether the chain is active or terminal, returns the
  durable run only when the fresh observation and artifact exactly match its governing, cumulative
  supporting, and closing authority; drift fails closed without ledger mutation.
- Missing or pending checks and auth/rate limits enter time-bounded `backoff`; replay cannot launch
  before `retry_after`. Rate-limit classification requires either a structured `retry` receipt or the
  launcher's structured `failure_class=rate_limit`, derived once from a non-zero provider failure;
  only parsed provider fields such as status 429 or canonical failure codes, inspected independently
  across bounded stderr and structured terminal events, or a full match of the versioned top-level
  Codex CLI `error` event grammar for plan guidance plus its bounded retry suffix, can create that
  signal. The grammar is exact ASCII with canonical case and spacing; Unicode compatibility folding
  and whitespace normalization are forbidden. Retry timestamps must parse as a real non-past local
  12-hour time or calendar date within the bounded future window and carry the correct ordinal suffix;
  regex shape alone is insufficient. Prefix-only matches are forbidden. The Codex event envelope
  is classified while streaming so a later `turn.failed` event cannot erase the earlier signal,
  while free-form, arbitrary, negated, or explicitly false terminal/stderr prose cannot select
  rate-limit backoff. Terminal completion
  additionally enforces the authenticated v3 `final_review_rounds` value from the live PR's unique
  `Final-Review-Rounds: 1|2` declaration. This verification-dispatch path is full-path only:
  light-path PRs declare `Final-Review-Rounds: 0` and bypass it. New full-path deliveries use one;
  two remains valid only for backward compatibility with already-authenticated deliveries. Intake,
  post-launch delivery validation, artifact replay, explicit restart, and neutralized or merged
  crash recovery all re-check that live authority before proceeding. The ledger does not raise the
  required clean-round count from risk or low-convergence evidence. Pre-v3 executable requests
  retain their conservative two-round behavior. Repair history remains bound per stable failure
  mechanism and failure domain. The closed domains are
  `review_code_correctness`, `static_quality`, `lease_concurrency`, and
  `deployment_model_schema`. Multiple findings may share a mechanism, while an existing finding
  cannot rebind to another domain or mechanism. There is no fixed repair-attempt cap or mandatory
  standard-attempt prerequisite: TCD may select the configured strongest capability with high or
  xhigh reasoning at any round. Every additional substantive repair still requires a fresh
  independent blocking review of the preceding repair. Capability escalation and evidence-based
  convergence are key-local; monotonic attempt history, policy version, and bindings persist across
  restart, head rebind, and takeover. A round may continue only with measurable progress, while
  documented non-progress, technical impasse, scope expansion, or authority conflict routes through
  the existing escalation classifier. Attempt count alone does not create a Human Exception.
- Completion never relies on coordinator receipt ids or review-event prose alone. The fresh exact-head
  GitHub read must contain a named, completed, successful `Unit tests (not pg)` check produced by
  the authoritative `github-actions` App and authenticated as a pull-request run of
  `.github/workflows/ci-smoke.yaml` on that exact head. Its workflow run must correlate to the check run's
  exact suite before latest-rerun selection; same-name checks from another App, workflow, suite,
  event, or head are ignored. The required workflow job runs repo-wide `mypy app` before it can
  publish success. Missing, ambiguous, unnamed, skipped, neutral, pending, or failed required-check
  evidence cannot open closure.
- The schema-valid coordinator receipt carries ordered repair/review events into the same
  lease-fenced ledger as one atomic, deterministically identified batch. Exact receipt replay is a
  no-op, and a later invalid/conflicting event rolls back the whole batch. A semantic event-batch
  rejection becomes an exact-lease technical terminal receipt before any pending-check backoff, so
  invalid review or repair events cannot strand coordinator authority or persist a partial ledger;
  a normal v3 delivery requires one distinct clean review session after its latest verification or
  repair anchor. An authenticated backward-compatible two-round declaration requires two fresh
  sessions, but ledger-visible low-convergence evidence does not raise a one-round declaration.
  The minimal coordinator context and CLI status expose only policy version plus a bounded,
  most-recent-first list of sanitized mechanism/domain keys and standard/escalated attempt counts.
  The compatibility-named `*_remaining` fields preserve the existing projection shape but are not
  repair-admission or stop authority. Total and omitted counts make any truncation explicit; finding
  identities are excluded. Schema validity does not make model-produced text durable-safe: raw coordinator prose
  remains transient and never enters
  attempts, pending replay receipts, terminal rows, Human Exception packets, or status output. Its
  only durable text projection is the canonical `[REDACTED]` marker followed by unique, bounded,
  allowlisted GitHub repository, issue, pull-request, or Actions-run evidence routes that are
  derived from the authenticated verification request; matching the owner/repository alone is not
  sufficient. Queries, fragments, percent-encoded paths, foreign repository identities, invented
  same-repository object ids, unsupported routes, secret-shaped path components, URL userinfo,
  explicit ports, and non-GitHub origins are never preserved. This
  allowlist, rather than credential-pattern coverage, establishes the no-secret invariant for
  free-form coordinator text. Human Exception options cross the same boundary only as the canonical
  `hold`, `authorize`, and optional `select-alternative` actions with fixed safe labels and
  consequences; no-action and recommendation relationships are retained. Retry hints are finite,
  positive, canonical, and duration-capped at one hour before persistence. The projection retains
  the structured identities and actionable option relationships required for deterministic replay
  and governed owner decisions, then passes the canonical schema and semantic validation again.
  Check eligibility selects the latest GitHub rerun per check name. Schema-v6 health, backup, and
  restore validation covers verification runs, attempts, exceptions, head-audit fields,
  `repair_budget_policy`, exact closing authority, legacy-recovery audit, and all write-critical
  keys. The additive sequence is explicit: v3 to v4 preserves the historical global policy marker as `v1`,
  v4 to v5 backfills exact closing authority only for canonical v2 requests, and v5 to v6 adds the
  recovery-audit column. A deployed pre-head-rebinding v3 backup may omit only its documented
  additive columns; missing older audit tables, columns, unique keys, or malformed rows fail closed
  before any schema marker commits.
  All v1 requests have unknown exact closure authority, including otherwise canonical v1 requests
  that carry `supporting_issues`. Migration therefore makes every recognized v1 row inert as
  `legacy_untrusted`, empties its executable supporting and closing projections, clears lease,
  session, context, retry, and active projections, and retains the immutable request, attempts,
  terminal evidence, and exception audit. Migration preserves a previously rebound
  `current_head_sha` separately from the immutable requested head only when it is a valid 40-character
  hexadecimal SHA and the retained terminal chain names that exact current head; malformed or
  inconsistent current-head state rolls the whole migration back. The two exact pre-trust shapes that predate
  `supporting_issues` remain permanently inert because compatible legacy supporting authority cannot
  be proved; any unrecognized historical shape rolls the whole migration back.
  A same-current-head v1-to-v2 promotion is allowed only for one unambiguous inert chain, a freshly
  authenticated canonical v2 artifact, and a bounded live observation proving the exact open,
  unmerged, non-draft repository, PR, stage, head, governing issue, and closing set. The legacy
  request's exact supporting list must equal the incoming durable supporting authority and remain
  present in live truth; the non-empty v2 closing set must be a subset of that governing/supporting
  authority and equal live closing truth. After a canonical-chain token is rechecked under
  `BEGIN IMMEDIATE`, promotion atomically archives the complete quarantined row and its exception
  children in `verification_legacy_recovery_audit.v2`, installs the authenticated v2 request and
  exact authorities, deletes only the now-archived live exception children, and clears stale
  head-bound execution state. The run id, attempts, repair-policy version, and repair history
  remain unchanged. The archived legacy current head stays bound to that recovered v2 request
  identity; the live row may later rebind to another freshly observed repair head without making
  the immutable archive unreadable or resetting the chain. An authenticated artifact for the
  immutable requested head or any unrelated head cannot create a parallel canonical run around a
  recoverable inert repaired-head chain. After promotion, an identical authenticated artifact
  replays against the stored recovered-request head rather than the immutable legacy requested
  head only while its exact durable supporting and closing authority still match. Once the active
  chain rebinds again, the older recovered-head artifact fails closed in both active and terminal
  states.
  Existing v1 recovery-audit receipts remain readable; ambiguity, drift, missing authentication,
  incompatible supporting authority, or any token mismatch is non-mutating and fail-closed.
  If normal stale-head handling supersedes a chain before the repaired-head artifact arrives, only
  a later artifact with the same repository, PR, stage, and governing issue may reopen that exact
  chain on the new head. Reopening preserves immutable requested-head audit plus all attempts and
  repair accounting, while clearing stale lease, session, context, retry, and terminal state. No other
  terminal status or supersession reason is reopenable, and a different-head artifact cannot route
  around that terminal chain by creating an empty run. Exact same-artifact replay is resolved
  globally before any canonical-chain decision. A stale-head reopen is allowed only when that row
  is the unambiguous terminal set; another terminal row fails closed without mutation. Further work
  requires a governed lifecycle decision rather than a budget reset. Any legacy database containing
  both an active chain and a terminal chain for the same authority is rejected before exact or active
  replay, so a newer empty run cannot hide older attempt history. More than one active canonical chain
  for the same repository, pull request, and stage is likewise rejected before exact replay; the
  dispatcher never selects a newer empty active row over an older row with attempt history.
  An expired unclaimed technical backoff follows the same authenticated live-head takeover rule:
  the first authoritative artifact for the newer live head requeues the existing canonical run,
  preserves its immutable requested head, attempts, exceptions, and cumulative repair accounting, and
  clears only head-bound coordinator, context, receipt, retry, and verified-head state. An
  unexpired backoff or any authority/token mismatch remains non-mutating and fail-closed. Retained
  merged or open-neutralized recovery artifacts polled before that exact `retry_after` return the
  current durable run without extending the retry or rewriting its receipt.
- The Codex process boundary drains bounded stderr concurrently and rejects non-zero exits or
  terminal error events even when stdout contained an otherwise valid receipt. A bounded rate-limit,
  usage-limit, quota, or credit-exhaustion signal on that non-zero path remains a lease-fenced backoff
  receipt with no repair-budget use or API-key fallback; either diagnostic channel can supply the
  structured provider signal without masking the other, while canonical Codex usage-limit messages
  are trusted only in a top-level CLI `error` event. This includes the exact model-specific CLI form
  (`usage limit for <identifier>` followed by `Switch to another model now`) only when the identifier
  is a bounded 1-64 character ASCII model token and is not `codex`; the same canonical, semantically
  future retry suffix remains required. Promo-message text, unbounded or Unicode identifiers, stderr,
  nested model/tool output, quoted examples, and arbitrary prose cannot select backoff. Raw stderr,
  terminal event content, exception
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
  exact live PR head; terminal delivery records the verified head after the required clean review
  rounds on it: one for a normal v3 request, two for an authenticated two-round declaration or
  ledger-visible low convergence on the final key.
  A later artifact for that repaired head reuses the same active repository/PR/governing-issue run
  instead of opening an empty verification chain, so redispatch cannot reset prior attempts or the
  run's policy-specific repair accounting and independent fresh-review accounting. A mismatched head or governing
  authority fails closed instead of sharing the ledger.
  When the repaired head's checks are still pending, its repair event is persisted before bounded
  backoff so replay cannot bypass its keyed or legacy-global ledger; review events are rejected until
  checks are green.
  An exact same-session terminal receipt replay reuses its deterministic verification attempt, so
  already-deduplicated review events retain the same closure anchor. A changed receipt or session
  creates a new anchor and must earn fresh reviews.

**Verified issue-set merge and exact closure: SHIPPED IN REPO**

- Verification dispatch request v3 binds one non-empty, sorted set of at most 10 closing issues and
  one authenticated `final_review_rounds` value to
  the exact repository, PR, and head. `supporting_authority_json` is durable, cumulative evidence
  authority across restart and takeover, but supporting issues grant no closure authority unless
  they are also named in the exact `closing_authority_json` set. A trusted collaborator-authored
  `verified_issue_set_merge_authority.v1` receipt binds the run, governing issue, exact closing and
  supporting sets, original and neutralized body digests, and current repair-budget projection.
- Verified-merge authority and phase body digests use one deterministic GitHub PR-body canonical
  form: remove at most one terminal LF before deriving or comparing the SHA-256 digest. This treats
  that terminal LF as equivalent to its absence; every other body byte and whitespace character
  remains exact, and any substantive body drift fails closed. A pre-#4010 authority receipt that
  stored the raw digest of the same body with exactly one terminal LF may also authenticate when
  GitHub returns the LF-less form, but only when the trusted receipt comment's GitHub-authenticated
  `created_at` and `updated_at` both precede #4010's merge at `2026-07-21T16:32:11Z`. Canonical
  #4010 digest equality is checked first, preserving unchanged bodies ending in two LFs; the legacy
  fallback then permits only the absent final LF and rejects CR/CRLF, spaces, or interior drift.
  The exception preserves the receipt identity, exact head, issue sets, phase chain, and repair accounting.
- Mutable PR text is never merge-time closure authority. Immediately before merge, the verified
  flow re-reads the exact head, title, body, and GitHub `closingIssuesReferences`, replaces every
  authenticated closing keyword with evidence-only `Refs` plus a bounded
  `Verified-Closing-Issues` marker, and requires the freshly triggered `pr-contract` result to prove
  the trusted receipt, neutralized body, and empty closing references. Merge uses only the fixed
  non-closing title/message from the plan. The fetched merge commit must match the exact repository
  and SHA, remain within its response/message caps, and contain no canonical or malformed closing
  attempt; a merge commit message can never become closer authority.
- A neutralized body's lifetime is bounded by the merge attempt that justified it. Neutralization
  requires a head-bound `verified_issue_set_merge_readiness.v1` statement asserting that CI and the
  review gate are green and that no further commits are anticipated on that exact head; the statement
  is not reusable across heads, and `prepare_verified_merge` refuses to neutralize without it. When a
  further commit changes the head while the body is still neutralized, the exact-head authority
  receipt correctly stops resolving and `pr-contract` fails on that head, so the canonical body must
  be restored before further repair work. `resolve_neutralized_body_restoration` detects that state
  from the live PR plus its trusted receipts and names the durable receipt's original-body digest as
  the only accepted restore target; it is read-only detection that grants no merge authority, does
  not weaken the exact-head binding, never rewrites the durable receipt trail, and fails closed on
  merged, foreign, untrusted, or conflicting evidence.
- The authority-bound phase ledger is continuous and idempotent:
  `prepared -> merged -> reconciled -> restored`. Duplicate identical phase receipts are harmless;
  missing, stale, forged, skipped, or conflicting phases fail closed. If a crash leaves the exact
  PR open with a neutralized body and a valid `prepared` receipt, recovery ignores any synthetic or
  malformed open-PR `merge_commit_sha` and passes `merge_commit_sha=null`, `merged_at=null`. If the
  PR is merged but incomplete, recovery re-authenticates the exact merge commit, authority receipt,
  checks, repair-budget policy, and highest continuous phase, then resumes at the first missing
  phase. Neither path resets attempts, durable supporting authority, or repair accounting.
- A narrow current-main/base-side recovery exists only for the pre-#4010 immutable PR #4052 head
  after a live-neutralized PR independently re-reads one unique trusted exact-head authority receipt
  and one continuous `prepared` phase. It uses the current-main `pr-contract` semantics and attaches
  an additional auditable `pr-contract` result only to that exact head after binding repository, PR,
  title, canonical body, empty closing links, governing/closing/supporting sets, authority/phase
  identity, and unchanged repair accounting. It is not a waiver or generic status API: mutable, foreign,
  unprepared, stale/forged/conflicting, drifted, live-closer, and noncanonical contexts fail closed
  without a result. Handoff remains the ordinary verified-merge flow; recovery does not merge, close,
  restore closers, rewrite receipts, or change dispatcher accounting.
- Post-merge reconciliation explicitly closes every and only the authenticated closing set, restores
  the authenticated original body, and proves exact closure attribution before terminal delivery.
  Candidate enumeration reads the bounded repository issue-event feed through REST, proves its
  reverse-time coverage through `merged_at`, and unions those candidates with authenticated and
  phase-known identities under a fixed cap. One bounded GraphQL `ClosedEvent.closer` batch then
  authenticates every Issue node, latest close timestamp, actor, and closer. A `PullRequest` closer
  counts only when PR number, repository, merge SHA, actor, and time identify this delivery; a null
  closer counts only for an expected issue explicitly closed by the exact delivery actor after the
  merge. Foreign-PR and independently closed issues remain unrelated. Only an unauthorized closure
  attributed to this PR may be reopened; any unresolved, extra, missing, or ambiguously attributed
  closure blocks `reconciled`, `restored`, and terminal delivery.
- Closure reads are deliberately bounded and fail closed: at most 500 repository issue events,
  20 unioned candidates, one 1 MB GraphQL response, an 8 MB REST event response, a 64 KiB merge
  commit response, and a 16 KiB commit message. GraphQL node ids cross the CLI as raw `-f` values so
  untrusted ids cannot trigger `gh -F` file expansion. Ordering gaps, page-cap exhaustion, response
  overflow, malformed identities, incomplete nodes, conflicting trusted receipts, API failures, or
  missing actor/time evidence are absence of authority, never permission to merge or close.
- The post-merge owner-doc watchdog prefers the trusted exact-head merge authority receipt; a
  trusted-but-invalid receipt fails closed instead of falling back to mutable linked-issue state.
  Its required targets are every authenticated closed issue plus a distinct open governing parent,
  or the PR for an issue-free lane. Only a trusted collaborator's exact
  `post-merge owner-doc check: PR #<PR>;` line is a closure receipt. A watchdog nudge, a generic
  receipt, or a receipt for another PR is not one, and verification cannot emit its delivery receipt
  until every required owner-doc receipt is read back.

- `verification-ingest` and `verification-status` are host-neutral command names backed exclusively
  by the authenticated BuilderOps API. They require explicit RepoRef plus host-owned API
  configuration and create no dispatcher SQLite authority when the service is unavailable. The
  Demerzel enable/disable/poll wrapper, scoped credentials, and service configuration remain
  host-local outside Git.
- GitHub Actions remains artifact-only. The consumer grants no mutation or merge authority beyond
  `.codex/skills/verification-and-closure/SKILL.md`.

## Source-of-Truth Boundaries

| Surface | Role in MVP | Authority |
| --- | --- | --- |
| GitHub Issues / PRs / CI | Durable delivery lifecycle and merge truth | Hard authority |
| BuilderOps API / PostgreSQL / outbox | Verification runs, attempts, fenced external-effect intents, and readback receipts | BuilderOps execution authority |
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
- `sync_result` (`ok`, `partial`, `stale`, `conflict`, `error`)
- `sync_note` (string)
- `labels` (list of GitHub label names, recorded on every pull since #4441)
- `url` (the issue's browser `html_url`, or null; Signboard cards and the
  `/api/signboard` board read these two keys for chips and links)

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
  repo so pulling one repo cannot reconcile another repo's tasks. The id has exactly one
  implementation — `app/dispatcher/sync_github.py::github_issue_task_id` — and every consumer,
  including the pickup wrapper's default `TASK_ID`, derives through it rather than respelling the
  format (INV-DG-2, #4440). `make dispatcher-init` and
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

## Kill-Switch Partial Sync (#4606)

When the GitHub rate-limit kill switch (`app/dispatcher/github_call_logger.py::is_kill_switch_active`)
suppresses the non-essential open-issues scan, the pull is truncated, not failed:

- The essential `agent:ready` read still runs and its upserts are preserved; no additional GitHub
  API calls are spent.
- `record_sync_partial` writes `sync_result=partial` with `kill_switch_active=true` and a
  machine-readable `sync_note` — never a plain `ok` (the false-green captured by LearningSignal
  `lrn_20260730235456_f70f8ccc`).
- `python -m app.dispatcher pull --json` keeps `ok=true`/exit 0 (not a hard source failure) but
  reports `sync_result=partial` and `kill_switch_active=true` top-level and per repo.
- `python -m app.dispatcher status --json` exposes an additive read-only `last_sync` summary
  (`last_pull_at`, `sync_result`, `sync_note`, `kill_switch_active`) so pickup tooling can
  distinguish a complete sync from a truncated one without spending GitHub API calls.
- Provider-wide partial-sync metadata is not task-specific absence evidence: the essential
  `agent:ready` scan still ran. `scripts/issue_pickup_claim.sh` therefore keeps a missing-task claim
  failure opaque and leaves `agent:ready` untouched instead of advertising a lease-bypassing
  label-only rerun from the partial row alone.

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
- if GitHub access is unavailable, unauthenticated, rate-limited, sync fails, or dispatcher pull
  reports `sync_result=partial`, startup continues and records a degraded BuilderOps bootstrap
  reason instead of failing the runtime stack.

The structured receipt is written to `tmp/builderops_startup_status.json` and merged under
`builderops_bootstrap` in `tmp/startup_status.json`. The receipt is operational coordination state:
GitHub Issues/PRs/CI remain durable delivery truth, dispatcher state remains a local lease/queue
surface, and GitHub Project remains an optional projection.

GitHub Project v2 / GraphQL reconciliation stays out of dispatcher `next`, `claim`, `heartbeat`,
and `complete`. Low-frequency/batched projection repair is exposed separately through
`scripts/reconcile_builderops_project_status.sh`, which delegates to the existing project
reconciliation helper.

### Signboard projection

> **Legacy surface.** `export-signboard` and `signboard-validate` are legacy operator commands. The
> visual board at `/signboard` is served directly from the dispatcher store and reads no Markdown at
> all (#4401), so nothing in the running system consumes this export. It is kept working for the
> builder hosts that still hold a board directory today; both commands announce themselves as
> `[LEGACY]` in `--help`. Physically removing the exporter, the prune, and the lint is a separate
> follow-up, so nothing below is switched off yet — but do not build anything new on it.

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
clear error instead of guessing a location. A genuinely never-selected reference (`status: none`)
and a dangling one — a `lastActiveVaultRef` naming a path that no longer exists on disk
(`status: missing`) — are reported distinctly (#4223): the dangling case names the missing path
instead of claiming no vault was ever selected, matching the existing precedent in
`app/api/routes/companion.py` for the same `VaultContext` status split.

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
dispatcher store, a same-column generated card whose title, priority, claim, linked PR, or labels no
longer match its dispatcher task (`content_drift`), unreadable generated-filename candidates, and a
board stamped by a different dispatcher store; run `export-signboard` to repair valid generated-card
drift. Human-authored files are outside this lint's jurisdiction.

A plain `export-signboard` only rewrites cards for task IDs that still exist in the dispatcher
store, so it cannot clear a card whose task ID has disappeared from the store — those accumulate as
`stale_card` findings the lint reports and nothing removes. `--prune-absent` is the repair for
exactly those cards:

```bash
python -m app.dispatcher signboard-validate [path] --json   # reports stale_card findings
python -m app.dispatcher export-signboard [path] --prune-absent --json
```

A board records which dispatcher store owns it. Every export writes a `.signboard-store.json` stamp
into the board root carrying that store's durable identity — an id minted once and kept in the
store's own metadata, never the store's path, so relocating a store does not make its boards read as
foreign. The stamp is not a card: it sits at the board root outside the column directories and is
not a `.md` file, so neither the exporter, the lint, nor the `/signboard` API ever renders it, and
it never becomes a second source of task truth.

This matters because the store resolves from the **current working directory**
(`app/dispatcher/config.py :: load_paths` → `_default_state_dir` → `discover_primary_worktree`).
Two checkouts of this repo on one host therefore have two independent stores, and to the store that
does not own a board *every* card on it is absent. On 2026-07-29 that deleted 404 live cards.
`--prune-absent` now refuses, non-zero and before it writes or unlinks anything, unless the board's
stamp matches the store the process resolved:

- **Stamp matches** — prunes exactly as described below.
- **Stamp belongs to another store** — refuses. Run the prune from the checkout that owns the board.
  A plain export from the other checkout does *not* re-stamp the board; a board changes owner only
  when a human deletes the stamp file.
- **No stamp, and the board already holds generated cards** — refuses. This is every board that
  predates the stamp. Claim it with a plain `export-signboard <path>` (no `--prune-absent`) run from
  the checkout that owns it, then retry. An unstamped board is never adopted by the same command
  that prunes it, because that would defeat the guard on exactly the boards that need it.
- **No stamp and no generated cards** — proceeds and stamps the board. A first export has nothing to
  lose, so a fresh board still works in one command.

`signboard-validate` reports a mismatch read-only as its own `store_stamp_mismatch` finding, named
before the `stale_card` findings it explains, and in that case its `repair` hint deliberately does
not name `--prune-absent`.

`--prune-absent` deletes a generated card only when its task ID is absent from the store *and* the
card carries nothing a human wrote. Both hand-editable sections count: `## Notes`, and any non-blank
text below the card's final `## Receipts` heading — the exporter always emits that heading empty,
and it never rewrites a stale card, so anything there is human-authored. A stale card carrying
either is kept and listed under `retained_with_notes` in the JSON result, so a human decides its
fate; human material is never destroyed by the prune. Malformed generated cards and non-generated files are never
touched. The prune is opt-in: the exporter run by the startup bootstrap and by the `/signboard`
refresh route never deletes.

Each generated card carries a `## Notes` section the human may hand-edit directly in the vault.
Re-running `export-signboard` refreshes the generated frontmatter and body but splices any existing
`## Notes` content back in unchanged — it never blind-overwrites human-authored notes. The exporter
still only touches cards it generated (keyed by `generated_by: dispatcher.signboard`); unrelated
files are left alone. The Signboard projection has no write path for claim, lease, or lock state —
it remains a durable Markdown projection only, per the Source-of-Truth Boundaries above and
ADR-0010.

### Local visual Signboard

The FastAPI runtime also exposes a local visual board at `/signboard`. **The board is served from the
dispatcher store** (#4401): `/api/signboard/board` builds every card from `store.list_tasks()` on each
request and reads no files. Column identity and order derive from
`app/dispatcher/signboard.py :: STATUS_COLUMNS`, so the board cannot disagree with the dispatcher
about where a status belongs, and the route holds no second copy of that table. Card moves are
loopback/API-key protected and invoke dispatcher service operations (`move`, `block`, or `complete`);
that store write *is* the durable change, so nothing is exported afterwards and the next read already
reflects it. The UI never writes the SQLite database itself.

`/signboard` is an operational and diagnostic dispatcher surface, not a separate long-term owner
product. The accepted `docs/DEVUI.md` target composes its queue, claim, lease, and activity evidence
inside one owner experience without embedding Signboard as a destination or transferring dispatcher
authority to devUI. Direct Signboard access may remain available for repair and low-level operations.

There is no board root on this path. `/api/signboard/board` carries no `root` field, its `authority`
is `dispatcher_store`, and `SIGNBOARD_ROOT` has no effect on it — the route reads the store resolved
by `app/dispatcher/config.py :: load_paths`, exactly like every other dispatcher caller. A projection
directory left on the host is not board input; a stale board on disk can no longer be rendered as
current work.

A store that cannot be read is still a visible error, never a healthy board. A missing dispatcher
database returns HTTP 503 `dispatcher is not initialised`, and a database file that exists but
carries no dispatcher schema returns 503 `dispatcher store is not readable`; the UI shows either as a
notice. A task whose status the column table cannot place is reported in `errors` with
`status: "error"` instead of being dropped. An initialised store with no tasks is the one case that
legitimately renders six empty columns — because that is what the authority actually says. "No work"
and "misconfigured" must not look the same; that invariant now keys on the store rather than on a
resolved root.

The board-root plumbing below now serves the legacy export only. It is unchanged and still correct
for `export-signboard`, but nothing it forwards reaches the visual board any more; retiring it
travels with the exporter's physical removal.

`make dev-start-full` and the prod full-stack launcher refresh the legacy board export as part of
their existing BuilderOps dispatcher bootstrap. `scripts/start_full_system.sh` resolves the board root
to an absolute host path (via `scripts/lib/signboard_root.sh`, which calls the same single source) and
`scripts/export_runtime_env.sh` forwards it into the generated runtime env consumed by the API
container's `env_file` chain; `/Users` is mounted at the same path, so the host path is valid
in-container. With no vault selected the variable stays unset and the bootstrap reports
`signboard_root_missing` instead of writing to an invented location. That degraded reason now means
"no legacy export was written", not "the board is unavailable" — `/signboard` renders from the store
regardless.

The channel deploy wrappers (`scripts/deploy_channel.sh`) do **not** regenerate the runtime env.
For each Compose invocation they resolve the board root through the same
`scripts/lib/signboard_root.sh` source and forward a container-readable path to the API with an
in-memory Compose override. Roots already visible through the same-path `/Users` or `/Volumes`
mounts stay absolute. A root proven contained by the governed legacy vault bind is translated to
the same relative suffix beneath `/app/vault`; containment must hold both lexically and after
symlink resolution. Before forwarding either form, the deploy requires the resolved root to be an
existing directory that the runtime can read and search for column traversal. Nonexistent,
unreadable, unreachable, or escaped roots fail closed. That deploy-only override wins over a
missing or stale `SIGNBOARD_ROOT` in the existing runtime env without rewriting the file or
disturbing its vault bindings. When no active vault resolves, the override removes any stale
runtime-env value so no export is written to a stale location. Since #4401 a stale value cannot make
the board itself lie: the board never reads it. On a Mac mini develop stack, use the existing API
port over Tailscale:
`http://<mac-mini-tailnet-name>:18001/signboard`. Remote refreshes and moves require the configured
`API_KEY`, entered into the Signboard session field and sent only as `X-API-Key`; it is not stored
in URLs or browser persistence. No separate Signboard process is started.

#### The projection root is not the shared BuilderOps vault's `agent-delivery/`

This distinction concerns the legacy export only — the visual board reads neither directory — but the
two trees still exist on the builder hosts, and they are not interchangeable:

| | Signboard projection root | Shared BuilderOps vault queue |
| --- | --- | --- |
| Location | `<active vault>/BuilderOpsVault/agent-delivery` (or the forwarded `SIGNBOARD_ROOT`) | `<BUILDEROPS_VAULT_ROOT>/agent-delivery` |
| Written by | `export-signboard` | `builderops vault` ticket commands |
| Card schema | `generated_by: dispatcher.signboard`, lowercase dispatcher `status`, `column` | BMI-01 ticket frontmatter: `agent_state`, title-case `status`, no `generated_by` |
| Authority | none — rebuildable projection of the dispatcher SQLite store | the vault tickets themselves |

Do not migrate cards from one into the other, and do not point `SIGNBOARD_ROOT` at the shared
vault's queue root. The projection is regenerable and disposable; the vault queue is not. See
`docs/builderops/BUILDEROPS_VAULT_STORE.md` for the shared-vault contract.

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

### Epic-runner context-budget observation

Dispatcher-backed epic run-state accepts a versioned v1 context-budget receipt at each slice
boundary. The observer records an explicit token measurement or `unknown`, a checkpoint/digest
containing slice status, decision delta, open review findings, and external-state marker, plus
truthful cost inputs for accepted slices. Missing token, monetary, repair, handoff, worker-start, or
human-minute evidence remains `unknown`; the receipt never estimates or fabricates it.

The evaluator reports coordinator lifecycle (`keep` or `checkpoint_rotate`) separately from slice
execution (`inline` or `thin_worker`) and retains the evidence needed to reconstruct both. These are
strictly advisory shadow recommendations: the receipt cannot dispatch or spawn agents, mutate CI,
review, acceptance, merge, or closure state, or weaken any quality gate. See
[the Dispatcher And Routing Model](development/BUILDER_SYSTEM_PROCESS_MAP.md#5-dispatcher-and-routing-model)
for the cross-system classification.

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
