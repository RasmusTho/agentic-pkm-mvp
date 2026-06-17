---
name: Add Merge-Ref Validation
description: Add an explicit merge-ref fetch-and-verify step to pr-integration after any review-fix push.
task_id: PIH-03
source_anchor: docs/learning-log.md :: 2026-05-07 — PR #800
parent_capability: PR_INTEGRATION_HARDENING
prerequisites: [PIH-02]
depends_on: [ADD_BRANCH_TRUTH_GATE.md]
can_parallelize_with: []
---

# Add Merge-Ref Validation

## Purpose

PR #800 had a `NameError` on the CI merge-ref that was invisible on the branch HEAD, because the merge-ref was assembled by GitHub from a base that diverged during conflict churn. Validating only the branch HEAD gave a false green before merge.

## What This Task Does

Adds a **merge-ref validation step** to `.codex/skills/pr-integration/SKILL.md` that runs after any review-fix push and before the skill declares `ready-for-verification`. The step:

1. Fetches `refs/pull/<PR_NUMBER>/merge` from origin.
2. Checks out that ref in a temporary detached state (or uses `git fetch` + `git show`).
3. Inspects touched symbols in that tree — specifically verifies that import sites and call sites for any symbols changed in the review-fix are consistent in the merge-ref, not only on the branch HEAD.
4. Runs at least one target test from the PR's test suite against the merge-ref tree.
5. If step 3 or 4 fails, the skill must report `blocked-ci-failure` and require another fix push rather than declaring ready.

## Concretely

**pr-integration/SKILL.md** addition (after the review-fix push section, before the exit-condition checklist):

```
### Merge-Ref Validation (mandatory after any review-fix push)

After pushing a review-fix, GitHub assembles a merge-ref at `refs/pull/<PR_NUMBER>/merge`.
Branch HEAD may be clean while the merge-ref carries a divergent context that causes CI-only failures.

```bash
PR_NUMBER=<PR_NUMBER>
git fetch origin refs/pull/${PR_NUMBER}/merge:refs/merge_validation

# Inspect touched symbols using git show — do NOT checkout into the active worktree
git show refs/merge_validation:app/<changed_module>.py | grep -n "<changed_symbol>"
```

Do not use `git checkout refs/merge_validation -- .`: that mutates the active working tree and index, leaving the PR branch dirty and risking accidental commits.

Then run a targeted smoke check in a **temporary separate worktree** to avoid touching the active branch state:

```bash
MERGE_WORKTREE=$(mktemp -d)
git worktree add --detach "$MERGE_WORKTREE" refs/merge_validation
(cd "$MERGE_WORKTREE" && pytest -q tests/<relevant_test_file>.py -k "<key_test>")
git worktree remove --force "$MERGE_WORKTREE"
```

If the test fails or the symbol is absent in the merge-ref:
- Do NOT declare `ready-for-verification`.
- Report `blocked-ci-failure` with the merge-ref tree context.
- Push a corrective fix to the branch and repeat this step.
[merge-ref-validation]
```

## Why This Matters

Declaring a PR ready based only on branch HEAD is insufficient when the merge-ref differs. CI fails on a tree that the agent never validated, creating a CI-only failure mode that is hard to diagnose and forces another integration loop.

## Acceptance Criteria

- [x] `.codex/skills/pr-integration/SKILL.md` contains a merge-ref validation section, labeled `[merge-ref-validation]`, after the review-fix push section.
  Verify: doc writeback at `.codex/skills/pr-integration/SKILL.md :: merge-ref-validation`
- [x] The section specifies: fetch `refs/pull/<PR>/merge`, inspect touched symbols in that tree, run at least one target test against it, and block on failure.
  Verify: doc writeback at `.codex/skills/pr-integration/SKILL.md :: merge-ref-validation`

Delivered by PR #861 (merged 2026-05-11).

## How to Verify (Pre-Merge)

```bash
grep -n "merge-ref-validation\|refs/pull.*merge" .codex/skills/pr-integration/SKILL.md
```

Must return at least one hit for the anchor label and at least one hit for the fetch command pattern.

Confirm the section appears after any review-fix section and before the exit-condition checklist.

## Out of Scope

- Automating the merge-ref fetch in CI (the validation is a skill-level manual step).
- Validating merge-refs in skills other than `pr-integration`.
- Changing GitHub Actions workflows.

## Related Docs

- [.codex/skills/pr-integration/SKILL.md](../../.codex/skills/pr-integration/SKILL.md)
- [docs/learning-log.md](../learning-log.md) (entry 2026-05-07 — PR #800)
- [docs/PR_INTEGRATION_HARDENING/README.md](README.md)

## Related GitHub Issues

Delivered. Governing issue: [#838](https://github.com/RasmusTho/agentic-pkm-mvp/issues/838) — closed by PR [#861](https://github.com/RasmusTho/agentic-pkm-mvp/pull/861) (merged 2026-05-11). No further issue creation needed.
