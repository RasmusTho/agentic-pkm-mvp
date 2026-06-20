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

After a fallback-orchestrated ingest (EMBEDREL-05), the `store_vector_index` table may contain vectors produced by two different providers — for example, Ollama/nomic-embed-text for notes that ingested successfully and Gemini/gemini-embedding-001 (with `output_dimensionality=768`) for notes that fell back. Both produce 768-dimensional vectors, so no dimension guardrail fires, but the two providers occupy different vector spaces: cosine scores across them are meaningless. CTI-1 requires that at steady state the index contains exactly one `EmbeddingIdentity`; CTI-2 declares this fallback-mixed state reconcilable, not terminal.

This task ships the convergence mechanism: per-vector provider recording, loud mixed-identity detection in `index doctor`, and an idempotent `index reconcile` command that re-embeds fallback-written vectors under the current primary identity.

It also updates `docs/EMBEDDINGS.md` to relax the absolute "no fallback" rule to the disciplined-fallback posture the capability now ships, and documents the chosen Gemini model (`gemini-embedding-001` with `output_dimensionality=768`, L2-renormalized) and the re-index path.

## What This Task Does

**(a) Per-vector full-identity recording.** Extend `store_vector_index` to store the full `EmbeddingIdentity` per row: `provider`, `model`, `normalize` as distinct columns alongside the existing `dim` column (CTI-1 keys on the full tuple `(provider, model, dim, normalize)`, not provider alone). The current schema stores `model` per-row but not `provider` or `normalize` distinctly — provider and normalize live only in the index-level `vector_index_meta` row. After a fallback, the meta identity stays as the primary identity, but individual rows written under the fallback identity have no per-row marker. Adding `provider` and `normalize` columns (alongside the already-present `model` and `dim`) makes the full fallback identity visible at the row level and is the prerequisite for mixed-identity detection.

Concretely:
- Add columns: `ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS provider TEXT`, `ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS normalize BOOLEAN`
- Populate on upsert: extract `provider`, `model`, `dim`, and `normalize` from the `EmbeddingIdentity` passed to `PgVectorIndex.upsert()` (`app/stores/pg.py` line 307–354) and write all four fields to the row. The `identity` parameter already carries all of these; the columns just need to be persisted.
- Backfill at migration time: for existing rows where `provider IS NULL` or `normalize IS NULL`, set them from `vector_index_meta` (the index-level identity): `provider = (SELECT identity_json->>'provider' FROM vector_index_meta WHERE id = 1)`, `normalize = (SELECT (identity_json->>'normalize')::boolean FROM vector_index_meta WHERE id = 1)`. This is safe: the EMBEDREL-05 schema is not yet in production, so the first upsert after migration writes the correct full identity.
- **Relax the index-level upsert guard for reconcilable fallback writes.** Today `PgVectorIndex.upsert()` calls `_ensure_index_identity(cur, resolved_identity, allow_create=True)` (`app/stores/pg.py:332`), which raises `RuntimeError("Embedding identity mismatch …")` (pg.py:149) whenever the row's provider/model differs from the index-level `vector_index_meta` identity. This **blocks** EMBEDREL-05 from writing a Gemini-fallback vector into an Ollama-identity index. The guard must move from "every upsert must match the single index identity" to "the index has a stable **primary** identity (used for queries and `allow_create`), but a row may be written under a different **per-vector** identity when it is explicitly marked reconcilable (`reconcile=pending`)". Keep the **dim** check unconditional (a dim mismatch still fails — CTI-1); only the provider/model/normalize divergence is tolerated, and only for reconcilable fallback rows. This guard change is the shared prerequisite that makes EMBEDREL-05's fallback upsert succeed and EMBEDREL-06's reconcile observable; land it with the new columns.

