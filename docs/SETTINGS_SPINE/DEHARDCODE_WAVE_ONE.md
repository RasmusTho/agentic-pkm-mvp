---
name: Dehardcode Wave One
description: The highest user-meaning hardcoded values — model routing overrides, TTS voices, rerank surface, curation/expansion thresholds, watcher tunables — migrate into the settings registry, tier-gated
task_id: SETTINGS-07
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3
parent_capability: Settings Spine
prerequisites: [SETTINGS-02, SETTINGS-03]
depends_on: [SINGLE_DEFAULT_REGISTRY.md, CANONICALIZE_SETTINGS_LOCATION.md]
can_parallelize_with: [Prompts As Settings]
---

# Dehardcode Wave One

## Purpose

Migrate the first wave of the ~50 user-meaningful env-only/constant-only values from audit
finding F3 into the settings surface, so an operator tunes behavior by editing markdown, not by
redeploying with different env vars.

## What This Task Does

Wave-one scope (each becomes a registry key with the current value as default, vault-editable at
the canonical location, tier-gated operator/lab per `app/settings/tiering.py`):

- **Model overrides:** `REASONING_MODEL`, `MERGE_LLM_MODEL` (both default `llama3.1:8b` today),
  `LLM_TEMPERATURE`, unified `LLM_TIMEOUT` (post SETTINGS-02) → `settings/llm_routing.md` keys.
- **TTS:** voices (`TTS_SV_VOICE`, `TTS_EN_US_VOICE`, `TTS_EN_GB_VOICE`) and the local-only /
  fallback toggles → a `settings/tts.md` note; `app/tts/config.py` gains a settings-backed layer
  (env remains deploy bootstrap override, lab-tier).
- **Rerank:** `RERANK_ENABLE`, `RERANK_PROVIDER`, `RERANK_TOP_K` → `settings/retrieval.md`
  (lab-tier; remaining RERANK_* stay env bootstrap).
- **Curation/expansion thresholds:** contradiction floor 0.4, relatedness floor 0.55, retrieval
  k 8, findings caps — and fix the constant-vs-field defect where the module constant is read
  instead of the configured instance field (`app/curation/contradiction.py:108,336`,
  `app/expansion/connect.py:112,212`) so configuration actually flows (lab-tier).
- **Watcher tunables:** debounce, rate limit, backoff, tick sleep, per-tick caps
  (`app/watcher/config.py:170-204`) → `settings/watchers.md` (lab-tier), env as bootstrap
  override.

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

- [ ] Every wave-one key resolves through the spine and is visible in `settings explain` with its
      origin and tier.
  - Verify: `tests/cli/test_settings_explain_cli.py::test_wave_one_keys_explainable` (extend)
- [ ] Curation/expansion passes honor configured thresholds (constant-vs-field defect fixed): a
      configured relatedness floor changes connect-pass admission.
  - Verify: `tests/expansion/test_connect_findings.py::test_configured_floor_is_honored`
    (enforcement AC — configures via the settings path and asserts the production pass uses it)
- [ ] TTS voice selection follows the settings value on the synthesis path.
  - Verify: `tests/tts/test_settings_backed_voices.py::test_voice_resolves_from_settings`
- [ ] Watcher tunables from settings reach `WatcherConfig` on startup and on reload.
  - Verify: `tests/watcher/test_settings_tiering_profile.py::test_tunables_from_settings` (extend
    existing module)
- [ ] Operator/lab tiering holds: lab-tier keys are inert under the operator profile and say so in
      `settings explain`.
  - Verify: `tests/settings/test_tiering_wave_one.py::test_lab_keys_inert_under_operator`
- [ ] No behavior change with an empty settings folder (defaults identical to today).
  - Verify: `pytest -q -m "not pg"` green with no settings fixtures

## How to Verify (Pre-Merge)

- `pytest -q tests/settings tests/cli/test_settings_explain_cli.py tests/expansion/test_connect_findings.py tests/tts -k settings`
- `pytest -q -m "not pg"` (broad shared surfaces — full suite mandatory)

## Out of Scope

- Wave two (embedding provider knobs, API browse limits, panel-agent decider, knowledge adapter
  choice) — follow-up issues after wave one proves the pattern.
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
