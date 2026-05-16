State: Handoff package — Crossing A. Design brief archived; interactive prototype (index.html) pending Claude Design session output.

# Panel Interaction Design Handoff — 2026-05-15

**Design surface:** Panel interaction surface — vault-native AI panel fence + Companion UI render layer
**Design date:** 2026-05-15
**Authority status:** Visual guidance and design intent only — not architecture authority, not runtime truth.
**Crossing status:** A — archived, maturity checklist not yet passed.
**Governing chain:** `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`

---

## What this package is

This package archives the design exploration for the **Panel interaction surface**: the human-to-agent channel built into vault notes using AI fences, and how the Companion UI should render it more richly alongside the vault-native Markdown layer.

The design problem is explicitly layered:

- **Vault-native layer** — the AI fence syntax (`%% AI:Start %%` / `%% AI:End %%`), heading structure (`## AI-instruktion`, `## AI-åtgärder`, `## AI-logg`), and AI status callout are the data contract. They remain readable and functional in Obsidian with or without Companion UI running. **This layer is not being redesigned.**
- **Companion UI layer** — renders the same panel content more richly; presents proposals with explicit confirmation affordances; shows receipts in structured form. Writes back to the vault through the runtime API.
- **The relationship** — both layers must stay coherent. A proposal confirmed in Companion UI must produce the same vault artifact as a checkbox checked in Obsidian. The vault is source of truth; the Companion UI is the richer interaction render.

---

## Package contents

| File | Role |
|---|---|
| `BRIEF.md` | Design session input brief — constraints, state machine spec, component inventory, open questions, non-goals |
| `index.html` | Interactive prototype — Claude Design session output (**pending; not yet created**) |
| `README.md` | This file — authority status and crossing target |
| `implementation-contracts.md` | State enum, allowed transitions, data attributes, component inventory, design intent vocabulary |
| `authority-boundaries.md` | What this design is and is not; invariants this package must honor |
| `open-questions.md` | Unresolved questions triaged into crossing-blocking / normalized-spec / deferred |
| `state-gallery.md` | State-by-state descriptions for all declared Panel UI states |

---

## Authority status

Design artifacts in this package are **guidance and input only**. They are not:

- **Architecture authority.** Architecture authority lives in `docs/**` owner docs — specifically `docs/PANEL_AGENT.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY.md`, `docs/CAPABILITY_CONTRACT_MODEL.md`, and `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`.
- **Runtime truth.** Runtime truth lives in shipped code, tests, `docs/STATUS.md`, and validation receipts.
- **A schema declaration.** This design references fields and event names; it does not declare them.
- **A claim about current behavior.** Unless a passage explicitly cites a shipped owner doc, treat it as target-state design intent.

**The vault-native AI panel syntax is the ground truth this design renders from.** It is not being replaced or extended by this design.

---

## Crossing target

This package targets **Crossing A → B**. Crossing B requires all of the following:

- [x] README names the surface and declares authority status (this file)
- [x] `authority-boundaries.md` present and distinguishes design / normalized-spec / architecture / runtime-truth layers
- [x] `implementation-contracts.md` present with state enum, transitions, and data attributes
- [x] `open-questions.md` present; all questions triaged into resolve-before-promotion / resolve-in-normalized-spec / defer
- [ ] No crossing-B-blocking open questions remain unresolved — **pending human review of `open-questions.md`**
- [x] State gallery covers all declared states
- [x] Package does not assert current runtime behavior beyond shipped owner docs

**Crossing B is not yet passed.** The open questions in `open-questions.md` must be reviewed by a human, and no blocking ones may remain unresolved before Crossing B can be signed off.

---

## Related issues

- **#977** — Decision: should PanelAgent generate proposed AI actions from `AI-instruktion` or only execute existing checkbox actions?
- **#978** — Task: align PanelAgent cognitive mediation with existing human-first architecture (parent hub)
- **#981** — Task: define capability taxonomy for cognitive mediation (`agent:ready`)

---

## Next steps

1. Complete the Claude Design session using `BRIEF.md` as the input brief; export the output HTML as `index.html` in this folder.
2. Human reviews `open-questions.md`; confirms triage and resolves any blocking questions.
3. Route to Crossing B when the maturity checklist is satisfied.
4. After Crossing B: author a normalized spec in `companion-ui/docs/PANEL_INTERACTION_SPEC.md`.
5. Create bounded GitHub issues from the normalized spec via the `docs-to-issue` skill.

---

## References

- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md` — governing handoff chain
- `companion-ui/docs/OVERLAY_GRAMMAR.md` — overlay structural rules
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — UI/runtime separation rules
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — normalized spec for the canvas suggestion surface (design reference quality bar)
- `companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/` — canvas suggestion flow design (vocabulary reference)
- `docs/PANEL_AGENT.md` — shipped runtime contract for the Panel surface (v5.6)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY.md` — Panel authority boundary spec
