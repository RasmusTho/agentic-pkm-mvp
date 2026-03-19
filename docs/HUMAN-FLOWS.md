State: SoT v5.5 Reality-MVP baseline locked with v5.6 forward line extending PanelAgent runtime and registry watcher behavior.
Doc role: Core SoT
Authority: Canonical user-facing behavior contract for the current system; architecture and implementation changes should remain compatible with this document unless it is updated intentionally.
# Human Flows — Yggdrasil / agentic-pkm-mvp

> Audience: humans using the system in Obsidian + CLI. Human language is canonical; automation is additive, not authoritative.

This document is intentionally user-facing and practical.
It therefore speaks often in note- and vault-centric language, because those are the most visible
human surfaces in the current baseline.

For the broader domain ontology of the system as a second-brain environment — including actors,
artifacts, commitment structures, metacognition, and provenance/accountability — see
`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`.

## 1. Vault-first, Human-first System
- Keep writing in your vault. Agents run as helpers, not owners.
- The vault is the human surface; agents write traces/logs to side-channels (ObjectStore, Outbox, System folders) without rewriting your prose by default.
- CLI is an agent tooling surface, not the main UI: it exists for automation, reproducible runs, and debugging.
- The current baseline is vault-first in practice, but the broader second-brain domain also includes external source artifacts, project material, reflective material, and system receipts outside the visible writing surface.

## 2. Scope and Current Reality-MVP Snapshot
- v4.10 locked baseline: ingest + ASK + observability + orchestrator runtime V1; panels are optional and not indexed as content.
- v5.x forward line: PanelAgent runtime + registry watcher automation with policy gating, UUID healing, and bounded scans. Legacy snapshot watchers remain dev-only.

## 3. Human Flow: Capture & Ingest
- Keep frontmatter lean: `title`, `uuid`, optional `type/category/facets`.
- Ingest happens through the canonical vault ingest path, either as a full batch or targeted note update.
- UUID healing is automatic and logged; malformed frontmatter is skipped with a warning, not a crash.
- Ingest projects notes and other ingestable artifacts into the Store, keeps derived indexes rebuildable, and maintains VaultMirror copies under `System/Metadata/VaultMirror/...`.
- External ingest (drop folder) is opt-in; ingested objects carry `origin: external_raw` and surface in ASK/status alongside vault entries.

### Vault sync principles
- Human-first: the system should not rewrite note bodies; normal automation is limited to agreed frontmatter keys, AI panel content, and side-channel artifacts.
- UUID is the identity boundary; filenames and paths are operational metadata and may change without changing note identity.
- Vault edits flow into the runtime through the registry watcher and ingest pipeline; runtime-side note updates should stay narrow, explainable, and traceable.
- If a note is active or conflicted, the system should prefer receipts, inbox items, or explicit proposals over silent mutation.

## 4. Human Flow: ASK (Reality-MVP)
- ASK is available through the HTTP API and CLI.
- Answers must cite sources with origin/plane tags so the human can inspect where the answer came from.
- Cite-before-trust: source visibility is mandatory, while reranking and critique remain optional overlays.
- The current baseline treats ASK as a reliable retrieval-and-answer surface; richer agent-facing ASK behavior belongs to the forward line, not this human contract.
- ASK is only one current human-facing retrieval/synthesis surface. It should not be read as exhausting the broader second-brain domain, which also includes capture, reflection, planning, project work, and creative work.

## 5. Design Principles (Human-first constraints)
- The human is the ultimate authority for classification and meaning; the system proposes but never silently overrides.
- Every automated action is explainable and traceable back to sources, spans, and mirror artifacts.
- Panels are a conversation space for suggestions/instructions, not part of the knowledge base.
- Metadata and logging remain inspectable (e.g., in `System/Metadata/...`) but unobtrusive in the writing surface.
- Stability first: idempotent operations and predictable frontmatter/move policies keep trust high.
- The system supports more than settled knowledge handling; it also supports project work, creative work, reflection, and other cognitive work without forcing all artifacts into a single note-like mold.
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
- Rename/move handling must preserve UUID continuity, update canonical paths consistently, and avoid unnecessary re-embedding when note body content did not change.

