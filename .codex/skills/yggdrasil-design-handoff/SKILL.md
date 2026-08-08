---
name: yggdrasil-design-handoff
description: "Prepare, run, revise, validate, or archive governed Yggdrasil UI/component design handoffs, including Claude Design projects, prototypes, visual audits, interaction designs, and component specifications. Use whenever work creates or changes a visual surface, reusable component, design prototype, design-system-bound mockup, or Claude Design handoff for this repository."
---

# Yggdrasil Design Handoff

Use this Builder System workflow to keep external design exploration inside Yggdrasil's design
language and authority chain. Do not use a generic visual style when the canonical design system is
available.

## Required context

Read:

1. `AGENTS.md`
2. `docs/DESIGN_PRINCIPLES.md`
3. `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md` when the surface enters the Companion UI
   design-handoff chain
4. `companion-ui/prompts/claude-design/README.md`
5. `companion-ui/docs/CORE_TERM_MAPPING.md`
6. the owner docs for the surface being designed

For Claude Design work, use
`companion-ui/prompts/claude-design/YGGDRASIL_HANDOFF_TEMPLATE.md` as the binding prompt preamble.

## Fail-closed design-system gate

Complete this gate before asking a design model to produce or revise any visual:

1. Resolve the live design system by the exact name **Yggdrasil Design System** using
   `mcp__claude-design__list_design_systems`. The currently verified system ID is
   **f2b13410-af14-4875-8029-445352123f57**; treat a different or ambiguous live result as drift and
   stop for reconciliation.
2. Read the live design system's `SKILL.md`, `README.md`, `colors_and_type.css`, and the relevant
   component/reference previews. Do not rely on its name alone.
3. Hash the live `colors_and_type.css` and the repo's binding token source,
   `companion-ui/companion-app/colors_and_type.css`. They must match byte for byte. If they do not,
   stop before design generation and reconcile the two authorities.
4. Select the Yggdrasil Design System when creating the Claude Design project. If an existing
   project cannot express selection, copy/attach the live skill, README, exact token sheet, and
   relevant previews under `design-system/`, then put the binding preamble in the design request.
   Never assume that a default project inherited the system.
5. Record the exact system name and ID, selection/attachment mechanism, token source, and token
   SHA-256 in the handoff package README.

No successful gate means no design generation. Do not silently fall back to a generic aesthetic,
invent a replacement token set, or continue with an unverified similarly named system.

## Workflow

1. **Classify the artifact.** Keep exploration/handoff guidance separate from normalized specs,
   architecture authority, shipped components, and runtime truth.
2. **Bound the request.** Name the operator journey, surface, states, authority limits, source
   evidence, responsive/accessible states, and requested deliverables.
3. **Run the design-system gate.** Preserve its receipt in the package README.
4. **Prepare evidence.** Attach current screenshots, relevant implementation surfaces, the exact
   token sheet, reusable components/previews, and the most local owner contracts. Prefer targeted
   evidence over a repo-wide context dump.
5. **Generate or revise.** Make Yggdrasil a binding component and visual constraint, not a palette
   suggestion. Reuse existing primitives before proposing extensions. Write revisions to a new
   versioned output folder; do not overwrite an earlier accepted or reviewable design.
6. **Validate.** Inspect desktop, narrow, 200% zoom, keyboard, print, JavaScript-off, empty,
   degraded, and blocked states when relevant. Confirm that colors, type, spacing, radii, icons,
   and components are grounded in the design system. Name any proposed extension in
   `open-questions.md`; do not use it silently in the prototype.
7. **Dispose and cross deliberately.** Record whether the research/design result is accepted,
   rejected, deferred, or requires an owner decision. When accepted material crosses an authority
   class into a normative owner document or specification, create or consume the existing
   BuilderOps `PromotionIntent` boundary with source refs, target surface/ref, intended output, and
   its receipt. `PromotionIntent` is proposal/provenance material; it does not write the target.
   For Companion UI, preserve the package under
   `companion-ui/design_handoff/<YYYY-MM-DD>-<slug>/` only when requested and route implementation
   intent through Crossing B. For other Product or Builder surfaces, keep the external package as
   supporting design input and normalize accepted intent through that surface's local owner
   document or specification. In every case, implementation begins only from a bounded Issue and
   the normal PR chain.

Use `AGENTS.md :: Total Cost of Development` for model and review depth. Mechanical transport and
file synchronization do not need the same capability as substantive interaction design.

## Required receipt

Return:

```text
Yggdrasil Design Handoff Receipt:
- Surface:
- Authority state:
- Design system name:
- Design system ID:
- Selection/attachment mechanism:
- Repo token source:
- Token SHA-256:
- Token parity: pass|fail
- Output/project:
- Visual verification:
- Crossing state:
- Open authority questions:
```

Set `Token parity` to `fail` and stop if the live and repo token sheets differ. Never report a
handoff as Yggdrasil-compliant based only on visual resemblance.
