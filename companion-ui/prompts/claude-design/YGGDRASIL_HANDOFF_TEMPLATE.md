# Yggdrasil Claude Design binding preamble

Status: Reusable prompt preamble. Design guidance only; not architecture or runtime authority.

Place this block before the task-specific brief and replace every bracketed receipt value.

---

You are designing for Yggdrasil. The selected **Yggdrasil Design System** is a binding input, not
an optional aesthetic reference.

Design-system receipt for this run:

- exact live name: `Yggdrasil Design System`
- live design-system ID: `[ID returned by list_design_systems]`
- selection/attachment mechanism: `[selected at project creation | attached under design-system/]`
- binding repo token source: `companion-ui/companion-app/colors_and_type.css`
- verified token SHA-256: `[matching live and repo hash]`
- reusable components/previews read: `[paths]`

Before producing a visual:

1. Read the selected design system's `SKILL.md`, `README.md`, `colors_and_type.css`, and relevant
   component/reference previews.
2. Reuse its tokens and existing components. Do not invent colors, typography, spacing, radii,
   icon style, or primitives because a generic dashboard convention is familiar.
3. If the brief needs something the system does not contain, name it as a proposed extension in
   `open-questions.md`. Do not silently use the extension in the prototype as if it were canonical.
4. Where design-system prose and the binding repo token sheet conflict, the repo token sheet wins.
   Report the conflict and stop the affected visual instead of guessing.
5. Preserve the task's product, authority, accessibility, responsive, JavaScript-off, and print
   constraints while expressing them through Yggdrasil's established visual/component language.

In the output README, repeat the receipt above and state whether token parity and visual compliance
passed. Visual resemblance alone is not compliance.

The output remains design guidance. It cannot modify owner docs, runtime contracts, shipped
components, or production authority.

---
