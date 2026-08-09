State: Local BuilderOps Vault store and CLI implemented through #1502. Includes minimal leases, idempotency semantics, receipt-backed state transitions, #1507 DocsFreshnessRecord verification/drift capture flags, and #1508 RoadmapExecutionItem execution-state capture flags. API/tool boundary mechanics are documented in `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`; promotion gateway mechanics are documented in `docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md`; generated projection mechanics are documented in `docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md`. No migrations or product/runtime authority changes are implemented here.
Doc role: BuilderOps store/CLI reference
Authority: Documents the #1501/#1502 local store/CLI mechanics. Object semantics remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`; authority boundaries remain owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: app/builderops, app/cli/builderops.py, ADR-0010, BuilderOps object model
Last reviewed: 2026-07-27
Last verified against: issues #1501/#1502/#1507/#1508/#3686; store-posture and receipt-bootstrap mechanics verified against app/builderops/config.py, app/builderops/cutover_evidence.py, and app/builderops/cli.py at c25f86949

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
- `BUILDEROPS_DB_PATH` sets the exact SQLite database path. When both are set, `BUILDEROPS_DB_PATH`
  selects the database and `BUILDEROPS_STATE_DIR` only sets the state directory; the state directory
  does not redirect an explicit database path.
- CLI commands generally accept `--db-path` for an explicit one-command override, which is the
  preferred test path. The `cutover-evidence generate` producer is the exception: it rejects this
  override because it can produce evidence only for the implicit host-stable store.
- API/tool callers may set `builderops_db_path` through tool settings or `BUILDEROPS_DB_PATH`
  through the environment; see `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md`.

The default path is machine-local operating-plane state outside repository checkouts. It is not
`$CODEX_HOME`, not runtime/user memory, not repo authority, and not a reviewed docs surface.
Existing legacy stores under `<checkout>/runtime/builderops/` are not migrated, merged, deleted, or
silently treated as the consolidated store by this code change. Absence of a legacy store in the
current repository is not evidence that other participating repositories have no legacy state.
With neither store override set, path loading therefore fails before opening or initializing the
host-stable database unless the operator has installed the supported producer-generated receipt.
The receipt is created (without running live cutover) with:

```text
python -m app.builderops builderops cutover-evidence generate \
  --participants-file participants.json --reconciliation-file reconciliation.json \
  --actor <operator> --json
```

The ordered participant/repository/root list is the explicit inventory boundary. The producer
recursively discovers every legacy store beneath those roots, binds its identity and disposition,
the actual host and numeric user, one reconciliation epoch, and an already-existing non-empty target.
Because this producer governs the implicit host-stable store, the group-level CLI `--db-path`
override is rejected before inspection or mutation.
The producer also applies the shared vault-confinement guard to the implicit target path before
legacy-store inventory, target inspection, marker stamping, or receipt creation. A target beneath
`BUILDEROPS_VAULT_ROOT` therefore fails without mutating the database or receipt location.
Implicit path loading applies that same guard before reading the receipt or opening the target, so
a previously valid target later confined beneath the vault is rejected without inspection.
The validator recomputes those bindings before SQLite initialization; copied, stale, incomplete,
post-epoch-mutated, or empty-target receipts fail closed.
The payload schema is `builderops.host-store-cutover.v2`; the `host-store-cutover-v1.json`
filename is intentionally retained as the compatibility location for the prior marker.

```text
~/.local/state/builderops/host-store-cutover-v1.json
```

```json
{
  "schema_version": "builderops.host-store-cutover.v2",
  "scope": "same-user-same-host",
  "host_id": "actual local hostname",
  "user_id": "actual local numeric uid",
  "participants": [{"repository": "owner/repo-a", "root": "/absolute/repo-a"}],
  "reconciliation_epoch": "7afaf9af-b94f-4b5e-8242-c3cb45fc70fb",
  "actor": "operator identity",
  "reconciled_at": "2026-07-15T00:00:00Z",
  "legacy_store_inventory": [],
  "reconciliation": [],
  "target_store": {"path": "/absolute/state/builderops.sqlite3", "record_count": 1}
}
```

