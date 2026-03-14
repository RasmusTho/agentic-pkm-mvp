State: Spec / planned (not implemented in v5.5 baseline). Keep this as a forward-line design reference; code may not match yet.
Doc role: Plan
Authority: Forward-line protocol design for future master/satellite sync; does not override the current runtime baseline in `docs/STATUS.md` or `docs/ARCHITECTURE.md`.
Owner: Satellite sync forward-line planning

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.


# Satellite Sync Protocol (Draft)

This draft defines how a master Yggdrasil instance and one or more satellite instances for the same human synchronize knowledge. The focus is text-first sync (Markdown notes + VaultMirror logs) using Git/iCloud as transport, and how `instance_id` and per-note logs fit in. It is a conceptual contract for future implementation, not current production behaviour, and is the canonical plan for v5.x master/satellite sync in the roadmap.

## 1. Instance roles and identity

- Runtimes: typically one master (e.g., home Mac mini) plus zero or more satellites (e.g., work machine, laptop).
- Identity: each runtime uses `settings.instance` (`id`, `role`). Defaults today are `id="home"`, `role="master"`; a satellite could be `id="work"`, `role="satellite"`.
- Events: every event envelope carries `instance_id` from settings, so logs and per-note histories can record which instance acted.

## 2. Sync surface (what actually moves)

- Portable core (text + metadata):
  - `Mimer/.../*.md` (human-facing notes in the Obsidian vault).
  - `System/Metadata/VaultMirror/.../<uuid>.md` (per-note metadata/logs in the machine-side mirror, outside the human vault surface).
- Transport: Git (Obsidian Git plugin or equivalent) and/or iCloud move these Markdown files between instances.
- Stores/DBs are not replicated; each instance owns its local Stores and can rebuild them from the text surface when needed.
- Non-portable / policy-dependent: binaries and heavy artifacts (slides, PDFs, media in Munin/Brokkr/Tyr) may stay local or follow separate rules; this protocol covers Markdown + VaultMirror.

## 3. Master vs satellite responsibilities

- Master: canonical long-term view; may run more housekeeping/promotion/consolidation and resolve conflicts that affect global structure (ontology, taxonomy, canon).
- Satellite: full intelligence locally (ASK, DeliberationAgent, PanelAgent, etc.) over its subset; edits notes and VaultMirror logs offline or under constrained networks; periodically syncs changes back via Git/iCloud.
- Conceptual only: not all flows are implemented yet.

## 4. Provenance at the note/log level

- Notes: frontmatter may later gain fields such as `origin_instance` or `last_touched_instance`; absent fields are interpreted using the local `instance.id`.
- Per-note logs (`System/Metadata/VaultMirror/.../<uuid>.md`): may include entries that record `instance_id`, timestamps, and key events (promotion, merges, conflict resolutions). Agents can derive these entries from event metadata (`instance_id`, `trace_id`, etc.). These logs are human-readable history and sync anchors.

## 5. Sync flows (conceptual)

### 5.1 Satellite → master

- Satellite commits/pushes Markdown changes (notes + VaultMirror logs).
- Master pulls/merges; conflicts are handled at Git/text level, with human resolution when needed.
- After merge, master can update its Stores by re-ingesting the changed notes/logs.

### 5.2 Master → satellite

- Master pushes updated notes/logs.
- Satellites pull/rebase and refresh their Stores by re-ingesting updated notes.

Sync follows Git workflows (branching/rebasing/merging). Database state is derived from text; text is the shared source of truth.

## 6. Conflict handling principles

- `uuid` is the stable identity for notes across instances.
- If master and satellite edit the same note, Markdown is the primary truth; VaultMirror log entries help trace who did what when.
- Complex semantic conflicts (ontology, taxonomy, canon) require human review; agents may propose resolutions in the future but must not overwrite human decisions silently.

## 7. Non-goals and current status

- Non-goals for Reality-MVP: no automatic cross-instance DB replication; no automatic semantic conflict resolution; no multi-user guarantees (single human across machines only).
- Status: InstanceSettings + `instance_id` on events + VaultMirror `uuid.md` + Git/iCloud sync provide the plumbing. This draft will be paired with future CLI/agent tooling that MUST follow this protocol.
