State: SoT v4.10 Reality-MVP (baseline locked) with v5.x forward line extending PanelAgent runtime + watcher track.
# Human Flows — Yggdrasil / agentic-pkm-mvp

> Audience: humans using the system in Obsidian + CLI. Human language is canonical; automation is additive, not authoritative.

## 1. Vault-first, Human-first System
- Keep writing in your vault. Agents run as helpers, not owners.
- The vault is the human surface; agents write traces/logs to side-channels (ObjectStore, Outbox, System folders) without rewriting your prose by default.
- CLI is an agent tooling surface, not the main UI: it exists for automation, reproducible runs, and debugging.

## 2. Scope and Reality-MVP Snapshot (SoT v4.10 + v5.x forward line)
- v4.10 locked baseline: ingest + ASK + observability + orchestrator runtime V1; panels are optional and not indexed as content.
- v5.0 PanelAgent runtime V1 baseline on top of v4.10; v5.1–v5.4 watcher track adds automation, dry-run, max-notes guards, and policy gating. Forward line v5.x continues to extend PanelAgent and watcher ergonomics.

## 3. Human Flow: Capture & Ingest
- Keep frontmatter lean: `title`, `uuid`, optional `type/category/facets`.
- Ingest via `vault-alpha-ingest` (or `ingest-vault-paths` for targeted notes).
- UUID healing is automatic and logged; malformed frontmatter is skipped with a warning, not a crash.
- Ingest writes objects to the Store, emits Outbox events (`index.object.*`), and maintains VaultMirror copies under `System/Metadata/VaultMirror/...`.
- External ingest (drop folder) is opt-in; ingested objects carry `origin: external_raw` and surface in ASK/status alongside vault entries.

## 4. Human Flow: ASK (Reality-MVP)
- `/api/ask` and `python -m app.cli ask` query the HybridStore (BM25 + embeddings) warmed from Store objects. Answers cite sources with origin/plane tags.
- Default LLM provider is mock; set `LLM_PROVIDER` + credentials to enable LLM drafting/self-check. Errors surface in ASK status metrics.
- Cite-before-trust: answers show source IDs/paths; rerank hooks/critique are optional overlays.

## 5. Design Principles (Human-first constraints)
- The human is the ultimate authority for classification and meaning; the system proposes but never silently overrides.
- Every automated action is explainable and traceable back to sources, spans, and mirror artifacts.
- Panels are a conversation space for suggestions/instructions, not part of the knowledge base.
- Metadata and logging remain inspectable (e.g., in `System/Metadata/...`) but unobtrusive in the writing surface.
- Stability first: idempotent operations and predictable frontmatter/move policies keep trust high.
- Panel semantics:
  - Freeform commands in the panel may execute when confidently mapped to a canonical action; the runtime still writes a receipt so the human sees what happened.
  - When the agent is uncertain, it should propose explicit checkboxes (human confirmation) rather than guessing; checkboxes are treated as explicit consent.
  - AI status receipts stay outside the panel to keep the panel a small working set; receipts acknowledge success/failure without adding history inside the panel.

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
- `ingest-vault-paths` ingests specific markdown files by path (same pipeline as `vault-alpha-ingest`), enabling targeted updates as part of the v5.1 watcher-ready work.
- `alpha-human-flows` orchestrates flows A–F on top of the same ingest path; `--reset-outbox` is a destructive, dev-only flag for local regression checks that truncates the configured index outbox.
- `/api/ask` and the QA agent backends use BM25+embedding hybrid search over the in-process HybridStore, warmed from `store_objects` on first request; answers are the top-hit snippet and sources include doc ids and `source_ref` paths, while zones are not surfaced yet.
- External corpus ingest is not automated; external objects only appear if inserted into the Store with an `origin` such as `external_raw`, and they surface in ASK/status alongside vault entries.
- The CLI `ask` command still routes through the planner/orchestrator pipeline (QA steps fall back to the same hybrid retrieval), while `ingest-vault-root`/`pkm-alpha-ingest` provide quick root-level ingest helpers for the Alpha vault.

