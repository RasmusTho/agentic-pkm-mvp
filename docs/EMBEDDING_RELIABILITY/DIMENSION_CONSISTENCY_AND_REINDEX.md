---
name: Dimension Consistency & Re-index Migration
description: Per-vector identity recording, mixed-identity detection in index doctor, reconcile/re-index migration, and the EMBEDDINGS.md fallback-rule update
task_id: EMBEDREL-06
source_anchor: docs/EMBEDDINGS.md :: Fallback rule
parent_capability: Embedding Reliability & Pluggable Provider
prerequisites: [EMBEDREL-05]
depends_on: [PROVIDER_FALLBACK_ORCHESTRATION.md]
can_parallelize_with: []
---

# Dimension Consistency & Re-index Migration

## Purpose

After a fallback-orchestrated ingest (EMBEDREL-05), the `store_vector_index` table may contain vectors produced by two different providers — for example, Ollama/nomic-embed-text for notes that ingested successfully and Gemini/text-embedding-004 for notes that fell back. Both produce 768-dimensional vectors, so no dimension guardrail fires, but the two providers occupy different vector spaces: cosine scores across them are meaningless. CTI-1 requires that at steady state the index contains exactly one `EmbeddingIdentity`; CTI-2 declares this fallback-mixed state reconcilable, not terminal.

This task ships the convergence mechanism: per-vector provider recording, loud mixed-identity detection in `index doctor`, and an idempotent `index reconcile` command that re-embeds fallback-written vectors under the current primary identity.

It also updates `docs/EMBEDDINGS.md` to relax the absolute "no fallback" rule to the disciplined-fallback posture the capability now ships, and documents the chosen Gemini model (text-embedding-004 @ 768) and the re-index path.

## What This Task Does

**(a) Per-vector provider recording.** Extend `store_vector_index` to store `provider` as a distinct per-row TEXT column alongside the existing `model` and `dim` columns. The current schema stores `model` per-row but not `provider` distinctly — provider lives only in the index-level `vector_index_meta` row. After a fallback, the meta identity stays as the primary identity, but individual rows written under the fallback provider have no per-row marker. Adding a `provider` column makes the fallback boundary visible at the row level and is the prerequisite for mixed-identity detection.

Concretely:
- Add column: `ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS provider TEXT`
- Populate on upsert: extract `provider` from the `EmbeddingIdentity` passed to `PgVectorIndex.upsert()` (`app/stores/pg.py` line 307–354) and write it to the new column. The `identity` parameter already carries provider; the column just needs to be persisted.
- Backfill at migration time: for existing rows where `provider IS NULL`, set `provider = (SELECT identity_json->>'provider' FROM vector_index_meta WHERE id = 1)` — i.e., assume pre-migration rows belong to the index-level identity. This is safe: the EMBEDREL-05 schema is not yet in production, so the first upsert after migration writes the correct provider.
- **Relax the index-level upsert guard for reconcilable fallback writes.** Today `PgVectorIndex.upsert()` calls `_ensure_index_identity(cur, resolved_identity, allow_create=True)` (`app/stores/pg.py:332`), which raises `RuntimeError("Embedding identity mismatch …")` (pg.py:149) whenever the row's provider/model differs from the index-level `vector_index_meta` identity. This **blocks** EMBEDREL-05 from writing a Gemini-fallback vector into an Ollama-identity index. The guard must move from "every upsert must match the single index identity" to "the index has a stable **primary** identity (used for queries and `allow_create`), but a row may be written under a different **per-vector** identity when it is explicitly marked reconcilable (`reconcile=pending`)". Keep the **dim** check unconditional (a dim mismatch still fails — CTI-1); only the provider/model/normalize divergence is tolerated, and only for reconcilable fallback rows. This guard change is the shared prerequisite that makes EMBEDREL-05's fallback upsert succeed and EMBEDREL-06's reconcile observable; land it with the provider column.

