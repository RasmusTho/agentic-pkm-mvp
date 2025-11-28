# Human Flows — Agentic PKM

## 1. Purpose & Scope
- This document states the intended behavior of the Agentic PKM system from the human (Rasmus) perspective, not the code structure.
- It complements `docs/ARCHITECTURE.md` and `docs/STATUS.md`: those describe internals and current state; this file is the human-facing contract for how core flows should feel and behave.
- Applies to the PKM-Alpha vault surface plus the Agentic PKM runtime (ObjectStore, SetDB, Reasoner, Outbox-driven agents, etc.), covering both ingestion and ASK/reasoning loops.

## 2. Mental Model: Layers and Roles
- **Surface layer (Obsidian PKM-Alpha vault)** — Human-authored notes, minimal frontmatter, free linking; this is where the human reads and writes.
- **System layer** — `ObjectStore` / `SetDB` hold UUID-based knowledge objects; a metadata mirror lives under `System/Metadata/VaultMirror/.../uuid.md`; Outbox emits events that drive agents and downstream stores.
- **Key agents (as seen by the human)** — Ingest/Normalizer (pulls notes safely), Classifier (proposes types/facets), ASK/QA (answers questions), Reasoner (multi-step thinking), SetEvaluator (ranks/evaluates candidates), Planner/Orchestrator (orders work), PanelAgent (handles AI panels in notes), Promotion/Evergreen logic (moves maturity forward). These collaborate to keep vault writing human-first while the system maintains structure underneath.

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
- An AI panel is a discrete, temporary block in a note, delimited by `%% AI:Start %%` and `%% AI:End %%`. It is written in human language, not code, and hosts AI suggestions or human instructions.
- Panel content is not ingested into the knowledge base and is never treated as a fact about the world.
- Suggestions appear as simple checkboxes, e.g.:
  - `[ ] Category: Concept`
  - `[ ] Category: Entity / Company`
- When the human checks an option, the system updates classification in ObjectStore/metadata accordingly; once handled, the entire panel disappears (checked and unchecked options are removed).
- Panels are optional; any note may have zero, one, or several panels.

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