After the operator has stopped BuilderOps writers and reconciled every discovered legacy store, the
producer recursively inventories the ordered `participants` roots without following symlinks,
verifies the supplied reconciliation report against that inventory and the existing non-empty
target, stamps the target, and creates the owner-only `0600`, non-symlink receipt. A report path
outside the discovered inventory is rejected before its records are opened. Each participant
contains its repository identity and one unique, resolved absolute root. Receipt validation accepts
a current working directory equal to or descended from exactly one declared root; an unrelated or
ambiguously nested participant location fails closed.

The deterministic `reconciliation_epoch` is derived from the actual host and numeric user, ordered
participants, complete legacy-store inventory, reconciliation report, and target identity. The
receipt binds the inventory and report with `inventory_sha256` and `reconciliation_sha256`, binds
the target path and identity, and carries a whole-receipt digest. The target marker binds that same
identity and epoch to an evidence digest of the receipt. Validation recomputes these bindings and
the inventory before the implicit database can be initialized; a future cutoff, post-cutoff legacy
write, copied host/user identity, incomplete report, changed target marker, invalid ownership or
mode, or malformed field fails closed. Error text remains privacy-safe; host paths and contents are
not printed.

Non-blank `BUILDEROPS_DB_PATH` and `BUILDEROPS_STATE_DIR` values bypass the receipt gate during
normal store selection, as does CLI `--db-path` for commands that support it. Blank environment
values are treated as absent and therefore follow the receipt-gated implicit host-store path. The
`cutover-evidence generate` command rejects CLI `--db-path` before inspection or mutation. These
overrides remain the operator path for pinning the current store before cutover and selecting the
reconciled store during cutover. The producer is evidence-only: it does not stop writers, migrate
or reconcile records, or perform the live cutover.

Default home-directory resolution is lazy. An absolute explicit DB/state/CLI override therefore
continues to work in hostless automation where no user home can be resolved.

### Choosing a store posture for a host

The receipt route and the explicit override are not interchangeable defaults. `validate_receipt`
re-derives its bindings on every implicit store load, so the receipt posture only holds on a host
where those bindings are stable:

- the current working directory must sit inside exactly one declared participant root;
- `_participants` resolves each declared root with `strict=True`, so a root that no longer exists
  fails the gate closed;
- the legacy-store inventory beneath the declared roots is re-walked and compared on each load, and
  any legacy-store write after the reconciliation epoch is rejected.

Prefer the receipt when the host's BuilderOps working directories all live under a small set of
long-lived roots that can be declared once, and the legacy stores beneath those roots are frozen.
Implicit selection is then self-verifying, with no environment state to lose.

Prefer the explicit override (`BUILDEROPS_STATE_DIR`, or `BUILDEROPS_DB_PATH`) when any of the
following holds on the host:

- BuilderOps commands run from worktrees under several unrelated parent directories — for example
  `<repo>/.claude/worktrees/`, `~/.codex/worktrees/`, and `~/code/pkm-worktrees/`. Every parent has
  to be declared, and adding a new worktree parent silently re-breaks the gate until the receipt is
  regenerated.
- Those parent directories are created and reaped routinely. A reaped root fails strict resolution
  and takes store selection down with it.
- The recursive legacy-store discovery walk over the declared roots is expensive enough that paying
  it on every store load is unattractive.

Set the override where every shell inherits it (for example `~/.zshenv`), so interactive shells,
agent tool shells, and CLI sessions resolve the same store regardless of which checkout or worktree
they start from. The value must be absolute (`~` expansion is applied, but a relative value is not
resolved against any stable base): a relative `BUILDEROPS_STATE_DIR` or `BUILDEROPS_DB_PATH` is
interpreted against each process working directory and silently produces a separate database per
worktree, which is the exact failure this posture exists to prevent. Record the choice in a
host-local operator note; that note is host state, not repo authority. Worked example: the primary
development laptop was consolidated onto the explicit `BUILDEROPS_STATE_DIR` posture on 2026-07-27,
with the reasoning kept host-locally in `~/.local/state/builderops/HOST_POSTURE.md` on that machine.