**(b) Mixed-identity detection in `index doctor`.** Extend `app/index/doctor.py::diagnose_index()` (currently at `app/index/doctor.py`) to detect when more than one distinct `provider` value is present in `store_vector_index`. When detected:
- Append to `issues`: `"Mixed provider identities in index: {providers}. Run 'python -m app.cli index reconcile' to converge."` (This is CTI-2's loud surface.)
- Set `status = "error"` and `rebuild_required = True` with `rebuild_reason` pointing to the reconcile command, not a full rebuild. A full rebuild is correct but unnecessarily destructive when reconcile suffices.
- Add a `mixed_providers` key to the returned dict listing the distinct providers found.
- Extend `app/cli/index_doctor.py` to print the mixed-provider list in non-JSON output.

The existing dim-mismatch and identity-drift detection (`app/index/doctor.py` lines 79–104) remains unchanged. Mixed-provider detection is additive.

**(c) Reconcile / re-index migration.** Add an `index reconcile` subcommand to the existing `index` Click group (registered in `app/cli/index_rebuild.py`). The subcommand re-embeds any vector whose `provider` differs from the current primary identity's provider, under the primary identity, and upserts the result in place.

CLI signature:
```
python -m app.cli index reconcile [--backend pg|memory] [--dry-run] [--json] [--strict] [--max-retries N] [--failures-path PATH] [--limit N]
```

Behavior:
1. Resolve the current primary `EmbeddingIdentity` via `get_embedding_client(profile="default")`.
2. Query `store_vector_index WHERE provider != <primary_provider>` (or where `provider IS NULL` post-migration). These are the vectors requiring re-embedding.
3. For each such row: fetch the original text from `store_objects` by `object_id`, call `client.embed_text(text)`, upsert the new vector with the primary identity (overwriting the fallback vector). Failures are dead-lettered to a JSONL file (same pattern as `index rebuild`, reusing `_record_failure` from `app/cli/index_rebuild.py`).
4. Emit a JSON/text summary: `total_mismatched`, `reconciled`, `skipped`, `errors`.
5. On completion (or interrupt), the index is valid: reconciled rows have the primary identity, un-reconciled rows retain the fallback identity. The index is still mixed if any rows remain un-reconciled, but never corrupt. A subsequent `index doctor` run reports the remaining mismatch count accurately.

The subcommand must be idempotent: running reconcile a second time on an already-reconciled index is a no-op (no rows match `provider != primary_provider`).

**(d) Dimension-change migration.** When switching to a provider/model that changes dim or normalization (for example, Gemini `text-embedding-001` @ 3072), the `store_vector_index` table cannot be reconciled in place — the pgvector column type and dimension are fixed at schema creation time. The required path:

1. Update `EMBED_DIM`, `EMBED_MODEL`, `EMBED_NORMALIZE` and the steering docs.
2. Run `index doctor --strict` to confirm no vectors exist at the old dim (or that you intend to discard them).
3. Drop and recreate the vector index schema: `reset_vector_index(cur)` (already implemented in `app/stores/pg.py::reset_vector_index`) clears `store_vector_index` and `vector_index_meta`. For a pgvector column-type change, this must be followed by a schema migration that recreates the `embedding` column at the new type/operator class.
4. Run `index rebuild` under the new identity.
5. Run `index doctor --strict` to confirm all stored vectors match the new identity.

For the current capability scope (Ollama-primary + Gemini-fallback, both @ 768), this path is documented but not exercised — both providers are pinned to 768 by operator decision (EMBEDREL-01). Mixed dims between the two providers are forbidden by the existing `assert_embed_dim` guardrail (`app/embedding_config.py::assert_embed_dim`) and would fail the upsert before writing, so a dim-split index cannot occur during normal fallback operation.

The multi-vault / per-vault-dim scenario (where different vaults may be configured with different dims) is deferred to epic #2143. This task's migration path is the building block for that work.

**(e) Owner-doc update.** Update `docs/EMBEDDINGS.md :: Fallback rule` to reflect the disciplined-fallback posture this capability ships. The current text ("Embeddings do not allow generic provider fallback") is accurate for the pre-EMBEDREL world but contradicts the shipped behavior after EMBEDREL-05.

New fallback rule text (replace the existing "Fallback rule" section):

> **Fallback rule**
>
> Disciplined, dim-matched fallback is permitted as an availability bridge. The constraints are:
>
> - The fallback provider must be pinned to the **same dimension** as the primary (e.g., Gemini `text-embedding-004` @ 768 to match Ollama `nomic-embed-text` @ 768). A provider returning a different dim fails the upsert via `assert_embed_dim` — it never silently writes.
> - A fallback-written index is **mixed-identity** (vectors from different providers occupy different vector spaces). This state is surfaced loudly by `index doctor` as an error and is reconcilable — not terminal.
> - Once the primary provider recovers, run `index reconcile` to re-embed fallback-written vectors under the primary identity, converging the index back to one identity (CTI-1).
> - Identity-changing fallback that changes dim or normalization is still forbidden and will be rejected at upsert time.
>
> See `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` for the egress decision (chosen posture: Ollama-primary + Gemini auto-fallback), and `docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md` for the re-index migration path.
>
> **Chosen Gemini model:** `text-embedding-004` @ dim 768 (dimension-matched to `nomic-embed-text`). Free tier; key supplied via `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
>
> **Re-index path:** see *Rebuild playbook* below and the *Reconcile* path in `docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md`.

Also update the `docs/EMBEDDINGS.md :: Configuration` section to add Gemini as a supported `LLM_PROVIDER` value alongside `ollama` and `mock`.

## Concretely

**Scenario A — after a fallback ingest:**

1. Operator runs `index rebuild` while Ollama is down. EMBEDREL-05 routes 10 of 63 notes to Gemini. The `store_vector_index` table now has 53 rows with `provider='ollama'` and 10 rows with `provider='gemini'`.
2. Operator runs `index doctor`. Doctor queries `SELECT DISTINCT provider FROM store_vector_index` and finds `{'ollama', 'gemini'}`. It appends to `issues`: `"Mixed provider identities in index: ['gemini', 'ollama']. Run 'python -m app.cli index reconcile' to converge."` Doctor exits with code 2 (or 0 with warning if `--no-strict`).
3. Ollama recovers. Operator runs `index reconcile`. The command finds 10 rows with `provider='gemini'`, re-embeds the 10 notes via the Ollama primary identity, upserts the results. Summary: `total_mismatched=10 reconciled=10 errors=0`.
4. Operator runs `index doctor` again. `SELECT DISTINCT provider FROM store_vector_index` returns `{'ollama'}`. Doctor reports `status=ok`.

**Scenario B — dim-change rebuild (switching to a hypothetical gemini-embedding-001 @ 3072):**

1. Operator sets `EMBED_DIM=3072`, `EMBED_MODEL=gemini-embedding-001`, updates steering docs.
2. Operator runs `reset_vector_index` (via admin tooling or a future `index reset` command). This clears `store_vector_index` and `vector_index_meta`.
3. Operator applies a schema migration to recreate the `embedding` column as `DOUBLE PRECISION[3072]` (or drops the pgvector extension constraint and recreates it).
4. Operator runs `index rebuild`. All 63 notes are embedded under the new identity.
5. Operator runs `index doctor --strict`. Confirms no mixed dims, no mixed providers, stored identity matches runtime identity.

## Why This Matters

Without per-vector provider recording, a fallback-written index is invisible: `index doctor` reports the index-level `vector_index_meta` identity (primary) as matching the runtime identity, masking the 10 fallback-identity rows. Retrieval over a silently-mixed index returns degraded results with no signal to the operator.

CTI-2 says fallback is non-terminal and reconcilable. This task is the mechanism that makes that claim true: doctor surfaces the drift, reconcile closes it, and the owner-doc no longer contradicts the shipped behavior.

## Acceptance Criteria

- [ ] **Per-vector provider column.** `store_vector_index` has a `provider` TEXT column. Every upsert via `PgVectorIndex.upsert()` writes the provider from the passed `EmbeddingIdentity`. Backfill migration sets `provider` from `vector_index_meta` for pre-existing rows.
  - Verify: `tests/stores/test_pg_vector_index.py::test_upsert_records_provider_column` — assert the row has the correct `provider` after upsert with an explicit identity.
- [ ] **Mixed-identity detection.** After inserting two rows with different providers, `diagnose_index()` returns `status='error'`, `issues` contains the mixed-provider message, and `mixed_providers` lists both providers.
  - Verify: `tests/indexer/test_mixed_identity_detection.py::test_diagnose_detects_mixed_providers`
- [ ] **Reconcile command exists and re-embeds fallback rows.** `index reconcile` finds rows where `provider != primary_provider`, re-embeds them, and upserts under the primary identity. After reconcile, `diagnose_index()` returns `status='ok'` with no mixed-provider issue.
  - Verify: `tests/cli/test_index_reconcile.py::test_reconcile_converges_mixed_index`
- [ ] **Reconcile is idempotent.** Running `index reconcile` twice on a single-identity index produces the same outcome both times: `total_mismatched=0`, `reconciled=0`, no errors.
  - Verify: `tests/cli/test_index_reconcile.py::test_reconcile_idempotent_on_clean_index`
- [ ] **Reconcile is resumable / non-corrupting on interrupt.** Interrupting reconcile mid-run leaves the index in a valid state: reconciled rows have the primary identity, un-reconciled rows retain the fallback identity. The index is still mixed but never corrupt (no partial writes, no missing rows). A subsequent `index doctor` accurately reports the remaining mismatch count.
  - Verify: `tests/cli/test_index_reconcile.py::test_reconcile_partial_run_leaves_valid_index` — simulate a failure after row N; assert rows 0..N-1 have primary identity, rows N..end have fallback identity, no rows are missing or corrupt.
- [ ] **Dim-change rebuild path documented.** `docs/EMBEDDINGS.md :: Rebuild playbook` and the *Dimension-change migration* section of this file describe the full path for switching to a different dim/provider without data corruption.
  - Verify: doc anchor — `docs/EMBEDDINGS.md :: Rebuild playbook` references the dim-change scenario and the `reset_vector_index` + `index rebuild` sequence.
- [ ] **Owner-doc fallback rule updated.** `docs/EMBEDDINGS.md :: Fallback rule` no longer forbids disciplined dim-matched fallback; it permits it under the stated constraints, points to `OPERATOR_EGRESS_DECISION.md` and this task, and documents `text-embedding-004 @ 768`.
  - Verify: doc anchor — `docs/EMBEDDINGS.md :: Fallback rule` contains "Disciplined, dim-matched fallback is permitted" and references this task.
- [ ] **`index doctor` CLI extended.** In non-JSON mode, `index doctor` prints the mixed-providers list when detected. In JSON mode, the response includes `mixed_providers`.
  - Verify: `tests/cli/test_index_doctor_mixed.py::test_doctor_cli_prints_mixed_providers`

## How to Verify (Pre-Merge)

1. Run the new test files:
   ```
   pytest tests/stores/test_pg_vector_index.py::test_upsert_records_provider_column
   pytest tests/indexer/test_mixed_identity_detection.py
   pytest tests/cli/test_index_reconcile.py
   pytest tests/cli/test_index_doctor_mixed.py
   ```
2. Confirm `docs/EMBEDDINGS.md :: Fallback rule` reads consistently with the disciplined-fallback posture (no contradictions with EMBEDREL-05 behavior).
3. Confirm `docs/EMBEDDINGS.md :: Configuration` lists `gemini` as a supported `LLM_PROVIDER` value.
4. Run `index doctor --strict` against a test pg backend with manually-inserted mixed-provider rows; confirm exit code 2 and the mixed-provider message.
5. Run `index reconcile --dry-run` and confirm the count matches the manually-inserted fallback rows without writing.
6. Run `index reconcile` and confirm doctor subsequently reports `status=ok`.

## Out of Scope

- Implementing the provider fallback orchestration itself (EMBEDREL-05, `PROVIDER_FALLBACK_ORCHESTRATION.md`).
- Per-vault dim configuration or multi-vault identity isolation (epic #2143).
- pgvector extension setup or operator-class configuration — this task uses the existing `DOUBLE PRECISION[]` column; pgvector extension migration is deferred.
- Automatic scheduled reconcile (a future operational concern; this task provides the CLI primitive).
- Fallback for a provider that returns a different dim — `assert_embed_dim` already guards this at upsert time; this task adds no new logic there.
- Memory backend mixed-identity detection — `MemoryVectorIndex` (`app/index/vector_index_memory.py`) has no per-row provider column and is used only in tests/dev. The new provider column and reconcile command apply to `PgVectorIndex` only.

## Restart / Durability Posture

**Idempotency.** Reconcile identifies candidate rows by `provider != <primary_provider>`. After a successful upsert for a row, its provider is updated to the primary provider. On re-run, that row no longer matches the query and is skipped. Running reconcile on a fully-converged index is a no-op.

**Resumability.** Reconcile processes rows one at a time (same pattern as `index rebuild`). If interrupted (SIGINT, crash, container restart), rows processed before the interrupt have already been upserted with the primary provider — they will not be re-processed on the next run. Rows not yet processed retain their fallback identity. The index is mixed but valid: no row is in a partial state, because the upsert is an atomic `INSERT ... ON CONFLICT DO UPDATE`. The `_record_failure` pattern (reused from `app/cli/index_rebuild.py`) dead-letters failed rows to a JSONL file; these can be retried by re-running reconcile.

**No corruption invariant.** A row is never deleted during reconcile — only upserted. If the re-embed call fails, the original fallback vector is retained. The index may be left mixed, but it is never missing a vector it previously had. This is the weakest acceptable outcome: degraded retrieval quality for the failed rows, not a missing-vector crash.

## Related Docs

- Owner doc (normative embedding spec): `docs/EMBEDDINGS.md` — this task's primary write target (fallback rule + rebuild playbook + Gemini model doc)
- Capability overview: `docs/EMBEDDING_RELIABILITY/README.md`
- Egress decision: `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md`
- Fallback orchestration: `docs/EMBEDDING_RELIABILITY/PROVIDER_FALLBACK_ORCHESTRATION.md` (EMBEDREL-05, prerequisite)
- Per-row schema: `app/stores/pg.py` — `PgVectorIndex.upsert()` (line 307), `_ensure_tables()` (line 37), `inspect_pg_index_state()` (line 555)
- Doctor logic: `app/index/doctor.py` — `diagnose_index()` (line 51)
- Doctor CLI: `app/cli/index_doctor.py`
- Rebuild CLI: `app/cli/index_rebuild.py` — `rebuild` command + `_record_failure` helper (line 150)
- Embedding identity: `app/components/embeddings.py` — `EmbeddingIdentity`, `get_embedding_identity()`
- Dim guardrail: `app/embedding_config.py` — `assert_embed_dim()` (line 36)
- Multi-vault / per-vault dims: epic #2143
- Events: `docs/EVENTS.md` (`index.embedding.created`, `index.embedding.failed`)

## Related GitHub Issues

Create one or two bounded slice issues for this task:

- **Option A (one issue):** a single issue covering (a) provider column migration + (b) doctor extension + (c) reconcile command + (e) owner-doc update. This fits one agent / one PR if the agent is comfortable with both migration code and CLI authoring. Recommended if the PR reviewers can absorb all three changes in one review.
- **Option B (two issues):** split into (i) provider column + mixed-identity doctor + owner-doc update (lighter, mostly schema + test) and (ii) `index reconcile` command + idempotency/resumability tests (heavier, CLI + migration correctness). This reduces PR scope if index migration correctness is reviewed separately.

Either way, label `lane:core-runtime` (data migration touches the production schema) and note the EMBEDREL-05 dependency.

TCD: Opus / high effort — data migration + index integrity + owner-doc change; migration correctness has high defect cost. A partial or non-idempotent reconcile that drops or duplicates vectors corrupts retrieval quality silently. Tests must cover the partial-run / resume path explicitly (`test_reconcile_partial_run_leaves_valid_index`). Owner-doc update must be bundled in the same PR as the implementation (not a follow-up) per project owner-doc bundling policy.
