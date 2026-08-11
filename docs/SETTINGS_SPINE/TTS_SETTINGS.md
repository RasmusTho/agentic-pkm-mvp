---
name: TTS Settings
description: Resolve voice and explicit fallback policy through the Settings Spine.
task_id: SETTINGS-07B
github_issue: 4797
source_anchor: docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md :: What This Task Does
parent_capability: Settings Spine
prerequisites: [SETTINGS-07A]
depends_on: [LLM_AND_RETRIEVAL_SETTINGS.md]
can_parallelize_with: []
---

# TTS Settings

## Purpose

Move the existing voice selection and explicit fallback policy into canonical vault settings without widening local-only behavior or changing the empty-settings default.

## What This Task Does

Adds `settings/tts.md` registry keys and resolves them at the production TTS configuration and synthesis path. Existing TTS environment variables remain one-release bootstrap overrides.

## Concretely

`agentic-pkm settings explain tts.voices.sv` reports the vault-shared origin and lab tier.

## Why This Matters

Voice selection is operator-facing behavior, but an accidental fallback change is an external-boundary regression. This slice keeps that policy explicit and testable.

## Acceptance Criteria

- [ ] Vault settings select voice at the production synthesis path and explain reports origin and tier.
  - Verify: `tests/tts/test_settings_backed_voices.py::test_voice_resolves_from_settings_on_synthesis_path`
- [ ] Empty settings and supported legacy environment values preserve current behavior.
  - Verify: `tests/tts/test_settings_backed_voices.py::test_empty_settings_and_legacy_tts_env_preserve_behavior`
- [ ] Fallback policy remains explicit and cannot silently widen local-only behavior.
  - Verify: `tests/tts/test_settings_backed_voices.py::test_tts_fallback_policy_stays_explicit_and_tier_gated`

## How to Verify (Pre-Merge)

- `pytest -q tests/tts/test_settings_backed_voices.py tests/tts/test_readback_segments_and_norm.py tests/cli/test_settings_explain_cli.py`
- `ruff check app tests`
- `mypy app`
- `pytest -q -m "not pg"`

## Out of Scope

Provider installation, external TTS calls, deployment, model-routing/rerank, watcher, curation, and expansion settings.

## Related Docs

- `docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md`
- `app/tts/config.py :: load_tts_config`

## Related GitHub Issues

Implements [#4797](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4797) after #4796 merges and is reconciled on `origin/main`.
