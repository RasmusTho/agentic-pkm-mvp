---
name: Provider Fallback Orchestration (Ollama-primary, Gemini-fallback)
description: Wire Ollama-primary to Gemini-fallback into the indexer/queue path on primary failure, with fallback-identity tagging and an egress-visible signal
task_id: EMBEDREL-05
source_anchor: docs/EMBEDDING_RELIABILITY/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: Embedding Reliability & Pluggable Provider
prerequisites: [EMBEDREL-02, EMBEDREL-03, EMBEDREL-04]
depends_on: [EMBEDDING_EXECUTION_QUEUE.md, PLUGGABLE_PROVIDER_REGISTRY.md, GOOGLE_GEMINI_ADAPTER.md]
can_parallelize_with: []
---

# Provider Fallback Orchestration (Ollama-primary, Gemini-fallback)

## Purpose

Wire the runtime fallback decision into the two production embedding call sites —
`handle_ingest_object_created` (`app/services/indexer.py`) and `process_event`
(`app/indexer/consumer.py`) — so that when the primary Ollama path raises
`EmbedDeadLetterError` (retry-exhausted, from EMBEDREL-02), the worker
transparently retries the same object via the Gemini adapter (EMBEDREL-04)
*if and only if* a Gemini key is configured and the fallback dimension matches
the primary dimension. On a successful fallback embed the vector is tagged with
the Gemini `EmbeddingIdentity`, marked RECONCILABLE in vector-index provenance,
and an operator-visible egress signal is emitted. When the fallback is
unavailable or dim-mismatched, the object is dead-lettered with
`index.embedding.failed` and the ingest continues (CTI-6).

This task ships no new queue mechanism, no new provider adapter, and no change
to the ASK/retrieval query path. Its only job is the orchestration decision that
joins those already-shipped primitives.

## What This Task Does

1. **Adds `app/llm/fallback_orchestrator.py`** — a new module exposing:
   - `embed_with_fallback(text, *, primary_identity, db_session_or_none)
     -> tuple[list[float], EmbeddingIdentity, bool]` — calls
     `embed_with_retry(text, ...)` (EMBEDREL-02) against the primary provider;
     on `EmbedDeadLetterError`, evaluates the fallback gate (key present,
     `EMBED_FALLBACK_PROVIDER` set, dims match), calls the Gemini adapter if
     all conditions pass, and returns `(vector, actual_identity, is_fallback)`.
     When no fallback is available or the gate fails, re-raises
     `EmbedDeadLetterError` so the caller can dead-letter the object.
   - `FallbackGateResult` — a named result enum:
     `AVAILABLE`, `NO_KEY`, `NO_FALLBACK_CONFIGURED`, `DIM_MISMATCH`.
   - `evaluate_fallback_gate(primary_dim) -> FallbackGateResult` — pure
     predicate: reads `EMBED_FALLBACK_PROVIDER` from the registry
     (`get_fallback_provider()`, EMBEDREL-03), resolves the Gemini adapter
     presence via `GeminiUnavailableError` probe (EMBEDREL-04), and checks
     that fallback dim == primary dim. Returns the appropriate gate result;
     does not embed.

2. **Wires `embed_with_fallback` into `handle_ingest_object_created`
   (`app/services/indexer.py`)** — replaces the direct
   `llm_embed_text` / `embed_with_retry` call (currently lines 90–98) with
   `embed_with_fallback`. The returned `(vector, actual_identity, is_fallback)`
   tuple drives:
   - `vector_index.upsert(...)` with `model=actual_identity.model` and
     `identity=actual_identity` (the fallback identity, not the primary one,
     when `is_fallback=True`).
   - `emit_index_object_embedded(...)` enriched with `provider=actual_identity.provider`,
     `model=actual_identity.model`, and a `fallback_used=True` annotation in
     the event `meta` when `is_fallback=True` (see Observable signal below).
   - When `embed_with_fallback` raises `EmbedDeadLetterError` (neither primary
     nor fallback succeeded), the existing `emit_index_embedding_failed` and
     `return` path fires unchanged (CTI-6).

