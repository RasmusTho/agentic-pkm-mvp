State: SoT v4.10 Reality-MVP (baseline locked) with v5.x forward line extending PanelAgent runtime + registry watcher.
# Human Flows — Yggdrasil / agentic-pkm-mvp

> Audience: humans using the system in Obsidian + CLI. Human language is canonical; automation is additive, not authoritative.

## 1. Vault-first, Human-first System
- Keep writing in your vault. Agents run as helpers, not owners.
- The vault is the human surface; agents write traces/logs to side-channels (ObjectStore, Outbox, System folders) without rewriting your prose by default.
- CLI is an agent tooling surface, not the main UI: it exists for automation, reproducible runs, and debugging.

## 2. Scope and Reality-MVP Snapshot (SoT v4.10 + v5.x forward line)
- v4.10 locked baseline: ingest + ASK + observability + orchestrator runtime V1; panels are optional and not indexed as content.
- v5.x forward line: PanelAgent runtime + registry watcher automation with policy gating, UUID healing, and bounded scans. Legacy snapshot watchers remain dev-only.

## 3. Human Flow: Capture & Ingest
- Keep frontmatter lean: `title`, `uuid`, optional `type/category/facets`.
- Ingest via `vault-alpha-ingest` (or `ingest-vault-paths` for targeted notes).
- UUID healing is automatic and logged; malformed frontmatter is skipped with a warning, not a crash.
- Ingest writes objects to the Store, emits DB outbox events (`index.object.*`), and maintains VaultMirror copies under `System/Metadata/VaultMirror/...`.
- External ingest (drop folder) is opt-in; ingested objects carry `origin: external_raw` and surface in ASK/status alongside vault entries.

## 4. Human Flow: ASK (Reality-MVP)
- `/api/ask` and `python -m app.cli ask` query the HybridStore (BM25 + embeddings) warmed from Store objects. Answers cite sources with origin/plane tags.
- Default LLM provider is mock; set `LLM_PROVIDER` + credentials to enable LLM drafting/self-check. Errors surface in ASK status metrics.
- Cite-before-trust: answers show source IDs/paths; rerank hooks/critique are optional overlays.
- `ASK_DOMAIN_SCOPE` (when set) limits retrieval to a single domain; default behavior excludes cross-domain results.
- `bridge_domains` explicitly allows inclusion across domains when needed (no implicit bridges).
- Contract tests enforce the scope boundary to prevent regressions.

## 5. Design Principles (Human-first constraints)
- The human is the ultimate authority for classification and meaning; the system proposes but never silently overrides.
- Every automated action is explainable and traceable back to sources, spans, and mirror artifacts.
- Panels are a conversation space for suggestions/instructions, not part of the knowledge base.
- Metadata and logging remain inspectable (e.g., in `System/Metadata/...`) but unobtrusive in the writing surface.
- Stability first: idempotent operations and predictable frontmatter/move policies keep trust high.
- See also: `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` (ASSERT/SUGGEST/APPLY gating + receipt expectations).
- Panel semantics:
  - Freeform commands in the panel may execute when confidently mapped to a canonical action; the runtime still writes a receipt so the human sees what happened.
  - Checkboxes remain explicit confirmation for uncertain actions; if the human is sloppy (missing frontmatter, wikilink uuids), the runtime normalizes/patches frontmatter via the note writer so promotions stay human-first.
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
- `ingest-vault-paths` ingests specific markdown files by path (same pipeline as `vault-alpha-ingest`), enabling targeted updates as part of the watcher-ready work.
- `alpha-human-flows` orchestrates flows A–F on top of the same ingest path; `--reset-outbox` is a destructive, dev-only flag for local regression checks that truncates the configured audit log.
- `/api/ask` and the QA agent backends use BM25+embedding hybrid search over the in-process HybridStore, warmed from `store_objects` on first request; answers are the top-hit snippet and sources include doc ids and `source_ref` paths, while zones are not surfaced yet.
- External corpus ingest is not automated; external objects only appear if inserted into the Store with an `origin` such as `external_raw`, and they surface in ASK/status alongside vault entries.
- The CLI `ask` command still routes through the planner/orchestrator pipeline (QA steps fall back to the same hybrid retrieval), while `ingest-vault-root`/`pkm-alpha-ingest` provide quick root-level ingest helpers for the Alpha vault.

