# Canvas Suggestion Flow — Normalized Implementation Spec

**Design source:** `companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/`
**Staging prototype:** `companion-ui/companion-app/canvas_suggestion_flow.html`
**Governing issue:** #876
**Implementation issues:** #868 (SuggestionCard), #869 (SuggestedInsertion), #870 (state machine), #871 (ReceiptPill/ReceiptsStrip), #872 (keyboard shortcuts), #873 (portrait bottom sheet), #874 (ProvenanceFooter)

---

## Purpose and scope

The Canvas Suggestion Flow is the interaction pattern for the moment Hugin proposes a change to the active note:

1. A proposal arrives from the server with a pre-declared classification (body-edit or governance-bearing).
2. The user previews the proposal and decides to apply, queue, or discard it.
3. The system either co-authors the note body in place or routes the intent through the governed pipeline.

Scope boundary: this spec covers the UI state machine, component contracts, intent vocabulary, and wiring to backend concepts. It does not prescribe the editor library, the streaming protocol, or the session-log retention window.

---

## Surface boundaries

The Canvas Suggestion Flow operates within the companion UI overlay surface (margin rail, portrait bottom sheet). It augments the active document — the document pane remains the primary cognitive anchor.

- **Design reference:** `companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/` — 14-section Claude Design handoff. Use for visual intent, rationale, and edge-case notes. Not an implementation contract by itself.
- **Staging prototype:** `companion-ui/companion-app/canvas_suggestion_flow.html` — interactive browser demo, no network side effects, no durable mutations. Explicitly non-production.
- **Implementation contract:** this file (`CANVAS_SUGGESTION_FLOW.md`) — the normalized spec that implementation issues reference.

---

## Hard invariants

These invariants must be present in implementation and must not be violated:

1. **Server-declared classification.** The UI renders the proposal type (body vs governance) from the server-returned payload. The UI never re-classifies. Classification logic lives in the backend.
2. **No Apply action on governance-bearing proposals.** The governance `SuggestionCard` variant must not render an Apply button under any condition. The only actions are Queue and Discard.
3. **Body-edit Apply does not create a Panel governance receipt.** Applying a body edit routes through `canvas_writer.apply_edit`, not through `GovernanceRouter`. No Panel receipt is generated.
4. **Body-edit Apply creates a session-log provenance entry.** Every body edit apply must produce a `body_edit_applied` turn in the session log.
5. **Governance proposals are queued, not executed directly.** Queue routes through `GovernanceRouter.request_governance_action` and returns a receipt/status. The receipt is surfaced as a `ReceiptPill`.
6. **Session log path from backend, not hardcoded.** `ProvenanceFooter` displays the session log path from backend-returned session data. Hardcoded paths are prototype-only.
7. **Canvas/Chat must not become a second source of truth.** Session logs are provenance (intent trail), not the primary artifact. The note is the artifact.

---

## UI state model

### Canonical state names (snake_case — use these in docs and contracts)

| Canonical name | Description |
|---|---|
| `idle` | No active proposal; composer enabled |
| `thinking` | Agent is processing; composer disabled |
| `staged_body` | Body-edit proposal staged; Apply/Discard available |
| `staged_governance` | Governance-bearing proposal staged; Queue/Discard available |
| `apply_pending` | Body edit being written via `canvas_writer` |
| `governance_pending` | Governance action being routed via `GovernanceRouter` |
| `applied` | Body edit confirmed; transitions to `idle` |
| `discarded` | Proposal discarded; transitions to `idle` |
| `blocked` | `CANVAS_ENABLED=0`; proposal blocked; Acknowledge available |

### Prototype DOM state name mapping

The prototype stores state in `data-suggestion-state` on `[data-testid="canvas-shell"]`. The DOM attribute uses CSS-friendly names that differ from canonical contract names. Implementations must use canonical names internally; DOM names are an acceptable rendering alias.