3. **Wires `embed_with_fallback` into `process_event`
   (`app/indexer/consumer.py`)** — the `embedder.embed_text(text)` call at
   line 109 is replaced with `embed_with_fallback`. On success with
   `is_fallback=True`, the `idx.upsert(...)` at line 114 uses
   `actual_identity` for `model=` and `identity=`. On `EmbedDeadLetterError`,
   `emit_index_embedding_failed` is called and the function returns (no
   exception propagates to the outbox worker).

4. **Adds the RECONCILABLE marker** — when `is_fallback=True`, the
   `vector_index.upsert(...)` call includes a `tags={"reconcile": "pending"}`
   kwarg (or equivalent provenance field already supported by the VectorIndex
   upsert signature). This marker is what EMBEDREL-06 (`index doctor`) will
   query to surface mixed-identity vectors for re-index. If the upsert
   signature does not yet accept `tags`, add a `meta` dict field scoped to
   the vector record. Document the exact field name in `## Concretely` so
   EMBEDREL-06 has a concrete anchor.

   **Blocking dependency — the Pg backend rejects mismatched identity on upsert (P1).**
   `app/stores/pg.py::PgVectorIndex.upsert()` calls
   `_ensure_index_identity(cur, resolved_identity, allow_create=True)` (pg.py:332),
   which raises `RuntimeError("Embedding identity mismatch ...")` (pg.py:149) whenever
   the requested provider/model/dim/normalize differs from the index's recorded
   identity. A Gemini-fallback vector therefore **cannot** be upserted into an
   Ollama-identity index as written — the write fails closed. This must be resolved
   before fallback writes are searchable: the vector index identity model has to move
   from **index-level single identity** to **per-vector identity with a stable index
   primary identity**, so a fallback vector can be recorded under the Gemini identity
   (tagged `reconcile=pending`) without tripping the index-level guard, while the
   index's *primary* identity (used for queries, CTI-3) stays Ollama. This schema/guard
   change is shared with EMBEDREL-06 (which records per-vector identity and detects the
   mixed state); land it as the first step of this slice (or a small precursor) and
   keep the dim guard intact (a dim mismatch must still fail — CTI-1). If the per-vector
   identity change is deferred, fallback must **not** silently fail the upsert: it
   dead-letters with `index.embedding.failed` and the object waits for the worker /
   re-index instead (degraded availability, but never a corrupt or silently-dropped
   write).

5. **Emits an observable fallback signal** — when `is_fallback=True`, the success
   event carries `provider=actual_identity.provider` (`"gemini"`) in `provenance`
   and `meta={"fallback_used": True, "primary_provider": primary_identity.provider}`.
   - `handle_ingest_object_created` already emits via `emit_index_object_embedded`,
     whose signature accepts `provider=` and `meta=` (`app/outbox/events.py:154-184`) —
     use them directly; no new event type is required.
   - **Consumer path needs an extension (P2).** `process_event` currently emits
     `emit_index_embedding_created`, whose signature is only
     `(*, object_id, trace_id, source)` with a fixed `provenance={"model": EMBED_MODEL,
     "version": "1.0"}` (`app/outbox/events.py:139-151`) — it cannot carry `provider`
     or `meta`. Either (a) extend `emit_index_embedding_created` to accept
     `provider`/`model`/`meta` (preferred — keep the event type the consumer already
     emits), or (b) switch the consumer success emission to `emit_index_object_embedded`.
     Do not assume the egress signal is emittable on the consumer path without this change.
   Operators tailing the outbox JSONL or querying the events table will then see
   `provenance.provider="gemini"` and `meta.fallback_used=true` on any fallback-routed
   write, making egress to Google fully visible.

6. **CTI-3 invariant — query path unchanged.** This task does NOT touch
   `app/components/embeddings.py::get_embedding_client`, `resolve_embedding_identity`,
   or any ASK/retrieval call site. The `EMBED_PRIMARY_PROVIDER` path that the
   query uses is untouched. Queries always embed with the primary identity;
   fallback-written document vectors are knowingly-degraded matches until
   EMBEDREL-06 reconciles them. This is an explicit architectural invariant
   that must not regress.

## Concretely

### Happy path — Ollama down, Gemini key configured

Preconditions: `GEMINI_API_KEY` set, `EMBED_FALLBACK_PROVIDER=gemini`,
`EMBED_DIM=768`, Ollama unreachable or OOM-crashed, pg backend populated with
at least one object (or use the in-process seed approach — see `## How to Verify`).

