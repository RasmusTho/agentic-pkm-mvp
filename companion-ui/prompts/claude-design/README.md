# Claude Design Prompts

Use this folder for prompts that generate or refine interaction and visual handoff material for Yggdrasil / Companion UI.

## Governance

Output from Claude Design sessions must land in the governed handoff chain before becoming implementation work. See:

- [`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`](../../docs/DESIGN_HANDOFF_GOVERNANCE.md) — the full handoff chain (exploration → handoff → normalized spec → issue → PR → receipt), maturity checklist, and authority boundaries.
- [`companion-ui/docs/CORE_TERM_MAPPING.md`](../../docs/CORE_TERM_MAPPING.md) — maps design-language terms to Yggdrasil architecture language.
- [`companion-ui/design_handoff/README.md`](../../design_handoff/README.md) — the handoff archive index.

**Design output is guidance only.** It is not architecture authority and not runtime truth. Architecture authority lives in `docs/**` owner-docs.

## Prompt posture

- Preserve document-first, overlay-first interaction.
- Keep chat subordinate to document context.
- Avoid dashboard-style AI UX.
- Honor the gated-execution invariant: no interaction surface should mutate durable state outside the governed pipeline.
- The server declares class, posture, and authority; the UI renders. Design prompts should reflect this — do not propose UI surfaces that re-classify runtime state.

## Folder shape for exported packages

When a Claude Design session produces a handoff package, export it to:

```
companion-ui/design_handoff/<YYYY-MM-DD>-<slug>/
```

Required files for a Crossing-B-eligible package: `README.md`, `prototype.html`, `implementation-contracts.md`, `authority-boundaries.md`, `open-questions.md`. See `DESIGN_HANDOFF_GOVERNANCE.md` for the full folder-shape spec.