**(b) Mixed-identity detection in `index doctor`.** Extend `app/index/doctor.py::diagnose_index()` (currently at `app/index/doctor.py`) to detect when more than one distinct `(provider, model, dim, normalize)` tuple is present in `store_vector_index` (per CTI-1). Keying on provider alone is insufficient: an Ollama model swap at the same dim (e.g. `nomic-embed-text` → `mxbai-embed-large`, both at 768) or a Gemini model migration (e.g. `gemini-embedding-001` → `gemini-embedding-2`) would share a provider but differ in model, producing a semantically mixed index that the provider-only check would miss. When more than one distinct full-identity tuple is detected:
- Append to `issues`: `"Mixed embedding identities in index: {identities}. Run 'python -m app.cli index reconcile' to converge."` where `{identities}` is a list of `(provider, model, dim, normalize)` tuples. (This is CTI-2's loud surface.)
- Set `status = "error"` and `rebuild_required = True` with `rebuild_reason` pointing to the reconcile command, not a full rebuild. A full rebuild is correct but unnecessarily destructive when reconcile suffices.
- Add a `mixed_identities` key to the returned dict listing the distinct `(provider, model, dim, normalize)` tuples found.
- Extend `app/cli/index_doctor.py` to print the mixed-identity list in non-JSON output.

The existing dim-mismatch and identity-drift detection (`app/index/doctor.py` lines 79–104) remains unchanged. Mixed-identity detection is additive.

**Implementation note:** query `SELECT provider, model, dim, normalize, COUNT(*) FROM store_vector_index GROUP BY provider, model, dim, normalize` and flag when the result set has more than one row.

**(c) Reconcile / re-index migration.** Add an `index reconcile` subcommand to the existing `index` Click group (registered in `app/cli/index_rebuild.py`). The subcommand re-embeds any vector whose `provider` differs from the current primary identity's provider, under the primary identity, and upserts the result in place.

CLI signature:
```
python -m app.cli index reconcile [--backend pg|memory] [--dry-run] [--json] [--strict] [--max-retries N] [--failures-path PATH] [--limit N]
```

Behavior:
1. Resolve the current primary `EmbeddingIdentity` via `get_embedding_client(profile="default")`. This yields the primary `(provider, model, dim, normalize)` tuple.
2. Query `store_vector_index WHERE (provider, model, dim, normalize) != (<primary_provider>, <primary_model>, <primary_dim>, <primary_normalize>)` (or where `provider IS NULL` post-migration). These are all vectors whose full identity differs from the primary — regardless of whether they share the provider name. An Ollama model swap (`nomic-embed-text` → `mxbai-embed-large` at the same dim) or a Gemini model migration (`gemini-embedding-001` → `gemini-embedding-2`) is also caught here.
3. For each such row: fetch the original text from `store_objects` by `object_id`, call `client.embed_text(text)`, upsert the new vector with the primary identity (overwriting the fallback vector). Failures are dead-lettered to a JSONL file (same pattern as `index rebuild`, reusing `_record_failure` from `app/cli/index_rebuild.py`).
4. Emit a JSON/text summary: `total_mismatched`, `reconciled`, `skipped`, `errors`.
5. On completion (or interrupt), the index is valid: reconciled rows have the primary identity, un-reconciled rows retain the fallback identity. The index is still mixed if any rows remain un-reconciled, but never corrupt. A subsequent `index doctor` run reports the remaining mismatch count accurately.

The subcommand must be idempotent: running reconcile a second time on an already-reconciled index is a no-op (no rows match the non-primary-identity predicate).

**(d) Dimension-change migration.** When switching to a provider/model that changes dim or normalization (for example, switching from `gemini-embedding-001` with `output_dimensionality=768` to the model's native 3072 default dim, or switching to `gemini-embedding-2` at 3072), the `store_vector_index` table cannot be reconciled in place — the pgvector column type and dimension are fixed at schema creation time. Note: `gemini-embedding-001` and `gemini-embedding-2` both default to 3072 dims; this capability pins `gemini-embedding-001` at 768 via `output_dimensionality`. Switching to the full 3072 default (or to `gemini-embedding-2` at 3072) is the dim-change re-index path. The required path:

1. Update `EMBED_DIM`, `EMBED_MODEL`, `EMBED_NORMALIZE` and the steering docs.
2. Run `index doctor --strict` to confirm no vectors exist at the old dim (or that you intend to discard them).
3. Drop and recreate the vector index schema: `reset_vector_index(cur)` (already implemented in `app/stores/pg.py::reset_vector_index`) clears `store_vector_index` and `vector_index_meta`. For a pgvector column-type change, this must be followed by a schema migration that recreates the `embedding` column at the new type/operator class.
4. Run `index rebuild` under the new identity.
5. Run `index doctor --strict` to confirm all stored vectors match the new identity.

For the current capability scope (Ollama-primary + Gemini-fallback, both @ 768), this path is documented but not exercised — both providers are pinned to 768 by operator decision (EMBEDREL-01): Ollama via `EMBED_DIM=768`, Gemini via `output_dimensionality=768` in the request. Mixed dims between the two providers are forbidden by the existing `assert_embed_dim` guardrail (`app/embedding_config.py::assert_embed_dim`) and would fail the upsert before writing, so a dim-split index cannot occur during normal fallback operation.

The multi-vault / per-vault-dim scenario (where different vaults may be configured with different dims) is deferred to epic #2143. This task's migration path is the building block for that work.

**(e) Owner-doc update.** Update `docs/EMBEDDINGS.md :: Fallback rule` to reflect the disciplined-fallback posture this capability ships. The current text ("Embeddings do not allow generic provider fallback") is accurate for the pre-EMBEDREL world but contradicts the shipped behavior after EMBEDREL-05.

New fallback rule text (replace the existing "Fallback rule" section):

> **Fallback rule**
>
> Disciplined, dim-matched fallback is permitted as an availability bridge. The constraints are:
>
> - The fallback provider must be pinned to the **same dimension** as the primary (e.g., Gemini `gemini-embedding-001` with `output_dimensionality=768`, L2-renormalized, to match Ollama `nomic-embed-text` @ 768). A provider returning a different dim fails the upsert via `assert_embed_dim` — it never silently writes.
> - A fallback-written index is **mixed-identity** (vectors from different providers occupy different vector spaces). This state is surfaced loudly by `index doctor` as an error and is reconcilable — not terminal.
> - Once the primary provider recovers, run `index reconcile` to re-embed fallback-written vectors under the primary identity, converging the index back to one identity (CTI-1).
> - Identity-changing fallback that changes dim or normalization is still forbidden and will be rejected at upsert time.
>
> See `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` for the egress decision (chosen posture: Ollama-primary + Gemini auto-fallback), and `docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md` for the re-index migration path.
>
> **Chosen Gemini model:** `gemini-embedding-001` with `output_dimensionality=768`, L2-renormalized (dimension-matched to `nomic-embed-text`). Free tier; key supplied via `GEMINI_API_KEY` or `GOOGLE_API_KEY`. (`text-embedding-004` was retired January 14, 2026; `gemini-embedding-001` is the active stable model.)
>
> **Re-index path:** see *Rebuild playbook* below and the *Reconcile* path in `docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md`.

Also update the `docs/EMBEDDINGS.md :: Configuration` section to add Gemini as a supported `LLM_PROVIDER` value alongside `ollama` and `mock`.

## Concretely

**Scenario A — after a fallback ingest:**

1. Operator runs `index rebuild` while Ollama is down. EMBEDREL-05 routes 10 of 63 notes to Gemini. The `store_vector_index` table now has 53 rows with `provider='ollama', model='nomic-embed-text', dim=768, normalize=True` and 10 rows with `provider='gemini', model='gemini-embedding-001', dim=768, normalize=True`.
2. Operator runs `index doctor`. Doctor queries the distinct `(provider, model, dim, normalize)` tuples in `store_vector_index` and finds two: `(ollama, nomic-embed-text, 768, True)` and `(gemini, gemini-embedding-001, 768, True)`. It appends to `issues`: `"Mixed embedding identities in index: [('gemini','gemini-embedding-001',768,True), ('ollama','nomic-embed-text',768,True)]. Run 'python -m app.cli index reconcile' to converge."` Doctor exits with code 2 (or 0 with warning if `--no-strict`).
3. Ollama recovers. Operator runs `index reconcile`. The command finds 10 rows with `provider='gemini'`, re-embeds the 10 notes via the Ollama primary identity, upserts the results. Summary: `total_mismatched=10 reconciled=10 errors=0`.
4. Operator runs `index doctor` again. `SELECT DISTINCT provider FROM store_vector_index` returns `{'ollama'}`. Doctor reports `status=ok`.

**Scenario B — dim-change rebuild (switching from `gemini-embedding-001` at `output_dimensionality=768` to the model's native 3072 default, or to `gemini-embedding-2` at 3072):**

1. Operator sets `EMBED_DIM=3072`, `EMBED_MODEL=gemini-embedding-001` (removing the `output_dimensionality=768` override, or switches to `gemini-embedding-2`), updates steering docs.
2. Operator runs `reset_vector_index` (via admin tooling or a future `index reset` command). This clears `store_vector_index` and `vector_index_meta`.
3. Operator applies a schema migration to recreate the `embedding` column as `DOUBLE PRECISION[3072]` (or drops the pgvector extension constraint and recreates it).
4. Operator runs `index rebuild`. All 63 notes are embedded under the new identity.
5. Operator runs `index doctor --strict`. Confirms no mixed dims, no mixed providers, stored identity matches runtime identity.

## Why This Matters

Without per-vector provider recording, a fallback-written index is invisible: `index doctor` reports the index-level `vector_index_meta` identity (primary) as matching the runtime identity, masking the 10 fallback-identity rows. Retrieval over a silently-mixed index returns degraded results with no signal to the operator.

CTI-2 says fallback is non-terminal and reconcilable. This task is the mechanism that makes that claim true: doctor surfaces the drift, reconcile closes it, and the owner-doc no longer contradicts the shipped behavior.

## Acceptance Criteria

- [ ] **Per-vector full-identity columns.** `store_vector_index` has `provider` TEXT and `normalize` BOOLEAN columns alongside the existing `model` and `dim` columns. Every upsert via `PgVectorIndex.upsert()` writes all four fields from the passed `EmbeddingIdentity`. Backfill migration sets `provider` and `normalize` from `vector_index_meta` for pre-existing rows.
  - Verify: `tests/stores/test_pg_vector_index.py::test_upsert_records_full_identity_columns` — assert the row has the correct `provider`, `model`, `dim`, and `normalize` after upsert with an explicit identity.
- [ ] **Mixed-identity detection — full tuple.** After inserting two rows with the same provider but different models (e.g. `provider='ollama', model='nomic-embed-text'` and `provider='ollama', model='mxbai-embed-large'`), `diagnose_index()` returns `status='error'`, `issues` contains the mixed-identity message, and `mixed_identities` lists both `(provider, model, dim, normalize)` tuples. Likewise for two rows with different providers (e.g. ollama + gemini). Provider-only matching is insufficient.
  - Verify: `tests/indexer/test_mixed_identity_detection.py::test_diagnose_detects_mixed_full_identities` — tests both same-provider-different-model and different-provider cases
- [ ] **Reconcile command exists and re-embeds non-primary-identity rows.** `index reconcile` finds rows whose full `(provider, model, dim, normalize)` differs from the primary identity, re-embeds them, and upserts under the primary identity. After reconcile, `diagnose_index()` returns `status='ok'` with no mixed-identity issue.
  - Verify: `tests/cli/test_index_reconcile.py::test_reconcile_converges_mixed_index`
- [ ] **Reconcile is idempotent.** Running `index reconcile` twice on a single-identity index produces the same outcome both times: `total_mismatched=0`, `reconciled=0`, no errors.
  - Verify: `tests/cli/test_index_reconcile.py::test_reconcile_idempotent_on_clean_index`
- [ ] **Reconcile is resumable / non-corrupting on interrupt.** Interrupting reconcile mid-run leaves the index in a valid state: reconciled rows have the primary identity, un-reconciled rows retain the fallback identity. The index is still mixed but never corrupt (no partial writes, no missing rows). A subsequent `index doctor` accurately reports the remaining mismatch count.
  - Verify: `tests/cli/test_index_reconcile.py::test_reconcile_partial_run_leaves_valid_index` — simulate a failure after row N; assert rows 0..N-1 have primary identity, rows N..end have fallback identity, no rows are missing or corrupt.
- [ ] **Dim-change rebuild path documented.** `docs/EMBEDDINGS.md :: Rebuild playbook` and the *Dimension-change migration* section of this file describe the full path for switching to a different dim/provider without data corruption.
  - Verify: doc anchor — `docs/EMBEDDINGS.md :: Rebuild playbook` references the dim-change scenario and the `reset_vector_index` + `index rebuild` sequence.
- [ ] **Owner-doc fallback rule updated.** `docs/EMBEDDINGS.md :: Fallback rule` no longer forbids disciplined dim-matched fallback; it permits it under the stated constraints, points to `OPERATOR_EGRESS_DECISION.md` and this task, and documents `gemini-embedding-001` with `output_dimensionality=768` (L2-renormalized).
  - Verify: doc anchor — `docs/EMBEDDINGS.md :: Fallback rule` contains "Disciplined, dim-matched fallback is permitted" and references this task.
- [ ] **`index doctor` CLI extended.** In non-JSON mode, `index doctor` prints the mixed-identities list (full `(provider, model, dim, normalize)` tuples) when detected. In JSON mode, the response includes `mixed_identities`.
  - Verify: `tests/cli/test_index_doctor_mixed.py::test_doctor_cli_prints_mixed_identities`

## How to Verify (Pre-Merge)

1. Run the new test files:
   ```
   pytest tests/stores/test_pg_vector_index.py::test_upsert_records_full_identity_columns
   pytest tests/indexer/test_mixed_identity_detection.py
   pytest tests/cli/test_index_reconcile.py
   pytest tests/cli/test_index_doctor_mixed.py
   ```
2. Confirm `docs/EMBEDDINGS.md :: Fallback rule` reads consistently with the disciplined-fallback posture (no contradictions with EMBEDREL-05 behavior).
3. Confirm `docs/EMBEDDINGS.md :: Configuration` lists `gemini` as a supported `LLM_PROVIDER` value.
4. Run `index doctor --strict` against a test pg backend with manually-inserted mixed-identity rows (including a same-provider-different-model case, e.g. two ollama models); confirm exit code 2 and the mixed-identity message listing full tuples.
5. Run `index reconcile --dry-run` and confirm the count matches the manually-inserted non-primary-identity rows without writing.
6. Run `index reconcile` and confirm doctor subsequently reports `status=ok`.

## Out of Scope

- Implementing the provider fallback orchestration itself (EMBEDREL-05, `PROVIDER_FALLBACK_ORCHESTRATION.md`).
- Per-vault dim configuration or multi-vault identity isolation (epic #2143).
- pgvector extension setup or operator-class configuration — this task uses the existing `DOUBLE PRECISION[]` column; pgvector extension migration is deferred.
- Automatic scheduled reconcile (a future operational concern; this task provides the CLI primitive).
- Fallback for a provider that returns a different dim — `assert_embed_dim` already guards this at upsert time; this task adds no new logic there.
- Memory backend mixed-identity detection — `MemoryVectorIndex` (`app/index/vector_index_memory.py`) has no per-row provider column and is used only in tests/dev. The new provider column and reconcile command apply to `PgVectorIndex` only.

## Restart / Durability Posture

**Idempotency.** Reconcile identifies candidate rows by **full-identity inequality** — `(provider, model, dim, normalize) != (<primary_provider>, <primary_model>, <primary_dim>, <primary_normalize>)` — consistent with the detection/selection predicate in section (c) and CTI-1. Keying on `provider` alone would leave same-provider model/normalization drift (e.g. `ollama/nomic-embed-text` → `ollama/mxbai-embed-large` at the same dim) unreconciled. After a successful upsert for a row, its full identity is updated to the primary identity. On re-run, that row no longer matches the predicate and is skipped. Running reconcile on a fully-converged index is a no-op.

**Resumability.** Reconcile processes rows one at a time (same pattern as `index rebuild`). If interrupted (SIGINT, crash, container restart), rows processed before the interrupt have already been upserted with the primary identity — they will not be re-processed on the next run. Rows not yet processed retain their prior (non-primary) full identity. The index is mixed but valid: no row is in a partial state, because the upsert is an atomic `INSERT ... ON CONFLICT DO UPDATE`. The `_record_failure` pattern (reused from `app/cli/index_rebuild.py`) dead-letters failed rows to a JSONL file; these can be retried by re-running reconcile.

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