```
$ OLLAMA_HOST=http://127.0.0.1:19999 GEMINI_API_KEY=<key> \
    EMBED_FALLBACK_PROVIDER=gemini EMBED_RETRY_MAX=1 \
    EMBED_RETRY_BASE_BACKOFF_S=0.1 \
    python -m app.cli index rebuild --backend pg --json
```

Note: `--backend memory` loads an **empty** in-memory object store in a fresh
process and exits with `processed=0` before any embedding call is made — it
cannot exercise the fallback path. Use `--backend pg` with a populated object
store, or the in-process seed script described in `## How to Verify`.

Expected observable properties:
- `processed >= 1` (objects embedded, ingest not aborted).
- Outbox JSONL contains `index.object.embedded` records with
  `provenance.provider="gemini"` and `meta.fallback_used=true` for every
  object that hit fallback.
- VectorIndex rows for those objects carry `identity.provider="gemini"`,
  `identity.model="gemini-embedding-001"`, `identity.dim=768`,
  `tags.reconcile="pending"` (the RECONCILABLE marker).
- Log lines: `embed_with_fallback: primary exhausted, trying fallback provider=gemini object_id=<uuid>`
  for each fallback invocation.

### No-key path — graceful dead-letter

Preconditions: `GEMINI_API_KEY` unset, `GOOGLE_API_KEY` unset, Ollama unreachable.

- `embed_with_fallback` raises `EmbedDeadLetterError` after evaluating
  `FallbackGateResult.NO_KEY`.
- `handle_ingest_object_created` catches it, calls
  `emit_index_embedding_failed(provider="ollama", ...)`, returns.
- Ingest continues to the next object (CTI-6). No content egresses to Google.
- Log line: `embed_with_fallback: fallback gate=NO_KEY, dead-lettering object_id=<uuid>`

### Dim-mismatch path — refused

Preconditions: `GEMINI_API_KEY` set, `EMBED_FALLBACK_PROVIDER=gemini`,
but fallback provider configured to return dim=3072 (e.g. wrong model override).

- `evaluate_fallback_gate(primary_dim=768)` returns `DIM_MISMATCH` because
  fallback_dim (3072) != primary_dim (768).
- `embed_with_fallback` raises `EmbedDeadLetterError` without calling the
  Gemini adapter.
- Object is dead-lettered with `index.embedding.failed`; index is not silently
  corrupted with wrong-dim vectors (CTI-1).
- Log line: `embed_with_fallback: fallback gate=DIM_MISMATCH (fallback_dim=3072 != primary_dim=768), dead-lettering object_id=<uuid>`

## Why This Matters

Without this task, the `EmbedDeadLetterError` sentinel introduced by
EMBEDREL-02 surfaces as a per-object failure with no recovery path: every
Ollama OOM event dead-letters the affected object and the note goes unindexed.
With this task, a configured Gemini key turns those dead-letters into
degraded-but-indexed vectors that remain searchable and are flagged for
reconciliation once Ollama recovers — satisfying the operator's chosen posture
(README.md § Decided posture) and the parent capability's ingest-completion AC
(README.md § Capability acceptance criteria, bullet 2).

The dim-mismatched-fallback refusal (CTI-1) and the CTI-3 query-path invariant
(untouched) are the two highest-blast-radius correctness properties in this
capability: a dim mismatch would silently corrupt the vector index, and a query
using the fallback identity would produce semantically meaningless cosine
rankings across different embedding spaces. Both are enforced here.

## Acceptance Criteria

- [ ] **AC1 — Fallback invoked from the production indexer call site on primary
  failure.** When `handle_ingest_object_created` is called with an object whose
  primary embed raises `EmbedDeadLetterError`, and a Gemini key and
  `EMBED_FALLBACK_PROVIDER=gemini` are configured, the Gemini adapter is called
  from within that same `handle_ingest_object_created` call, the returned
  vector is upserted with the Gemini `EmbeddingIdentity`, and no exception
  propagates to the caller. This is a behavioral test at the production call
  site, not a unit test of an isolated helper.
  Verify: `tests/indexer/test_provider_fallback_indexer.py::test_fallback_invoked_from_handle_ingest_object_created`
  — patches `embed_with_retry` to raise `EmbedDeadLetterError`, patches the
  Gemini adapter to return a valid 768-dim vector, calls
  `handle_ingest_object_created(obj)` directly, asserts (a) the Gemini adapter
  was called, (b) `vector_index.upsert` was called with `identity.provider="gemini"`,
  (c) no exception propagated.

