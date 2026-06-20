---
name: Embedding Execution Queue & Backpressure
description: Bounded-concurrency, rate-limited, retry-with-backoff embedding execution with per-object dead-letter so one failure can't abort an ingest
task_id: EMBEDREL-02
source_anchor: docs/EMBEDDINGS.md :: Oversized input handling
parent_capability: Embedding Reliability & Pluggable Provider
prerequisites: []
depends_on: []
can_parallelize_with: [PLUGGABLE_PROVIDER_REGISTRY.md]
---

# Embedding Execution Queue & Backpressure

## Purpose

Make the primary Ollama embedding path reliable under memory-constrained
conditions (Colima 4 GB, `nomic-embed-text` + `llama3.1:8b` co-resident) by
adding bounded concurrency, exponential backoff on transient failures, and a
per-object dead-letter path so a single embedding failure can never abort a
whole-vault ingest.

This task delivers the **retry/backoff seam** that later tasks (task 5:
`PROVIDER_FALLBACK_ORCHESTRATION.md`) will hook into for Gemini fallback. It
does not add a second queue or a new event substrate — it extends the existing
outbox/worker path and the existing `index rebuild` CLI loop.

## What This Task Does

1. **Introduces `app/llm/embed_queue.py`** — a new module exposing:
   - `embed_with_retry(text, *, provider, model, dim, normalize, timeout)` — a
     single-object embed call that wraps `_ollama_embed_one` (and the existing
     chunking + mean-pooling in `_embed_single`) with exponential backoff on
     transient failures, using the same classification logic as
     `_is_transient_dispatch_error` in `app/workers/outbox_worker.py`. On
     exhaustion it raises `EmbedDeadLetterError` (a subclass of `RuntimeError`)
     instead of the raw provider error, enabling callers to distinguish "retry
     exhausted" from "unexpected crash".
   - `EmbedDeadLetterError` — typed sentinel so call sites can dead-letter
     without inspecting exception strings.
   - Config helpers that read the env vars described below.

2. **Wires `embed_with_retry` into `app/services/indexer.py`** — the
   `handle_ingest_object_created` function currently calls `llm_embed_text`
   directly (line 91). Replace that call with `embed_with_retry`. On
   `EmbedDeadLetterError`, emit `index.embedding.failed` and return (existing
   behaviour) rather than letting the raw error propagate. The ingest of all
   other objects continues (CTI-6).

3. **Wires `embed_with_retry` into `app/indexer/consumer.py`** — the
   `process_event` function calls `embedder.embed_text(text)` (line 109).
   Wrap that call with `embed_with_retry` (or delegate to it through the client
   protocol so the retry policy is applied once, not duplicated). On
   `EmbedDeadLetterError`, call `emit_index_embedding_failed` and return.

4. **Replaces the inline retry loop in `app/cli/index_rebuild.py`** — the
   `rebuild` command already has `_attempt_with_retries` / `_is_retryable_exception`
   (lines 120–139). Replace the embed call inside the per-object loop (line 273)
   with `embed_with_retry`. The existing failure-record path (`_record_failure`)
   is preserved; `EmbedDeadLetterError` maps to `stage="embed"` in the failure
   JSONL and the loop continues to the next object. Remove the now-redundant
   `_is_retryable_exception` / `_attempt_with_retries` helpers if they are not
   used by any other call site after the migration (or keep them if the upsert
   retry still needs them — do not touch the upsert retry path in scope).

5. **Bounded concurrency for batch paths** — `embed_with_retry` is synchronous
   and serializes by default (concurrency=1). When `EMBED_QUEUE_CONCURRENCY > 1`
   is set, `index rebuild` MAY fan out embedding calls via a
   `concurrent.futures.ThreadPoolExecutor` bounded to `EMBED_QUEUE_CONCURRENCY`.
   The default of 1 is the safe production setting for a memory-bound Ollama;
   concurrency > 1 is opt-in. The worker path (one outbox row per tick) is
   inherently serial and does not need an explicit semaphore — `embed_with_retry`
   is simply called once per tick.