## 8. Planned v5.x Watcher-driven Flows (Vault Watcher + siblings)
State: SoT v4.10 (Reality-MVP) and v5.0 (PanelAgent Runtime V1) are locked baselines. Watcher-driven flows are planned v5.x work (v5.1–v5.4) and describe how the system should feel once delivered.

### Mental model (human)
- I edit and save a note in Obsidian. After a short cooldown, the system catches up: the change is ingested into Stores and, if the note has an AI panel that matches the auto-run policy, PanelAgent runtime can run for that note. I can still run the same CLI/service entrypoints manually; the watcher is convenience, not magic.
- I expect batching: agents do not fire on every save. A short cooldown window collects edits and then runs ingest/panel once per batch.
- I can see what ran: ingest and panel runs emit the usual events, AI-log entries, and status metrics; nothing rewrites my note body.

### Mental model (system, high level)
- Vault Watcher detects changed markdown files in the Obsidian vault (git watcher preferred, filesystem watcher as fallback per `docs/OBSIDIANSYNC.md`), batches them over a cooldown window, then triggers existing entrypoints:
  - Ingestion via the vault ingest pipeline, including targeted ingest using `ingest-vault-paths` for the changed files.
  - Panel/policy flows via note-update/PanelAgent runtime for notes whose panels satisfy an explicit auto-run policy (planned v5.3); the same pipelines are available via CLI by hand.
  - Future flows (relations, summaries, hygiene) can reuse the same batching trigger.
- The watcher does not rewrite note content; it only calls the existing ingest/update pipelines. It surfaces runs/errors/metrics into the existing observability/status surfaces.

### Cooldown and batching
- Watchers are not per-keystroke. They collect file changes during a short cooldown/batch window, then run ingest/panel once per batch. The human experience is “after a short while the system catches up,” not “agents fire on every save.”

### Watcher types (planned)
- Vault Watcher (v5.1–v5.4): watches Obsidian vault markdown files, triggers ingest and, once policy exists, panel runtime via note-update; emits watcher metrics (runs, changed files, errors). A Docker-first daemon (`vault-watcher-daemon`) keeps polling with snapshots stored outside the vault (e.g., `/state`); host services (launchd/systemd) remain a fallback when mounts are unreliable.
- External Inbox Watcher (future): watches an external drop folder/inbox and triggers external ingest into the `external_raw` plane via the existing external ingest CLI.
- Scheduler/Time-based Watcher (future): triggers periodic flows (daily review, weekly summary, hygiene jobs).
- All watcher types call the same CLI/service entrypoints as manual runs, integrate with observability/status, and are opt-in/auditable (no hidden automation).

