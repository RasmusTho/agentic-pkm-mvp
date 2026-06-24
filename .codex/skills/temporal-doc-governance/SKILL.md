---
name: temporal-doc-governance
description: "Audit and update time-sensitive docs such as STATUS, ROADMAP, rollout docs, and other temporal control surfaces so they stay aligned with delivered reality."
---

# Temporal Doc Governance

Use this skill when the task is to audit or update documentation with a strong temporal component.
This is a periodic maintenance pass, not a hot-path delivery step.

Typical targets:

- `docs/STATUS.md`
- `docs/ROADMAP.md` for strategic sequencing authority, not daily execution movement
- `docs/DOCS_INDEX.md` for stable doc roles and reading order, not freshness queue state
- rollout, track, runbook, and current-state docs
- any doc that can drift because code, issues, runtime posture, or operational state changed

Use it to repair temporal drift, not to add one-off backlog intake or implementation chatter.

## BuilderOps routing

Write BuilderOps records instead of editing repo docs when the finding is operational state:

- docs freshness posture, stale reasons, evidence, or next review owner -> `DocsFreshnessRecord`
- roadmap execution movement, active issues, blockers, shipped refs, or next execution decision -> `RoadmapExecutionItem`
- a proposed doc/index/roadmap writeback -> `PromotionIntent`
- completion, discard, supersession, or projection evidence -> `BuilderOpsReceipt`

Generated BuilderOps projections are review views, not authority. `docs/DOCS_INDEX.md` remains the
stable document role/routing authority, and `docs/ROADMAP.md` remains the strategic sequencing
authority. Do not rewrite either file solely to capture high-churn operational state.

## BuilderOps projection regeneration — store selection and fail-loud rule

When this audit runs a `generate-projections` command to regenerate checked-in projections under
`docs/generated/builderops/`, it **must** select the intended BuilderOps store explicitly before
writing. The default store (`runtime/builderops/builderops.sqlite3`) is gitignored, machine-local,
and not shared across devices or worktrees; regenerating from a partial or wrong store will silently
drop records.

**Required:** set `BUILDEROPS_DB_PATH`, `BUILDEROPS_STATE_DIR`, or `--db-path` to the canonical
store before invoking `generate-projections`. Use the wrapper:

```bash
BUILDEROPS_DB_PATH=/path/to/intended/builderops.sqlite3 \
  scripts/builderops_cli.sh builderops generate-projections \
  --output-dir docs/generated/builderops
```

**Fail-loud requirement:** if the selected store has fewer records than the existing checked-in
projection, the generator's count-based shrink guard (`_guard_against_incomplete_projection_store`
in `app/builderops/projections.py`) fails before writing. The guard compares record *counts*, not
record IDs — a wrong store with an equal or greater count can still overwrite the projection while
dropping specific record IDs, so selecting the intended store explicitly (above) is the primary
safeguard, not the count guard. Do not suppress the failure or work around it by hand-editing the
generated files; fix the store selection instead.

A regen diff is expected — the backing store is non-reproducible over time. Treat missing records
in the regenerated output as a store-selection signal, not data loss. See
`docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md :: Non-Authoritative and Non-Reproducible` and
`docs/builderops/BUILDEROPS_VAULT_STORE.md :: Store Location`.

## First context to load

- Read `AGENTS.md` first.
- Read `docs/DOCS_INDEX.md` to identify the owner doc and active role.
- Read `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` for semantic posture.
- Read `docs/templates/DOC_TEMPLATE.md` for required metadata fields.
- If the task is docs-only, follow `.codex/skills/docs-authoring/SKILL.md`.
- If backlog or GitHub state is involved, also use `.codex/skills/backlog-reconciliation-drift-audit/SKILL.md`.

## Audit model

Treat temporal drift as a mismatch between a document's current claims and one or more of:

- shipped code
- runtime/operator surfaces
- open Issues / Project state / merged PRs
- other owning SoT docs
- elapsed time since the last explicit verification

For each target doc, classify:

- `temporally stable`
- `review due`
- `likely stale`
- `historical only`

## Required metadata posture

Time-sensitive docs should carry or inherit these fields near the top:

- `Temporal class`
- `Review cadence`
- `Source of truth`
- `Last reviewed`
- `Last verified against`

Use these classes:

- `timeless` — concept contracts and low-drift principles
- `operational` — current runtime/health/startup/current-state docs
- `strategic` — roadmap and sequencing docs
- `snapshot` — point-in-time reports, delivery snapshots, or status captures

## Update rules

- Prefer correcting current-state claims over rewriting large sections.
- Keep `ROADMAP` forward-looking; move delivered truth into the owner/current-state doc and move
  daily execution movement into `RoadmapExecutionItem`.
- Keep `STATUS` explicitly operational; remove roadmap-like language when reality is already shipped or no longer active.
- Keep `DOCS_INDEX` focused on stable document roles, authority, and reading order; move review
  queue/freshness state into `DocsFreshnessRecord`.
- Batch repeated temporal corrections where the same claim appears across multiple docs, and avoid splitting one drift class into many micro-edits unless the surfaces truly diverge.
- If a claim cannot be verified, mark the uncertainty instead of presenting it as current truth.
- Update `Last reviewed` whenever the doc is intentionally checked.
- Update `Last verified against` with the most local concrete verification anchor available.
- If a document is no longer an active truth surface, reclassify it as `Historical` or `Legacy`.

## Minimal output format

When auditing, report:

1. Documents reviewed
2. Drift findings
3. Proposed updates
4. Residual uncertainty

When updating, also report:

1. Which claims were rewritten
2. Which metadata fields were refreshed
3. Which items remain intentionally unverified

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.