6. **Preserves all existing guards:**
   - `#2110` chunking + mean-pooling in `_embed_single` / `_embed_single` is
     not changed. `embed_with_retry` sits above `_embed_single`/`_ollama_embed_one`
     in the call stack and retries the whole single-object embed (which internally
     already chunks).
   - `#2190` all-zero-batch fail-loud guard in `embed_texts` is not changed.
     `embed_with_retry` does not call `embed_texts`; it calls the single-object
     path. The `embed_texts` guard continues to fire when a caller uses the batch
     API and every item degrades.

## Concretely

After this task ships, running `index rebuild` over a corpus that includes one
note that transiently fails (e.g. Ollama runner momentarily OOM-crashes) behaves
as follows:

```
$ index rebuild --backend memory --json
{
  "total_objects": 63,
  "processed": 62,
  "skipped": 0,
  "errors": [
    {
      "object_id": "...",
      "kind": "note",
      "source_ref": "vault/Inbox/pathological.md",
      "stage": "embed",
      "exception_type": "EmbedDeadLetterError",
      "message": "embed exhausted after 3 attempts (transient): Ollama embedding requests failed ...",
      "retryable": true,
      "attempts": 3
    }
  ],
  "error_count": 1,
  "duration_ms": 4200
}
```

Key observable properties:
- `processed=62` (not 0, not aborted).
- The failure JSONL at `INDEX_REBUILD_FAILURES_PATH` contains the dead-lettered
  object with `stage=embed` and `exception_type=EmbedDeadLetterError`.
- Logs show backoff messages between attempts:
  `embed_with_retry attempt=2/3 backoff_s=2.0 error=... object_id=...`

For the worker path, a `INGEST_VAULT_CHANGED` event that triggers embedding
through `handle_ingest_object_created` → `embed_with_retry` will log backoff
attempts, then emit `index.embedding.failed` and return — the worker acks the
row and moves to the next one. The outbox is not blocked.

## Why This Matters

The current failure mode is a crash that aborts the entire ingest:

```
RuntimeError: Ollama embedding requests failed (model=nomic-embed-text:latest,
expected_dim=768) ... HTTP 500: do embedding request: ... EOF
```

This EOF surfaces when the Ollama model runner OOM-crashes under load. The
backoff gives the runner time to reload between attempts (CTI-5). A single
crash within a 63-note ingest should not prevent 62 other notes from being
indexed.

Without this task, task 5 (provider fallback) has nowhere to hook in: the
primary path raises immediately on first failure and the call stack unwinds
before any fallback can be consulted.

## Acceptance Criteria

- [ ] **AC1 — Transient classification matches the worker.** `embed_with_retry`
  classifies HTTP 5xx, 408, 429, EOF/connection-reset/timeout errors as
  transient (retryable) using the same logic as `_is_transient_dispatch_error`
  in `app/workers/outbox_worker.py`. Non-transient errors (e.g. dimension
  mismatch `ValueError`, unsupported provider) are not retried.
  Verify: `tests/llm/test_embed_queue.py::test_transient_classification`

- [ ] **AC2 — Exponential backoff between retry attempts.** Between each retry
  attempt, `embed_with_retry` sleeps for `min(EMBED_RETRY_BASE_BACKOFF_S *
  2^(attempt-1), EMBED_RETRY_MAX_BACKOFF_S)` seconds. At default settings (base
  1.0 s, max 30.0 s) the sleeps for 3 attempts are approximately 1 s and 2 s
  before the third attempt.
  Verify: `tests/llm/test_embed_queue.py::test_backoff_timing`

- [ ] **AC3 — Dead-letter on exhaustion, raises `EmbedDeadLetterError`.** When
  all `EMBED_RETRY_MAX` attempts are exhausted on a transient error,
  `embed_with_retry` raises `EmbedDeadLetterError` (subclass of `RuntimeError`).
  The error message includes the attempt count and the last provider error.
  Verify: `tests/llm/test_embed_queue.py::test_dead_letter_on_exhaustion`

