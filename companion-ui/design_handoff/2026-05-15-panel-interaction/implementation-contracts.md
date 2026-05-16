State: Handoff package governance doc — implementation contracts derived from design intent. Not a runtime contract. Requires normalized spec before becoming authoritative.

# Implementation Contracts — Panel Interaction Design

**Package:** `companion-ui/design_handoff/2026-05-15-panel-interaction/`
**Crossing status:** A
**Authority:** Design intent only. These contracts become authoritative only after Crossing B and a normalized spec PR.

---

## Scope of this file

This file captures what the design governs and what it explicitly does not govern, the state enum and allowed transitions, proposed component inventory, and the proposed design intent vocabulary. Nothing here is a runtime contract; everything here is design-layer input to the normalized spec.

---

## What this design governs

- Visual states and allowed transitions for the Panel UI surface.
- Interaction gestures and their confirmation semantics (what confirm/discard/acknowledge mean in this surface).
- Vault Markdown ↔ Companion UI render correspondence (for each state, what Obsidian shows and what the UI renders).
- Component shapes and reuse/diverge decisions relative to the canvas suggestion flow.
- Provenance display depth: what proposal metadata is shown at a glance vs. on expand.

## What this design does not govern

- The action catalog or capability taxonomy — see `docs/CAPABILITY_CONTRACT_MODEL.md` and issue #981.
- Runtime event names or payload shapes — see `docs/EVENTS.md` and `docs/PANEL_AGENT.md`.
- Policy gates, write guards, or idempotency windows — runtime owns those.
- Whether a `proposals-written` event or a dedicated confirm API endpoint exists — design names these as dependencies; runtime confirms or rejects.
- The PA2-FREEFORM catalog lookup logic — see `docs/PANEL_AGENT.md §PA2-FREEFORM`.
- PanelAgent cognition mode selection (rule vs LLM) — see `docs/PANEL_AGENT.md §PanelAgent 2.0`.

---

## State enum (canonical names)

These names are proposed by the design. Canonical implementation names must be confirmed in the normalized spec.

| State | Description |
|---|---|
| `idle` | Panel fence present; no pending proposals; no active run |
| `running` | PanelAgent run in flight (triggered by watcher or explicit action) |
| `proposals-staged` | Unchecked proposals written into `AI-åtgärder`; awaiting confirmation |
| `confirming` | Human is actively reviewing proposals (one or more selected) |
| `executing` | Confirmed proposals submitted; execution in flight |
| `receipt-displayed` | Execution complete; AI status callout updated; receipts shown |
| `no-match` | PanelAgent ran; no catalog match found; instruction echoed with reason |
| `blocked` | Write guard or policy prevented execution; reason surfaced with recovery path |

Future states (not in scope for this design; named for extensibility):

| State | Description |
|---|---|
| `clarifying` | PanelAgent is requesting clarification before generating proposals |
| `plan-staged` | A multi-step plan is staged; human reviews steps before committing |
| `partial-complete` | Some proposals executed; others failed or were skipped |
| `capability-needed` | A proposed action requires a capability that is not currently available |

---

## Allowed state transitions

```
idle ──────────────────► running         (watcher tick or explicit run)
running ───────────────► proposals-staged (PanelAgent writes unchecked checkboxes)
running ───────────────► no-match        (PanelAgent: no catalog match)
running ───────────────► blocked         (write guard or policy gate prevents execution)
running ───────────────► idle            (cancel or no instruction present)
proposals-staged ──────► confirming      (human selects ≥1 proposal)
proposals-staged ──────► idle            (human discards all proposals)
confirming ────────────► executing       (human submits confirmation)
confirming ────────────► proposals-staged (human cancels confirmation step)
executing ─────────────► receipt-displayed (execution complete)
executing ─────────────► blocked         (write guard activates mid-execution)
receipt-displayed ─────► idle            (auto after brief receipt display, ~1.5s; or explicit dismiss)
no-match ──────────────► idle            (human acknowledges)
no-match ──────────────► running         (human edits instruction and re-runs)
blocked ───────────────► idle            (human acknowledges)
blocked ───────────────► running         (human resolves block reason and re-runs)
```

Forbidden transitions:
- `running` → `executing` (proposals must be confirmed before execution; no auto-execute)
- `proposals-staged` → `executing` (same; gated execution invariant)
- Any transition that bypasses explicit human confirmation for execution

---

## Vault Markdown ↔ Companion UI correspondence (design intent)

For each state, the two layers must remain coherent.

| State | Vault Markdown (Obsidian) | Companion UI render |
|---|---|---|
| `idle` | Panel fence with `AI-instruktion`; `AI-åtgärder` empty or has only prior receipts | Panel widget shows instruction; no pending proposals; run affordance available |
| `running` | No vault change yet | Running indicator (reuse ThinkingIndicator or new PanelRunningIndicator); action inputs disabled |
| `proposals-staged` | Unchecked checkboxes written into `AI-åtgärder` by PanelAgent | Proposal list with individual confirm/discard affordances; provenance badge on each row |
| `confirming` | No vault change yet | Selected proposals highlighted; submit/cancel affordances; composer/other actions disabled |
| `executing` | Checkboxes now checked (confirmed by Companion UI write-back); execution in flight | Executing indicator; confirmed proposals locked (not dismissible) |
| `receipt-displayed` | AI status callout updated; executed checkboxes removed from panel | Receipt strip showing `✅` entries; proposal list cleared |
| `no-match` | AI status callout: `⚠️ No match for: "<instruction snippet>"` | No-match state: instruction echoed, reason surfaced, next-step affordance (edit instruction / view catalog) |
| `blocked` | AI status callout: `⚠️ Blocked: <reason>` | Blocked state: reason displayed; recovery path (view details, acknowledge) |