## 8. Watcher-driven Flows (Registry Watcher)
State: v5.x forward line. Runtime automation uses the registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`). Legacy snapshot watchers are dev-only.

### Mental model (human)
- I edit and save a note in Obsidian. After a short cooldown, the system catches up: the change is ingested into Stores and, if the note has an AI panel that matches the auto-run policy, PanelAgent runtime can run for that note. I can still run the same CLI/service entrypoints manually; the watcher is convenience, not magic.
- I expect batching: agents do not fire on every save. A short cooldown window collects edits and then runs ingest/panel once per batch.
- I can see what ran: ingest and panel runs emit the usual events, AI-log entries, and status metrics; nothing rewrites my note body.

### Mental model (system, high level)
- Registry watcher scans vault-wide markdown by default (`**/*.md` under `WATCHER_VAULT_PATH`, override via `WATCHER_SCOPE_GLOB`), emits `ingest.vault.changed` and `panel.scan.requested`, and writes heartbeat + tick logs for observability.
- DB outbox is canonical; JSONL (`INDEX_OUTBOX_PATH`) is audit/diagnostic only.
- The watcher may rewrite note content in narrow, human-first ways: it can heal missing UUIDs for inbox notes and it can update AI panels (add proposals/questions, annotate action IDs, append receipts). It does not perform side-effecting actions unless an explicit checkbox/action is checked.

### Cooldown and batching
- Watchers are not per-keystroke. They collect file changes during a short cooldown/batch window, then run ingest/panel once per batch. The human experience is “after a short while the system catches up,” not “agents fire on every save.”

### PanelAgent runtime + watcher integration
- PanelAgent Runtime V1 uses its fixed mapping from checked actions to follow-up events; behavior matches the v5.x baseline.
- PanelAgent now consults a catalog of canonical actions (`docs/settings/panel-actions.md`) and can run in either rule-mode (default, deterministic label→action mapping) or optional LLM-mode, which uses the catalog plus panel/note context; checkbox states are treated as hints rather than hard gates in LLM-mode.
- Panel action wiring can be overridden per vault via `System/Config/panel-action-wiring.yaml`; resolution order: `PANEL_ACTION_WIRING_PATH` env > vault System/Config > repo default (`docs/settings/panel-action-wiring.yaml`). Invalid configs emit a warning and fall back to the default wiring without changing behavior.
- Auto-panel policy: any note containing an AI fence (`%% ...ai... %%`, case-insensitive) is a candidate by default. Eligible notes without a fence may also get a panel created with proposals/questions (proactive assist); disable with `PANEL_PROACTIVE_ASSIST=0`. The per-note opt-out remains `ai_panel_auto_run: never` (or nested `ai_panel: { auto_run: never }`). Manual CLI (`panel run` / `panel run-many`) is always allowed.
- `WATCHER_AUTO_EXEC` is the global arm switch: when off, watchers compute candidacy and emit summaries but do not execute panel mutations.
- Panel runtime emits `panel.intent.created`, `panel.intent.executed`, `panel.action.*`, emits `promote.intent.created` for mapped promotion actions, and writes receipts into the in-note AI status callout (panel stays as the working set; receipts live outside the panel).
- Promotion consumer updates the note file (frontmatter `review_state`) using the path in `promote.intent.created`; Store metadata can lag, but the vault note is the source of truth.

### UAT: Watcher + Panel + Promotion on vault/Test
- Seed curated notes into your vault Test folder:
  - `python -m app.cli uat-seed-vault-test --vault-root "<vault_root>"` (defaults to Test/AgenticPKM-UAT).
- Run the end-to-end flow with the registry watcher:
  - `WATCHER_ENABLE=1 WATCHER_VAULT_PATH="<vault_root>" WATCHER_SCOPE_GLOB="Test/**" WATCHER_AUTO_EXEC=1 python -m app.cli watcher run --max-ticks 1`
- Verify status: `python -m app.cli status` and confirm counters increased: `panel_runs`, `promote.intent.created`, `promotion_executed`, and ingest run counts. Use DB outbox as the ground truth.
- Policy gating: the only per-note block is `ai_panel_auto_run: never` (nested form supported). Fenced notes become candidates when `WATCHER_AUTO_EXEC=1` is armed; proactive assist may also create panels for eligible non-fenced notes unless disabled.
- Intent vs mutation: panel runtime emits intents (`promote.intent.created`), while `promote.done` comes from the promotion consumer; note mutation requires the consumer to run (included by default in runtime).

### Legacy/dev-only tools
- `vault-watcher-run` / `vault-watcher-daemon` and `runtime-loop` are legacy snapshot-based tools. They are not used for runtime start-system flows and are kept for historical/dev-only workflows.