- [ ] **AC2 — Fallback invoked from `process_event` on primary failure.**
  When `process_event` is called for an `index.embedding.requested` event whose
  primary embed raises `EmbedDeadLetterError`, the Gemini adapter is called and
  the upsert uses the Gemini identity.
  Verify: `tests/indexer/test_provider_fallback_consumer.py::test_fallback_invoked_from_process_event`
  — same patch pattern as AC1, drives `process_event(evt)` directly.

- [ ] **AC3 — Dim-mismatched fallback is refused; object is dead-lettered.**
  When `evaluate_fallback_gate(primary_dim=768)` is called with a fallback
  provider whose resolved dim is 3072, the gate returns `DIM_MISMATCH` and
  `embed_with_fallback` raises `EmbedDeadLetterError` without calling the
  Gemini adapter.
  Verify: `tests/llm/test_provider_fallback.py::test_dim_mismatch_refuses_fallback`
  — sets up a fallback adapter stub returning dim=3072, asserts `DIM_MISMATCH`
  gate result and `EmbedDeadLetterError` raised, asserts Gemini adapter
  `embed_gemini_text` never called.

- [ ] **AC4 — No-key path: fallback gate returns `NO_KEY`; object dead-lettered.**
  With `GEMINI_API_KEY` and `GOOGLE_API_KEY` both unset, `evaluate_fallback_gate`
  returns `NO_KEY` and `embed_with_fallback` raises `EmbedDeadLetterError`.
  `handle_ingest_object_created` emits `index.embedding.failed` and returns.
  Verify: `tests/llm/test_provider_fallback.py::test_no_key_dead_letters_object`

- [ ] **AC5 — No `EMBED_FALLBACK_PROVIDER` set: gate returns
  `NO_FALLBACK_CONFIGURED`; object dead-lettered.**
  With `EMBED_FALLBACK_PROVIDER` unset (or empty), `evaluate_fallback_gate`
  returns `NO_FALLBACK_CONFIGURED` and `embed_with_fallback` raises
  `EmbedDeadLetterError`.
  Verify: `tests/llm/test_provider_fallback.py::test_no_fallback_provider_configured_dead_letters`

- [ ] **AC6 — Fallback vector tagged with Gemini identity in upsert.**
  When fallback succeeds, `vector_index.upsert` is called with
  `identity.provider="gemini"`, `identity.model="gemini-embedding-001"`,
  `identity.dim=768` — not the primary (Ollama) identity.
  Verify: `tests/indexer/test_provider_fallback_indexer.py::test_fallback_upsert_uses_gemini_identity`
  — asserts the `identity` kwarg passed to the mock `vector_index.upsert` has
  `provider="gemini"`.

- [ ] **AC7 — RECONCILABLE marker written on fallback upsert.**
  When fallback succeeds, `vector_index.upsert` is called with a provenance
  marker (`tags={"reconcile": "pending"}` or equivalent field) that
  EMBEDREL-06 can query. The exact field name is documented below in
  `## Restart / Durability Posture`.
  Verify: `tests/indexer/test_provider_fallback_indexer.py::test_fallback_upsert_has_reconcile_marker`
  — asserts the mock `vector_index.upsert` call includes the documented marker
  field.

- [ ] **AC8 — Egress signal emitted on fallback success.**
  When `is_fallback=True`, `emit_index_object_embedded` (or
  `emit_index_embedding_created` in the consumer path) is called with
  `provider="gemini"` and `meta={"fallback_used": True, ...}` so operators can
  detect Gemini egress from the outbox JSONL or events table.
  Verify: `tests/indexer/test_provider_fallback_indexer.py::test_fallback_emits_egress_signal`
  — captures the call to the mocked emit function and asserts `provider="gemini"`
  and `meta["fallback_used"] is True`.

- [ ] **AC9 — CTI-3: query path is untouched.**
  `get_embedding_client`, `resolve_embedding_identity`, and
  `get_embeddings_client(LLMTaskIntent(...))` are not modified by this task;
  they continue to return the primary identity. No ASK or retrieval call site
  is changed.
  Verify: `pytest tests/llm/test_provider_resolution.py -x` — all existing
  query-path identity resolution tests remain green with no modifications.

