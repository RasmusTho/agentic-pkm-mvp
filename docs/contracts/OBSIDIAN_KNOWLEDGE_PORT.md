State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Core SoT
Authority: Canonical contract for vault-facing knowledge operations and adapter boundaries; runtime/services must route note operations through this boundary or approved helpers built on top of it.
# Obsidian Knowledge Port Contract

## Purpose
Define one domain-facing interface between agents/runtime and knowledge operations so transport details
(Obsidian CLI vs fallback filesystem adapter) are isolated from business logic.

This contract follows:
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`
- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`

## Runtime posture (current decision)
- Production/server posture: Obsidian Desktop + CLI are required.
- Fallback is not implicit. It is explicitly policy-controlled.
- Startup must fail fast when strict mode is enabled and Obsidian dependencies are not healthy.
- The bootstrap script and runtime health gate must agree on strict-vs-nonstrict behavior; a strict startup setting is not a warning-only mode.

## Interface surface (domain-level)
- `read_note(locator)`
- `write_note(locator, content, expected_version=None, writer_identity=None)` — `expected_version` opts a rewritten note into optimistic concurrency over raw on-disk bytes. An already-stale first comparison leaves the canonical note unchanged, publishes the proposed bytes as a sibling Markdown conflict artifact through the shared classifier grammar, and returns `WriteReceipt(outcome="conflict_staged", conflict_artifact=<vault-relative path>, writer_identity=..., written_at=...)`. A trusted hidden hard link retains the exact proposal until final public-artifact verification; a public-name replacement before that receipt fence fails without a receipt and keeps the trusted link recoverable. The filesystem adapter anchors the target parent and its non-symlink `_conflicts` child with directory descriptors; all stage, target, exchange, artifact, rollback, and cleanup operations are descriptor-relative. Both descriptors are identity-checked against their canonical path entries immediately before exchange and before receipt, so a directory rename or replacement fails with `KnowledgeWriteConflict` instead of falsely reporting a non-canonical write as successful. A matching version performs an atomic path exchange, preserves the existing permission mode, verifies the displaced original, and rolls the exchange back when bytes or mode changed at the linearization point. Every successful exchange retains the displaced inode beside the actual target as a non-indexed `_conflicts/*.md.conflict` artifact so a late save through a pre-existing descriptor cannot disappear without reintroducing stale note content into search/projection readers. File data and affected directories are `fsync`ed before success. Missing targets and races after the first comparison fail with `KnowledgeWriteConflict`; rollback and rollback-failure preservation use the same descriptor-anchored filesystem tree. Cleanup failures are logged without masking the write receipt or primary conflict. Unsupported descriptor-relative or atomic-exchange platforms fail closed with `KnowledgeCapabilityError`.
- `append_note(locator, content)`
- `prepend_note(locator, content)`
- `search_notes(vault, query, limit=20)`
- `open_note(locator)`

The `write_note` receipt above is the low-level port result. Production/service callers use
`write_note_from_absolute` or `write_note_relative`; those helpers raise
`KnowledgeWriteConflict` with the staged receipt attached when `outcome="conflict_staged"`.
Consequently, a normal helper return continues to mean the canonical write completed. A caller
that understands the non-canonical result may opt in explicitly to receive the staged receipt and
must branch on `outcome` before acknowledging success or running downstream effects.

Reference types:
- `NoteLocator(vault, path)` where `path` is vault-relative and portable (`/` separators).
- `WriteReceipt(operation, locator, adapter, trace_id, fallback_used, note_class, writer_identity, written_at, outcome, conflict_artifact)`.
- Locator construction for runtime/services must go through shared helpers:
  - `resolve_obsidian_vault_name(...)`
  - `make_note_locator(...)`
  - `make_note_locator_from_absolute(...)`

## Policy surface
- `KNOWLEDGE_PRIMARY_ADAPTER` (`obsidian_cli` or `fs_vault`)
- `KNOWLEDGE_FALLBACK_ADAPTER` (`obsidian_cli` or `fs_vault`)
- `KNOWLEDGE_ALLOW_FALLBACK` (`0|1`)
- `KNOWLEDGE_STRICT_STARTUP` (`1` by default)

