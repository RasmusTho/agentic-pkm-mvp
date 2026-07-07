---
name: Prompts As Settings
description: Vault settings/prompts/*.md become the runtime prompt source of truth; the dead loader and stale descriptive mirrors are removed
task_id: SETTINGS-06
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3
parent_capability: Settings Spine
prerequisites: [SETTINGS-03]
depends_on: [CANONICALIZE_SETTINGS_LOCATION.md]
can_parallelize_with: [Dehardcode Wave One]
---

# Prompts As Settings

## Purpose

Make the prompt md files real (SET-6). Today the ask prompt's source of truth is the Python
constant `DEFAULT_ASK_SYSTEM_PROMPT` (`app/settings/models.py:285-296`); the compiler key exists
but no vault prompt note does; `docs/settings/prompts/*.v1.md` self-declare as descriptive
mirrors; and the loader that would read them (`app/components/settings/prompts_loader.py:53-103`)
has zero callers — dead code that looks like a capability.

## What This Task Does

- Seeds `<vault>/settings/prompts/ask.md` (canonical location per SETTINGS-03) from the current
  constant and makes the runtime resolve `AskSettings.system_prompt` from it through the spine
  (registry default = the code constant, vault file overrides — normal precedence, hot-reloaded
  via SETTINGS-01).
- Locates the classifier prompt's actual runtime source (audit left it unresolved —
  `docs/settings/prompts/classifier.v1.md` mirrors something not found in `app/settings/models.py`)
  and gives it the same treatment, or records exactly why it stays code-owned (schema-binding
  I-C3 coupling may justify code ownership for the output-schema half; the instruction text still
  migrates).
- Deletes `app/components/settings/prompts_loader.py` (dead) and either deletes
  `docs/settings/prompts/*` or regenerates them as clearly marked, generated projections of the
  vault/runtime truth — never a hand-maintained "keep in sync" mirror again.
- Adds the drift check (DOCTOR): any remaining mirror artifact is compared against its source in
  CI; divergence fails visibly.

## Concretely

```
$ $EDITOR "$VAULT/settings/prompts/ask.md"     # tighten the answering style, save
$ curl -s localhost:8000/api/ask -d '{"q":"..."}'   # answer reflects the edited prompt
$ agentic-pkm settings explain ask.system_prompt
  origin: vault-shared (settings/prompts/ask.md), default: registry (DEFAULT_ASK_SYSTEM_PROMPT)
```

## Why This Matters

Tone and answering behavior are the most user-meaningful settings the product has, and today they
are unreachable without a code deploy. This is also the template for every future prompt: md file
is truth, constant is seed.

## Acceptance Criteria

- [ ] Editing `settings/prompts/ask.md` changes `/api/ask` behavior without restart; with no vault
      file present, behavior is identical to today (constant as registry default).
  - Verify: `tests/settings/test_prompts_as_settings.py::test_ask_prompt_resolves_from_vault`
    (enforcement AC — asserts resolution through the production ask path,
    `app/agents/ask/utils.py`, not the settings model in isolation)
- [ ] `prompts_loader.py` is deleted; no dangling imports.
  - Verify: `tests/settings/test_prompts_as_settings.py::test_dead_loader_removed` (import scan)
- [ ] `docs/settings/prompts/*` are deleted or generated-and-marked; the drift check exists and
      fails on manufactured divergence.
  - Verify: `tests/architecture/test_prompt_mirror_drift.py::test_mirrors_are_generated_or_absent`
- [ ] `settings explain` names the origin of the effective prompt.
  - Verify: `tests/cli/test_settings_explain_cli.py::test_explain_prompt_origin` (extend existing)
- [ ] SET-6 registered in the invariant registry with enforcement `static_test` (DOCTOR-class
      reconciliation).
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: mirrors_declare_and_check_drift`

## How to Verify (Pre-Merge)

- `pytest -q tests/settings/test_prompts_as_settings.py tests/architecture/test_prompt_mirror_drift.py`
- `pytest -q -m "not pg"` (ask hot path touched)

## Out of Scope

- Migrating every agent prompt in one pass — ask (and classifier disposition) set the pattern;
  remaining prompts ride SETTINGS-07 or follow-ups.
- Prompt versioning/registry redesign — `registry.yaml` semantics stay as-is unless deleted with
  the mirrors.

## Restart / Durability Posture

The vault md file is the durable truth; the in-memory resolved prompt rebuilds on restart. Restart
with an invalid prompt file follows SETTINGS-01 degradation semantics (last-valid, visible state).

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3, RQ2`
- Memory precedent: prompt-contract docs are mirrors, ASK SoT = `DEFAULT_ASK_SYSTEM_PROMPT`

## Related GitHub Issues

One implementation issue. TCD hint: sonnet / high — bounded but touches the ask hot path and
deletes public-looking surfaces; review for accidental behavior drift in the seeded prompt.