| Canonical (contract) | Prototype DOM (`data-suggestion-state`) | Prototype internal JS |
|---|---|---|
| `idle` | `idle` | `idle` |
| `thinking` | `thinking` | `thinking` |
| `staged_body` | `staged-body` | `suggestion-staged:body` |
| `staged_governance` | `staged-gov` | `suggestion-staged:gov` |
| `apply_pending` | `pending-apply` | `apply-pending` |
| `governance_pending` | `pending-gov` | `governance-pending` |
| `applied` | `applied` | `applied` |
| `discarded` | `discarded` | `discarded` |
| `blocked` | `blocked` | `blocked` |

---

## Allowed state transitions

```
idle ──────────────► thinking
thinking ──────────► staged_body
thinking ──────────► staged_governance
thinking ──────────► blocked
thinking ──────────► idle (cancel)
staged_body ───────► apply_pending (Apply)
staged_body ───────► discarded (Discard)
staged_governance ─► governance_pending (Queue)
staged_governance ─► discarded (Discard)
apply_pending ─────► applied (canvas_writer confirms)
governance_pending ► idle (receipt returned)
applied ───────────► idle (auto, ~1.4s)
discarded ─────────► idle (auto, ~1.4s)
blocked ───────────► idle (Acknowledge)
```

Forbidden: no transition may skip `apply_pending` or `governance_pending` to jump directly from `staged_*` to `applied`/`idle`.

---

## Body-edit lane

1. Server sends a proposal classified as `body` with insertion anchor, preview text, and `suggestion_id`.
2. State transitions: `idle` → `thinking` → `staged_body`.
3. `SuggestionCard` (body variant) renders in the rail; `SuggestedInsertion` renders in the document pane at the insertion anchor.
4. User presses Apply (or keyboard `A`): state → `apply_pending`. `canvas_writer.apply_edit` is called. Composer disabled.
5. On confirm: `SuggestedInsertion` flips to `applied` appearance. Session log receives `body_edit_applied` turn. State → `applied` → `idle`.
6. `ProvenanceFooter` Undo button becomes active after apply; pressing Undo calls `canvas.undoLastEdit` and restores `staged_body`.
7. No Panel receipt is generated. No governance routing.

---

## Governance-bearing lane

1. Server sends a proposal classified as `governance` (frontmatter, maturity, cross-note, lifecycle op) with `action_type`, payload, and `suggestion_id`.
2. State transitions: `idle` → `thinking` → `staged_governance`.
3. `SuggestionCard` (governance variant) renders with classification label "Cannot be applied from chat — must be queued." **No Apply button.**
4. User presses Queue (or keyboard `Q`): state → `governance_pending`. `GovernanceRouter.request_governance_action` is called.
5. On receipt return: a `ReceiptPill` appears in the thread and in `ReceiptsStrip`. Session log receives `governance_intent_queued` turn. State → `idle`.
6. `SuggestedInsertion` does not render for governance proposals (no in-document preview for governance mutations).

---

## Component inventory

| Component | Variants | data-testid | Description |
|---|---|---|---|
| `SuggestionCard` | `body`, `governance`, `blocked` | `suggestion-card` | Proposal card in the rail thread |
| `SuggestedInsertion` | `staged`, `applied`, `discarded` | `suggested-insertion-block` | In-document inline preview marker |
| `ReceiptPill` | `queued`, (future: `approved`, `rejected`) | `receipt-pill` | Governance receipt pill in thread and strip |
| `ReceiptsStrip` | — | `receipts-strip` | Strip of pending governance receipts above composer |
| `ProvenanceFooter` | — | `provenance-footer` | Session log path, turn count, undo intent |
| `ThinkingIndicator` | `active`, `inactive` | `thinking-indicator` | Animated dots shown during `thinking` and `apply_pending` |
| `ComposerInput` | — | `composer-input` | Text input; disabled outside `idle` |

---

