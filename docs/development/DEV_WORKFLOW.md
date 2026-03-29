State: Development reference. Not an auto-loaded instruction file.
# Development Workflow

Use this document for the builder-agent working loop and validation expectations after reading `AGENTS.md`.

This document applies to development-time contributors. It does not define runtime/system-agent behavior.

## Working loop

For non-trivial changes:

1. Identify the owning document via `docs/DOCS_INDEX.md`.
2. Read the owner doc before changing code or neighboring docs.
3. Add or update tests for the intended change when the work is not docs-only.
4. Implement the smallest change that fits the documented architecture.
5. Update owner docs in the same change when behavior, contracts, or architecture changed.
6. Run the relevant validation commands and record any gaps.

## Validation baseline

- Docs-only changes:
  - run any repo docs validation command if one exists
  - otherwise run lightweight repo checks that are still appropriate
- Code-affecting changes:
  - `ruff check app tests`
  - `mypy app`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`
- Settings/runtime contract changes:
  - `python -m app.cli settings-validate --json`

Run narrower or broader suites when the touched area requires it.

## Documentation rules

- Update the owner doc first.
- Keep current-state docs descriptive of shipped reality.
- Put future-state intent in roadmap/plan docs instead of current-state owner docs.
- Replace duplicated policy with links or short boundary notes.

## Runtime separation

- Builder-agent instruction lives in `AGENTS.md` and the development reference docs.
- Runtime/system-agent architecture lives in `docs/AGENTS.md` and related runtime/concept docs.
- Do not treat runtime semantics as builder-agent instructions, and do not write builder-agent workflow into runtime docs.
