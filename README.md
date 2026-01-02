Agentic PKM — Second-Brain Engine

System-of-Truth baseline: v4.10 (Reality-MVP, locked)
System-of-Truth forward line: v5.5 (PanelAgent Runtime + Watchers)

Agentic PKM is an agentic, event-driven, CI-guarded system for personal knowledge management.
It treats the human writing surface (a Markdown vault) and the cold archive brain (source artifacts) as canonical, portable artifacts.
Operational stores, indexes, outbox events, and receipts are rebuildable mirrors and audit trails — they must never become the only copy of meaning.
SoT v4.10 is the locked Reality-MVP baseline. Ongoing development happens on the v5.x forward line (PanelAgent / Watchers / Satellite Sync / Yggdrasil).

<!-- DOCS-LINKS:BEGIN -->
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Status](docs/STATUS.md)
- [Diagrams](docs/DIAGRAMS.md)
<!-- DOCS-LINKS:END -->

Start here
- `docs/PROJECT_KERNEL.md` — product intent + stability contracts
- `docs/DOCS_INDEX.md` — documentation map and review status

## What works today
- PER-loop ingestion that normalizes Obsidian notes into Core-6 objects, emits canonical outbox events, and keeps deterministic CI guardrails.
- Hybrid retrieval + ASK CLI over the vault plane with flag-gated rerank/reasoning overlays.
- Domain/Plane/Zone boundaries: vault is the human surface, `external_raw` objects stay off the warm plane, and trust layers keep proposals reversible.
- Deterministic CI via the eight-line contract (LATENCY, EVAL, DELTA, RELATION COVERAGE, RELATIONS, DIARIZATION, REASONING, GATES).

## Reality-MVP (SoT v4.10) — what is included
- Hardened ingest of real Obsidian vault folders into ObjectStore + VectorIndex, with tolerant frontmatter handling, error tracking, and resume support.
- Minimal external ingest: a drop folder (txt/md) feeds `external_raw` objects that are indexed but not rendered as notes in the vault.
- ASK FastAPI endpoint that returns answers with sources, latency, and status API/CLI metrics per plane.
- Interim FastAPI GUI for status + ASK (no multi-user collaboration or advanced serendipity features yet).
- Orchestrator Runtime V1 for running external ingest plans, with dual execution paths: direct CLI (`ingest-external`) or plan-driven orchestrator runs (`orchestrate-external`).

## Baseline kernel includes
- Store abstractions (ObjectStore, VectorIndex, RelationIndex, ReasoningStore) with clear interfaces; the human surfaces remain canonical while derived views stay rebuildable.
- Outbox + event-driven pipeline that connects ingestion, indexing, reasoning, planning, and promotion gates via structured events.
- Typed relations + promotion gates so objects carry explicit provenance links before promotion.
- Reasoning Layer v1 (Claims, Evidence, Inferences) that feeds reasoning-aware promotion policies.
- Planner agent (LLM or deterministic mock) that turns reasoning artifacts into structured plans.
- A2A protocol for agent-to-agent coordination, plus an Orchestrator Runtime V1 that validates steps and records deterministic audit logs.
- Deterministic CI via the 8-line contract (LATENCY, EVAL, DELTA, RELATION COVERAGE, RELATIONS, DIARIZATION, REASONING, GATES).

## Orchestrator Runtime (v4.10 — V1)
The runtime validates each plan step, logs `orchestrator.step.started|finished|error`, and runs the corresponding MCP tool or agent call.
- `agent_call` talks over A2A; default agents respond `not_implemented` when a step lacks support.
- `tool_call` validates MCP descriptors and uses mock results when real tools are unavailable.
All failures propagate through `orchestrator.step.error` so plan status can be reconstructed deterministically.

## Quickstart
Install dependencies under the virtualenv:

```bash
python -m pip install --upgrade pip
pip install -e .
pip install pytest
```

Run the pipeline with mock LLMs and the in-memory store:

```bash
export STORE_BACKEND=memory
export LLM_PROVIDER=mock
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

python -m app.cli pipe /tmp/demo.md
python -m app.fitness.report
python -m app.cli yggdrasil-init --root /tmp/yg-demo
LLM_TRACE_PATH=/tmp/llm-trace-sample.jsonl python -m app.cli llm-trace-sequence --latest --format mermaid > /tmp/llm-trace-seq.md
```

