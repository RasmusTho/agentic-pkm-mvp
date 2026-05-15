# Design Brief — Panel Interaction Surface

**Date:** 2026-05-15
**Scope:** Layered system — vault-native data contract + companion UI render layer
**Session target:** Claude Design at claude.ai/design
**Governing handoff chain:** `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`

---

## System frame

One user: a senior software architect. Vault-first (Obsidian + Markdown). The system is a
cognitive prosthesis — it supports cognitive functions a human cannot reliably do unaided
without taking authorship away. This is not a productivity product; it is a thinking
environment.

The vault is the canonical truth surface. All durable artifacts live as Markdown files with
frontmatter, readable in Obsidian with or without the companion UI running. The companion UI
is a client of the FastAPI runtime; it does not own vault I/O directly. Multi-device: iPhone,
iPad, Mac — desktop primary, mobile a thinner subset.

The companion UI's job is to render vault artifacts more richly and support cognitive acts
that are awkward in Obsidian's document-centric surface — not to replace it.

---

## What this brief is about

The **Panel interaction surface**: the human-to-agent channel built into vault notes using AI
fences. Currently, this interaction lives entirely in Obsidian Markdown. The companion UI has
no Panel surface at all.

This is a **layered design problem**:

- **Vault-native layer** — the panel fences, heading syntax, and AI status callout are the
  data contract. They remain readable and functional in Obsidian with or without the companion
  UI running. This layer is not being redesigned; it is the ground truth the companion UI
  renders from.
- **Companion UI layer** — renders the same panel content more richly, presents proposals with
  explicit confirmation affordances, shows receipts in a structured way. Writes back to the
  vault through the runtime API.
- **The relationship** — both layers must stay coherent. A proposal confirmed in the companion
  UI must produce the same vault artifact as a checkbox checked in Obsidian. The vault is
  source of truth; the companion UI is the richer interaction render.

**Design the relationship** — for every state, show what the vault Markdown looks like and
what the companion UI renders. That correspondence is the core deliverable.

---

## What currently exists (the vault-native contract)

Panel syntax — this is the data contract. Design renders from it; does not replace it.

```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder
- [ ] Proposed action 1
- [ ] Proposed action 2

## AI-logg
%% AI:End %%

> [!info]- AI status
> - ✅ Re-classify as Concept (2026-05-14 10:00)
> - ⚠️ No match for: "rephrase intro paragraph"
> - ⏳ Pending: summarize-for-review
```

- **`AI-instruktion`** — freeform human instruction to PanelAgent.
- **`AI-åtgärder`** — checkbox list. Unchecked = proposed by PanelAgent (awaiting confirmation).
  Checked = human-confirmed, will execute on next run. Executed items are removed from the
  panel by the runtime after execution.
- **`AI-logg`** — structured append-only log (optional section).
- **AI status callout** — receipt overlay outside the fence. `✅` executed, `⚠️` no-match or
  warning, `⏳` pending. Trimmed to last 20 entries by runtime.

**The freeform proposal path (shipped, PA2-FREEFORM):** when `AI-instruktion` has an
instruction and `AI-åtgärder` is empty, PanelAgent consults the action catalog and writes
proposed unchecked checkboxes back into `AI-åtgärder`. Those proposals do not execute; they
wait for the human to check them (in Obsidian) or confirm them (in companion UI). This is the
primary path this design must serve.

---

## Production anchor — the design problem

Prod UAT on 2026-05-15 exposed the failure mode this design must answer. A freeform
`AI-instruktion` with empty `AI-åtgärder` produced these runtime events:

```json
{
  "event": "panel.intent.created",
  "payload": {
    "panel": { "instruction": "Diagnose this note and propose safe next actions." },
    "actions": []
  }
}
```

```json
{
  "event": "panel.intent.executed",
  "actions": [],
  "executed_action_ids": [],
  "summary": "panel.intent.executed | no actions affected"
}
```

The vault note showed nothing. No proposals appeared. No receipt in the AI status callout.
The operator could not tell whether the run failed, whether no catalog match was found, or
whether proposals were forthcoming.

