State: Draft contract (spec-first for Obsidian-required runtime).
# Obsidian Knowledge Port Contract (v0)

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

## TDD test baseline (must exist before adapter wiring)
1. Contract tests for `NoteLocator` portability constraints.
2. Settings tests for adapter policy parsing + invalid combinations.
3. CLI scope tests enforcing `vault=<...>` first.
4. Dependency health tests for missing CLI and installer version checks.
5. Architecture guardrails preventing direct `NoteLocator(...)` construction and direct `OBSIDIAN_VAULT_NAME` reads outside shared helpers.

## Next implementation step
Wire this contract into:
- MCP vault tools path
- inbox/watcher URI helpers
- startup health command and runbooks
without changing external event contracts.

## Rolling implementation backlog
- [x] Verify all runtime call sites that perform note open/search are explicitly routed through `resolve_knowledge_port()`.
- [x] Add contract tests for `make_note_locator_from_absolute(...)` usage in service flows with mixed absolute/relative paths.
- [x] Add CI marker command in runbooks for `tests/architecture/test_obsidian_port_boundaries.py`.
