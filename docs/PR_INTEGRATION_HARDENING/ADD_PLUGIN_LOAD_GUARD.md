---
name: Add Plugin Load Guard
description: Add a caution about explicit pytest plugin loading to docs/TESTING.md and the pr-integration skill CI triage section.
task_id: PIH-01
source_anchor: docs/learning-log.md :: 2026-05-06 — #783
parent_capability: PR_INTEGRATION_HARDENING
prerequisites: []
depends_on: []
can_parallelize_with: [ADD_BRANCH_TRUTH_GATE]
---

# Add Plugin Load Guard

## Purpose

When `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set, pytest flags provided by plugins (e.g. `-n`/`--dist` from `pytest-xdist`) silently fail or error unless the plugin is explicitly loaded via `-p <plugin_name>`. This was discovered during PR #783 and was not documented anywhere in the repo.

## What This Task Does

1. Adds a caution block to `docs/TESTING.md` explaining that plugin-provided pytest flags require explicit plugin loading when `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is active, with a concrete example for `xdist`.
2. Adds a short CI triage note to `.codex/skills/pr-integration/SKILL.md` (in its CI failure triage section) so agents diagnosing a "flag not recognised" or "no such option" CI failure know to check for missing explicit plugin load before adding dependencies.

## Concretely

**docs/TESTING.md** addition (under the relevant pytest invocation section):

```
> **Plugin-load guard:** When `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set, flags provided by
> plugins are not available unless the plugin is also explicitly loaded with `-p <plugin_name>`.
> For example, to use `pytest-xdist` with autoload disabled:
> ```
> PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p xdist.plugin -n auto ...
> ```
> Do not assume installing a plugin is sufficient — verify the flag resolves with an explicit
> `-p` load if autoload is disabled.
```

**.codex/skills/pr-integration/SKILL.md** CI triage addition:

```
- If CI reports "unrecognised option" or "no such option" for a pytest flag that corresponds to
  an installed plugin, check whether `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set and the plugin
  is not explicitly loaded. Add `-p <plugin_name>` to the pytest invocation.
  [plugin-load-guard]
```

## Why This Matters

Without this guard, an agent diagnosing a CI failure on a flag like `-n`/`--dist` will try adding/upgrading the dependency instead of adding the `-p` load, wasting CI cycles and potentially introducing unneeded dependency changes.

## Acceptance Criteria

- [ ] `docs/TESTING.md` contains a caution block about explicit plugin loading under `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` with a concrete xdist example.
  Verify: doc writeback at `docs/TESTING.md :: plugin-load-guard`
- [ ] `.codex/skills/pr-integration/SKILL.md` CI triage section contains the `[plugin-load-guard]` note.
  Verify: doc writeback at `.codex/skills/pr-integration/SKILL.md :: plugin-load-guard`

## How to Verify (Pre-Merge)

```bash
grep -n "plugin-load-guard\|PYTEST_DISABLE_PLUGIN_AUTOLOAD" docs/TESTING.md
grep -n "plugin-load-guard\|PYTEST_DISABLE_PLUGIN_AUTOLOAD" .codex/skills/pr-integration/SKILL.md
```

Both commands must return at least one hit. Confirm the text matches the spec above.

Run the repo docs validation check:
```bash
python scripts/docs_guard.py 2>/dev/null || echo "no docs guard"
```

## Out of Scope

- Changing any pytest invocation in CI workflows.
- Adding `-p xdist.plugin` to any existing test commands.
- Documenting any plugins other than xdist as the concrete example.

## Related Docs

- [docs/TESTING.md](../TESTING.md)
- [.codex/skills/pr-integration/SKILL.md](../../.codex/skills/pr-integration/SKILL.md)
- [docs/learning-log.md](../learning-log.md) (entry 2026-05-06 — #783)
- [docs/PR_INTEGRATION_HARDENING/README.md](README.md)

## Related GitHub Issues

Create one bounded governance issue: `[PR-Integration-Hardening] add-plugin-load-guard: document xdist explicit load requirement`.
Label: `lane:governance`, `agent:ready`, `Status=Ready`.
