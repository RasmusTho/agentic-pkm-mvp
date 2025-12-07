State: SoT v4.10 Reality-MVP (current core).
# Human Flows — Agentic PKM

Orientation: This doc is anchored in `docs/SYSTEM_DESIGN_v4.10.md` (global system design). Keep the two in sync when surfaces, dependencies, or flows change.

## 1. Purpose & Scope
- This document states the intended behavior of the Agentic PKM system from the human (Rasmus) perspective, not the code structure.
- It complements `docs/ARCHITECTURE.md`, `docs/STATUS.md`, and `docs/SYSTEM_DESIGN_v4.10.md`: those describe internals, current state, and system design; this file is the human-facing contract for how core flows should feel and behave.
- Applies to the PKM-Alpha vault surface plus the Agentic PKM runtime (ObjectStore, SetDB, Reasoning Layer, Outbox-driven agents incl. DeliberationAgent, etc.), covering both ingestion and ASK/reasoning loops.
- In this documentation “PKM-Alpha vault” refers to the same Obsidian vault now called Mimer—the knowledge module in the wider Yggdrasil system.

## 2. Mental Model: Layers and Roles
- **Surface layer (Obsidian PKM-Alpha vault)** — Human-authored notes, minimal frontmatter, free linking; this is where the human reads and writes.
- **System layer** — `ObjectStore` / `SetDB` hold UUID-based knowledge objects; a metadata mirror lives under `System/Metadata/VaultMirror/.../uuid.md`; Outbox emits events that drive agents and downstream stores.
- **Key agents (as seen by the human)** — Ingest/Normalizer (pulls notes safely), Classifier (proposes types/facets), ASK/QA (answers questions), DeliberationAgent (multi-step deliberation for ASK), SetEvaluator (ranks/evaluates candidates), Planner/Orchestrator (orders work), PanelAgent (handles AI panels in notes), Promotion/Evergreen logic (moves maturity forward). These collaborate to keep vault writing human-first while the system maintains structure underneath, and reasoning is a cross-cutting capability available to every agent.

### Per-note log (machine log)
- For each note with `uuid` there is a mirrored metadata file `uuid.md` in `System/Metadata/VaultMirror/<vault-relative path>/`.
- The same file is both metadata mirror and per-note log: the system collects agent decisions, promotion history, conflict resolution, and provenance from satellites there.
- It is the canonical machine log/history file for the note and serves as the sync/merge anchor between master and satellite runtimes.
- The human note stays clean; machine noise lives in the mirror `uuid.md`.

## 3. Core Flows (from the human’s perspective)

### Capture & Ingest
- When the human creates or edits a note in the PKM-Alpha vault, the ingest path ensures a stable `uuid` in frontmatter (stored as a wikilink `[[uuid]]`).
- Ingestion mirrors the note into ObjectStore and into `System/Metadata/VaultMirror/.../uuid.md` without generating duplicate objects for the same note.
- Ingestion only treats files as new/changed when their content or relevant metadata changed; fingerprint checks (text hash + mtime) drive skips, `--force` bypasses them.
- Classification proposes types/facets via heuristics + optional LLM; it records a provisional decision in the store/decisions table. There is no automated human-confirmation loop yet; human edits to frontmatter override system guesses.
- Alpha ingest writes `uuid` into frontmatter when missing; if only the mirror carries a UUID, ingest writes it back, and if neither exists a new UUID is generated and written to both. The ingest fingerprint lives in mirror + Store; `--force` also heals missing frontmatter/mirrors.

#### Infra touchpoints
- Surfaces: Obsidian vault (Mimer), CLI ingest helpers.
- Agents/components: Watcher/ingest CLI, Normalizer, Classifier, Chunker, Deduper, Indexer.
- Stores: ObjectStore, VectorIndex, VaultMirror, Outbox (events), fingerprints.
- Observability: ingest throughput/errors, outbox events, span traces when enabled.

### ASK
- `/api/ask` answers are grounded in stored objects; responses include contributing notes/paths and latency.
- Execution is a single-pass graph: retrieve (hybrid BM25 + embeddings) → optional rerank → answer. By default the answer is the top-hit snippet; when `REASONING_ENABLE=1` an LLM drafts the answer using the same context.
- Zones are not yet surfaced in answers; `origin`/`path` are included when present in payloads.

#### Infra touchpoints
- Surfaces: CLI `ask`, HTTP `/api/ask`.
- Agents/components: ASK Agent (planner/reranker/answerer).
- Stores: ObjectStore, VectorIndex.
- Observability: ASK latency, hit counts, rerank traces, answer errors.

### Review & Promotion
- “Promote” / “make evergreen” advances maturity so a note becomes durable long-term memory (zones can still vary: Active/Warm/Cold).
- Promotion/Evergreen logic updates frontmatter predictably, may move files per policy, and logs actions in the metadata mirror; note bodies are never rewritten by automation.

#### Infra touchpoints
- Surfaces: CLI/API triggers, Obsidian (frontmatter changes).
- Agents/components: Reviewer, SetEvaluator, Promotion Agent.
- Stores: ObjectStore, Outbox, VaultMirror.
- Observability: promotion/review events, guardrail metrics, spans around frontmatter writes.

### Panel Interaction
- An AI panel is a discrete, temporary block delimited by *AI comment fences* and structured headings:

  ```
  %% AI:Start %%
  ## AI instruction
  ...
  ## AI actions
  ...
  ## AI log
  ...
  %% AI:End %%
  ```

  The fence rule is forgiving: any Obsidian comment line that starts with `%%` (ignoring leading spaces) and contains `ai` (case-insensitive) opens a panel; the next such line closes it; the third opens the next, etc. Older notes that only use the headings without fences are still treated as panels, but new panels should use fences.
