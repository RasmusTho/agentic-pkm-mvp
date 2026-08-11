---
name: LLM And Retrieval Settings
description: Move model routing and rerank tuning through the Settings Spine without changing empty-settings behavior.
task_id: SETTINGS-07A
github_issue: 4796
source_anchor: docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md :: What This Task Does
parent_capability: Settings Spine
prerequisites: [SETTINGS-02, SETTINGS-03]
depends_on: [SINGLE_DEFAULT_REGISTRY.md, CANONICALIZE_SETTINGS_LOCATION.md]
can_parallelize_with: []
---

# LLM And Retrieval Settings

## Purpose

Make the existing model-routing and rerank controls vault-editable through the one Settings Spine, while preserving current defaults and one-release environment compatibility.

## What This Task Does

Adds registry declarations and canonical `settings/llm_routing.md` / `settings/retrieval.md` keys for model, timeout, temperature, and rerank controls. Production consumers resolve these keys through SettingsService; legacy environment variables stay bootstrap overrides and are visible as deprecated in `settings explain`.

## Concretely

`agentic-pkm settings explain retrieval.rerank.top_k` reports the vault-shared origin and lab tier.

## Why This Matters

Model and retrieval tuning are user-meaningful behavior. Leaving them as scattered environment reads recreates audit F3 and makes origin invisible to an operator.

## Acceptance Criteria

- [ ] Vault model-routing and rerank settings reach their production consumers and explain reports origin and tier.
  - Verify: `tests/settings/test_llm_retrieval_settings.py::test_vault_settings_reach_model_and_rerank_production_consumers`
- [ ] Empty settings and supported legacy environment overrides preserve current behavior.
  - Verify: `tests/settings/test_llm_retrieval_settings.py::test_empty_settings_and_legacy_env_preserve_llm_and_rerank_behavior`
- [ ] Lab keys are inert under the operator profile.
  - Verify: `tests/settings/test_llm_retrieval_settings.py::test_llm_and_rerank_lab_keys_are_inert_for_operator_profile`

## How to Verify (Pre-Merge)

- `pytest -q tests/settings/test_llm_retrieval_settings.py tests/cli/test_settings_explain_cli.py tests/retrieval/test_retrieval_tuning_config.py`
- `ruff check app tests`
- `mypy app`
- `pytest -q -m "not pg"`

## Out of Scope

TTS, watcher, curation, expansion, environment-variable removal, and release-channel work.

## Related Docs

- `docs/SETTINGS_SPINE/DEHARDCODE_WAVE_ONE.md`
- `docs/SETTINGS_SPINE/README.md :: Cross-Task Invariants / Interaction Safety`
- `app/services/llm.py :: _model`
- `app/retrieval/tuning.py :: load_retrieval_tuning`

## Related GitHub Issues

Implements [#4796](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4796), first in the serial SETTINGS-07 chain. Its delivery receipt is posted to #3156 before SETTINGS-07B starts.