## data-intent vocabulary

| Intent token | Triggered by | Description |
|---|---|---|
| `suggestion.apply` | Apply button / keyboard `A` | Apply body edit via `canvas_writer` |
| `suggestion.discard` | Discard button / keyboard `D` | Discard proposal without writing |
| `suggestion.inspect` | Inspect button / keyboard `I` | Expand diff or classification rationale (UI-only) |
| `suggestion.edit` | keyboard `E` | Inline edit before apply (UI-only) |
| `governance.queue` | Queue button / keyboard `Q` | Route governance intent via `GovernanceRouter` |
| `governance.openReceipt` | ReceiptPill click | Open governance receipt in Panel |
| `blocked.acknowledge` | Acknowledge button | Log `governance_intent_blocked` and return to idle |
| `blocked.openPanel` | Open in Panel button | Route blocked intent to Panel surface |
| `canvas.cancelTurn` | Cancel button in ThinkingIndicator | Cancel in-flight agent turn |
| `canvas.undoLastEdit` | Undo button in ProvenanceFooter | Undo last applied body edit |
| `provenance.openSessionLog` | Session path link in ProvenanceFooter | Open session log in vault |
| `composer.send` | Send button | Send composer message (idle only) |
| `session-drawer.open` | Session pill in top bar | Open session drawer |

---

## data-testid vocabulary

| data-testid | Element | Notes |
|---|---|---|
| `canvas-shell` | Root container | Carries `data-suggestion-state` (DOM name) |
| `document-pane` | Active note render area | |
| `margin-rail` | Hugin conversation rail | |
| `conversation-thread` | Thread scroll container | |
| `suggestion-card` | SuggestionCard | Carries `data-variant` |
| `suggestion-card-classification` | Classification label (governance variant) | |
| `suggested-insertion-block` | In-document inline preview | Carries `data-state` |
| `apply-suggestion` | Apply button (body variant) | |
| `discard-suggestion` | Discard button (body or governance variant) | |
| `queue-governance` | Queue button (governance variant) | |
| `receipt-pill` | ReceiptPill | Carries `data-receipt-id`, `data-status` |
| `receipts-strip` | ReceiptsStrip | |
| `thinking-indicator` | ThinkingIndicator | |
| `composer-input` | ComposerInput | |
| `provenance-footer` | ProvenanceFooter | |
| `undo-last-edit` | Undo button in ProvenanceFooter | |
| `session-pill` | Session drawer opener in top bar | |

---

## Backend and API concept mapping

| UI concept | Backend concept | Notes |
|---|---|---|
| Body-edit apply | `canvas_writer.apply_edit` | Writes to active note body; no governance receipt |
| Governance queue | `GovernanceRouter.request_governance_action` | Returns `receipt_id` and status |
| Session log append | `session_log.append_turn` | Turn kinds below |
| Session log path | Returned from session context | Never hardcoded in production UI |
| Canvas enabled check | `CANVAS_ENABLED` flag | Flag is server-side; UI renders `blocked` variant when server signals disabled |

### Session log turn kinds

| Kind | When |
|---|---|
| `body_edit_applied` | Body edit confirmed by `canvas_writer` |
| `body_edit_discarded` | Body proposal discarded |
| `body_edit_undone` | Undo of a previously applied body edit |
| `governance_intent_queued` | Governance proposal queued via `GovernanceRouter` |
| `governance_intent_discarded` | Governance proposal discarded |
| `governance_intent_blocked` | Governance intent blocked by `CANVAS_ENABLED=0` |

---

## Receipt and provenance behavior

- Governance proposals produce a `ReceiptPill` with `data-receipt-id` and `data-status="queued"` on routing.
- `ReceiptPill` appears inline in the thread and is cloned into `ReceiptsStrip`.
- `ReceiptsStrip` is visible whenever one or more governance receipts are pending.
- Body-edit proposals do not produce receipts. The provenance record is the session-log `body_edit_applied` turn.
- `ProvenanceFooter` displays: session log path (from backend), turn count, undo button, and current state label.
- In the staging prototype, the session log path (`.chats/q2-arch/2026-05-11T1442.md`) is hardcoded for demo purposes. In real implementation, it must come from the server-returned session context.

