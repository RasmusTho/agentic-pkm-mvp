Perfekt, vi gör två saker nu in one go:
	1.	En uppdaterad README som matchar hur systemet faktiskt ser ut nu (v4.3.1→v4.4), med rätt ordning (promotion / merge / hygiene / smoke).
	2.	En arkitekturöversikt (text + enkel ASCII-diagram) som visar alla komponenter runt systemet så att du kan se helheten igen.

Du kan ta hela blocket nedan och skriva över din README.md rakt av.

# Agentic PKM — SoT v4.3.1 → v4.4

Personal knowledge system with:
- file-first notes (Markdown + YAML frontmatter),
- ingestion & promotion automation,
- semantic merge and hygiene agents,
- hybrid search (BM25-lite + pgvector),
- full audit trail and traceable agent decisions.

The goal is to make a second brain that can scale, stay consistent, and keep context clean — without needing plugins, SaaS lock-in, or manual babysitting.


## 0. Mental model (high level)

You keep notes in a vault (Markdown with frontmatter like `uuid`, `review_state`, etc).

Agents run in PER loops (Plan → Execute → Reflect). They:
- ingest and normalize notes into Postgres (SetDB / AMG),
- chunk + embed them for search,
- auto-promote them when you “intend to promote,”
- semantically merge conflicts instead of doing last-write-wins,
- clean junk / archive trash via hygiene,
- emit events, audit, and spans so you always know what happened.

Everything is deterministic, diffable, and testable locally.


---

## 1. Runtime

- Platform: macOS (Apple Silicon) or Linux
- Python: 3.14 in `.venv`
- Containers: Docker + Docker Compose
- DB: Postgres 16 with pgvector
- Optional: Redis if you want fan-out / queue-like behavior
- Optional: Ollama for local LLMs (llama3.*, deepseek-r1)
- Tracing: Jaeger via OTLP (optional, gated by settings)

### Process surfaces
- FastAPI (`api/`) for query and service endpoints
- Background workers (promotion worker, etc.)
- LangGraph-based agents (PER loops)
- CLI tools under `app/cli/` (e.g. semantic merge driver)
- Smoke tests and system tests (`make smoke`, `pytest -q`)


---

## 2. Setup (current dev workflow)

### 2.1 Create venv + install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

2.2 Start Postgres locally

docker compose up -d db
export DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app"
PYTHONPATH="$(pwd)" alembic upgrade head

Your Postgres holds:
	•	objects (canonical notes as structured payloads)
	•	chunks + embeddings (for retrieval)
	•	agent_memories, audit, etc.

2.3 (Optional) local LLMs

brew install ollama
OLLAMA_FLASH_ATTENTION="1" OLLAMA_KV_CACHE_TYPE="q8_0" ollama serve &
ollama pull llama3.1:8b
ollama pull deepseek-r1:8b

export LLM_PROVIDER=ollama
export LLM_MODEL="llama3.1:8b"
export LLM_REASONING_MODEL="deepseek-r1:8b"

If no LLM is available, we fall back to deterministic heuristics for merge/hygiene, and tests still pass.

2.4 Initialize / validate settings

System policy is defined in YAML and treated like code.
	•	Canonical config lives in:
vault/_system/settings/system-settings.yaml
	•	Validate policies and vault layout:

make smoke

make smoke runs schema validation, promotion roundtrip, merge smoke, hygiene, etc.

2.5 Run full test suite

PYTHONPATH="$(pwd)" \
DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" \
pytest -q

2.6 API (optional)

docker compose up -d api

Default listen: http://localhost:18000
Used for search and other service endpoints during development.

⸻

3. Core flows in the system

### 3.0 Capture Layer (External sources → Vault + DB)

Before ingestion even starts, **Capture Agents** bring external material into your system automatically.  
Examples include pulling documents from a “drop” folder, scraping meeting notes, ingesting email attachments, OCRing screenshots, or importing chat logs.

Each capture agent:
- creates a Markdown note with YAML frontmatter in your vault (usually under `@Inbox`),
- mirrors that same content into Postgres (`objects`, `chunks`, `embeddings`),
- records provenance (`origin`, timestamps, `source_ref`),
- emits a `capture.object.created` event.

Result: your vault becomes the *total memory surface* — everything you’ve written **and** everything you’ve ever seen.  
You may not curate or even read most of it, but it’s indexed, contextualized, and ready to surface when needed.

The lifecycle agents then take over (Normalizer, Chunker, Indexer, etc.), refining the content and maintaining consistency between the vault and the database.

3.1 Ingestion & Indexing

