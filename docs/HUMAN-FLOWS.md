# Human Flows — Agentic PKM

## 1. Purpose & Scope
- This document states the intended behavior of the Agentic PKM system from the human (Rasmus) perspective, not the code structure.
- It complements `docs/ARCHITECTURE.md` and `docs/STATUS.md`: those describe internals and current state; this file is the human-facing contract for how core flows should feel and behave.
- Applies to the PKM-Alpha vault surface plus the Agentic PKM runtime (ObjectStore, SetDB, Reasoning Layer, Outbox-driven agents incl. DeliberationAgent, etc.), covering both ingestion and ASK/reasoning loops.
- I den här dokumentationen avser “PKM-Alpha vault” samma Obsidian-valv som nu kallas Mimer – kunskapsmodulen i det större systemet Yggdrasil.

## 2. Mental Model: Layers and Roles
- **Surface layer (Obsidian PKM-Alpha vault)** — Human-authored notes, minimal frontmatter, free linking; this is where the human reads and writes.
- **System layer** — `ObjectStore` / `SetDB` hold UUID-based knowledge objects; a metadata mirror lives under `System/Metadata/VaultMirror/.../uuid.md`; Outbox emits events that drive agents and downstream stores.
- **Key agents (as seen by the human)** — Ingest/Normalizer (pulls notes safely), Classifier (proposes types/facets), ASK/QA (answers questions), DeliberationAgent (multi-step deliberation for ASK), SetEvaluator (ranks/evaluates candidates), Planner/Orchestrator (orders work), PanelAgent (handles AI panels in notes), Promotion/Evergreen logic (moves maturity forward). These collaborate to keep vault writing human-first while the system maintains structure underneath, and reasoning är en grundförmåga som alla agenter kan använda.

### Per-noteloggen (maskinlogg)
- För varje note med `uuid` finns en speglad metadatafil `uuid.md` i `System/Metadata/VaultMirror/<vault-relativ path>/`.
- Samma fil är både metadata-spegel och per-note-logg: här kan systemet samla agentbeslut, promotionshistorik, konfliktlösning och proveniens från satelliter.
- Den är den kanoniska maskinlogg-/historikfilen för noten och fungerar som synk-/merge-ankare mellan master och satelliter.
- Den mänskliga noten hålls ren; maskinbrus hör hemma i spegelns `uuid.md`.

## 3. Core Flows (From the Human’s Perspective)

### 3.1 Creating and editing notes in Obsidian
- When the human creates or edits a note in the PKM-Alpha vault, the system ensures a stable `uuid` in frontmatter (often stored as an Obsidian link like `[[uuid]]`).
- Ingestion mirrors the note into ObjectStore and into `System/Metadata/VaultMirror/.../uuid.md` without generating duplicate objects for the same note.
- The note body remains untouched by the system; no extra or noisy frontmatter appears beyond the agreed essentials.

### 3.2 Ingestion and classification
- Ingestion only treats files as new/changed when their content or relevant metadata actually changed; it is safe and idempotent to re-run.
- Classification proposes types and facets (task, meeting note, entity card, concept, etc.) and records a “pending user confirmation” state until the human confirms.
- Human choices take precedence: the system never overwrites a human-chosen classification unless the human explicitly reclassifies.
- Some classifications can trigger automations or flows, but only after alignment with explicit human intent.

### 3.3 AI Panels in notes
- An AI panel is a discrete, temporary block delimited by *AI comment fences* and structured headings:

  ```
  %% AI:Start %%
  ## AI-instruktion
  ...
  ## AI-åtgärder
  ...
  ## AI-logg
  ...
  %% AI:End %%
  ```

  The fence rule is forgiving: any Obsidian comment line that starts with `%%` (ignoring leading spaces) and contains `ai` (case-insensitive) opens a panel; the next such line closes it; the third opens the next, etc. Older notes that only use the headings without fences are still treated as panels, but new panels should use fences.
- Panel content is *not* part of the knowledge base and must not be indexed or used as facts.
- Suggestions appear as simple checkboxes inside `## AI-åtgärder`, e.g.:
  - `[ ] Category: Concept`
  - `[ ] Category: Entity / Company`
- When the human checks an option, the system updates classification in ObjectStore/metadata accordingly; once handled, the entire panel disappears (checked and unchecked options are removed).
- Panels are optional; any note may have zero, one, or several panels.

### 3.3.1 Validate panel stripping in alpha runs
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
  grep -i "AI-instruktion" /tmp/index-outbox-alpha.jsonl || echo "no AI headings in outbox"
  ```

- Without `--reset-outbox`, the outbox may contain historic events (including older, pre-fix panel content). Use a fresh path or `--reset-outbox` for clean validation.
- `--reset-outbox` truncates the JSONL file; it is intended for local experiments/regression checks and should not run in automated or production flows.

### 3.4 Questions, ASK, and reasoning
- `/api/ask` answers are grounded in actual notes and metadata; the response surfaces which notes/paths contributed to the answer.
- Reasoning is multi-step (planning/evaluation when relevant), not a single opaque LLM call; if the system speculates beyond vault facts, it clearly signals that it is guessing.

### 3.5 Promotion, evergreen notes, and long-term memory
- “Promote” / “make evergreen” means advancing a note’s maturity so it becomes durable long-term memory (zoner alignment can still vary: Active/Warm/Cold).
- Promotion/Evergreen logic updates frontmatter in a predictable, documented way, may move files according to policies, and logs actions in the metadata mirror.
- The human-written note content is never rewritten by automation; only agreed frontmatter fields change and moves happen transparently.

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
- `vault-alpha-ingest` ingests Concepts (and optionally `Test/Alpha-HumanFlows.md`), strips AI panels, writes VaultMirror `uuid.md` files when missing, and populates the configured Store backend plus the in-process HybridStore used by ASK; `--force` reingests even when a UUID already exists.
- `alpha-human-flows` orchestrates flows A–F on top of the same ingest path; `--reset-outbox` is a destructive, dev-only flag for local regression checks that truncates the configured index outbox.
- `/api/ask` and the QA agent backends use BM25+embedding hybrid search over the in-process HybridStore, warmed from `store_objects` on first request; answers are the top-hit snippet and sources include doc ids and `source_ref` paths, while zones are not surfaced yet.
- External corpus ingest is not automated; external objects only appear if inserted into the Store with an `origin` such as `external_raw`, and they surface in ASK/status alongside vault entries.
- The CLI `ask` command still routes through the planner/orchestrator pipeline (QA steps fall back to the same hybrid retrieval), while `ingest-vault-root`/`pkm-alpha-ingest` provide quick root-level ingest helpers for the Alpha vault.
