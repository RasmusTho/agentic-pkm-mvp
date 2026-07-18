State: Local BuilderOps Vault store and CLI implemented through #1502. Includes minimal leases, idempotency semantics, receipt-backed state transitions, #1507 DocsFreshnessRecord verification/drift capture flags, and #1508 RoadmapExecutionItem execution-state capture flags. API/tool boundary mechanics are documented in `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`; promotion gateway mechanics are documented in `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md`; generated projection mechanics are documented in `docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md`. No migrations or product/runtime authority changes are implemented here.
Doc role: BuilderOps store/CLI reference
Authority: Documents the #1501/#1502 local store/CLI mechanics. Object semantics remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`; authority boundaries remain owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: app/builderops, app/cli/builderops.py, ADR-0010, BuilderOps object model
Last reviewed: 2026-07-14
Last verified against: issues #1501/#1502/#1507/#1508/#3686

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
~/.local/state/builderops/builderops.sqlite3
```

The default expands to an absolute, host-stable path in the current user's home directory. It is
independent of the process working directory, so agents launched from separate checkouts or
worktrees on the same host share one SQLite database and one lease table. The store remains
single-host; this default does not add cross-host coordination.

Override mechanisms:

- `BUILDEROPS_STATE_DIR` sets the BuilderOps state directory. The default database name remains
  `builderops.sqlite3`.
- `BUILDEROPS_DB_PATH` sets the exact SQLite database path.
- CLI commands also accept `--db-path` for explicit one-command override, which is the preferred
  test path.
- API/tool callers may set `builderops_db_path` through tool settings or `BUILDEROPS_DB_PATH`
  through the environment; see `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`.

The default path is machine-local operating-plane state outside repository checkouts. It is not
`$CODEX_HOME`, not runtime/user memory, not repo authority, and not a reviewed docs surface.
Existing legacy stores under `<checkout>/runtime/builderops/` are not migrated, merged, deleted, or
silently treated as the consolidated store by this code change. Absence of a legacy store in the
current repository is not evidence that other participating repositories have no legacy state.
With neither store override set, path loading therefore fails before opening or initializing the
host-stable database unless the operator has installed this host-level acknowledgement:

```text
~/.local/state/builderops/host-store-cutover-v1.json
```

```json
{
  "schema_version": "builderops.host-store-cutover.v1",
  "scope": "same-user-same-host",
  "host_id": "actual local hostname",
  "user_id": "actual local numeric uid",
  "legacy_stores_reconciled": true,
  "participating_repos": ["owner/repo-a", "owner/repo-b"],
  "participating_roots": ["/absolute/repo-a", "/absolute/repo-b"],
  "inventory_epoch": "7afaf9af-b94f-4b5e-8242-c3cb45fc70fb",
  "actor": "operator identity",
  "acknowledged_at": "2026-07-15T00:00:00Z"
}
```

The operator creates this owner-only `0600`, non-symlink marker only after stopping BuilderOps writers, inventorying
every participating repository on the host, and reconciling or explicitly retaining its legacy
stores. The marker is bound to the actual hostname and numeric UID. `participating_repos` names
the bounded logical inventory; `participating_roots` lists the same number of unique, resolved,
absolute local roots in matching inventory order, and the current working directory must equal one
of those exact roots. Every listed root is recursively inventoried for nested
`runtime/builderops/builderops.sqlite3` stores without following symlinks, so a broad secondary
root cannot hide a newer nested legacy store. The UUID
`inventory_epoch` and timezone-aware timestamp identify the
reconciliation pass. A future timestamp, a legacy DB written after that pass, a copied host/user
identity, an unlisted current root, wrong ownership/mode, or a missing/malformed field fails before
the consolidated DB is opened. Error text remains privacy-safe; host paths and contents are not
printed.

`BUILDEROPS_DB_PATH`, `BUILDEROPS_STATE_DIR`, and CLI `--db-path` bypass the acknowledgement gate.
Environment overrides must be non-blank after trimming; blank values are treated as absent and
therefore follow the acknowledged implicit host-store path.
They remain the operator path for keeping the current store pinned before cutover and selecting the
reconciled store during cutover. This PR does not create the acknowledgement, inventory repos,
reconcile records, migrate data, stop writers, or perform the live cutover.

Default home-directory resolution is lazy. An absolute explicit DB/state/CLI override therefore
continues to work in hostless automation where no user home can be resolved.

### Shared artifact vault and advisory claim signals

`BUILDEROPS_VAULT_ROOT` may point to the dedicated Yggdrasil BuilderOps vault. It is a shared
Markdown artifact root, not a database or lock service. `builderops vault init` creates
`agent-delivery/<status>/` directories plus `.builderops/claims/` for TTL-based advisory signals.
It never creates SQLite files or provider credentials there.

`builderops vault init` creates `.builderops/claims/` in the shared vault for TTL-based advisory
claim signals. Multiple agents may write claims for the same ticket. These files improve queue
visibility and stale-recovery, but are explicitly not distributed locks: iCloud gives no global
atomic/exclusive guarantee and a live claim must never be interpreted as exclusive ownership.
SQLite (`BUILDEROPS_DB_PATH`) remains machine-local and fails closed if configured under the shared
vault. Provider credentials must remain machine-local; these vault commands neither accept nor
write provider credentials.

The SQLite separation check is a store-level invariant. CLI configuration, explicit API/MCP
`BuilderOpsBoundary` paths, completeness-report inspection, and direct `SqliteBuilderOpsStore`
construction all reach the same guard before SQLite can open or create a file. Completeness-report
inspection opens existing databases in SQLite read-only mode so a discovery/open race cannot create
a replacement file. The guard checks both lexical and resolved containment, so a database symlink
located in the shared vault cannot redirect a store open to an outside target.

### Model-inquiry artifact records

Pre-ticket model inquiries are durable file-first records under
`$BUILDEROPS_VAULT_ROOT/model-inquiries/<inquiry_id>/`. Their immutable question, ordered turns,
optional synthesis/readiness artifacts, and canonical `BuilderOpsReceipt` files are shared artifacts,
not SQLite rows. A manifest written after the question and start receipt is the inquiry commit
marker. Trace reads fail closed on missing receipts, invalid hashes, dangling input references,
foreign inquiry IDs, or symlinked artifact paths.

Inquiry writes serialize to a same-directory temporary file and install the final pathname with a
no-overwrite link. Equal retries reconcile to the existing value; a different payload for an
already committed path is a conflict. Local SQLite remains the mutable machine-local operational
index and is neither created nor treated as durable inquiry authority in the shared vault.
Turn filenames reserve their numeric sequence slot atomically on one filesystem, and turn-ID
reservation files independently reserve the logical identity. Canonical artifact hashes bind
content plus provenance and causal edges, while manifests and terminal receipts bind the relevant
artifact hash. Reservation publication, turn publication, and conflict cleanup are serialized per
inquiry across threads and processes on one host using an OS advisory file lock. Orphaned
reservations remain visible as an incomplete trace and can be reconciled by an exact retry.

The configured filesystem must support same-directory hard links, file `fsync`, and directory
`fsync`. Inquiry creation and each immutable write enforce those operations and fail closed when
the filesystem rejects them. A post-link directory-sync failure is reported as incomplete; an
equal retry reconciles the installed payload and retries the directory sync. Newly created
directory entries are synced through their parent chain before start returns.

This does not promote iCloud advisory claims into distributed locks: independently synchronized
devices can still race, and any resulting conflicting graph fails trace validation rather than
being silently accepted.

BMI-03 provider turns add adapter request ID, nullable provider-returned request ID,
adapter/provider/model identity, canonical context/request/input/output hashes, phase, round, and
stance to the immutable turn record. Valid output is committed before a successor request. Refusal,
malformed output, unavailable adapters, provider errors, persistence failures, exhausted rounds,
and consensus are recorded as canonical BuilderOps receipts.

Role-to-adapter configuration and credentials remain machine-local. Shared inquiry files never
store HTTP credentials, bearer headers, command argv, environment dumps, or raw stderr. The runner
does not use Product/Runtime provider fallback: an unconfigured Fable role records
`provider_unavailable`. Host-local inquiry-runner flock prevents duplicate provider execution by
concurrent local CLI/API workers; cross-device iCloud coordination remains advisory and any
conflicting synchronized graph fails closed.

Treat the shared tree as untrusted file input. Queue operations fail closed on a symlinked vault
root, any existing symlinked ancestor in the configured root path, pre-existing symlinked
queue/claim ancestors, and ticket, claim, or SQLite-candidate leaves rather than following
them outside the vault. This is a static-entry confinement guarantee, not protection from a
malicious same-host process swapping filesystem entries between system calls. Queue tickets require
unique YAML mapping keys plus valid `id` and normalized `status` fields; optional dispatcher
`column` must agree with status. Advisory claims require filename-safe ticket IDs, non-empty agents,
timezone-aware timestamps, and an increasing claim interval. Blank agent identities are rejected
before write. Claim filenames remain non-authoritative: release matches the validated payload's
ticket and agent, never the filename prefix. BMI-01 does not impose a maximum TTL or future-clock-skew limit because these
files never grant exclusive ownership.

Use the following operator checks before using a shared vault:

```bash
scripts/builderops_cli.sh builderops vault paths --json
scripts/builderops_cli.sh builderops vault init "$BUILDEROPS_VAULT_ROOT" --json
scripts/builderops_cli.sh builderops vault validate "$BUILDEROPS_VAULT_ROOT" --json
```

Signboard may render the resulting `agent-delivery/` Markdown tree for a human. It is a projection
only and is never an automation API or a source of authoritative lease state.

Projection regeneration reads from the selected store path using the same mechanisms. Automation
worktrees that regenerate checked-in projection views should set the intended store explicitly with
`BUILDEROPS_DB_PATH`, `BUILDEROPS_STATE_DIR`, or `--db-path`; otherwise the guard in the projection
generator may fail loud before overwriting existing generated projections with records from an empty
or incomplete worktree-local store.

**Store durability and regen diff expectations:** The default store at
`~/.local/state/builderops/builderops.sqlite3` is machine-local and mutable. It is not shared across
devices and is not reproducible over time. Unlike the former worktree-local default, worktree
pruning does not remove it. Checked-in projections under
`docs/generated/builderops/` are non-authoritative views over this ephemeral store; records that
appear in a checked-in projection may be absent in the current local store after any store rotation,
device change, or worktree lifecycle event. A regen diff — records appearing or disappearing between
runs — is expected, not data loss. Only promotion through a real authority path (GitHub Issue, PR,
ADR, or owner doc) makes BuilderOps material durable; a projection record alone carries no
durability guarantee. See `docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md ::
Non-Authoritative and Non-Reproducible` for the full consequences.

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

Automation worktrees and dev/prod full-stack startup should use the supported wrapper instead of
assuming a bare `python` binary exists on `PATH`:

```bash
scripts/builderops_cli.sh builderops list --json
```

`scripts/start_builderops_services.sh` uses this wrapper during `make dev-start-full` and
`make prod-start-full` to verify that the BuilderOps store can initialize/list records and that the
database path resolves predictably.
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