## 7. Current Human-Facing Surfaces
- Obsidian vault: the primary writing and reading surface.
- CLI: operator/developer tooling for ingest, ASK, watcher control, and diagnostics.
- HTTP API: `/api/ask`, `/api/health`, and `/api/status` for retrieval and runtime visibility.
- AI panels + receipts: the in-note working surface for human-confirmed or human-visible actions.

Detailed command behavior, startup flows, and troubleshooting belong in:
- `docs/OPERATIONS.md`
- `docs/INFRASTRUCTURE.md`
- `docs/PANEL_AGENT.md`
- `docs/TESTING.md`

## 8. Watcher-driven Flows (Registry Watcher)
State: v5.x forward line. Runtime automation uses the registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`). Legacy snapshot watchers are dev-only.

### Mental model (human)
- I edit and save a note in Obsidian. After a short cooldown, the system catches up: the change is ingested into Stores and, if the note has an AI panel that matches the auto-run policy, PanelAgent runtime can run for that note. I can still run the same CLI/service entrypoints manually; the watcher is convenience, not magic.
- I expect batching: agents do not fire on every save. A short cooldown window collects edits and then runs ingest/panel once per batch.
- I can see what ran: ingest and panel runs emit the usual events, AI-log entries, and status metrics; nothing rewrites my note body.

### Mental model (system, high level)
- Recommended operator posture (safe-by-default): run the registry watcher on an inbox-bounded scope and expand only when the guardrails are proven on your vault.
  - Set `WATCHER_SCOPE_GLOB="<inbox>/**"` (where `<inbox>` matches your vault layout) to bound scanning.
  - Note: the current code default is vault-wide markdown (`**/*.md`) unless `WATCHER_SCOPE_GLOB` is set; this doc recommends inbox-scoped operation for daily usage.
- The watcher may rewrite note content in narrow, human-first ways: it can heal missing UUIDs for inbox notes and it can update AI panels (add proposals/questions, annotate action IDs, append receipts). It does not perform side-effecting actions unless policy/allowlists plus explicit intent (for example, checked actions) allow it.

### Cooldown and batching
- Watchers are not per-keystroke. They collect file changes during a short cooldown/batch window, then run ingest/panel once per batch. The human experience is “after a short while the system catches up,” not “agents fire on every save.”

### PanelAgent runtime + watcher integration
- PanelAgent Runtime V1 uses its fixed mapping from checked actions to follow-up events; behavior matches the v5.x baseline.
- PanelAgent now consults a catalog of canonical actions (`docs/settings/panel-actions.md`) and can run in either rule-mode (default, deterministic label→action mapping) or optional LLM-mode, which uses the catalog plus panel/note context; checkbox states are treated as hints rather than hard gates in LLM-mode.
- Panel action wiring can be overridden per vault via `<vault>/System/Config/panel-action-wiring.yaml` (vault-relative path); resolution order: `PANEL_ACTION_WIRING_PATH` env > vault override file > repo default (`docs/settings/panel-action-wiring.yaml`). Invalid configs emit a warning and fall back to the default wiring without changing behavior.
- Auto-panel policy: any note containing an AI fence (`%% ...ai... %%`, case-insensitive) is a candidate by default. Eligible notes without a fence may also get a panel created with proposals/questions (proactive assist); disable with `PANEL_PROACTIVE_ASSIST=0`. The per-note opt-out remains `ai_panel_auto_run: never` (or nested `ai_panel: { auto_run: never }`). Manual CLI (`panel run` / `panel run-many`) is always allowed.
- `WATCHER_AUTO_EXEC` is the global arm switch: when off, watchers compute candidacy and emit summaries but do not execute panel mutations.
- Panel runtime emits `panel.intent.created`, `panel.intent.executed`, `panel.action.*`, emits `promote.intent.created` for mapped promotion actions, and writes receipts into the in-note AI status callout (panel stays as the working set; receipts live outside the panel).
- Promotion consumer updates the note file (frontmatter `review_state`) using the path in `promote.intent.created`; Store metadata can lag, but the vault note is the source of truth.

For UAT flows, operator commands, and dev-only watcher tools, use:
- `docs/runbooks/UAT_PANEL_WATCHER.md`
- `docs/OPERATIONS.md`
