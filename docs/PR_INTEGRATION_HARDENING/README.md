State: Specification. Active — parent issue #835, implementation issues #836 #837 #838.
Doc role: Capability specification
Authority: Feature specification; governed by docs/development/DEV_WORKFLOW.md
Owner: docs/development/DEV_WORKFLOW.md
Source: docs/learning-log.md (entries 2026-05-06 through 2026-05-07)

# PR Integration Hardening

Three divergences logged after the 2026-05-06 retrospective all point at the same surface: the `pr-integration` skill (and its upstream neighbor `issue-to-code`) lacks explicit guards against the most common failure modes encountered in recent delivery. This capability repairs those gaps.

## Capability intent

Add three concrete hardening steps to the integration and implementation lane skills and supporting docs:

1. **Plugin-load guard** — document that pytest flags provided by plugins (e.g. `-n`/`--dist` from `pytest-xdist`) require explicit plugin loading when `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set; add this caution to `docs/TESTING.md` and to the `pr-integration` skill CI triage section.
2. **Branch-truth gate** — mandate a hard branch-truth check (`git branch --show-current` + PR head SHA equality) before any `git add/commit/push` in `issue-to-code` and `pr-integration`; mandate a per-issue worktree for the full issue lifecycle in multi-agent work.
3. **Merge-ref validation** — add an explicit post-push merge-ref fetch-and-verify step to `pr-integration`: after review-fix pushes, fetch `pull/<id>/merge`, inspect touched symbols, and run at least one target test against that tree before declaring PR ready.

## Source entries

| Entry date | Issue/PR | Upstream artifact |
|---|---|---|
| 2026-05-06 | #783 | `docs/TESTING.md` + `pr-integration/SKILL.md` |
| 2026-05-07 | #775 | `issue-to-code/SKILL.md` + `pr-integration/SKILL.md` |
| 2026-05-07 | PR #800 | `pr-integration/SKILL.md` |

## Specification files

- [ADD_PLUGIN_LOAD_GUARD.md](ADD_PLUGIN_LOAD_GUARD.md) — xdist explicit-load caution in TESTING.md + pr-integration
- [ADD_BRANCH_TRUTH_GATE.md](ADD_BRANCH_TRUTH_GATE.md) — branch-truth gate + worktree isolation mandate in issue-to-code + pr-integration
- [ADD_MERGE_REF_VALIDATION.md](ADD_MERGE_REF_VALIDATION.md) — merge-ref validation step in pr-integration

## Execution order

All three tasks touch `.codex/skills/pr-integration/SKILL.md` and must be serialized to avoid diff conflicts:

1. `ADD_PLUGIN_LOAD_GUARD` — touches `docs/TESTING.md` + `pr-integration/SKILL.md`
2. `ADD_BRANCH_TRUTH_GATE` — touches `issue-to-code/SKILL.md` + `pr-integration/SKILL.md`; sequence after 1
3. `ADD_MERGE_REF_VALIDATION` — touches `pr-integration/SKILL.md` only; sequence after 2

No two tasks may be worked in parallel. Each must merge before the next is picked up.

## GitHub issues

| Task | Issue |
|---|---|
| Parent feature | [#835](https://github.com/RasmusTho/agentic-pkm-mvp/issues/835) |
| PIH-01: Add Plugin Load Guard | [#836](https://github.com/RasmusTho/agentic-pkm-mvp/issues/836) — merged |
| PIH-02: Add Branch Truth Gate | [#837](https://github.com/RasmusTho/agentic-pkm-mvp/issues/837) — merged |
| PIH-03: Add Merge-Ref Validation | [#838](https://github.com/RasmusTho/agentic-pkm-mvp/issues/838) — merged (PR [#861](https://github.com/RasmusTho/agentic-pkm-mvp/pull/861), 2026-05-11) |

## Acceptance criteria

- [x] `docs/TESTING.md` contains a caution about explicit plugin loading under `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
  Verify: doc writeback at `docs/TESTING.md :: plugin-load-guard`
- [x] `pr-integration/SKILL.md` contains a CI triage note about plugin-provided flags requiring explicit load.
  Verify: doc writeback at `.codex/skills/pr-integration/SKILL.md :: plugin-load-guard`
- [x] `issue-to-code/SKILL.md` contains a branch-truth gate step before any commit action.
  Verify: doc writeback at `.codex/skills/issue-to-code/SKILL.md :: branch-truth-gate`
- [x] `pr-integration/SKILL.md` contains a merge-ref fetch-and-verify step after review-fix pushes.
  Verify: doc writeback at `.codex/skills/pr-integration/SKILL.md :: merge-ref-validation`
- [ ] `docs/learning-log.md` retro marker appended after all three tasks merge.
  Verify: retro marker entry in `docs/learning-log.md` referencing this capability.

## Validation / acceptance path

After all three implementation issues close:

1. Manually confirm the four skill/doc changes are present in the merged state.
2. Observe adoption over the next 2–3 deliveries to confirm the guards prevent recurrence.
3. Append the retro marker to `docs/learning-log.md`.
4. Close the parent feature issue.

Owner-doc promotion: not required — this capability repairs skill/doc text, not shipped product behavior.

## Change lane

Governance lane — all changes stay within `.codex/skills/**` and `docs/**`.
