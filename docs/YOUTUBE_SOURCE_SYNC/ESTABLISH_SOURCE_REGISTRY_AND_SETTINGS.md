---
name: Establish Source Registry and Settings
description: Durable per-account source registry (table + memory backend + service layer) and the youtubeSync settings model with validation.
task_id: YSS-01
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Source registry"
parent_capability: YouTube Source Sync
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Establish Source Registry and Settings

## Purpose

Every later slice reads or writes "which collections does this account follow, with what policy,
cursor, and state". This task lands that substrate once — durable, validated, channel-isolated —
so no later slice invents private persistence or ad-hoc config.

## What This Task Does

1. New module `app/knowledge_acquisition/source_registry.py`: typed registry rows per
   `SOURCE_SYNC_CONTRACT.md :: Source registry`, with a Postgres backend (new table
   `acquisition_source_registry`, Alembic forward-only migration following the KERNEL-04/05
   precedent) and an in-memory backend for `not_pg` tests, selected the same way existing stores
   select backends.
2. Service-layer integrity rules (identical across backends): unique binding triple; **exactly one
   enabled inbox per account binding** with atomic "change inbox" swap; poll-interval bounds;
   Watch Later (`WL`) / Watch History (`HL`) registration refused with `source_unsupported` and a
   legible explanation; title is display-only (rename-safe).
3. Settings: register the `youtubeSync.*` definitions from `SOURCE_SYNC_CONTRACT.md :: Settings
   model` in `app/vault/settings_service.py` (`SETTING_DEFINITIONS`), add
   `<vault>/settings/youtube.md` to the vault-shared file set, `youtubeSync.runnerEnabled` as
   vault-local, and add `youtubeSync.enabled` + `youtubeSync.runnerEnabled` to
   `RUNTIME_GATING_SETTINGS`.
4. Acquisition-policy JSON validation (modes, media object shape per the contract) at write time,
   degrading invalid values to defaults with a `SettingsValidationError` / registry validation
   error — never a silent apply.

## Concretely

```python
from app.knowledge_acquisition.source_registry import SourceRegistry
reg = SourceRegistry.for_runtime()
b = reg.register(collection_kind="inbox_playlist", collection_ref="PL<fixture>", account_binding_id=acct, title="Mimer Inbox")
reg.set_inbox(acct, b.binding_id)          # atomic swap; a second enabled inbox is impossible
reg.register(collection_kind="owned_playlist", collection_ref="WL", ...)  # -> SourceUnsupportedError
```

`python -m app.cli settings-validate`-class validation surfaces reject `inboxPollSeconds: -5`
with a named error; effective values resolve with scope + source-file provenance.

## Why This Matters

Playlist title as identity breaks on rename; two enabled inboxes double-acquire; an unvalidated
interval of 0 hammers the API; a second settings format forks operator truth. Every one of those
is a real defect this slice makes structurally impossible.

## Acceptance Criteria

- [ ] Registry rows persist and round-trip on both backends with the contract's field set.
      Verify: `tests/knowledge_acquisition/test_source_registry.py::test_registry_round_trip_memory_and_contract_fields`
- [ ] Exactly one enabled inbox per account binding; changing inbox is an atomic swap.
      Verify: `tests/knowledge_acquisition/test_source_registry.py::test_single_enabled_inbox_enforced_and_swap_atomic`
- [ ] Duplicate `(collection_kind, collection_ref, account_binding_id)` registration is refused.
      Verify: `tests/knowledge_acquisition/test_source_registry.py::test_duplicate_binding_refused`
- [ ] Watch Later and Watch History are refused as `source_unsupported` with legible copy.
      Verify: `tests/knowledge_acquisition/test_source_registry.py::test_watch_later_and_history_refused_unsupported`
- [ ] Renaming a source's title changes no identity, cursor, or policy (binding survives).
      Verify: `tests/knowledge_acquisition/test_source_registry.py::test_title_rename_does_not_break_binding`
- [ ] Poll-interval and policy validation reject out-of-bounds/unknown values loudly; defaults
      apply and the error is surfaced.
      Verify: `tests/knowledge_acquisition/test_source_registry.py::test_invalid_interval_and_policy_fail_loud`
- [ ] `youtubeSync.*` settings resolve with defaults, scopes, and provenance; invalid values
      degrade to defaults with a validation error; the two gating keys are WriteGuard-gated on
      write from the production call site.
      Verify: `tests/vault/test_youtube_sync_settings.py::test_defaults_scopes_provenance_and_gated_writes`
- [ ] Alembic migration creates the table forward-only (downgrade raises), and the pg backend
      passes the same service-layer suite.
      Verify: `tests/knowledge_acquisition/test_source_registry_pg.py::test_pg_backend_contract` (marked `pg`)

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_source_registry.py tests/vault/test_youtube_sync_settings.py`
- `pytest -q -m "not pg"` (full default suite — settings and store surfaces are hot-path)
- `ruff check app tests && mypy app`

## Out of Scope

OAuth (YSS-02), any egress, request queue (YSS-04), scheduling (YSS-06), UI/CLI surfaces beyond
settings resolution (YSS-10/11).

## Restart / Durability Posture

Registry rows, cursors, and policies are durable in the channel database; nothing registry-shaped
lives only in process memory. The memory backend exists for tests only and is never selected in a
configured runtime.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Source registry / Settings model / Acquisition policy`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md` (scopes, precedence)
- `docs/ENVIRONMENTS.md :: Cross-Environment Invariants`

## Related GitHub Issues

One issue. TCD hint: Sonnet / high — multi-file with real design choices but locally verifiable;
escalate to Opus only if the store-backend seam fights back.