---

## Component inventory (design intent)

### New components (Panel-specific)

| Component | Role | data-testid (proposed) |
|---|---|---|
| `PanelWidget` | Container that renders a single panel fence; root of the Panel surface in Companion UI | `panel-widget` |
| `ProposalRow` | A single unchecked proposal with confirm/discard affordances and a provenance badge | `panel-proposal-row` |
| `PanelNoMatchState` | State display when no catalog match was found; echoes instruction, shows reason, offers next step | `panel-no-match` |
| `PanelBlockedState` | State display when write guard or policy blocked execution; shows reason and recovery | `panel-blocked` |
| `PanelRunningIndicator` | Visual indicator for an in-flight PanelAgent run | `panel-running` |
| `PanelReceiptStrip` | Renders AI status callout entries in companion UI; `✅`/`⚠️`/`⏳` rows | `panel-receipt-strip` |

### Reuse candidates from canvas suggestion flow

| Canvas component | Proposed reuse decision | Notes |
|---|---|---|
| `ThinkingIndicator` | **Reuse or extend** — running/executing indicator semantics are similar | Confirm during normalized spec |
| `ReceiptPill` / `ReceiptsStrip` | **Likely diverge** — Panel receipts are AI status callout entries, not governance route receipts | Confirm during normalized spec |
| `SuggestionCard` | **Diverge** — Panel proposals are proposal rows inside a widget, not top-level card in rail | Panel context and vault/UI correspondence are different |
| `ProvenanceBadge` (if extracted) | **Reuse** — catalog action ID + cognition mode badge applies to both surfaces | Confirm if extractable |

Design principle: extend the canvas suggestion flow vocabulary; do not fork. Name divergences explicitly rather than silently.

---

## Proposed design intent vocabulary

These are design-layer intent tokens proposed for the Panel surface. They are **not runtime contracts**. Normalized spec must confirm which become `data-intent` tokens and which map to API calls.

| Intent token | Triggered by | Description |
|---|---|---|
| `panel.proposal.confirm` | Confirm button / keyboard shortcut | Confirm selected proposal(s); route through runtime for vault write-back |
| `panel.proposal.discard` | Discard button / keyboard shortcut | Discard a proposal without writing to vault |
| `panel.run.request` | Explicit run affordance | Request a new PanelAgent run on the active note |
| `panel.run.cancel` | Cancel button during `running` | Cancel an in-flight run |
| `panel.nomatch.acknowledge` | Acknowledge button in `no-match` state | Dismiss no-match state; return to `idle` |
| `panel.nomatch.editInstruction` | Edit link in `no-match` state | Return focus to `AI-instruktion` for editing |
| `panel.blocked.acknowledge` | Acknowledge button in `blocked` state | Dismiss blocked state; return to `idle` |
| `panel.blocked.openDetails` | Details link in `blocked` state | Show full block reason and recovery path |

Keyboard shortcut candidates (proposed; confirm against canvas flow conventions):
- `C` — confirm selected proposal (scoped to `confirming` state)
- `D` — discard focused proposal (scoped to `proposals-staged` / `confirming` states)
- `A` — acknowledge (scoped to `no-match` / `blocked` states)

---

## Data attributes (design intent)

| Attribute | Element | Values |
|---|---|---|
| `data-panel-state` | `PanelWidget` root | `idle`, `running`, `proposals-staged`, `confirming`, `executing`, `receipt-displayed`, `no-match`, `blocked` |
| `data-proposal-id` | `ProposalRow` | Catalog action ID (e.g., `promote.evergreen`) |
| `data-cognition-mode` | `ProposalRow` provenance badge | `rule`, `llm` |
| `data-receipt-status` | `PanelReceiptStrip` row | `executed`, `warning`, `pending` |

---

## Runtime dependencies named by this design

The following items are design **dependencies** that must be confirmed or resolved by the runtime before a Companion UI implementation is possible. They are not assumed; they are named so the normalized spec can address them explicitly.

1. **Proposals-written signal:** Does the runtime emit a distinguishable event or API response when proposals are written back to `AI-åtgärder` (vs. execution complete)? The Companion UI needs this to transition from `running` to `proposals-staged` rather than polling the vault.

2. **Confirmation write-back contract:** When a human confirms a proposal in Companion UI, what is the exact write-back sequence? Options: (a) check the vault checkbox and trigger a re-run; (b) route through a dedicated confirm API endpoint that marks the proposal confirmed and triggers execution. Design preference: option (b) — a dedicated endpoint — but this must be confirmed by runtime. See `open-questions.md` Q2.

3. **Run-state detection:** How does Companion UI know a watcher-triggered panel run has started and completed? Options: polling `/api/status`, an event subscription, or a panel-state endpoint. Design preference: short-poll on active-note panel state while Panel widget is visible. See `open-questions.md` Q3.

4. **Cognition mode in response:** The runtime must include `cognition_mode` (`rule` / `llm`) in the proposals payload so the Companion UI can display the provenance badge. This is already in `panel.intent.executed` per `docs/PANEL_AGENT.md §PanelAgent 2.0` — confirm the payload path during normalized spec.
