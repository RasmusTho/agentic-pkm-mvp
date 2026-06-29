State: Audit report (point-in-time GitHub API / GraphQL exhaustion architecture audit, 2026-06-29; advisory, not normative).
Doc role: Reference (advisory audit snapshot)
Authority: Advisory only; subordinate to docs/DOCS_INDEX.md and owner contracts. Remediation tracked in issues #2680–#2685; bleed-stop delivered in #2686.

# GitHub API Exhaustion — Architecture Audit (2026-06-29)

**Status:** Audit / evidence-based review. No code changed by this document.
**Scope:** The builder-automation GitHub integration (issue dispatcher, Projects-V2
reconcile scripts, governance Actions, and the agent skills that drive GitHub).
This is the *development substrate*, not a product runtime feature.
**Source anchors:** see [Findings](#findings) — each finding carries a stable
`GHAPI-*` anchor so backlog issues can trace to it.

---

## TL;DR

The "GraphQL exhausted" pain is an **implementation/architecture problem, not a
GitHub tool-fit problem.** The shipped mitigations are almost entirely
*behavioral conventions* (REST-first / cache-IDs / batch-mutations in `AGENTS.md`,
born from one 2026-04-19 incident #514) plus a reactive ~6 s retry loop — and
**retry under a shared-pool exhaustion adds load rather than shedding it.**

Three structural drivers, all sharing one quota pool:

1. **`scripts/reconcile_project_status.py` re-paginates the entire Project board on
   every invocation**, and runs **hourly via cron** (`project-status-reconcile.yml`
   → `17 * * * *`) *plus* on every issue/PR event. `--scan` also re-reads every
   board item individually (`gh issue/pr view`). Cost ≈ `24 × (3 + N)` calls/day,
   linear in backlog `N`.
2. **Board automation runs on `PROJECT_TOKEN` (a user PAT)** which very likely
   **shares the single 5,000/hr pool with the interactive Claude/Codex agents**.
3. **The skills tell agents to "wait for CI green" and resolve the Codex verdict
   across 4 REST surfaces with no prescribed cadence or backoff** — every
   autonomous delivery polls live GitHub in a loop.

There is **no webhook → local-read-model → low-frequency-reconcile architecture**
for the builder path, and **zero GitHub-API observability** (no dashboard, alert,
metric, circuit breaker, kill switch, or runbook).

**Decision: stay on GitHub Issues/Projects and finish the API-architecture
remediation.** None of the target-architecture fixes have actually been built, so
the "GitHub can't handle this" threshold has not been reached. See
[Stay vs migrate](#stay-vs-migrate).

### Live evidence captured during this audit (2026-06-29 ~12:26Z)

```
graphql : remaining 0    / 5000  (used 5175 — over ceiling)   <- the only dead pool
core    : remaining 4834 / 5000                               <- REST healthy
search  : remaining 30   / 30                                 <- healthy
```

GraphQL is the *only* exhausted pool — a direct confirmation of "GraphQL exhausts
first." REST issue/PR creation (core pool) was unaffected.

---

## Architecture map — where the API load originates

| Source | Mechanism | Pool | Cadence |
|---|---|---|---|
| `project-status-reconcile.yml --scan` | `gh project` (GraphQL) + per-item `gh issue/pr view` | `PROJECT_TOKEN` (shared user) | **hourly cron** |
| `project-pr-opened` / `-stage-change` | full-board pull to locate one card | `PROJECT_TOKEN` (shared user) | per PR event |
| Interactive agents (skills) | "wait for CI green" + 4-surface Codex-verdict poll; maintenance double-sweep | ambient `gh` (likely shared) | per delivery, loop |
| `issue-pr-governance` / `post-merge-owner-doc-watchdog` | `pulls.get`/`listFiles`/`closingIssuesReferences` | **`GITHUB_TOKEN` (isolated, per-repo)** | per PR event |
| `app/dispatcher/sync_github.py` | `gh issue list` (REST **search**, GraphQL-free) | ambient `gh` | startup-triggered |

The core dispatcher is GraphQL-free by design
(`tests/dispatcher/test_sync_github.py:268`). The GraphQL load is concentrated in
the Projects-V2 path and the maintenance skills.

---

## Findings

Severity-ordered. Each has a stable anchor for issue traceability.

### GHAPI-C1 — Shared 5,000/hr quota across board automation + interactive agents (CRITICAL)
- **Evidence:** `project-status-reconcile.yml:27,43` (`PROJECT_TOKEN || GITHUB_TOKEN`);
  agents use ambient `gh` auth (`AGENTS.md:159`, `docs/AGENT_ISSUE_DISPATCHER.md:213`);
  live signal *"5,000/hr shared across all tools and agents."* Docs neither claim
  nor refute separation.
- **Impact:** The hourly scan, every PR/issue event, *and* every interactive agent
  contend for one pool; one busy delivery session exhausts GraphQL for everything.
- **Fix:** GitHub App installation token for all board/governance automation →
  separate quota pool, isolates interactive agents. **Effort M · Confidence high**
  (verify collapse with `gh auth status` token vs the `PROJECT_TOKEN` secret).

### GHAPI-C2 — Hourly full-board re-pagination reconcile (CRITICAL)
- **Evidence:** `scripts/reconcile_project_status.py:108-131` (`item-list --limit
  200→N` pulls the whole board, re-fetches higher if `totalCount>200`); `--scan`
  then `gh issue/pr view` per item (`:334,338`); cron `17 * * * *`.
- **Impact:** Constant baseline drain independent of change; grows with backlog.
- **Fix:** Drop scan to daily/on-demand; make incremental; locate single cards by
  content-id instead of full-board pull. **Effort S (cadence) / M (incremental) ·
  Confidence high**.

### GHAPI-H1 — Agent polling loops with no cadence or backoff (HIGH)
- **Evidence:** `.codex/skills/verification-and-closure/SKILL.md:99,120-126`
  ("wait for CI green"; 4-surface Codex-verdict resolution: reactions + reviews +
  issue-comments + pull-comments), "do not block indefinitely" but **no interval
  specified**.
- **Impact:** Every autonomous delivery polls GitHub in a tight loop on the shared
  pool; N concurrent deliveries multiply it.
- **Fix:** Mandate poll interval + cap + exponential backoff; honor `Retry-After`;
  collapse the verdict check into one query. **Effort M · Confidence high**.

### GHAPI-H2 — No failure classification; retry amplifies exhaustion (HIGH)
- **Evidence:** `app/dispatcher/sync_github.py:283-285,315-332` (errors → `None`/
  opaque string); `reconcile_project_status.py:54-58` fixed ~6 s jittered retry, no
  `Retry-After`/reset honoring. A *per-query* `RESOURCE_LIMITS_EXCEEDED`/timeout is
  indistinguishable from quota and is retried identically.
- **Impact:** The "GraphQL exhausted" symptom conflates ≥2 causes (pool quota vs
  per-query cost); retrying an over-cost query just re-spends points.
- **Fix:** Classify on HTTP status + GraphQL error `type` + `x-ratelimit-*`; on
  quota → sleep-until-reset; on per-query cost → shrink page, don't retry as-is.
  **Effort M · Confidence high**.

### GHAPI-H3 — Zero GitHub-API observability (HIGH)
- **Evidence:** `docs/OBSERVABILITY.md` has no GitHub section; captured
  `rate_limit_remaining`/`reset` (`sync_github.py:114-117`) is **stored but never
  read**; no breaker/kill-switch/flag/runbook (negative greps documented in audit).
- **Impact:** Exhaustion is invisible until calls fail; no attribution, no
  pre-emption.
- **Fix:** Per-call structured log (op, read/write, cost, remaining, reset, status,
  retry, latency) + one rate-limit panel + a pre-exhaustion alert + a kill switch
  reading the already-captured `remaining`. **Effort M · Confidence high**.

### GHAPI-M1 — Bootstrap pre-flight checks the wrong rate-limit pool (MEDIUM)
- **Evidence:** `app/ops/builderops_startup.py:156-184` gates on
  `core.remaining < 25`, but the reads spend the **search** pool
  (`gh issue list --search`).
- **Impact:** The one guardrail can pass while the consumed quota is exhausted.
- **Fix:** Gate on the pool actually spent. **Effort S · Confidence high**.

### GHAPI-M2 — Per-event project workflows re-pull the whole board (MEDIUM)
- **Evidence:** `project-pr-opened.yml` / `project-pr-stage-change.yml` →
  `scripts/project_status.py` → `reconcile_pr` → `list_project_items` (full board);
  no `concurrency:` group.
- **Fix:** id-based card lookup; add `concurrency:` groups. **Effort M · Confidence high**.

### GHAPI-M3 — `gh issue list --limit 1000` search burst every pull (MEDIUM)
- **Evidence:** `sync_github.py:244-258` forces ~10 synchronous search pages, no
  backoff; search has a stricter 30/min limit.
- **Fix:** Paginate; fetch only when needed; smaller limit. **Effort S · Confidence medium**.

### GHAPI-L1 — REST-first convention not applied to the GraphQL hotspot (LOW)
- **Evidence:** `AGENTS.md:313-315` says prefer REST; the Projects path is still
  100 % `gh project` GraphQL; `X-GitHub-Api-Version` never set.
- **Fix:** Adopt Projects-V2 REST item endpoints where available. **Effort M · Confidence high**.

---

## Implementation coverage scores (0–5)

| Area | Score | Gap |
|---|---:|---|
| Failure classification | 1 | Only string-match of two rate-limit phrases in one script. |
| GraphQL query reduction | 2 | Dispatcher GraphQL-free; but full-board re-pagination remains. |
| REST Projects API adoption | 1 | Projects path is 100 % GraphQL; no API-version header. |
| Webhook adoption | 2 | Actions are de-facto events; no `project_v2_item` events, no persistence. |
| Local read model / cache | 1 | Only a narrow poll-populated `agent:ready` issue mirror. |
| Write throttling / coalescing | 2 | State-checked writes; no queue/serialize/concurrency groups. |
| Token / quota isolation | 1 | Only `PROJECT_TOKEN || GITHUB_TOKEN`; agents likely share the pool. |
| CI / API pressure control | 2 | Pure-CI healthy; project workflows are the pressure. |
| Observability | 0 | No dashboard/alert/metric/SLO/breaker/kill-switch/log/runbook. |
| Migration readiness | 1 | High coupling — but migration is not recommended. |

---

## GraphQL query audit

| Query / location | Risk | Why expensive | Current mitigation | Better mitigation |
|---|---|---|---|---|
| `list_project_items` — `reconcile_project_status.py:108-131` | High | Pulls entire board (content + fieldValues), re-fetches higher; hourly + per-event | ID resolved once/run; jittered retry | Item-by-id; incremental; local read model |
| Maintenance board audit — `issue-maintenance-change-control/SKILL.md:285-321,400` | High | Full-board pagination, then **re-run** as post-condition = 2 sweeps/run | Graceful stop on rate-limit | One sweep into a cached snapshot |
| `closingIssuesReferences` — `post-merge-owner-doc-watchdog.yml:30-45` | Low–Med | Paginated linked-issue query per merged PR | Isolated `GITHUB_TOKEN`; idempotent | Keep on repo token |
| `project list`/`field-list` — `reconcile_project_status.py:80,99` | Low | Small ID lookups | Resolved once/run | Cache ids across runs |

---

## Polling audit

| Job | Frequency | API/run | Token | Recommendation |
|---|---:|---:|---|---|
| `project-status-reconcile.yml --scan` | hourly (24/day) | ~3 + N | PROJECT_TOKEN (shared) | Drop to daily; incremental; kill-switch |
| Agent "wait for CI green" | per delivery, loop | repeated, no cadence | ambient (shared) | interval+cap+backoff; Retry-After |
| Agent Codex-verdict resolution | per PR, loop | 4 REST/check | ambient (shared) | single combined query; backoff |
| Maintenance / drift sweeps | per run | 2 full-board GraphQL | ambient (shared) | sweep once into cache |
| `project-pr-opened`/`-stage-change` | per PR event | ~4–8 (full board) | PROJECT_TOKEN (shared) | id lookup; concurrency group |
| `issue-pr-governance` (`synchronize`) | per push to open PR | ~2 | GITHUB_TOKEN (isolated) | leave as-is (healthy pool) |
| Dispatcher `pull` | startup | 2 search | ambient | paginate; fix pre-flight pool |

---

## Recommended next 10 changes (impact ÷ effort)

1. **GitHub App installation token** for all board/governance automation (GHAPI-C1). *M*
2. **Drop `--scan` cron hourly → daily**, gated by captured `rate_limit_remaining` (GHAPI-C2, H3). *S*
3. **Interval + cap + backoff on agent "wait for CI / Codex" loops**; collapse verdict to one query (GHAPI-H1). *M*
4. **Stop full-board re-pagination** — locate items by content-id (GHAPI-C2, M2). *M*
5. **Failure classification + sleep-until-reset** (GHAPI-H2). *M*
6. **Kill switch / circuit breaker** reading the captured `remaining` (GHAPI-H3). *S*
7. **Fix bootstrap pre-flight pool** (GHAPI-M1). *S*
8. **Structured GitHub-call logging + 1 panel + pre-exhaustion alert** (GHAPI-H3). *M*
9. **Extend dispatcher store into a project-item/PR/check read model** fed by the event-driven Actions; read local-first (GHAPI local-read-model). *L*
10. **`concurrency:` groups on the 3 project workflows + paginate `--limit 1000`** (GHAPI-M2, M3). *S*

---

## Stay vs migrate

**Recommendation: Stay on GitHub Issues/Projects and finish the API-architecture
remediation.**

Every exhaustion driver is a self-inflicted implementation choice — full-board
re-pagination, one shared token, cadence-free agent polling, retry amplification,
no read model, no observability — and none of the target-architecture fixes have
been built, so the "GitHub can't handle this" threshold has **not** been reached.
Migrating Issues/Projects to Linear/Jira/Azure Boards would be a massive lift
across the dispatcher + every skill + governance, and would **not** fix the root
cause: agents would poll the new tool's API just as hard, plus a GitHub↔external
sync bridge would itself consume GitHub quota.

The repo already has a *better-fit equivalent* of "webhooks + read model": **GitHub
Actions are the event layer (GitHub-hosted, no inbound endpoint to self-host)**,
which aligns with this single-user system's explicit decision against public
inbound webhooks (`docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md`). The missing half is
durable local persistence + low-frequency reconcile (rec #9).

**Migration threshold — revisit only if:** after (a) App-token isolation,
(b) killing full-board re-pagination, (c) a local project read model, and
(d) agent-polling backoff are all shipped, the system *still* exhausts. The only
migration variant with merit is the **hybrid** (GitHub for code/PRs, external for
Kanban) — but defer it; it doesn't address the polling root cause and fractures
the issue↔PR↔skill substrate the agentic system depends on.

---

## 30 / 60 / 90-day remediation plan

**Days 0–30 — Stop the bleeding (token isolation + cadence):**
- Provision a GitHub App, install on the repo, swap `PROJECT_TOKEN` → installation
  token in the three project workflows (rec 1).
- Change `project-status-reconcile.yml` cron `17 * * * *` → daily; add a kill-switch
  step reading `rate_limit_remaining` (rec 2, 6).
- Add poll interval + cap + backoff to `verification-and-closure` / `pr-integration`
  skill polling; collapse Codex-verdict to one query (rec 3).
- Fix `builderops_startup.py` pre-flight to gate on the spent pool (rec 7);
  paginate the dispatcher `--limit 1000` search (rec 10).
- *Verify the GHAPI-C1 collapse assumption first* (`gh auth status` vs `PROJECT_TOKEN`).

**Days 31–60 — Make failures legible + cut query volume:**
- Failure classification + `Retry-After`/reset honoring in the reconcile + dispatcher
  paths; on per-query cost, shrink page rather than retry (rec 5).
- Replace full-board pulls with content-id item lookup; add `concurrency:` groups
  (rec 4, 10).
- Ship per-call structured GitHub logging + one rate-limit panel + a pre-exhaustion
  alert (rec 8).

**Days 61–90 — Target architecture:**
- Extend `dispatcher.sqlite3` into a project-item/PR/check read model, write-through
  on each event-driven Action; migrate status/triage/agent reads to local-first,
  GitHub for writes + a daily drift reconcile against the model (rec 9).
- Write a GitHub-API-exhaustion runbook + a simple error budget for the shared pool;
  convert maintenance double-sweeps to single-sweep-against-cache.
- Re-measure. If exhaustion persists after this, *then* evaluate the hybrid-Kanban
  option with real data.

---

## Source anchors index

| Anchor | Title | Severity |
|---|---|---|
| GHAPI-C1 | Shared 5,000/hr quota across board automation + interactive agents | Critical |
| GHAPI-C2 | Hourly full-board re-pagination reconcile | Critical |
| GHAPI-H1 | Agent polling loops with no cadence or backoff | High |
| GHAPI-H2 | No failure classification; retry amplifies exhaustion | High |
| GHAPI-H3 | Zero GitHub-API observability | High |
| GHAPI-M1 | Bootstrap pre-flight checks the wrong rate-limit pool | Medium |
| GHAPI-M2 | Per-event project workflows re-pull the whole board | Medium |
| GHAPI-M3 | `gh issue list --limit 1000` search burst every pull | Medium |
| GHAPI-L1 | REST-first convention not applied to the GraphQL hotspot | Low |