- [ ] **AC10 — Fallback is the last resort; primary retries exhaust first
  (CTI-5).** The fallback gate is evaluated only AFTER `embed_with_retry`
  raises `EmbedDeadLetterError` (i.e., after all `EMBED_RETRY_MAX` primary
  attempts are exhausted). Fallback is never consulted on the first transient
  error from the primary.
  Verify: `tests/llm/test_provider_fallback.py::test_fallback_only_after_primary_retry_exhausted`
  — `EMBED_RETRY_MAX` is the **total attempt count** (per `EMBEDDING_EXECUTION_QUEUE.md`),
  so configure `EMBED_RETRY_MAX=3` and patch the primary embed stub to fail twice then
  succeed on the 3rd attempt; assert the Gemini adapter is never called (primary
  succeeded before `EmbedDeadLetterError` was raised). A companion case configures
  `EMBED_RETRY_MAX=2` with the primary failing on both attempts and asserts the gate
  IS consulted (fallback attempted) — proving fallback fires exactly when the primary
  attempt budget is exhausted, with no off-by-one.

- [ ] **AC11 — Neither primary nor fallback succeeds: object dead-lettered,
  ingest continues (CTI-6).** When the primary is exhausted AND the fallback
  adapter also raises (e.g. `GeminiTransientError`), `embed_with_fallback`
  raises `EmbedDeadLetterError`, the caller emits `index.embedding.failed`,
  and the ingest continues to the next object.
  Verify: `tests/indexer/test_provider_fallback_indexer.py::test_both_providers_fail_dead_letters_and_continues`

- [ ] **AC12 — Owner doc updated.** `docs/EMBEDDINGS.md` is updated to document
  the `EMBED_FALLBACK_PROVIDER` env var and the observable fallback signal
  fields (`provenance.provider`, `meta.fallback_used`).
  Verify: presence of `EMBED_FALLBACK_PROVIDER` and `fallback_used` in
  `docs/EMBEDDINGS.md` after the PR merges.

## How to Verify (Pre-Merge)

**Local unit tests (must all pass):**

```bash
# New tests introduced by this task
pytest tests/llm/test_provider_fallback.py -v
pytest tests/indexer/test_provider_fallback_indexer.py -v
pytest tests/indexer/test_provider_fallback_consumer.py -v

# Regression: query-path identity resolution must be untouched
pytest tests/llm/test_provider_resolution.py -x

# Regression: existing embed queue and gemini adapter tests must remain green
pytest tests/llm/test_embed_queue.py -x
pytest tests/llm/test_gemini_embeddings.py -x

# Regression: indexer ingest and consumer dead-letter tests (EMBEDREL-02)
pytest tests/indexer/test_embed_queue_ingest.py -x
pytest tests/indexer/test_embed_queue_consumer.py -x
```

**Integration smoke (local, requires Ollama and a Gemini key):**

The `--backend memory` flag loads an empty in-memory object store in a fresh process, so `index rebuild` exits with `processed=0` before any embedding call — it cannot exercise the fallback path or produce `index.object.embedded` records. Use one of the following alternatives instead:

**Option A — pg backend (populated object store):**

```bash
# Requires a running pg instance with objects already ingested (e.g. from a
# prior 'index rebuild --backend pg' run that wrote to store_objects).
# Induce Ollama failure via bad URL; confirm fallback routes to Gemini:
OLLAMA_HOST=http://127.0.0.1:19999 GEMINI_API_KEY=<real-key> \
  EMBED_FALLBACK_PROVIDER=gemini EMBED_RETRY_MAX=1 \
  EMBED_RETRY_BASE_BACKOFF_S=0.1 \
  python -m app.cli index rebuild --backend pg --json
# Expected: JSON summary processed >= 1 (at least one object from store_objects),
#   outbox JSONL contains index.object.embedded records with
#   provenance.provider="gemini" and meta.fallback_used=true for each
#   object that hit fallback; no exception raised.

# No-key path: confirm graceful dead-letter with no Gemini egress:
OLLAMA_HOST=http://127.0.0.1:19999 \
  EMBED_FALLBACK_PROVIDER=gemini EMBED_RETRY_MAX=1 \
  python -m app.cli index rebuild --backend pg --json
# Expected: JSON summary processed=0, error_count >= 1, no exception,
#   outbox JSONL contains index.embedding.failed for each object.
```