The vault-native panel can hint at states via the AI status callout, but cannot render
interaction affordances. The companion UI layer is the designed response: it must make the
difference between `no-match`, `proposals-staged`, `running`, and `receipt-ready` legible and
actionable — states the AI status callout can record but cannot present interactively.

**The `no-match` state is the most important fixture to design.**

---

## Hard constraints

1. **Gated execution invariant.** Proposals ≠ execution. Unchecked checkboxes do not execute.
   The companion UI may not add an "accept all" affordance that bypasses individual
   confirmation. No same-turn auto-execution of generated proposals.

2. **Vault is source of truth.** Companion UI writes proposals back to the vault via the
   runtime API. The vault Markdown is the canonical artifact, not the UI state. If the
   companion UI is closed, the note must show the correct proposal state in Obsidian.

3. **Confirmation is explicit, named, and reversible.** The human's confirmation step must be
   a visible, named action — not a swipe, not a background operation, not inferred from
   focus. It must be undoable before execution begins.

4. **Provenance visible at confirmation time.** Every proposal must show its origin — catalog
   action ID and cognition mode (rule vs LLM) — at the moment of confirmation, not only in
   the audit log. Source: `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`.

5. **Overlays augment; document remains the cognitive anchor.** The Panel surface in companion
   UI is rendered in relation to the active note, not as a standalone inbox. Source:
   `companion-ui/docs/OVERLAY_GRAMMAR.md`.

6. **`no-match` is a first-class state, not silence.** When PanelAgent ran and found no
   catalog match, the companion UI must render a distinct, legible state. The human must be
   able to read what happened and what to do next.

7. **Match the canvas suggestion flow design language.** Same Yggdrasil design tokens. Same
   interaction vocabulary (A/Q/D keyboard gesture family, staged proposal card, governance
   badge, receipt pill) where applicable. Extend; do not fork. Name any divergences
   explicitly.

---

## Design reference

**Primary reference — quality bar and interaction language:**
`companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/Canvas Suggestion Flow.html`

This is the design to match in quality and extend in vocabulary. It defines: proposal card
anatomy, staged states, A/Q/D keyboard shortcuts, governance-bearing vs body-edit lane split,
bottom sheet portrait behavior, receipt pill format. Reuse components where the interaction
semantics are the same; name new components when the panel moment differs from the canvas
chat moment.

**Design tokens:**
`companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/colors_and_type.css`
(same tokens as `companion-ui/design_handoff/2026-05-14-claude-design-package/colors_and_type.css`)

---

## What the design should produce

### 1. State machine

Enumerate Panel surface states for **both layers** — vault Markdown shape + companion UI
render — in a single state table. Minimum states:

| State | Vault Markdown | Companion UI |
|---|---|---|
| `idle` | Panel fence exists; `AI-åtgärder` empty or has prior receipts only | Panel widget shows instruction; no pending proposals |
| `running` | No change yet | Running indicator; composer disabled |
| `proposals-staged` | Unchecked checkboxes written into `AI-åtgärder` | Proposal list with confirmation affordances |
| `confirming` | No vault change yet | Human is reviewing/selecting proposals |
| `executing` | Checkboxes checked; execution in flight | Executing indicator; confirmed items locked |
| `receipt-displayed` | AI status callout updated; executed checkboxes removed | Receipt strip; proposal list cleared |
| `no-match` | AI status callout: `⚠️ No match for: "..."` | No-match state: instruction echoed, reason surfaced, next-step affordance |
| `blocked` | AI status callout: `⚠️ Blocked: write guard active` | Blocked state: reason shown, action available |

Add states as needed. Show allowed transitions.

### 2. Vault/UI mapping

For the four most important states (`proposals-staged`, `receipt-displayed`, `no-match`,
`blocked`): show a side-by-side — the Markdown as it appears in Obsidian, and the companion
UI component rendering the same artifact. This is the core deliverable; it proves the
relationship is coherent.

### 3. Component inventory

List new components vs canvas-flow reuse:

- **Panel widget** — the companion UI surface that renders a panel fence. New or extends
  canvas rail?
- **Proposal row** — unchecked proposal with provenance badge (catalog ID + cognition mode).
  Same as canvas SuggestionCard or divergent?
