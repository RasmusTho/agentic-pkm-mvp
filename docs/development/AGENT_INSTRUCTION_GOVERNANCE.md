State: Development reference. Not an auto-loaded instruction file.
# Builder-Agent Instruction Governance

This document explains how builder-agent instruction files are structured in this repository.

It governs development-time instruction surfaces only. It does not define runtime/system-agent semantics.

## Canonical entrypoints

- `AGENTS.md` is the canonical builder-agent instruction file for the repository.
- `.codex/skills/README.md :: Skill routing` is the complete discoverability index for repo-local
  skills. It is subordinate to `AGENTS.md`, but the root must link to it instead of maintaining a
  second full list.
- `CLAUDE.md` is a thin, non-operational compatibility/provenance pointer to `AGENTS.md`. It
  must not launch Claude, read Anthropic credentials, or select a provider/model target.
- `.codex/AGENTS.md` is a compatibility pointer only. It must not become the canonical policy surface again.

## Repo-local skills

- Repo-local Codex skills may live under `.codex/skills/` as optional workflow helpers for this repository.
- Repo-local skills are not canonical policy surfaces; they must defer to `AGENTS.md` and the owning development docs.
- The root must name unconditional early gates such as `klart`, and may name a small set of critical
  workflow entrypoints. Full skill discoverability belongs only in the linted Skill routing index.
- The Skill routing section must contain an entry for every immediate repo-local skill directory.
- Repo-local skills may summarize or sequence existing workflow steps, but they must not override Issue scope, acceptance criteria, PR linkage, or CI/validation requirements.
- Keep repo-local skills narrowly scoped, reversible, and aligned with the existing GitHub issue-first delivery model.
- Temporal-doc maintenance skills should prefer audit-first behavior, refresh owner/current-state docs before roadmap wording, and use explicit verification anchors rather than implied freshness.

## Separation rules

- Keep auto-loaded instruction files short, normative, and durable.
- Put rationale, migration notes, governance, and maintenance guidance in development reference docs such as this file.
- Keep runtime/system-agent architecture in `docs/AGENTS.md` and the related SoT concept/architecture docs.
- Do not store historical drift analysis, changelog-style narrative, or governance detail in `AGENTS.md` or `CLAUDE.md`.

## Maintenance rules

- Update `AGENTS.md` only for durable builder-agent policy changes.
- Keep `AGENTS.md` at or below 161 lines, 2,080 whitespace-delimited words, and 15,500 characters.
  These budgets preserve the owner's requested 30% active-instruction ceiling against the
  pre-compaction baseline while leaving margin for platform newline differences.
- Update `CLAUDE.md` only to keep the non-operational compatibility/provenance pointer
  aligned or to retire it through a governed change.
- If a longer explanation is needed, extend a development reference doc instead of expanding the root instruction files.
- When canonical entrypoints, reading order, or doc roles change, update `docs/DOCS_INDEX.md` in the same change.
- When compatibility pointers remain, label them explicitly as non-canonical.
- Keep backlog-discipline rules in `AGENTS.md` when agents must follow them during normal execution; do not leave required task-contract behavior only in reference docs.
- Keep the source-anchor naming convention and GitHub-first receipt rationale in development reference docs, but keep the "must use Source Anchors" rule in the root instruction file.
- Run `python3 scripts/lint_skills_consistency.py` after any skill-index change; the lint owns
  directory-to-index completeness and section-citation validity.

## Review checklist

When changing builder-agent guidance, confirm:

- `AGENTS.md` remains the canonical root instruction file.
- `AGENTS.md` remains within its line, word, and character budgets.
- the Skill routing index names every repo-local skill, including `klart`.
- `CLAUDE.md` is shorter than `AGENTS.md`, remains non-operational compatibility/provenance
  only, and does not authorize Claude execution, credentials, or provider/model selection.
- runtime/system-agent docs are still clearly separate from builder-agent instruction files.
- long rationale or recordkeeping lives outside the auto-loaded instruction files.
- duplicated normative policy has not been introduced across `AGENTS.md`, `CLAUDE.md`, and development docs.
- builder-agent backlog rules are explicit enough that a new agent can create, pick up, and close delivery work without relying on chat-only context.