---

## Responsive behavior

| Viewport | Rail shape | Transition trigger |
|---|---|---|
| ≥900px (landscape) | Side margin rail | Static; no sheet behavior |
| <900px (portrait) | Bottom sheet | Auto-snap to `half` when a proposal is staged |

### Portrait bottom-sheet snap points

| Name | Height |
|---|---|
| `peek` | ~72px — visible tip only |
| `half` | ~50% viewport — proposal readable |
| `full` | ~90% viewport — **never auto-snap to full; document must remain visible** |

Auto-snap to `full` is forbidden. The document must remain partly visible at the insertion point during staging.

---

## Accessibility requirements

- Keyboard shortcuts `A` (apply), `Q` (queue), `D` (discard), `I` (inspect), `E` (edit) are active **only** when `data-suggestion-state` is `staged-body` or `staged-gov`.
- Shortcuts must not fire when focus is inside `ComposerInput` or any `<input>`/`<textarea>`.
- Buttons with keyboard shortcuts carry `aria-keyshortcuts` attribute.
- `ComposerInput` is `disabled` (not hidden) outside `idle` to preserve focus management and indicate unavailability.
- `ReceiptsStrip` and `conversation-thread` carry `aria-live="polite"`.
- Blocked `SuggestionCard` variant carries `role="alert"`.
- All major interactive regions carry `aria-label`.

---

## Implementation-contract vs design-reference split

Items below are **contracts** — implementations must satisfy them exactly:

- State enum and canonical names (9 states as listed).
- Two-lane split: `body` vs `governance`; UI never re-classifies.
- No Apply button on governance-bearing `SuggestionCard`.
- Apply ≠ governance receipt: body-edit applies do not generate Panel governance receipts.
- `ComposerInput` disabled outside `idle`.
- Session-log provenance turn on every body-edit apply.
- Keyboard shortcuts `A/Q/D/I/E` scoped to `staged_*` states only.
- Portrait bottom-sheet: 3 snap points; auto-snap `half` on proposal; never auto-full.

Items below are **design guidance** — rationale and visual intent from the handoff, not hard contracts:

- Exact color tokens, spacing, and typography (see `companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/colors_and_type.css`).
- Specific animation durations (current prototype uses 900ms apply, 700ms governance pending).
- Exact copy strings in card labels and classification notices.
- The lane-switcher tab bar (present in prototype for demo; absent in production).

---

## Open questions and deferred items

- **Panel receipt shape for governance mutations:** what fields does the `ReceiptPill` carry when the Panel pipeline returns a decision? Deferred to the canvas-commit capability lane.
- **`CANVAS_ENABLED` propagation:** when and how the server signals the `blocked` condition to the UI. Likely via session context payload; contract not yet specified.
- **Undo scope:** whether undo restores only the last body edit or a full stack. Prototype supports single-step undo; multi-step undo deferred.
- **Retention window for session logs:** duration and soft-deletion policy not yet named. Deferred to the retention-policy lane.
- **Workspace mode (multi-note):** cross-note synthesis sessions. Out of scope for this flow; inherits the same governance-bearing classification when it ships.
- **Conflict resolution:** what happens if another session applies an edit to the same anchor while a proposal is staged. No protocol defined yet.

---

## Related docs

- `companion-ui/docs/OVERLAY_GRAMMAR.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`
- `companion-ui/docs/INTERACTION_PRINCIPLES.md`
- `docs/CANVAS_CHAT_SURFACE/` — backend contract for the canvas-Chat runtime
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` — co-authoring vs governance-bearing authority split
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` — gated-execution invariant