Either posture yields the same host-stable store. The override does not weaken the SQLite
separation check or the vault-confinement guard; it only bypasses the receipt gate during store
selection.

### Bootstrapping the receipt on a host with no host-stable store

`cutover-evidence generate` verifies an existing target; it never creates one. `build_receipt`
inspects the implicit target with `inspect_target` and fails closed with `target store is empty`
unless that database already exists, is an initialized BuilderOps database, and holds at least one
record. The producer always resolves the target from the default state directory:
`BUILDEROPS_STATE_DIR` does not redirect it, and the CLI rejects `--db-path` before inspection.

Because implicit selection is exactly what the guard blocks, the target cannot be created through
the implicit path. On a host with no host-stable store yet, the receipt route is therefore
override-first — the override is a prerequisite of the receipt, not an alternative to it:

```bash
# 1. Pin the store explicitly at the default state directory, because that is the only target the
#    producer will inspect. Clear any inherited BUILDEROPS_DB_PATH first: an exact database path
#    takes precedence over the state directory when both are set, so leaving it in place would
#    write step 2 into the old database while the producer inspects the still-empty target.
unset BUILDEROPS_DB_PATH
export BUILDEROPS_STATE_DIR="$HOME/.local/state/builderops"

# 2. Initialize the target and give it at least one record. An initialized but record-free
#    database still fails with "target store is empty".
scripts/builderops_cli.sh builderops create-worklog \
  --summary "Host store bootstrap" \
  --body "Initialized the host-stable target store." \
  --source-ref repo_doc:docs/builderops/BUILDEROPS_VAULT_STORE.md \
  --idempotency-key create:host_store_bootstrap

# 3. Stop BuilderOps writers and reconcile every legacy store beneath the participant roots into
#    that target, then generate the receipt from a working directory inside exactly one declared
#    participant root.
python -m app.builderops builderops cutover-evidence generate \
  --participants-file participants.json --reconciliation-file reconciliation.json \
  --actor <operator> --json

# 4. Drop the override and confirm that implicit selection now passes.
unset BUILDEROPS_STATE_DIR
scripts/builderops_cli.sh builderops list --json
```

Stopping after step 2 leaves a working host-stable store under the explicit-override posture. The
receipt only adds self-verifying implicit selection on top of it, and is worth producing only when
the bindings in `Choosing a store posture for a host` hold.

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

`builderops vault validate` additionally scans the vault for a SQLite database that is already
there. That scan is the only part of these commands whose cost grows with vault size, and on a
synchronized vault it deliberately avoids downloading evicted files it can prove are not database
images; `--progress` reports what it is doing. See the operator-check block under
`Model-inquiry artifact records` below for the command, the flag, and the measured cost.

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

### Builder Thread artifact exchange

Builder Threads are an executable file-first exchange under
`$BUILDEROPS_VAULT_ROOT/builder-threads/`. They are for one bounded question to a named recipient
when a reply is expected and the same subject/source/recipient capture is not already represented.
Monologic work notes remain `AgentWorklog`; Builder Threads are never Issue, PR, review, approval,
`Verify:`, merge, closure, or promotion authority.

`builder-thread init` normally verifies the immutable `.builderops/vault-genesis.json` and matching
`builder-threads/genesis.json` envelopes. First adoption requires the explicit
`--adopt-existing` operator flag after vault validation; ordinary create/read/review paths never
self-attest a root. Every client must pin the UUID through `BUILDEROPS_VAULT_ID`; a mismatched,
missing, or divergent identity fails before artifact use. Contributions are canonical
`shared_non_sensitive` JSON envelopes at
`builder-threads/threads/<thread-id>/entries/<slot>/<sha256>.json`, where the filename binds the complete
file bytes. Canonical encoding is UTF-8 with lexicographically sorted object keys, compact
comma/colon separators, direct JSON Unicode, and one terminal LF. Strict bounds and scanners reject
obvious credentials, argv/env/stderr, raw private host
paths, unsafe refs, symlinks, SQLite, conflict-copy names, partial/temp artifacts, unknown schemas or
paths, duplicate IDs, hash mismatches, and replay conflicts.