### PanelAgent runtime + watcher integration
- When a panel is auto-run by the watcher today, PanelAgent Runtime V1 uses its fixed mapping from checked actions to follow-up events; behaviour matches the v5.0 baseline.
- Forward-looking (v5.5+): PanelAgent 2.0 will use LLM-based reasoning inside a LangGraph graph to decide which actions to trigger, making watcher-driven panels more adaptive without changing current behaviour until proven.
- PanelAgent now consults a catalog of canonical actions (`docs/settings/panel-actions.md`) and can run in either rule-mode (default, deterministic label→action mapping) or optional LLM-mode, which uses the catalog plus panel/note context; checkbox states are treated as hints rather than hard gates in LLM-mode.
- Panel action wiring can be overridden per vault via `System/Config/panel-action-wiring.yaml`; resolution order: `PANEL_ACTION_WIRING_PATH` env > vault System/Config > repo default (`docs/settings/panel-action-wiring.yaml`). Invalid configs emit a warning and fall back to the default wiring without changing behaviour.
- PanelAgent Runtime V1 (SoT v5.0) interprets AI panels, emits `panel.intent.created`, `panel.intent.executed`, `panel.action.*`, emits `promote.intent.created` for mapped promotion actions, and writes receipts into the in-note AI status callout (panel stays as the working set; receipts live outside the panel).
- Watcher track (v5.1–v5.3) adds automation that calls the same panel pipeline via note-update/PanelAgent runtime based on explicit policy (e.g., a flag on the note/panel). Manual CLI (`panel run` / `panel run-many`) and watcher-triggered runs share the same pipeline; watchers simply automate when to call it.
- A multi-note CLI (`panel run-many`) runs the same PanelAgent parse/runtime for multiple notes in one invocation (emit-only supported); it is the watcher-ready entrypoint when a batch of notes changed.
- Vault Watcher MVP (v5.2) ships as a polling CLI (`vault-watcher-run`) that diffs the vault against a snapshot, ingests changed notes via `ingest-vault-paths`, optionally runs `panel run-many` on those notes, prints a summary, refreshes the snapshot, and exits. A long-running wrapper (`vault-watcher-daemon`) reuses the same tick logic with `--poll-seconds`/`--cooldown-seconds` to support Docker/host services.
- Auto-panel policy (v5.3 planned/delivered in CLI): watcher-driven panel runs are opt-in per note. Frontmatter controls: `ai_panel_auto_run: watcher` allows watcher auto-run; missing/`manual` defaults to skip; `never` forbids watcher auto-run. Nested form `ai_panel: { auto_run: watcher|manual|never }` is also accepted. Manual CLI (`panel run` / `panel run-many`) is unaffected and always allowed; watchers only run panels when explicitly permitted.
- Hardening (v5.4): `vault-watcher-run` supports `--dry-run` (no ingest/panel, shows what would run) and `--max-notes` with optional `--force` to prevent storming on large change sets. Summaries report changed notes, ingest attempts, panel candidates/runs, skips, and errors. Watchers remain opt-in and bounded by both global flags and per-note policy.
- See also: `docs/UAT_PANEL_WATCHER.md` for a human-facing walkthrough of manual + watcher UAT.

### Runtime Loop V1 (CLI tool surface)
- Purpose: run the watcher → ingest → panel (policy-gated) → promotion consumer sequence once or on an interval for operator rehearsals.
- Command (once): `python -m app.cli runtime-loop --vault-root "<vault>" --once` (use `--interval N` to loop).
- Recommended with the UAT seed pack (Test/AgenticPKM-UAT): set `INDEX_OUTBOX_PATH` and `STORE_BACKEND=memory` for dry rehearsals.
- Expected: changed notes ingested, panel runs for policy-allowed notes, `promote.intent.created` emitted, promotion consumer applies state (`promote.done`), and the AI status callout shows receipts for executed panel actions (panel section stays clean).
- UAT check: after a runtime-loop tick, run `python -m app.cli status` and confirm `watcher_runs` increased (fed by the emitted `watcher.run` event), alongside panel/promotion counters.
- Observe via `python -m app.cli status` (counters for watcher_runs, panel_runs, promote.intent.created, promotion_executed) and the runtime-loop summary output.
### UAT: Watcher + Panel + Promotion on vault/Test
- Seed curated notes into your vault Test folder:
  - `python -m app.cli uat-seed-vault-test --vault-root "<vault_root>"` (defaults to Test/AgenticPKM-UAT).
- Run the end-to-end flow (watcher + panel runtime + promotion consumer):
  - `python -m app.cli uat-run-vault-test --vault-root "<vault_root>" --assert`
  - The runner scopes watcher to `<vault_root>/Test`, uses the seeded folder, runs panel runtime (policy-gated), and then consumes promotion intents to emit `promote.done` and apply the promotion state.
- Verify status: `python -m app.cli status` and confirm counters increased: watcher_runs, ingest_attempted/ingested, panel_runs (`panel.intent.executed`), promote.intent.created, promote.done.
- Policy gating: only notes with `ai_panel_auto_run: watcher` (or `ai_panel: { auto_run: watcher }`) are auto-run by watcher; manual/never notes are skipped and reported in the summary.
- Intent vs mutation: panel runtime emits intents (`promote.intent.created`), while `promote.done` comes from the promotion consumer; note mutation requires the consumer to run (included by default in the UAT runner).