**Option B — in-process seed (no pg required):**

```python
# smoke_fallback.py — seed two objects into the in-process memory store, then run
# `index rebuild` in the SAME process so the seeded store is visible and the fallback
# path exercises real embedding calls. Uses the actual repo APIs
# (app.objects.ObjectStore / DomainObject; app.cli `index rebuild`), matching the
# pattern in tests/cli/test_index_rebuild_resilience.py.
import os
from datetime import datetime, timezone
from click.testing import CliRunner
from app.objects import DomainObject, ObjectStore

os.environ["STORE_BACKEND"] = "memory"
# Force the primary (Ollama) to fail so fallback is consulted; configure Gemini:
os.environ["OLLAMA_HOST"] = "http://127.0.0.1:19999"
os.environ["GEMINI_API_KEY"] = "<real-key>"
os.environ["EMBED_FALLBACK_PROVIDER"] = "gemini"
os.environ["EMBED_RETRY_MAX"] = "1"
os.environ["EMBED_RETRY_BASE_BACKOFF_S"] = "0.1"

store = ObjectStore()
for i, text in enumerate(["Hello world", "Agentic PKM system"], start=1):
    store.save_object(
        DomainObject(uuid=f"00000000-0000-0000-0000-00000000000{i}", kind="note",
                     payload={"text": text, "content": text}, source_ref=f"vault/n{i}.md",
                     created_at=datetime.now(timezone.utc)),
        emit_outbox=False, trace_id="smoke-fallback",
    )

from app.cli import cli
result = CliRunner().invoke(cli, ["index", "rebuild", "--backend", "memory", "--json"])
print(result.output)
# Expected: processed=2; outbox JSONL shows provenance.provider="gemini" and
# meta.fallback_used=true for both objects.
```

Run one of the above and verify:
- `processed >= 1` (objects embedded, ingest not aborted).
- Outbox JSONL contains `index.object.embedded` with `provenance.provider="gemini"` and `meta.fallback_used=true` for fallback-routed objects.
- Log lines include `embed_with_fallback: primary exhausted, trying fallback provider=gemini object_id=<uuid>`.

**CI gate:**