Create, reply, close, archive, and quarantine require a caller-retained `--entry-id` UUIDv4. An exact
semantic retry with that ID returns the installed contribution even when the helper generates a later
timestamp; changed semantics under one ID are refused. Before contribution publication, an immutable
visible manifest at `builder-threads/entry-claims/<entry-id>.json` atomically binds that vault-wide ID,
thread ID, and canonical semantic-request digest (excluding only the generated timestamp). It is a
create-if-absent concurrency/recovery guard, not a mutable index or authority. A claim-only crash is
incomplete to readers and only an exact writer retry may finish it. Each entry slot carries an
identity-bound durable reservation until the claimed final exists. If final publication succeeded but
temp or reservation cleanup failed, a later mutation retry removes it only after the claim, bytes, and
content-addressed final agree. Read-only health never performs cleanup.

Publication uses a same-directory exclusive temporary file, file `fsync`, a no-overwrite hard
link, directory `fsync`, readback, temp unlink, and a second directory `fsync`. There is no
sequence, mutable head, database, shared lock, reminder entry, or hidden client index. Exact replay
is idempotent. Initial thread destinations use create-if-absent/no-overwrite directory creation;
readers accept them only after the entries directory, one reserved slot, and a complete
content-addressed open contribution exist. A pre-existing empty destination is left untouched and
reported as a typed conflict. Stale dispositions use immutable supersession lineage. An explicit
hash-bound quarantine contribution can preserve and redact a structurally valid unsafe or conflicting
artifact; it never masks structural corruption. Each thread has exactly 128 possible immutable
entry slots. A writer reserves one before publishing contribution bytes, so a concurrent or
sequential 129th append fails without changing the tree. Multiple active quarantine decisions for
one target are themselves a conflict; only a real set of at least two active sibling decisions
allows `concurrent_conflict` to disposition one exact decision without deleting either envelope
while a slot remains. A lone quarantine decision cannot be neutralized. Entry IDs are unique across
the whole Builder Thread vault, not merely within one thread.

Use the production operator surfaces:

```bash
scripts/builderops_cli.sh builderops builder-thread --help
scripts/builderops_cli.sh builderops builder-inbox --help
```

`builder-inbox` is read-only. It reconstructs bounded recipient/health views and a deterministic
snapshot hash from validated contributions. Unchanged input produces no mutation, and review never
replies, closes, archives, quarantines, reminds, promotes, or triggers learning by itself.

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

`vault paths` is pure path arithmetic and returns instantly. `vault validate` walks the whole vault
to enforce the SQLite confinement invariant, so its cost scales with vault size — add `--progress`
to get a stderr heartbeat and a final `scanned N files, opened M, skipped K non-local` line, which
is how you tell a slow synchronized vault from a hung command. The JSON payload carries the same
counts under `sqlite_scan`. On a synchronized (iCloud) vault the scan deliberately does not
materialize evicted files whose size cannot be a SQLite database image; see
`docs/BUILDEROPS_MODEL_INQUIRY/EXTERNAL_BUILDEROPS_VAULT_CONFIGURATION.md :: SQLite Confinement
Invariant` for why that cannot hide a real database. Measured on the ~900-file shared vault
2026-07-28: 0.13 s scan, versus ~1.4 s of extra network wait for every evicted file the previous
scan downloaded.

The resulting `agent-delivery/` tree holds BMI-01 ticket Markdown for a human to read. It is never
an automation API or a source of authoritative lease state.

It is **not** the dispatcher Signboard board. The visual Signboard at `/signboard` is served directly
from the dispatcher SQLite store and reads no Markdown at all (#4401). The legacy
`export-signboard` command still writes a separate, regenerable Markdown board whose cards carry
`generated_by: dispatcher.signboard` and a different frontmatter schema from these vault tickets.
Do not point `SIGNBOARD_ROOT` at this vault's `agent-delivery/`, and do not migrate cards between
the two trees — see `docs/AGENT_ISSUE_DISPATCHER.md :: The projection root is not the shared
BuilderOps vault's agent-delivery/`.

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
