State: Local BuilderOps Vault store and CLI implemented through #1502. Includes minimal leases, idempotency semantics, receipt-backed state transitions, #1507 DocsFreshnessRecord verification/drift capture flags, and #1508 RoadmapExecutionItem execution-state capture flags. API/tool boundary mechanics are documented in `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`; promotion gateway mechanics are documented in `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md`; generated projection mechanics are documented in `docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md`. No migrations or product/runtime authority changes are implemented here.
Doc role: BuilderOps store/CLI reference
Authority: Documents the #1501/#1502 local store/CLI mechanics. Object semantics remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`; authority boundaries remain owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: app/builderops, app/cli/builderops.py, ADR-0010, BuilderOps object model
Last reviewed: 2026-06-01
Last verified against: issues #1501/#1502/#1507/#1508

# BuilderOps Vault Store and CLI

## Scope

The initial BuilderOps Vault implementation is a local SQLite store plus CLI for creating,
reading, listing, and lease-protected state transitions for BuilderOps records.

The store validates every initial object type from the object model. Typed CLI commands in this
slice cover:

- `AgentWorklog`
- `LearningSignal`
- `PromotionIntent`
- `DocsFreshnessRecord`
- `RoadmapExecutionItem`
- `BuilderOpsReceipt`

The store preserves the object envelope from the BuilderOps object model, including
`source_refs`, `promotion_status`, `lifecycle_state`, `authority_class`, timestamps, and actor
identity. It validates supported `object_type` values and required fields before persistence.

## Multi-Agent Safety

The #1502 safety layer is intentionally local and minimal. It does not provide distributed locking
across machines, but it does serialize local SQLite writes and gives agents explicit failure modes.

### Agent identity

Every created record still carries `created_by`. Lease acquisition and state transitions require an
`actor` with `actor_type` and `id`. State transitions also write `updated_by` into the record
payload.

### Idempotency

Create commands may provide an `idempotency_key`. Receipt creation requires one. The store records
the operation, request hash, result record, and response payload for each key.

- Retrying the same operation with the same key and same request returns the original response.
- Reusing a key for different material is rejected as a conflict.
- Idempotency keys are BuilderOps write-safety metadata only; they do not promote records or mutate
  repo/GitHub authority.

### Leases

State transitions require an active lease for the target BuilderOps record. Agents acquire a lease
for a record, perform the transition with the returned `lease_id`, then may release it.

- A second actor cannot acquire an unexpired lease for the same record.
- Expired leases are rejected on transition and may be replaced by a later acquire.
- Leases protect BuilderOps material updates only; they do not lock product/runtime state or
  GitHub/repo authority surfaces.

### Receipts

`transition` appends a `BuilderOpsReceipt` and links it from the transitioned record's
`receipt_refs`. The receipt captures `previous_state`, `new_state`, the acting agent, source refs,
and the transition idempotency key. Receipt records are append-only; they are not silently rewritten
or transitioned.

## Store Location

Default state path:

```text
runtime/builderops/builderops.sqlite3
```

Override mechanisms:

- `BUILDEROPS_STATE_DIR` sets the BuilderOps state directory. The default database name remains
  `builderops.sqlite3`.
- `BUILDEROPS_DB_PATH` sets the exact SQLite database path.
- CLI commands also accept `--db-path` for explicit one-command override, which is the preferred
  test path.
- API/tool callers may set `builderops_db_path` through tool settings or `BUILDEROPS_DB_PATH`
  through the environment; see `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`.

The default path is repo-local runtime state and is ignored by Git via `runtime/builderops/`. It is
not `$CODEX_HOME`, not local hidden memory, not repo authority, and not a reviewed docs surface.

Projection regeneration reads from the selected store path using the same mechanisms. Automation
worktrees that regenerate checked-in projection views should set the intended store explicitly with
`BUILDEROPS_DB_PATH`, `BUILDEROPS_STATE_DIR`, or `--db-path`; otherwise the guard in the projection
generator may fail loud before overwriting existing generated projections with records from an empty
or incomplete worktree-local store.

## CLI

Examples:

