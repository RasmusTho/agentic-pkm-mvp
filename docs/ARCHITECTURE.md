# Architecture — SoT v4.3.1 baseline (on path to v4.4)

_Reference for how the platform actually runs today. Treat this as the system of record._

---

## Runtime & Deployment
- **Language/runtime:** Python 3.12
- **Surfaces:** FastAPI APIs, background workers, LangGraph-driven agents orchestrated via PER (Plan → Execute → Reflect) loops
- **Persistence:** Postgres 16 with pgvector extension, deterministic embedding fallback when vector SIMD unavailable
- **Queues/outbox:** Filesystem-backed event outbox (JSONL) with optional Redis bridge for fan-out
- **LLMs:** Local Ollama (llama3 family, deepseek) plus pluggable remote adapters
- **Packaging:** Docker Compose for local stack (db, api, worker)
- **CLI entrypoints:** `python -m app.agents.runner --agent <name>`, plus dedicated tools under `app/cli/`

---

## Data Model & Storage Guarantees
- **Objects:** `objects(uuid PK, fallback_id bigint, kind, payload jsonb, created_at, updated_at)` — immutable `uuid`; mutable fields live inside `payload`
- **Chunks / embeddings:** `chunks(uuid PK, object_uuid, idx, text, offset_start, offset_end)` with associated `embeddings` rows (pgvector or deterministic embedding)
- **Decisions / audit / agent_memories:** deterministic agent outputs captured with `trace_id`, agent name, and PER phase metadata
- **Vault mirror:** Markdown notes with YAML frontmatter remain the canonical human surface; merges and promotions always write Markdown + YAML
- **Deterministic safeguards:** UUID immutability enforced at agent layer, `review_state` monotonic (`draft → reviewed → promoted → archived`), provenance references never discarded
- **Merge semantics:** conflict resolution now semantic (MergeResolverAgent) instead of timestamp-last-write-wins

---

## Eventing & Observability
- **Outbox-driven events:** every agent run emits domain events (e.g. `ingest.object.created`, `merge.intent.created`, `promote.done`, `cleanup.done`) into `events.jsonl`
- **PER loop instrumentation:** each Plan/Execute/Reflect cycle records audit rows and emits events atomically
- **Tracing:** all agents wrap execution in `start_span("agent.name", trace_id, {...})`; when `runtime.enable_tracing=true` spans are exported via OTLP to Jaeger
- **Trace context:** `trace_id` propagates through events, audit tables, and CLI tooling for replay/debug

---

## Pipelines
### Ingestion & Indexing
1. **Normalizer** ingests raw files/content, creates `objects` rows, locks immutables
2. **Classifier** annotates taxonomy and trust decisions
3. **Chunker** slices Markdown into semantic spans recorded in `chunks`
4. **Indexer** writes embeddings (pgvector or deterministic), updates search indices
5. **Reviewer & SetEvaluator** score readiness; **Projector** publishes eligible objects into public sets

### Merge Flow
- `merge.intent.created` event triggers MergeResolverAgent
- Semantic comparison merges Markdown/YAML, emits `merge.resolved`, `merge.prompted`, or `merge.conflict`
- Deterministic fallbacks run if LLM output is absent/invalid; uuid/review_state invariants enforced before commit

### Hygiene Flow
- `cleanup.intent.created` fires NoteHygieneAgent post-ingest or post-merge
- Agent salvages minimal notes, archives empties, or relocates noisy dumps, guaranteeing the vault stays usable
- Emits `cleanup.done` with remediation details

### Promotion Flow
- Promotion Agent consumes `promote.intent.created`
- Applies cooldown/idle policy, updates frontmatter (`review_state: promoted`), may queue batch file moves, emits `promote.done`
- Acts as thin wrapper over event pipeline, replacing manual Obsidian updates

---

## Agents (PER Loops)
### MergeResolverAgent
- **Purpose:** resolve conflicts between divergent Markdown notes that include YAML frontmatter
- **Inputs:** `(base, a, b)` note blobs
- **Flow:**
  1. `diff_conflict_loci()` separates YAML keys from body loci
  2. `judge_locus()` LLM scoring (strict schema, penalises noisy dumps, preserves references, prevents review_state regressions)
  3. `apply_decisions()` assembles a single frontmatter block and merged body
- **Output contract:** `(merged_text, info.status, info.reason)`
- **CLI:** `app/cli/merge_driver.py` wraps `merge_note_from_blobs`, prints the merged note, and returns `(status, reason)` so callers know whether the merge was resolved automatically, requires a prompt, or hit a conflict. The CLI is covered by `tests/cli/test_merge_driver.py`, which now runs under `make smoke`.
- **Determinism:** fallback heuristics run when LLM output is missing/invalid to guarantee safe merges
- **Status:** implemented, covered by unit + smoke tests; ready to be invoked as future git merge driver
- **Future:** callable via planned CLI/merge driver hook

Warning: the merge CLI currently writes the merged note only to stdout; it does not modify the working copy. Git merge driver wiring remains TODO.

#### Developer workflow
- Run `make merge-dryrun BASE=... A=... B=...` to exercise the semantic merge CLI against conflict triples.
- Exit code semantics: `0` means the merge is safe to apply as-is; non-zero exits signal that human intervention is required.
- The CLI is intentionally human-in-the-loop today—review the stdout output and apply it manually until the Git merge driver integration lands.

### NoteHygieneAgent
- **Purpose:** identify fragments or garbage after ingestion/merge and salvage or quarantine
- **Behaviours:**
  - Title + URL only → keep minimal cleaned note with salvage summary
  - Frontmatter-only / empty body → set `review_state: archived`
  - Oversized JSON/log dumps in non-technical notes → move to attachment/parking path, leave reference pointer
- **Events:** emits `cleanup.*` outcomes documenting action taken
- **Guarantee:** prevents noisy content from poisoning downstream promotion/indexing
- **Status:** implemented and tested

### Promotion Agent (recap)
- **Purpose:** process `promote.intent.created`, update frontmatter (`review_state: promoted`), enforce cooldown/idle policy, emit `promote.done`, optionally schedule batch moves
- **UX impact:** replaces manual “mark as done” in Obsidian; no plugin required

Additional agents (Reviewer, SetEvaluator, Projector, Classifier, Normalizer, Indexer) continue to run under PER with deterministic safeguards and trace instrumentation.

---

## Observability & Tooling
- Centralised traces via `start_span`, audit trails in Postgres, JSONL event log for replay
- CLI utilities under `tools/` and `app/cli/` provide event tailing, merge prompt exports, and (now) merge driver experiments
- Metrics (latency targets, merge decision counts) captured via audit + events; Jaeger visualisation available when tracing enabled

---

## Testing & CI
- `pytest -q` covers agents (merge, hygiene, promotion), schema validation, indexer invariants
- `make smoke` exercises settings schema, promotion flows, merge smoke tests, and end-to-end promotion-worker roundtrip
- Deterministic fallbacks ensure green builds even when LLM runway is constrained

---

## Roadmap Hooks
- v4.4 focuses on semantic merge rollout, hygiene integration, observability enhancements
- v4.5 introduces golden fixtures, block-aware diffing, merge-driver CI
- v5.0 targets reasoning layer integration while preserving current safeguards