- [ ] **AC4 — Non-transient errors are raised immediately (no retry).** A
  `ValueError` from dimension mismatch or an unsupported-provider error is
  re-raised on the first attempt without sleeping or incrementing the retry
  counter.
  Verify: `tests/llm/test_embed_queue.py::test_no_retry_on_non_transient`

- [ ] **AC5 — One embedding failure does not abort `handle_ingest_object_created`.** When
  `embed_with_retry` raises `EmbedDeadLetterError` inside
  `handle_ingest_object_created` (`app/services/indexer.py`), the function emits
  `index.embedding.failed` and returns without raising. Callers (worker loop,
  test) observe no exception; the other objects in a batch continue.
  Verify: `tests/indexer/test_embed_queue_ingest.py::test_dead_letter_does_not_abort_ingest`
  (behavioral test at the production call site; patches `embed_with_retry` to
  raise `EmbedDeadLetterError` and asserts (a) no exception propagates from
  `handle_ingest_object_created` and (b) `emit_index_embedding_failed` is
  called)

- [ ] **AC6 — One embedding failure does not abort `process_event` in the indexer
  consumer.** When `embed_with_retry` raises `EmbedDeadLetterError` inside
  `process_event` (`app/indexer/consumer.py`), the function emits
  `index.embedding.failed` and returns without raising. The worker loop
  subsequently acks the outbox row and processes the next one.
  Verify: `tests/indexer/test_embed_queue_consumer.py::test_dead_letter_emits_failed_and_returns`

- [ ] **AC7 — `index rebuild` CLI continues on per-object dead-letter.** When one
  object's embed raises `EmbedDeadLetterError`, the rebuild loop records the
  failure, increments `error_count`, and continues to the next object. The final
  JSON summary contains `"processed": N-1, "error_count": 1` (not `"processed":
  0`).
  Verify: `tests/cli/test_index_rebuild_cli.py::test_rebuild_continues_past_embed_dead_letter`