All new test files must be collected by pytest under the existing `not-pg`
unit gate with `--timeout 120` (watchdog from #2260). No new CI configuration
is required. All new tests use mocked httpx and patched adapters; no real
network calls or real keys are needed.

## Out of Scope

- Implementing the Gemini adapter (EMBEDREL-04) or the provider registry
  (EMBEDREL-03) — both are prerequisites, not deliverables here.
- Implementing the embedding execution queue / `embed_with_retry` (EMBEDREL-02)
  — prerequisite.
- The `index doctor` mixed-identity detection and re-index migration
  (EMBEDREL-06) — that task owns convergence; this task writes the
  RECONCILABLE marker it queries.
- Changing `docs/EMBEDDINGS.md :: Fallback rule` beyond the two additions in
  AC12 (the broader fallback-rule update is owned by EMBEDREL-01/EMBEDREL-06).
- The ASK/retrieval query path — explicitly untouched (CTI-3).
- Per-request fallback configuration (e.g. per-note override); the fallback
  provider is an operator-level config (`EMBED_FALLBACK_PROVIDER`).
- Colima memory bump — evaluated and rejected (OPERATOR_EGRESS_DECISION.md).
- Hot-reload of the fallback config at runtime; a process restart is the
  expected reload path for env-var changes.
- Persistent dead-letter replay UI — dead-lettered objects are recorded via
  `index.embedding.failed` events and `INDEX_REBUILD_FAILURES_PATH` JSONL,
  both owned by EMBEDREL-02.

## Restart / Durability Posture

**Fallback writes survive a worker restart.** When `embed_with_fallback`
successfully embeds via Gemini, the vector is written to the VectorIndex store
(`vector_index.upsert`) before the outbox row is acked. VectorIndex persistence
(PostgreSQL or the in-memory store in tests) is durable across a worker
restart. The RECONCILABLE marker — `tags={"reconcile": "pending"}` in the
upsert call — is stored as part of the vector record's provenance and is
therefore also durable. A worker restart does not lose the marker or re-attempt
the embed.

**Re-index ownership is EMBEDREL-06.** This task writes the marker; it does not
own the reconcile/re-index lifecycle. EMBEDREL-06 (`DIMENSION_CONSISTENCY_AND_REINDEX.md`)
implements `index doctor` to surface all vectors where `tags.reconcile=pending`
(or the equivalent field agreed on in AC7 above) and re-embeds them under the
primary identity once Ollama is stable. Until EMBEDREL-06 ships, the
reconcile-pending vectors remain in the index and are searchable via fallback
identity — degraded but available.

**Exact RECONCILABLE field name (anchor for EMBEDREL-06):** the upsert call
passes `meta={"reconcile": "pending", "fallback_provider": "gemini"}` as the
provenance marker. If the `VectorIndex.upsert` signature does not yet accept a
`meta` dict, add it as an optional `meta: dict | None = None` kwarg. Document
the chosen field name in a comment at the call site so EMBEDREL-06 has a
single concrete anchor.

## Related Docs

- `docs/EMBEDDING_RELIABILITY/README.md` — capability design SoT; CTI-1
  (dim guardrail), CTI-2 (fallback non-terminal), CTI-3 (query uses primary),
  CTI-4 (secret-gated egress), CTI-5 (backpressure precedes fallback),
  CTI-6 (no abort on single-object failure)
- `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` — operator decision
  + secret env var choices; rejected alternatives
- `docs/EMBEDDING_RELIABILITY/EMBEDDING_EXECUTION_QUEUE.md` — EMBEDREL-02;
  `EmbedDeadLetterError` + `embed_with_retry` (the primary-failure seam this
  task hooks into)
- `docs/EMBEDDING_RELIABILITY/PLUGGABLE_PROVIDER_REGISTRY.md` — EMBEDREL-03;
  `get_fallback_provider()`, `EMBED_FALLBACK_PROVIDER` env var, `EmbeddingProfile`
  `fallback_provider` field
- `docs/EMBEDDING_RELIABILITY/GOOGLE_GEMINI_ADAPTER.md` — EMBEDREL-04;
  `embed_gemini_text`, `GeminiUnavailableError`, `GeminiTransientError`
- `docs/EMBEDDING_RELIABILITY/DIMENSION_CONSISTENCY_AND_REINDEX.md` —
  EMBEDREL-06; `index doctor` mixed-identity detection; owner of reconcile
  lifecycle
- `docs/EMBEDDINGS.md` — normative embedding spec; embedding identity,
  dim guardrail, fallback rule (updated by AC12)
- `docs/EVENTS.md` — `index.object.embedded`, `index.embedding.failed` schemas;
  `meta` and `provenance` field conventions
- `app/services/indexer.py` — `handle_ingest_object_created` (primary call site,
  lines 46–149); `llm_embed_text`; `emit_index_object_embedded`
- `app/indexer/consumer.py` — `process_event` (secondary call site, lines
  47–126); `embedder.embed_text` at line 109 is the embed call replaced here
- `app/outbox/events.py` — `emit_index_object_embedded` (line 154, accepts
  `meta=` kwarg at line 164); `emit_index_embedding_failed` (line 187);
  `DEFAULT_EMBEDDING_VIEW`
- `app/components/embeddings.py` — `EmbeddingIdentity`; `get_embedding_identity`;
  `_SUPPORTED_EMBED_PROVIDERS` (must include `"gemini"` per EMBEDREL-03/04)
- `app/llm/embeddings.py` — `get_fallback_provider()` (added by EMBEDREL-03)
- `app/llm/embed_queue.py` — `embed_with_retry`, `EmbedDeadLetterError` (added
  by EMBEDREL-02)
- `app/llm/gemini_embeddings.py` — `embed_gemini_text`, `GeminiUnavailableError`,
  `GeminiTransientError` (added by EMBEDREL-04)

## Related GitHub Issues

Create one bounded implementation slice issue (`lane:core-runtime`) covering
all deliverables above. No docs-lane split is needed — AC12 (the
`docs/EMBEDDINGS.md` update) ships in the same PR as the implementation.

TCD: Opus / high effort — concurrency + data-egress + cross-cutting invariants
(identity tagging, query-path safety); highest defect blast radius in this
capability.