You should see the eight-line CI summary: LATENCY / EVAL / DELTA / RELATION COVERAGE / RELATIONS / DIARIZATION / REASONING / GATES

## Golden Path (Alpha)

```bash
export VAULT_ROOT="/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha"
export VAULT_INBOX_DIR_REL="Inbox"
export VAULT_RUNTIME_DIR_REL="System/Runtime"
export VAULT_SYSTEM_DIR_REL="System"
make alpha-down || true
make alpha-up
python scripts/alpha_e2e.py
make alpha-smoke
```

The canonical flow is `make alpha-up` → `python scripts/alpha_e2e.py` → `make alpha-smoke`. `VAULT_INBOX_DIR_REL` defines the watcher scope, `VAULT_RUNTIME_DIR_REL` defines where alpha_e2e writes its temporary runtime note (under `<runtime_dir_rel>/alpha_e2e`), and `VAULT_SYSTEM_DIR_REL` controls where health settings live. The alpha_e2e note is deleted after success; on failure it is kept unless you run with `--teardown`.

Optional checks:
- `make alpha-status`
- `make alpha-doctor`
- `make alpha-e2e`

Note: `/api/health` can report `ok=false` when optional tools are missing; in Alpha runtime, ffmpeg is bundled in the container image, so a missing ffmpeg check indicates a build/runtime issue. Treat `required_ok` as the gating signal.

## Alpha Compose Runtime

The canonical Alpha Compose Runtime runs `db`, `api`, `watcher`, and `worker` in Docker Compose. The watcher writes audit events (JSONL) and enqueues DB outbox events. The worker consumes the DB outbox to perform ingest and promotion side effects, while the API surfaces status and health.

Deprecated: `scripts/run_alpha_stack.sh` and `scripts/run_alpha_live.sh` are legacy helpers; use `make alpha-up` (which calls `scripts/start_full_system.sh`) instead.

## Alpha quickstart (Docker)

```bash
export VAULT_ROOT="/path/to/your/vault"
make alpha
curl -sS http://127.0.0.1:18000/api/status
```

Bootstrap a fresh environment (doctor is read-only):

```bash
export VAULT_ROOT="/path/to/your/vault"
make alpha-bootstrap
```

Run with Ollama-backed LLMs (reads provider defaults from vault settings):

```bash
export VAULT_ROOT="/path/to/your/vault"
make alpha-up-ollama
```

Check environment readiness (read-only):

```bash
export VAULT_ROOT="/path/to/your/vault"
make alpha-doctor
```

Stop services:

```bash
make alpha-down
```

### Run Reality-MVP HTTP API locally

From the repo root:

```bash
source .venv/bin/activate

export STORE_BACKEND=pg
export DATABASE_URL="postgresql+psycopg://app:app@localhost:15432/app"
export VECTOR_BACKEND=pgvector

uvicorn app.main:app --reload --port 18000
```

- GET http://127.0.0.1:18000/api/status → system status snapshot
- POST http://127.0.0.1:18000/api/ask → ASK pipeline with sources + latency

### Bootstrap data for the dashboard & ASK

The dashboard and `/api/ask` look empty until an object is ingested into the ObjectStore and indexed.
If `vault: 0` and `external: 0` in the Stores table and ASK returns “No results found,” rerun ingest for the current `STORE_BACKEND` / `DATABASE_URL`.

```bash
source .venv/bin/activate

export STORE_BACKEND=pg
export DATABASE_URL="postgresql+psycopg://app:app@localhost:15432/app"
export VECTOR_BACKEND=pgvector

python -m app.cli ingest-vault-root --limit 25
```

Check object counts with:

```bash
python -m app.cli status
```

Then reload the dashboard at http://127.0.0.1:18000. The Stores table should show non-zero counts, and ASK will have retrievable objects.

If counts stay zero, verify you used the same STORE_BACKEND and DATABASE_URL when running uvicorn and the ingest command.

