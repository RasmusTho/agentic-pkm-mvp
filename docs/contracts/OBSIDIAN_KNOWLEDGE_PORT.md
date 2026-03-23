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

## Interface surface (domain-level)
- `read_note(locator)`
- `write_note(locator, content)`
- `append_note(locator, content)`
- `prepend_note(locator, content)`
- `search_notes(vault, query, limit=20)`
- `open_note(locator)`

Reference types:
- `NoteLocator(vault, path)` where `path` is vault-relative and portable (`/` separators).
- `WriteReceipt(operation, locator, adapter, trace_id, fallback_used)`.
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
- `_system/companions/` is a system-owned vault path for companion-note artifacts.
- Runtime/services may write there only through KnowledgePort or approved helpers built on top of it.

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
- [x] Route Yggdrasil bootstrap settings placeholder writes through `KnowledgePort` (`app/settings/yggdrasil_scaffolder.py`).
- [x] Route vault ingest mirror-note writes through `KnowledgePort` (`app/ingest/vault_alpha.py`).
- [x] Route note hygiene archive-note writes through `KnowledgePort` (`app/agents/note_hygiene/agent.py`).
- [x] Centralize service/runtime vault write+append wiring behind `app/knowledge/write_ops.py` helper functions (`write_note_from_absolute`, `write_note_relative`, `append_note_relative`).
- [x] Centralize Advanced URI vault-path conversion via `app/knowledge/write_ops.py::advanced_uri_from_vault_path` and remove ad-hoc locator parsing from runtime/services.