- [ ] **AC8 — All-zero-batch fail-loud guard is preserved.** When ALL embeddable
  items in a batch degrade (provider-wide outage), `embed_texts` still raises
  `RuntimeError` (the #2190 guard). This task does not suppress that guard.
  Verify: `tests/llm/test_provider_fail_loud.py` — existing tests remain green
  (no new test required; this AC is a regression guard)

- [ ] **AC9 — Config env vars are read with sane defaults.** `EMBED_QUEUE_CONCURRENCY`
  defaults to 1, `EMBED_RETRY_MAX` to 3, `EMBED_RETRY_BASE_BACKOFF_S` to 1.0,
  `EMBED_RETRY_MAX_BACKOFF_S` to 30.0. All four are read identically in dev,
  test, and prod (no environment-conditional branching).
  Verify: `tests/llm/test_embed_queue.py::test_config_defaults`

- [ ] **AC10 — Owner doc updated.** `docs/EMBEDDINGS.md` is updated to document
  the four new env vars (`EMBED_QUEUE_CONCURRENCY`, `EMBED_RETRY_MAX`,
  `EMBED_RETRY_BASE_BACKOFF_S`, `EMBED_RETRY_MAX_BACKOFF_S`) under
  "Optional env vars" and to note that per-object transient failures are retried
  with backoff before `index.embedding.failed` is emitted.
  Verify: presence of the four env var names and the word "backoff" in
  `docs/EMBEDDINGS.md` after the PR merges.

## How to Verify (Pre-Merge)

**Local unit tests (must all pass):**

```bash
# New tests introduced by this task
pytest tests/llm/test_embed_queue.py -v
pytest tests/indexer/test_embed_queue_ingest.py -v
pytest tests/indexer/test_embed_queue_consumer.py -v

# Regression: index rebuild CLI (extends existing test file)
pytest tests/cli/test_index_rebuild_cli.py -v

# Regression guard: all-zero-batch fail-loud (must not regress)
pytest tests/llm/test_provider_fail_loud.py -v
```

**Integration smoke (local, requires Ollama running):**

```bash
# With EMBED_RETRY_MAX=1 to shorten the wait, induce an Ollama failure by
# pointing at a bad URL; verify rebuild completes with error_count > 0, not crash:
OLLAMA_HOST=http://127.0.0.1:19999 EMBED_RETRY_MAX=1 EMBED_RETRY_BASE_BACKOFF_S=0.1 \
  python -m app.cli.entrypoint index rebuild --backend memory --json
# Expected: JSON summary with processed=0 (no objects in memory store), no exception
# In a populated pg store with LLM_PROVIDER=ollama pointing at bad URL:
# Expected: JSON summary with error_count = total_objects, no SystemExit unless --strict
```

**CI gate:**

The existing `not-pg` unit gate covers `tests/llm/` and `tests/cli/` and
`tests/indexer/`. All new test files must be collected by pytest without
`PYTEST_DISABLE_PLUGIN_AUTOLOAD` (see: `docs/` CI gating posture note — that
plugin autoload guard was dropped in PR #2046). The not-pg gate must pass with
`--timeout 120` (the watchdog introduced in #2260).

## Out of Scope

- **Provider fallback (Gemini).** This task provides the `EmbedDeadLetterError`
  seam that task 5 (`PROVIDER_FALLBACK_ORCHESTRATION.md`) hooks into. No Gemini
  code is added here.
- **`EmbeddingClientProtocol` / provider registry.** Formalized in task 3
  (`PLUGGABLE_PROVIDER_REGISTRY.md`), which can run in parallel with this task.
- **Dimension consistency enforcement / `index doctor` mixed-identity
  detection.** Task 6 (`DIMENSION_CONSISTENCY_AND_REINDEX.md`).
- **Colima memory bump.** Evaluated and rejected (see
  `OPERATOR_EGRESS_DECISION.md`).
- **`embed_texts` batch API changes.** The `embed_texts` all-zero-batch guard
  (`#2190`) is preserved as-is. `embed_with_retry` uses the single-object path.
- **Persistent dead-letter queue / replay UI.** Dead-lettered objects are
  recorded in the existing JSONL failure file (`INDEX_REBUILD_FAILURES_PATH`)
  and via `index.embedding.failed` events. No new UI or replay mechanism is
  introduced here.
- **ASK/retrieval query embedding.** This task covers the ingest/indexing paths
  only.

## Related Docs

- `docs/EMBEDDING_RELIABILITY/README.md` — capability design SoT; CTI-1..CTI-6
- `docs/EMBEDDINGS.md` — normative embedding spec; "Oversized input handling"
  (`#2110`), all-zero-batch fail-loud guard (`#2190`), env var table
- `docs/EVENTS.md` — `index.embedding.requested`, `index.embedding.created`,
  `index.embedding.failed` event schemas
- `docs/LLM.md` — provider/endpoint table (`/api/embeddings` →
  `/v1/embeddings` fallback)
- `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` — egress/provider
  decision record
- `app/llm/embeddings.py` — `_ollama_embed_one`, `_embed_single`,
  `embed_with_retry` will sit in a new peer module `app/llm/embed_queue.py`
- `app/workers/outbox_worker.py` — `_is_transient_dispatch_error`,
  `_TRANSIENT_*` sets, `_MAX_DISPATCH_ATTEMPTS` — the transient classification
  logic this task reuses
- `app/cli/index_rebuild.py` — `rebuild` command, `_attempt_with_retries`,
  `INDEX_REBUILD_MAX_RETRIES`
- `app/indexer/consumer.py` — `process_event` (embedding call site)
- `app/services/indexer.py` — `handle_ingest_object_created` (embedding call
  site)

## Related GitHub Issues

- [#2242](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2242) — substrate
  antecedent ("index rebuild reports processed >= 1"); this task is the next
  blocker toward closing that capability AC
- `PARENT_FEATURE_ISSUE.md` in this directory — the feature validation hub;
  EMBEDREL-02 is a child slice

**TCD: Sonnet / high effort — concurrency + retry policy + transient
classification, multi-file, defect-sensitive (reliability path).**
