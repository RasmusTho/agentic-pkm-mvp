---
name: Wire Settings Ingestion
description: Running services load vault-authored settings at startup and reload on markdown edits; invalid input degrades loudly, never silently to code defaults
task_id: SETTINGS-01
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F1
parent_capability: Settings Spine
prerequisites: []
depends_on: []
can_parallelize_with: [Single Default Registry]
---

# Wire Settings Ingestion

## Purpose

Close audit finding F1: the md→runtime settings pipeline (`vault/@Settings/*.md` →
`app/settings/compiler.py::compile_all()` → `runtime/settings/*.yaml`) is invoked only by a manual
CLI and CI, never by any running service, so LLM routing, embeddings, the ask prompt, planner,
ingest, outbox worker and observability silently run on pydantic code defaults (SET-1).

## What This Task Does

- Service startup (API lifespan, watcher, worker entrypoints) resolves vault-authored settings —
  either by invoking the existing compile step or by loading the markdown sources directly — so a
  container that never ran `settings compile` still honors the vault content.
- The watcher's existing settings-delta path (`app/watcher/settings_delta.py`) extends from
  `local.md`-only to the settings source files: change detected → validate → recompile/reload →
  in-process `settings.changed` event (existing hot-reload bus, `app/settings/hotreload.py`).
- Validation failure on reload degrades to the last-valid bundle and surfaces a degraded-settings
  state on `/api/health` — never a silent fallback to code defaults, never a crash of the consumer.
- No-vault boot is untouched: with no vault selected, the bundle builds from defaults exactly as
  today, and the health surface says so (that is a truthful state, not degradation).

## Concretely

```
# dev channel, no manual compile ever run:
$ docker compose up api
$ grep -m1 model_id "$VAULT/@Settings/llm_routing.md"   # user edits model in Obsidian
$ curl -s localhost:8000/api/ask -d '{"q":"..."}'        # answer uses the edited routing
$ curl -s localhost:8000/api/health | jq .settings       # {"state":"ok","source":"vault","loaded_at":...}
# then break the markdown (invalid YAML):
$ curl -s localhost:8000/api/health | jq .settings       # {"state":"degraded_last_valid","error":"..."}
```

## Why This Matters

Without this, "settings live in human-friendly md files" is false in production: every deployed
container ignores the vault and runs on hardcoded defaults, and nothing signals it. This is the
same silent-false-green class the correctness kernel targeted.

## Acceptance Criteria

- [ ] API, watcher, and worker startup load vault-authored settings without any manual CLI step;
      a consumer reading `get_settings_bundle()` sees vault values, not code defaults, when a vault
      with settings sources is selected.
  - Verify: `tests/settings/test_ingestion_startup.py::test_service_startup_loads_vault_settings`
    (enforcement AC — the test drives the production startup entrypoint, not `compile_all()` in
    isolation)
- [ ] Editing a settings source file while the service runs updates the effective bundle within
      bounded staleness (one watcher tick + reload), via the existing `settings.changed` bus.
  - Verify: `tests/settings/test_ingestion_startup.py::test_settings_edit_reloads_bundle`
- [ ] An invalid settings edit degrades to the last-valid bundle and surfaces
      `settings.state=degraded_last_valid` on the health contract; code defaults are never
      substituted while a last-valid bundle exists.
  - Verify: `tests/settings/test_ingestion_startup.py::test_invalid_settings_degrade_loud`
    (enforcement AC — asserts the degradation path from the production reload call site)
- [ ] No-vault boot behavior is unchanged: typed defaults, no error, no `./vault` fallback.
  - Verify: `tests/settings/test_watcher_settings_no_vault.py` and
    `tests/settings/test_health_settings_no_vault.py` pass unmodified
- [ ] SET-1 is registered in the invariant registry with enforcement `runtime_test`.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: settings_take_effect_or_fail_loud`

## How to Verify (Pre-Merge)

- `pytest -q tests/settings/test_ingestion_startup.py`
- `pytest -q -m "not pg"` (shared/hot-path rule — full suite, not targeted-only)
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration -k settings` (vault hot path touched)
- Manual dev-channel receipt: the Concretely transcript above, attached to the PR.

## Out of Scope

- Moving or renaming settings source locations (SETTINGS-02/03).
- Receipts for the reload writes (SETTINGS-04 owns receipt unification).
- New settings keys or de-hardcoding (SETTINGS-07).

## Restart / Durability Posture

The effective bundle is in-memory and rebuilt from markdown sources at every startup — restart
loses nothing because the markdown is the durable truth. The `degraded_last_valid` state does NOT
survive restart: a restart with still-invalid sources boots on defaults with
`settings.state=invalid_sources` (visible, distinct from ok). The user experience: a bad edit
never takes down the service, and the health card tells them their edit is not live.

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F1`
- `docs/SETTINGS.md` (compiler contract), `docs/OBSERVABILITY.md` (health contract)

## Related GitHub Issues

One implementation issue. TCD hint: sonnet / high — bounded wiring of existing machinery, but the
degradation semantics and health-contract change need careful review; hot-path (full suite + UAT).
