State: Minimal local BuilderOps Vault store and CLI implemented for #1501. No leases, idempotency semantics, API/MCP boundary, promotion gateway, generated projections, migrations, or product/runtime authority changes are implemented here.
Doc role: BuilderOps store/CLI reference
Authority: Documents the #1501 minimal local store/CLI mechanics. Object semantics remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`; authority boundaries remain owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: app/builderops, app/cli/builderops.py, ADR-0010, BuilderOps object model
Last reviewed: 2026-06-01
Last verified against: issue #1501

# BuilderOps Vault Store and CLI

## Scope

The initial BuilderOps Vault implementation is a minimal local SQLite store plus CLI for creating,
reading, and listing BuilderOps records.

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

The default path is repo-local runtime state. It is not `$CODEX_HOME`, not local hidden memory, and
not a reviewed docs surface.

## CLI

Examples:

```bash
python -m app.cli builderops create-worklog \
  --summary "Issue #1501 implementation context" \
  --body "Captured minimal store/CLI implementation context." \
  --task-context '{"issue":"#1501"}' \
  --source-ref github_issue:#1501

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
  --source-ref builderops_object:lrn_example

python -m app.cli builderops create-docs-freshness-record \
  --summary "DOCS_INDEX BuilderOps entry checked" \
  --doc-ref repo_doc:docs/DOCS_INDEX.md \
  --owner "Documentation role map" \
  --review-cadence event-driven \
  --freshness-posture current \
  --last-reviewed-at 2026-06-01T00:00:00Z \
  --next-review-due-at 2026-06-15T00:00:00Z \
  --source-ref repo_doc:docs/DOCS_INDEX.md

python -m app.cli builderops create-roadmap-execution-item \
  --summary "BuilderOps Vault #1501 is in progress" \
  --roadmap-ref github_issue:#1498 \
  --execution-state in_progress \
  --owner "BuilderOps governance" \
  --next-decision "Continue with #1502 after #1501 merges." \
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

python -m app.cli builderops list --type AgentWorklog
python -m app.cli builderops read awl_example
```

Each command accepts `--json` for machine-readable output. References may be supplied as JSON
objects or as shorthand `ref_type:ref`.

## Authority Boundary

The store is BuilderOps operational infrastructure. Writing a BuilderOps record does not mutate
repo authority, product/runtime truth, GitHub Issues, docs, skills, ADRs, PRs, generated
projections, or runtime behavior.

Promotion remains explicit and separate. `PromotionIntent` records are staged material only until a
later promotion gateway and normal repo/GitHub authority gate act on them.

## Out Of Scope

This slice intentionally does not implement:

- multi-agent leases
- idempotency semantics beyond SQLite record identity
- automatic receipts for every create/update
- API or MCP exposure
- promotion gateway execution
- generated repo projections
- migrations from `docs/learning-log.md`, `docs/DOCS_INDEX.md`, or `docs/ROADMAP.md`
- product/runtime authority changes
