---
name: Single Default Registry
description: Every behavior-shaping default is declared exactly once; duplicated env-default literals at call sites are collapsed
task_id: SETTINGS-02
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3
parent_capability: Settings Spine
prerequisites: []
depends_on: []
can_parallelize_with: [Wire Settings Ingestion]
---

# Single Default Registry

## Purpose

Close the duplicated-default divergences from audit finding F3 (SET-4): the same setting has
different defaults at different call sites today — `LLM_TIMEOUT` defaults to 12s
(`app/services/llm.py:376`), 60s (`app/llm/adapter.py:74,88`) and 120s (`app/llm/adapter.py:56`);
`WATCHER_ENABLE` defaults to `"0"` in `app/watcher/config.py:147` and `"1"` in
`app/watcher/registry.py:472`.

## What This Task Does

- Introduces one default-declaration surface (extending the existing `SETTING_DEFINITIONS`
  registry pattern in `app/vault/settings_service.py:185-265` or the pydantic settings models —
  implementer's choice, but ONE place per key).
- Migrates every call site that currently inlines an env-read-with-literal-default for an already
  known settings key to read through the registry.
- Resolves each divergence explicitly (the registry entry documents the chosen value and why).
- Adds a gate test that fails when a behavior-shaping default literal is duplicated at a call site
  for a registered key.

## Concretely

```
$ grep -rn 'LLM_TIMEOUT' app/ | grep -v registry   # after: only registry reads, no literals
$ pytest -q tests/architecture/test_single_default_registry.py   # divergence gate green
```

## Why This Matters

Duplicated defaults are how the five-substrate split regrows: each new call site re-declares its
own truth, and two components disagree about the same knob without anyone deciding it.

## Acceptance Criteria

- [ ] `LLM_TIMEOUT` and `WATCHER_ENABLE` each resolve to one declared default from one declaration
      site; all previous call sites read through it.
  - Verify: `tests/architecture/test_single_default_registry.py::test_no_duplicated_default_literals`
- [ ] The gate covers registered keys generically (adding a second default literal for any
      registered key fails CI), not just the two named repairs.
  - Verify: `tests/architecture/test_single_default_registry.py::test_gate_detects_new_duplicate`
- [ ] Behavior change from default unification is stated explicitly in the PR (which value won and
      why), and existing behavior tests pass.
  - Verify: `pytest -q -m "not pg"` green + PR body section "Default resolutions"
- [ ] SET-4 is registered in the invariant registry with enforcement `static_test`.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: single_default_registry`

## How to Verify (Pre-Merge)

- `pytest -q tests/architecture/test_single_default_registry.py`
- `pytest -q -m "not pg"` (shared surfaces touched)

## Out of Scope

- Exposing the keys as vault-editable settings (SETTINGS-07 migrates values into the user surface;
  this task only unifies where defaults are declared).
- Location changes (SETTINGS-03).

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3`

## Related GitHub Issues

One implementation issue. TCD hint: sonnet / medium — mechanical consolidation with a clear gate;
the only judgment call (which divergent default wins) is small and documented per key.
