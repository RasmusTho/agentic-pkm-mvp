# Codex Implementation Boundary

This document defines the constraints Codex must observe when implementing changes from
the Claude Design specification. It is addressed to Codex.

Claude Design produces a design specification. Codex implements it. This document defines
what Codex may and may not do within the Companion UI implementation.

---

## The sequence

1. Claude Design reviews the Companion UI against this package.
2. Claude Design produces a design specification (prioritized recommendations, acceptance
   criteria, typography specifications, error-state specifications).
3. A human reviews the Claude Design output and decides what to implement.
4. Codex implements the accepted design specification as bounded GitHub issues.

**Codex must not infer design changes from screenshots alone.** Screenshots are inputs to
Claude Design's review, not implementation instructions. Codex implements what Claude Design
specified and a human accepted — not what Codex infers from looking at a screenshot.

---

## What Codex may implement

- CSS and Tailwind class changes that affect typography, spacing, color, and visual hierarchy
  in the note body, outline, and Panel.
- HTML/Jinja2 template changes that improve structure, accessibility, or information
  organization without changing Markdown rendering logic.
- Design token updates (CSS custom properties or Tailwind config extensions) that enforce
  the specified design system.
- Error and missing-state visual treatments for known failures (Mermaid, wikilinks, images,
  body edit unavailability) as specified by Claude Design.
- Structural layout changes (column widths, surface proportions, responsive behavior) as
  specified by Claude Design.
- Stable test selectors and test fixtures that verify design states without relying on visual
  regression testing alone.

---

## What Codex must not do without explicit scope

### Do not fix Mermaid, wikilinks, images, or body edit in the typography issue

These are separate functional problems with separate implementation tracks. The design review
may produce specifications for what their degraded/missing states should look like — Codex
may implement those visual specifications. But Codex must not treat the design review as
authorization to fix the underlying functionality of Mermaid, wikilink resolution, image
loading, or body edit.

If a Claude Design recommendation requires resolving a wikilink or rendering a Mermaid
diagram, that recommendation must be scoped as a separate bounded implementation issue, not
folded into a typography or visual design issue.

### Do not change governance/write boundaries

The Companion UI must not write vault files directly. All mutations route through the runtime
governance pipeline: policy, WriteGuard, idempotency, deterministic note-writer, receipt.
No design change may create a path that bypasses this boundary.

Specifically:
- Task checkbox toggling must not be made interactive without a governed write contract.
- Frontmatter editing must not be enabled without a governance route through Panel/governance.
- Body edit controls must route through the Canvas body-edit API (`POST /api/canvas/sessions/{id}/edits`), not through any direct vault write.
- Panel proposals must not auto-execute. Each proposal requires explicit human confirmation.

If Claude Design specifies an affordance that would require bypassing governance, Codex must
stop and raise a bounded implementation question rather than proceeding with a bypass.

### Do not keep Markdown/Vault as an afterthought

Any implementation change must preserve vault compatibility:
- Markdown files must remain readable in Obsidian without the Companion UI.
- Frontmatter must remain human-legible YAML.
- Wikilinks must remain standard Obsidian wikilinks.
- Removing the Companion UI must not damage the vault.

### Do not infer requirements from screenshots

Screenshots document the current state for Claude Design's review. They are not specifications.
Codex implements from the Claude Design specification and the bounded GitHub issue that
captures it — not from visual inference.

---

## Preferred implementation approaches

### Prefer CSS / design-token changes

Typography, spacing, color, and visual hierarchy changes should be implemented as CSS or
Tailwind changes rather than as structural HTML changes where possible. This minimizes
regression risk and keeps changes reviewable.

Where the current Tailwind configuration does not support the required design tokens, extend
it using CSS custom properties or Tailwind config rather than inline styles.

### Prefer focused tests

Any implementation must be verifiable. Use:
- Snapshot or DOM assertion tests for structural HTML changes.
- Tailwind/CSS class assertion tests for visual token changes where possible.
- Focused UAT steps in the implementing issue's acceptance criteria.

Do not rely on visual regression screenshot tests as the primary verification method —
they are brittle and slow. Use them only as supplementary evidence.

### Use human UAT for design verification

Automated tests verify structural correctness. Human UAT verifies that the design change
achieves the intended cognitive effect. Codex should always include human UAT steps in the
acceptance criteria for design-driven implementation changes.

---

## What a bounded implementation issue must contain

When Codex creates a GitHub issue from a Claude Design recommendation, the issue must
include:

- A reference to the Claude Design specification it implements.
- A specific, bounded scope (one component, one element, one feature area — not "redesign
  the entire workspace").
- Acceptance criteria with `Verify:` targets: either a concrete test pointer or a concrete
  human UAT step.
- An explicit `Out of scope` section listing what the issue does not cover.

Issues must not expand scope beyond what Claude Design specified and a human accepted.

---

## Authority hierarchy for implementation decisions

When implementation choices arise that Claude Design did not specify:

1. The governing GitHub issue (scope and acceptance criteria) wins.
2. The surface contracts listed below win over inferred requirements.
3. Codex must stop and raise a bounded question rather than improvise a design decision.

Binding surface contracts:
- `companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md` — renderer and parser boundaries
- `companion-ui/docs/OBSIDIAN_COMPATIBILITY_MATRIX.md` — feature phase and mutation risk
- `companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md` — hosting and vault-boundary rules
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — cognitive and integration boundary rules
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md` — Panel surface contract and write-back boundary
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — Canvas body-edit governance
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — product mode model
- `docs/DESIGN_PRINCIPLES.md` — boundary-first design and explicit mutation authority

---

## Summary: Codex in three sentences

Codex implements the design specification Claude Design produced and a human accepted. Codex
does not infer design changes from screenshots, does not bypass governance boundaries, and
does not expand scope beyond the bounded issue. When Codex encounters an ambiguity or a
governance boundary conflict, it stops and raises a question rather than improvising.