```bash
python -m app.cli builderops create-worklog \
  --summary "Issue #1501 implementation context" \
  --body "Captured minimal store/CLI implementation context." \
  --task-context '{"issue":"#1501"}' \
  --source-ref github_issue:#1501 \
  --idempotency-key create:awl_example

python -m app.cli builderops create-learning-signal \
  --summary "BuilderOps records need provenance" \
  --content "The minimal store rejects records without source_refs." \
  --signal-type workflow \
  --source-ref github_issue:#1501

python -m app.cli builderops create-promotion-intent \
  --summary "Draft a follow-up issue" \
  --target-authority-surface github_issue \
  --target-action create \
  --target-ref pending \
  --target-authority-class operational \
  --intended-output "Bounded GitHub Issue draft." \
  --source-ref builderops_object:lrn_example \
  --idempotency-key create:prom_example

python -m app.cli builderops create-docs-freshness-record \
  --summary "DOCS_INDEX BuilderOps entry checked" \
  --doc-ref repo_doc:docs/DOCS_INDEX.md \
  --owner "Documentation role map" \
  --review-cadence event-driven \
  --freshness-posture current \
  --drift-status none \
  --last-reviewed-at 2026-06-01T00:00:00Z \
  --last-verified-against repo_doc:docs/ARCHITECTURE.md \
  --last-verified-at 2026-06-01T01:00:00Z \
  --next-review-due-at 2026-06-15T00:00:00Z \
  --freshness-evidence-ref github_issue:#1507 \
  --next-review-owner "BuilderOps governance" \
  --source-ref repo_doc:docs/DOCS_INDEX.md

python -m app.cli builderops create-roadmap-execution-item \
  --summary "BuilderOps Vault #1501 is in progress" \
  --roadmap-ref github_issue:#1498 \
  --theme "BuilderOps Vault" \
  --capability "shared operating plane" \
  --execution-state in_progress \
  --status active \
  --owner "BuilderOps governance" \
  --active-issue github_issue:#1508 \
  --blocker none \
  --last-movement "PR #1519 merged #1507." \
  --next-decision "Continue with #1508 after #1507 merges." \
  --shipped-ref pull_request:#1519 \
  --source-ref github_issue:#1498

python -m app.cli builderops append-receipt \
  --summary "Created learning signal" \
  --event-type object_created \
  --actor codex \
  --occurred-at 2026-06-01T00:00:00Z \
  --target-ref builderops_object:lrn_example \
  --action create \
  --receipt-body "Created learning signal from issue #1501." \
  --idempotency-key object_created:lrn_example \
  --source-ref github_issue:#1501

python -m app.cli builderops acquire-lease prom_example \
  --actor codex \
  --json

python -m app.cli builderops transition prom_example \
  --actor codex \
  --lease-id lease_from_acquire_lease \
  --idempotency-key transition:prom_example:accepted \
  --source-ref github_issue:#1502 \
  --summary "Accepted promotion intent" \
  --action accept \
  --receipt-body "Accepted the promotion intent as BuilderOps material." \
  --lifecycle-state accepted

python -m app.cli builderops list --type AgentWorklog
python -m app.cli builderops read awl_example
```

Each command accepts `--json` for machine-readable output. References may be supplied as JSON
objects or as shorthand `ref_type:ref`.

### Startup readiness wrapper

Automation worktrees and dev startup should use the supported wrapper instead of assuming a bare
`python` binary exists on `PATH`:

```bash
scripts/builderops_cli.sh builderops list --json
```

`scripts/start_builderops_services.sh` uses this wrapper during `make dev-start-full` to verify that
the BuilderOps store can initialize/list records and that the database path resolves predictably.
Failure to reach GitHub during the same bootstrap is recorded as degraded startup state, but the
BuilderOps store readiness check itself goes through the wrapper/API boundary rather than importing
store internals or relying on host Python.

## Authority Boundary

The store is BuilderOps operational infrastructure. Writing a BuilderOps record does not mutate
repo authority, product/runtime truth, GitHub Issues, docs, skills, ADRs, PRs, generated
projections, or runtime behavior.

Docs freshness records are the operational place for high-churn review queues, stale/drift
observations, next-review due dates, and verification evidence. `docs/DOCS_INDEX.md` remains the
repo-authoritative role/routing map, while the generated `docs-freshness` projection is only a
repo-readable view over BuilderOps records.

Roadmap execution records are the operational place for daily movement, active issues, blockers,
last movement, next decision, and shipped references. `docs/ROADMAP.md` remains the strategic
sequencing surface, while the generated `roadmap-execution` projection is only a repo-readable view
over BuilderOps records.

Promotion remains explicit and separate. `PromotionIntent` records are staged material until the
promotion gateway renders proposal material, appends receipts, and records explicit state
transitions. Normal repo/GitHub authority gates still own the target surface.

## Out Of Scope

This slice intentionally does not implement:

- migrations from `docs/learning-log.md`, `docs/DOCS_INDEX.md`, or `docs/ROADMAP.md`
- product/runtime authority changes