Validation rules:
- Primary and fallback adapters must differ.
- `strict_startup=1` cannot be combined with `allow_fallback=1`.

## Obsidian CLI invariants
- Scope argument must be injected as first argument: `vault=<...>`.
- CLI availability and installer compatibility (`>= 1.12.4`) are dependency checks.
- Dependency checks are treated as startup gates in strict mode.

## Error taxonomy
- `KnowledgeConfigError` (invalid policy/settings)
- `KnowledgeDependencyError` (missing CLI/installer dependency)
- `KnowledgeCapabilityError` (adapter cannot perform requested operation)
- `KnowledgeWriteConflict` (safe write preconditions fail)

## Allowed exceptions (boundary)
- Startup/ops glue may reference Obsidian only for dependency gates and telemetry:
  - `scripts/start_full_system.sh`
  - `app/cli/health.py`
- URI rendering helpers may stay outside adapter classes but must only consume `NoteLocator` (no ad-hoc vault/path parsing).
- No domain/service code may construct `NoteLocator` directly from env vars; use shared locator helpers instead.

## Allowed write operations

The KnowledgePort boundary is the normative write path for:
- normal vault note writes and appends,
- UUID healing writes back into vault notes,
- companion-note creation and update,
- bounded system-surface writes under system-owned paths,
- and repair writes that restore continuity metadata without silently redefining human meaning.

System-owned path clarification:
- `<system_folder>/companions/` (layout-aware; e.g. `⚙️ System/companions/`) is the canonical system-owned vault path for companion-note artifacts. The legacy `_system/companions/` path is a read-only fallback for vaults that have not yet migrated; no new files are written there.
- Runtime/services may write companion notes only through KnowledgePort or approved helpers built on top of it.

KnowledgePort may not:
- bypass write-policy and safety checks through ad-hoc direct filesystem mutations as the normative
  path,
- silently redefine human-authored meaning-bearing body content under the banner of healing,
- or promote runtime/index artifacts into human-surface truth by write side effect alone.

## Required test baseline
1. Contract tests for `NoteLocator` portability constraints.
2. Settings tests for adapter policy parsing + invalid combinations.
3. CLI scope tests enforcing `vault=<...>` first.
4. Dependency health tests for missing CLI and installer version checks.
5. Architecture guardrails preventing direct `NoteLocator(...)` construction and direct `OBSIDIAN_VAULT_NAME` reads outside shared helpers.

Current enforcement:
- CI/architecture tests enforce the boundary in `tests/architecture/test_obsidian_port_boundaries.py`.
- Runtime/service writes are expected to route through `app/knowledge/write_ops.py` or deeper `app/knowledge/*` modules rather than direct service/runtime wiring.

## Rolling implementation backlog
- [x] Verify all runtime call sites that perform note open/search are explicitly routed through `resolve_knowledge_port()`.
- [x] Add contract tests for `make_note_locator_from_absolute(...)` usage in service flows with mixed absolute/relative paths.
- [x] Add CI marker command in runbooks for `tests/architecture/test_obsidian_port_boundaries.py`.
- [x] Route settings auto-heal/writeback note updates through `KnowledgePort` (`app/settings/writeback.py`, `app/settings/compiler.py`).
- [x] Route vault layout/system-note bootstrap writes through `KnowledgePort` (`app/vault/layout.py`).
- [x] Route alpha human flows vault note mutation writes through `KnowledgePort` (`app/cli/alpha_human_flows.py`).
- [x] Route note update + promotion note writes through `KnowledgePort` (`app/services/note_update.py`).
- [x] Route Mimer bootstrap settings placeholder writes through `KnowledgePort` (`app/settings/mimer_scaffolder.py`).
- [x] Route vault ingest mirror-note writes through `KnowledgePort` (`app/ingest/vault_alpha.py`).
- [x] Route note hygiene archive-note writes through `KnowledgePort` (`app/agents/note_hygiene/agent.py`).
- [x] Centralize service/runtime vault write+append wiring behind `app/knowledge/write_ops.py` helper functions (`write_note_from_absolute`, `write_note_relative`, `append_note_relative`).
- [x] Centralize Advanced URI vault-path conversion via `app/knowledge/write_ops.py::advanced_uri_from_vault_path` and remove ad-hoc locator parsing from runtime/services.
