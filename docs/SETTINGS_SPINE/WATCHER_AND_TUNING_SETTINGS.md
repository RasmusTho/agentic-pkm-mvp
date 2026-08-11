---
name: Watcher And Tuning Settings
description: Feed watcher and curation or expansion tuning through the existing Settings Spine reload path.
task_id: SETTINGS-07C
github_issue: 4798
source_anchor: docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md :: What This Task Does
parent_capability: Settings Spine
prerequisites: [SETTINGS-07B]
depends_on: [TTS_SETTINGS.md]
can_parallelize_with: []
---

# Watcher And Tuning Settings

## Purpose

Make watcher cadence and curation/expansion thresholds vault-editable through the existing reload path, including the production-path repair where configured fields were ignored.

## What This Task Does

Adds canonical watcher and tuning keys, resolves them through SettingsService at watcher startup and reload, and makes curation/expansion use configured fields rather than module constants. Legacy environment variables stay one-release bootstrap overrides.

## Concretely

`agentic-pkm settings explain watchers.debounce_ms` reports the vault-shared origin and lab tier.

## Why This Matters

A setting that appears editable but is ignored by its production pass is a silent false-control surface. This final child proves both ingestion/reload and configured-field behavior.

## Acceptance Criteria

- [ ] Watcher tunables reach production startup and the existing settings reload path.
  - Verify: `tests/watcher/test_settings_tiering_profile.py::test_watcher_tunables_reach_startup_and_reload_from_settings`
- [ ] Configured curation and expansion thresholds are honored by production passes.
  - Verify: `tests/expansion/test_connect_findings.py::test_configured_floor_is_honored_through_settings_path`
- [ ] Empty settings, legacy environment values, and operator tier preserve existing watcher and tuning behavior.
  - Verify: `tests/settings/test_watcher_and_tuning_settings.py::test_empty_settings_legacy_env_and_operator_tier_preserve_watcher_and_tuning_behavior`

## How to Verify (Pre-Merge)

- `pytest -q tests/watcher/test_settings_tiering_profile.py tests/expansion/test_connect_findings.py tests/settings/test_watcher_and_tuning_settings.py`
- `ruff check app tests`
- `mypy app`
- `pytest -q -m "not pg"`

## Out of Scope

Watcher deployment, a second settings loader, TTS, model-routing, rerank, embedding, browse-limit, and panel-agent settings.

## Related Docs

- `docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md`
- `app/watcher/config.py :: WatcherConfig.from_env`
- `app/curation/contradiction.py`
- `app/expansion/connect.py :: ConnectPassConfig.relatedness_floor`

## Related GitHub Issues

Implements [#4798](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4798) after #4797 merges and is reconciled on `origin/main`; its parent receipt advances the SETTINGS-07 stage.
