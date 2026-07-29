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
still enforced by a downstream pre-merge gate — CI (`pr-contract`, `Unit tests (not pg)`,
`harness-selfverify`), `scripts/lint_skills_consistency.py`, `scripts/docs_guard.py`, the branch-truth
gate, or the verification step in `verification-and-closure`. If a rule has no such gate, its read
stays mandatory and unconditional.

The corollary is a maintenance rule: **before narrowing a citation, confirm the omitted content is
either reproduced at the citation site or caught by an existing fail-loud gate.** Content that is
unique to the cited section and has no gate must be inlined at the citation site before the parent
document becomes conditional.

## Scope

This contract governs read scope only. It does not change any authority, gate, check, or lane rule,
and it never authorizes skipping a section an instruction file marks as unconditional.