- Panel content is *not* part of the knowledge base and must not be indexed or used as facts.
- Checkbox actions can be mapped to internal intents/events (via `vault/_system/panel-actions`); the PanelAgent translates newly checked items into auditable outbox events (`source=panel.agent`) and appends simple log entries so the human can see what happened. Event dispatch to Planner/Orchestrator is flag-gated (`PANEL_EVENTS_ENABLE`); without it, intents are returned but not dispatched.
- Suggestions appear as simple checkboxes inside `## AI actions`, e.g.:
  - `[ ] Category: Concept`
  - `[ ] Category: Entity / Company`
- When the human checks an option, the agent removes one-shot actions and appends a log entry; panels are optional and any note may have zero, one, or several panels.

#### Infra touchpoints
- Surfaces: Obsidian panels.
- Agents/components: PanelAgent, downstream classifiers/promotion hooks.
- Stores: Outbox events (intent), ObjectStore/metadata after actions, VaultMirror logs.
- Observability: panel intent events, outbox volume, optional spans for intent handling.

### Eval & QA (dev-side)
- Dev-side validation keeps panel text out of indexing and ensures ingest/ASK guardrails hold.
- To verify that panel content is not contaminating indexing/QA in the PKM-Alpha vault, use the alpha-human-flows CLI with a clean outbox:

  ```
  export STORE_BACKEND=memory
  export LLM_PROVIDER=mock
  export INDEX_OUTBOX_PATH=/tmp/index-outbox-alpha.jsonl
  python -m app.cli alpha-human-flows --reset-outbox
  ```

- Then inspect the outbox for unwanted panel text:

  ```
  grep -i "two moons" /tmp/index-outbox-alpha.jsonl || echo "no panel contamination"
  grep -i "AI instruction" /tmp/index-outbox-alpha.jsonl || echo "no AI headings in outbox"
  ```

- Without `--reset-outbox`, the outbox may contain historic events (including older, pre-fix panel content). Use a fresh path or `--reset-outbox` for clean validation. `--reset-outbox` truncates the JSONL file; it is intended for local experiments/regression checks and should not run in automated or production flows.

#### Infra touchpoints
- Surfaces: CLI eval runners.
- Agents/components: eval flows, ASK Agent (for QA), ingest pipeline when re-running fixtures.
- Stores: Outbox (fixtures), ObjectStore, VectorIndex.
- Observability: eval run logs, ASK metrics in CI, optional OTLP traces.

## 4. Visibility and Noise (What must never leak into the user surface)
- System metadata never appears in the note body; frontmatter stays minimal (uuid, title, essential Core-6/12 fields), while heavier metadata lives in the metadata mirror or DB.
- AI panel text is never indexed, chunked, or treated as knowledge content.
- Outbox/event noise, agent traces, and other low-level details stay out of the vault reading/writing experience.

## 5. Design Principles (Human-first constraints)
- The human is the ultimate authority for classification and meaning; the system proposes but never silently overrides.
- Every automated action is explainable and traceable back to sources, spans, and mirror artifacts.
- Panels are a conversation space for suggestions/instructions, not part of the knowledge base.
- Metadata and logging remain inspectable (e.g., in `System/Metadata/...`) but unobtrusive in the writing surface.
- Stability first: idempotent operations and predictable frontmatter/move policies keep trust high.

## 6. Guardrails Against Regressions
- Human classification changes (type/category/facets) must never be overwritten by AI without explicit reclassification intent.
- AI panel text must never be included in indexing, chunking, or reasoning inputs as factual content.
- Each note UUID maps to a single canonical metadata object; no duplicate UUIDs in ObjectStore or the mirror.
- Ingestion is idempotent: reruns must not create duplicate objects or stale “changed” events for untouched files.
- System metadata must not pollute the main vault surface; only agreed frontmatter fields appear in notes.
- ASK answers must cite contributing notes/paths; losing source visibility is a regression.
- Promotion/Evergreen steps must not rewrite note bodies; frontmatter and moves follow documented policies with logs in the mirror.

## 7. Current Reality-MVP surfaces (implementation snapshot)
- `vault-alpha-ingest` ingests Concepts (and optionally `Test/Alpha-HumanFlows.md`), strips AI panels, writes/updates VaultMirror `uuid.md` mirrors to match frontmatter, and populates the configured Store backend plus the in-process HybridStore used by ASK; fingerprints live in mirrors/store, skip unchanged notes once the Store is populated, and `--force` bypasses fingerprints/store checks, reingests everything, and heals missing frontmatter (run this after a fresh DB paired with existing mirrors).
- `alpha-human-flows` orchestrates flows A–F on top of the same ingest path; `--reset-outbox` is a destructive, dev-only flag for local regression checks that truncates the configured index outbox.
- `/api/ask` uses BM25+embedding hybrid search over the in-process HybridStore warmed from `store_objects` on first request; answers are the top-hit snippet by default and sources include doc ids and `source_ref` paths; zones are not surfaced yet.
- External corpus ingest is not automated; external objects only appear if inserted into the Store with an `origin` such as `external_raw`, and they surface in ASK/status alongside vault entries.
- The CLI `ask` command routes through the planner/orchestrator pipeline (QA steps fall back to the same hybrid retrieval), while `ingest-vault-root`/`pkm-alpha-ingest` provide quick root-level ingest helpers for the Alpha vault.
