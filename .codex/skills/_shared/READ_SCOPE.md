State: Shared skill contract. Canonical read-scope protocol for every `FILE :: Section` citation in the agent instruction chain.

# Read Scope

Single source for **how much** of a cited document an agent must read. Instruction files
(`AGENTS.md`, `CLAUDE.md`, `.codex/skills/**`, and the development docs they route to) cite sources
in one of two shapes, and the shape is the instruction.

## The protocol

- **`FILE :: Section`** — read that heading's section only. Do not read the rest of the file.
  The cited heading is the narrowest true owner of the rule; anything outside it is reference
  material the citation does not require.
- **`FILE` with no `::`** — a whole-file read. It requires a stated reason at the citation site
  (for example "read whole; the file is a short checklist" or "read whole; the rule spans every
  section"). A bare whole-file citation with no stated reason is a defect in the instruction file,
  not a mandate to read the file.
- **A citation under a stated condition** — read it only when the condition holds. Conditions are
  keyed to the **actual diff** (`git diff --name-only origin/main...HEAD`), not to the issue's
  declared scope, because the diff is what the downstream gates judge.
- **`docs/DOCS_INDEX.md`** is grep-only. It is a ~250 KB, 700-row routing table; grep it for the
  work area to find the owner document, and never read it whole.

## Why this is safe

Reducing read scope removes a *read*, never a *check*. Every rule whose read is narrowed here is
still enforced by a downstream pre-merge gate. What actually runs as an unconditional pre-merge check
depends on the diff class:

- On every PR, regardless of diff class: CI's `pr-contract` job, plus the `smoke` job's three
  unconditional steps in `.github/workflows/ci-smoke.yaml` — `scripts/lint_skills_consistency.py`
  ("Skills consistency lint"), "Doc integrity", and `tests/architecture/test_pr_hot_path_governance.py`
  ("Hot path governance architecture test").
- Only when the diff touches code paths matched by the `code` filter in `ci-smoke.yaml`: CI's
  `Unit tests (not pg)` job (`pr-unit-tests-not-pg`). Its filter includes instruction and docs
  surfaces — `AGENTS.md`, `CLAUDE.md`, `.codex/**`, and `docs/**` — so those diffs run the job's
  focused test selection as well.
- Only when the diff touches the release/promotion harness surface named in
  `harness-selfverify.yml`'s `paths:` trigger (for example `tests/uat/**`, `app/ops/**`,
  `.codex/skills/promote-to-test/**`) or via its cron/manual dispatch: the `harness-selfverify`
  workflow.
- Only on governance/docs-only pull requests (`governance_docs == true` and `heavy_smoke != true`):
  the `smoke` job runs `scripts/docs_guard.py`. The same guard also remains available through manual
  `workflow_dispatch` in `architecture-ci.yaml`.
- The branch-truth gate and the verification step in `verification-and-closure` apply per their own
  governing procedures.

If a rule has no gate that actually fires for the diff class in front of you, its read stays
mandatory and unconditional.

The corollary is a maintenance rule: **before narrowing a citation, confirm the omitted content is
either reproduced at the citation site or caught by an existing fail-loud gate.** Content that is
unique to the cited section and has no gate must be inlined at the citation site before the parent
document becomes conditional.

## Scope

This contract governs read scope only. It does not change any authority, gate, check, or lane rule,
and it never authorizes skipping a section an instruction file marks as unconditional.