## Architecture — SoT v4.10
This document focuses on the runtime and data model for the Mimer module (vault ingest + indexing + agents) within Yggdrasil.
See `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md` for the bigger system map and `docs/HUMAN-FLOWS.md` for the human experience.

### Agent pipeline
```
vault/markdown
    ↓ normalize        (Core-6 frontmatter)
    ↓ classify         (LLM or mock)
    ↓ chunk            (diarization-aware)
    ↓ embed            (VectorIndex + hybrid retrieval + optional rerank)
    ↓ relate           (typed relations)
    ↓ reason           (claims, evidence, inferences)
    ↓ plan             (Planner Agent — LLM or mock)
    ↓ orchestrate      (Orchestrator — executes plan via A2A + MCP)
    ↓ promote          (promotion gates + audit)
```

### Stores (operational persistence layer)

| Store | Function |
| --- | --- |
| ObjectStore | Markdown objects + outbox event payloads |
| VectorIndex | Embeddings + hybrid retrieval + rerank |
| RelationIndex | Typed relations + coverage/validity guards |
| ReasoningStore | Claims/Evidence/Inference graphs |
| PlanStore (v4.10) | Logs plans, steps, and execution graphs |

All persistence flows through stores; canonical meaning remains anchored in warm notes and cold archive artifacts.

## Event-driven model
Agents emit outbox events such as `object.created`, `index.object.embedded`, `relation.added`, `reasoning.claim.added`, `plan.created`, `a2a.request.created`, `a2a.response.created`, and `promote.done`.
The envelope (`event`, `trace_id`, `source`, `timestamp`, `payload`, `meta`) is shared across memory and Postgres backends.
Events carry metadata so pipelines can be traced without changing human-facing flows.

## A2A protocol (Agent-to-Agent)
Introduced in v4.8 and fully implemented in v4.10.
- JSON schema validates every request.
- Request/Response/Error pairs share a trace_id for correlation.
- All agents implement `async def handle_agent_request(self, request: A2ARequest) -> A2AResponse`.
A2A enables the Orchestrator to run plan steps deterministically.

## Planner Agent (LLM-driven planning)
Planner produces structured plans with:
```
Plan:
  id: UUID
  steps: List[PlanStep]
  metadata: PlanMetadata
```
Plans ship when `PLANNER_ENABLE=1`.
Providers: deterministic mock (CI-safe) and optional LLM (Ollama / OpenAI-compatible endpoint).
Plans and steps log to PlanStore and the outbox for audit.

## Orchestrator Runtime
The runtime reads plans, executes them via A2A or MCP tools, and logs each step with `orchestrator.step.*` events.
Step validation (unique IDs, satisfied dependencies) happens before execution.
Execution is sequential in v4.10 but flag-gated with `ORCHESTRATOR_ENABLE`.
Errors always produce `orchestrator.step.error` so state can be rebuilt deterministically.

## Reasoning Layer v1
Claims, Evidence, and Inferences are schema-validated structures that feed the relations graph and promotion gates.
A deterministic MockDeliberationAgent keeps CI runs reproducible.

## Watcher readiness and panel flows
- Vault Watcher (v5.1–v5.5) watches Obsidian files, batches edits, ingests changed notes, and triggers PanelAgent runtime when frontmatter policies allow it.
- `vault-watcher-run` (v5.2 CLI) polls snapshots, runs ingest/panel flows, emits summaries, and respects dry-run / `--max-notes` guards.
- Frontmatter controls (`ai_panel_auto_run` / `ai_panel: { auto_run: watcher|manual|never }`) gate watcher automation.
- Watchers remain opt-in and auditable; they reuse CLI entrypoints rather than inventing new pipelines.

## Promotion and relations
The promotion consumer uses typed relations to decide when to promote or block notes.
Overrides (e.g., `PROMOTION_ALLOW_ORPHANS=1` with a recorded reason) emit audit entries and log entries like `promote.orphan.override`.

## Note ingestion defaults
- Notes always gain a UUID (`ensure_note_uuid`) before panel/update flows; missing UUIDs are healed and logged.
- Default mode leaves note moves disabled; `promotion` logs `promote.skip.move` instead of moving files.
- Flags and policies control when automation crosses boundaries; human intent stays authoritative.
