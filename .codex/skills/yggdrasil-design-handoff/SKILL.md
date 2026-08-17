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

## Required method

### Design-work classifier

Classify the complete requested visual scope before asking a design model to generate anything or
before using the constrained-reuse route. Tool availability is evidence about execution, not about
the class of work.

| Scope class | Route | Required evidence |
| --- | --- | --- |
| `exact_shipped_reuse` | `constrained_reuse_eligible` | Every visual and interaction decision maps to an exact shipped source component or pattern and an exact accepted token declaration at a named repository commit and content hash. Only transformations explicitly admitted by the constrained-reuse receipt are allowed. |
| `novel` | `live_handoff_required` | Any new component, geometry system, token, typography source, motion language, icon language, interaction class, or authority affordance requires the live gate. |
| `mixed` | `live_handoff_required` | A scope containing both exact reuse and any novel, unresolved, or out-of-envelope decision uses the live gate for the whole scope; do not let the reusable subset create a fallback for the rest. |
| `unknown` | `live_handoff_required` | Missing source identity, incomplete decision mapping, an unverified hash, or ambiguous transformation authority fails closed to the live gate. |

Only `exact_shipped_reuse` may enter the constrained-reuse route. A proposed extension is `novel`,
even when it begins from a shipped component. MCP unavailability does not reclassify novel, mixed,
or unknown work as exact reuse; the live-gate-required scope stays blocked.

### Constrained reuse gate

This route admits implementation guidance derived only from exact shipped Yggdrasil patterns. It
does not ask an external design model to generate or revise a visual. Before using it:

1. Prove the complete classifier mapping: every rendered component, layout decision, interaction,
   state treatment, accessibility behavior, and token declaration has a content-addressed shipped
   source. An unlisted decision makes the scope `mixed` or `unknown`.
2. Bind the exact repository commit; source paths and stable component/pattern references; hashes
   for every reused source; the binding token source and each reused declaration; and the complete
   allowed-transformation list.
3. Permit no new visual language. The allowed transformations may only adapt exact source behavior
   for the named target, including explicitly bounded layout reflow, content binding, interaction
   binding, or local-system-font/no-egress normalization. They may not introduce a new component,
   geometry system, token, typography source, motion language, icon language, interaction class, or
   authority affordance.
4. Cover every state required by the consuming contract and its stable fixtures. Cover desktop,
   narrow, 200% zoom, keyboard, screen-reader naming, print, and JavaScript-off behavior when those
   modes apply. State and accessibility evidence must preserve server-declared semantics.
5. Prove no egress: remove external font imports, bind their local-system-font normalization to the
   exact accepted token source and hash, observe zero cross-origin requests, and make no CSP
   relaxation.
6. Produce `yggdrasil-constrained-reuse.v1` exactly as owned by
   `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: yggdrasil-constrained-reuse.v1 receipt` and
   obtain an author-independent review whose passing verdict binds the receipt payload hash.

A missing or failed check is not partial success. Reclassify the scope through the table above or
stop. Any implementation or final visual delta outside the reviewed reuse envelope becomes
`mixed` or `novel` and must pass the live design-system gate before it proceeds.

`yggdrasil-constrained-reuse.v1` is not `yggdrasil-design-handoff.v1`; a copied token sheet is
repository provenance only and cannot satisfy a live handoff receipt. Never represent constrained
reuse as live MCP/system selection, live project creation, or live token parity.

### Live design-system gate

Complete this gate before asking a design model to produce or revise any `novel`, `mixed`, or
`unknown` visual scope:

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
invent a replacement token set, or continue with an unverified similarly named system. A copied
token sheet cannot prove live system selection or token parity and cannot satisfy a live handoff
receipt.

## Workflow

1. **Classify the artifact and work.** Keep exploration/handoff guidance separate from normalized
   specs, architecture authority, shipped components, and runtime truth. Apply the classifier above
   to the complete visual scope before choosing a route.
2. **Bound the request.** Name the operator journey, surface, states, authority limits, source
   evidence, responsive/accessible states, and requested deliverables.
3. **Run the selected gate.** For `exact_shipped_reuse`, complete the constrained-reuse gate without
   design generation. For `novel`, `mixed`, or `unknown`, complete the live design-system gate and
   preserve its receipt in the package README.
4. **Prepare evidence.** Attach current screenshots, relevant implementation surfaces, the exact
   token sheet, reusable components/previews, and the most local owner contracts. For constrained
   reuse, record content hashes and stable source references instead of relying on resemblance.
   Prefer targeted evidence over a repo-wide context dump.
5. **Generate, revise, or normalize exact reuse.** On the live route, make Yggdrasil a binding
   component and visual constraint, not a palette suggestion, and write revisions to a new
   versioned output folder. On the constrained route, do not generate a visual: normalize only the
   exact reviewed reuse envelope. Never overwrite an earlier accepted or reviewable design.
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

## Required receipts

For the live design-system route, return the following only after actually executing and passing
the live gate. Never draft it from copied repository assets or from tool-unavailability evidence:

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

For the constrained route, return the content-addressed
`yggdrasil-constrained-reuse.v1` receipt defined in
`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`. Its authority block must preserve the literal
`not_claimed` values for live selection, MCP system identity, project creation, and live parity; it
must never be relabeled as the live receipt above.
