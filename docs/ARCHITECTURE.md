# Architecture — SoT v4.3.1 baseline (on path to v4.4)

_Reference for how the platform actually runs today. Treat this as the system of record._

This document covers:
- Runtime & deployment
- Data model (SetDB / AMG)
- Eventing, PER loops, observability
- Pipelines (ingestion/indexing, promotion, merge, hygiene)
- Agent responsibilities and safety rails
- Testing/CI gates
- Roadmap hooks into v4.4+

---

## 1. Runtime & Deployment

- **Language/runtime:** Python 3.14
- **Surfaces:** FastAPI API surface (`/search`, etc), background workers, and LangGraph-driven agents that run PER loops (Plan → Execute → Reflect).
- **Persistence:** Postgres 16 with pgvector. We fall back to deterministic embeddings when vector SIMD/remote LLMs aren't available.
- **Queues / Outbox:** Filesystem-backed outbox (JSONL append) plus optional Redis bridge for fan-out. Outbox is the event bus inside the walking skeleton.
- **LLMs:** Local-first (Ollama: llama3.1 8B for dialogue, deepseek-r1 8B for structured/arbiter reasoning), with pluggable remote adapters (OpenAI/Anthropic/etc) via env (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_REASONING_MODEL`).
- **Packaging / runtime topology:** Docker Compose brings up db, redis, api, Jaeger, workers on the Mac mini host. We dev via VS Code Remote-SSH into that host.
- **CLI entrypoints:**  
  - `python -m app.agents.runner --agent <name>` for agents  
  - `app/cli/merge_driver.py` for semantic merge / future git merge driver  
  - other helpers under `app/cli/` and `scripts/`

- **Tracing / observability:**  
  - We instrument critical sections with `start_span("agent.name", trace_id, {...})`.
  - When `runtime.enable_tracing=true` in `system-settings.yaml`, spans export via OTLP to Jaeger.
  - `trace_id` propagates through audit rows, events, and CLI output so we can reconstruct what happened.

---

## 2. Data Model & Storage Guarantees (SetDB / AMG)

Postgres is our SetDB (knowledge store) and AMG (Agent Memory Graph). Core tables:

- **objects**  
  `objects(uuid PK, kind, payload jsonb, created_at, updated_at, ...)`  
  - `uuid` is the canonical logical identity. Older `id`/`fallback_id` fields are being retired.
  - `payload` carries Core-6 style metadata: title, review_state, provenance, timestamps.
  - `review_state` is monotonic: `draft → reviewed → promoted → evergreen/archived`. We never regress state (an agent cannot silently downgrade `promoted` back to `reviewed`).
  - `source_ref` / `source_uuid` link back to the vault file or ingest source so we can round-trip edits.

- **chunks / embeddings**  
  - `chunks(uuid PK, object_uuid, idx, text, offset_start, offset_end, meta jsonb)`  
    Logical spans of content for retrieval. Produced by Chunker.
  - `embeddings(object_uuid, dim, vector)`  
    Deterministic embeddings per note/chunk. Produced/updated by Indexer.  
    These power hybrid search: lexical + vector.

- **decisions**  
  Per-agent “opinions” / classifications:
  `decisions(id uuid, object_uuid uuid, key text, value jsonb, created_at timestamptz)`  
  Examples: duplicate-of, trust score, readiness score.

- **audit**  
  `audit(id uuid, object_uuid uuid, agent text, action text, ts timestamptz, trace_id text, details jsonb)`  
  Append-only activity log. Every agent step writes here. This is how we reconstruct “why did that change.”

- **agent_memories**  
  `agent_memories(id uuid, run_id uuid, layer text, payload jsonb, provenance jsonb, created_at timestamptz)`  
  Episodic memory per agent run. Lets an agent recall prior context / decisions without mutating the canonical object directly.

- **sets / membership**  
  Logical groupings like “Evergreen,” “Published,” etc.  
  `sets(id uuid, name text)` and `membership(id uuid, set_id uuid, object_uuid uuid)`.  
  Projector + Promotion Agent ensure that once content is “ready,” it's assigned to the right set(s).

- **Vault mirror (Markdown as human surface)**  
  The human-facing source of truth is still Markdown with YAML frontmatter.  
  Frontmatter keys like `uuid`, `kind`, `review_state` are mirrored into `objects.payload`.  
  Agents MUST:
  - keep `uuid` stable
  - never regress `review_state`
  - preserve provenance / citations
  - avoid silently dropping references

**Deterministic safeguards:**
- UUID immutability is enforced at the agent layer.
- review_state only advances forward.
- Provenance / references are not discarded.
- We do not “just overwrite” a note because it's newer; we merge semantically and explain why.

---

## 3. Eventing, PER Loops & Observability

### PER loop
All agents follow Plan → Execute → Reflect:
1. **Plan:** Look at object/event/state, decide intended action.
2. **Execute:** Perform the action (update DB, mutate frontmatter, move file, write embeddings…).
3. **Reflect:** Emit an event and write audit + episodic memory, including `trace_id`.

This pattern is consistent across Normalizer, Promotion Agent, MergeResolverAgent, etc.

### Outbox-driven events
We emit domain events like:
- `ingest.object.created`
- `merge.intent.created`
- `promote.intent.created`
- `promote.done`
- `cleanup.done`

These go to an append-only JSONL “outbox” / event log and can be replayed. Some flows also use Redis for fan-out. The outbox is what downstream workers consume (Indexer, Promotion, etc).

We also enforce an SLA / quality gate around propagation times. Example: promotion intent → promoted+indexed should hit search within ~2 seconds (QAS-010).

### Traceability
- Each agent run creates spans (`start_span(...)`).
- Each span carries a `trace_id`.
- We persist `trace_id` in `audit` and in emitted events.
- Jaeger can visualize full agent runs, including Promotion Agent or merge resolution.

---

## 4. Pipelines

### 4.1 Ingestion & Indexing
1. **Normalizer**  
   - Ingests raw Markdown or external text.
   - Ensures the note has a UUID and a valid frontmatter (`review_state`, etc).
   - Writes/updates `objects` and initial audit + episodic memory.
   - Emits `ingest.object.created`.

2. **Classifier**  
   - Assigns taxonomy, tags, trust scores.
   - Persists decisions in `decisions`.

3. **Chunker**  
   - Breaks the note body into semantic spans.
   - Writes `chunks`.

4. **Deduper**  
   - Detects near-duplicates / superseded content.
   - Writes `duplicate_of` style decisions.

5. **CitationChecker**  
   - Flags missing citations / weak provenance.
   - Can block promotion.

6. **Indexer**  
   - Generates deterministic embeddings.
   - Upserts into `embeddings` and `objects`.
   - Re-runs whenever body text or `review_state` changes.
   - Powers hybrid `/search`.

7. **Reviewer & SetEvaluator**  
   - Reviewer aggregates provenance & quality, writes review decisions and episodic memory.
   - SetEvaluator scores “is this ready to surface?”

8. **Projector**  
   - Ensures membership in logical sets (“Evergreen”, etc).
   - Publishes objects outward (export / vault mirror) in a consistent way.

Result: any note in the vault becomes an indexed, retrievable object with provenance, decisions, embeddings, and set membership.

---

### 4.2 Promotion Flow
**Goal:** remove manual Obsidian curation.

- Human action in the vault (like “mark this ready”) generates `promote.intent.created`.
- **Promotion Agent**:
  - Applies cooldown/idle detection and idempotence (don't promote while still being edited; don't promote twice).
  - Updates YAML frontmatter (`review_state: promoted`).
  - Emits `promote.done`, plus structured audit with `trace_id`.
  - Optionally schedules or performs physical file moves based on policy (for example: moving from `@Inbox` to an Evergreen folder).
  - Triggers reindex so the promoted version is immediately searchable and boosted.

This replaces “manually move the note / update state by hand.” Frontmatter becomes the product truth for lifecycle state. The Promotion Agent is just enforcing policy on top.

---

### 4.3 Merge Flow (Semantic merge)
**Problem:** Same note edited in parallel on two machines / branches → traditional git merge creates garbage.  
**Solution:** MergeResolverAgent.

Flow:
1. A merge conflict triggers `merge.intent.created` (conceptually) or calls the CLI merge driver with `BASE`, `OURS`, `THEIRS`.
2. `merge_note_from_blobs(base, a, b)`:
   - `diff_conflict_loci()` splits the conflict into loci: a YAML/frontmatter locus and a body locus.
   - `judge_locus()` (LLM arbiter + deterministic fallback) scores each locus:
     - prefer concise, structured text over rambly walls of text,
     - carry across useful references/links,
     - penalize dumping huge code blocks into concept notes,
     - enforce invariants (uuid must match or we bail; review_state cannot regress).
   - `apply_decisions()` reassembles a single merged note with exactly one frontmatter block + resolved body.

3. Output contract:
   - `merged_text`
   - `info.status` in `{resolved, prompted, conflict}`
   - `info.reason` (short human explanation / rationale)

4. Safety rails:
   - If the UUIDs in `OURS` and `THEIRS` differ, we **do not merge**. We emit `status="conflict"` and exit non-zero.
   - We never silently downgrade `review_state`.

CLI:
- `app/cli/merge_driver.py` wraps all of this.
- It prints:
  - the merged Markdown
  - a trailer with `MERGE_STATUS=` and `MERGE_REASON=`
- Exit code:  
  - `0` if `status=="resolved"` (safe auto-merge)  
  - non-zero otherwise (`prompted`, `conflict`) so git knows to ask a human.
- Today it writes merged output to stdout instead of mutating the working copy directly. The git merge driver wiring (redirect stdout → %A, ensure `%A` gets updated) is planned for v4.4.

Tests:
- `tests/agents/test_merge_resolver.py`
- `tests/smoke/test_merge_smoke.py`
- `tests/cli/test_merge_driver.py`

These assert:
- Frontmatter is preserved and only appears once.
- `review_state` never regresses.
- We always return `status` and `reason`.
- UUID mismatch forces non-zero exit.

---

### 4.4 Hygiene Flow
**Goal:** keep the vault clean so garbage doesn’t poison retrieval or promotion.

- After ingest or merge, we may emit `cleanup.intent.created`.
- **NoteHygieneAgent** runs:
  - If note is basically “title + URL” → salvage a minimal clean summary instead of throwing it away.
  - If note is frontmatter-only / basically empty → mark `review_state: archived` so it won’t be boosted.
  - If huge JSON / log dump ends up in a concept note → move that blob to an attachment/parking path and leave behind a clean pointer.
- Emits `cleanup.done` plus audit + trace_id.
- Guarantees we don’t spam Promotion / Indexer / Search with junk.

This agent is already implemented and tested. The periodic scheduling (launchd/cron/worker loop) is planned to formalize hygiene as a background maintenance task under v4.4.

---

## 5. Agent Summary (PER loops)

All agents follow PER and emit traceable events:
- **Normalizer**
- **Classifier**
- **Chunker**
- **Deduper**
- **CitationChecker**
- **Indexer**
- **Reviewer**
- **SetEvaluator**
- **Projector**
- **Promotion Agent**
- **MergeResolverAgent**
- **NoteHygieneAgent**

Shared properties:
- They all write `audit` rows with `trace_id`.
- They all update `agent_memories` so future runs can reflect / reason.
- They all respect invariants: UUID never changes; review_state only advances; provenance is preserved.

---

## 6. Testing & CI

### Smoke / CI gates
- `pytest -q` runs full unit + integration tests for ingestion, promotion, merge, hygiene, indexer, etc.
- `make smoke` runs the critical contract tests:
  - `test_settings_schema` (system-settings.yaml must match schema)
  - indexing rules / ignore rules
  - end-to-end promotion worker roundtrip (intent → promoted → indexed)
  - promotion smoke (cooldown/idempotence policy)
  - merge smoke (frontmatter preserved, UUID stable, `status`/`reason` present, non-regression of `review_state`)
  - merge driver CLI roundtrip

These smoke tests are what we intend to enforce in GitHub Actions for PRs during v4.4:
- if merge safety breaks → block the PR
- if promotion flow breaks → block the PR
- if settings schema drifts → block the PR

### Observability checks
- We already emit spans (OpenTelemetry) and can ingest them in Jaeger.
- CI does not yet assert the presence/shape of spans; adding that is a v4.4 item.

---

## 7. Roadmap Hooks

- **v4.4 focus:**  
  - Wire the merge driver into git for real. Update `%A` directly or redirect stdout into `%A`. Non-zero exit when human intervention is needed.  
  - Add hygiene as a scheduled job + smoke assertions.  
  - Make promotion spans appear in Jaeger with `trace_id` and capture `promote.done` in tests.  
  - Enforce smoke (settings schema, merge safety, promotion path) in GitHub Actions.

- **Broker ADR / scaling path:**  
  We are drafting an ADR for a broker-backed outbox (Debezium/Kafka). Target SLA: ingestion or promotion intent → indexed and searchable in ≤2 seconds across processes. This is exploratory for v4.4+.

- **v5.0 direction:**  
  A reasoning / governance layer:  
  - Represent claims/relationships symbolically (triples / SHACL-style constraints).  
  - Add a Guard/Reasoner agent that can validate consistency and provenance, and surface contradictions or missing sources.  
  - Keep this as a governed layer on top of AMG instead of hard-wiring OWL/SHACL reasoning into the core DB.  
  - Human still approves promotion of “facts”, so hallucinations can’t silently become canonical.

---