- **No-match state** — new. Needs design. Must show: instruction echoed, reason, next-step.
- **Panel receipt strip** — AI status callout rendered in companion UI. Same as canvas
  ReceiptPill/ReceiptsStrip or divergent?
- **Running indicator** — same as canvas `thinking` state or new?

### 4. Implementation contracts

Separate design authority from architecture authority.

**This design governs:**
- Visual states and allowed transitions
- Interaction gestures and their confirmation semantics
- Vault Markdown ↔ companion UI render correspondence
- Component shapes and reuse/diverge decisions vs canvas flow

**This design does not govern:**
- The action catalog or capability taxonomy (architecture owns those)
- Runtime event names or payload shapes
- Policy gates, write guards, idempotency windows
- Whether a "proposals-written" event exists (design should name this as a dependency, not
  assume it)

**Must be confirmed by runtime before companion UI can use:**
- Does the runtime emit a distinguishable event when proposals are written back to the vault
  (vs execution complete)? Design should propose what it needs; runtime may or may not have
  it.
- What is the write-back contract when a proposal is confirmed in companion UI? Does it check
  the vault checkbox and trigger a re-run, or does it route through a dedicated API endpoint?

### 5. Open questions

At minimum — each question must name a proposed default and an implicit owner doc:

1. **Panel surface placement** — is the Panel widget rendered inline with the active note
   (when the note contains a panel fence), or as a persistent sidebar/overlay?
   *Proposed default:* inline with note, appearing when panel fence is detected in active
   document. *Owner:* `OVERLAY_GRAMMAR.md` / interaction surface spec.

2. **Companion UI → vault write-back** — when the human confirms a proposal in companion UI,
   what is the exact write-back sequence? Check checkbox + re-trigger PanelAgent, or a
   separate confirm endpoint? *Proposed default:* dedicated confirm endpoint that marks the
   proposal as confirmed and triggers execution without requiring a note-save. *Owner:* runtime
   contract (new, to be defined).

3. **Run detection** — how does companion UI know a watcher-triggered panel run has started
   and completed? Polling `/api/status`? An event subscription? *Proposed default:* short-poll
   on active-note panel state while Panel widget is visible. *Owner:* runtime transport
   contract.

4. **Multi-panel notes** — a note may contain multiple AI panel fences. How does companion UI
   present them — a list, tabs, a single active-panel concept? *Proposed default:* list,
   rendered in document order, each with its own state. *Owner:* Panel surface spec.

5. **Proposal provenance depth** — how much provenance does the proposal row show at a glance
   vs. on expand? Catalog ID always; cognition mode (rule/LLM) always; full `llm_hint` on
   expand? *Proposed default:* catalog label + cognition mode badge always; expand for hint
   and confidence. *Owner:* this design.

### 6. Fixture gallery

Produce at minimum four rendered fixtures. The `no-match` fixture is the most important.

1. **`no-match`** — instruction ran; no catalog match; nothing in `AI-åtgärder`.
   Show: what the vault note looks like (AI status callout `⚠️`), and what companion UI
   renders (echoed instruction, reason, next-step affordance).

2. **`proposals-staged`** — three unchecked proposals written to `AI-åtgärder`.
   Show: vault Markdown side-by-side with companion UI proposal list.

3. **`receipt-displayed`** — two proposals confirmed and executed; AI status callout updated.
   Show: vault Markdown (executed items removed, callout updated), companion UI receipt strip.

4. **`blocked`** — write guard or policy prevented execution.
   Show: vault callout `⚠️` entry, companion UI blocked state with reason and recovery path.

---

## Non-goals

- A standalone Panel inbox surface (not bound to the active note)
- Bulk-accept or auto-accept affordances
- Any modification of the vault panel syntax or heading structure
- A new authority layer over which actions are allowed — that belongs to the action catalog
  and capability taxonomy docs (#981)
- Notification or alert mechanics (no badges, no push, no "unreviewed panels" count)
- Multi-user or collaboration affordances
- Runtime transport design — design names what it needs from the runtime; it does not specify
  the event or API contract
