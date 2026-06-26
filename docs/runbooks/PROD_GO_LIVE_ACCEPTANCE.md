# Prod Go-Live Acceptance Runbook

State: Active operator runbook for the production go-live acceptance procedure.
Doc role: Operator runbook
Authority: Describes the operator-executed acceptance procedure; runtime contracts stay in `docs/HEALTH.md`, `docs/OPERATIONS.md`, and `docs/RELEASE_CHANNELS/README.md`.
Owner: Runtime / operator playbook
Temporal class: operational
Review cadence: event-driven (re-verify before each production go-live)
Last reviewed: 2026-05-15
Last verified against: docs/HEALTH.md, docs/OBSERVABILITY.md, docs/OPERATIONS.md, docs/ENVIRONMENTS.md, docs/RELEASE_CHANNELS/README.md, .codex/skills/prepare-promotion/SKILL.md, .codex/skills/execute-promotion/SKILL.md, .codex/skills/verify-promotion/SKILL.md, .codex/skills/rollback-promotion/SKILL.md

---

## Purpose

This runbook defines the operator-executed procedure for accepting the production runtime as go-live ready. It covers everything from preflight through soak and final acceptance or rejection. Use it alongside the machine-readable receipt at `docs/runbooks/prod_acceptance_receipt.example.json`.

**This is a stabilization and operator-acceptance procedure, not a feature rollout or capability expansion.** The acceptance path uses the existing baseline: registry watcher → DB outbox → worker → health/status.

**Out of scope for this acceptance path:**
- Canvas co-authoring surface (`CANVAS_ENABLED`)
- Chat cognition paths
- Deep Agents / v6.1 runtime capability consumption
- New watcher authority or mutation behavior

Companion-inclusive acceptance is covered by the test-channel golden path in
`docs/runbooks/UAT_INTEGRATED_RUNTIME_V1.md`. That runbook extends acceptance
visibility for Start → Orient → Work → Review → Confirm → Receipt → Resume
without weakening this production baseline scope or using the operator vault.

---

## Prerequisites

Before starting, confirm:

- You have a clean shell session against the prod checkout (separate git worktree from dev work per `docs/RELEASE_CHANNELS/README.md`).
- `make prod-up` is available and the prod compose stack can start.
- `VAULT_ROOT` is set to the real operator vault path.
- `DATABASE_URL` or `DB_DSN` resolves to the prod Postgres container (port 15432).
- You have a promotion plan from `prepare-promotion` if this acceptance follows a promotion. If this is a first-time go-live, the plan is produced now.
- The real vault is backed up or the operator has confirmed the vault is under iCloud sync or equivalent continuity.

---

<!-- anchor: prod-baseline-overview -->
## Prod Baseline Reference

This section answers the nine prod-baseline questions independently of the full acceptance phases below.
Use it for day-to-day startup, restart, and spot-verification without running the complete acceptance procedure.

For a full promotion acceptance (after a code-ref move from dev → stable), proceed through Phases 1–13.

<!-- anchor: canonical-prod-startup -->
### Canonical prod startup

The canonical prod startup uses the prod compose overlay, the `pkm-prod` project namespace,
explicit `prod` environment selection, and the `.env.prod.local` Midgård vault default.

**Via Makefile target** (preferred):

```bash
make prod-start-full
```

**Equivalent direct command:**

```bash
COMPOSE_FILE="docker-compose.yaml:docker-compose.prod.yml" \
COMPOSE_PROJECT_NAME="pkm-prod" \
PKM_ENVIRONMENT="prod" \
scripts/start_full_system.sh
```

