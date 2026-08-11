---
name: Dehardcode Wave One
description: SETTINGS-07 validation hub and serial ledger for the highest user-meaning settings migrations
task_id: SETTINGS-07
github_issue: 3165
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3
parent_capability: Settings Spine
prerequisites: [SETTINGS-02, SETTINGS-03]
depends_on: [SINGLE_DEFAULT_REGISTRY.md, CANONICALIZE_SETTINGS_LOCATION.md]
can_parallelize_with: [Prompts As Settings]
---

# Dehardcode Wave One

## Purpose

This is the SETTINGS-07 validation hub. The three bounded child specifications migrate the first
wave of user-meaningful env-only/constant-only values, so an operator tunes behavior by editing
markdown rather than redeploying with different environment variables.

## What This Task Does

The hub owns the serial child ledger and stage-level acceptance. Each child owns its own registry
keys and production consumers:

1. [LLM_AND_RETRIEVAL_SETTINGS.md](LLM_AND_RETRIEVAL_SETTINGS.md) / SETTINGS-07A / #4796
2. [TTS_SETTINGS.md](TTS_SETTINGS.md) / SETTINGS-07B / #4797
3. [WATCHER_AND_TUNING_SETTINGS.md](WATCHER_AND_TUNING_SETTINGS.md) / SETTINGS-07C / #4798

The original wave-one scope is allocated as follows:

- **Model overrides and rerank:** SETTINGS-07A.
- **TTS:** SETTINGS-07B.
- **Curation/expansion thresholds and watcher tunables:** SETTINGS-07C.

Env vars for migrated keys keep working one release as bootstrap overrides with a deprecation
note in `settings explain` output; the registry is the declaration point (SETTINGS-02 gate
applies).

## Concretely

```
$ agentic-pkm settings explain retrieval.rerank.top_k
  origin: vault-shared (settings/retrieval.md) | default: registry (none) | tier: lab
$ agentic-pkm settings explain tts.voices.sv
  origin: registry default (sv_SE-lisa-medium) | env override: TTS_SV_VOICE (deprecated for tuning)
```

## Why This Matters

This is the "settings should not be hardcoded as they largely are today" payoff: the values a
product owner actually wants to tune become tunable, with origin visibility, without growing a
parallel mechanism per subsystem.

## Acceptance Criteria

- [ ] Every child has a merged delivery receipt and the parent ledger names SETTINGS-07 delivered.
  - Verify: doc writeback at `docs/SETTINGS_SPINE/PARENT_FEATURE_ISSUE.md :: Child issues (execution order)`
- [ ] Every migrated wave-one key is explainable with origin and tier while empty settings preserve behavior.
  - Verify: `tests/settings/test_llm_retrieval_settings.py::test_empty_settings_and_legacy_env_preserve_llm_and_rerank_behavior`
  - Verify: `tests/tts/test_settings_backed_voices.py::test_empty_settings_and_legacy_tts_env_preserve_behavior`
  - Verify: `tests/settings/test_watcher_and_tuning_settings.py::test_empty_settings_legacy_env_and_operator_tier_preserve_watcher_and_tuning_behavior`

## How to Verify (Pre-Merge)

- Run every child’s declared validation on its exact delivery SHA.
- On the final child, run `pytest -q -m "not pg"` and attach the result to #3165 and #3156.

## Out of Scope

- Implementation; each code change belongs to the named child.
- Wave two (embedding provider knobs, API browse limits, panel-agent decider, knowledge adapter
  choice).
- Removing env vars — bootstrap override semantics stay.
- Prompt migration (SETTINGS-06).

## Restart / Durability Posture

All wave-one keys are md-durable with registry defaults; restart resolves identically. No new
non-durable user-facing state.

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3` (full inventory table)
- `docs/SETTINGS.md :: Settings Tiering`

## Related GitHub Issues

May split into 2-3 issues if one PR grows past review size (llm+retrieval / tts / watcher+
curation are natural cuts); the spec is the source of truth either way. TCD hint: sonnet / medium
per cut — mechanical migrations onto an established spine; the one subtle fix (constant-vs-field)
is called out explicitly.