Agents run in a PER loop:
	1.	Normalizer
	•	Reads a Markdown note, stabilizes required frontmatter (uuid, review_state, etc.)
	•	Creates/updates the canonical objects row in Postgres.
	•	Locks immutables (uuid never changes).
	2.	Classifier
	•	Tags, trust assessment, categorization.
	3.	Chunker
	•	Splits content into semantically meaningful spans and stores them in chunks.
	4.	Indexer
	•	Embeds each chunk.
	•	Writes to embeddings using pgvector.
	•	Also supports deterministic embeddings as fallback (no GPU needed).
	5.	Reviewer / SetEvaluator / Projector
	•	Reviewer: builds provenance, quality assessment.
	•	SetEvaluator: decides if it’s ready for promotion / publication.
	•	Projector: projects approved content into “published sets” or surfaced collections.

The result: searchable, structured memory with provenance you can interrogate later.

3.2 Promotion Flow
	•	You express intent to promote (e.g. “this is ready” via a flag/checkbox/intent event).
	•	promote.intent.created lands in the outbox.
	•	Promotion Agent:
	•	Enforces cooldown (don’t promote notes that are still thrashing),
	•	Updates frontmatter to review_state: promoted,
	•	Emits promote.done,
	•	Optionally schedules file moves (batch / nightly),
	•	Triggers reindex so search surfaces the promoted version.

No Obsidian plugin required. Frontmatter is the single source of truth for lifecycle state.

3.3 Semantic Merge Flow

Problem: You edited the same note on two machines. Git gives you A vs B.
	•	We generate merge.intent.created.
	•	MergeResolverAgent:
	1.	Diffs YAML frontmatter separately from body.
	2.	Judges each “locus” (frontmatter locus, body locus) with rules:
	•	Never let review_state go backwards (promoted must not become draft).
	•	Never change uuid.
	•	Prefer concise text over rambly text.
	•	Preserve useful reference lists / links.
	•	Penalize giant code dumps in concept notes.
	3.	Assembles a single merged Markdown doc.
	4.	Returns:
	•	status: "resolved", "prompted", "conflict"
	•	reason: human-readable rationale
	•	final merged note text

We expose this as a CLI tool:
app/cli/merge_driver.py

It:
	•	Reads BASE, OURS, THEIRS.
	•	Runs semantic merge.
	•	Writes the merged result.
	•	Returns exit code 0 only if status == "resolved".

There’s also a simple fallback when UUIDs don’t match: we refuse to auto-merge and force human review rather than silently corrupting.

This CLI is on track to become the repo’s custom git merge driver for *.md.

Tests:
	•	tests/agents/test_merge_resolver.py
	•	tests/smoke/test_merge_smoke.py
	•	tests/cli/test_merge_driver.py

3.4 Hygiene Flow

After merge (or after ingestion), notes can be ugly:
	•	Only a title and a link,
	•	Just frontmatter and nothing else,
	•	Giant JSON/log blob pasted into a concept note.

NoteHygieneAgent runs a cleanup pass:
	•	Salvages minimal content into a short summary,
	•	Archives “frontmatter-only” notes (review_state: archived),
	•	Moves oversized dumps somewhere safe and leaves a pointer,
	•	Emits cleanup.done.

This keeps the vault usable over time so promoted content stays high-signal.

3.5 Events, Audit & Tracing

Every agent writes:
	•	an audit row (agent name, action, trace_id),
	•	and an event to an outbox (JSONL) such as:
	•	ingest.object.created
	•	promote.intent.created / promote.done
	•	merge.intent.created / merge.resolved
	•	cleanup.done

trace_id propagates through all of this so you can reconstruct “why did this note change?” later.

If runtime.enable_tracing: true in settings and OTLP endpoint is configured, we export spans to Jaeger so you can see timing and decisions across agents.

⸻

4. Search / Retrieval model

We support hybrid retrieval:
	•	BM25-lite / tsvector-style lexical search for fast keyword match,
	•	pgvector similarity search for semantic match,
	•	then we blend results before returning.

Because we also store provenance, we can in principle answer:
“Show me what I said about X after it reached review_state: promoted with source links.”

⸻

5. CLI tooling
	•	make smoke
Runs schema validation, promotion roundtrip, merge smoke, hygiene checks.
This is meant to gate CI.
	•	app/cli/merge_driver.py
Future git merge driver for Markdown notes. Emits merged note + status/reason.
Exit code 0 = safe to apply, non-zero = human review.
	•	(planned) make merge-dryrun BASE=... A=... B=...
Helper to exercise the merge driver manually.

⸻

6. CI state
	•	Local smoke is green.
	•	We plan to wire make smoke into GitHub Actions so PRs are blocked if:
	•	promotion flow regresses,
	•	merge resolver breaks determinism,
	•	hygiene stops archiving garbage,
	•	settings schema drifts.

