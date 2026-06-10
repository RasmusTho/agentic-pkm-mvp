# Design Handoff Archive

Preserved Claude Design artifacts and handoff packages. These are reference/handoff inputs, not production code.

**Governance:** All packages follow the governed handoff chain defined in [`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`](../docs/DESIGN_HANDOFF_GOVERNANCE.md). Before any design exploration becomes implementation work, it must pass through that chain (exploration → handoff → normalized spec → issue → PR → validation receipt).

**Term mapping:** When converting design language into architecture or implementation language, use [`companion-ui/docs/CORE_TERM_MAPPING.md`](../docs/CORE_TERM_MAPPING.md).

## Current packages

| Package | Date | Crossing | Related issue(s) | Notes |
|---|---|---|---|---|
| `2026-05-03-converse/` | 2026-05-03 | A (pre-governance) | — | Converse surface wireframes and spec assets. |
| `2026-05-08-cognitive-temporal/` | 2026-05-08 | A (pre-governance) | — | Cognitive modes, temporal cognition, re-entry mist variants. |
| `2026-05-11-canvas-suggestion-flow/` | 2026-05-11 | B+ | #868–#874 | Canvas Suggestion Flow: body-edit lane, governance-bearing lane, 8-state UI model, component inventory. Normalized spec: `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`. |
| `2026-05-14-claude-design-package/` | 2026-05-14 | A (index) | #901 + others | Executive summary index for the 2026-05-14 design session. Five packages + implementation intake table. |
| `2026-05-14-handoff-governance-pack/` | 2026-05-14 | B | **#901** | Meta-process: the six-link handoff chain, maturity checklist, review console prototype, templates. Normalized spec: `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`. |
| `2026-05-14-runtime-proof-dashboard/` | 2026-05-14 | A | #865, #866, #850 | Compact single-operator proof surface. Design only — not yet a normalized spec. |
| `2026-05-14-context-bundle-inspector/` | 2026-05-14 | A | #894, #895, #896 | Inspectable context-bundle bridge object. Design only. |
| `2026-05-14-memory-candidate-review/` | 2026-05-14 | A | #900 | Pull-based memory candidate review queue. Design only. |
| `2026-05-14-vault-action-layer/` | 2026-05-14 | A | #910 | 9-step vault action pipeline, 5-tier tool taxonomy. Design only. |
| `2026-05-15-panel-interaction/` | 2026-05-15 | A (accepted as design intent — #994) | #977, #978, #981, #994 | Panel interaction surface: vault-native AI fence + Companion UI render layer. State machine (8 states), component inventory, authority boundaries, open questions. Accepted as design-intent input per `ACCEPTANCE.md`; AI fence reaffirmed as communication envelope, `companion:panel:run` HTML-comment blocks classified as proposed/internal projection only. Interactive prototype (prototype.html) pending. |
| `2026-05-24-vault-browser-foundation/` | 2026-05-24 | A | #1259, #1260, #1261, #1253–#1257 | Vault Browser Foundation: 20-section design handoff covering executive summary, workspace shell critique (C1–C7), design principles, information architecture, main layout, browsing modes, metadata filters, artifact list/inspector, action display model, receipts/review posture, degraded states, responsive behavior, `data-*` test attributes, MLP-vs-future capability table, future feature map, design risks, and a 16-slice (A–P) post-#1253–#1257 implementation grid. Landed for #1259 as non-authoritative design input; converted from Claude Design HTML to Markdown. Names workspace-shell alignment (#1260) as the prerequisite before deeper browser UI work. |
| `2026-06-09-system-entry-point/` | 2026-06-09 | **B (PROMOTE — normalized spec authoring unblocked)** | — | System Entry Point: the companion's front door — entry-point state machine (boot / no_vault / cold_start / orienting / shell_active), unified shell (document anchor + overlay layer + Chat rail + Panel command surface), and a system map composing all existing surfaces. Includes settings/read-back/capture/receipts surfaces; context lane (time+place) ships as explicit placeholder gated on Q15–Q16. |

**Crossing A** = archived, not yet through maturity checklist.
**Crossing B** = maturity checklist passed; normalized spec exists in `companion-ui/docs/`.
**Pre-governance** = archived before this governance doc existed; exempt from retroactive checklist.

## Rules

- Design artifacts in this folder are guidance only. They are not architecture authority and not runtime truth.
- Do not implement production UI components directly from a handoff package. Route through the governed chain.
- Do not let a design package modify or override an owner-doc in `docs/**`.
- Implementation issues #868–#874 (canvas suggestion flow) and others remain their own task contracts. This folder does not absorb them.
