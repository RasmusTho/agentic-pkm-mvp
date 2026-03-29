State: Development reference. Not an auto-loaded instruction file.
# Builder-Agent Instruction Governance

This document explains how builder-agent instruction files are structured in this repository.

It governs development-time instruction surfaces only. It does not define runtime/system-agent semantics.

## Canonical entrypoints

- `AGENTS.md` is the canonical builder-agent instruction file for the repository.
- `CLAUDE.md` is a thin Claude adapter that should point to `AGENTS.md` and add only minimal Claude-specific notes when needed.
- `.codex/AGENTS.md` is a compatibility pointer only. It must not become the canonical policy surface again.

## Separation rules

- Keep auto-loaded instruction files short, normative, and durable.
- Put rationale, migration notes, governance, and maintenance guidance in development reference docs such as this file.
- Keep runtime/system-agent architecture in `docs/AGENTS.md` and the related SoT concept/architecture docs.
- Do not store historical drift analysis, changelog-style narrative, or governance detail in `AGENTS.md` or `CLAUDE.md`.

## Maintenance rules

- Update `AGENTS.md` only for durable builder-agent policy changes.
- Update `CLAUDE.md` only when Claude-specific adapter behavior is required.
- If a longer explanation is needed, extend a development reference doc instead of expanding the root instruction files.
- When canonical entrypoints, reading order, or doc roles change, update `docs/DOCS_INDEX.md` in the same change.
- When compatibility pointers remain, label them explicitly as non-canonical.

## Review checklist

When changing builder-agent guidance, confirm:

- `AGENTS.md` remains the canonical root instruction file.
- `CLAUDE.md` is shorter than `AGENTS.md` and does not restate it.
- runtime/system-agent docs are still clearly separate from builder-agent instruction files.
- long rationale or recordkeeping lives outside the auto-loaded instruction files.
- duplicated normative policy has not been introduced across `AGENTS.md`, `CLAUDE.md`, and development docs.
