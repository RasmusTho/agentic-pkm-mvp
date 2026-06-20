State: Generated projection support implemented for #1505 and extended for the #1507 docs-freshness split and #1508 roadmap-execution split. BuilderOps projections render repo-readable Markdown views over BuilderOps Vault records; they are not source-of-truth records and are not published automatically by CI.
Doc role: BuilderOps generated projection reference
Authority: Documents the #1505 projection generator and output contract. Object semantics remain owned by `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`; store mechanics remain owned by `docs/builderops/BUILDEROPS_VAULT_STORE.md`; authority boundaries remain owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: app/builderops/projections.py, BuilderOps Vault records
Last reviewed: 2026-06-01
Last verified against: issues #1505/#1507/#1508

# BuilderOps Vault Projections

## Scope

#1505 adds generated Markdown projections over the BuilderOps Vault store.

Initial projection types:

- `learning-summary`
- `docs-freshness`
- `roadmap-execution`
- `promotion-queue`

Each projection is a generated view for repo readers. It does not replace BuilderOps Vault as the
source for operational state, does not become product/runtime truth, and does not silently promote
BuilderOps material into repo or GitHub authority.

## Metadata Contract

Every generated projection starts with:

```text
State: Generated projection
Authority: non-authoritative BuilderOps Vault projection
Source of truth: BuilderOps Vault
Generated at: <UTC timestamp>
Projection type: <projection type>
Do not edit: regenerate from BuilderOps Vault records.
```

The generated body includes record IDs, lifecycle state, promotion status, authority class,
projection-specific fields, `source_refs`, and `receipt_refs` when present.

## CLI

Generate all projections:

```bash
python -m app.cli builderops generate-projections \
  --output-dir docs/generated/builderops
```

Generate one projection:

```bash
python -m app.cli builderops generate-projections \
  --type learning-summary \
  --output-dir docs/generated/builderops
```

The command writes only the generated projection files in the requested output directory. It does
not migrate `docs/learning-log.md`, `docs/DOCS_INDEX.md`, or `docs/ROADMAP.md`, and it does not
publish projections automatically in CI.

When the target output directory already contains generated BuilderOps projections with records, the
generator fails before writing if the selected store would shrink those projections. This catches
automation worktrees that accidentally point at an empty or incomplete local BuilderOps DB. Select
the intended store with `BUILDEROPS_DB_PATH`, `BUILDEROPS_STATE_DIR`, or `--db-path`, and prefer
`scripts/builderops_cli.sh builderops generate-projections --output-dir docs/generated/builderops`
from the repo root or worktree so the supported virtualenv and store selection are used. Generated
projection files remain non-authoritative views over BuilderOps Vault records; do not hand-edit them
to repair a failed regeneration.

## Default Output Names

| Projection type | BuilderOps object type | Filename |
| --- | --- | --- |
| `learning-summary` | `LearningSignal` | `learning-summary.md` |
| `docs-freshness` | `DocsFreshnessRecord` | `docs-freshness.md` |
| `roadmap-execution` | `RoadmapExecutionItem` | `roadmap-execution.md` |
| `promotion-queue` | `PromotionIntent` | `promotion-queue.md` |

The `docs-freshness` projection renders high-churn docs review state from `DocsFreshnessRecord`
objects, including owner, review cadence, freshness posture, `drift_status`, `last_reviewed_at`,
`last_verified_against`, `last_verified_at`, `next_review_due_at`, stale reasons, freshness
evidence refs, and next review owner when those fields are present. This projection is the
repo-readable freshness queue view after #1507; it does not replace `docs/DOCS_INDEX.md` as the
stable document role/routing authority.

The `roadmap-execution` projection renders high-churn roadmap movement state from
`RoadmapExecutionItem` objects, including roadmap ref, theme, capability, execution state, status,
owner, active issues, blockers, last movement, next decision, and shipped refs when those fields are
present. This projection is the repo-readable execution movement view after #1508; it does not
replace `docs/ROADMAP.md` as the strategic sequencing authority.

## Authority Boundary

Generated projections are non-authoritative exports from BuilderOps Vault. A human or agent may use
them for reading, review, and planning, but durable operational state remains in BuilderOps Vault.

Editing a generated projection by hand does not update BuilderOps Vault and must not be treated as
an authority transfer. Repo docs, ADRs, skills, GitHub Issues, PRs, and product/runtime truth still
change only through their explicit owner workflows and promotion gates.

## Out Of Scope

This slice intentionally does not implement:

- migration of existing docs or learning-log content
- automatic CI publication of projections
- product/runtime authority changes
- replacement of canonical product docs
- API/MCP exposure for projection generation