- `VAULT_ROOT` is loaded from `.env.prod.local` and should resolve to Midgård — see [prod-vault-binding](#prod-vault-binding) below.
- The startup script waits for health before returning. A successful startup writes
  `startup_succeeded: true` and `runtime_verified: true` to `tmp/startup_status.json`.
- Confirm the startup receipt before enabling watcher auto-exec.
- For Ollama: add `LLM_PROVIDER=ollama`.

**Compose identity:**

| Surface | Value |
|---|---|
| Base compose file | `docker-compose.yaml` |
| Prod overlay | `docker-compose.prod.yml` |
| Compose project | `pkm-prod` |
| Postgres host port | `15432` |
| API host port | `18000` |

---

<!-- anchor: prod-db-volume-safety -->
### Prod DB and volume binding

Prod Postgres data lives in the external named volume `pkm-prod_pgdata`.

**Volume configuration (`docker-compose.prod.yml`):**

```yaml
volumes:
  pgdata_prod:
    external: true
    name: pkm-prod_pgdata
```

**Volume safety rules:**

- `external: true` means `docker compose down` (even without `-v`) cannot destroy prod data.
- Only `docker volume rm pkm-prod_pgdata` destroys the volume — never run this against prod.
- `make prod-down` runs `$(COMPOSE_PROD) down --remove-orphans` without `-v`; prod data is safe.
- Never run `make reset-zero`, `make reset-zero-force`, or any `scripts/reset_to_zero.sh` call
  against the prod channel.

The prod DB name defaults to `app` (override: `PKM_DB_NAME_PROD`).
Prod Postgres listens on host port `15432`.

Confirm the running prod DB:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec db psql -U postgres -c '\l'
```

---

<!-- anchor: prod-vault-binding -->
### Prod vault binding

The real vault root is always supplied by the operator at startup. It is never hardcoded in
code, compose files, or Makefile targets.

**How the vault root is supplied:**

```bash
# Via environment variable:
export VAULT_ROOT="/absolute/path/to/your/real/vault"
make prod-start-full

# Or inline with the canonical command:
VAULT_ROOT="/absolute/path/to/your/real/vault" \
COMPOSE_FILE="docker-compose.yaml:docker-compose.prod.yml" \
COMPOSE_PROJECT_NAME="pkm-prod" \
PKM_ENVIRONMENT="prod" \
scripts/start_full_system.sh
```

Confirm the active vault root after startup:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec api python -m app.cli settings-explain --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
vr = d.get('vault_root') or d.get('paths', {}).get('vault_root')
print(f'vault_root={vr}')
"
```

The printed path must be the real vault before proceeding with any watcher-enabled run.

**Vault safety rules:**

- Never pass a dev vault (`vault-dev/`) or test vault (`vault-test/`) as `VAULT_ROOT` to prod.
- Never start prod with `PKM_SETTINGS_PROFILE=lab` — that maps to the dev environment.
- If `settings-explain` shows a `dev` or `test` path, stop and correct the environment before
  enabling the watcher.

---

<!-- anchor: prod-verification-checklist -->
### Prod verification checklist

Run after every startup or restart. All items must be green before enabling watcher auto-exec.

```bash
# 1. Container-level health
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec api python -m app.cli health --json

# 2. Environment and vault-root gate
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec api python -m app.cli settings-explain --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
assert d.get('environment') == 'prod', f'Expected prod, got {d.get(\"environment\")}'
vr = d.get('vault_root') or d.get('paths', {}).get('vault_root')
print(f'env=prod OK  vault_root={vr}')
"

# 3. Runtime status counters (watcher tick count, worker ticks, error totals)
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec api python -m app.cli status

# 4. Watcher heartbeat freshness
cat tmp/watcher_heartbeat.json | python3 -m json.tool

# 5. Worker heartbeat freshness
cat tmp/worker_heartbeat.json | python3 -m json.tool

# 6. Outbox check — confirm no stuck rows
# Resolve the prod DB name from settings (honours PKM_DB_NAME_PROD override)
PROD_DB=$(docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec -T api python -m app.cli settings-explain --json 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('database') or d.get('db_name') or 'app')")
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec -T db psql -U postgres -d "$PROD_DB" -c "
    SELECT topic,
           count(*) FILTER (WHERE delivered_at IS NULL)        AS pending,
           min(created_at) FILTER (WHERE delivered_at IS NULL) AS oldest_pending,
           count(*) FILTER (WHERE delivered_at IS NOT NULL)     AS delivered
    FROM outbox
    GROUP BY topic
    ORDER BY pending DESC, oldest_pending;"

# 7. Settings validation
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod \
  exec api python -m app.cli settings-validate --json
```

**Required health signals (all must be green):**

- `health.state == running`
- `settings-explain.environment == prod`
- `settings-explain.vault_root` is the real vault (not a dev or test path)
- Watcher heartbeat fresh (within `WATCHER_HEARTBEAT_STALE_SECONDS`, default 60 s)
- Worker heartbeat fresh
- No stuck outbox rows with `null delivered_at` older than 2× the heartbeat cadence
- `settings-validate` returns no errors

---

<!-- anchor: safe-prod-restart -->
### Safe prod stop and restart

**Safe stop:**

```bash
make prod-down
# Equivalent: docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod down --remove-orphans
```

- Stops containers and removes orphaned containers.
- Does NOT touch the `pkm-prod_pgdata` volume (external, protected).
- Does NOT remove vault files (vault is a host-directory mount, not a Docker volume).

**Safe restart:**

```bash
export VAULT_ROOT="/absolute/path/to/your/real/vault"
make prod-down
make prod-start-full
```

After restart always run the [prod-verification-checklist](#prod-verification-checklist)
before enabling watcher auto-exec.

**Avoid:**

- `docker compose down -v` against `pkm-prod` — destroys `pkm-prod_pgdata`.
- `make reset-zero` or `make reset-zero-force` on the prod channel.
- Running `docker compose down` without `-f docker-compose.prod.yml -p pkm-prod` — may target
  the wrong project.

---

<!-- anchor: prod-baseline-receipt -->
### Prod baseline receipt

A baseline receipt records the observed runtime state at a point in time.
It is distinct from a full promotion receipt (which records a code-ref transition from
`prepare-promotion` / `execute-promotion`).

**Receipt location:** `ops/baseline/YYYY-MM-DD-<short-description>.json`
(create the directory on first use: `mkdir -p ops/baseline`)

**Minimum fields:**

```json
{
  "receipt_type": "prod-baseline",
  "environment": "prod",
  "timestamp": "<ISO 8601 UTC>",
  "compose_project": "pkm-prod",
  "compose_files": ["docker-compose.yaml", "docker-compose.prod.yml"],
  "vault_root": "<.env.prod.local Midgård path — confirm before storing>",
  "database": "app",
  "db_volume": "pkm-prod_pgdata",
  "health_state": "running",
  "watcher_heartbeat_fresh": true,
  "worker_heartbeat_fresh": true,
  "outbox_pending_count": 0,
  "startup_status_path": "tmp/startup_status.json",
  "startup_succeeded": true,
  "runtime_verified": true,
  "notes": ""
}
```

For a full post-promotion receipt (after a code-ref move), use
`docs/runbooks/prod_acceptance_receipt.example.json` as the template and Phase 9 of this
runbook as the procedure.

---

<!-- anchor: prod-baseline-vs-governance -->
### Phase distinction: baseline stabilization vs future promotion governance

Be explicit about which scope is active:

**Phase 1 — Prod baseline stabilization (current scope, Issues #964 / #969):**

- Start prod with the canonical command and prod compose overlay.
- Confirm environment, vault root, DB volume, health, watcher, worker, and outbox are correct.
- Record a baseline receipt at `ops/baseline/`.
- Does not require a code-ref promotion, rollback rehearsal, or CI gate verification.

**Phase 2 — Full promotion governance (future hardening, Issue #964 and later):**

- dev → stable promotion workflow with `prepare-promotion` / `execute-promotion`.
- Release-candidate verification against `CI SUMMARY GATES ok=true`.
- Automated rollback rehearsal and `rollback_rehearsed: true` gate.
- Full Phase 1–13 acceptance procedure in this runbook.
- Channel-isolation guard suite and cross-channel safety automation.
- Direct dev→prod policy decision.

Do not require Phase 2 gates as a prerequisite for Phase 1 baseline work.

---

## Phase 1 — Prod/Stable Preflight

**Goal:** confirm the code ref, environment config, and runtime surfaces are correct before touching the real vault.

```bash
# 1. Confirm prod checkout is on stable ref
git rev-parse stable
git rev-parse HEAD   # should match

# 2. Confirm environment resolves to prod
python -m app.cli settings-explain --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
assert d.get('environment') == 'prod', f\"Expected prod, got {d.get('environment')}\"
print('env=prod OK')
"

# 3. Validate settings artifacts (panel catalog, watcher settings, outbox wiring)
python -m app.cli settings-validate --json

# 4. Confirm vault root points at the real vault, not a fixture or dev vault
python -m app.cli settings-explain --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
vr = d.get('vault_root') or d.get('paths', {}).get('vault_root')
print(f'vault_root={vr}')
"
# Verify the printed path is your real vault before continuing.
```

**Stop if:** environment is not `prod`, `settings-validate` fails, or vault root is not the real vault.

---

## Phase 2 — Environment and Vault-Root Verification

**Goal:** confirm the separation invariants hold — prod DB, prod vault, prod artifact paths.

```bash
# Check resolved DB name
python -m app.cli settings-explain --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
db = d.get('database') or d.get('db_name')
print(f'database={db}')
# Expected: 'app' (prod default) or PKM_DB_NAME_PROD override
"

# Confirm Postgres is on the prod port (15432)
docker compose exec -T db psql -U postgres -c '\l' 2>&1 | grep -E 'app|template'

# Confirm no dev or test artifact paths are active
python -m app.cli settings-explain --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
paths = d.get('paths', {})
for k, v in paths.items():
    if v and ('dev' in str(v) or 'test' in str(v)):
        print(f'WARNING: {k}={v} looks like a non-prod path')
    else:
        print(f'  {k}={v} OK')
"
```

**Cross-environment invariants (must hold):**
- Vault root is the real vault, not `vault-dev/` or `vault-test/`.
- DB resolves to `app` (or `PKM_DB_NAME_PROD`), not `app_dev` or `app_test`.
- Runtime artifact paths are under `tmp/`, not `tmp-dev/` or `tmp-test/`.

---

## Phase 3 — DB and LLM Provider Checks

**Goal:** confirm the runtime can talk to all required dependencies.

```bash
# Health check — confirms DB, LLM provider, outbox write access
python -m app.cli health --json

# Confirm state is 'running' not 'degraded' or 'blocked'
python -m app.cli health status --json | python3 -c "
import sys, json; d=json.load(sys.stdin)
state = d.get('state')
print(f'health.state={state}')
assert state == 'running', f'Expected running, got {state}'
"

# LLM reachability
python -m app.cli llm check
```

**If health returns degraded:** read the `reason` field, check DB connection, check outbox write access (`INDEX_OUTBOX_PATH`), and check LLM provider settings before continuing.

---

## Phase 4 — Canonical Startup Path

**Goal:** confirm the runtime starts cleanly via the supported startup wrapper with the prod compose overlay.

```bash
# Start via the prod-baseline canonical command (sets WATCHER_AUTO_EXEC=1 by default)
# See canonical-prod-startup for the full command reference.
export VAULT_ROOT="/path/to/real/vault"
make prod-start-full

# Equivalent direct command:
# COMPOSE_FILE="docker-compose.yaml:docker-compose.prod.yml" \
# COMPOSE_PROJECT_NAME="pkm-prod" \
# PKM_ENVIRONMENT="prod" \
# VAULT_ROOT="/path/to/real/vault" \
# scripts/start_full_system.sh
```

Monitor `tmp/startup_status.json` for completion. A healthy startup writes `startup_succeeded: true` and `runtime_verified: true`.

**Key startup events to observe:**
- `phase` advances through `compose_up` → `db_probe` → `llm_probe` → `runtime_verified`.
- No `exit_reason` with `*_failed` values.
- `ollama_endpoint_repaired: true` (if Ollama was probed) means the endpoint was auto-corrected; run `make persist-runtime-repairs` to make it durable.

```bash
# Confirm startup status
cat tmp/startup_status.json | python3 -m json.tool
```

---

## Phase 5 — Health and Status Verification

**Goal:** confirm all runtime surfaces report healthy after startup.

```bash
# Container-level health (authoritative for the Docker stack)
make verify-runtime

# In-container health check
docker compose exec -T api python -m app.cli health --json

# Settings gate view
docker compose exec -T api python -m app.cli settings-explain --json

# Runtime status snapshot
docker compose exec -T api python -m app.cli status

# Required checks per docs/OPERATIONS.md §Operator triage order:
# 1. make verify-runtime                                      ✓
# 2. health --json                                            ✓
# 3. settings-explain --json (watcher gate, allowlist)        ✓
# 4. status (counters, tick skips, provenance)                ✓
# 5. watcher heartbeat freshness                              check below
# 6. outbox rows and delivered_at                             check below
```

```bash
# Watcher heartbeat freshness (expect updated within WATCHER_HEARTBEAT_STALE_SECONDS)
cat tmp/watcher_heartbeat.json | python3 -m json.tool

# Worker heartbeat freshness
cat tmp/worker_heartbeat.json | python3 -m json.tool

# Outbox freshness (requires psql or DB access)
docker compose exec -T db psql -U postgres -d app \
  -c "SELECT topic, created_at, delivered_at FROM outbox ORDER BY created_at DESC LIMIT 20;"
```

**Required health signals (all must be green before proceeding):**
- `health.state == running`
- `settings-explain.environment == prod`
- `settings-explain.vault_root` is the real vault
- Watcher heartbeat is fresh
- Worker heartbeat is fresh
- No stuck outbox rows with null `delivered_at` older than the heartbeat cadence

---

## Phase 6 — Real-Vault Low-Risk Smoke Test

**Goal:** confirm the watcher detects and processes a real vault note without mutations or risky side effects.

This smoke test uses the watcher in **read-and-report mode**: watcher runs, emits an outbox event, worker ingests. No panel auto-exec mutation should occur unless `WATCHER_AUTO_EXEC=1` and the note has an `ai_panel` fence without `ai_panel_auto_run: never`.

```bash
# Use a known-safe test note (no ai_panel fence, or ai_panel_auto_run: never)
# Choose a low-risk existing note from the vault, or create a new one:
TEST_NOTE_PATH="$VAULT_ROOT/smoke-test-$(date +%s).md"
cat > "$TEST_NOTE_PATH" <<'EOF'
---
uuid: <generate-uuid-here>
title: Prod Acceptance Smoke Test
ai_panel_auto_run: never
tags: [acceptance-test]
---

Prod go-live acceptance smoke test note. Safe to delete after acceptance.
EOF

# Generate UUID and substitute
UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
sed -i '' "s/<generate-uuid-here>/$UUID/" "$TEST_NOTE_PATH"
echo "Test note UUID: $UUID"
```

Record `$UUID` in the acceptance receipt as `test_note_uuid`.

```bash
# Run one watcher tick against the real vault
docker compose exec -T watcher python -m app.cli watcher run --max-ticks 1

# Confirm watcher detected the note (watcher.run audit row in JSONL log)
tail -5 "$(python -m app.cli settings-explain --json 2>/dev/null | \
  python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("outbox_path","tmp/outbox.jsonl"))')"

# Confirm outbox event was emitted
docker compose exec -T db psql -U postgres -d app \
  -c "SELECT topic, payload->>'uuid' AS note_uuid, created_at, delivered_at FROM outbox \
      WHERE payload->>'uuid' = '$UUID' ORDER BY created_at DESC LIMIT 5;"
```

After confirming the smoke test note was detected, delete it or set `ai_panel_auto_run: never` permanently to avoid future auto-exec.

---

## Phase 7 — Watcher → DB Outbox → Worker → Index/Status Verification

**Goal:** end-to-end verification of the canonical runtime path.

```bash
# 1. Confirm watcher emitted events (watcher.run audit rows)
docker compose exec -T api python -m app.cli status | grep -i watcher

# 2. Confirm outbox rows are being consumed (worker picking up events)
docker compose exec -T db psql -U postgres -d app \
  -c "SELECT topic, count(*), max(created_at), max(delivered_at) FROM outbox \
      GROUP BY topic ORDER BY max(created_at) DESC;"

# 3. Confirm worker processed events (delivered_at is set)
docker compose exec -T db psql -U postgres -d app \
  -c "SELECT count(*) AS pending FROM outbox WHERE delivered_at IS NULL \
      AND created_at > now() - interval '10 minutes';"
# Expected: 0 or low number (worker catching up). Stuck rows need investigation.

# 4. Check worker logs for errors
docker compose logs --tail=50 worker 2>&1 | grep -E "error|ERROR|failed|retry exhausted"
```

**Watcher → outbox → worker path is healthy when:**
- Watcher tick count in `python -m app.cli status` is increasing.
- Outbox rows for recent ticks have `delivered_at` set.
- Worker logs show no `worker retry exhausted` or `worker handler failed`.

---

## Phase 8 — Write-Guard and Allowlist Checks

**Goal:** confirm the allowlist and write-guard posture are production-safe before accepting.

```bash
# Full gate-resolution view (the canonical pre-production-enablement checklist)
docker compose exec -T api python -m app.cli settings-explain --json | python3 -c "
import sys, json
d = json.load(sys.stdin)
watcher = d.get('watcher', {})
print(f\"watcher_auto_exec: {watcher.get('auto_exec')}\")
print(f\"allowlist: {watcher.get('allowed_actions')}\")
print(f\"writes_allowed: {watcher.get('writes_allowed')}\")
print(f\"dedup_skipped: {watcher.get('skipped_dedup')}\")
print(f\"panel_skipped_policy: {watcher.get('panel_skipped_policy')}\")
print(f\"write_guard_context: {watcher.get('write_guard_context')}\")
"
```

**Write-guard acceptance criteria:**
- `allowlist` contains only the expected action IDs from `vault/@Settings/watchers.md`. The conservative default is `promote.evergreen`; for measurement-mode runs, `ingest.summary.create` may appear transiently.
- `writes_allowed` matches the intended posture (confirm intentionally, not by accident).
- `WATCHER_AUTO_EXEC=1` is necessary but not sufficient for safe auto-exec: confirm `allowlist`, `dedup/skipped_*`, `panel_skipped_policy`, and `writes_allowed` are all coherent.
- No `write_guard_violations` — check the acceptance receipt field and confirm it is 0.

```bash
# Check for write-guard violations in logs
docker compose logs --tail=200 watcher worker 2>&1 | grep -i "write.guard\|write_guard\|writes_allowed"
```

---

## Phase 9 — Promotion Receipt Capture

**Goal:** record a durable, machine-readable promotion receipt for audit and rollback evidence.

If this acceptance follows a `prepare-promotion` / `execute-promotion` run, a plan file already exists at `ops/promotions/YYYY-MM-DD-<short-sha>.md`. Append the acceptance receipt to it.

```bash
# Capture stable ref
STABLE_REF=$(git rev-parse stable 2>/dev/null || git rev-parse HEAD)
echo "stable_ref=$STABLE_REF"

# Generate a promotion receipt ID
RECEIPT_ID="acceptance-$(date +%Y%m%d-%H%M%S)"
echo "promotion_receipt_id=$RECEIPT_ID"
```

Populate the receipt fields using the template at `docs/runbooks/prod_acceptance_receipt.example.json`. Replace all placeholder values with observed runtime values. The receipt is the operator's signed statement of what was observed.

Fields that must be populated before finalizing the receipt:
- `environment` — must be `prod`
- `stable_ref` — the exact git ref prod is running from
- `started_at` / `ended_at` — ISO 8601 timestamps bounding the acceptance window
- `vault_root` — absolute path to the real vault
- `database` — resolved DB name (`app` or override)
- `health_required_ok` — `true` if all required health checks passed
- `watcher_ticks_seen` — count from `python -m app.cli status`
- `outbox_pending_final` — pending outbox row count at acceptance time
- `worker_errors` — count from worker logs during acceptance window
- `write_guard_violations` — count of write-guard events during acceptance window
- `test_note_uuid` — UUID of the smoke test note from Phase 6
- `promotion_receipt_id` — generated receipt ID
- `rollback_rehearsed` — `true` only after Phase 10 rehearsal is complete
- `operator_decision` — `accept` or `reject` with brief rationale in `notes`

---

## Phase 10 — Rollback Rehearsal

**Goal:** confirm the operator can execute rollback before committing to production. Rehearsal runs against a non-destructive path (does not execute real rollback unless explicitly chosen).

**Rehearsal steps (dry-run mode):**

```bash
# 1. Confirm previous stable ref exists for rollback anchor
git tag --list | grep stable
git rev-parse stable 2>/dev/null && echo "stable ref OK"
# If a stable-prev ref was recorded during execute-promotion, confirm it resolves:
git rev-parse stable-prev 2>/dev/null && echo "stable-prev ref OK" || \
  echo "stable-prev not set; manual rollback would use the previous stable sha from ops/promotions/"

# 2. Confirm the rollback skill is available
ls .codex/skills/rollback-promotion/SKILL.md && echo "rollback skill present"

# 3. Confirm the promotion plan file exists (if applicable)
ls ops/promotions/*.md 2>/dev/null | tail -1 && echo "promotion plan present"

# 4. Read the rollback contract limits (no vault rewind, no forward-only migration reversal)
echo "Rollback limits per docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md:"
echo "  - Vault is NOT rewound. Real vault notes authored after promotion are retained."
echo "  - Forward-only migrations are NOT reversed."
echo "  - External side-effects are out of scope."

# 5. Simulate the rollback path mentally:
#    rollback-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md
#    -> reverses reversible migrations on prod DB (port 15432)
#    -> moves stable ref back to stable-prev
#    -> make prod-down && make prod-up
#    -> verify-promotion to confirm prod is healthy on the previous ref

# 6. Record rehearsal as complete in the acceptance receipt:
echo "rollback_rehearsed: true"
```

**Rehearsal is considered complete when:**
- The operator has read and understood the rollback contract limits.
- The promotion plan file (or the manual rollback anchor SHA) is confirmed present.
- The operator can articulate the rollback command sequence without looking at this runbook.
- `rollback_rehearsed: true` is set in the acceptance receipt.

**If the rehearsal reveals a gap** (missing plan file, unresolvable `stable-prev`, unclear migration reversibility), stop, resolve the gap, and re-run the rehearsal before setting `rollback_rehearsed: true`.

---

## Phase 11 — Soak Guidance

**Goal:** confirm the runtime is stable over time, not just at the point of startup.

Recommended minimum soak period: **30 minutes** of active watcher ticking against the real vault before finalizing the acceptance decision.

During the soak window, observe:

```bash
# Check watcher tick count is increasing over time
watch -n 60 'docker compose exec -T api python -m app.cli status | grep -i watcher'

# Check outbox rows are not accumulating (pending count stays low)
watch -n 60 'docker compose exec -T db psql -U postgres -d app \
  -c "SELECT count(*) AS pending FROM outbox WHERE delivered_at IS NULL" -t'

# Check worker heartbeat is fresh
watch -n 60 'cat tmp/worker_heartbeat.json | python3 -c \
  "import sys,json,datetime; d=json.load(sys.stdin); print(d.get(\"last_heartbeat\"))"'
```

**Soak acceptance signals:**
- Watcher tick count is monotonically increasing over the soak window.
- Pending outbox rows remain low (< 10 rows older than 2× the worker heartbeat cadence).
- No new `worker retry exhausted` lines in worker logs.
- No write-guard violations in watcher/worker logs.
- Health endpoint continues to report `state=running`.

**If any soak signal degrades:** pause acceptance, investigate the degraded signal using `docs/OPERATIONS.md §Operator triage order`, and do not finalize `operator_decision: accept` until the issue is understood.

---

## Phase 12 — Final Acceptance / Rejection Criteria

**Accept** when ALL of the following are true:

- [ ] Phase 1: Prod/stable preflight passed (env=prod, correct vault, settings-validate green).
- [ ] Phase 2: Environment and vault-root separation invariants confirmed.
- [ ] Phase 3: DB and LLM provider health checks passed.
- [ ] Phase 4: Startup completed with `startup_succeeded: true` and `runtime_verified: true`.
- [ ] Phase 5: `make verify-runtime` passed; health, settings-explain, status all healthy.
- [ ] Phase 6: Real-vault smoke test completed; outbox event emitted and worker processed it.
- [ ] Phase 7: Watcher → outbox → worker → index path confirmed end-to-end.
- [ ] Phase 8: Write-guard and allowlist posture confirmed production-safe.
- [ ] Phase 9: Promotion receipt populated with all required fields.
- [ ] Phase 10: Rollback rehearsal completed; `rollback_rehearsed: true`.
- [ ] Phase 11: Soak period completed with no degraded signals.
- [ ] CI gate: `CI SUMMARY GATES ok=true` is green for the stable ref.

Set `operator_decision: accept` in the receipt and record a brief rationale in `notes`.

**Reject** when ANY of the following are true:

- Any required health check fails and cannot be resolved within the acceptance window.
- Outbox rows accumulate without worker delivery for longer than 2× the heartbeat cadence.
- Write-guard violations are observed.
- The smoke test note was not processed by the worker.
- Rollback rehearsal reveals an unresolvable gap (missing plan, ambiguous stable-prev).
- Soak window shows recurring degradation signals.
- CI gate is not green on the stable ref.

Set `operator_decision: reject` in the receipt, record the specific failure in `notes`, and follow the failure handling procedure in Phase 13.

---

## Phase 13 — Failure Handling and Rollback-First Guidance

**If acceptance fails at any phase, rollback is the default path.**

Do not attempt to patch prod in place unless the issue is fully understood and the patch is lower risk than rollback. When in doubt, roll back first.

```bash
# Rollback sequence (use if acceptance fails after a promotion)
rollback-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md

# Always verify after rollback
verify-promotion --plan ops/promotions/YYYY-MM-DD-<short-sha>.md
```

**Failure-specific guidance:**

| Failure | First action |
|---|---|
| health.state != running | Check DB connection, outbox write access, LLM provider; fix or rollback |
| Outbox accumulating (worker not consuming) | Check worker logs for retry exhausted; restart worker or rollback |
| Write-guard violation | Stop watcher auto-exec (`WATCHER_AUTO_EXEC=0`), investigate allowlist; do not accept |
| Smoke test note not processed | Check worker logs, outbox row for the test UUID; investigate before accepting |
| Startup failed (startup_status.json shows exit) | Read `exit_reason`, `compose_up_*`, `db_probe_*` fields; fix or rollback |
| Rollback anchor missing | Operator must identify the correct previous ref manually before rollback |
| verify-promotion FAIL after rollback | Escalate to operator; do not attempt automated second rollback |

**After any rollback:**
- Run `verify-promotion` and confirm PASS before treating prod as stable again.
- Update the promotion plan file with the rollback receipt.
- Record `operator_decision: reject` with the failure reason in the acceptance receipt.
- Open a follow-up issue to address the root cause before re-attempting go-live.

---

## Related documents

- `docs/OPERATIONS.md` — operator playbook and triage order
- `docs/HEALTH.md` — health CLI behavior and runtime health contract
- `docs/OBSERVABILITY.md` — runtime signals and counter interpretation
- `docs/ENVIRONMENTS.md` — environment model and control surfaces
- `docs/RELEASE_CHANNELS/README.md` — channel model, invariants, and promotion/rollback posture
- `.codex/skills/prepare-promotion/SKILL.md` — produce a promotion plan
- `.codex/skills/execute-promotion/SKILL.md` — execute an operator-acknowledged promotion plan
- `.codex/skills/verify-promotion/SKILL.md` — verify prod health after promotion or rollback
- `.codex/skills/rollback-promotion/SKILL.md` — roll prod back to the previous stable ref
- `docs/runbooks/prod_acceptance_receipt.example.json` — machine-readable receipt template
- `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md` — incident triage for watcher/panel/worker
- `docs/runbooks/RUNBOOK_GO_LIVE.md` — go-live startup walkthrough
