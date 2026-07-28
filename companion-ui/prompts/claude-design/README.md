# Claude Design Prompts

Use this folder for prompts that generate or refine interaction and visual handoff material for Yggdrasil / Companion UI.

## Governance

Output from Claude Design sessions must land in the governed handoff chain before becoming implementation work. See:

- [`.codex/skills/yggdrasil-design-handoff/SKILL.md`](../../../.codex/skills/yggdrasil-design-handoff/SKILL.md)
  — mandatory workflow and fail-closed design-system preflight.
- [`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`](../../docs/DESIGN_HANDOFF_GOVERNANCE.md) — the full handoff chain (exploration → handoff → normalized spec → issue → PR → receipt), maturity checklist, and authority boundaries.
- [`companion-ui/docs/CORE_TERM_MAPPING.md`](../../docs/CORE_TERM_MAPPING.md) — maps design-language terms to Yggdrasil architecture language.
- [`companion-ui/design_handoff/README.md`](../../design_handoff/README.md) — the handoff archive index.

**Design output is guidance only.** It is not architecture authority and not runtime truth. Architecture authority lives in `docs/**` owner-docs.

## Mandatory design-system preflight

Use [`YGGDRASIL_HANDOFF_TEMPLATE.md`](YGGDRASIL_HANDOFF_TEMPLATE.md) as the first block in every
Claude Design request that creates or changes a visual.

Before generation:

1. Resolve and select the live **Yggdrasil Design System**.
2. Verify its `colors_and_type.css` matches
   `companion-ui/companion-app/colors_and_type.css` byte for byte.
3. Read the relevant reusable components and previews instead of reconstructing them from memory.
4. Record the selection and token hash in the package README.

If selection or token parity cannot be proved, stop. Do not let Claude Design use its generic
default aesthetic and do not treat later recoloring as compliance.

## Prompt posture

- Treat Yggdrasil tokens and existing components as binding; propose extensions explicitly instead
  of silently inventing colors, type, spacing, radii, icons, or primitives.
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