We will also add:
	•	Jaeger span visibility check (optional),
	•	deterministic safety checks (uuid must not change, review_state must not regress),
	•	merge driver contract test.

⸻

7. System topology (who talks to who)

Below is the current mental map with all major moving parts and external deps.

                     ┌───────────────────────────────┐
                     │           You (human)         │
                     │ - Edit Markdown notes locally │
                     │ - Git commit / merge          │
                     │ - Mark stuff "ready"          │
                     └───────────────┬───────────────┘
                                     │
                          Vault (Markdown+YAML)
                          e.g. vault/.../*.md
                          frontmatter: uuid, review_state, ...
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
         │                           │                           │
         ▼                           ▼                           ▼
┌───────────────────┐      ┌──────────────────────┐     ┌─────────────────────┐
│ Promotion Agent   │      │ MergeResolverAgent   │     │ NoteHygieneAgent    │
│ (PER loop)        │      │ (PER loop)           │     │ (PER loop)          │
│ - watches         │      │ - handles conflicts  │     │ - cleans junk /     │
│   promote.intent  │      │   between branches   │     │   archives trash    │
│ - updates         │      │ - enforces uuid +    │     │ - emits cleanup.*   │
│   review_state    │      │   review_state rules │     └─────────┬───────────┘
│ - emits promote.* │      │ - emits merge.*      │               │
└─────────┬─────────┘      └──────────┬───────────┘               │
          │                           │                           │
          │                           │                           │
          ▼                           ▼                           ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │            Ingestion / Indexing Pipeline (PER agents)            │
   │  Normalizer → Classifier → Chunker → Indexer → Reviewer →        │
   │  SetEvaluator → Projector                                        │
   │                                                                  │
   │  - Writes canonical objects, chunks, embeddings into Postgres    │
   │  - Computes promotion readiness / set membership                 │
   │  - Emits ingest.*, review.*, promote.done, etc.                  │
   └───────────────┬──────────────────────────────────────────────────┘
                   │
                   ▼
          ┌───────────────────────┐
          │ Postgres (SetDB/AMG)  │  <-- pgvector
          │ objects / chunks /    │
          │ embeddings / audit /  │
          │ agent_memories        │
          └─────────┬─────────────┘
                    │
                    ▼
          ┌───────────────────────┐
          │ Search / API (FastAPI)│
          │ - hybrid lexical +    │
          │   vector search       │
          │ - query endpoints     │
          └─────────┬─────────────┘
                    │
                    ▼
          ┌───────────────────────┐
          │  You ask questions    │
          │  ("what did I say     │
          │   about topic X?")    │
          └───────────────────────┘

External / optional integrations:
	•	Ollama: for local LLM calls (merge judgement, hygiene decisions).
If it’s off, we fall back to deterministic heuristics and still stay green.
	•	Jaeger (OTLP): to visualize traces (trace_id across steps).
	•	Redis: optional fan-out / broker-like behaviour for events (not mandatory in dev).

⸻

8. Where to look in the repo
	•	docs/ARCHITECTURE.md
Ground truth: runtime model, agents, flows, tracing model.
	•	docs/STATUS.md
Snapshot of current health, per component. Think “what is green right now?”.
	•	docs/ROADMAP.md
Near-term evolution (v4.4 merge/hygiene rollout, v4.5 UX/governance, v5.0 reasoning).
	•	vault/_system/settings/system-settings.yaml
Policy, cooldowns, move rules, tracing toggle, etc.
	•	app/agents/*
Each agent (promotion, merge_resolver, note_hygiene, normalizer, etc.)
lives here under a PER-loop pattern.
	•	app/cli/merge_driver.py
Semantic merge driver (future git merge driver).
	•	tests/
Unit, integration, and smoke.
tests/smoke/ is what we want to enforce in CI.

⸻

9. Current maturity
	•	Promotion Agent: ✅ live, end-to-end tested.
	•	MergeResolverAgent: ✅ implemented, status/reason contract, smoke-tested.
	•	Git merge driver integration: in progress.
	•	NoteHygieneAgent: ✅ implemented, prevents garbage from leaking forward.
	•	Ingestion/Indexing pipeline: ✅ established.
	•	Event outbox & trace_id: ✅ established.
	•	Jaeger/OTLP tracing: available, needs endpoint config.
	•	CI: we’re moving toward “make smoke must pass in PRs,” including merge smoke.

For forward planning, see docs/ROADMAP.md.
For current health, see docs/STATUS.md.
For guarantees and invariants, see docs/ARCHITECTURE.md.

This README is intentionally written for Future Me.
If I come back cold:
	1.	run Postgres + alembic,
	2.	run make smoke,
	3.	look at ARCHITECTURE for how agents fit together,
	4.	read STATUS to see what’s green.
